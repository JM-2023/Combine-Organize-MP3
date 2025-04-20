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

# moviepy imports
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
            # Specify UTF-8 encoding, though JSON standard is usually fine without it
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
# Set the max number of parallel tasks based on CPU cores
# Ensure os.cpu_count() returns a value, default to 1 if it returns None
MAX_WORKERS = config.get("max_workers", min(32, (os.cpu_count() or 1) * 2 + 4))

# Ensure the output directory exists
current_directory = os.getcwd() # Rename 'directory' to avoid conflict with built-in names
output_directory_path = OUTPUT_DIR if OUTPUT_DIR else current_directory
if not os.path.exists(output_directory_path):
    os.makedirs(output_directory_path, exist_ok=True)

def load_audio_clip(file_path):
    """
    Load an audio clip from the given file path using moviepy.
    Returns the AudioFileClip if successful, otherwise returns None.
    """
    try:
        # Check if file exists and is not empty
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
             logging.warning("File does not exist or is empty: %s", file_path)
             return None
        clip = AudioFileClip(file_path)
        # Additional check to ensure clip loaded successfully and has duration
        if clip is None or clip.duration is None or clip.duration <= 0:
            logging.warning("Failed to load clip or clip has invalid duration: %s", file_path)
            if clip:
                clip.close() # Attempt to close to release resources
            return None
        return clip
    except Exception as e:
        # More detailed error logging
        import traceback
        logging.error("Error loading clip %s: %s\n%s", file_path, e, traceback.format_exc())
        return None

# Compile regex pattern
date_time_pattern = re.compile(DATE_TIME_REGEX)

def parse_date_and_time_from_filename(filename):
    """Parse the date and time from the filename using the regex."""
    match = date_time_pattern.search(filename)
    if match:
        # Ensure capture groups exist
        groups = match.groups()
        if len(groups) >= 2:
            date_str = groups[0]
            time_str = groups[1]
            # Try format with seconds if the third group (seconds) exists and is not None
            time_format_to_try = DEFAULT_TIME_FORMAT if len(groups) > 2 and groups[2] else "%H-%M"

            parsed_date = None
            parsed_time = None

            try:
                parsed_date = datetime.strptime(date_str, DEFAULT_DATE_FORMAT).date()
            except ValueError:
                logging.warning(f"Could not parse date '{date_str}' with format '{DEFAULT_DATE_FORMAT}' (from file: {filename})")
                return None, None # If date is invalid, return immediately

            try:
                parsed_time = datetime.strptime(time_str, time_format_to_try).time()
            except ValueError:
                # If format with seconds failed, try format without seconds
                if time_format_to_try == DEFAULT_TIME_FORMAT:
                    try:
                        parsed_time = datetime.strptime(time_str, "%H-%M").time()
                    except ValueError:
                        logging.warning(f"Could not parse time '{time_str}' with format '{DEFAULT_TIME_FORMAT}' or '%H-%M' (from file: {filename})")
                        # To maintain consistency with original logic, return None, None if time fails
                        return None, None
                else: # If the format without seconds (%H-%M) also failed
                    logging.warning(f"Could not parse time '{time_str}' with format '%H-%M' (from file: {filename})")
                    return None, None

            return parsed_date, parsed_time
        else:
             logging.warning(f"Regex matched in filename '{filename}', but capture groups are insufficient.")
    else:
        # Use debug level for non-matching files to avoid flooding logs
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
             return datetime.min # Return min on error
    return datetime.min # Return min on parsing failure

# ----------------------------
# Merging Function for MP3 Files (supports multiple days)
# ----------------------------

def process_files(files, output_dir_path, progress_callback=None):
    """
    Given a list of MP3 file names (which may come from different days), load, concatenate,
    and write the merged MP3 file. Returns (success_flag, output_file_path).

    Parameters:
        files (list): List of MP3 file names to process
        output_dir_path (str): Directory path to save the output file
        progress_callback (function): Optional callback function to report progress
    """
    if not files:
        logging.warning("No files provided for processing.")
        return False, None

    # Sort files by the parsed datetime
    try:
        # Add error handling in case parse_time_from_filename returns non-datetime objects
        files.sort(key=lambda x: parse_time_from_filename(x))
    except TypeError as e:
        logging.error(f"Error sorting files, possibly due to invalid datetime parsing: {e}")
        # Optionally stop here, or try to continue (order might be wrong)
        return False, None # Choose to stop to avoid potential issues

    file_paths = [os.path.join(current_directory, f) for f in files]

    if progress_callback:
        progress_callback(f"Loading {len(files)} audio files...")

    # Load audio clips in parallel
    audio_clips = []
    valid_files_for_merge = [] # Store original filenames of successfully loaded and valid clips
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Map future to (file_path, original_filename) for better error reporting and filename tracking
        future_to_file = {executor.submit(load_audio_clip, file_path): (file_path, os.path.basename(file_path)) for file_path in file_paths}

        processed_count = 0
        for future in as_completed(future_to_file):
            file_path, original_filename = future_to_file[future]
            processed_count += 1
            if progress_callback: # Update progress in real-time
                 progress_callback(f"Loaded {processed_count}/{len(files)} audio files...")

            try:
                clip = future.result()
                # Ensure clip is not None and has a valid duration
                if clip and clip.duration is not None and clip.duration > 0:
                    audio_clips.append(clip)
                    valid_files_for_merge.append(original_filename) # Add corresponding original filename
                elif clip:
                     logging.warning(f"Skipping file (invalid duration or loading issue): {file_path}")
                     clip.close() # Attempt to close if clip exists but is invalid
                else:
                     logging.warning(f"Skipping file (load failed): {file_path}")

            except Exception as e:
                import traceback
                logging.error(f"An error occurred while processing file {file_path}: {e}\n{traceback.format_exc()}")


    if not audio_clips:
        logging.warning("No valid audio clips found in the selection.")
        if progress_callback:
            progress_callback("No valid audio clips found.")
        return False, None

    # Log a warning if not all files were loaded successfully
    if len(valid_files_for_merge) < len(files):
         logging.warning(f"Note: {len(files) - len(valid_files_for_merge)} file(s) were skipped due to loading errors or invalid duration.")


    # Ensure we only use successfully loaded filenames to determine the output name
    if not valid_files_for_merge:
         logging.error("No files loaded successfully, cannot determine output filename.")
         # Clean up loaded clips
         for c in audio_clips:
             c.close()
         return False, None

    # Use the first and last *valid* file for naming
    first_valid_clip_filename = valid_files_for_merge[0]
    last_valid_clip_filename = valid_files_for_merge[-1]

    first_date, first_time = parse_date_and_time_from_filename(first_valid_clip_filename)
    # Parse date from the last valid filename, time part not needed
    last_date_str = ""
    match_last = date_time_pattern.search(last_valid_clip_filename)
    if match_last:
        last_date_str = match_last.group(1) # Get only the date part 'YYYY-MM-DD'
    else:
        logging.warning(f"Could not parse date from the last valid filename '{last_valid_clip_filename}'. Using the first date.")
        # Fallback to first_date if available, or handle error
        last_date_str = first_date.strftime(DEFAULT_DATE_FORMAT) if first_date else "" # Use first date if available


    if not first_date or not first_time:
        logging.error(f"Could not parse date/time from the first valid filename: {first_valid_clip_filename}")
         # Clean up loaded clips
        for c in audio_clips:
             c.close()
        return False, None

    # Format dates as YYYYMMDD
    first_date_formatted = first_date.strftime('%Y%m%d')
    # Parse last_date_str to format it (if different from first_date)
    last_date_formatted = ""
    if last_date_str:
        try:
             last_date_obj = datetime.strptime(last_date_str, DEFAULT_DATE_FORMAT).date()
             if last_date_obj != first_date:
                 last_date_formatted = last_date_obj.strftime('%Y%m%d')
             else:
                 last_date_formatted = first_date_formatted # Dates are the same
        except ValueError:
             logging.warning(f"Could not convert parsed last date string '{last_date_str}' to date object. Using the first date.")
             last_date_formatted = first_date_formatted # Fallback to first date


    # Create an output filename.
    time_formatted = first_time.strftime('%H-%M') # Always use the time from the first file
    if first_date_formatted == last_date_formatted or not last_date_formatted:
         # Same date or last date couldn't be parsed
         output_filename = f"{first_date_formatted} {time_formatted}.mp3"
    else:
         # Different dates
         output_filename = f"{first_date_formatted}-{last_date_formatted} {time_formatted}.mp3"

    # -- Sanitize output filename --
    # Remove or replace characters that might be illegal in filenames (e.g., / \ : * ? " < > |)
    output_filename = re.sub(r'[\\/*?:"<>|]', '_', output_filename)
    # Could also limit filename length if needed

    output_path = os.path.join(output_dir_path, output_filename)


    total_duration = sum(clip.duration for clip in audio_clips)
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    logging.info(f"Merging {len(audio_clips)} valid files (from {len(files)} selected), total duration: {minutes}m {seconds}s. Output to: {output_filename}")


    if progress_callback:
        progress_callback(f"Merging {len(audio_clips)} audio clips ({minutes}m {seconds}s total)...")

    final_clip = None # Initialize final_clip
    try:
        final_clip = concatenate_audioclips(audio_clips)
        if progress_callback:
            progress_callback(f"Writing final audio file to {output_filename}...")

        # Use logger=None to prevent moviepy console output unless debugging
        # Show progress bar only if logging level is DEBUG
        final_clip.write_audiofile(output_path, codec='mp3', logger='bar' if logging.getLogger().isEnabledFor(logging.DEBUG) else None)

        logging.info(f"Merge complete! Output saved as: {output_path}")
        return True, output_path
    except Exception as e:
        import traceback
        logging.error("Error during merging: %s\n%s", e, traceback.format_exc())
        return False, None
    finally:
        # Ensure all clips are closed, including the final one
        for c in audio_clips:
            try:
                c.close()
            except Exception as close_err:
                 logging.warning(f"Error closing intermediate clip: {close_err}")
        if final_clip: # Check if final_clip was successfully created
             try:
                 final_clip.close()
             except Exception as close_err:
                 logging.warning(f"Error closing final clip: {close_err}")


