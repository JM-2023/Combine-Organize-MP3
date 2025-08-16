#!/usr/bin/env python3
"""
Core audio processing engine.
Single dispatcher, no special cases.
"""
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable, Dict, Any
import re

from audio_models import (
    AudioFile, FileState, TaskType, ProcessingTask, 
    TaskResult, AudioLibrary
)
from external_tools import ToolManager


class AudioProcessor:
    """Main processing engine - handles all operations uniformly"""
    
    def __init__(self, config: dict = None, max_workers: int = 4):
        self.config = config or {}
        self.max_workers = max_workers
        self.tools = ToolManager(config)
        self.library = AudioLibrary()
        
        # Single dispatcher for all task types
        self._task_handlers = {
            TaskType.IMPORT: self._import_files,
            TaskType.CONVERT: self._convert_files,
            TaskType.MERGE: self._merge_files,
            TaskType.REMOVE_SILENCE: self._remove_silence,
            TaskType.ORGANIZE: self._organize_files,
        }
        
        # File detection patterns
        self.date_pattern = re.compile(
            self.config.get('date_pattern', r'(\d{4}-\d{2}-\d{2})[_ ](\d{2}-\d{2}(?:-\d{2})?)')
        )
        
        # Pattern for merged output files: YYYYMMDD HH-MM.mp3
        self.merged_output_pattern = re.compile(r'^(\d{8}) (\d{2}-\d{2})\.mp3$')
    
    def find_obs_save_location(self) -> Optional[Path]:
        """Find OBS default save location on macOS"""
        home = Path.home()
        possible_locations = [
            home / "Movies",  # Default macOS Movies folder
            home / "Videos",  # Alternative
            home / "Documents" / "OBS",  # Some users configure this
            home / "Desktop",  # Some users save to desktop
        ]
        
        # Check if any of these exist and contain MP4 files
        for location in possible_locations:
            if location.exists():
                try:
                    mp4_files = list(location.glob('*.mp4'))
                    if mp4_files:
                        logging.info(f"Found OBS recordings in: {location}")
                        return location
                except Exception as e:
                    logging.warning(f"Error checking {location}: {e}")
        
        logging.info("No OBS recordings found in common locations")
        return None
    
    def scan_directory(self, directory: Path = None) -> None:
        """Scan directory and populate library"""
        scan_dir = directory or Path.cwd()
        self.library.clear()
        
        # Scan for audio and video files
        patterns = ['*.mp3', '*.mp4', '*.wav', '*.m4a', '*.flac', '*.ogg', '*.avi', '*.mov', '*.mkv']
        for pattern in patterns:
            for file_path in scan_dir.glob(pattern):
                if file_path.is_file():
                    audio_file = self._create_audio_file(file_path)
                    if audio_file:
                        self.library.add(audio_file)
        
        logging.info(f"Found {len(self.library.files)} media files")
    
    def _create_audio_file(self, path: Path) -> Optional[AudioFile]:
        """Create AudioFile from path, extracting metadata"""
        try:
            # Check if this is a merged output file
            merged_match = self.merged_output_pattern.match(path.name)
            if merged_match:
                # Parse merged output filename: YYYYMMDD HH-MM.mp3
                date_str = merged_match.group(1)
                time_str = merged_match.group(2).replace('-', ':')
                timestamp = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M")
                
                audio_file = AudioFile.from_path(path, timestamp)
                # Mark as merged output
                audio_file.state = FileState.MERGED_OUTPUT
                return audio_file
            
            # Extract timestamp from regular filename
            match = self.date_pattern.search(path.name)
            if match:
                date_str = match.group(1)
                time_str = match.group(2).replace('-', ':')
                timestamp = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            else:
                timestamp = None  # Let factory method use file mtime
            
            return AudioFile.from_path(path, timestamp)
        except Exception as e:
            logging.warning(f"Failed to create AudioFile for {path}: {e}")
            return None
    
    def process_task(self, task: ProcessingTask, 
                    progress_callback: Optional[Callable] = None) -> TaskResult:
        """Process any task through the unified dispatcher"""
        handler = self._task_handlers.get(task.task_type)
        if not handler:
            return TaskResult(task=task, success=False, 
                            error=f"Unknown task type: {task.task_type}")
        
        # Update file states
        for file in task.files:
            self.library.update_state(file, FileState.PROCESSING)
        
        try:
            # Execute the handler
            result = handler(task, progress_callback)
            
            # Update states based on result
            new_state = FileState.PROCESSED if result.success else FileState.FAILED
            for file in task.files:
                self.library.update_state(file, new_state)
            
            return result
        except Exception as e:
            logging.error(f"Task {task.task_type} failed: {e}")
            for file in task.files:
                self.library.update_state(file, FileState.FAILED)
            return TaskResult(task=task, success=False, error=str(e))
    
    def _import_files(self, task: ProcessingTask, 
                     progress_callback: Optional[Callable] = None) -> TaskResult:
        """Import files from OBS or other sources"""
        source_dir = task.params.get('source_dir')
        
        # Auto-detect OBS location if not provided
        if not source_dir:
            source_dir = self.find_obs_save_location()
            if not source_dir:
                return TaskResult(
                    task=task,
                    success=False,
                    error="No OBS recordings found in common locations"
                )
        else:
            source_dir = Path(source_dir)
        
        output_dir = task.output_dir
        
        if progress_callback:
            progress_callback(f"Importing from: {source_dir}")
        
        imported = []
        for file_path in source_dir.glob('*.mp4'):
            dest_path = output_dir / file_path.name
            try:
                file_path.rename(dest_path)
                imported.append(dest_path)
                if progress_callback:
                    progress_callback(f"Imported: {file_path.name}")
            except Exception as e:
                logging.error(f"Failed to import {file_path}: {e}")
        
        return TaskResult(
            task=task,
            success=len(imported) > 0,
            output_files=imported,
            processed_count=len(imported)
        )
    
    def _convert_files(self, task: ProcessingTask,
                      progress_callback: Optional[Callable] = None) -> TaskResult:
        """Convert files to MP3 format"""
        if not self.tools.has_ffmpeg:
            return TaskResult(task=task, success=False, error="FFmpeg not available")
        
        output_files = []
        processed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for audio_file in task.files:
                if audio_file.format != 'mp3':
                    output_path = task.output_dir / f"{audio_file.path.stem}.mp3"
                    future = executor.submit(self.tools.convert_to_mp3, 
                                           audio_file.path, output_path)
                    futures[future] = (audio_file, output_path)
            
            for future in as_completed(futures):
                audio_file, output_path = futures[future]
                try:
                    success = future.result()
                    if success:
                        output_files.append(output_path)
                        processed += 1
                        # Mark original file as converted
                        self.library.update_state(audio_file, FileState.CONVERTED)
                        # Create new AudioFile for the converted MP3
                        converted_file = AudioFile.from_path(output_path, audio_file.timestamp)
                        converted_file.source_file = audio_file.path
                        self.library.add(converted_file)
                        if progress_callback:
                            progress_callback(f"Converted: {audio_file.basename}")
                except Exception as e:
                    logging.error(f"Conversion failed for {audio_file.path}: {e}")
        
        return TaskResult(
            task=task,
            success=processed > 0,
            output_files=output_files,
            processed_count=processed
        )
    
    def _merge_files(self, task: ProcessingTask,
                    progress_callback: Optional[Callable] = None) -> TaskResult:
        """Merge audio files chronologically"""
        if not self.tools.has_ffmpeg:
            return TaskResult(task=task, success=False, error="FFmpeg not available")
        
        if not task.files:
            return TaskResult(task=task, success=False, error="No files to merge")
        
        # Sort files chronologically
        sorted_files = sorted(task.files, key=lambda f: f.timestamp)
        
        # Generate output filename: YYYYMMDD HH-MM.mp3
        # Use the date and start time from the first file
        first_time = sorted_files[0].timestamp
        output_name = f"{first_time.strftime('%Y%m%d %H-%M')}.mp3"
        output_path = task.output_dir / output_name
        
        if progress_callback:
            progress_callback(f"Merging {len(sorted_files)} files...")
        
        # Merge using FFmpeg
        input_paths = [f.path for f in sorted_files]
        success = self.tools.merge_audio_files(input_paths, output_path)
        
        if success:
            # Mark source files as merged
            for f in sorted_files:
                self.library.update_state(f, FileState.MERGED)
        
        return TaskResult(
            task=task,
            success=success,
            output_files=[output_path] if success else [],
            processed_count=len(sorted_files) if success else 0
        )
    
    def _remove_silence(self, task: ProcessingTask,
                       progress_callback: Optional[Callable] = None) -> TaskResult:
        """Remove silence from audio files"""
        if not self.tools.has_ffmpeg:
            return TaskResult(task=task, success=False, error="FFmpeg not available")
        
        output_files = []
        processed = 0
        
        # Get silence parameters (using original working values)
        threshold = task.params.get('threshold', '-55dB')
        duration = task.params.get('duration', 0.1)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for audio_file in task.files:
                output_path = task.output_dir / f"nosilence_{audio_file.path.name}"
                future = executor.submit(self.tools.remove_silence,
                                       audio_file.path, output_path,
                                       threshold, duration)
                futures[future] = (audio_file, output_path)
            
            for future in as_completed(futures):
                audio_file, output_path = futures[future]
                try:
                    success = future.result()
                    if success:
                        output_files.append(output_path)
                        processed += 1
                        if progress_callback:
                            progress_callback(f"Processed: {audio_file.basename}")
                except Exception as e:
                    logging.error(f"Silence removal failed for {audio_file.path}: {e}")
        
        return TaskResult(
            task=task,
            success=processed > 0,
            output_files=output_files,
            processed_count=processed
        )
    
    def _organize_files(self, task: ProcessingTask,
                       progress_callback: Optional[Callable] = None) -> TaskResult:
        """Organize source files by date into folders and optionally create archives"""
        organized_dirs = []
        moved_count = 0
        
        # Filter out merged output files - only organize source files
        source_files = []
        for audio_file in task.files:
            # Skip merged output files (format: YYYYMMDD HH-MM.mp3)
            if self.merged_output_pattern.match(audio_file.path.name):
                if progress_callback:
                    progress_callback(f"Skipping merged output: {audio_file.basename}")
                continue
            # Skip files that are already marked as merged output
            if audio_file.state == FileState.MERGED_OUTPUT:
                continue
            source_files.append(audio_file)
        
        if not source_files:
            return TaskResult(
                task=task,
                success=False,
                error="No source files to organize (only merged outputs found)"
            )
        
        # Group source files by date (using filename date, 0:00 cutoff)
        files_by_date = {}
        for audio_file in source_files:
            # Use date_key which is based on filename date
            date_key = audio_file.date_key
            if date_key not in files_by_date:
                files_by_date[date_key] = []
            files_by_date[date_key].append(audio_file)
        
        # Process each date group
        for date_key, files in sorted(files_by_date.items()):
            # Sort files chronologically
            sorted_files = sorted(files, key=lambda f: f.timestamp)
            
            # Create directory with format: YYYYMMDD HH-MM (using first file's time)
            if sorted_files:
                first_time = sorted_files[0].timestamp
                folder_name = f"{first_time.strftime('%Y%m%d %H-%M')}"
                date_dir = task.output_dir / folder_name
                date_dir.mkdir(parents=True, exist_ok=True)
            else:
                continue
            
            # Move all source files to the date directory
            for file in sorted_files:
                try:
                    dest = date_dir / file.path.name
                    if progress_callback:
                        progress_callback(f"Moving {file.basename} to {folder_name}/")
                    file.path.rename(dest)
                    file.path = dest  # Update path in model
                    moved_count += 1
                except Exception as e:
                    logging.error(f"Failed to move {file.path}: {e}")
            
            if progress_callback:
                progress_callback(f"Organized {len(sorted_files)} files in {folder_name}/")
            
            organized_dirs.append(date_dir)
            
            # Create archive if requested  
            if task.params.get('create_archive', False) and self.tools.has_sevenzip:
                # Use folder name for archive
                archive_path = task.output_dir / f"{folder_name}.7z"
                if self.tools.create_archive(date_dir, archive_path):
                    if progress_callback:
                        progress_callback(f"Created archive: {archive_path.name}")
        
        return TaskResult(
            task=task,
            success=len(organized_dirs) > 0,
            output_files=organized_dirs,
            processed_count=moved_count
        )
    
    def create_merge_task_for_date(self, date_str: str, output_dir: Path = None) -> Optional[ProcessingTask]:
        """Create a merge task for all unmerged files on a date"""
        unmerged = self.library.get_unmerged_for_date(date_str)
        if not unmerged:
            return None
        
        return ProcessingTask(
            task_type=TaskType.MERGE,
            files=unmerged,
            output_dir=output_dir or Path.cwd()
        )