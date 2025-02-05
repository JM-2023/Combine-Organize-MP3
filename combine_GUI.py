import os
import sys
import re
import json
import logging
import subprocess
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
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

def process_files(files, output_dir):
    """
    Given a list of MP3 file names (which may come from different days), load, concatenate,
    and write the merged MP3 file. Returns (success_flag, output_file_path).
    """
    # Sort files by the parsed datetime
    files.sort(key=lambda x: parse_time_from_filename(x))
    file_paths = [os.path.join(directory, f) for f in files]

    # Load audio clips in parallel
    audio_clips = []
    with ThreadPoolExecutor() as executor:
        futures = list(executor.map(load_audio_clip, file_paths))
        for clip in futures:
            if clip and clip.duration > 0:
                audio_clips.append(clip)

    if not audio_clips:
        logging.warning("No valid audio clips found in the selection.")
        return False, None

    total_duration = sum(clip.duration for clip in audio_clips)
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    logging.info(f"Merging {len(files)} files with total duration: {minutes} minutes and {seconds} seconds.")

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

def convert_mp4_to_mp3(video_file):
    """
    Convert a single MP4 file to an MP3 file.
    The output file will have the same base name with a .mp3 extension.
    """
    audio_file = os.path.splitext(video_file)[0] + '.mp3'
    video_path = os.path.join(directory, video_file)
    clip = AudioFileClip(video_path)
    output_path = os.path.join(directory, audio_file)
    clip.write_audiofile(output_path, codec='mp3')
    clip.close()

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
        count = 0
        for file in self.files:
            input_file = os.path.join(directory, file)
            base, ext = os.path.splitext(file)
            output_file = os.path.join(directory, f"{base}_nosilence{ext}")
            # Use the silenceremove filter:
            # stop_periods=-1 : removes all silence segments throughout the file.
            # stop_duration=0.04 : silence segments must be longer than 40ms.
            # stop_threshold=-50dB : silence is considered below -50dB.
            command = [
                ffmpeg_path,
                "-y",  # overwrite output file if it exists
                "-i", input_file,
                "-af", "silenceremove=stop_periods=-1:stop_duration=0.04:stop_threshold=-50dB",
                output_file
            ]
            try:
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                count += 1
            except Exception as e:
                logging.error("Error removing silence from file %s: %s", file, e)
        self.finished.emit(True, count)

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
        success, output_path = process_files(self.files, self.output_dir)
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
        if not mp4_files:
            self.finished.emit(False, count)
            return
        try:
            with ThreadPoolExecutor() as executor:
                list(executor.map(convert_mp4_to_mp3, mp4_files))
            count = len(mp4_files)
            self.finished.emit(True, count)
        except Exception as e:
            logging.error("Error during MP4 to MP3 conversion: %s", e)
            self.finished.emit(False, count)

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
        
        # New button to remove silence from selected audio files
        self.removeSilenceButton = QtWidgets.QPushButton("Remove Silence")
        self.removeSilenceButton.clicked.connect(self.removeSilenceSelectedFiles)
        buttonLayout.addWidget(self.removeSilenceButton)
        
        layout.addLayout(buttonLayout)
        
        # Indefinite progress bar (hidden until an operation starts)
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)
        
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
        self.mergeButton.setEnabled(False)
        self.mergeAllButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.removeSilenceButton.setEnabled(False)
        
        self.thread = QtCore.QThread()
        self.worker = MergeWorker(files, OUTPUT_DIR)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
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
        self.mergeButton.setEnabled(True)
        self.mergeAllButton.setEnabled(True)
        self.refreshButton.setEnabled(True)
        self.convertButton.setEnabled(True)
        self.removeSilenceButton.setEnabled(True)
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
        self.mergeButton.setEnabled(False)
        self.mergeAllButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.removeSilenceButton.setEnabled(False)
        
        self.convertThread = QtCore.QThread()
        self.convertWorker = ConvertWorker()
        self.convertWorker.moveToThread(self.convertThread)
        self.convertThread.started.connect(self.convertWorker.run)
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
        self.mergeButton.setEnabled(True)
        self.mergeAllButton.setEnabled(True)
        self.refreshButton.setEnabled(True)
        self.convertButton.setEnabled(True)
        self.removeSilenceButton.setEnabled(True)
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
        self.mergeButton.setEnabled(False)
        self.mergeAllButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.removeSilenceButton.setEnabled(False)
        
        self.silenceThread = QtCore.QThread()
        self.silenceWorker = RemoveSilenceWorker(all_files)
        self.silenceWorker.moveToThread(self.silenceThread)
        self.silenceThread.started.connect(self.silenceWorker.run)
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
        self.mergeButton.setEnabled(True)
        self.mergeAllButton.setEnabled(True)
        self.refreshButton.setEnabled(True)
        self.convertButton.setEnabled(True)
        self.removeSilenceButton.setEnabled(True)
        if success:
            QtWidgets.QMessageBox.information(self, "Silence Removal Complete",
                                              f"Removed silence from {count} file(s).")
        else:
            QtWidgets.QMessageBox.warning(self, "Silence Removal",
                                          "An error occurred during silence removal.")
        # Refresh the file list in case new MP3 files were created.
        self.refreshFileList()

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
