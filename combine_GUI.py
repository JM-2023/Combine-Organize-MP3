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

# moviepy imports
from moviepy.editor import concatenate_audioclips, AudioFileClip

# PyQt5 imports
from PyQt5 import QtCore, QtWidgets

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
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning("Failed to load config.json: %s", e)
    return {}

config = load_config()

# Configuration defaults
DATE_TIME_REGEX = config.get("date_time_regex", r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
DEFAULT_DATE_FORMAT = config.get("default_date_format", "%Y-%m-%d")
DEFAULT_TIME_FORMAT = config.get("default_time_format", "%H-%M-%S")
OUTPUT_DIR = config.get("default_output_dir", None)  # if None, use current directory
PATH_TO_7ZIP = config.get("path_to_7zip", "C:\\Program Files\\7-Zip\\7z.exe")  # Default path to 7-Zip
# Set the max number of parallel tasks based on CPU cores
MAX_WORKERS = config.get("max_workers", min(32, os.cpu_count() * 2 + 4))  # Default to CPU cores * 2 + 4, max 32

directory = os.getcwd()
if OUTPUT_DIR and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_audio_clip(file_path):
    """
    Load an audio clip from the given file path using moviepy.
    Returns the AudioFileClip if successful, otherwise returns None.
    """
    try:
        clip = AudioFileClip(file_path)
        return clip
    except Exception as e:
        logging.error("Error loading clip %s: %s", file_path, e)
        return None

# Compile regex pattern
date_time_pattern = re.compile(DATE_TIME_REGEX)

def parse_date_and_time_from_filename(filename):
    """Parse the date and time from the filename using the regex."""
    match = date_time_pattern.search(filename)
    if match:
        date_str, time_str = match.groups()[:2]
        try:
            date = datetime.strptime(date_str, DEFAULT_DATE_FORMAT).date()
        except ValueError:
            return None, None
        try:
            time = datetime.strptime(time_str, DEFAULT_TIME_FORMAT).time()
        except ValueError:
            try:
                time = datetime.strptime(time_str, "%H-%M").time()
            except ValueError:
                return None, None
        return date, time
    return None, None

def parse_time_from_filename(filename):
    """Return a datetime combining the parsed date and time (or a minimal datetime if parsing fails)."""
    date, time = parse_date_and_time_from_filename(filename)
    if date and time:
        return datetime.combine(date, time)
    return datetime.min

# ----------------------------
# Merging Function for MP3 Files (supports multiple days)
# ----------------------------

def process_files(files, output_dir, progress_callback=None):
    """
    Given a list of MP3 file names (which may come from different days), load, concatenate,
    and write the merged MP3 file. Returns (success_flag, output_file_path).
    
    Parameters:
        files (list): List of MP3 file names to process
        output_dir (str): Directory to save the output file
        progress_callback (function): Optional callback function to report progress
    """
    # Sort files by the parsed datetime
    files.sort(key=lambda x: parse_time_from_filename(x))
    file_paths = [os.path.join(directory, f) for f in files]
    
    if progress_callback:
        progress_callback(f"Loading {len(files)} audio files...")

    # Load audio clips in parallel
    audio_clips = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Create a map of future to filename for better error reporting
        future_to_file = {executor.submit(load_audio_clip, file_path): file_path for file_path in file_paths}
        
        for i, future in enumerate(as_completed(future_to_file)):
            file_path = future_to_file[future]
            if progress_callback and i % 5 == 0:  # Update progress every 5 files
                progress_callback(f"Loaded {i}/{len(files)} audio files...")
            try:
                clip = future.result()
                if clip and clip.duration > 0:
                    audio_clips.append(clip)
            except Exception as e:
                logging.error(f"Error processing {file_path}: {e}")

    if not audio_clips:
        logging.warning("No valid audio clips found in the selection.")
        return False, None

    total_duration = sum(clip.duration for clip in audio_clips)
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    logging.info(f"Merging {len(files)} files with total duration: {minutes} minutes and {seconds} seconds.")
    
    if progress_callback:
        progress_callback(f"Merging {len(audio_clips)} audio clips ({minutes}m {seconds}s total)...")

    # Use the first and last file for naming.
    first_clip_filename = files[0]
    last_clip_filename = files[-1]
    first_date, first_time = parse_date_and_time_from_filename(first_clip_filename)
    last_date, _ = parse_date_and_time_from_filename(last_clip_filename)
    
    if not first_date or not first_time:
        logging.error(f"Could not parse date/time from filename: {first_clip_filename}")
        return False, None

    # Create an output filename.
    if first_date == last_date:
        output_filename = f"{first_date.strftime('%Y%m%d')} {first_time.strftime('%H-%M')}.mp3"
    else:
        output_filename = f"{first_date.strftime('%Y%m%d')}-{last_date.strftime('%Y%m%d')} {first_time.strftime('%H-%M')}.mp3"
    
    if output_dir:
        output_path = os.path.join(output_dir, output_filename)
    else:
        output_path = os.path.join(directory, output_filename)

    logging.info(f"Merging files into: {output_filename}")
    try:
        final_clip = concatenate_audioclips(audio_clips)
        if progress_callback:
            progress_callback(f"Writing final audio file to {output_filename}...")
        final_clip.write_audiofile(output_path)
        # Close all clips
        for c in audio_clips:
            c.close()
        final_clip.close()
        logging.info(f"Merge complete! Output saved as: {output_path}")
        return True, output_path
    except Exception as e:
        logging.error("Error during merging: %s", e)
        return False, None

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
    try:
        audio_file = os.path.splitext(video_file)[0] + '.mp3'
        video_path = os.path.join(directory, video_file)
        clip = AudioFileClip(video_path)
        output_path = os.path.join(directory, audio_file)
        clip.write_audiofile(output_path, codec='mp3', logger=None)  # Disable moviepy logging
        clip.close()
        if progress_callback:
            progress_callback(f"Converted {index+1}/{total}: {video_file}")
        return True, video_file
    except Exception as e:
        logging.error(f"Error converting {video_file}: {e}")
        return False, video_file

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
        input_file = os.path.join(directory, file)
        base, ext = os.path.splitext(file)
        output_file = os.path.join(directory, f"{base}_nosilence{ext}")
        
        # Use the silenceremove filter
        command = [
            ffmpeg_path,
            "-y",  # overwrite output file if it exists
            "-i", input_file,
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.1:stop_threshold=-50dB",
            output_file
        ]
        
        # Run ffmpeg command
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if progress_callback:
            progress_callback(f"Processed {index+1}/{total}: {file}")
        
        return True, file
    except Exception as e:
        logging.error(f"Error removing silence from {file}: {e}")
        return False, file

# ----------------------------
# Function to process a date group for organization
# ----------------------------

def process_date_group(args):
    """
    Process a single date group for organization.
    Creates a folder and moves files into it.
    
    Parameters:
        args (tuple): (date, files, working_directory, progress_callback, index, total_dates)
    
    Returns:
        tuple: (date, folder_path, success)
    """
    date, files, working_directory, progress_callback, index, total_dates = args
    
    try:
        files.sort()  # Sort files by time
        folder_name = f"{date} {files[0][0]}"
        folder_path = os.path.join(working_directory, folder_name)
        
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        
        for _, file in files:
            source_path = os.path.join(working_directory, file)
            dest_path = os.path.join(folder_path, file)
            try:
                shutil.move(source_path, dest_path)
            except Exception as e:
                logging.error(f"Error moving file {file}: {e}")
        
        if progress_callback:
            progress_callback(f"Organized folder {index+1}/{total_dates}: {folder_name}")
        
        return date, folder_path, True
    except Exception as e:
        logging.error(f"Error processing date group {date}: {e}")
        return date, None, False

# ----------------------------
# Function to create a ZIP archive
# ----------------------------

def create_zip_archive(args):
    """
    Create a ZIP archive for a folder.
    
    Parameters:
        args (tuple): (folder_name, folder_path, path_to_7zip, working_directory, progress_callback, index, total)
    
    Returns:
        tuple: (folder_name, success)
    """
    folder_name, folder_path, path_to_7zip, working_directory, progress_callback, index, total = args
    
    try:
        zip_name = f"{folder_name}.zip"
        zip_path = os.path.join(working_directory, zip_name)
        
        # Build the 7-Zip command
        zip_command = [
            path_to_7zip,
            "a",        # add to archive
            zip_path,   # archive name
            folder_path # folder to compress
        ]
        
        # Run the 7-Zip command
        result = subprocess.run(
            zip_command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        
        success = result.returncode == 0
        
        if progress_callback:
            if success:
                progress_callback(f"Created ZIP {index+1}/{total}: {zip_name}")
            else:
                progress_callback(f"Failed to create ZIP {index+1}/{total}: {zip_name}")
        
        return folder_name, success
    except Exception as e:
        logging.error(f"Error creating ZIP for {folder_name}: {e}")
        return folder_name, False

# ----------------------------
# PyQt5 Worker Classes
# ----------------------------

class MergeWorker(QtCore.QObject):
    """
    Worker object to run the merge process in a separate thread.
    Emits a finished signal when done.
    """
    finished = QtCore.pyqtSignal(bool, str, list)  # success, output_path, merged_files
    progress = QtCore.pyqtSignal(str)
    
    def __init__(self, files, output_dir, parent=None):
        super().__init__(parent)
        self.files = files
        self.output_dir = output_dir
        
    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Merging files...")
        success, output_path = process_files(self.files, self.output_dir, self.progress.emit)
        self.finished.emit(success, output_path if output_path else "", self.files)

class ConvertWorker(QtCore.QObject):
    """
    Worker object to run MP4 to MP3 conversion in a separate thread.
    Emits a finished signal when done.
    """
    finished = QtCore.pyqtSignal(bool, int)  # success, count of files converted
    progress = QtCore.pyqtSignal(str)
    
    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Converting MP4 files to MP3...")
        mp4_files = [f for f in os.listdir(directory) if f.lower().endswith('.mp4')]
        count = 0
        successful = 0
        
        if not mp4_files:
            self.finished.emit(False, count)
            return
        
        try:
            total = len(mp4_files)
            self.progress.emit(f"Found {total} MP4 files to convert")
            
            # Create arguments for parallel processing
            args_list = [(file, self.progress.emit, i, total) for i, file in enumerate(mp4_files)]
            
            # Process files in parallel
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(convert_mp4_to_mp3, args): args[0] for args in args_list}
                
                for future in as_completed(future_to_file):
                    success, file = future.result()
                    count += 1
                    if success:
                        successful += 1
            
            self.progress.emit(f"Conversion complete. Successfully converted {successful}/{count} files.")
            self.finished.emit(True, successful)
        except Exception as e:
            logging.error(f"Error during MP4 to MP3 conversion: {e}")
            self.finished.emit(False, count)

# ----------------------------
# New Feature: Remove Silence from Audio using ffmpeg.exe
# ----------------------------

class RemoveSilenceWorker(QtCore.QObject):
    """
    Worker object to remove silent parts from selected audio files using ffmpeg.exe.
    Silence is defined as below -50dB and segments longer than 40ms.
    For each input file, a new file with '_nosilence' appended to its name is created.
    """
    finished = QtCore.pyqtSignal(bool, int)  # success flag, count of processed files
    progress = QtCore.pyqtSignal(str)
    
    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files
        
    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Removing silence from selected files...")
        ffmpeg_path = os.path.join(directory, "ffmpeg.exe")
        if not os.path.isfile(ffmpeg_path):
            logging.error("ffmpeg.exe not found in the current directory.")
            self.finished.emit(False, 0)
            return
        
        try:
            total = len(self.files)
            self.progress.emit(f"Processing {total} files to remove silence")
            
            # Create arguments for parallel processing
            args_list = [(file, ffmpeg_path, self.progress.emit, i, total) for i, file in enumerate(self.files)]
            
            # Process files in parallel
            successful = 0
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {executor.submit(remove_silence_from_file, args): args[0] for args in args_list}
                
                for future in as_completed(future_to_file):
                    success, file = future.result()
                    if success:
                        successful += 1
            
            self.progress.emit(f"Silence removal complete. Successfully processed {successful}/{total} files.")
            self.finished.emit(True, successful)
        except Exception as e:
            logging.error(f"Error during silence removal: {e}")
            self.finished.emit(False, 0)

# ----------------------------
# New Feature: Organize MP3 Files by Date and Create ZIP archives
# ----------------------------

class OrganizeWorker(QtCore.QObject):
    """
    Worker object to organize MP3 files by date, move them to folders, and create ZIP archives.
    """
    finished = QtCore.pyqtSignal(bool, int, int)  # success flag, folder count, zip count
    progress = QtCore.pyqtSignal(str)
    
    def __init__(self, path_to_7zip, parent=None):
        super().__init__(parent)
        self.path_to_7zip = path_to_7zip
        
    @QtCore.pyqtSlot()
    def run(self):
        self.progress.emit("Organizing MP3 files by date...")
        
        # Check if 7-Zip exists
        if not os.path.isfile(self.path_to_7zip):
            logging.error("7-Zip executable not found at %s", self.path_to_7zip)
            self.progress.emit("Warning: 7-Zip not found. Files will be organized without creating ZIP archives.")
            can_zip = False
        else:
            can_zip = True
        
        # Working directory
        working_directory = os.getcwd()
        
        # Get all mp3 files in the current directory
        mp3_files = [f for f in os.listdir(working_directory) if f.lower().endswith('.mp3')]
        
        # Create a dictionary to store files by date
        files_by_date = defaultdict(list)
        
        # Extract date and time and organize files by date
        for file in mp3_files:
            date, time = parse_date_and_time_from_filename(file)
            if date and time:
                formatted_date = date.strftime('%Y%m%d')  # Format as YYYYMMDD
                files_by_date[formatted_date].append((time.strftime('%H-%M'), file))
        
        if not files_by_date:
            self.progress.emit("No MP3 files with valid date/time found.")
            self.finished.emit(False, 0, 0)
            return
        
        try:
            # Process date groups in parallel
            total_dates = len(files_by_date)
            self.progress.emit(f"Organizing {total_dates} date groups...")
            
            # Create arguments for parallel processing
            args_list = [(date, files, working_directory, self.progress.emit, i, total_dates) 
                        for i, (date, files) in enumerate(files_by_date.items())]
            
            # Process date groups in parallel
            processed_folders = []
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_dates)) as executor:
                future_to_date = {executor.submit(process_date_group, args): args[0] for args in args_list}
                
                for future in as_completed(future_to_date):
                    date, folder_path, success = future.result()
                    if success and folder_path:
                        folder_name = os.path.basename(folder_path)
                        processed_folders.append((folder_name, folder_path))
            
            folder_count = len(processed_folders)
            
            # Create ZIP archives in parallel if 7-Zip is available
            zip_count = 0
            if can_zip and processed_folders:
                total_folders = len(processed_folders)
                self.progress.emit(f"Creating {total_folders} ZIP archives...")
                
                # Create arguments for parallel ZIP creation
                zip_args_list = [(folder_name, folder_path, self.path_to_7zip, working_directory, self.progress.emit, i, total_folders) 
                               for i, (folder_name, folder_path) in enumerate(processed_folders)]
                
                # Create ZIP archives in parallel
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_folders)) as executor:
                    future_to_folder = {executor.submit(create_zip_archive, args): args[0] for args in zip_args_list}
                    
                    for future in as_completed(future_to_folder):
                        folder_name, success = future.result()
                        if success:
                            zip_count += 1
            
            self.progress.emit(f"Organization complete. Created {folder_count} folders and {zip_count} ZIP archives.")
            self.finished.emit(True, folder_count, zip_count)
        except Exception as e:
            logging.error(f"Error during organization: {e}")
            self.finished.emit(False, 0, 0)

