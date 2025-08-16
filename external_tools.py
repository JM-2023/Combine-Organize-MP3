#!/usr/bin/env python3
"""
External tool management. 
One place for FFmpeg/7-Zip, no scattered globals.
"""
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Tuple
import platform
import os


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
                '-y',  # Overwrite output
                str(output_file)
            ]
            result = self.run_ffmpeg(args)
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg conversion failed: {e}")
            return False
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
                '-y',
                str(output_file)
            ]
            result = self.run_ffmpeg(args)
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logging.error(f"Silence removal failed: {e}")
            return False
        except Exception as e:
            logging.error(f"Silence removal error: {e}")
            return False
    
    def merge_audio_files(self, input_files: List[Path], output_file: Path) -> bool:
        """Merge multiple audio files into one"""
        if not self.has_ffmpeg:
            logging.error("FFmpeg not available for merging")
            return False
        
        if not input_files:
            logging.error("No input files for merging")
            return False
        
        try:
            # Create concat list file
            list_file = output_file.parent / "concat_list.txt"
            with open(list_file, 'w') as f:
                for file in input_files:
                    # FFmpeg concat demuxer format
                    f.write(f"file '{file.absolute()}'\n")
            
            args = [
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-c', 'copy',
                '-y',
                str(output_file)
            ]
            result = self.run_ffmpeg(args)
            
            # Clean up temp file
            list_file.unlink(missing_ok=True)
            
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logging.error(f"Audio merge failed: {e}")
            return False
        except Exception as e:
            logging.error(f"Merge error: {e}")
            return False
        finally:
            # Ensure temp file is cleaned up
            if 'list_file' in locals():
                list_file.unlink(missing_ok=True)
    
    def create_archive(self, input_dir: Path, output_file: Path) -> bool:
        """Create a 7z archive of a directory"""
        if not self.has_sevenzip:
            logging.error("7-Zip not available for archiving")
            return False
        
        try:
            args = [
                'a',  # Add to archive
                '-t7z',  # 7z format
                '-mx=5',  # Compression level
                str(output_file),
                str(input_dir / '*')
            ]
            result = self.run_sevenzip(args)
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logging.error(f"Archive creation failed: {e}")
            return False
        except Exception as e:
            logging.error(f"Archive error: {e}")
            return False