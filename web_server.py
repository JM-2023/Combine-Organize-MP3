#!/usr/bin/env python3
"""
Audio Toolbox Web UI server (standard library only).

- Serves static files from ./webui
- Exposes JSON APIs under /api/*
- Runs one background task at a time using existing AudioProcessor logic
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from audio_models import FileState, ProcessingTask, TaskType
from audio_processor import AudioProcessor
from file_organizer import FileOrganizer
from file_presenter import FilePresenter


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return None
    raw = handler.rfile.read(length)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _path_is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _validate_rel_path(rel: str) -> Tuple[bool, str]:
    if not isinstance(rel, str) or not rel.strip():
        return False, "Empty path"
    p = Path(rel)
    if p.is_absolute():
        return False, "Absolute paths are not allowed"
    if ".." in p.parts:
        return False, "Path traversal is not allowed"
    return True, ""


def _open_chrome(url: str) -> bool:
    try:
        result = subprocess.run(
            ["open", "-a", "Google Chrome", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    try:
        return webbrowser.open(url)
    except Exception:
        return False


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _load_config_file() -> Dict[str, Any]:
    config_path = Path.cwd() / "config.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@dataclass
class PersistedState:
    version: int = 1
    settings: Dict[str, Any] = field(default_factory=lambda: {"timezone": "Asia/Shanghai", "max_workers": 4})

    @classmethod
    def load(cls, path: Path) -> "PersistedState":
        try:
            if not path.exists():
                return cls()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = cls()
            if isinstance(data, dict):
                state.version = int(data.get("version", 1) or 1)
                settings = data.get("settings", {})
                if isinstance(settings, dict):
                    tz = settings.get("timezone", state.settings["timezone"])
                    mw = settings.get("max_workers", state.settings["max_workers"])
                    state.settings["timezone"] = str(tz)
                    try:
                        state.settings["max_workers"] = int(mw)
                    except (TypeError, ValueError):
                        pass
            return state
        except Exception:
            return cls()

    def dump(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "settings": self.settings,
        }


@dataclass
class TaskRecord:
    task_id: str
    status: str  # running|done|error
    started_at: float
    finished_at: Optional[float] = None
    log: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log": self.log[-500:],  # cap payload size
            "result": self.result,
        }


class AudioToolboxApp:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.webui_dir = root_dir / "webui"
        self.state_path = Path.cwd() / ".audio_toolbox" / "state.json"

        self._lock = threading.RLock()
        self._base_config: Dict[str, Any] = _load_config_file()
        self._persisted = PersistedState.load(self.state_path)

        if not self.state_path.exists():
            default_tz = self._base_config.get("default_timezone", self._persisted.settings["timezone"])
            default_workers = self._base_config.get("max_workers", self._persisted.settings["max_workers"])
            self._persisted.settings["timezone"] = str(default_tz)
            try:
                self._persisted.settings["max_workers"] = int(default_workers)
            except (TypeError, ValueError):
                pass
            self._save_state()

        self.processor = AudioProcessor(self._base_config, max_workers=self._persisted.settings.get("max_workers", 4))
        self.organizer = FileOrganizer(self._persisted.settings.get("timezone", "Asia/Shanghai"))

        # Session-only merged state (matches desktop behavior: resets on restart)
        self._session_merged_files: Set[str] = set()

        self._tasks: Dict[str, TaskRecord] = {}
        self._current_task_id: Optional[str] = None

        self._files_cache: Dict[str, Any] = {"groups": [], "stale": True, "generated_at": 0.0}
        self._refresh_files_cache(force=True)

    def settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._persisted.settings)

    def busy(self) -> bool:
        with self._lock:
            if not self._current_task_id:
                return False
            rec = self._tasks.get(self._current_task_id)
            return bool(rec and rec.status == "running")

    def current_task(self) -> Optional[TaskRecord]:
        with self._lock:
            if not self._current_task_id:
                return None
            return self._tasks.get(self._current_task_id)

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def _save_state(self) -> None:
        _atomic_write_json(self.state_path, self._persisted.dump())

    def set_settings(self, timezone: str, max_workers: int) -> None:
        with self._lock:
            self._persisted.settings["timezone"] = str(timezone)
            self._persisted.settings["max_workers"] = int(max_workers)
            self.processor.max_workers = int(max_workers)
            self.organizer = FileOrganizer(str(timezone))
            self._save_state()
            if not self.busy():
                self._refresh_files_cache(force=True)

    def find_obs_location(self) -> Optional[str]:
        path = self.processor.find_obs_save_location()
        return str(path) if path else None

    def _restore_session_merged_states(self) -> None:
        cwd = Path.cwd()
        by_abs: Dict[Path, Any] = {f.path.resolve(): f for f in self.processor.library.files}
        for rel in self._session_merged_files:
            ok, _ = _validate_rel_path(rel)
            if not ok:
                continue
            abs_path = (cwd / rel).resolve()
            file_obj = by_abs.get(abs_path)
            if file_obj:
                self.processor.library.update_state(file_obj, FileState.MERGED)

    def _file_to_json(self, f) -> Dict[str, Any]:
        cwd = Path.cwd()
        try:
            rel = f.path.resolve().relative_to(cwd.resolve()).as_posix()
        except Exception:
            rel = f.path.name
        presented = FilePresenter.present(f)
        size_bytes = int(getattr(f, "size", 0) or 0)
        return {
            "path": rel,
            "timestamp": f.timestamp.isoformat(),
            "is_audio": bool(f.is_audio),
            "is_video": bool(f.is_video),
            "size_bytes": size_bytes,
            "display": presented.get("display"),
            "time": presented.get("time"),
            "state": presented.get("state"),
            "size": presented.get("size"),
            "style": presented.get("style"),
            "checkable": bool(presented.get("checkable")),
            "disabled": bool(presented.get("disabled")),
        }

    def _refresh_files_cache(self, *, force: bool = False) -> None:
        with self._lock:
            if self.busy() and not force:
                return

            self.processor.scan_directory(Path.cwd())
            self._restore_session_merged_states()

            files = self.organizer.prepare_files(self.processor.library.files)
            groups = self.organizer.group_files(files)

            payload_groups = []
            for g in groups:
                payload_groups.append(
                    {
                        "date_key": g.date_key,
                        "display_date": g.display_date.strftime("%Y-%m-%d"),
                        "color": g.color,
                        "files": [self._file_to_json(f) for f in g.files],
                    }
                )

            self._files_cache = {
                "groups": payload_groups,
                "stale": False,
                "generated_at": time.time(),
                "timezone": self._persisted.settings.get("timezone", "Asia/Shanghai"),
            }

    def get_files_payload(self) -> Dict[str, Any]:
        with self._lock:
            if not self.busy():
                self._refresh_files_cache()
            else:
                self._files_cache = dict(self._files_cache)
                self._files_cache["stale"] = True
            return dict(self._files_cache)

    def _audio_files_from_paths(self, rel_paths: List[str]) -> Tuple[List[Any], Optional[str]]:
        cwd = Path.cwd().resolve()
        by_abs = {f.path.resolve(): f for f in self.processor.library.files}

        files = []
        for rel in rel_paths:
            ok, err = _validate_rel_path(rel)
            if not ok:
                return [], f"Invalid path: {rel} ({err})"
            abs_path = (cwd / rel).resolve()
            if not _path_is_within(cwd, abs_path):
                return [], f"Invalid path (outside cwd): {rel}"
            if abs_path not in by_abs:
                return [], f"File not found in library: {rel}"
            files.append(by_abs[abs_path])
        return files, None

    def _selectable_files_from_paths(self, rel_paths: List[str]) -> Tuple[List[Any], Optional[str]]:
        files, err = self._audio_files_from_paths(rel_paths)
        if err:
            return [], err
        selectable = []
        for f in files:
            presented = FilePresenter.present(f)
            if not presented.get("checkable") or presented.get("disabled"):
                return [], f"File is not selectable (disabled in UI): {f.path.name}"
            selectable.append(f)
        return selectable, None

    def start_task(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        with self._lock:
            if self.busy():
                return HTTPStatus.CONFLICT, {"error": "Busy", "message": "A task is already running"}

            task_type = str(payload.get("type") or "").strip().upper()
            paths = payload.get("paths") or []
            params = payload.get("params") or {}
            if not isinstance(paths, list):
                paths = []
            if not isinstance(params, dict):
                params = {}

            self._refresh_files_cache(force=True)

            try:
                task_enum = TaskType[task_type] if task_type in TaskType.__members__ else None
            except Exception:
                task_enum = None

            task: Optional[ProcessingTask] = None

            if task_type == "MERGE_BY_DATE":
                date_key = str(params.get("date_key") or "").strip()
                if not date_key:
                    return HTTPStatus.BAD_REQUEST, {"error": "Missing date_key"}
                task = self.processor.create_merge_task_for_date(date_key, Path.cwd())
                if not task:
                    adjusted_files = []
                    for f in self.processor.library.files:
                        if f.state != FileState.UNPROCESSED:
                            continue
                        adjusted = self.organizer.timezone_adapter.get_adjusted_date(f.timestamp).strftime("%Y-%m-%d")
                        if adjusted == date_key and f.is_audio:
                            adjusted_files.append(f)
                    if adjusted_files:
                        task = ProcessingTask(task_type=TaskType.MERGE, files=sorted(adjusted_files, key=lambda x: x.timestamp), output_dir=Path.cwd())
                if not task:
                    return HTTPStatus.BAD_REQUEST, {"error": "No files", "message": f"No unmerged files for {date_key}"}
            elif task_enum == TaskType.IMPORT:
                source_dir = str(params.get("source_dir") or "").strip()
                if not source_dir:
                    return HTTPStatus.BAD_REQUEST, {"error": "Missing source_dir"}
                source_path = Path(source_dir)
                if not source_path.exists() or not source_path.is_dir():
                    return HTTPStatus.BAD_REQUEST, {"error": "Invalid source_dir", "message": "Directory does not exist"}
                task = ProcessingTask(task_type=TaskType.IMPORT, files=[], output_dir=Path.cwd(), params={"source_dir": source_dir})
            elif task_enum in {TaskType.CONVERT, TaskType.MERGE, TaskType.REMOVE_SILENCE}:
                rel_paths = [str(p) for p in paths if isinstance(p, str)]
                files, err = self._selectable_files_from_paths(rel_paths)
                if err:
                    return HTTPStatus.BAD_REQUEST, {"error": "Invalid paths", "message": err}

                if task_enum == TaskType.CONVERT:
                    files = [f for f in files if f.is_video]
                    if not files:
                        return HTTPStatus.BAD_REQUEST, {"error": "No videos selected"}
                    task = ProcessingTask(task_type=TaskType.CONVERT, files=files, output_dir=Path.cwd())
                elif task_enum == TaskType.MERGE:
                    files = [f for f in files if f.is_audio]
                    task = ProcessingTask(task_type=TaskType.MERGE, files=files, output_dir=Path.cwd())
                else:
                    files = [f for f in files if f.is_audio]
                    if not files:
                        return HTTPStatus.BAD_REQUEST, {"error": "No audio selected"}
                    threshold = params.get("threshold", "-55dB")
                    duration = params.get("duration", 0.1)
                    task = ProcessingTask(
                        task_type=TaskType.REMOVE_SILENCE,
                        files=files,
                        output_dir=Path.cwd(),
                        params={"threshold": threshold, "duration": duration},
                    )
            elif task_enum == TaskType.ORGANIZE:
                create_archive = bool(params.get("create_archive", True))
                task = ProcessingTask(
                    task_type=TaskType.ORGANIZE,
                    files=list(self.processor.library.files),
                    output_dir=Path.cwd(),
                    params={"create_archive": create_archive},
                )
            else:
                return HTTPStatus.BAD_REQUEST, {"error": "Unknown task type"}

            task_id = str(uuid.uuid4())
            record = TaskRecord(task_id=task_id, status="running", started_at=time.time(), log=[])
            self._tasks[task_id] = record
            self._current_task_id = task_id

            thread = threading.Thread(
                target=self._run_task_thread,
                args=(task_id, task),
                daemon=True,
            )
            thread.start()
            return HTTPStatus.OK, {"task_id": task_id}

    def _run_task_thread(self, task_id: str, task: ProcessingTask) -> None:
        def progress(msg: str) -> None:
            with self._lock:
                rec = self._tasks.get(task_id)
                if not rec or rec.status != "running":
                    return
                rec.log.append(str(msg))

        try:
            result = self.processor.process_task(task, progress_callback=progress)
            with self._lock:
                rec = self._tasks.get(task_id)
                if not rec:
                    return

                if result.success:
                    rec.status = "done"
                    rec.result = {
                        "success": True,
                        "processed_count": result.processed_count,
                        "output_files": [str(p) for p in (result.output_files or [])],
                    }

                    if task.task_type == TaskType.MERGE:
                        cwd = Path.cwd().resolve()
                        for f in task.files:
                            try:
                                rel = f.path.resolve().relative_to(cwd).as_posix()
                            except Exception:
                                continue
                            ok, _ = _validate_rel_path(rel)
                            if ok:
                                self._session_merged_files.add(rel)
                else:
                    rec.status = "error"
                    rec.result = {"success": False, "error": result.error}
                    if result.error:
                        rec.log.append(f"ERROR: {result.error}")

                rec.finished_at = time.time()
                self._refresh_files_cache(force=True)
        except Exception as e:
            with self._lock:
                rec = self._tasks.get(task_id)
                if rec:
                    rec.status = "error"
                    rec.finished_at = time.time()
                    rec.log.append(f"ERROR: {e}")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AudioToolboxWeb/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep terminal output clean (only important server prints)
        return

    @property
    def app(self) -> AudioToolboxApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"

        if path.startswith("/api/"):
            self._handle_api_get(path)
            return

        if path == "/":
            path = "/index.html"

        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        if not path.startswith("/api/"):
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not Found"})
            return

        body = None
        try:
            body = _read_json(self)
        except Exception:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        if path == "/api/settings":
            if not isinstance(body, dict):
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid payload"})
                return
            tz = str(body.get("timezone") or "Asia/Shanghai")
            try:
                mw = int(body.get("max_workers") or 4)
            except (TypeError, ValueError):
                mw = 4
            mw = max(1, min(16, mw))
            self.app.set_settings(tz, mw)
            _json_response(self, HTTPStatus.OK, {"ok": True, "settings": self.app.settings()})
            return

        if path == "/api/task":
            if not isinstance(body, dict):
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid payload"})
                return
            status, payload = self.app.start_task(body)
            _json_response(self, status, payload)
            return

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not Found"})

    def _handle_api_get(self, path: str) -> None:
        if path == "/api/state":
            rec = self.app.current_task()
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "cwd": str(Path.cwd()),
                    "settings": self.app.settings(),
                    "busy": self.app.busy(),
                    "current_task": rec.to_json() if rec else None,
                },
            )
            return

        if path == "/api/files":
            payload = self.app.get_files_payload()
            _json_response(self, HTTPStatus.OK, payload)
            return

        if path == "/api/obs_location":
            _json_response(self, HTTPStatus.OK, {"path": self.app.find_obs_location()})
            return

        if path == "/api/task/current":
            rec = self.app.current_task()
            _json_response(self, HTTPStatus.OK, rec.to_json() if rec else {"task_id": None})
            return

        if path.startswith("/api/task/"):
            task_id = path.split("/api/task/", 1)[1].strip()
            rec = self.app.get_task(task_id)
            if not rec:
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not Found"})
                return
            _json_response(self, HTTPStatus.OK, rec.to_json())
            return

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not Found"})

    def _serve_static(self, url_path: str) -> None:
        rel = url_path.lstrip("/")
        file_path = (self.app.webui_dir / rel).resolve()
        if not _path_is_within(self.app.webui_dir.resolve(), file_path):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        ctype, _ = mimetypes.guess_type(str(file_path))
        if not ctype:
            ctype = "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text/") else ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audio Toolbox Web UI server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent
    app = AudioToolboxApp(root_dir)

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    server.app = app  # type: ignore[attr-defined]

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"

    print("Audio Toolbox Web UI")
    print(f"Serving: {url}")
    print(f"CWD: {Path.cwd()}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        _open_chrome(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
