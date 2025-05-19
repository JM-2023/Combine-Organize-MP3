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
import platform # Import platform
import traceback # Import traceback for detailed error logging
# moviepy imports (still needed for MP3 merging)
from moviepy.editor import concatenate_audioclips, AudioFileClip
# PyQt5 imports
from PyQt5 import QtCore, QtWidgets, QtGui # Import QtGui to use QIcon
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
PATH_TO_7ZIP = config.get("path_to_7zip", "C:\\Program Files\\7-Zip\\7z.exe")  # Default path to 7-Zip
# Default FFmpeg path: ffmpeg.exe in script dir for Windows, ffmpeg for other OS
default_ffmpeg_name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
PATH_TO_FFMPEG = config.get("path_to_ffmpeg", os.path.join(os.getcwd(), default_ffmpeg_name))
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
    # before starting tasks.
    logging.info(f"Attempting conversion of {video_file} to MP3 using FFmpeg...")
    command = [
        PATH_TO_FFMPEG,
        "-y",  # Overwrite output file if it exists
        "-i", video_path,
        "-vn",  # No video output
        "-acodec", "mp3", # Explicitly set audio codec to MP3
        # Optional: Add audio quality parameters like:
        # "-b:a", "192k",   # Audio bitrate
        # "-ar", "44100",   # Audio sample rate
        # "-ac", "2",       # Number of audio channels
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
            logging.error(f"FFmpeg stdout: {result.stdout.strip() if result.stdout else 'N/A'}")
            logging.error(f"FFmpeg stderr: {result.stderr.strip() if result.stderr else 'N/A'}")
            if progress_callback:
                progress_callback(f"Error {index+1}/{total}: FFmpeg conversion failed for {video_file}")
            if os.path.exists(output_path): # Clean up potentially partial file
                try: os.remove(output_path)
                except OSError as rm_err: logging.warning(f"Could not delete failed FFmpeg output file {output_path}: {rm_err}")
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
        command = [
            PATH_TO_FFMPEG,
            "-y", "-i", input_file_path,
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.1:stop_threshold=-50dB",
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
    folder_name, folder_path, path_to_7zip_exe, working_directory, progress_callback, index, total = args
    try:
        if not os.path.isdir(folder_path):
             logging.error(f"Source folder not found, cannot create ZIP: {folder_path}")
             if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: Folder not found {folder_name}")
             return folder_name, False
        zip_name = f"{folder_name}.zip"
        zip_path = os.path.join(working_directory, zip_name) # Place zip in the parent (current_directory)
        # Ensure 7-Zip is targeting the contents of the folder, not the folder itself as a top-level item in the zip
        # Path to archive: zip_path
        # Path to files/folders to add: folder_path\* (or similar, depending on 7-Zip's CWD)
        # To zip contents of folder_path into zip_path: 7z a -tzip {zip_path} {folder_path}\*
        # Or, more robustly, change CWD or use full paths for contents.
        # Simpler: just archive the folder itself. Users can extract.
        zip_command = [
            path_to_7zip_exe, "a", "-tzip", zip_path, os.path.join(folder_path, '*') # Add contents of folder
        ]
        logging.info(f"Creating ZIP archive for '{folder_name}' using contents of '{folder_path}'...")
        
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
                logging.error(f"7-Zip stdout: {result.stdout.strip() if result.stdout else 'N/A'}")
                logging.error(f"7-Zip stderr: {result.stderr.strip() if result.stderr else 'N/A'}")
        
        return folder_name, success
    except Exception as e:
        logging.error(f"Unexpected error creating ZIP for {folder_name}: {e}\n{traceback.format_exc()}")
        if progress_callback:
             progress_callback(f"Error {index+1}/{total}: Failed creating ZIP {folder_name}")
        return folder_name, False
# ----------------------------
# PyQt5 Worker Classes
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
        # If successful, self.files contains the list of original basenames that were intended for merging.
        # process_files returns the actual output_path. We need to confirm which files were *actually* merged.
        # The current process_files doesn't directly return the list of successfully merged source files,
        # but `valid_files_for_merge` within it holds that. We can pass `self.files` back for now,
        # as the UI uses it to disable merged files. A more precise list could be returned by process_files.
        # For now, assume all files in self.files were part of the merge if successful.
        self.finished.emit(success, output_path if output_path else "", self.files if success else [])

class ConvertWorker(QtCore.QObject): # Uses FFmpeg via convert_mp4_to_mp3
    finished = QtCore.pyqtSignal(bool, int, int) # overall_success, successful_count, processed_count
    progress = QtCore.pyqtSignal(str)

    # No __init__ needed if it just calls super and takes no args other than parent

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Scanning for MP4 files...")
        if not PATH_TO_FFMPEG or not os.path.isfile(PATH_TO_FFMPEG):
            logging.error(f"FFmpeg not found at the configured path: {PATH_TO_FFMPEG}")
            self.progress.emit(f"Error: FFmpeg not found at '{PATH_TO_FFMPEG}'. Cannot convert MP4 files. Please check config.json or place FFmpeg in the script directory.")
            self.finished.emit(False, 0, 0) 
            return
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
            # It's possible processed_count < total_files if ThreadPoolExecutor had issues submitting all tasks
            # or if there were unhandled exceptions before future.result() for some tasks.
            # as_completed guarantees we only iterate over completed futures.
            if processed_count < total_files:
                 final_message += f" ({total_files - processed_count} initial task(s) may not have completed or were not processed)."
            elif successful_count < processed_count:
                 final_message += f" ({processed_count - successful_count} file(s) failed during conversion)."

            self.progress.emit(final_message)
            # Overall success if all processed tasks were successful, OR if no files were processed (e.g. no mp4s found initially)
            # A single failure among processed tasks means overall_success is False from a strict "all or nothing" view,
            # but True if "some work was done successfully or no work was needed".
            # Let's define overall success as: (no files to process) OR (all processed files were successful).
            # If processed_count is 0 but total_files > 0, it's a failure.
            # If processed_count is 0 and total_files is 0, it's a success.
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
        if not PATH_TO_FFMPEG or not os.path.isfile(PATH_TO_FFMPEG):
            logging.error(f"ffmpeg not found at the configured path: {PATH_TO_FFMPEG}")
            self.progress.emit(f"Error: ffmpeg not found at '{PATH_TO_FFMPEG}'. Please check config.json or place it in the script directory.")
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

    def __init__(self, path_to_7zip_exe, parent=None):
        super().__init__(parent)
        self.path_to_7zip_exe = path_to_7zip_exe # Can be empty if not found/specified

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting MP3 file organization by date...")
        can_zip = False
        if self.path_to_7zip_exe and os.path.isfile(self.path_to_7zip_exe):
            can_zip = True
            logging.info(f"7-Zip found: {self.path_to_7zip_exe}. Zipping will be attempted.")
        else:
            logging.warning(f"7-Zip executable not found or not specified (path: {self.path_to_7zip_exe if self.path_to_7zip_exe else '<Not Provided>'}). Files will be organized, but ZIP archives will not be created.")
            self.progress.emit("Warning: 7-Zip not found. Files will be organized without creating ZIP archives.")
        
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
                        # A specific group failed, log it. Overall process might still be "successful" if some work is done.
                        logging.warning(f"Organization for date group {date_group_key} reported failure or no path.")
                        # organization_completed_successfully = False # Uncomment if one failure means overall failure
                except Exception as e:
                    logging.error(f"Error processing future for organizing date group {date_group_key}: {e}\n{traceback.format_exc()}")
                    organization_completed_successfully = False # Critical error in task execution

        self.progress.emit(f"File organization into folders complete. Created {organized_folder_count} folders.")

        # --- Stage 2: Zip organized folders (if 7-Zip is available and folders were created) ---
        if can_zip and processed_folders_for_zipping:
            total_folders_to_zip = len(processed_folders_for_zipping)
            self.progress.emit(f"Starting ZIP archive creation for {total_folders_to_zip} folders using 7-Zip...")
            
            zipping_tasks_args = [
                (folder_info['name'], folder_info['path'], self.path_to_7zip_exe, working_directory, self.progress.emit, i, total_folders_to_zip)
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
                        # else: zipping_completed_successfully = False # Uncomment if one zip failure means overall zip failure
                    except Exception as e:
                        logging.error(f"Error processing future for zipping folder {folder_name_key}: {e}\n{traceback.format_exc()}")
                        # zipping_completed_successfully = False # Critical error

        final_org_message = f"Organization process finished. Created {organized_folder_count} folders."
        if can_zip:
            if organized_folder_count > 0 :
                 final_org_message += f" Successfully created {successful_zip_count} of {len(processed_folders_for_zipping)} possible ZIP archives."
                 if successful_zip_count < len(processed_folders_for_zipping):
                     final_org_message += " Some ZIP operations may have failed; check logs."
            else: # No folders were created, so no zipping attempted.
                 final_org_message += " No folders were created, so no ZIP archives were made."
        else: # Zipping was not attempted
             final_org_message += " (ZIP creation skipped as 7-Zip was not found, not specified, or no folders were created)."
        
        self.progress.emit(final_org_message)
        # Define overall success: True if at least organization started and didn't critically fail,
        # or if there were no files to organize.
        # A more strict definition might require all steps for all items to succeed.
        # For now, if organization_completed_successfully is true, we call it a success.
        self.finished.emit(organization_completed_successfully, organized_folder_count, successful_zip_count)
# ----------------------------
# PyQt5 GUI Implementation
# ----------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Toolbox (MP3 Merge, Convert, Silence Removal, Organize)")
        self.resize(900, 700) # Adjusted default size
        self.merged_files = set() # Stores basenames of files that are part of a merge output
        self.current_workers = 0 # Counter for active QThreads/workers
        self.active_threads_workers = [] # To keep QThread and worker alive

        self.initUI()
        self.applyStyles()
        self.refreshFileList()

        # Log paths at startup
        effective_7zip = PATH_TO_7ZIP if PATH_TO_7ZIP and os.path.isfile(PATH_TO_7ZIP) else 'Not configured or found'
        logging.info(f"Initial 7-Zip path from config/default: {effective_7zip}")
        effective_ffmpeg = PATH_TO_FFMPEG if PATH_TO_FFMPEG and os.path.isfile(PATH_TO_FFMPEG) else 'Not configured or found'
        logging.info(f"Initial FFmpeg path from config/default: {effective_ffmpeg}")


    def initUI(self):
        centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(centralWidget)
        mainLayout = QtWidgets.QVBoxLayout(centralWidget)
        mainLayout.setSpacing(15) # Increased spacing
        mainLayout.setContentsMargins(15, 15, 15, 15) # Increased margins

        # Title
        titleLabel = QtWidgets.QLabel("Audio Toolbox")
        titleFont = titleLabel.font()
        titleFont.setPointSize(24)
        titleFont.setBold(True)
        titleLabel.setFont(titleFont)
        titleLabel.setAlignment(QtCore.Qt.AlignCenter)
        titleLabel.setStyleSheet("color: #2c3e50; margin-bottom: 10px;")
        mainLayout.addWidget(titleLabel)

        # File Tree
        self.treeWidget = QtWidgets.QTreeWidget()
        self.treeWidget.setHeaderLabels(["Date / File Name"])
        self.treeWidget.setAlternatingRowColors(True)
        self.treeWidget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection) # Allow multi-select
        # self.treeWidget.setSortingEnabled(True) # Consider if user sorting is desired vs programmatic
        mainLayout.addWidget(self.treeWidget, 1) # Give tree more space

        # Bottom layout for controls
        bottomLayout = QtWidgets.QHBoxLayout()

        # Actions Group
        actionsGroup = QtWidgets.QGroupBox("File Operations")
        actionsLayout = QtWidgets.QVBoxLayout(actionsGroup)
        actionsLayout.setSpacing(10)

        # Icons (using standard names, will fall back if not found by theme)
        icon_merge = QtGui.QIcon.fromTheme("media-join", QtGui.QIcon.fromTheme("list-add"))
        icon_merge_date = QtGui.QIcon.fromTheme("media-playlist-shuffle", QtGui.QIcon.fromTheme("view-sort-ascending"))
        icon_convert = QtGui.QIcon.fromTheme("utilities-x-terminal", QtGui.QIcon.fromTheme("applications-accessories")) # More generic
        icon_silence = QtGui.QIcon.fromTheme("audio-volume-muted", QtGui.QIcon.fromTheme("multimedia-volume-control"))
        icon_organize = QtGui.QIcon.fromTheme("folder-zip", QtGui.QIcon.fromTheme("document-export"))


        self.mergeButton = QtWidgets.QPushButton("Merge Selected MP3s")
        if not icon_merge.isNull(): self.mergeButton.setIcon(icon_merge)
        self.mergeButton.setToolTip("Merge all checked MP3 files (can span across dates) using MoviePy.\nOutput filename based on the earliest file.")
        self.mergeButton.clicked.connect(self.mergeSelectedFiles)
        actionsLayout.addWidget(self.mergeButton)

        self.mergeAllButton = QtWidgets.QPushButton("Merge All MP3s for Date")
        if not icon_merge_date.isNull(): self.mergeAllButton.setIcon(icon_merge_date)
        self.mergeAllButton.setToolTip("Merge all unmerged MP3 files under the selected date group using MoviePy.\nOutput filename based on the earliest file in that group.")
        self.mergeAllButton.clicked.connect(self.mergeAllForSelectedDate)
        actionsLayout.addWidget(self.mergeAllButton)
        
        self.convertButton = QtWidgets.QPushButton("Convert All MP4 to MP3")
        if not icon_convert.isNull(): self.convertButton.setIcon(icon_convert)
        self.convertButton.setToolTip("Convert all MP4 files in the current directory to MP3 using FFmpeg.")
        self.convertButton.clicked.connect(self.convertMp4Files)
        actionsLayout.addWidget(self.convertButton)

        self.removeSilenceButton = QtWidgets.QPushButton("Remove Silence from Selected")
        if not icon_silence.isNull(): self.removeSilenceButton.setIcon(icon_silence)
        self.removeSilenceButton.setToolTip("Remove silent segments from checked audio files using FFmpeg.\nOutputs new files with '_nosilence' suffix.")
        self.removeSilenceButton.clicked.connect(self.removeSilenceSelectedFiles)
        actionsLayout.addWidget(self.removeSilenceButton)

        self.organizeButton = QtWidgets.QPushButton("Organize All MP3s & Zip")
        if not icon_organize.isNull(): self.organizeButton.setIcon(icon_organize)
        self.organizeButton.setToolTip("Organize all MP3s in the current directory into date-based folders,\nthen create ZIP archives for each folder (requires 7-Zip).")
        self.organizeButton.clicked.connect(self.organizeFiles)
        actionsLayout.addWidget(self.organizeButton)
        
        bottomLayout.addWidget(actionsGroup)

        # Selection & Refresh Group
        selectionGroup = QtWidgets.QGroupBox("Selection & View")
        selectionLayout = QtWidgets.QVBoxLayout(selectionGroup)
        selectionLayout.setSpacing(10)

        icon_select_all = QtGui.QIcon.fromTheme("edit-select-all")
        icon_deselect_all = QtGui.QIcon.fromTheme("edit-clear", QtGui.QIcon.fromTheme("edit-select-none"))
        icon_refresh = QtGui.QIcon.fromTheme("view-refresh", QtGui.QIcon.fromTheme("reload"))

        self.selectAllButton = QtWidgets.QPushButton("Select All Enabled")
        if not icon_select_all.isNull(): self.selectAllButton.setIcon(icon_select_all)
        self.selectAllButton.setToolTip("Check all enabled (not already merged) files in the list.")
        self.selectAllButton.clicked.connect(self.selectAllFiles)
        selectionLayout.addWidget(self.selectAllButton)

        self.deselectAllButton = QtWidgets.QPushButton("Deselect All")
        if not icon_deselect_all.isNull(): self.deselectAllButton.setIcon(icon_deselect_all)
        self.deselectAllButton.setToolTip("Uncheck all files in the list.")
        self.deselectAllButton.clicked.connect(self.deselectAllFiles)
        selectionLayout.addWidget(self.deselectAllButton)
        
        self.refreshButton = QtWidgets.QPushButton("Refresh File List")
        if not icon_refresh.isNull(): self.refreshButton.setIcon(icon_refresh)
        self.refreshButton.setToolTip("Rescan the current directory and update the file list.")
        self.refreshButton.clicked.connect(self.refreshFileList)
        selectionLayout.addWidget(self.refreshButton)
        selectionLayout.addStretch() # Pushes buttons to top
        bottomLayout.addWidget(selectionGroup)

        # Settings & Status (Combined in a QVBoxLayout for better arrangement)
        settingsAndStatusLayout = QtWidgets.QVBoxLayout()

        # Settings Group (within the QVBoxLayout)
        settingsGroup = QtWidgets.QGroupBox("Settings")
        settingsLayout = QtWidgets.QFormLayout(settingsGroup) # QFormLayout is good for label-field pairs
        settingsLayout.setSpacing(10)

        self.threadCountSpinner = QtWidgets.QSpinBox()
        self.threadCountSpinner.setMinimum(1)
        # Allow more threads, up to a higher cap, default based on CPU but user can override
        self.threadCountSpinner.setMaximum(max(64, (os.cpu_count() or 1) * 4)) 
        self.threadCountSpinner.setValue(MAX_WORKERS)
        self.threadCountSpinner.setToolTip("Set the maximum number of parallel processing tasks (threads).")
        self.threadCountSpinner.valueChanged.connect(self.updateThreadCount)
        settingsLayout.addRow("Max Parallel Tasks:", self.threadCountSpinner)

        cpu_cores = os.cpu_count() or 'N/A'
        cpuLabel = QtWidgets.QLabel(f"{cpu_cores}")
        settingsLayout.addRow("Detected CPU Cores:", cpuLabel)
        
        settingsAndStatusLayout.addWidget(settingsGroup)
        settingsAndStatusLayout.addStretch() # Pushes settings group to top if status is below
        bottomLayout.addLayout(settingsAndStatusLayout) # Add this vertical layout to the horizontal bottomLayout

        mainLayout.addLayout(bottomLayout)

        # Progress Bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False) # Initially hidden
        self.progressBar.setTextVisible(False) # Cleaner look, statusLabel provides text
        self.progressBar.setRange(0,0) # Indeterminate initially
        mainLayout.addWidget(self.progressBar)

        # Status Label
        self.statusLabel = QtWidgets.QLabel("Ready")
        self.statusLabel.setAlignment(QtCore.Qt.AlignCenter)
        mainLayout.addWidget(self.statusLabel)

    def applyStyles(self):
        # Modern, cleaner stylesheet
        style = """
        QWidget {
            font-family: "Segoe UI", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
            font-size: 10pt; /* Base font size */
            background-color: #f8f9fa; /* Light gray background */
            color: #343a40; /* Dark gray text */
        }
        QMainWindow {
            background-color: #f8f9fa;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #dee2e6; /* Lighter border */
            border-radius: 8px; /* Rounded corners */
            margin-top: 10px; /* Space above groupbox */
            background-color: #ffffff; /* White background for groupbox content */
            padding: 15px 10px 10px 10px; /* More padding inside */
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px 5px 5px; /* Padding around title */
            color: #0056b3; /* Darker blue for title */
            left: 10px; /* Indent title slightly */
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #007bff, stop:1 #0056b3); /* Blue gradient */
            color: white;
            border: none; /* No border for a flatter look */
            padding: 8px 15px; /* Comfortable padding */
            border-radius: 5px; /* Rounded corners */
            min-height: 25px; /* Minimum height */
            outline: none; /* No focus outline */
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0069d9, stop:1 #004fa3); /* Darker blue on hover */
        }
        QPushButton:pressed {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #005cbf, stop:1 #004085); /* Even darker on press */
        }
        QPushButton:disabled {
            background-color: #ced4da; /* Gray when disabled */
            color: #6c757d; /* Darker gray text when disabled */
        }
        QTreeWidget {
            background-color: #ffffff; /* White background */
            border: 1px solid #ced4da; /* Standard border */
            border-radius: 5px;
            alternate-background-color: #e9ecef; /* Very light gray for alternating rows */
            font-size: 9pt; /* Slightly smaller font for list items */
        }
        QTreeWidget::item {
            padding: 6px 4px; /* Padding within items */
            border-radius: 3px; /* Slight rounding for selection highlight */
        }
        QTreeWidget::item:selected:active {
            background-color: #007bff; /* Blue selection color */
            color: white;
        }
        QTreeWidget::item:selected:!active { /* When window is not focused */
            background-color: #d4e8ff; /* Lighter blue */
            color: #343a40; /* Original text color */
        }
        QTreeWidget::item:disabled {
            color: #adb5bd; /* Light gray for disabled text */
            background-color: transparent; /* Ensure no odd background */
        }
        QHeaderView::section {
            background-color: #e9ecef; /* Light gray header */
            padding: 4px;
            border: none;
            border-bottom: 1px solid #ced4da; /* Separator line */
            font-weight: bold;
            color: #495057; /* Darker gray header text */
        }
        QProgressBar {
            border: 1px solid #ced4da;
            border-radius: 5px;
            text-align: center;
            background-color: #e9ecef; /* Light gray background */
            height: 12px; /* Slimmer progress bar */
        }
        QProgressBar::chunk {
            background-color: #28a745; /* Green progress chunk */
            border-radius: 5px; /* Rounded chunk to match PBar */
        }
        QProgressBar:indeterminate { /* For indeterminate state */
            background-color: #e9ecef;
        }
        QProgressBar:indeterminate::chunk { /* Animated indeterminate chunk */
             background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007bff, stop: 0.5 #e9ecef, stop:1 #007bff);
        }
        QLabel#StatusLabel { /* Specific styling for status label if needed */
            color: #6c757d; /* Medium gray */
            font-size: 9pt;
            font-weight: bold;
        }
        QSpinBox {
            padding: 4px 6px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            min-width: 60px; /* Ensure it's wide enough */
        }
        QSpinBox:disabled {
            background-color: #e9ecef;
            color: #6c757d;
        }
        QToolTip {
             background-color: #343a40; /* Dark tooltip */
             color: white;
             border: 1px solid #343a40; /* Same color border or none */
             padding: 5px;
             border-radius: 4px;
             opacity: 230; /* Slightly transparent (if supported by style engine) */
        }
        """
        self.setStyleSheet(style)
        self.statusLabel.setObjectName("StatusLabel") # For specific QLabel styling if needed

    def updateThreadCount(self, value):
        global MAX_WORKERS
        MAX_WORKERS = value
        logging.info(f"Maximum worker threads set to: {MAX_WORKERS}")
        self.updateStatus(f"Max parallel tasks set to {MAX_WORKERS}.")

    def selectAllFiles(self):
        root = self.treeWidget.invisibleRootItem()
        count = 0
        for i in range(root.childCount()): # Iterate through date items
            dateItem = root.child(i)
            for j in range(dateItem.childCount()): # Iterate through file items under this date
                childItem = dateItem.child(j)
                # Check if item is enabled (not disabled) and checkable
                if childItem.flags() & QtCore.Qt.ItemIsEnabled and \
                   childItem.flags() & QtCore.Qt.ItemIsUserCheckable:
                    childItem.setCheckState(0, QtCore.Qt.Checked)
                    count += 1
        self.updateStatus(f"Selected {count} enabled files.")

    def deselectAllFiles(self):
        root = self.treeWidget.invisibleRootItem()
        count = 0
        for i in range(root.childCount()): # Iterate through date items
            dateItem = root.child(i)
            for j in range(dateItem.childCount()): # Iterate through file items
                childItem = dateItem.child(j)
                if childItem.flags() & QtCore.Qt.ItemIsUserCheckable:
                     if childItem.checkState(0) == QtCore.Qt.Checked:
                         count +=1
                     childItem.setCheckState(0, QtCore.Qt.Unchecked)
        self.updateStatus(f"Deselected {count} files.")

    def refreshFileList(self):
        self.treeWidget.clear()
        grouped_files = defaultdict(list) # date_obj: [(basename, timestamp_obj)]
        
        try:
            all_files_in_dir = os.listdir(current_directory)
            # Filter for MP3 files directly and ensure they are files
            mp3_file_basenames = [f for f in all_files_in_dir if f.lower().endswith('.mp3') and os.path.isfile(os.path.join(current_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning directory '{current_directory}': {e}")
            QtWidgets.QMessageBox.critical(self, "Directory Scan Error", f"Could not scan directory for files:\n{e}")
            return

        for basename in mp3_file_basenames:
            date_obj, time_obj = parse_date_and_time_from_filename(basename)
            if date_obj: # Ensure date was parsed
                 # If time_obj is None (e.g. only date in filename), use midnight for sorting
                 timestamp = datetime.combine(date_obj, time_obj if time_obj else datetime.min.time())
                 grouped_files[date_obj].append((basename, timestamp))
            # else:
            #    logging.debug(f"File '{basename}' does not match date/time pattern, not listed for merging/organization.")

        root = self.treeWidget.invisibleRootItem()
        total_file_count = 0
        
        # Sort date groups by date_obj for consistent display
        for date_obj_key in sorted(grouped_files.keys()):
            date_str_display = date_obj_key.strftime('%Y-%m-%d (%A)') # e.g., 2023-10-26 (Thursday)
            dateItem = QtWidgets.QTreeWidgetItem([date_str_display])
            # Make date items checkable to select all children, autoTristate for partial checks
            dateItem.setFlags(dateItem.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate)
            dateItem.setCheckState(0, QtCore.Qt.Unchecked)
            
            font = dateItem.font(0)
            font.setBold(True)
            dateItem.setFont(0, font)
            root.addChild(dateItem)

            # Sort files under this date group by their full timestamp
            files_sorted_by_time = sorted(grouped_files[date_obj_key], key=lambda item: item[1])
            
            for basename, timestamp in files_sorted_by_time:
                total_file_count += 1
                # Display filename, perhaps with time for clarity if desired, but basename is usually enough
                childItem = QtWidgets.QTreeWidgetItem([basename])
                childItem.setFlags(childItem.flags() | QtCore.Qt.ItemIsUserCheckable)
                
                if basename in self.merged_files: # Check if this basename was part of a successful merge
                    childItem.setCheckState(0, QtCore.Qt.Checked) # Visually indicate it's "done"
                    childItem.setDisabled(True) # Disable it from being re-selected for merge
                    # Optional: change color for disabled/merged items
                    # brush = QtGui.QBrush(QtGui.QColor("gray"))
                    # childItem.setForeground(0, brush)
                else:
                    childItem.setCheckState(0, QtCore.Qt.Unchecked)
                
                childItem.setData(0, QtCore.Qt.UserRole, basename) # Store basename for easy retrieval
                dateItem.addChild(childItem)
            dateItem.setExpanded(True) # Expand date groups by default

        self.treeWidget.resizeColumnToContents(0)
        self.updateStatus(f"Ready. Found {total_file_count} MP3 files in '{current_directory}'.")

    def getSelectedFiles(self):
        """
        Collects basenames of all checked and enabled files from the QTreeWidget.
        Handles checking parent (date) items to include all their enabled children.
        Returns a list of unique basenames, sorted chronologically.
        """
        selected_basenames = set() # Use a set to ensure uniqueness initially
        root = self.treeWidget.invisibleRootItem()
        
        for i in range(root.childCount()): # Iterate through date items
            dateItem = root.child(i)
            # If dateItem itself is checked, all its enabled children are considered selected
            # If dateItem is partially checked (Qt.PartiallyChecked), implies individual children are selected
            # If dateItem is unchecked, still need to check its children individually.

            is_date_item_fully_checked = (dateItem.checkState(0) == QtCore.Qt.Checked)

            for j in range(dateItem.childCount()): # Iterate through file items (children of dateItem)
                fileItem = dateItem.child(j)
                if not fileItem.isDisabled(): # Only consider enabled files
                    # If parent is fully checked, add child. OR if child itself is checked.
                    if is_date_item_fully_checked or (fileItem.checkState(0) == QtCore.Qt.Checked):
                        basename = fileItem.data(0, QtCore.Qt.UserRole) # Get basename from UserRole
                        if basename:
                            selected_basenames.add(basename)
        
        # Convert set to list and sort chronologically
        sorted_selected_files = sorted(list(selected_basenames), key=lambda bn: parse_time_from_filename(bn))
        return sorted_selected_files

    def mergeSelectedFiles(self):
        selected_files_list = self.getSelectedFiles() # Gets sorted list of basenames
        if not selected_files_list:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please check at least one enabled MP3 file to merge.")
            return
        
        logging.info(f"Preparing to merge {len(selected_files_list)} selected MP3 files using MoviePy: {selected_files_list}")
        self.startMerge(selected_files_list)

    def mergeAllForSelectedDate(self):
        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            QtWidgets.QMessageBox.warning(self, "No Date Selected", "Please select a date group item (e.g., '2023-10-26') or any file under it in the list first.")
            return

        item = selectedItems[0]
        dateItem = None
        
        # Determine if the selected item is a date item or a file item
        if item.parent() is None or item.parent() == self.treeWidget.invisibleRootItem(): # It's a date item
            dateItem = item
        elif item.parent() is not None and (item.parent().parent() is None or item.parent().parent() == self.treeWidget.invisibleRootItem()): # It's a file item, get its parent (date item)
             dateItem = item.parent()

        if dateItem is None: # Should not happen if logic above is correct
             QtWidgets.QMessageBox.warning(self, "Invalid Selection", "Could not determine the date group from your selection. Please select a date item directly.")
             return

        date_str_display = dateItem.text(0) # e.g. "2023-10-26 (Thursday)"
        logging.info(f"Preparing to merge all unmerged MP3 files under date group '{date_str_display}' using MoviePy.")
        
        files_to_merge_basenames = []
        for j in range(dateItem.childCount()):
            childFileItem = dateItem.child(j)
            if not childFileItem.isDisabled(): # Only consider enabled (not already merged) files
                basename = childFileItem.data(0, QtCore.Qt.UserRole)
                if basename:
                    files_to_merge_basenames.append(basename)
        
        if not files_to_merge_basenames:
            QtWidgets.QMessageBox.information(self, "No Files to Merge", f"No enabled MP3 files available to merge under date group '{date_str_display}'.")
            return

        # Sort them chronologically (though they should already be if sourced from tree correctly)
        files_to_merge_basenames.sort(key=parse_time_from_filename)
        
        logging.info(f"Found {len(files_to_merge_basenames)} MP3 files to merge for date group {date_str_display}: {files_to_merge_basenames}")
        self.startMerge(files_to_merge_basenames)

    def startTask(self, worker_class, worker_args_tuple, finish_slot, progress_message):
        """ General method to start a worker in a QThread """
        self.current_workers += 1
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0) # Indeterminate progress
        self.updateStatus(progress_message)
        self.disableButtons()

        thread = QtCore.QThread(self) # Parent `self` for QThread
        # Pass worker_args_tuple expanded to the worker constructor
        worker = worker_class(*worker_args_tuple) 
        worker.moveToThread(thread)

        # Connections
        thread.started.connect(worker.run)
        worker.progress.connect(self.updateStatus)
        worker.finished.connect(finish_slot) # Specific finish slot for this task type
        worker.finished.connect(self.onTaskFinished) # Generic cleanup
        
        # Ensure thread quits and resources are cleaned up
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        self.active_threads_workers.append((thread, worker)) # Keep references
        thread.start()

    def onTaskFinished(self):
        """Generic slot called when any worker's 'finished' signal is emitted."""
        self.current_workers -= 1
        
        # Clean up the completed thread and worker from the list
        sender_worker = self.sender() # The worker that emitted the signal
        self.active_threads_workers = [(t, w) for t, w in self.active_threads_workers if w is not sender_worker]

        if self.current_workers <= 0:
            self.current_workers = 0 # Ensure it doesn't go negative
            self.progressBar.setVisible(False)
            self.progressBar.setRange(0, 100) # Reset for determinate (or hide)
            self.progressBar.setValue(0)
            self.updateStatus("Ready") # Reset status or show summary
            self.enableButtons()
            logging.info("All tasks finished. UI enabled.")
        else:
             logging.info(f"A task finished. {self.current_workers} task(s) still running.")

    def startMerge(self, files_basenames_list):
        """ Initiates the merge operation with a list of basenames. """
        output_dir = output_directory_path # Global or class member
        # Worker arguments are passed as a tuple
        worker_args = (files_basenames_list, output_dir) 
        self.startTask(MergeWorker, worker_args,
                       finish_slot=self.onMergeFinishedSpecific,
                       progress_message="Merging MP3 files (MoviePy)...")

    def onMergeFinishedSpecific(self, success, output_path, merged_original_files_basenames):
        if success:
            QtWidgets.QMessageBox.information(self, "Merge Complete", f"Merge successful!\nOutput: {output_path}")
            # Add the *original* basenames that were part of this successful merge to self.merged_files
            self.merged_files.update(merged_original_files_basenames)
            self.refreshFileList() # Refresh to show merged files as disabled/checked
        else:
            QtWidgets.QMessageBox.critical(self, "Merge Failed", "An error occurred during the MP3 merge process. Please check logs for details.")
            # No need to refresh list if it failed, unless partial results need indication

    def convertMp4Files(self):
        # FFmpeg path check is primarily in the worker, but a pre-check or relying on worker's message is fine.
        # The ConvertWorker now takes no arguments in constructor.
        self.startTask(ConvertWorker, (), # Empty tuple for worker_args
                       finish_slot=self.onConvertFinishedSpecific,
                       progress_message="Converting MP4 to MP3 (FFmpeg)...")

    def onConvertFinishedSpecific(self, overall_success, successful_count, total_processed):
        # This slot receives: overall_success (bool), successful_count (int), total_processed (int)
        if not overall_success and total_processed == 0 and successful_count == 0:
            # This case implies the worker might have failed very early (e.g., FFmpeg not found as handled by worker)
            if "ffmpeg not found" in self.statusLabel.text().lower(): # Check status message
                 QtWidgets.QMessageBox.critical(self, "Conversion Error", f"MP4 to MP3 conversion failed: FFmpeg not found at '{PATH_TO_FFMPEG}'. Please check configuration.")
            else:
                 QtWidgets.QMessageBox.critical(self, "Conversion Error", "MP4 to MP3 conversion failed to start or process any files. Please check logs.")
        elif total_processed == 0 and overall_success : # No MP4 files were found to convert
             QtWidgets.QMessageBox.information(self, "Conversion Info", "No MP4 files found to convert.")
        elif overall_success and successful_count == total_processed and total_processed > 0 : # All files converted successfully
             QtWidgets.QMessageBox.information(self, "Conversion Complete",
                                               f"Successfully converted {successful_count}/{total_processed} MP4 files to MP3 using FFmpeg.")
        elif not overall_success and total_processed > 0: # Some files processed, but not all were successful
             QtWidgets.QMessageBox.warning(self, "Conversion Problem",
                                            f"Conversion process completed. Successfully converted {successful_count} out of {total_processed} MP4 files using FFmpeg. Some files may have failed; please check logs for errors.")
        else: # Fallback for any other unhandled status
             QtWidgets.QMessageBox.error(self, "Conversion Status Unknown", f"Conversion finished. Success: {overall_success}, Converted: {successful_count}/{total_processed}. Check logs for details.")
        
        self.refreshFileList() # Refresh list as new MP3s might be present

    def removeSilenceSelectedFiles(self):
        selected_files_basenames = self.getSelectedFiles()
        if not selected_files_basenames:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please check at least one audio file to process for silence removal.")
            return
        
        # FFmpeg path pre-check in UI (worker also checks)
        if not PATH_TO_FFMPEG or not os.path.isfile(PATH_TO_FFMPEG):
            QtWidgets.QMessageBox.critical(self, "FFmpeg Not Found",
                                           f"FFmpeg not found at the configured path: {PATH_TO_FFMPEG}\n"
                                           "Cannot remove silence. Please ensure FFmpeg is correctly configured in config.json or present in the script directory.")
            return

        logging.info(f"Preparing to remove silence from {len(selected_files_basenames)} selected files using FFmpeg: {selected_files_basenames}")
        worker_args = (selected_files_basenames,) # Tuple with one element
        self.startTask(RemoveSilenceWorker, worker_args,
                       finish_slot=self.onRemoveSilenceFinishedSpecific,
                       progress_message="Removing silence from audio files (FFmpeg)...")

    def onRemoveSilenceFinishedSpecific(self, overall_success, successful_count, total_processed):
        if not overall_success and total_processed == 0 and successful_count == 0:
             if "ffmpeg not found" in self.statusLabel.text().lower():
                 QtWidgets.QMessageBox.critical(self, "Silence Removal Error", f"Silence removal failed: FFmpeg not found at '{PATH_TO_FFMPEG}'. Please check configuration.")
             else:
                QtWidgets.QMessageBox.critical(self, "Silence Removal Error", "Silence removal failed to start or process any files. Please check logs.")
        elif total_processed == 0 and overall_success: # No files were selected or processed
             QtWidgets.QMessageBox.information(self, "Silence Removal Info", "No files were processed for silence removal (e.g., none selected).")
        elif overall_success and successful_count == total_processed and total_processed > 0:
            QtWidgets.QMessageBox.information(self, "Silence Removal Complete",
                                              f"Successfully processed {successful_count}/{total_processed} file(s) for silence removal.")
        elif not overall_success and total_processed > 0 :
             QtWidgets.QMessageBox.warning(self, "Silence Removal Problem",
                                            f"Silence removal process completed. Successfully processed {successful_count} out of {total_processed} files. Some files may have failed; please check logs for errors.")
        else:
             QtWidgets.QMessageBox.error(self, "Silence Removal Status Unknown", f"Silence removal finished. Success: {overall_success}, Processed: {successful_count}/{total_processed}. Check logs for details.")
        
        self.refreshFileList() # New "_nosilence" files might be present

    def organizeFiles(self):
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm File Organization",
            "This action will:\n"
            "1. Scan all MP3 files in the current directory.\n"
            "2. Group them by date (parsed from filename).\n"
            "3. Create a new subfolder for each date group (e.g., 'YYYYMMDD HH-MM').\n"
            "4. MOVE the original MP3 files into these new subfolders.\n"
            "5. Attempt to create a ZIP archive for each created subfolder (requires 7-Zip).\n\n"
            "IMPORTANT: Original MP3 files will be MOVED from their current location.\n\n"
            "Do you want to proceed?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No # Default to No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            self.updateStatus("Organization cancelled by user.")
            return

        # Determine 7-Zip path (similar to your existing logic but slightly streamlined)
        effective_7zip_path = ""
        config_7zip_path = PATH_TO_7ZIP # From global config
        
        if config_7zip_path and os.path.isfile(config_7zip_path):
            effective_7zip_path = config_7zip_path
            logging.info(f"Using 7-Zip path from config/default: {effective_7zip_path}")
        else:
            logging.warning(f"7-Zip path from config/default ('{config_7zip_path}') is invalid or not set. Attempting auto-detection or user selection.")
            common_paths = [
                "C:\\Program Files\\7-Zip\\7z.exe", "C:\\Program Files (x86)\\7-Zip\\7z.exe",
                "/usr/bin/7z", "/usr/local/bin/7z", "/opt/homebrew/bin/7z" # For macOS Homebrew
            ]
            found_automatically = False
            for p in common_paths:
                if os.path.isfile(p):
                    effective_7zip_path = p
                    logging.info(f"Auto-detected 7-Zip at: {effective_7zip_path}")
                    found_automatically = True
                    break
            
            if not found_automatically:
                self.updateStatus("7-Zip not found in common locations. Please select it.")
                selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "Locate 7-Zip Executable (e.g., 7z.exe or 7z)",
                    os.path.expanduser("~"), # Start in user's home directory
                    "Executable Files (*.exe);;All Files (*)"
                )
                if selected_path and os.path.isfile(selected_path):
                    effective_7zip_path = selected_path
                    logging.info(f"User selected 7-Zip path: {effective_7zip_path}")
                else:
                    QtWidgets.QMessageBox.warning(self, "7-Zip Not Found",
                                                  "7-Zip executable was not found or selected.\n"
                                                  "Files will be organized into folders, but ZIP archives will NOT be created.")
                    effective_7zip_path = "" # Ensure it's empty if no valid path
        
        if effective_7zip_path:
             self.updateStatus(f"Starting organization. 7-Zip found at: {effective_7zip_path}. ZIPs will be attempted.")
        else:
             self.updateStatus("Starting organization. 7-Zip NOT found. ZIPs will be skipped.")

        worker_args = (effective_7zip_path,) # Tuple with one element
        self.startTask(OrganizeWorker, worker_args,
                       finish_slot=self.onOrganizeFinishedSpecific,
                       progress_message="Organizing MP3 files by date and creating ZIPs...")

    def onOrganizeFinishedSpecific(self, overall_success, folder_count, zip_count):
        # `overall_success` from OrganizeWorker indicates if the organization part (moving files) was generally okay.
        # `folder_count` is number of date folders created.
        # `zip_count` is number of successful ZIPs.

        sender_worker = self.sender() # Get the worker instance
        zipping_was_attempted = False
        if sender_worker and isinstance(sender_worker, OrganizeWorker):
            zipping_was_attempted = bool(sender_worker.path_to_7zip_exe) # Check if 7zip path was provided to worker

        if overall_success:
            message = f"Organization process completed.\nCreated {folder_count} date folder(s)."
            if folder_count == 0:
                 message = "No date-stamped MP3 files found that matched the criteria for organization."
            
            if zipping_was_attempted and folder_count > 0:
                message += f"\nSuccessfully created {zip_count} ZIP archive(s)."
                if zip_count < folder_count:
                    message += f" ({folder_count - zip_count} ZIP operation(s) may have failed; please check logs and 7-Zip path)."
            elif not zipping_was_attempted and folder_count > 0:
                message += "\nZIP archive creation was skipped (7-Zip not found or specified)."
            
            QtWidgets.QMessageBox.information(self, "Organization Finished", message)
        else:
            # This implies a more significant error during the organization (file moving) stage.
            QtWidgets.QMessageBox.warning(
                self, "Organization Problem",
                f"A critical error occurred during file organization. Process may be incomplete.\n"
                f"Folders created: {folder_count}, ZIPs created: {zip_count}.\n"
                "Please check logs for detailed error messages."
            )
        
        self.refreshFileList() # Refresh to show new folder structure (though this app doesn't show folders yet)
                               # or to reflect moved files (they'll disappear from root).

    def updateStatus(self, message):
        self.statusLabel.setText(message)
        logging.info(f"Status: {message}") # Also log status updates

    def disableButtons(self):
        # Centralize button disabling
        widgets_to_disable = [
            self.mergeButton, self.mergeAllButton, self.refreshButton,
            self.convertButton, self.removeSilenceButton, self.organizeButton,
            self.selectAllButton, self.deselectAllButton, self.threadCountSpinner
        ]
        for widget in widgets_to_disable:
            widget.setEnabled(False)

    def enableButtons(self):
        # Centralize button enabling, only if no workers are active
        if self.current_workers == 0:
             widgets_to_enable = [
                 self.mergeButton, self.mergeAllButton, self.refreshButton,
                 self.convertButton, self.removeSilenceButton, self.organizeButton,
                 self.selectAllButton, self.deselectAllButton, self.threadCountSpinner
             ]
             for widget in widgets_to_enable:
                 widget.setEnabled(True)

    def closeEvent(self, event):
        if self.current_workers > 0:
             reply = QtWidgets.QMessageBox.question(
                 self, "Tasks Still Running",
                 f"{self.current_workers} background task(s) are still running.\n"
                 "Exiting now might interrupt them and leave things in an inconsistent state.\n\n"
                 "Are you sure you want to exit?",
                 QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                 QtWidgets.QMessageBox.StandardButton.No # Default to No
             )
             if reply == QtWidgets.QMessageBox.StandardButton.No:
                  event.ignore()
                  return
        
        # Attempt to gracefully quit any running QThreads if any are somehow missed by onTaskFinished logic
        # This is a fallback, normally active_threads_workers should be empty if current_workers is 0
        for thread, worker in self.active_threads_workers:
            if thread.isRunning():
                logging.info(f"Requesting quit for thread: {thread}")
                thread.quit()
                if not thread.wait(1000): # Wait up to 1 sec for thread to finish
                    logging.warning(f"Thread {thread} did not finish gracefully, terminating.")
                    thread.terminate() # Force terminate if doesn't quit
                    thread.wait() # Wait for termination

        logging.info("Closing Audio Toolbox application.")
        super().closeEvent(event)

if __name__ == "__main__":
    # Enable High DPI scaling for better visuals on high-resolution displays
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("AudioToolbox")
    app.setOrganizationName("YourOrganizationName") # Optional: For settings, etc.
    
    # Example: Set a nicer style if available
    # available_styles = QtWidgets.QStyleFactory.keys()
    # if "Fusion" in available_styles:
    #    app.setStyle(QtWidgets.QStyleFactory.create("Fusion"))
    # elif "WindowsVista" in available_styles and platform.system() == "Windows": # Or "Windows" for native
    #    app.setStyle(QtWidgets.QStyleFactory.create("WindowsVista"))


    window = MainWindow()
    window.show()
    sys.exit(app.exec_())