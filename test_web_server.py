import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from web_server import AudioToolboxApp, _build_open_url, _normalize_open_path, _resolve_static_request


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class WebServerFilesPayloadTests(unittest.TestCase):
    def test_files_payload_includes_matching_mp4_and_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-03-06 09-00.mp3").write_bytes(b"audio")
            (root / "2026-03-06 09-00.mp4").write_bytes(b"video")

            with working_directory(root):
                app = AudioToolboxApp(Path(__file__).resolve().parent)
                payload = app.get_files_payload()

        self.assertEqual(len(payload["groups"]), 1)
        files = payload["groups"][0]["files"]
        self.assertEqual(
            [file["path"] for file in files],
            ["2026-03-06 09-00.mp3", "2026-03-06 09-00.mp4"],
        )

        mp4_file = next(file for file in files if file["format"] == "mp4")
        self.assertTrue(mp4_file["is_video"])
        self.assertFalse(mp4_file["is_audio"])


class WebServerRoutingTests(unittest.TestCase):
    def test_root_resolves_to_modern_index(self):
        modern = Path("/tmp/modern")
        classic = Path("/tmp/classic")

        static_root, rel_path, redirect = _resolve_static_request(modern, classic, "/")

        self.assertEqual(static_root, modern)
        self.assertEqual(rel_path, "index.html")
        self.assertIsNone(redirect)

    def test_classic_root_redirects_to_trailing_slash(self):
        modern = Path("/tmp/modern")
        classic = Path("/tmp/classic")

        static_root, rel_path, redirect = _resolve_static_request(modern, classic, "/classic")

        self.assertIsNone(static_root)
        self.assertEqual(rel_path, "")
        self.assertEqual(redirect, "/classic/")

    def test_classic_assets_resolve_from_classic_directory(self):
        modern = Path("/tmp/modern")
        classic = Path("/tmp/classic")

        static_root, rel_path, redirect = _resolve_static_request(modern, classic, "/classic/styles.css")

        self.assertEqual(static_root, classic)
        self.assertEqual(rel_path, "styles.css")
        self.assertIsNone(redirect)

    def test_normalize_open_path_adds_leading_slash(self):
        self.assertEqual(_normalize_open_path("classic/"), "/classic/")

    def test_build_open_url_keeps_root_url_for_default_route(self):
        self.assertEqual(_build_open_url("http://127.0.0.1:9999/", "/"), "http://127.0.0.1:9999/")

    def test_build_open_url_appends_non_root_route(self):
        self.assertEqual(
            _build_open_url("http://127.0.0.1:9999/", "/classic/"),
            "http://127.0.0.1:9999/classic/",
        )


if __name__ == "__main__":
    unittest.main()