# ----------------------------
# PyQt5 GUI Implementation
# ----------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MP3 Merger & MP4 Converter")
        self.resize(900, 600)
        self.merged_files = set()  # Keep track of merged file names in this session
        self.initUI()
        self.refreshFileList()
        
    def initUI(self):
        centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(centralWidget)
        layout = QtWidgets.QVBoxLayout(centralWidget)
        
        # Title label with modern styling
        titleLabel = QtWidgets.QLabel("MP3 Merger & MP4 Converter")
        font = titleLabel.font()
        font.setPointSize(20)
        font.setBold(True)
        titleLabel.setFont(font)
        titleLabel.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(titleLabel)
        
        # Tree widget to list dates and MP3 files
        self.treeWidget = QtWidgets.QTreeWidget()
        self.treeWidget.setHeaderLabels(["File Name"])
        layout.addWidget(self.treeWidget)
        
        # Buttons layout
        buttonLayout = QtWidgets.QHBoxLayout()
        
        self.mergeButton = QtWidgets.QPushButton("Merge Selected Files")
        self.mergeButton.clicked.connect(self.mergeSelectedFiles)
        buttonLayout.addWidget(self.mergeButton)
        
        self.mergeAllButton = QtWidgets.QPushButton("Merge All for Selected Date")
        self.mergeAllButton.clicked.connect(self.mergeAllForSelectedDate)
        buttonLayout.addWidget(self.mergeAllButton)
        
        self.refreshButton = QtWidgets.QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.refreshFileList)
        buttonLayout.addWidget(self.refreshButton)
        
        self.convertButton = QtWidgets.QPushButton("Convert MP4 to MP3")
        self.convertButton.clicked.connect(self.convertMp4Files)
        buttonLayout.addWidget(self.convertButton)
        
        # Button to remove silence from selected audio files
        self.removeSilenceButton = QtWidgets.QPushButton("Remove Silence")
        self.removeSilenceButton.clicked.connect(self.removeSilenceSelectedFiles)
        buttonLayout.addWidget(self.removeSilenceButton)
        
        # New button for organizing files by date and creating ZIP archives
        self.organizeButton = QtWidgets.QPushButton("Organize Files")
        self.organizeButton.clicked.connect(self.organizeFiles)
        buttonLayout.addWidget(self.organizeButton)
        
        layout.addLayout(buttonLayout)
        
        # Progress bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)
        
        # Status label for showing current operation
        self.statusLabel = QtWidgets.QLabel("")
        layout.addWidget(self.statusLabel)

        # Add a separator to distinguish file operation buttons from selection buttons
        buttonLayout.addStretch()

        # Button to select all files
        self.selectAllButton = QtWidgets.QPushButton("Select All Files")
        self.selectAllButton.clicked.connect(self.selectAllFiles)
        buttonLayout.addWidget(self.selectAllButton)

        # Button to deselect all files
        self.deselectAllButton = QtWidgets.QPushButton("Deselect All")
        self.deselectAllButton.clicked.connect(self.deselectAllFiles)
        buttonLayout.addWidget(self.deselectAllButton)
        
        # Add the thread count configuration
        configLayout = QtWidgets.QHBoxLayout()
        
        configLayout.addWidget(QtWidgets.QLabel("Max Parallel Tasks:"))
        
        self.threadCountSpinner = QtWidgets.QSpinBox()
        self.threadCountSpinner.setMinimum(1)
        self.threadCountSpinner.setMaximum(64)
        self.threadCountSpinner.setValue(MAX_WORKERS)
        self.threadCountSpinner.valueChanged.connect(self.updateThreadCount)
        configLayout.addWidget(self.threadCountSpinner)
        
        configLayout.addStretch()
        
        # Add CPU core indicator
        cpu_cores = os.cpu_count()
        configLayout.addWidget(QtWidgets.QLabel(f"CPU Cores: {cpu_cores}"))
        
        layout.addLayout(configLayout)

    def updateThreadCount(self, value):
        """Update the MAX_WORKERS global variable when the spinner changes."""
        global MAX_WORKERS
        MAX_WORKERS = value
        logging.info(f"Maximum worker threads set to: {MAX_WORKERS}")

    def selectAllFiles(self):
        root = self.treeWidget.invisibleRootItem()
        count = 0
        for i in range(root.childCount()):
            dateItem = root.child(i)
            for j in range(dateItem.childCount()):
                childItem = dateItem.child(j)
                if not childItem.isDisabled():
                    childItem.setCheckState(0, QtCore.Qt.Checked)
                    count += 1
        self.statusLabel.setText(f"Selected {count} files.")

    def deselectAllFiles(self):
        root = self.treeWidget.invisibleRootItem()
        for i in range(root.childCount()):
            dateItem = root.child(i)
            for j in range(dateItem.childCount()):
                childItem = dateItem.child(j)
                if not childItem.isDisabled():
                    childItem.setCheckState(0, QtCore.Qt.Unchecked)
        self.statusLabel.setText("All files deselected.")
        
    def refreshFileList(self):
        """
        Scan the current directory for MP3 files, group them by date, and update the tree view.
        """
        self.treeWidget.clear()
        grouped_files = defaultdict(list)
        for f in os.listdir(directory):
            if f.lower().endswith('.mp3'):
                date, _ = parse_date_and_time_from_filename(f)
                if date:
                    grouped_files[date].append(f)
        # Add items to the tree widget (dates as top-level items)
        for date in sorted(grouped_files.keys()):
            date_str = date.strftime('%Y-%m-%d')
            dateItem = QtWidgets.QTreeWidgetItem([date_str])
            # Make the top-level item not selectable
            dateItem.setFlags(dateItem.flags() & ~QtCore.Qt.ItemIsSelectable)
            self.treeWidget.addTopLevelItem(dateItem)
            
            # Sort files (by time) and add as child items with checkboxes
            files = sorted(grouped_files[date], key=parse_time_from_filename)
            for file in files:
                childItem = QtWidgets.QTreeWidgetItem([file])
                childItem.setFlags(childItem.flags() | QtCore.Qt.ItemIsUserCheckable)
                if file in self.merged_files:
                    childItem.setCheckState(0, QtCore.Qt.Checked)
                    childItem.setDisabled(True)
                else:
                    childItem.setCheckState(0, QtCore.Qt.Unchecked)
                # Store the file's date in the item for later use
                childItem.setData(0, QtCore.Qt.UserRole, date)
                dateItem.addChild(childItem)
            dateItem.setExpanded(True)
        
    def getSelectedFiles(self):
        """
        Returns a dictionary mapping dates to lists of selected (checked) file names.
        """
        selected_files = defaultdict(list)
        root = self.treeWidget.invisibleRootItem()
        for i in range(root.childCount()):
            dateItem = root.child(i)
            for j in range(dateItem.childCount()):
                childItem = dateItem.child(j)
                if childItem.checkState(0) == QtCore.Qt.Checked and not childItem.isDisabled():
                    file_date = childItem.data(0, QtCore.Qt.UserRole)
                    selected_files[file_date].append(childItem.text(0))
        return selected_files
    
    def mergeSelectedFiles(self):
        """
        Merge only the files that have been checked.
        This version allows selection of files from different dates.
        """
        selected = self.getSelectedFiles()
        if not selected:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one file to merge.")
            return
        
        # Flatten the dictionary into a list of file names.
        all_files = []
        for file_list in selected.values():
            all_files.extend(file_list)
            
        self.startMerge(all_files)
        
    def mergeAllForSelectedDate(self):
        """
        Merge all (non-merged) files for the date corresponding to the selected top-level item.
        """
        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            QtWidgets.QMessageBox.warning(self, "No Date Selected", "Please select a date from the list.")
            return
        # If a child item is selected, use its parent instead
        item = selectedItems[0]
        if item.parent() is not None:
            item = item.parent()
        date_str = item.text(0)
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid Date", "Selected date is invalid.")
            return
        files = []
        for j in range(item.childCount()):
            child = item.child(j)
            if not child.isDisabled():
                files.append(child.text(0))
        if not files:
            QtWidgets.QMessageBox.information(self, "No Files", "No unmerged files available for this date.")
            return
        self.startMerge(files)
        
    def startMerge(self, files):
        """
        Start the merging process in a background thread.
        """
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # indefinite (busy) indicator
        self.statusLabel.setText("Merging files...")
        self.disableButtons()
        
        self.thread = QtCore.QThread()
        self.worker = MergeWorker(files, OUTPUT_DIR)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.updateStatus)
        self.worker.finished.connect(self.onMergeFinished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        
    def onMergeFinished(self, success, output_path, merged_files_list):
        """
        Called when the merge worker finishes.
        Updates the UI and marks the merged files as merged.
        """
        self.progressBar.setVisible(False)
        self.statusLabel.setText("")
        self.enableButtons()
        if success:
            QtWidgets.QMessageBox.information(self, "Merge Complete",
                                              f"Merge completed successfully!\nOutput: {output_path}")
            # Mark the merged files so that they become disabled in the list.
            self.merged_files.update(merged_files_list)
            self.refreshFileList()
        else:
            QtWidgets.QMessageBox.critical(self, "Merge Failed", "An error occurred during the merge process.")
        
    def convertMp4Files(self):
        """
        Start the MP4 to MP3 conversion process in a background thread.
        """
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # indefinite (busy) indicator
        self.statusLabel.setText("Converting MP4 files to MP3...")
        self.disableButtons()
        
        self.convertThread = QtCore.QThread()
        self.convertWorker = ConvertWorker()
        self.convertWorker.moveToThread(self.convertThread)
        self.convertThread.started.connect(self.convertWorker.run)
        self.convertWorker.progress.connect(self.updateStatus)
        self.convertWorker.finished.connect(self.onConvertFinished)
        self.convertWorker.finished.connect(self.convertThread.quit)
        self.convertWorker.finished.connect(self.convertWorker.deleteLater)
        self.convertThread.finished.connect(self.convertThread.deleteLater)
        self.convertThread.start()
        
    def onConvertFinished(self, success, count):
        """
        Called when the conversion worker finishes.
        Updates the UI and notifies the user.
        """
        self.progressBar.setVisible(False)
        self.statusLabel.setText("")
        self.enableButtons()
        if success:
            QtWidgets.QMessageBox.information(self, "Conversion Complete",
                                              f"Successfully converted {count} MP4 files to MP3.")
        else:
            QtWidgets.QMessageBox.warning(self, "Conversion",
                                          "No MP4 files found or an error occurred during conversion.")
        # After conversion, refresh the file list (in case new MP3s were created)
        self.refreshFileList()
    
    def removeSilenceSelectedFiles(self):
        """
        Remove silent parts from the selected MP3 files using ffmpeg.exe.
        """
        selected = self.getSelectedFiles()
        if not selected:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one audio file to process.")
            return
        
        # Flatten the dictionary into a list of file names.
        all_files = []
        for file_list in selected.values():
            all_files.extend(file_list)
        
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # indefinite (busy) indicator
        self.statusLabel.setText("Removing silence from audio files...")
        self.disableButtons()
        
        self.silenceThread = QtCore.QThread()
        self.silenceWorker = RemoveSilenceWorker(all_files)
        self.silenceWorker.moveToThread(self.silenceThread)
        self.silenceThread.started.connect(self.silenceWorker.run)
        self.silenceWorker.progress.connect(self.updateStatus)
        self.silenceWorker.finished.connect(self.onRemoveSilenceFinished)
        self.silenceWorker.finished.connect(self.silenceThread.quit)
        self.silenceWorker.finished.connect(self.silenceWorker.deleteLater)
        self.silenceThread.finished.connect(self.silenceThread.deleteLater)
        self.silenceThread.start()
        
    def onRemoveSilenceFinished(self, success, count):
        """
        Called when the remove silence worker finishes.
        Updates the UI and notifies the user.
        """
        self.progressBar.setVisible(False)
        self.statusLabel.setText("")
        self.enableButtons()
        if success:
            QtWidgets.QMessageBox.information(self, "Silence Removal Complete",
                                              f"Removed silence from {count} file(s).")
        else:
            QtWidgets.QMessageBox.warning(self, "Silence Removal",
                                          "An error occurred during silence removal.")
        # Refresh the file list in case new MP3 files were created.
        self.refreshFileList()
    
    def organizeFiles(self):
        """
        Organize MP3 files by date, move them to folders, and create ZIP archives.
        """
        reply = QtWidgets.QMessageBox.question(
            self, 
            "Organize Files", 
            "This will organize all MP3 files by date, move them to folders, and create ZIP archives. Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        # Ask for the path to 7-Zip if not found in config
        path_to_7zip = PATH_TO_7ZIP
        if not os.path.isfile(path_to_7zip):
            path_to_7zip, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select 7-Zip Executable",
                os.path.expanduser("~"),
                "Executable Files (*.exe)"
            )
            if not path_to_7zip:
                path_to_7zip = ""  # Empty string will trigger the warning in the worker
        
        self.progressBar.setVisible(True)
        self.progressBar.setRange(0, 0)  # indefinite (busy) indicator
        self.statusLabel.setText("Organizing files by date...")
        self.disableButtons()
        
        self.organizeThread = QtCore.QThread()
        self.organizeWorker = OrganizeWorker(path_to_7zip)
        self.organizeWorker.moveToThread(self.organizeThread)
        self.organizeThread.started.connect(self.organizeWorker.run)
        self.organizeWorker.progress.connect(self.updateStatus)
        self.organizeWorker.finished.connect(self.onOrganizeFinished)
        self.organizeWorker.finished.connect(self.organizeThread.quit)
        self.organizeWorker.finished.connect(self.organizeWorker.deleteLater)
        self.organizeThread.finished.connect(self.organizeThread.deleteLater)
        self.organizeThread.start()
    
    def onOrganizeFinished(self, success, folder_count, zip_count):
        """
        Called when the organization worker finishes.
        Updates the UI and notifies the user.
        """
        self.progressBar.setVisible(False)
        self.statusLabel.setText("")
        self.enableButtons()
        if success:
            QtWidgets.QMessageBox.information(
                self, 
                "Organization Complete",
                f"Successfully organized files into {folder_count} folders and created {zip_count} ZIP archives."
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, 
                "Organization",
                "An error occurred during file organization."
            )
        # Refresh the file list in case files were moved
        self.refreshFileList()
    
    def updateStatus(self, message):
        """
        Update the status label with the current operation message.
        """
        self.statusLabel.setText(message)
    
    def disableButtons(self):
        self.mergeButton.setEnabled(False)
        self.mergeAllButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.removeSilenceButton.setEnabled(False)
        self.organizeButton.setEnabled(False)
        self.selectAllButton.setEnabled(False)  # Disable select all button
        self.deselectAllButton.setEnabled(False)  # Disable deselect all button
        self.threadCountSpinner.setEnabled(False)  # Disable thread count spinner
    
    def enableButtons(self):
        """
        Enable all operation buttons after a background task completes.
        """
        self.mergeButton.setEnabled(True)
        self.mergeAllButton.setEnabled(True)
        self.refreshButton.setEnabled(True)
        self.convertButton.setEnabled(True)
        self.removeSilenceButton.setEnabled(True)
        self.organizeButton.setEnabled(True)
        self.selectAllButton.setEnabled(True)  # Enable select all button
        self.deselectAllButton.setEnabled(True)  # Enable deselect all button
        self.threadCountSpinner.setEnabled(True)  # Enable thread count spinner

if __name__ == "__main__":
    import platform
    app = QtWidgets.QApplication(sys.argv)
    
    # Adjust appearance based on platform
    if platform.system() == "Darwin":
        # Use the macOS native style if available
        app.setStyle("macintosh")
        mac_style = """
        /* macOS-like appearance */
        QWidget {
            background-color: #FFFFFF;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 14px;
        }
        QMainWindow {
            background-color: #FFFFFF;
        }
        QLabel {
            color: #333333;
        }
        QPushButton {
            background-color: #E0E0E0;
            border: 1px solid #B0B0B0;
            border-radius: 4px;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background-color: #D0D0D0;
        }
        QPushButton:pressed {
            background-color: #C0C0C0;
        }
        QTreeWidget {
            background-color: #FFFFFF;
            border: 1px solid #C0C0C0;
            border-radius: 4px;
        }
        QTreeWidget::item {
            padding: 5px;
        }
        QTreeWidget::item:selected {
            background-color: #007AFF;
            color: #FFFFFF;
        }
        QProgressBar {
            border: 1px solid #C0C0C0;
            border-radius: 4px;
            text-align: center;
            background-color: #FFFFFF;
        }
        QProgressBar::chunk {
            background-color: #007AFF;
            border-radius: 4px;
        }
        """
        app.setStyleSheet(mac_style)
    else:
        # Retain the original futuristic style on non-macOS platforms.
        style = """
        /* Futuristic style for non-macOS platforms */
        QWidget {
            background-color: #f7f8fa;
            color: #333333;
            font-family: 'Roboto', sans-serif;
            font-size: 14px;
        }
        QMainWindow {
            background-color: #f7f8fa;
        }
        QLabel {
            color: #333333;
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0067b9, stop:1 #69b3e7);
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0088d4, stop:1 #69b3e7);
        }
        QPushButton:pressed {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #005a99, stop:1 #69b3e7);
        }
        QTreeWidget {
            background-color: #ffffff;
            border: 1px solid #cccccc;
            border-radius: 5px;
        }
        QTreeWidget::item {
            padding: 5px;
        }
        QTreeWidget::item:selected {
            background-color: #ffc107;
            color: #333333;
        }
        QProgressBar {
            border: 1px solid #cccccc;
            border-radius: 5px;
            text-align: center;
            background-color: #ffffff;
        }
        QProgressBar::chunk {
            background-color: #0067b9;
            border-radius: 5px;
        }
        """
        app.setStyleSheet(style)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())