# ----------------------------
# Conversion Function: Convert MP4 to MP3
# ----------------------------

def convert_mp4_to_mp3(args):
    """
    Convert a single MP4 file to an MP3 file.
    The output file will have the same base name with a .mp3 extension.

    Parameters:
        args (tuple): (video_file, progress_callback, index, total)
    """
    video_file, progress_callback, index, total = args
    clip = None # Initialize clip to None
    try:
        video_path = os.path.join(current_directory, video_file)
        # Check if file exists
        if not os.path.exists(video_path):
            logging.error(f"File not found, cannot convert: {video_path}")
            if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: File not found {video_file}")
            return False, video_file

        audio_file_base = os.path.splitext(video_file)[0]
        audio_file = f"{audio_file_base}.mp3"
        # Output to the current directory, could be changed to output_directory_path if needed
        output_path = os.path.join(current_directory, audio_file)

        # Extract audio using AudioFileClip
        clip = AudioFileClip(video_path)
        if clip is None or clip.duration is None or clip.duration <= 0:
             logging.error(f"Could not load audio from {video_file} or audio has invalid duration.")
             if clip: clip.close() # Attempt to close
             if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: Cannot load audio {video_file}")
             return False, video_file

        # Write MP3 file, disable moviepy logger to keep console clean
        clip.write_audiofile(output_path, codec='mp3', logger=None)
        clip.close() # Close the clip to release resources
        clip = None # Explicitly set back to None

        if progress_callback:
            progress_callback(f"Converted {index+1}/{total}: {video_file} -> {audio_file}")
        logging.info(f"Successfully converted {video_file} to {output_path}")
        return True, video_file
    except Exception as e:
        import traceback
        logging.error(f"Error converting {video_file}: {e}\n{traceback.format_exc()}")
        if progress_callback:
             progress_callback(f"Error {index+1}/{total}: Conversion failed {video_file}")
        return False, video_file
    finally:
        # Ensure clip is closed in any case (if it was created)
        if clip:
            try:
                clip.close()
            except Exception as close_err:
                 logging.warning(f"Error closing clip for {video_file}: {close_err}")

# ----------------------------
# Function to process a file for silence removal
# ----------------------------

