#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import functools
import os
import sys
import re
import json
import logging
import subprocess
import shutil
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import platform
import traceback
# moviepy imports (still needed for MP3 merging)
from moviepy import concatenate_audioclips, AudioFileClip
# PyQt5 imports
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtWidgets import QGraphicsDropShadowEffect, QWidget
from PyQt5.QtGui import QPalette, QColor, QLinearGradient, QPainter, QBrush, QPen

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

# ----------------------------
# Configuration and Utility Functions
# ----------------------------
def load_config():
    """Load configuration from config.json"""
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning("Failed to load config.json: %s", e)
    return {}

config = load_config()

# Configuration defaults
DATE_TIME_REGEX = config.get("date_time_regex", r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
DEFAULT_DATE_FORMAT = config.get("default_date_format", "%Y-%m-%d")
DEFAULT_TIME_FORMAT = config.get("default_time_format", "%H-%M-%S")
OUTPUT_DIR = config.get("default_output_dir", None)  # If None, use current directory

# --- Enhanced FFmpeg Path Detection ---
_ffmpeg_path_to_use = None
# 1. Try from config.json
configured_ffmpeg_path = config.get("path_to_ffmpeg")
if configured_ffmpeg_path:
    if os.path.isfile(configured_ffmpeg_path) and os.access(configured_ffmpeg_path, os.X_OK):
        _ffmpeg_path_to_use = configured_ffmpeg_path
        logging.info(f"Using FFmpeg from config: {_ffmpeg_path_to_use}")
    else:
        logging.warning(f"FFmpeg path in config.json ('{configured_ffmpeg_path}') not found or not executable. Trying other methods.")

# 2. Try executable in script's directory
if not _ffmpeg_path_to_use:
    script_dir_ffmpeg_name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
    script_dir_ffmpeg_path = os.path.join(os.getcwd(), script_dir_ffmpeg_name)
    if os.path.isfile(script_dir_ffmpeg_path) and os.access(script_dir_ffmpeg_path, os.X_OK):
        _ffmpeg_path_to_use = script_dir_ffmpeg_path
        logging.info(f"Using FFmpeg from script directory: {_ffmpeg_path_to_use}")

# 3. For non-Windows, check common installation paths
if not _ffmpeg_path_to_use and platform.system() != "Windows":
    common_ffmpeg_paths = [
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg", # For Homebrew on Apple Silicon and Intel
        os.path.expanduser("~/.local/bin/ffmpeg") # Common user install path
    ]
    for p in common_ffmpeg_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            _ffmpeg_path_to_use = p
            logging.info(f"Found FFmpeg in common system path: {_ffmpeg_path_to_use}")
            break

# 4. Try finding in system PATH using shutil.which()
if not _ffmpeg_path_to_use:
    ffmpeg_exe_name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
    ffmpeg_exe_in_path = shutil.which(ffmpeg_exe_name)
    if ffmpeg_exe_in_path:
        _ffmpeg_path_to_use = ffmpeg_exe_in_path
        logging.info(f"Found FFmpeg in system PATH: {_ffmpeg_path_to_use}")

# 5. Final fallback (should ideally be covered by shutil.which if in PATH)
if not _ffmpeg_path_to_use:
    _ffmpeg_path_to_use = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
    logging.warning(f"FFmpeg not found by previous methods. "
                    f"Falling back to '{_ffmpeg_path_to_use}' and hoping it's in PATH. "
                    "Consider adding FFmpeg to PATH, placing it in the script directory, or setting 'path_to_ffmpeg' in config.json.")
PATH_TO_FFMPEG = _ffmpeg_path_to_use


# --- Enhanced 7-Zip Path Detection ---
_7zip_path_to_use = None
# 1. Try from config.json
configured_7zip_path = config.get("path_to_7zip")
if configured_7zip_path:
    if os.path.isfile(configured_7zip_path) and os.access(configured_7zip_path, os.X_OK):
        _7zip_path_to_use = configured_7zip_path
        logging.info(f"Using 7-Zip from config: {_7zip_path_to_use}")
    else:
        logging.warning(f"7-Zip path in config.json ('{configured_7zip_path}') not found or not executable. Trying other methods.")

# 2. Platform-specific defaults or PATH check
if not _7zip_path_to_use:
    if platform.system() == "Windows":
        common_windows_7zip_paths = [
            "C:\\Program Files\\7-Zip\\7z.exe",
            "C:\\Program Files (x86)\\7-Zip\\7z.exe"
        ]
        for p in common_windows_7zip_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                _7zip_path_to_use = p
                logging.info(f"Using 7-Zip from default Windows location: {_7zip_path_to_use}")
                break
        if not _7zip_path_to_use:
            seven_zip_in_path_windows = shutil.which("7z.exe") # Check PATH
            if seven_zip_in_path_windows:
                _7zip_path_to_use = seven_zip_in_path_windows
                logging.info(f"Found 7z.exe in system PATH (Windows): {_7zip_path_to_use}")
            else:
                _7zip_path_to_use = "7z.exe" # Fallback for Windows
                logging.warning("7-Zip not found in default Windows locations or PATH. "
                                f"Falling back to '7z.exe'. Zipping might fail or prompt in UI.")
    else: # macOS, Linux, etc.
        # Try common paths for non-Windows (often installed via package managers)
        common_other_7zip_paths = [
            "/usr/bin/7z",
            "/usr/local/bin/7z",
            "/opt/homebrew/bin/7z", # For Homebrew on macOS
            os.path.expanduser("~/.local/bin/7z")
        ]
        for p in common_other_7zip_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                _7zip_path_to_use = p
                logging.info(f"Found 7z in common system path (non-Windows): {_7zip_path_to_use}")
                break
        if not _7zip_path_to_use:
            seven_zip_in_path_other = shutil.which("7z") # Check PATH
            if seven_zip_in_path_other:
                _7zip_path_to_use = seven_zip_in_path_other
                logging.info(f"Found 7z in system PATH (non-Windows): {_7zip_path_to_use}")
            else:
                _7zip_path_to_use = "7z" # Fallback for non-Windows
                logging.warning(f"7z not found in common paths or system PATH (non-Windows). "
                                f"Falling back to '7z'. Zipping might fail or prompt in UI.")
PATH_TO_7ZIP = _7zip_path_to_use

# Set the max number of parallel tasks based on CPU cores
MAX_WORKERS = config.get("max_workers", min(32, (os.cpu_count() or 1) * 2 + 4))

# Ensure the output directory exists
current_directory = os.getcwd()
output_directory_path = OUTPUT_DIR if OUTPUT_DIR else current_directory
if not os.path.exists(output_directory_path):
    os.makedirs(output_directory_path, exist_ok=True)

def load_audio_clip(file_path): # Still used by MP3 merging
    """
    Load an audio clip from the given file path using moviepy.
    Returns the AudioFileClip if successful, otherwise returns None.
    """
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            logging.warning("File does not exist or is empty: %s", file_path)
            return None
        clip = AudioFileClip(file_path)
        if clip is None or clip.duration is None or clip.duration <= 0:
            logging.warning("Failed to load clip or clip has invalid duration: %s", file_path)
            if clip:
                clip.close()
            return None
        return clip
    except Exception as e:
        logging.error("Error loading clip %s: %s\n%s", file_path, e, traceback.format_exc())
        return None

date_time_pattern = re.compile(DATE_TIME_REGEX)
def parse_date_and_time_from_filename(filename):
    """Parse the date and time from the filename using the regex."""
    match = date_time_pattern.search(filename)
    if match:
        groups = match.groups()
        if len(groups) >= 2:
            date_str = groups[0]
            time_str = groups[1]
            # Check if the optional seconds part (group 3) was captured
            time_format_to_try = DEFAULT_TIME_FORMAT if len(groups) > 2 and groups[2] else "%H-%M"
            
            parsed_date = None
            parsed_time = None
            try:
                parsed_date = datetime.strptime(date_str, DEFAULT_DATE_FORMAT).date()
            except ValueError:
                logging.warning(f"Could not parse date '{date_str}' with format '{DEFAULT_DATE_FORMAT}' (from file: {filename})")
                return None, None
            try:
                parsed_time = datetime.strptime(time_str, time_format_to_try).time()
            except ValueError:
                # If the primary attempt failed, and it was using DEFAULT_TIME_FORMAT (implying seconds might be expected)
                # try parsing as HH-MM just in case the filename was missing seconds contrary to expectation.
                if time_format_to_try == DEFAULT_TIME_FORMAT and DEFAULT_TIME_FORMAT != "%H-%M": # Avoid re-trying if already %H-%M
                    try:
                        parsed_time = datetime.strptime(time_str, "%H-%M").time()
                    except ValueError:
                        logging.warning(f"Could not parse time '{time_str}' with format '{DEFAULT_TIME_FORMAT}' or '%H-%M' (from file: {filename})")
                        return None, None
                else: # If the initial try was already %H-%M or some other format, just log the failure for that.
                    logging.warning(f"Could not parse time '{time_str}' with format '{time_format_to_try}' (from file: {filename})")
                    return None, None
            return parsed_date, parsed_time
        else:
            logging.warning(f"Regex matched in filename '{filename}', but capture groups are insufficient.")
    else:
        logging.debug(f"Date/time pattern not found in filename '{filename}'.")
    return None, None

def parse_time_from_filename(filename):
    """Return a datetime combining the parsed date and time (or a minimal datetime if parsing fails)."""
    date, time = parse_date_and_time_from_filename(filename)
    if date and time:
        try:
            return datetime.combine(date, time)
        except Exception as e:
            logging.error(f"Error combining date {date} and time {time} (from file: {filename}): {e}")
            return datetime.min # Return earliest possible datetime on error for sorting
    return datetime.min # Return earliest possible datetime if parsing fails

# ----------------------------
# Merging Function for MP3 Files (uses MoviePy)
# ----------------------------
def process_files(files, output_dir_path, progress_callback=None):
    if not files:
        logging.warning("No files provided for processing.")
        return False, None

    try:
        # Sort files chronologically. This is crucial for correct merge order and naming.
        files.sort(key=lambda x: parse_time_from_filename(os.path.basename(x)))
    except TypeError as e:
        logging.error(f"Error sorting files, possibly due to invalid datetime parsing: {e}")
        return False, None

    # Note: 'files' now contains basenames, sorted.
    # We will load them using full paths, but keep track using basenames.

    if progress_callback:
        progress_callback(f"Loading {len(files)} audio files...")

    loaded_clip_data = {}  # Stores successfully loaded clips: {basename: clip_object}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Create futures, mapping them to the original basename for later retrieval
        future_to_basename = {
            executor.submit(load_audio_clip, os.path.join(current_directory, basename)): basename
            for basename in files
        }
        processed_count = 0
        for future in as_completed(future_to_basename):
            basename = future_to_basename[future]
            processed_count += 1
            if progress_callback:
                progress_callback(f"Loading {processed_count}/{len(files)} audio files (async)...")
            try:
                clip = future.result()
                if clip and clip.duration is not None and clip.duration > 0:
                    loaded_clip_data[basename] = clip
                elif clip:
                    logging.warning(f"Skipping file (invalid duration or loading issue): {basename}")
                    clip.close() # Close the invalid clip
                else:
                    logging.warning(f"Skipping file (load failed): {basename}")
            except Exception as e:
                # Log the error with the specific basename that caused it
                logging.error(f"An error occurred while loading/processing file {basename}: {e}\n{traceback.format_exc()}")

    # Reconstruct audio_clips and valid_files_for_merge in the originally sorted order
    audio_clips = []
    valid_files_for_merge = [] # List of basenames that were successfully loaded
    skipped_count = 0

    for basename_in_sorted_order in files: # Iterate through the *originally sorted* list of basenames
        if basename_in_sorted_order in loaded_clip_data:
            audio_clips.append(loaded_clip_data[basename_in_sorted_order])
            valid_files_for_merge.append(basename_in_sorted_order)
        else:
            # This file was in the input 'files' list but failed to load or was invalid.
            # Logging for this specific skip already happened inside the thread pool loop or by load_audio_clip.
            skipped_count += 1
            
    if not audio_clips:
        logging.warning("No valid audio clips found after attempting to load all selected files.")
        if progress_callback:
            progress_callback("No valid audio clips found.")
        # Clean up any clips that were loaded but not added to audio_clips (e.g., if process exits early)
        for clip_to_close in loaded_clip_data.values():
            # Check if it's not in audio_clips (though audio_clips is empty here)
            # This is more a safeguard for any loaded clips if the lists weren't populated
            try: 
                if clip_to_close not in audio_clips: # Defensive check
                    clip_to_close.close()
            except Exception: pass # Errors during close are less critical here
        return False, None

    if skipped_count > 0:
        logging.warning(f"Note: {skipped_count} file(s) were skipped due to loading errors or invalid duration.")
    
    # At this point, valid_files_for_merge contains basenames of successfully loaded files,
    # and audio_clips contains the corresponding clip objects, both in correct chronological order.

    # This check should ideally be redundant if 'if not audio_clips:' above is effective.
    if not valid_files_for_merge:
        logging.error("No files loaded successfully, cannot determine output filename.")
        # audio_clips would be empty here, so closing them is a no-op.
        # Clean up any clips in loaded_clip_data that might exist
        for clip_to_close in loaded_clip_data.values():
            try: clip_to_close.close()
            except Exception: pass
        return False, None

    # Determine output filename based on the *first successfully loaded file in chronological order*
    first_valid_clip_filename = valid_files_for_merge[0] 
    first_date, first_time = parse_date_and_time_from_filename(first_valid_clip_filename)

    if not first_date or not first_time:
        logging.error(f"Could not parse date/time from the first valid filename: {first_valid_clip_filename}")
        for c in audio_clips: c.close()
        # Also close clips in loaded_clip_data that might not be in audio_clips if something went wrong
        for basename, clip_obj in loaded_clip_data.items():
            if clip_obj not in audio_clips : # Defensive
                try: clip_obj.close()
                except: pass
        return False, None

    first_date_formatted = first_date.strftime('%Y%m%d')
    time_formatted = first_time.strftime('%H-%M') # Using %H-%M for output filename time consistently
    
    output_filename = f"{first_date_formatted} {time_formatted}.mp3"
    output_filename = re.sub(r'[\\/*?:"<>|]', '_', output_filename) # Sanitize filename
    output_path = os.path.join(output_dir_path, output_filename)

    total_duration = sum(clip.duration for clip in audio_clips)
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    
    logging.info(f"Merging {len(audio_clips)} valid files (from {len(files)} selected initially), total duration: {minutes}m {seconds}s. Output to: {output_filename}")
    if progress_callback:
        progress_callback(f"Merging {len(audio_clips)} audio clips ({minutes}m {seconds}s total)...")
    
    final_clip = None
    try:
        # Concatenate clips in the correct, sorted order
        final_clip = concatenate_audioclips(audio_clips)
        if progress_callback:
            progress_callback(f"Writing final audio file to {output_filename}...")
        
        # Use logger='bar' only if DEBUG logging is enabled for MoviePy's progress bar
        moviepy_logger = 'bar' if logging.getLogger().isEnabledFor(logging.DEBUG) else None
        final_clip.write_audiofile(output_path, codec='mp3', logger=moviepy_logger)
        
        logging.info(f"Merge complete! Output saved as: {output_path}")
        return True, output_path
    except Exception as e:
        logging.error("Error during merging or writing audio file: %s\n%s", e, traceback.format_exc())
        return False, None
    finally:
        # Close all individual clips that were part of audio_clips
        for c in audio_clips:
            try: c.close()
            except Exception as close_err: logging.warning(f"Error closing intermediate clip: {close_err}")
        
        # Close any other clips that were loaded but perhaps not added to audio_clips (defensive)
        # This ensures all clips from loaded_clip_data are attempted to be closed.
        for basename, clip_obj in loaded_clip_data.items():
            if clip_obj not in audio_clips and clip_obj != final_clip : # Avoid double-closing
                try: clip_obj.close()
                except Exception as close_err: logging.warning(f"Error closing a loaded_clip_data clip: {close_err}")

        if final_clip:
            try: final_clip.close()
            except Exception as close_err: logging.warning(f"Error closing final clip: {close_err}")

# ----------------------------
# Conversion Function: Convert MP4 to MP3 (uses FFmpeg directly)
# ----------------------------
def convert_mp4_to_mp3(args):
    video_file, progress_callback, index, total = args
    video_path = os.path.join(current_directory, video_file)
    audio_file_base = os.path.splitext(video_file)[0]
    audio_file = f"{audio_file_base}.mp3"
    output_path = os.path.join(current_directory, audio_file) # Output to current directory

    if not os.path.exists(video_path):
        logging.error(f"File not found, cannot convert: {video_path}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: File not found {video_file}")
        return False, video_file

    # FFmpeg availability should be checked by the calling worker (ConvertWorker)
    # before starting tasks. This function assumes PATH_TO_FFMPEG is valid.
    logging.info(f"Attempting conversion of {video_file} to MP3 using FFmpeg at {PATH_TO_FFMPEG}...")
    command = [
        PATH_TO_FFMPEG,
        "-y",  # Overwrite output file if it exists
        "-i", video_path,
        "-vn",  # No video output
        "-acodec", "mp3", # Explicitly set audio codec to MP3
        # Optional: Add audio quality parameters like:
        # "-b:a", "192k",    # Audio bitrate
        # "-ar", "44100",    # Audio sample rate
        # "-ac", "2",        # Number of audio channels
        output_path
    ]
    try:
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(command, check=False, capture_output=True, text=True,
                                encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        if result.returncode == 0:
            logging.info(f"FFmpeg successfully converted {video_file} to {output_path}")
            if progress_callback:
                progress_callback(f"Converted {index+1}/{total}: {video_file} -> {audio_file} (FFmpeg)")
            return True, video_file
        else:
            logging.error(f"FFmpeg failed to convert '{video_file}'. Return code: {result.returncode}")
            logging.error(f"FFmpeg command: {' '.join(command)}")
            logging.error(f"FFmpeg stdout: {result.stdout.strip() if result.stdout else 'N/A'}")
            logging.error(f"FFmpeg stderr: {result.stderr.strip() if result.stderr else 'N/A'}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total}: FFmpeg conversion failed for {video_file}")
            if os.path.exists(output_path): # Clean up potentially partial file
                try: os.remove(output_path)
                except OSError as rm_err: logging.warning(f"Could not delete failed FFmpeg output file {output_path}: {rm_err}")
            return False, video_file
    except FileNotFoundError:
        logging.error(f"FFmpeg executable not found at '{PATH_TO_FFMPEG}' when trying to convert {video_file}.\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: FFmpeg not found at '{PATH_TO_FFMPEG}' for {video_file}")
        return False, video_file
    except Exception as e_ffmpeg_execution:
        logging.error(f"Error during FFmpeg execution for {video_file}: {e_ffmpeg_execution}\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: FFmpeg execution crashed for {video_file}")
        return False, video_file

# ----------------------------
# Function to process a file for silence removal (uses FFmpeg)
# ----------------------------
def remove_silence_from_file(args):
    file, progress_callback, index, total = args
    try:
        input_file_path = os.path.join(current_directory, file)
        if not os.path.exists(input_file_path):
            logging.error(f"File not found, cannot remove silence: {input_file_path}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total}: File not found {file}")
            return False, file

        base, ext = os.path.splitext(file)
        safe_base = re.sub(r'[\\/*?:"<>|]', '_', base)
        output_filename = f"{safe_base}_nosilence{ext}"
        output_file_path = os.path.join(current_directory, output_filename)

        # Assumes PATH_TO_FFMPEG is valid and executable.
        command = [
            PATH_TO_FFMPEG,
            "-y", "-i", input_file_path,
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.1:stop_threshold=-55dB",
            output_file_path
        ]
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        
        result = subprocess.run(command, check=False, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
        
        if result.returncode != 0:
            logging.error(f"ffmpeg failed to remove silence from '{file}'. Return code: {result.returncode}")
            logging.error(f"FFmpeg command: {' '.join(command)}")
            logging.error(f"FFmpeg stdout: {result.stdout.strip() if result.stdout else 'N/A'}")
            logging.error(f"FFmpeg stderr: {result.stderr.strip() if result.stderr else 'N/A'}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total}: Processing failed {file}")
            if os.path.exists(output_file_path):
                try: os.remove(output_file_path)
                except OSError as rm_err: logging.warning(f"Could not delete failed output file {output_file_path}: {rm_err}")
            return False, file
        else:
            if progress_callback:
                progress_callback(f"Processed {index+1}/{total}: {file} -> {output_filename}")
            logging.info(f"Successfully removed silence from {file}, output as {output_filename}")
            return True, file
    except FileNotFoundError: # Specifically catch if PATH_TO_FFMPEG itself isn't found
        logging.error(f"FFmpeg executable not found at '{PATH_TO_FFMPEG}' when trying to remove silence from {file}.\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: FFmpeg not found at '{PATH_TO_FFMPEG}' for {file}")
        return False, file
    except Exception as e:
        logging.error(f"Unexpected error removing silence from {file}: {e}\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: Unexpected failure {file}")
        return False, file

# ----------------------------
# Function to process a date group for organization
# ----------------------------
def process_date_group(args):
    date_str, files_with_time, working_directory, progress_callback, index, total_dates = args
    try:
        files_with_time.sort(key=lambda item: item[0]) # Sort by time string HH-MM
        first_time_str = files_with_time[0][0]
        folder_name = f"{date_str} {first_time_str}" # Date YYYYMMDD, Time HH-MM
        folder_name = re.sub(r'[\\/*?:"<>|]', '_', folder_name) # Sanitize
        folder_path = os.path.join(working_directory, folder_name)

        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        elif not os.path.isdir(folder_path):
            logging.error(f"Cannot create folder, a file with the same name already exists: {folder_path}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total_dates}: Cannot create folder {folder_name}")
            return date_str, None, False # Indicate failure but allow others to proceed

        moved_count = 0
        error_count = 0
        for time_str, filename in files_with_time:
            source_path = os.path.join(working_directory, filename)
            dest_path = os.path.join(folder_path, filename)
            if not os.path.exists(source_path): # File might have been moved/deleted by another process
                logging.warning(f"Source file not found, skipping move: {source_path}")
                error_count += 1
                continue
            try:
                shutil.move(source_path, dest_path)
                moved_count += 1
            except Exception as e:
                logging.error(f"Error moving file {filename} to {folder_path}: {e}")
                error_count += 1
        
        if progress_callback:
            status_msg = f"Organized folder {index+1}/{total_dates}: {folder_name} ({moved_count} files)"
            if error_count > 0:
                status_msg += f" ({error_count} errors)"
            progress_callback(status_msg)
        
        logging.info(f"Organized folder {folder_name}, moved {moved_count} files with {error_count} errors.")
        return date_str, folder_path, True # Return success and path for zipping
    except Exception as e:
        logging.error(f"Error processing date group {date_str}: {e}\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total_dates}: Failed processing date group {date_str}")
        return date_str, None, False # Indicate failure

# ----------------------------
# Function to create a ZIP archive
# ----------------------------
def create_zip_archive(args):
    folder_name, folder_path, path_to_7zip_exe_arg, working_directory, progress_callback, index, total = args
    try:
        if not os.path.isdir(folder_path):
            logging.error(f"Source folder not found, cannot create ZIP: {folder_path}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total}: Folder not found {folder_name}")
            return folder_name, False

        zip_name = f"{folder_name}.zip"
        zip_path = os.path.join(working_directory, zip_name) # Place zip in the parent (current_directory)
        
        # path_to_7zip_exe_arg is the one determined by MainWindow.organizeFiles,
        # which could be from config, auto-detected, or user-selected.
        # PATH_TO_7ZIP global is the initial best guess.
        # We should use the one passed if available and valid.
        
        actual_7zip_exe_to_use = path_to_7zip_exe_arg
        if not (actual_7zip_exe_to_use and os.path.isfile(actual_7zip_exe_to_use) and os.access(actual_7zip_exe_to_use, os.X_OK)):
             # Fallback to global if arg is bad, then to a direct check
             if PATH_TO_7ZIP and os.path.isfile(PATH_TO_7ZIP) and os.access(PATH_TO_7ZIP, os.X_OK):
                 actual_7zip_exe_to_use = PATH_TO_7ZIP
             else: # Try shutil.which as a last resort before failing
                 found_via_which = shutil.which("7z.exe" if platform.system() == "Windows" else "7z")
                 if found_via_which:
                     actual_7zip_exe_to_use = found_via_which
                 else:
                    logging.error(f"7-Zip executable not found or not executable at '{path_to_7zip_exe_arg}' or global '{PATH_TO_7ZIP}'. Cannot create ZIP for {folder_name}.")
                    if progress_callback:
                        progress_callback(f"Error {index+1}/{total}: 7-Zip not found for {folder_name}")
                    return folder_name, False
        
        zip_command = [
            actual_7zip_exe_to_use, "a", "-tzip", zip_path, os.path.join(folder_path, '*') # Add contents of folder
        ]
        logging.info(f"Creating ZIP archive for '{folder_name}' using contents of '{folder_path}' with command: {' '.join(zip_command)}")
        
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        
        result = subprocess.run(
            zip_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='ignore', check=False, startupinfo=startupinfo
        )
        
        success = result.returncode == 0
        if progress_callback:
            if success:
                progress_callback(f"Created ZIP {index+1}/{total}: {zip_name}")
                logging.info(f"Successfully created ZIP archive: {zip_name}")
            else:
                progress_callback(f"Failed to create ZIP {index+1}/{total}: {zip_name}")
                logging.error(f"Failed to create ZIP archive '{zip_name}'. Return code: {result.returncode}")
                logging.error(f"7-Zip command: {' '.join(zip_command)}")
                logging.error(f"7-Zip stdout: {result.stdout.strip() if result.stdout else 'N/A'}")
                logging.error(f"7-Zip stderr: {result.stderr.strip() if result.stderr else 'N/A'}")
        
        return folder_name, success
    except FileNotFoundError: # Specifically for the 7zip executable itself
        logging.error(f"7-Zip executable not found when trying to create ZIP for {folder_name}.\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: 7-Zip executable not found for {folder_name}")
        return folder_name, False
    except Exception as e:
        logging.error(f"Unexpected error creating ZIP for {folder_name}: {e}\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total}: Failed creating ZIP {folder_name}")
        return folder_name, False

# ----------------------------
# Custom Widgets for Modern UI
# ----------------------------
class ModernButton(QtWidgets.QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        # Remove the animation for now as it's causing issues
        # We'll rely on CSS hover effects instead
        
    def enterEvent(self, event):
        # Hover effect will be handled by stylesheet
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        # Hover effect will be handled by stylesheet
        super().leaveEvent(event)

class GlassPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Glass effect background
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(255, 255, 255, 20))
        gradient.setColorAt(1, QColor(255, 255, 255, 10))
        
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.drawRoundedRect(self.rect(), 12, 12)

# ----------------------------
# PyQt5 Worker Classes (unchanged)
# ----------------------------
class MergeWorker(QtCore.QObject): # Uses MoviePy
    finished = QtCore.pyqtSignal(bool, str, list) # success, output_path, list_of_original_merged_files
    progress = QtCore.pyqtSignal(str)

    def __init__(self, files, output_dir, parent=None):
        super().__init__(parent)
        self.files = files # Expected to be list of basenames
        self.output_dir_path = output_dir

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting file merge (MoviePy)...")
        # process_files expects a list of basenames, which self.files should be
        success, output_path = process_files(self.files, self.output_dir_path, self.progress.emit)
        self.finished.emit(success, output_path if output_path else "", self.files if success else [])

class ConvertWorker(QtCore.QObject): # Uses FFmpeg via convert_mp4_to_mp3
    finished = QtCore.pyqtSignal(bool, int, int) # overall_success, successful_count, processed_count
    progress = QtCore.pyqtSignal(str)

    # No __init__ needed if it just calls super and takes no args other than parent

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Scanning for MP4 files...")
        # Check if PATH_TO_FFMPEG is valid and executable
        if not (PATH_TO_FFMPEG and os.path.isfile(PATH_TO_FFMPEG) and os.access(PATH_TO_FFMPEG, os.X_OK)):
            # Try one last time with shutil.which if PATH_TO_FFMPEG isn't a direct file path (e.g. just "ffmpeg")
            ffmpeg_executable = shutil.which(PATH_TO_FFMPEG)
            if not (ffmpeg_executable and os.path.isfile(ffmpeg_executable) and os.access(ffmpeg_executable, os.X_OK)):
                error_msg = f"Error: FFmpeg not found or not executable at '{PATH_TO_FFMPEG}'. Cannot convert MP4 files. " \
                            "Please check config.json, ensure FFmpeg is in your PATH, or place it in the script directory."
                logging.error(error_msg)
                self.progress.emit(error_msg)
                self.finished.emit(False, 0, 0) 
                return
            # If found via shutil.which, update the global for consistency if it was just a name
            # This is less ideal for a global but helps if initial setup missed it.
            # However, convert_mp4_to_mp3 uses the global PATH_TO_FFMPEG, so if it's good, this check passes.

        try:
            mp4_files = [f for f in os.listdir(current_directory) if f.lower().endswith('.mp4') and os.path.isfile(os.path.join(current_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning for MP4 files: {e}")
            self.progress.emit("Error: Could not scan for files.")
            self.finished.emit(False, 0, 0)
            return

        total_files = len(mp4_files)
        if not mp4_files:
            self.progress.emit("No MP4 files found.")
            self.finished.emit(True, 0, 0) # No files is a form of success (nothing to do)
            return

        self.progress.emit(f"Found {total_files} MP4 files, starting FFmpeg conversion...")
        successful_count = 0
        processed_count = 0 # Tracks how many futures completed
        
        try:
            args_list = [(file, self.progress.emit, i, total_files) for i, file in enumerate(mp4_files)]
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(convert_mp4_to_mp3, args): args[0] for args in args_list}
                for future in as_completed(future_to_file):
                    original_file_arg = future_to_file[future]
                    processed_count +=1
                    try:
                        success_file, _ = future.result() # second item is filename, already have it
                        if success_file:
                            successful_count += 1
                    except Exception as e:
                        logging.error(f"Error processing future for MP4 conversion of file {original_file_arg}: {e}\n{traceback.format_exc()}")
                        self.progress.emit(f"Error during conversion task for: {original_file_arg}")
            
            final_message = f"FFmpeg conversion complete. Successfully converted {successful_count}/{processed_count} files."
            if processed_count < total_files:
                final_message += f" ({total_files - processed_count} initial task(s) may not have completed or were not processed)."
            elif successful_count < processed_count:
                final_message += f" ({processed_count - successful_count} file(s) failed during conversion)."

            self.progress.emit(final_message)
            overall_task_success = (total_files == 0) or (processed_count > 0 and successful_count == processed_count)
            if total_files > 0 and processed_count == 0 : # tasks were there but none processed
                overall_task_success = False

            self.finished.emit(overall_task_success, successful_count, processed_count)

        except Exception as e:
            logging.error(f"Error during MP4 to MP3 conversion process (FFmpeg): {e}\n{traceback.format_exc()}")
            self.progress.emit("A critical error occurred during FFmpeg conversion process.")
            self.finished.emit(False, successful_count, processed_count)


class RemoveSilenceWorker(QtCore.QObject): # Uses FFmpeg
    finished = QtCore.pyqtSignal(bool, int, int) # overall_success, successful_count, total_processed
    progress = QtCore.pyqtSignal(str)

    def __init__(self, files, parent=None): # files are basenames
        super().__init__(parent)
        self.files = files

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting silence removal (FFmpeg)...")
        if not (PATH_TO_FFMPEG and os.path.isfile(PATH_TO_FFMPEG) and os.access(PATH_TO_FFMPEG, os.X_OK)):
            ffmpeg_executable = shutil.which(PATH_TO_FFMPEG) # Try which if it's just a name
            if not (ffmpeg_executable and os.path.isfile(ffmpeg_executable) and os.access(ffmpeg_executable, os.X_OK)):
                error_msg = f"Error: FFmpeg not found or not executable at '{PATH_TO_FFMPEG}'. Cannot remove silence. " \
                            "Please check config.json, ensure FFmpeg is in your PATH, or place it in the script directory."
                logging.error(error_msg)
                self.progress.emit(error_msg)
                self.finished.emit(False, 0, 0)
                return

        total_files = len(self.files)
        if total_files == 0:
            self.progress.emit("No files selected for silence removal.")
            self.finished.emit(True, 0, 0) # No files is a success (nothing to do)
            return
        
        self.progress.emit(f"Processing {total_files} files to remove silence (FFmpeg)...")
        successful_count = 0
        processed_count = 0
        try:
            args_list = [(file, self.progress.emit, i, total_files) for i, file in enumerate(self.files)]
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(remove_silence_from_file, args): args[0] for args in args_list}
                for future in as_completed(future_to_file):
                    original_file_arg = future_to_file[future]
                    processed_count +=1
                    try:
                        success_file, _ = future.result()
                        if success_file:
                            successful_count += 1
                    except Exception as e:
                        logging.error(f"Error processing future for silence removal of file {original_file_arg}: {e}\n{traceback.format_exc()}")
                        self.progress.emit(f"Error during silence removal task for: {original_file_arg}")
            
            final_message = f"Silence removal complete. Successfully processed {successful_count}/{processed_count} files."
            if processed_count < total_files:
                final_message += f" ({total_files - processed_count} initial task(s) may not have completed or were not processed)."
            elif successful_count < processed_count:
                final_message += f" ({processed_count - successful_count} file(s) failed during processing)."
            
            self.progress.emit(final_message)
            overall_task_success = (total_files == 0) or (processed_count > 0 and successful_count == processed_count)
            if total_files > 0 and processed_count == 0 : 
                overall_task_success = False
            self.finished.emit(overall_task_success, successful_count, processed_count)

        except Exception as e:
            logging.error(f"Error during silence removal process (FFmpeg): {e}\n{traceback.format_exc()}")
            self.progress.emit("A critical error occurred during silence removal process.")
            self.finished.emit(False, successful_count, processed_count)


class OrganizeWorker(QtCore.QObject): # Uses 7-Zip for zipping
    finished = QtCore.pyqtSignal(bool, int, int) # overall_success, folder_count, zip_count
    progress = QtCore.pyqtSignal(str)

    def __init__(self, path_to_7zip_from_ui, parent=None): # Renamed for clarity
        super().__init__(parent)
        # This is the path determined by the UI (config, auto-detect, or QFileDialog)
        self.effective_path_to_7zip = path_to_7zip_from_ui 

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting MP3 file organization by date...")
        can_zip = False
        # The effective_path_to_7zip is what the UI decided to use.
        # create_zip_archive will do a final check on this path too.
        if self.effective_path_to_7zip and os.path.isfile(self.effective_path_to_7zip) and os.access(self.effective_path_to_7zip, os.X_OK):
            can_zip = True
            logging.info(f"7-Zip confirmed at: {self.effective_path_to_7zip}. Zipping will be attempted.")
        else:
            # Try shutil.which if self.effective_path_to_7zip was just a name (e.g. "7z")
            exe_via_which = shutil.which(self.effective_path_to_7zip if self.effective_path_to_7zip else ("7z.exe" if platform.system() == "Windows" else "7z"))
            if exe_via_which and os.path.isfile(exe_via_which) and os.access(exe_via_which, os.X_OK):
                self.effective_path_to_7zip = exe_via_which # Update with full path from which
                can_zip = True
                logging.info(f"7-Zip found via PATH at: {self.effective_path_to_7zip}. Zipping will be attempted.")
            else:
                logging.warning(f"7-Zip executable not found or not executable (path tried: {self.effective_path_to_7zip}). Files will be organized, but ZIP archives will not be created.")
                self.progress.emit("Warning: 7-Zip not found/executable. Files will be organized without creating ZIP archives.")
        
        working_directory = current_directory # Base directory for operations
        try:
            all_files_in_dir = os.listdir(working_directory)
            mp3_files = [f for f in all_files_in_dir if f.lower().endswith('.mp3') and os.path.isfile(os.path.join(working_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning for MP3 files in {working_directory}: {e}")
            self.progress.emit(f"Error: Could not scan for MP3 files in {working_directory}.")
            self.finished.emit(False, 0, 0)
            return

        files_by_date = defaultdict(list)
        for file_basename in mp3_files:
            date_obj, time_obj = parse_date_and_time_from_filename(file_basename)
            if date_obj and time_obj: # Ensure both date and time are parsed
                formatted_date_for_grouping = date_obj.strftime('%Y%m%d') # Key for grouping
                time_str_for_sorting = time_obj.strftime('%H-%M') # For sorting within group and naming folder
                files_by_date[formatted_date_for_grouping].append((time_str_for_sorting, file_basename))
        
        if not files_by_date:
            self.progress.emit("No MP3 files with valid date/time found for organization.")
            self.finished.emit(True, 0, 0) # Success, as there's nothing to do
            return

        organized_folder_count = 0
        successful_zip_count = 0
        processed_folders_for_zipping = [] # List of {'name': folder_name, 'path': folder_path}

        total_date_groups = len(files_by_date)
        self.progress.emit(f"Organizing {len(mp3_files)} MP3 files into {total_date_groups} date groups...")
        
        # --- Stage 1: Organize files into folders ---
        organization_tasks_args = [
            (date_str, files_list_with_time, working_directory, self.progress.emit, i, total_date_groups)
            for i, (date_str, files_list_with_time) in enumerate(files_by_date.items())
        ]
        
        organization_completed_successfully = True # Assume success unless a task fails critically
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_date_groups if total_date_groups > 0 else 1)) as executor:
            future_to_date_group = {
                executor.submit(process_date_group, args): args[0] # args[0] is date_str
                for args in organization_tasks_args
            }
            for future in as_completed(future_to_date_group):
                date_group_key = future_to_date_group[future]
                try:
                    _, created_folder_path, success_flag = future.result()
                    if success_flag and created_folder_path:
                        organized_folder_count += 1
                        folder_basename = os.path.basename(created_folder_path)
                        processed_folders_for_zipping.append({'name': folder_basename, 'path': created_folder_path})
                    elif not success_flag:
                        logging.warning(f"Organization for date group {date_group_key} reported failure or no path.")
                except Exception as e:
                    logging.error(f"Error processing future for organizing date group {date_group_key}: {e}\n{traceback.format_exc()}")
                    organization_completed_successfully = False # Critical error in task execution

        self.progress.emit(f"File organization into folders complete. Created {organized_folder_count} folders.")

        # --- Stage 2: Zip organized folders (if 7-Zip is available and folders were created) ---
        if can_zip and processed_folders_for_zipping:
            total_folders_to_zip = len(processed_folders_for_zipping)
            self.progress.emit(f"Starting ZIP archive creation for {total_folders_to_zip} folders using 7-Zip...")
            
            zipping_tasks_args = [
                # Pass the self.effective_path_to_7zip which was validated
                (folder_info['name'], folder_info['path'], self.effective_path_to_7zip, working_directory, self.progress.emit, i, total_folders_to_zip)
                for i, folder_info in enumerate(processed_folders_for_zipping)
            ]
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_folders_to_zip if total_folders_to_zip > 0 else 1)) as executor:
                future_to_zip_task = {
                    executor.submit(create_zip_archive, args): args[0] # args[0] is folder_name
                    for args in zipping_tasks_args
                }
                for future in as_completed(future_to_zip_task):
                    folder_name_key = future_to_zip_task[future]
                    try:
                        _, success_flag = future.result()
                        if success_flag:
                            successful_zip_count += 1
                    except Exception as e:
                        logging.error(f"Error processing future for zipping folder {folder_name_key}: {e}\n{traceback.format_exc()}")

        final_org_message = f"Organization process finished. Created {organized_folder_count} folders."
        if can_zip: # Based on if 7zip was deemed usable by this worker
            if organized_folder_count > 0 :
                final_org_message += f" Successfully created {successful_zip_count} of {len(processed_folders_for_zipping)} possible ZIP archives."
                if successful_zip_count < len(processed_folders_for_zipping):
                    final_org_message += " Some ZIP operations may have failed; check logs."
            # else: No folders created, so no zipping attempted.
        elif organized_folder_count > 0: # Folders created, but zipping was not possible/attempted
            final_org_message += " (ZIP creation skipped as 7-Zip was not found or specified)."
        
        self.progress.emit(final_org_message)
        self.finished.emit(organization_completed_successfully, organized_folder_count, successful_zip_count)

# ----------------------------
# Modern PyQt5 GUI Implementation
# ----------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Toolbox Pro")
        self.resize(1100, 800)
        self.merged_files = set()  # Set of files that were used in merges
        self.output_files = {}  # Dict mapping output files to their source files
        self.current_workers = 0
        self.active_threads_workers = []

        self.initUI()
        self.applyModernStyles()
        self.refreshFileList()

        # Log paths at startup
        logging.info(f"Effective FFmpeg path determined: {PATH_TO_FFMPEG}")
        if not (os.path.isfile(PATH_TO_FFMPEG) and os.access(PATH_TO_FFMPEG, os.X_OK)):
            if not shutil.which(PATH_TO_FFMPEG):
                logging.warning(f"FFmpeg at '{PATH_TO_FFMPEG}' might not be found or executable. Operations requiring FFmpeg may fail or prompt.")
        
        logging.info(f"Effective 7-Zip path determined: {PATH_TO_7ZIP}")
        if not (os.path.isfile(PATH_TO_7ZIP) and os.access(PATH_TO_7ZIP, os.X_OK)):
            if not shutil.which(PATH_TO_7ZIP):
                logging.warning(f"7-Zip at '{PATH_TO_7ZIP}' might not be found or executable. Zipping operations may fail or prompt for location.")

    def initUI(self):
        centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(centralWidget)
        mainLayout = QtWidgets.QVBoxLayout(centralWidget)
        mainLayout.setSpacing(20)
        mainLayout.setContentsMargins(25, 25, 25, 25)

        # Header Section with gradient background
        headerWidget = QWidget()
        headerLayout = QtWidgets.QVBoxLayout(headerWidget)
        headerLayout.setContentsMargins(0, 20, 0, 20)
        
        # Title with modern font
        titleLabel = QtWidgets.QLabel("Audio Toolbox Pro")
        titleFont = QtGui.QFont("SF Pro Display", 32, QtGui.QFont.Bold)
        if platform.system() == "Windows":
            titleFont = QtGui.QFont("Segoe UI", 32, QtGui.QFont.Bold)
        elif platform.system() == "Linux":
            titleFont = QtGui.QFont("Ubuntu", 32, QtGui.QFont.Bold)
        titleLabel.setFont(titleFont)
        titleLabel.setAlignment(Qt.AlignCenter)
        titleLabel.setStyleSheet("color: #1a1a1a; margin: 0px;")
        headerLayout.addWidget(titleLabel)
        
        # Subtitle
        subtitleLabel = QtWidgets.QLabel("Professional Audio Processing Suite")
        subtitleFont = QtGui.QFont("SF Pro Display", 14)
        if platform.system() == "Windows":
            subtitleFont = QtGui.QFont("Segoe UI", 14)
        elif platform.system() == "Linux":
            subtitleFont = QtGui.QFont("Ubuntu", 14)
        subtitleLabel.setFont(subtitleFont)
        subtitleLabel.setAlignment(Qt.AlignCenter)
        subtitleLabel.setStyleSheet("color: #666666; margin-top: 5px;")
        headerLayout.addWidget(subtitleLabel)
        
        mainLayout.addWidget(headerWidget)

        # Main content area with glass panel effect
        contentPanel = GlassPanel()
        contentLayout = QtWidgets.QVBoxLayout(contentPanel)
        contentLayout.setContentsMargins(20, 20, 20, 20)
        contentLayout.setSpacing(20)

        # File Tree with modern styling
        self.treeWidget = QtWidgets.QTreeWidget()
        self.treeWidget.setHeaderLabels(["📁 Files by Date"])
        self.treeWidget.setAlternatingRowColors(True)
        self.treeWidget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.treeWidget.setMinimumHeight(350)
        
        # Add shadow effect to tree widget
        tree_shadow = QGraphicsDropShadowEffect()
        tree_shadow.setBlurRadius(15)
        tree_shadow.setXOffset(0)
        tree_shadow.setYOffset(2)
        tree_shadow.setColor(QColor(0, 0, 0, 30))
        self.treeWidget.setGraphicsEffect(tree_shadow)
        
        contentLayout.addWidget(self.treeWidget, 1)

        # Control panels container
        controlsContainer = QtWidgets.QWidget()
        controlsLayout = QtWidgets.QHBoxLayout(controlsContainer)
        controlsLayout.setSpacing(20)

        # Operations Panel
        operationsPanel = self.createOperationsPanel()
        controlsLayout.addWidget(operationsPanel, 2)

        # Right side panel with selection controls and settings
        rightPanel = QtWidgets.QVBoxLayout()
        rightPanel.setSpacing(15)
        
        selectionPanel = self.createSelectionPanel()
        rightPanel.addWidget(selectionPanel)
        
        settingsPanel = self.createSettingsPanel()
        rightPanel.addWidget(settingsPanel)
        rightPanel.addStretch()
        
        controlsLayout.addLayout(rightPanel, 1)
        
        contentLayout.addWidget(controlsContainer)
        mainLayout.addWidget(contentPanel, 1)

        # Progress Section
        progressWidget = self.createProgressSection()
        mainLayout.addWidget(progressWidget)

    def createOperationsPanel(self):
        panel = QtWidgets.QGroupBox("Operations")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(12)
        
        # Create modern buttons with icons
        button_data = [
            ("🎵 Merge Selected MP3s", "Merge all selected MP3 files using MoviePy", self.mergeSelectedFiles),
            ("📅 Merge by Date", "Merge all unmerged MP3s for selected date", self.mergeAllForSelectedDate),
            ("🎬 Convert MP4 to MP3", "Convert all MP4 files to MP3 using FFmpeg", self.convertMp4Files),
            ("🔇 Remove Silence", "Remove silent segments from selected files", self.removeSilenceSelectedFiles),
            ("📦 Organize & Zip", "Organize MP3s by date and create archives", self.organizeFiles)
        ]
        
        for text, tooltip, callback in button_data:
            btn = ModernButton(text)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
            
        layout.addStretch()
        return panel

    def createSelectionPanel(self):
        panel = QtWidgets.QGroupBox("Selection")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(10)
        
        selectAllBtn = ModernButton("✓ Select All")
        selectAllBtn.setToolTip("Select all enabled files")
        selectAllBtn.clicked.connect(self.selectAllFiles)
        layout.addWidget(selectAllBtn)
        
        deselectAllBtn = ModernButton("✗ Deselect All")
        deselectAllBtn.setToolTip("Deselect all files")
        deselectAllBtn.clicked.connect(self.deselectAllFiles)
        layout.addWidget(deselectAllBtn)
        
        refreshBtn = ModernButton("↻ Refresh")
        refreshBtn.setToolTip("Refresh file list")
        refreshBtn.clicked.connect(self.refreshFileList)
        layout.addWidget(refreshBtn)
        
        return panel

    def createSettingsPanel(self):
        panel = QtWidgets.QGroupBox("Settings")
        layout = QtWidgets.QFormLayout(panel)
        layout.setSpacing(10)
        
        # Thread count spinner with modern styling
        self.threadCountSpinner = QtWidgets.QSpinBox()
        self.threadCountSpinner.setMinimum(1)
        self.threadCountSpinner.setMaximum(max(64, (os.cpu_count() or 1) * 4))
        self.threadCountSpinner.setValue(MAX_WORKERS)
        self.threadCountSpinner.setToolTip("Set maximum parallel tasks")
        self.threadCountSpinner.valueChanged.connect(self.updateThreadCount)
        self.threadCountSpinner.setMinimumHeight(32)
        layout.addRow("Max Threads:", self.threadCountSpinner)
        
        # CPU info
        cpu_cores = os.cpu_count() or 'N/A'
        cpuLabel = QtWidgets.QLabel(f"🖥️ {cpu_cores} cores")
        cpuLabel.setStyleSheet("color: #666666; font-size: 11pt;")
        layout.addRow("CPU:", cpuLabel)
        
        return panel

    def createProgressSection(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Modern progress bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)
        self.progressBar.setTextVisible(False)
        self.progressBar.setMinimumHeight(8)
        self.progressBar.setMaximumHeight(8)
        layout.addWidget(self.progressBar)
        
        # Status label with modern styling
        self.statusLabel = QtWidgets.QLabel("✓ Ready")
        self.statusLabel.setAlignment(Qt.AlignCenter)
        self.statusLabel.setMinimumHeight(30)
        layout.addWidget(self.statusLabel)
        
        return widget

    def applyModernStyles(self):
        # Modern, clean stylesheet optimized for macOS and cross-platform
        style = """
        QWidget {
            font-family: "SF Pro Display", "Helvetica Neue", "Segoe UI", "Ubuntu", Arial, sans-serif;
            font-size: 13px;
            background-color: #f5f5f7;
            color: #1d1d1f;
        }
        
        QMainWindow {
            background-color: #f5f5f7;
        }
        
        /* Group Boxes */
        QGroupBox {
            font-weight: 600;
            font-size: 15px;
            border: 1px solid #d2d2d7;
            border-radius: 12px;
            margin-top: 12px;
            background-color: rgba(255, 255, 255, 0.9);
            padding: 20px 15px 15px 15px;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 10px 5px 10px;
            color: #1d1d1f;
            left: 15px;
            top: -2px;
        }
        
        /* Modern Buttons */
        QPushButton, ModernButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #007AFF, stop:1 #0051D5);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 500;
            font-size: 14px;
            min-height: 36px;
        }
        
        QPushButton:hover, ModernButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #0088FF, stop:1 #0066FF);
        }
        
        QPushButton:pressed, ModernButton:pressed {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #0051D5, stop:1 #003D9E);
        }
        
        QPushButton:disabled, ModernButton:disabled {
            background-color: #e5e5e7;
            color: #8e8e93;
        }
        
        /* Tree Widget */
        QTreeWidget {
            background-color: white;
            border: 1px solid #d2d2d7;
            border-radius: 10px;
            alternate-background-color: #fafafa;
            outline: none;
            font-size: 13px;
            show-decoration-selected: 0;
        }
        
        QTreeWidget::item {
            padding: 8px 5px;
            border-radius: 6px;
        }
        
        QTreeWidget::item:selected {
            background-color: transparent;
            color: #1d1d1f;
        }
        
        QTreeWidget::item:hover:!disabled:!selected {
            background-color: #f0f0f2;
        }
        
        QTreeWidget::item:disabled {
            color: #969696;
            background-color: rgba(0, 0, 0, 0.03);
        }
        
        QHeaderView::section {
            background-color: #f5f5f7;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #d2d2d7;
            font-weight: 600;
            color: #1d1d1f;
        }
        
        /* Progress Bar */
        QProgressBar {
            border: none;
            border-radius: 4px;
            background-color: #e5e5e7;
            height: 8px;
        }
        
        QProgressBar::chunk {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #34C759, stop:1 #30D158);
            border-radius: 4px;
        }
        
        /* Spin Box */
        QSpinBox {
            padding: 6px 10px;
            border: 1px solid #d2d2d7;
            border-radius: 6px;
            background-color: white;
            min-width: 80px;
            font-size: 13px;
        }
        
        QSpinBox:focus {
            border-color: #007AFF;
            outline: none;
        }
        
        QSpinBox::up-button, QSpinBox::down-button {
            width: 20px;
            border: none;
            background-color: transparent;
        }
        
        QSpinBox::up-arrow {
            image: none;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 4px solid #8e8e93;
        }
        
        QSpinBox::down-arrow {
            image: none;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 4px solid #8e8e93;
        }
        
        /* Labels */
        QLabel {
            color: #1d1d1f;
        }
        
        /* Status Label */
        QLabel#statusLabel {
            font-size: 14px;
            font-weight: 500;
            color: #8e8e93;
            background-color: rgba(255, 255, 255, 0.8);
            border-radius: 6px;
            padding: 5px;
        }
        """
        
        self.setStyleSheet(style)
        
        # Apply custom palette for better integration
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(245, 245, 247))
        palette.setColor(QPalette.WindowText, QColor(29, 29, 31))
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.AlternateBase, QColor(250, 250, 250))
        palette.setColor(QPalette.Text, QColor(29, 29, 31))
        palette.setColor(QPalette.Button, QColor(0, 122, 255))
        palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.Highlight, QColor(0, 122, 255))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

    # All the existing methods remain the same
    def refreshFileList(self):
        """Refresh the file tree with current directory contents"""
        self.treeWidget.clear()
        # Don't clear merged_files or output_files - keep track across refreshes
        
        try:
            files_by_date = defaultdict(list)
            output_files_by_date = defaultdict(list)
            
            # Scan for MP3 files
            for file in os.listdir(current_directory):
                if file.lower().endswith('.mp3'):
                    date, time = parse_date_and_time_from_filename(file)
                    if date:
                        date_str = date.strftime('%Y-%m-%d')
                        # Check if this is an output file from merging
                        if file in self.output_files:
                            output_files_by_date[date_str].append(file)
                        else:
                            files_by_date[date_str].append(file)
                    else:
                        if file in self.output_files:
                            output_files_by_date['Unknown Date'].append(file)
                        else:
                            files_by_date['Unknown Date'].append(file)
            
            # Build tree structure
            all_dates = sorted(set(files_by_date.keys()) | set(output_files_by_date.keys()))
            
            for date_str in all_dates:
                date_item = QtWidgets.QTreeWidgetItem(self.treeWidget)
                date_item.setText(0, f"📅 {date_str}")
                date_item.setExpanded(True)
                
                # First add regular files
                for file in sorted(files_by_date.get(date_str, [])):
                    file_item = QtWidgets.QTreeWidgetItem(date_item)
                    
                    # Check if file was used in a merge
                    if file in self.merged_files:
                        file_item.setText(0, f"🔒 {file}")
                        file_item.setDisabled(True)
                        file_item.setToolTip(0, "This file has been merged")
                        # Set gray color
                        for col in range(file_item.columnCount()):
                            file_item.setForeground(col, QtGui.QBrush(QtGui.QColor(150, 150, 150)))
                    else:
                        file_item.setText(0, file)
                        file_item.setCheckState(0, Qt.Unchecked)
                        file_item.setData(0, Qt.UserRole, file)
                
                # Then add merged output files
                for output_file in sorted(output_files_by_date.get(date_str, [])):
                    output_item = QtWidgets.QTreeWidgetItem(date_item)
                    # Get file extension
                    _, ext = os.path.splitext(output_file)
                    output_item.setText(0, f"🎵 {output_file} [MERGED{ext.upper()}]")
                    output_item.setDisabled(True)
                    # Set different color for merged outputs
                    for col in range(output_item.columnCount()):
                        output_item.setForeground(col, QtGui.QBrush(QtGui.QColor(0, 128, 0)))
                    # Add tooltip showing source files
                    if output_file in self.output_files:
                        source_files = self.output_files[output_file]
                        tooltip = f"Merged from {len(source_files)} files:\n" + "\n".join(source_files[:10])
                        if len(source_files) > 10:
                            tooltip += f"\n... and {len(source_files) - 10} more"
                        output_item.setToolTip(0, tooltip)
        
        except Exception as e:
            logging.error(f"Error refreshing file list: {e}")
            self.statusLabel.setText(f"❌ Error: {str(e)}")

    def getSelectedFiles(self):
        """Get list of checked files from the tree"""
        selected = []
        for i in range(self.treeWidget.topLevelItemCount()):
            date_item = self.treeWidget.topLevelItem(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                if file_item.checkState(0) == Qt.Checked and not file_item.isDisabled():
                    selected.append(file_item.data(0, Qt.UserRole))
        return selected

    def selectAllFiles(self):
        """Check all enabled files"""
        for i in range(self.treeWidget.topLevelItemCount()):
            date_item = self.treeWidget.topLevelItem(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                if not file_item.isDisabled():
                    file_item.setCheckState(0, Qt.Checked)

    def deselectAllFiles(self):
        """Uncheck all files"""
        for i in range(self.treeWidget.topLevelItemCount()):
            date_item = self.treeWidget.topLevelItem(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                file_item.setCheckState(0, Qt.Unchecked)

    def updateThreadCount(self, value):
        """Update the global MAX_WORKERS value"""
        global MAX_WORKERS
        MAX_WORKERS = value
        logging.info(f"Max parallel tasks updated to: {value}")

    def showProgress(self, message):
        """Show progress with animation"""
        self.statusLabel.setText(f"⏳ {message}")
        if not self.progressBar.isVisible():
            self.progressBar.setVisible(True)
            self.progressBar.setRange(0, 0)  # Indeterminate

    def hideProgress(self, message="✓ Ready"):
        """Hide progress with animation"""
        self.statusLabel.setText(message)
        self.progressBar.setVisible(False)

    # Worker methods
    def mergeSelectedFiles(self):
        selected_files = self.getSelectedFiles()
        if not selected_files:
            self.statusLabel.setText("⚠️ Please select files to merge")
            return
            
        self.showProgress("Starting merge operation...")
        
        # Create and setup worker
        worker = MergeWorker(selected_files, output_directory_path)
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.progress.connect(self.showProgress)
        worker.finished.connect(lambda success, output, files: self.onMergeFinished(success, output, files, thread, worker))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Start
        self.current_workers += 1
        self.active_threads_workers.append((thread, worker))
        thread.start()

    def onMergeFinished(self, success, output_path, merged_files, thread, worker):
        self.current_workers -= 1
        self.active_threads_workers.remove((thread, worker))
        
        if success and output_path:
            # Mark the source files as merged
            self.merged_files.update(merged_files)
            # Track the output file and its sources
            output_filename = os.path.basename(output_path)
            self.output_files[output_filename] = list(merged_files)
            self.hideProgress(f"✓ Merge complete: {output_filename}")
            self.refreshFileList()
        else:
            self.hideProgress("❌ Merge failed")

    def mergeAllForSelectedDate(self):
        # Get selected date item
        selected_items = self.treeWidget.selectedItems()
        if not selected_items:
            self.statusLabel.setText("⚠️ Please select a date")
            return
            
        date_item = selected_items[0]
        if date_item.parent() is not None:
            date_item = date_item.parent()
            
        # Collect all unmerged files for this date
        files_to_merge = []
        for i in range(date_item.childCount()):
            file_item = date_item.child(i)
            if not file_item.isDisabled():
                files_to_merge.append(file_item.data(0, Qt.UserRole))
                
        if not files_to_merge:
            self.statusLabel.setText("⚠️ No unmerged files for this date")
            return
            
        self.showProgress(f"Merging {len(files_to_merge)} files...")
        
        # Create and setup worker
        worker = MergeWorker(files_to_merge, output_directory_path)
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.progress.connect(self.showProgress)
        worker.finished.connect(lambda success, output, files: self.onMergeFinished(success, output, files, thread, worker))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Start
        self.current_workers += 1
        self.active_threads_workers.append((thread, worker))
        thread.start()

    def convertMp4Files(self):
        self.showProgress("Starting MP4 conversion...")
        
        # Create and setup worker
        worker = ConvertWorker()
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.progress.connect(self.showProgress)
        worker.finished.connect(lambda success, converted, total: self.onConvertFinished(success, converted, total, thread, worker))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Start
        self.current_workers += 1
        self.active_threads_workers.append((thread, worker))
        thread.start()

    def onConvertFinished(self, success, converted_count, total_count, thread, worker):
        self.current_workers -= 1
        self.active_threads_workers.remove((thread, worker))
        
        if success:
            self.hideProgress(f"✓ Converted {converted_count}/{total_count} files")
            if converted_count > 0:
                self.refreshFileList()
        else:
            self.hideProgress(f"❌ Conversion failed ({converted_count}/{total_count} successful)")

    def removeSilenceSelectedFiles(self):
        selected_files = self.getSelectedFiles()
        if not selected_files:
            self.statusLabel.setText("⚠️ Please select files")
            return
            
        self.showProgress(f"Removing silence from {len(selected_files)} files...")
        
        # Create and setup worker
        worker = RemoveSilenceWorker(selected_files)
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.progress.connect(self.showProgress)
        worker.finished.connect(lambda success, processed, total: self.onSilenceRemovalFinished(success, processed, total, thread, worker))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Start
        self.current_workers += 1
        self.active_threads_workers.append((thread, worker))
        thread.start()

    def onSilenceRemovalFinished(self, success, processed_count, total_count, thread, worker):
        self.current_workers -= 1
        self.active_threads_workers.remove((thread, worker))
        
        if success:
            self.hideProgress(f"✓ Processed {processed_count}/{total_count} files")
            if processed_count > 0:
                self.refreshFileList()
        else:
            self.hideProgress(f"❌ Processing failed ({processed_count}/{total_count} successful)")

    def organizeFiles(self):
        # Check for 7-Zip availability
        path_to_7zip = PATH_TO_7ZIP
        if not (path_to_7zip and os.path.isfile(path_to_7zip) and os.access(path_to_7zip, os.X_OK)):
            response = QtWidgets.QMessageBox.question(
                self,
                "7-Zip Not Found",
                "7-Zip is required for creating archives. Would you like to:\n\n"
                "• Select 7-Zip location manually\n"
                "• Continue without creating archives",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel
            )
            
            if response == QtWidgets.QMessageBox.Yes:
                file_filter = "7z.exe (7z.exe);;All files (*)" if platform.system() == "Windows" else "7z (7z);;All files (*)"
                path_to_7zip, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self,
                    "Select 7-Zip Executable",
                    "",
                    file_filter
                )
                if not path_to_7zip:
                    return
            elif response == QtWidgets.QMessageBox.Cancel:
                return
                
        self.showProgress("Organizing files...")
        
        # Create and setup worker
        worker = OrganizeWorker(path_to_7zip)
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.progress.connect(self.showProgress)
        worker.finished.connect(lambda success, folders, zips: self.onOrganizeFinished(success, folders, zips, thread, worker))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Start
        self.current_workers += 1
        self.active_threads_workers.append((thread, worker))
        thread.start()

    def onOrganizeFinished(self, success, folder_count, zip_count, thread, worker):
        self.current_workers -= 1
        self.active_threads_workers.remove((thread, worker))
        
        if success:
            msg = f"✓ Created {folder_count} folders"
            if zip_count > 0:
                msg += f", {zip_count} archives"
            self.hideProgress(msg)
            self.refreshFileList()
        else:
            self.hideProgress("❌ Organization failed")

def main():
    # Enable high-DPI support before creating QApplication
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Audio Toolbox Pro")
    app.setOrganizationName("AudioTools")
    
    # Set application icon if available
    if platform.system() == "Darwin":  # macOS
        app.setWindowIcon(QtGui.QIcon.fromTheme("multimedia-audio-player"))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
