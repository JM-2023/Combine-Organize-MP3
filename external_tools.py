#!/usr/bin/env python3
"""
External tool management. 
One place for FFmpeg/7-Zip, no scattered globals.
"""
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, List
import platform
import os
import zipfile


class ToolManager:
    """Manages external tool paths and execution"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self._ffmpeg_path = None
        self._sevenzip_path = None
        self._validate_tools()
    
    def _validate_tools(self):
        """Find and validate external tools once"""
        self._ffmpeg_path = self._find_tool('ffmpeg', self.config.get('ffmpeg_path'))
        self._sevenzip_path = self._find_tool('7z', self.config.get('sevenzip_path'))
    
    def _find_tool(self, tool_name: str, config_path: Optional[str] = None) -> Optional[Path]:
        """Find a tool using a simple precedence order"""
        # 1. Config path
        if config_path:
            path = Path(config_path)
            if path.exists() and os.access(path, os.X_OK):
                logging.info(f"Found {tool_name} from config: {path}")
                return path
        
        # 2. System PATH
        system_path = shutil.which(tool_name)
        if system_path:
            logging.info(f"Found {tool_name} in PATH: {system_path}")
            return Path(system_path)
        
        # 3. Common locations (platform-specific)
        if platform.system() == "Darwin":  # macOS
            common_paths = [
                f"/usr/local/bin/{tool_name}",
                f"/opt/homebrew/bin/{tool_name}",
            ]
        elif platform.system() == "Linux":
            common_paths = [
                f"/usr/bin/{tool_name}",
                f"/usr/local/bin/{tool_name}",
            ]
        else:  # Windows
            common_paths = [
                Path.cwd() / f"{tool_name}.exe",
            ]
        
        for path_str in common_paths:
            path = Path(path_str)
            if path.exists() and os.access(path, os.X_OK):
                logging.info(f"Found {tool_name} at: {path}")
                return path
        
        logging.warning(f"{tool_name} not found")
        return None
    
    @property
    def has_ffmpeg(self) -> bool:
        return self._ffmpeg_path is not None
    
    @property
    def has_sevenzip(self) -> bool:
        return self._sevenzip_path is not None

    def preferred_archive_suffix(self) -> str:
        """Preferred archive suffix based on config and available tools."""
        configured = str(self.config.get('archive_format', '')).strip().lower()
        if configured in {"7z", ".7z"}:
            if self.has_sevenzip:
                return ".7z"
            logging.warning("archive_format=7z requested but 7-Zip not found; falling back to .zip")
        return ".zip"
    
    def run_ffmpeg(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run FFmpeg with given arguments"""
        if not self.has_ffmpeg:
            raise RuntimeError("FFmpeg not available")
        
        cmd = [str(self._ffmpeg_path)] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    
    def run_sevenzip(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run 7-Zip with given arguments"""
        if not self.has_sevenzip:
            raise RuntimeError("7-Zip not available")
        
        cmd = [str(self._sevenzip_path)] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def _ffmpeg_error_tail(self, result: subprocess.CompletedProcess, max_lines: int = 3) -> str:
        """Return a short, useful FFmpeg stderr tail for logs."""
        stderr = (result.stderr or "").strip()
        if not stderr:
            return "no stderr output"
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        if not lines:
            return "no stderr output"
        return " | ".join(lines[-max_lines:])

    def _cleanup_partial_output(self, output_file: Path) -> None:
        """Best-effort cleanup of partial outputs produced by failed FFmpeg runs."""
        try:
            if output_file.exists():
                output_file.unlink()
        except Exception as e:
            logging.warning(f"Failed to clean up partial output {output_file}: {e}")
    
    def convert_to_mp3(self, input_file: Path, output_file: Path) -> bool:
        """Convert any audio/video file to MP3"""
        if not self.has_ffmpeg:
            logging.error("FFmpeg not available for conversion")
            return False
        
        try:
            args = [
                '-i', str(input_file),
                '-acodec', 'libmp3lame',
                '-ab', '192k',
                '-n',  # Never overwrite existing output
                str(output_file)
            ]
            result = self.run_ffmpeg(args, check=False)
            if result.returncode != 0:
                logging.error(
                    f"FFmpeg conversion failed ({input_file.name}): {self._ffmpeg_error_tail(result)}"
                )
                return False
            return True
        except Exception as e:
            logging.error(f"Conversion error: {e}")
            return False
    
    def remove_silence(self, input_file: Path, output_file: Path, 
                      threshold: str = "-55dB", duration: float = 0.1) -> bool:
        """Remove silence from audio file"""
        if not self.has_ffmpeg:
            logging.error("FFmpeg not available for silence removal")
            return False
        
        try:
            # Use simple silenceremove filter (matches original working implementation)
            filter_str = f"silenceremove=stop_periods=-1:stop_duration={duration}:stop_threshold={threshold}"
            
            args = [
                '-i', str(input_file),
                '-af', filter_str,
                '-n',
                str(output_file)
            ]
            result = self.run_ffmpeg(args, check=False)
            if result.returncode != 0:
                logging.error(
                    f"Silence removal failed ({input_file.name}): {self._ffmpeg_error_tail(result)}"
                )
                return False
            return True
        except Exception as e:
            logging.error(f"Silence removal error: {e}")
            return False
    
    def merge_audio_files(self, input_files: List[Path], output_file: Path) -> bool:
        """Merge multiple audio files into one.

        Strategy:
        1) Fast path: concat demuxer + stream copy (no re-encode).
        2) Fallback: concat demuxer + MP3 re-encode for mixed/incompatible inputs.
        """
        if not self.has_ffmpeg:
            logging.error("FFmpeg not available for merging")
            return False
        
        if not input_files:
            logging.error("No input files for merging")
            return False
        
        try:
            # Create concat list file
            list_file = output_file.parent / "concat_list.txt"
            with open(list_file, 'w', encoding='utf-8') as f:
                for file in input_files:
                    # FFmpeg concat demuxer format
                    f.write(f"file '{file.absolute()}'\n")

            copy_args = [
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-vn',
                '-c', 'copy',
                '-n',
                str(output_file)
            ]
            copy_result = self.run_ffmpeg(copy_args, check=False)
            if copy_result.returncode == 0:
                return True

            logging.warning(
                "Merge copy mode failed (%s): %s",
                output_file.name,
                self._ffmpeg_error_tail(copy_result),
            )
            self._cleanup_partial_output(output_file)

            # Fallback: decode + re-encode to improve compatibility.
            reencode_args = [
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-vn',
                '-acodec', 'libmp3lame',
                '-ab', '192k',
                '-ar', '44100',
                '-ac', '2',
                '-n',
                str(output_file)
            ]
            reencode_result = self.run_ffmpeg(reencode_args, check=False)
            if reencode_result.returncode == 0:
                logging.info(f"Merge succeeded using re-encode fallback: {output_file.name}")
                return True

            logging.error(
                "Merge failed after fallback (%s): %s",
                output_file.name,
                self._ffmpeg_error_tail(reencode_result),
            )
            self._cleanup_partial_output(output_file)
            return False
        except Exception as e:
            logging.error(f"Merge error: {e}")
            return False
        finally:
            # Ensure temp file is cleaned up
            if 'list_file' in locals():
                list_file.unlink(missing_ok=True)
    
    def create_archive(self, input_dir: Path, output_file: Path) -> bool:
        """Create an archive of a directory.

        - `.7z` uses 7-Zip if available
        - `.zip` uses Python's standard library (no external dependency)
        """
        suffix = output_file.suffix.lower()
        if suffix == ".7z":
            return self._create_7z_archive(input_dir, output_file)
        if suffix == ".zip":
            return self._create_zip_archive(input_dir, output_file)

        logging.error(f"Unsupported archive format: {output_file.suffix}")
        return False

    def _create_7z_archive(self, input_dir: Path, output_file: Path) -> bool:
        """Create a 7z archive of a directory"""
        if not self.has_sevenzip:
            logging.error("7-Zip not available for .7z archiving")
            return False

        try:
            args = [
                'a',  # Add to archive
                '-t7z',  # 7z format
                '-mx=5',  # Compression level
                '-y',  # Assume Yes on all queries
                str(output_file),
                str(input_dir / '*')
            ]
            result = self.run_sevenzip(args)
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logging.error(f"7z archive creation failed: {e}")
            return False
        except Exception as e:
            logging.error(f"7z archive error: {e}")
            return False

    def _create_zip_archive(self, input_dir: Path, output_file: Path) -> bool:
        """Create a zip archive containing the directory (including the root folder)."""
        try:
            input_dir = Path(input_dir)
            output_file = Path(output_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            root_parent = input_dir.parent
            with zipfile.ZipFile(output_file, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                for file_path in sorted(input_dir.rglob('*')):
                    if not file_path.is_file():
                        continue
                    arcname = file_path.relative_to(root_parent)
                    zipf.write(file_path, arcname.as_posix())

            return True
        except Exception as e:
            logging.error(f"Zip archive error: {e}")
            return False