def remove_silence_from_file(args):
    """
    Remove silence from a single audio file using ffmpeg.

    Parameters:
        args (tuple): (file, ffmpeg_path, progress_callback, index, total)
    """
    file, ffmpeg_path, progress_callback, index, total = args

    try:
        input_file_path = os.path.join(current_directory, file)
        # Check if input file exists
        if not os.path.exists(input_file_path):
             logging.error(f"File not found, cannot remove silence: {input_file_path}")
             if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: File not found {file}")
             return False, file

        base, ext = os.path.splitext(file)
        # Sanitize base name in case it contains illegal characters (less likely but safe)
        safe_base = re.sub(r'[\\/*?:"<>|]', '_', base)
        output_filename = f"{safe_base}_nosilence{ext}"
        output_file_path = os.path.join(current_directory, output_filename)

        # Use the silenceremove filter
        # stop_periods=-1: Remove silence throughout the file, not just at the start.
        # stop_duration=0.1: Silence must be at least 0.1 seconds long to be removed.
        # stop_threshold=-50dB: Audio below -50dB is considered silence.
        command = [
            ffmpeg_path,
            "-y",  # Overwrite output file if it exists
            "-i", input_file_path,
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.1:stop_threshold=-50dB",
            output_file_path
        ]

        # Run ffmpeg command
        # Use subprocess.run and capture output for better error reporting
        # Add startupinfo to prevent console window popup on Windows
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        # Run the command, capture output, don't check return code automatically
        result = subprocess.run(command, check=False, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        if result.returncode != 0:
            logging.error(f"ffmpeg failed to remove silence from '{file}'. Return code: {result.returncode}")
            logging.error(f"FFmpeg stdout: {result.stdout}")
            logging.error(f"FFmpeg stderr: {result.stderr}")
            if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: Processing failed {file}")
            # Attempt to delete potentially incomplete output file
            if os.path.exists(output_file_path):
                 try:
                     os.remove(output_file_path)
                 except OSError as rm_err:
                     logging.warning(f"Could not delete failed output file {output_file_path}: {rm_err}")
            return False, file
        else:
            if progress_callback:
                progress_callback(f"Processed {index+1}/{total}: {file} -> {output_filename}")
            logging.info(f"Successfully removed silence from {file}, output as {output_filename}")
            return True, file

    except Exception as e:
        import traceback
        logging.error(f"Unexpected error removing silence from {file}: {e}\n{traceback.format_exc()}")
        if progress_callback:
             progress_callback(f"Error {index+1}/{total}: Unexpected failure {file}")
        return False, file

# ----------------------------
# Function to process a date group for organization
# ----------------------------

def process_date_group(args):
    """
    Process a single date group for organization.
    Creates a folder and moves files into it.

    Parameters:
        args (tuple): (date_str, files_with_time, working_directory, progress_callback, index, total_dates)
                     date_str is in 'YYYYMMDD' format
                     files_with_time is a list of (time_str, filename) tuples

    Returns:
        tuple: (date_str, folder_path, success)
    """
    date_str, files_with_time, working_directory, progress_callback, index, total_dates = args

    try:
        # Sort by time string ('HH-MM')
        files_with_time.sort(key=lambda item: item[0])

        # Folder name format: YYYYMMDD HH-MM (using the earliest time for that date)
        first_time_str = files_with_time[0][0] # Get 'HH-MM' from the first file
        folder_name = f"{date_str} {first_time_str}"
        # Sanitize folder name for illegal characters
        folder_name = re.sub(r'[\\/*?:"<>|]', '_', folder_name)
        folder_path = os.path.join(working_directory, folder_name)

        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        elif not os.path.isdir(folder_path):
             logging.error(f"Cannot create folder, a file with the same name already exists: {folder_path}")
             if progress_callback:
                 progress_callback(f"Error {index+1}/{total_dates}: Cannot create folder {folder_name}")
             return date_str, None, False


        moved_count = 0
        error_count = 0
        for time_str, filename in files_with_time:
            source_path = os.path.join(working_directory, filename)
            dest_path = os.path.join(folder_path, filename)

            # Check if source file exists before moving
            if not os.path.exists(source_path):
                logging.warning(f"Source file not found, skipping move: {source_path}")
                error_count += 1
                continue # Skip this file

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

        # Consider it successful as long as the main process didn't throw an exception.
        # Success doesn't necessarily mean all files were moved without error.
        return date_str, folder_path, True

    except Exception as e:
        import traceback
        logging.error(f"Error processing date group {date_str}: {e}\n{traceback.format_exc()}")
        if progress_callback:
            progress_callback(f"Error {index+1}/{total_dates}: Failed processing date group {date_str}")
        return date_str, None, False

# ----------------------------
# Function to create a ZIP archive
# ----------------------------

def create_zip_archive(args):
    """
    Create a ZIP archive for a folder using 7-Zip.

    Parameters:
        args (tuple): (folder_name, folder_path, path_to_7zip, working_directory, progress_callback, index, total)

    Returns:
        tuple: (folder_name, success)
    """
    folder_name, folder_path, path_to_7zip, working_directory, progress_callback, index, total = args

    try:
        # Ensure the source folder exists
        if not os.path.isdir(folder_path):
             logging.error(f"Source folder not found, cannot create ZIP: {folder_path}")
             if progress_callback:
                 progress_callback(f"Error {index+1}/{total}: Folder not found {folder_name}")
             return folder_name, False


        zip_name = f"{folder_name}.zip"
        # Place the zip file in the working directory
        zip_path = os.path.join(working_directory, zip_name)

        # Build the 7-Zip command
        # 'a' - add to archive
        # '-tzip' - explicitly specify ZIP format
        # '-mx=5' - set compression level (optional, 5 is normal)
        # '-r' - recursively include subdirectories (harmless here, good practice)
        zip_command = [
            path_to_7zip,
            "a",         # add to archive
            "-tzip",     # create ZIP format
            #"-mx=5",    # Optional: compression level (0=store, 9=max)
            zip_path,    # output archive name
            folder_path  # source folder path to compress
        ]

        logging.info(f"Creating ZIP archive for '{folder_name}'...")
        # Run 7-Zip command
        # Add startupinfo to prevent console window popup on Windows
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        result = subprocess.run(
            zip_command,
            stdout=subprocess.PIPE, # Capture standard output
            stderr=subprocess.PIPE, # Capture error output
            text=True,              # Decode output as text
            encoding='utf-8',       # Specify encoding
            errors='ignore',        # Ignore decoding errors
            check=False,            # Do not automatically check return code
            startupinfo=startupinfo
        )

        success = result.returncode == 0

        if progress_callback:
            if success:
                progress_callback(f"Created ZIP {index+1}/{total}: {zip_name}")
                logging.info(f"Successfully created ZIP archive: {zip_name}")
                # Optional: Delete original folder after successful compression
                # try:
                #     shutil.rmtree(folder_path)
                #     logging.info(f"Deleted original folder: {folder_path}")
                # except Exception as rm_err:
                #     logging.error(f"Error deleting folder {folder_path}: {rm_err}")
            else:
                progress_callback(f"Failed to create ZIP {index+1}/{total}: {zip_name}")
                logging.error(f"Failed to create ZIP archive '{zip_name}'. Return code: {result.returncode}")
                logging.error(f"7-Zip stdout: {result.stdout}")
                logging.error(f"7-Zip stderr: {result.stderr}")

        return folder_name, success
    except Exception as e:
        import traceback
        logging.error(f"Unexpected error creating ZIP for {folder_name}: {e}\n{traceback.format_exc()}")
        if progress_callback:
             progress_callback(f"Error {index+1}/{total}: Failed creating ZIP {folder_name}")
        return folder_name, False

# ----------------------------
# PyQt5 Worker Classes (Mostly unchanged, updated signals/progress messages)
# ----------------------------

class MergeWorker(QtCore.QObject):
    """Worker object to run the merge process in a separate thread. Emits finished signal when done."""
    finished = QtCore.pyqtSignal(bool, str, list)  # success, output_path, merged_files
    progress = QtCore.pyqtSignal(str) # Progress message signal

    def __init__(self, files, output_dir_path, parent=None):
        super().__init__(parent)
        self.files = files
        self.output_dir_path = output_dir_path # Use updated variable name

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting file merge...")
        success, output_path = process_files(self.files, self.output_dir_path, self.progress.emit)
        # Only return the list of merged files on success
        self.finished.emit(success, output_path if output_path else "", self.files if success else [])


class ConvertWorker(QtCore.QObject):
    """Worker object to run MP4 to MP3 conversion in a separate thread. Emits finished signal when done."""
    finished = QtCore.pyqtSignal(bool, int, int)  # success, successful_count, total_processed
    progress = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Scanning for MP4 files...")
        try:
            # Ensure we only list files, not directories
            mp4_files = [f for f in os.listdir(current_directory) if f.lower().endswith('.mp4') and os.path.isfile(os.path.join(current_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning for MP4 files: {e}")
            self.progress.emit("Error: Could not scan for files.")
            self.finished.emit(False, 0, 0)
            return

        total_files = len(mp4_files)
        if not mp4_files:
            self.progress.emit("No MP4 files found.")
            self.finished.emit(True, 0, 0) # Consider finding no files as a "successful" completion
            return

        self.progress.emit(f"Found {total_files} MP4 files, starting conversion...")
        successful_count = 0
        processed_count = 0

        try:
            # Create arguments for parallel processing
            args_list = [(file, self.progress.emit, i, total_files) for i, file in enumerate(mp4_files)]

            # Process files in parallel
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(convert_mp4_to_mp3, args): args[0] for args in args_list}

                for future in as_completed(future_to_file):
                    processed_count += 1
                    try:
                        success, file = future.result()
                        if success:
                            successful_count += 1
                    except Exception as e:
                         # future.result() might raise exceptions from the worker function
                         file_arg = future_to_file[future]
                         logging.error(f"Error processing future for file {file_arg}: {e}")
                         # Update progress callback about the error
                         self.progress.emit(f"Error processing file: {file_arg}")


            final_message = f"Conversion complete. Successfully converted {successful_count}/{processed_count} files."
            if processed_count < total_files:
                 final_message += f" ({total_files - processed_count} task(s) did not complete or failed)."
            self.progress.emit(final_message)
            # Consider successful if any files were converted or if no files needed processing
            self.finished.emit(successful_count > 0 or processed_count == 0, successful_count, processed_count)
        except Exception as e:
            import traceback
            logging.error(f"Error during MP4 to MP3 conversion process: {e}\n{traceback.format_exc()}")
            self.progress.emit("An error occurred during conversion.")
            self.finished.emit(False, successful_count, processed_count)


class RemoveSilenceWorker(QtCore.QObject):
    """Worker object to remove silent parts from selected audio files using ffmpeg.exe."""
    finished = QtCore.pyqtSignal(bool, int, int)  # success flag, successful_count, total_processed
    progress = QtCore.pyqtSignal(str)

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting silence removal...")
        ffmpeg_path = os.path.join(current_directory, "ffmpeg.exe")
        if not os.path.isfile(ffmpeg_path):
            logging.error("ffmpeg.exe not found in the current directory.")
            self.progress.emit("Error: ffmpeg.exe not found.")
            self.finished.emit(False, 0, 0)
            return

        total_files = len(self.files)
        if total_files == 0:
             self.progress.emit("No files selected for silence removal.")
             self.finished.emit(True, 0, 0) # No files is a successful completion
             return

        self.progress.emit(f"Processing {total_files} files to remove silence...")
        successful_count = 0
        processed_count = 0

        try:
            # Create arguments for parallel processing
            args_list = [(file, ffmpeg_path, self.progress.emit, i, total_files) for i, file in enumerate(self.files)]

            # Process files in parallel
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(remove_silence_from_file, args): args[0] for args in args_list}

                for future in as_completed(future_to_file):
                    processed_count += 1
                    try:
                        success, file = future.result()
                        if success:
                            successful_count += 1
                    except Exception as e:
                         file_arg = future_to_file[future]
                         logging.error(f"Error processing future for file {file_arg}: {e}")
                         self.progress.emit(f"Error processing file: {file_arg}")

            final_message = f"Silence removal complete. Successfully processed {successful_count}/{processed_count} files."
            if processed_count < total_files:
                 final_message += f" ({total_files - processed_count} task(s) did not complete or failed)."

            self.progress.emit(final_message)
            # Consider successful if any files were processed or if no files needed processing
            self.finished.emit(successful_count > 0 or processed_count == 0, successful_count, processed_count)
        except Exception as e:
            import traceback
            logging.error(f"Error during silence removal process: {e}\n{traceback.format_exc()}")
            self.progress.emit("An error occurred during silence removal.")
            self.finished.emit(False, successful_count, processed_count)


class OrganizeWorker(QtCore.QObject):
    """Worker object to organize MP3 files by date, move them to folders, and create ZIP archives."""
    finished = QtCore.pyqtSignal(bool, int, int)  # success flag, folder count, zip count
    progress = QtCore.pyqtSignal(str)

    def __init__(self, path_to_7zip, parent=None):
        super().__init__(parent)
        self.path_to_7zip = path_to_7zip # Store the potentially updated path

    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Starting MP3 file organization by date...")

        # Check if 7-Zip exists
        can_zip = False
        if self.path_to_7zip and os.path.isfile(self.path_to_7zip): # Check if path is valid
            can_zip = True
            logging.info(f"7-Zip found: {self.path_to_7zip}")
        else:
            logging.warning("7-Zip executable not found at %s.", self.path_to_7zip if self.path_to_7zip else "<Not Specified>")
            self.progress.emit("Warning: 7-Zip not found. Files will be organized without creating ZIP archives.")

        working_directory = current_directory # Use global variable

        # Get all mp3 files in the current directory, ensuring they are files
        try:
            all_files = os.listdir(working_directory)
            mp3_files = [f for f in all_files if f.lower().endswith('.mp3') and os.path.isfile(os.path.join(working_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning for MP3 files: {e}")
            self.progress.emit("Error: Could not scan for MP3 files.")
            self.finished.emit(False, 0, 0)
            return

        # Create a dictionary to store files by date
        files_by_date = defaultdict(list)

        # Extract date and time and organize files by date
        for file in mp3_files:
            date, time = parse_date_and_time_from_filename(file)
            if date and time:
                formatted_date = date.strftime('%Y%m%d')  # Format as YYYYMMDD
                # Store ('HH-MM', filename)
                files_by_date[formatted_date].append((time.strftime('%H-%M'), file))
            # else:
                # logging.debug(f"File '{file}' does not match date/time pattern, ignoring for organization.")


        if not files_by_date:
            self.progress.emit("No MP3 files with valid date/time found for organization.")
            self.finished.emit(True, 0, 0) # No files is a successful completion
            return

        folder_count = 0
        zip_count = 0
        processed_folders_info = [] # Store {'name': folder_name, 'path': folder_path}

        try:
            # Process date groups in parallel (move files to folders)
            total_dates = len(files_by_date)
            self.progress.emit(f"Organizing {len(mp3_files)} files into {total_dates} date groups...")

            # Create arguments for parallel processing
            args_list_organize = [
                (date_str, files_with_time, working_directory, self.progress.emit, i, total_dates)
                for i, (date_str, files_with_time) in enumerate(files_by_date.items())
            ]

            # Use thread pool to process date groups
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_dates)) as executor:
                future_to_date = {executor.submit(process_date_group, args): args[0] for args in args_list_organize}

                for future in as_completed(future_to_date):
                     # No need to unpack date_str_result here unless used
                     _, folder_path_result, success_result = future.result()
                     if success_result and folder_path_result:
                         folder_name = os.path.basename(folder_path_result)
                         processed_folders_info.append({'name': folder_name, 'path': folder_path_result})
                         folder_count += 1
                     # else:
                         # Log organizing failures if needed


            self.progress.emit(f"File organization complete. Created {folder_count} folders.")

            # Create ZIP archives in parallel if 7-Zip is available and folders were processed
            if can_zip and processed_folders_info:
                total_folders_to_zip = len(processed_folders_info)
                self.progress.emit(f"Starting ZIP archive creation for {total_folders_to_zip} folders...")

                # Create arguments for parallel ZIP creation
                zip_args_list = [
                    (info['name'], info['path'], self.path_to_7zip, working_directory, self.progress.emit, i, total_folders_to_zip)
                    for i, info in enumerate(processed_folders_info)
                ]

                # Use thread pool to create ZIPs
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_folders_to_zip)) as executor:
                    future_to_folder = {executor.submit(create_zip_archive, args): args[0] for args in zip_args_list}

                    for future in as_completed(future_to_folder):
                        # No need to unpack folder_name_result here
                        _, success_zip = future.result()
                        if success_zip:
                            zip_count += 1
                        # else:
                            # Log ZIP creation failures if needed


            final_org_message = f"Organization complete. Created {folder_count} folders."
            if can_zip: # Report zip status only if attempted
                 final_org_message += f" Successfully created {zip_count} ZIP archives."
            else:
                 final_org_message += " (ZIP creation skipped as 7-Zip was not found or specified)."

            self.progress.emit(final_org_message)
            # Consider successful if the main organization process didn't throw an error
            self.finished.emit(True, folder_count, zip_count)

        except Exception as e:
            import traceback
            logging.error(f"Error during organization process: {e}\n{traceback.format_exc()}")
            self.progress.emit("A critical error occurred during organization.")
            # Report failure even if some folders/zips were created before the error
            self.finished.emit(False, folder_count, zip_count)


# ----------------------------
# PyQt5 GUI Implementation (Modernized Look)
# ----------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Toolbox (MP3 Merge, Convert, Silence Removal, Organize)") # Updated title
        self.resize(900, 700) # Slightly larger window size
        self.merged_files = set()  # Keep track of merged file names in this session
        self.current_workers = 0 # Track number of active worker threads
        self.initUI()
        self.applyStyles() # Apply the new stylesheet
        self.refreshFileList()

    def initUI(self):
        centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(centralWidget)
        mainLayout = QtWidgets.QVBoxLayout(centralWidget)
        mainLayout.setSpacing(15) # Increased main layout spacing
        mainLayout.setContentsMargins(15, 15, 15, 15) # Added margins

        # --- Title ---
        titleLabel = QtWidgets.QLabel("Audio Toolbox")
        titleFont = titleLabel.font()
        titleFont.setPointSize(24)
        titleFont.setBold(True)
        titleLabel.setFont(titleFont)
        titleLabel.setAlignment(QtCore.Qt.AlignCenter)
        titleLabel.setStyleSheet("color: #2c3e50; margin-bottom: 10px;") # Set title color and bottom margin
        mainLayout.addWidget(titleLabel)

        # --- File List Tree ---
        self.treeWidget = QtWidgets.QTreeWidget()
        self.treeWidget.setHeaderLabels(["Date / File Name"]) # Updated header
        self.treeWidget.setAlternatingRowColors(True) # Alternating row colors
        self.treeWidget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection) # Allow multi-select
        # Allow tree widget to expand vertically
        mainLayout.addWidget(self.treeWidget, 1) # The '1' makes it stretch

        # --- Button Groups ---
        bottomLayout = QtWidgets.QHBoxLayout() # Horizontal layout for button groups and settings

        # -- Actions Group --
        actionsGroup = QtWidgets.QGroupBox("File Operations")
        actionsLayout = QtWidgets.QVBoxLayout(actionsGroup)
        actionsLayout.setSpacing(10)

        # Standard icons (try to get them, don't set icon if failed)
        icon_merge = QtGui.QIcon.fromTheme("media-skip-forward", QtGui.QIcon.fromTheme("go-jump")) # Try theme icons
        icon_merge_date = QtGui.QIcon.fromTheme("document-save-as", QtGui.QIcon.fromTheme("document-save"))
        icon_convert = QtGui.QIcon.fromTheme("utilities-terminal", QtGui.QIcon.fromTheme("applications-utilities"))
        icon_silence = QtGui.QIcon.fromTheme("audio-volume-muted", QtGui.QIcon.fromTheme("player-volume-muted"))
        icon_organize = QtGui.QIcon.fromTheme("folder-zip", QtGui.QIcon.fromTheme("package-x-generic"))
        icon_refresh = QtGui.QIcon.fromTheme("view-refresh", QtGui.QIcon.fromTheme("reload"))


        self.mergeButton = QtWidgets.QPushButton("Merge Selected")
        if not icon_merge.isNull(): self.mergeButton.setIcon(icon_merge)
        self.mergeButton.setToolTip("Merge all checked files (can span across dates)") # Add tooltip
        self.mergeButton.clicked.connect(self.mergeSelectedFiles)
        actionsLayout.addWidget(self.mergeButton)

        self.mergeAllButton = QtWidgets.QPushButton("Merge All for Date")
        if not icon_merge_date.isNull(): self.mergeAllButton.setIcon(icon_merge_date)
        self.mergeAllButton.setToolTip("Merge all unmerged files under the selected date")
        self.mergeAllButton.clicked.connect(self.mergeAllForSelectedDate)
        actionsLayout.addWidget(self.mergeAllButton)

        self.convertButton = QtWidgets.QPushButton("Convert MP4 to MP3")
        if not icon_convert.isNull(): self.convertButton.setIcon(icon_convert)
        self.convertButton.setToolTip("Convert all MP4 files in the current directory to MP3")
        self.convertButton.clicked.connect(self.convertMp4Files)
        actionsLayout.addWidget(self.convertButton)

        self.removeSilenceButton = QtWidgets.QPushButton("Remove Silence")
        if not icon_silence.isNull(): self.removeSilenceButton.setIcon(icon_silence)
        self.removeSilenceButton.setToolTip("Remove silent segments from checked files using ffmpeg")
        self.removeSilenceButton.clicked.connect(self.removeSilenceSelectedFiles)
        actionsLayout.addWidget(self.removeSilenceButton)

        self.organizeButton = QtWidgets.QPushButton("Organize & Zip")
        if not icon_organize.isNull(): self.organizeButton.setIcon(icon_organize)
        self.organizeButton.setToolTip("Organize all MP3s into date folders and create ZIPs (requires 7-Zip)")
        self.organizeButton.clicked.connect(self.organizeFiles)
        actionsLayout.addWidget(self.organizeButton)

        bottomLayout.addWidget(actionsGroup)

        # -- Selection & Refresh Group --
        selectionGroup = QtWidgets.QGroupBox("Selection & Refresh")
        selectionLayout = QtWidgets.QVBoxLayout(selectionGroup)
        selectionLayout.setSpacing(10)

        icon_select_all = QtGui.QIcon.fromTheme("edit-select-all")
        icon_deselect_all = QtGui.QIcon.fromTheme("edit-clear", QtGui.QIcon.fromTheme("edit-select-none"))

        self.selectAllButton = QtWidgets.QPushButton("Select All")
        if not icon_select_all.isNull(): self.selectAllButton.setIcon(icon_select_all)
        self.selectAllButton.setToolTip("Check all enabled files")
        self.selectAllButton.clicked.connect(self.selectAllFiles)
        selectionLayout.addWidget(self.selectAllButton)

        self.deselectAllButton = QtWidgets.QPushButton("Deselect All")
        if not icon_deselect_all.isNull(): self.deselectAllButton.setIcon(icon_deselect_all)
        self.deselectAllButton.setToolTip("Uncheck all files")
        self.deselectAllButton.clicked.connect(self.deselectAllFiles)
        selectionLayout.addWidget(self.deselectAllButton)

        self.refreshButton = QtWidgets.QPushButton("Refresh List")
        if not icon_refresh.isNull(): self.refreshButton.setIcon(icon_refresh)
        self.refreshButton.setToolTip("Rescan the current directory for files")
        self.refreshButton.clicked.connect(self.refreshFileList)
        selectionLayout.addWidget(self.refreshButton)

        selectionLayout.addStretch() # Push buttons to the top
        bottomLayout.addWidget(selectionGroup)


        # -- Settings Group (in a vertical layout to the right) --
        settingsAndStatusLayout = QtWidgets.QVBoxLayout() # Vertical layout for settings and status

        settingsGroup = QtWidgets.QGroupBox("Settings")
        settingsLayout = QtWidgets.QFormLayout(settingsGroup) # Use QFormLayout for label-widget alignment
        settingsLayout.setSpacing(10)

        self.threadCountSpinner = QtWidgets.QSpinBox()
        self.threadCountSpinner.setMinimum(1)
        # Increase max limit, useful for I/O bound tasks
        self.threadCountSpinner.setMaximum(max(64, (os.cpu_count() or 1) * 4))
        self.threadCountSpinner.setValue(MAX_WORKERS)
        self.threadCountSpinner.setToolTip("Set the maximum number of parallel processing tasks")
        self.threadCountSpinner.valueChanged.connect(self.updateThreadCount)
        settingsLayout.addRow("Max Parallel Tasks:", self.threadCountSpinner)

        cpu_cores = os.cpu_count() or 'N/A' # Get CPU core count
        cpuLabel = QtWidgets.QLabel(f"{cpu_cores}")
        settingsLayout.addRow("CPU Cores:", cpuLabel)

        settingsAndStatusLayout.addWidget(settingsGroup)
        settingsAndStatusLayout.addStretch() # Push settings group to the top

        # Add settings and status layout to the right side
        bottomLayout.addLayout(settingsAndStatusLayout)

        # Add the horizontal layout containing button groups and settings to the main layout
        mainLayout.addLayout(bottomLayout)

        # --- Progress Bar and Status Label ---
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)
        self.progressBar.setTextVisible(False) # Hide percentage text for a cleaner look
        mainLayout.addWidget(self.progressBar)

        self.statusLabel = QtWidgets.QLabel("Ready") # Initial status
        self.statusLabel.setAlignment(QtCore.Qt.AlignCenter)
        mainLayout.addWidget(self.statusLabel)


    def applyStyles(self):
        """Apply the modernized QSS stylesheet"""
        # Style Sheet using a modern, clean look
        style = """
        QWidget {
            /* Preferred fonts with fallbacks */
            font-family: "Segoe UI", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
            font-size: 10pt; /* Slightly larger base font size */
            background-color: #f8f9fa; /* Light background */
            color: #343a40; /* Darker text color */
        }
        QMainWindow {
            background-color: #f8f9fa;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #dee2e6; /* Light gray border */
            border-radius: 8px; /* Rounded corners */
            margin-top: 10px; /* Space above the group box title */
            background-color: #ffffff; /* White background for group content */
            padding: 15px 10px 10px 10px; /* Padding inside (top adjusted for title) */
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left; /* Position title at the top left */
            padding: 0 5px 5px 5px; /* Padding around the title */
            color: #0056b3; /* Blue title color */
            left: 10px; /* Indent title slightly */
            /* background-color: #f8f9fa; */ /* Optional: Match window background */
        }
        QPushButton {
            /* Blue gradient */
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #007bff, stop:1 #0056b3);
            color: white;
            border: none;
            padding: 8px 15px; /* Comfortable padding */
            border-radius: 5px; /* Rounded corners */
            min-height: 25px; /* Ensure minimum height */
            outline: none; /* Remove focus outline */
            font-weight: bold; /* Make button text bold */
        }
        QPushButton:hover {
            /* Darker blue on hover */
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0069d9, stop:1 #004fa3);
        }
        QPushButton:pressed {
            /* Even darker blue when pressed */
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #005cbf, stop:1 #004085);
        }
        QPushButton:disabled {
            background-color: #ced4da; /* Gray background when disabled */
            color: #6c757d; /* Darker gray text */
        }
        QTreeWidget {
            background-color: #ffffff; /* White background */
            border: 1px solid #ced4da; /* Light gray border */
            border-radius: 5px;
            alternate-background-color: #e9ecef; /* Subtle alternating row color */
            font-size: 9pt; /* Slightly smaller font for file list */
        }
        QTreeWidget::item {
            padding: 6px 4px; /* Item padding */
            border-radius: 3px; /* Slight rounding for selection highlight */
        }
        /* Style for selected items */
        QTreeWidget::item:selected:active {
            background-color: #007bff; /* Blue selection background */
            color: white; /* White text for selected item */
        }
        QTreeWidget::item:selected:!active { /* When widget doesn't have focus */
             background-color: #d4e8ff;
             color: #343a40;
        }
         /* Style for disabled (e.g., merged) items */
         QTreeWidget::item:disabled {
             color: #adb5bd; /* Gray text for disabled items */
             background-color: transparent; /* Ensure no background overrides selection */
         }
        QHeaderView::section {
            background-color: #e9ecef; /* Light gray header background */
            padding: 4px;
            border: none; /* No header border */
            border-bottom: 1px solid #ced4da; /* Bottom border for separation */
            font-weight: bold;
            color: #495057; /* Dark gray header text */
        }
        QProgressBar {
            border: 1px solid #ced4da; /* Light gray border */
            border-radius: 5px;
            text-align: center;
            background-color: #e9ecef; /* Light background */
            height: 12px; /* Slim progress bar */
        }
        QProgressBar::chunk {
            background-color: #28a745; /* Green progress chunk */
            border-radius: 5px;
        }
        /* Style for indeterminate (busy) progress bar */
        QProgressBar:indeterminate {
            background-color: #e9ecef;
        }
        QProgressBar:indeterminate::chunk {
            /* Animated gradient chunk */
             background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007bff, stop: 0.5 #e9ecef, stop:1 #007bff);
            /* width: 20px; */ /* Width of the moving chunk - might need animation */
        }
        QLabel#StatusLabel { /* Specific style for status label using objectName */
            color: #6c757d; /* Gray status text */
            font-size: 9pt;
            font-weight: bold; /* Make status slightly bolder */
        }
        QSpinBox {
            padding: 4px 6px;
            border: 1px solid #ced4da; /* Match other borders */
            border-radius: 4px;
            min-width: 60px; /* Ensure spinner is wide enough */
        }
        QSpinBox:disabled {
             background-color: #e9ecef; /* Disabled background */
             color: #6c757d; /* Disabled text color */
        }
        QToolTip { /* Style tooltips */
             background-color: #343a40; /* Dark background */
             color: white; /* White text */
             border: 1px solid #343a40;
             padding: 5px;
             border-radius: 4px;
             opacity: 230; /* Slightly transparent */
        }
        """
        self.setStyleSheet(style)
        # Set object name for specific styling if needed
        self.statusLabel.setObjectName("StatusLabel")


    def updateThreadCount(self, value):
        """Update the MAX_WORKERS global variable when the spinner changes."""
        global MAX_WORKERS
        MAX_WORKERS = value
        logging.info(f"Maximum worker threads set to: {MAX_WORKERS}")

    def selectAllFiles(self):
        """Check all enabled file items in the tree."""
        root = self.treeWidget.invisibleRootItem()
        count = 0
        for i in range(root.childCount()):
            dateItem = root.child(i)
            for j in range(dateItem.childCount()):
                childItem = dateItem.child(j)
                # Check if item is enabled and checkable
                if childItem.flags() & QtCore.Qt.ItemIsEnabled and childItem.flags() & QtCore.Qt.ItemIsUserCheckable:
                    childItem.setCheckState(0, QtCore.Qt.Checked)
                    count += 1
        self.updateStatus(f"Selected {count} files.")


    def deselectAllFiles(self):
        """Uncheck all checkable file items in the tree."""
        root = self.treeWidget.invisibleRootItem()
        count = 0
        for i in range(root.childCount()):
            dateItem = root.child(i)
            for j in range(dateItem.childCount()):
                childItem = dateItem.child(j)
                if childItem.flags() & QtCore.Qt.ItemIsUserCheckable: # Check if it's checkable
                     if childItem.checkState(0) == QtCore.Qt.Checked:
                         count += 1
                     childItem.setCheckState(0, QtCore.Qt.Unchecked)
        self.updateStatus(f"Deselected {count} files.")


    def refreshFileList(self):
        """
        Scan the current directory for MP3 files, group them by date, and update the tree view.
        """
        self.treeWidget.clear()
        grouped_files = defaultdict(list)
        try:
            all_files_in_dir = os.listdir(current_directory)
            # Filter for .mp3 files that are actually files (not directories)
            mp3_files = [f for f in all_files_in_dir if f.lower().endswith('.mp3') and os.path.isfile(os.path.join(current_directory, f))]
        except Exception as e:
            logging.error(f"Error scanning directory: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not scan directory for files:\n{e}")
            return

        for f in mp3_files:
            date, time = parse_date_and_time_from_filename(f)
            if date:
                 # Store (filename, datetime object for sorting)
                 timestamp = datetime.combine(date, time) if time else datetime.combine(date, datetime.min.time())
                 grouped_files[date].append((f, timestamp))
            # else: # File doesn't match pattern, ignore
                # logging.debug(f"File '{f}' ignored (doesn't match date/time pattern).")


        # Add items to the tree widget (dates as top-level items)
        root = self.treeWidget.invisibleRootItem()
        file_count = 0
        for date in sorted(grouped_files.keys()):
            date_str = date.strftime('%Y-%m-%d')
            dateItem = QtWidgets.QTreeWidgetItem([date_str])
            # Make top-level item non-selectable but checkable (for selecting all children)
            dateItem.setFlags(dateItem.flags() & ~QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate)
            dateItem.setCheckState(0, QtCore.Qt.Unchecked)

            # Make date font bold
            font = dateItem.font(0)
            font.setBold(True)
            dateItem.setFont(0, font)

            # Add to the tree root
            root.addChild(dateItem)

            # Sort files by timestamp and add as child items with checkboxes
            files_sorted = sorted(grouped_files[date], key=lambda item: item[1]) # Sort by datetime object
            for filename, timestamp in files_sorted:
                file_count += 1
                childItem = QtWidgets.QTreeWidgetItem([filename])
                childItem.setFlags(childItem.flags() | QtCore.Qt.ItemIsUserCheckable)

                if filename in self.merged_files:
                    childItem.setCheckState(0, QtCore.Qt.Checked) # Show merged files as checked
                    childItem.setDisabled(True) # Disable merged files
                    # Optional: Change appearance of merged files (handled by QSS :disabled state)
                    # childItem.setForeground(0, QtGui.QColor('gray'))
                else:
                    childItem.setCheckState(0, QtCore.Qt.Unchecked)

                # Store the file's date and optionally full path in the item for later use
                childItem.setData(0, QtCore.Qt.UserRole, date)
                # childItem.setData(0, QtCore.Qt.UserRole + 1, os.path.join(current_directory, filename)) # Store full path if needed

                dateItem.addChild(childItem)
            dateItem.setExpanded(True) # Expand date items by default

        self.treeWidget.resizeColumnToContents(0) # Adjust column width to fit content
        self.updateStatus(f"Ready. Found {file_count} MP3 files.")


    def getSelectedFiles(self):
        """
        Returns a flat list of selected (checked) file names that are not disabled.
        Also includes files under a checked date item.
        """
        selected_files_list = []
        processed_files = set() # Avoid duplicates if date and file are checked

        root = self.treeWidget.invisibleRootItem()
        iterator = QtWidgets.QTreeWidgetItemIterator(self.treeWidget) # Iterate all items

        while iterator.value():
            item = iterator.value()
            # Process checked file items first
            if item.checkState(0) == QtCore.Qt.Checked:
                parent = item.parent()
                # Is it a file item (has a parent which is not the root)?
                if parent and parent is not root:
                    # Is it enabled?
                    if not item.isDisabled():
                        filename = item.text(0)
                        if filename not in processed_files:
                            selected_files_list.append(filename)
                            processed_files.add(filename)
                # Is it a date item (parent is root)?
                elif parent is root:
                     # Add all enabled children of the checked date item
                     for j in range(item.childCount()):
                          child = item.child(j)
                          if not child.isDisabled(): # Only add enabled files
                               filename = child.text(0)
                               if filename not in processed_files:
                                    selected_files_list.append(filename)
                                    processed_files.add(filename)
            iterator += 1

        # Sort the final list based on the parseable time from filename for consistency
        selected_files_list.sort(key=parse_time_from_filename)

        return selected_files_list


    def mergeSelectedFiles(self):
        """
        Merge all checked (and enabled) files. Allows selecting files across different dates.
        """
        selected_files_list = self.getSelectedFiles() # Get flat list of checked, enabled files

        if not selected_files_list:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please check at least one file to merge.")
            return

        logging.info(f"Preparing to merge {len(selected_files_list)} selected files.")
        self.startMerge(selected_files_list)


    def mergeAllForSelectedDate(self):
        """
        Merge all enabled (unmerged) files under the currently selected date item in the tree.
        """
        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            QtWidgets.QMessageBox.warning(self, "No Date Selected", "Please select a date item in the list first.")
            return

        # Find the top-level date item that is selected or contains the selection
        dateItem = None
        item = selectedItems[0]
        # If a date item itself is selected
        if item.parent() is None or item.parent() == self.treeWidget.invisibleRootItem():
            dateItem = item
        # If a file item under a date is selected, get its parent
        elif item.parent() is not None and (item.parent().parent() is None or item.parent().parent() == self.treeWidget.invisibleRootItem()):
             dateItem = item.parent()

        if dateItem is None:
             QtWidgets.QMessageBox.warning(self, "Invalid Selection", "Please select a valid date item or a file under it.")
             return


        date_str = dateItem.text(0)
        logging.info(f"Preparing to merge all unmerged files under date '{date_str}'.")

        files_to_merge = []
        for j in range(dateItem.childCount()):
            child = dateItem.child(j)
            # Check if the child item is enabled (i.e., not already merged)
            if not child.isDisabled():
                files_to_merge.append(child.text(0))

        if not files_to_merge:
            QtWidgets.QMessageBox.information(self, "No Files", f"No files available to merge under date '{date_str}'.")
            return

        logging.info(f"Found {len(files_to_merge)} files to merge for date {date_str}.")
        # Sort them by time before starting merge
        files_to_merge.sort(key=parse_time_from_filename)
        self.startMerge(files_to_merge)


    def startTask(self, worker_class, *args, finish_slot, progress_message):
        """Generic function to start a background task."""
        self.current_workers += 1
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # Set to indeterminate mode
        self.updateStatus(progress_message)
        self.disableButtons()

        thread = QtCore.QThread()
        worker = worker_class(*args)
        worker.moveToThread(thread)

        # Connect signals and slots
        thread.started.connect(worker.run)
        worker.progress.connect(self.updateStatus)
        worker.finished.connect(finish_slot) # Connect to specific finish handler
        worker.finished.connect(self.onTaskFinished) # Connect to generic handler
        worker.finished.connect(thread.quit) # Quit thread when worker finishes
        # Schedule cleanup using functools.partial
        cleanup_slot = functools.partial(self.schedule_worker_cleanup, worker, thread)
        worker.finished.connect(cleanup_slot)

        # Store references for potential management (though cleanup is scheduled)
        if not hasattr(self, 'active_threads'):
             self.active_threads = []
        self.active_threads.append((thread, worker))

        thread.start()

    def schedule_worker_cleanup(self, worker, thread):
         """Safely schedule cleanup after signals are processed."""
         worker.deleteLater()
         thread.deleteLater()
         # Remove from active list
         self.active_threads = [(t, w) for t, w in self.active_threads if w != worker]


    def onTaskFinished(self):
        """Generic cleanup when any task finishes."""
        self.current_workers -= 1
        if self.current_workers <= 0:
            self.current_workers = 0 # Ensure it doesn't go negative
            self.progressBar.setVisible(False)
            self.progressBar.setRange(0, 100) # Reset to determinate mode
            self.progressBar.setValue(0)
            self.statusLabel.setText("Ready") # Reset status
            self.enableButtons()
        else:
             logging.info(f"A task finished, but {self.current_workers} task(s) are still running. Buttons remain disabled.")


    def startMerge(self, files):
        """Start the merge process."""
        # Determine output directory based on config or current dir
        output_dir = output_directory_path # Use the globally determined path
        self.startTask(MergeWorker, files, output_dir,
                       finish_slot=self.onMergeFinishedSpecific, # Use specific handler first
                       progress_message="Merging files...")

    def onMergeFinishedSpecific(self, success, output_path, merged_files_list):
        """Callback specific to merge worker completion."""
        if success:
            QtWidgets.QMessageBox.information(self, "Merge Complete",
                                              f"Merge successful!\nOutput: {output_path}")
            # Mark the merged files so they become disabled in the list.
            self.merged_files.update(merged_files_list)
            self.refreshFileList() # Refresh list to show disabled items
        else:
            QtWidgets.QMessageBox.critical(self, "Merge Failed", "An error occurred during the merge process. Please check logs for details.")
        # Generic cleanup (like enabling buttons) is handled by onTaskFinished connected separately


    def convertMp4Files(self):
        """Start the MP4 to MP3 conversion process."""
        self.startTask(ConvertWorker, # No extra args for ConvertWorker.__init__
                       finish_slot=self.onConvertFinishedSpecific,
                       progress_message="Converting MP4 files to MP3...")


    def onConvertFinishedSpecific(self, success, successful_count, total_processed):
        """Callback specific to conversion worker completion."""
        if total_processed == 0 and success: # No files found is considered success
             QtWidgets.QMessageBox.information(self, "Conversion", "No MP4 files found to convert.")
        elif success:
             QtWidgets.QMessageBox.information(self, "Conversion Complete",
                                               f"Successfully converted {successful_count}/{total_processed} MP4 files to MP3.")
        else: # success is False
             message = "An error occurred during conversion."
             if successful_count > 0:
                  message += f" Converted {successful_count} files successfully, but {total_processed - successful_count} failed."
             QtWidgets.QMessageBox.warning(self, "Conversion Problem", message + " Please check logs.")

        # Refresh file list after conversion (in case new MP3s were created)
        self.refreshFileList()
        # Generic cleanup handled by onTaskFinished


    def removeSilenceSelectedFiles(self):
        """Remove silent parts from the selected MP3 files using ffmpeg.exe."""
        selected_files_list = self.getSelectedFiles()
        if not selected_files_list:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please check at least one audio file to process.")
            return

        # Check if ffmpeg.exe exists before starting the task
        ffmpeg_path = os.path.join(current_directory, "ffmpeg.exe")
        if not os.path.isfile(ffmpeg_path):
            QtWidgets.QMessageBox.critical(self, "Error", f"ffmpeg.exe not found in the application directory:\n{current_directory}\n\nCannot remove silence.")
            return

        logging.info(f"Preparing to remove silence from {len(selected_files_list)} selected files.")
        self.startTask(RemoveSilenceWorker, selected_files_list,
                       finish_slot=self.onRemoveSilenceFinishedSpecific,
                       progress_message="Removing silence from audio files...")


    def onRemoveSilenceFinishedSpecific(self, success, successful_count, total_processed):
        """Callback specific to remove silence worker completion."""
        if success:
            QtWidgets.QMessageBox.information(self, "Silence Removal Complete",
                                              f"Successfully processed {successful_count}/{total_processed} file(s).")
        else:
             message = "An error occurred during silence removal."
             if successful_count > 0:
                  message += f" Processed {successful_count} files successfully, but {total_processed - successful_count} failed."

             # Check if the failure might be due to missing ffmpeg (though checked before starting)
             ffmpeg_path = os.path.join(current_directory, "ffmpeg.exe")
             if not os.path.isfile(ffmpeg_path):
                  message += "\nError: ffmpeg.exe was not found."

             QtWidgets.QMessageBox.warning(self, "Silence Removal Problem", message + " Please check logs.")

        # Refresh file list as new files might have been created (_nosilence)
        self.refreshFileList()
        # Generic cleanup handled by onTaskFinished


    def organizeFiles(self):
        """Organize MP3 files by date, move them to folders, and create ZIP archives."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm File Organization", # Title
            "This action will organize all MP3 files in the current directory by date, move them into new folders, and attempt to create a ZIP archive for each folder.\n\nOriginal MP3 files will be MOVED. Please confirm.\n\nContinue?", # Message text
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No, # Buttons
            QtWidgets.QMessageBox.StandardButton.No # Default button
        )

        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        # Check or ask for 7-Zip path
        path_to_7zip = PATH_TO_7ZIP # Get from config or default
        effective_7zip_path = "" # Path to pass to worker

        if path_to_7zip and os.path.isfile(path_to_7zip):
            effective_7zip_path = path_to_7zip
            logging.info(f"Using 7-Zip path from config/default: {effective_7zip_path}")
        else:
            logging.warning(f"7-Zip path from config/default is invalid or not set: {path_to_7zip}")
            # Try finding it in common locations
            common_paths = [
                "C:\\Program Files\\7-Zip\\7z.exe",
                "C:\\Program Files (x86)\\7-Zip\\7z.exe",
                "/usr/bin/7z", # Linux common path
                "/usr/local/bin/7z" # Another common path
            ]
            found = False
            for p in common_paths:
                if os.path.isfile(p):
                    effective_7zip_path = p
                    logging.info(f"Auto-detected 7-Zip at: {effective_7zip_path}")
                    found = True
                    break

            if not found:
                # Ask user only if not found automatically
                selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self,
                    "Select 7-Zip Executable (7z.exe or 7z)",
                    os.path.expanduser("~"), # Start directory
                    "Executable Files (*.exe);;All Files (*)" # File filter
                )
                if selected_path and os.path.isfile(selected_path):
                    effective_7zip_path = selected_path
                    logging.info(f"User selected 7-Zip path: {effective_7zip_path}")
                else:
                    # User cancelled or selected invalid file
                    QtWidgets.QMessageBox.warning(self, "7-Zip Not Found", "Could not find 7-Zip executable.\nFiles will be organized into folders, but ZIP archives will not be created.")
                    effective_7zip_path = "" # Pass empty string to worker to indicate no zipping

        logging.info(f"Starting file organization. Using 7-Zip path: '{effective_7zip_path if effective_7zip_path else 'N/A'}'")
        # Pass the determined path (or empty string) to the worker
        self.startTask(OrganizeWorker, effective_7zip_path,
                       finish_slot=self.onOrganizeFinishedSpecific,
                       progress_message="Organizing files by date...")


    def onOrganizeFinishedSpecific(self, success, folder_count, zip_count):
        """Callback specific to organization worker completion."""
        # Access the path used by the worker if needed (e.g., via self.sender())
        worker_instance = self.sender()
        zipping_attempted = bool(worker_instance.path_to_7zip) if worker_instance else False

        if success:
            message = f"Successfully organized files into {folder_count} folders."
            if zipping_attempted:
                 if zip_count == folder_count and folder_count > 0:
                     message += f" Successfully created {zip_count} ZIP archives."
                 elif zip_count > 0:
                      message += f" Successfully created {zip_count}/{folder_count} ZIP archives."
                 elif folder_count > 0: # Zipping attempted but failed for all
                      message += f" However, failed to create any ZIP archives (0/{folder_count}). Please check 7-Zip path and logs."
                 # else: folder_count is 0, message already covers it.
            # else: Zipping was not attempted, message already covers folder creation.

            QtWidgets.QMessageBox.information(self, "Organization Complete", message)
        else:
            # Organization process itself failed
            QtWidgets.QMessageBox.warning(
                self,
                "Organization Problem",
                f"An error occurred during file organization. Created {folder_count} folders and {zip_count} ZIPs (process may be incomplete).\nPlease check logs for details."
            )
        # Refresh file list as files have been moved
        self.refreshFileList()
        # Generic cleanup handled by onTaskFinished


    def updateStatus(self, message):
        """Update the status label text and log the message."""
        self.statusLabel.setText(message)
        # Avoid logging redundancy if message comes directly from worker logging
        # logging.info(message)


    def disableButtons(self):
        """Disable all action buttons and settings to prevent concurrent operations."""
        widgets_to_disable = [
            self.mergeButton, self.mergeAllButton, self.refreshButton,
            self.convertButton, self.removeSilenceButton, self.organizeButton,
            self.selectAllButton, self.deselectAllButton, self.threadCountSpinner
        ]
        for widget in widgets_to_disable:
            widget.setEnabled(False)

    def enableButtons(self):
        """Enable all action buttons and settings after background task(s) complete."""
        # Only enable if no other workers are running
        if self.current_workers == 0:
             widgets_to_enable = [
                 self.mergeButton, self.mergeAllButton, self.refreshButton,
                 self.convertButton, self.removeSilenceButton, self.organizeButton,
                 self.selectAllButton, self.deselectAllButton, self.threadCountSpinner
             ]
             for widget in widgets_to_enable:
                 widget.setEnabled(True)
        # else: Keep buttons disabled if other tasks are still running


    def closeEvent(self, event):
        """Handle window close event."""
        # Optional: Add logic here to gracefully stop running threads if desired.
        # This can be complex. A simple approach is just to log and exit.
        if self.current_workers > 0:
             reply = QtWidgets.QMessageBox.question(
                 self,
                 "Tasks Running",
                 f"{self.current_workers} task(s) are still running in the background.\nExiting now might interrupt them.\n\nAre you sure you want to exit?",
                 QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                 QtWidgets.QMessageBox.StandardButton.No
             )
             if reply == QtWidgets.QMessageBox.StandardButton.No:
                  event.ignore() # Prevent closing
                  return

        logging.info("Closing application.")
        # Terminating threads forcefully is generally unsafe.
        # Let Python's exit process handle cleanup if user confirms exit.
        # for thread, worker in getattr(self, 'active_threads', []):
        #     if thread.isRunning():
        #         thread.terminate() # Forceful termination (use with caution)
        super().closeEvent(event)


if __name__ == "__main__":
    # Ensure GUI scales well on high-DPI displays
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)

    # Set application info (optional, used by some OS features)
    app.setApplicationName("AudioToolbox")
    app.setOrganizationName("YourOrganization") # Optional

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())