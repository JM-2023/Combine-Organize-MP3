#!/usr/bin/env python3
"""
Clean GUI implementation with checkboxes, timezone colors, and MP4 support.
Only presentation logic, no business logic.
"""
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt, pyqtSignal, QThread, pyqtProperty
from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtGui import QColor, QPainter, QBrush
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import logging
import pytz

from audio_models import AudioFile, TaskType, ProcessingTask, FileState
from audio_processor import AudioProcessor
from file_organizer import FileOrganizer, FileGroup


class ColoredItemDelegate(QStyledItemDelegate):
    """Custom delegate to paint background colors for tree items"""
    
    def paint(self, painter, option, index):
        """Custom paint method to draw background colors"""
        # Get color from item data
        color = index.data(Qt.UserRole + 2)  # Color stored at UserRole + 2
        
        if color:
            painter.save()
            painter.fillRect(option.rect, QColor(color))
            
            # Semi-transparent selection overlay
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(220, 154, 98, 30))
            
            painter.restore()
        
        # Draw the text and other elements
        super().paint(painter, option, index)


class ProcessingThread(QThread):
    """Single worker thread type for all operations"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)  # TaskResult
    
    def __init__(self, processor: AudioProcessor, task: ProcessingTask):
        super().__init__()
        self.processor = processor
        self.task = task
    
    def run(self):
        """Execute task in thread"""
        result = self.processor.process_task(
            self.task, 
            progress_callback=self.progress.emit
        )
        self.finished.emit(result)


class AudioToolboxGUI(QtWidgets.QMainWindow):
    """Clean GUI with checkboxes, colors, and full feature support"""
    
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        self.processor = AudioProcessor(config)
        self.current_thread = None
        self.selected_timezone = self.config.get('default_timezone', 'Asia/Shanghai')
        
        # File organization handler
        self.organizer = FileOrganizer(self.selected_timezone)
        
        # Track merged and output files
        self.merged_files = set()
        self.output_files = {}
        
        self.init_ui()
        self.refresh_files()
    
    def init_ui(self):
        """Initialize UI components"""
        self.setWindowTitle("Audio Toolbox")
        self.setMinimumSize(1000, 700)
        
        # Central widget
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Title
        title = QtWidgets.QLabel("Audio Toolbox Pro")
        title_font = QtGui.QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Main content area
        content_layout = QtWidgets.QHBoxLayout()
        
        # Left side - File tree
        tree_group = QtWidgets.QGroupBox("Files by Date")
        tree_layout = QtWidgets.QVBoxLayout(tree_group)
        
        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setHeaderLabels(["File", "Time", "State", "Size"])
        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.file_tree.setAlternatingRowColors(False)  # We'll use custom colors
        
        # Set column widths - make file column much wider
        self.file_tree.setColumnWidth(0, 400)  # File column - wide enough for filenames
        self.file_tree.setColumnWidth(1, 80)   # Time column
        self.file_tree.setColumnWidth(2, 100)  # State column
        self.file_tree.setColumnWidth(3, 80)   # Size column
        
        # Set custom delegate for coloring
        self.color_delegate = ColoredItemDelegate(self.file_tree)
        self.file_tree.setItemDelegate(self.color_delegate)
        
        tree_layout.addWidget(self.file_tree)
        content_layout.addWidget(tree_group, stretch=3)
        
        # Right side - Controls
        controls_layout = QtWidgets.QVBoxLayout()
        
        # Operations panel
        ops_group = QtWidgets.QGroupBox("Operations")
        ops_layout = QtWidgets.QVBoxLayout(ops_group)
        
        operations = [
            ("📥 Import OBS", self.import_files),
            ("🎬 Convert to MP3", self.convert_selected),
            ("🎵 Merge Selected", self.merge_selected),
            ("📅 Merge by Date", self.merge_by_date),
            ("🔇 Remove Silence", self.remove_silence),
            ("📦 Organize", self.organize_files),
        ]
        
        for text, callback in operations:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(callback)
            ops_layout.addWidget(btn)
        
        controls_layout.addWidget(ops_group)
        
        # Selection panel
        sel_group = QtWidgets.QGroupBox("Selection")
        sel_layout = QtWidgets.QVBoxLayout(sel_group)
        
        select_all_btn = QtWidgets.QPushButton("✓ Select All")
        select_all_btn.clicked.connect(self.select_all_files)
        sel_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QtWidgets.QPushButton("✗ Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        sel_layout.addWidget(deselect_all_btn)
        
        refresh_btn = QtWidgets.QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self.refresh_files)
        sel_layout.addWidget(refresh_btn)
        
        controls_layout.addWidget(sel_group)
        
        # Settings panel
        settings_group = QtWidgets.QGroupBox("Settings")
        settings_layout = QtWidgets.QFormLayout(settings_group)
        
        # Timezone selector
        self.timezone_combo = QtWidgets.QComboBox()
        common_timezones = [
            "UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
            "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Copenhagen",
            "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney"
        ]
        self.timezone_combo.addItems(common_timezones)
        self.timezone_combo.setCurrentText(self.selected_timezone)
        self.timezone_combo.currentTextChanged.connect(self.on_timezone_changed)
        settings_layout.addRow("Timezone:", self.timezone_combo)
        
        # Thread count
        self.thread_spin = QtWidgets.QSpinBox()
        self.thread_spin.setMinimum(1)
        self.thread_spin.setMaximum(16)
        self.thread_spin.setValue(self.processor.max_workers)
        self.thread_spin.valueChanged.connect(self.on_thread_count_changed)
        settings_layout.addRow("Threads:", self.thread_spin)
        
        controls_layout.addWidget(settings_group)
        controls_layout.addStretch()
        
        content_layout.addLayout(controls_layout, stretch=1)
        layout.addLayout(content_layout)
        
        # Progress bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status bar
        self.status_label = QtWidgets.QLabel("Ready")
        self.statusBar().addWidget(self.status_label)
    
    def refresh_files(self):
        """Refresh file list from processor"""
        self.processor.scan_directory()
        
        # Restore states for tracked files
        for file in self.processor.library.files:
            # Restore merged state for source files
            if file.path in self.merged_files:
                self.processor.library.update_state(file, FileState.MERGED)
            
            # Mark files that are outputs from merge operations
            if file.path in self.output_files:
                self.processor.library.update_state(file, FileState.MERGED_OUTPUT)
        
        self.update_file_tree()
    
    def update_file_tree(self):
        """Update tree widget with current files"""
        self.file_tree.clear()
        
        # Use organizer to prepare and group files
        files = self.organizer.prepare_files(self.processor.library.files)
        groups = self.organizer.group_files(files)
        
        # Render groups
        for group in groups:
            self._render_group(group)
    
    def _render_group(self, group: FileGroup):
        """Render a single file group in the tree"""
        # Show the adjusted date in the group header
        date_display = f"📅 {group.date_key}"
        
        # Add timezone info if not Beijing
        if self.selected_timezone != 'Asia/Shanghai':
            date_display += f" ({self.selected_timezone})"
        
        date_item = QtWidgets.QTreeWidgetItem([date_display])
        self.file_tree.addTopLevelItem(date_item)
        
        for file in group.files:
            file_item = self._create_file_item(file, group)
            date_item.addChild(file_item)
        
        date_item.setExpanded(True)
    
    def _create_file_item(self, file: AudioFile, group: FileGroup) -> QtWidgets.QTreeWidgetItem:
        """Create a tree widget item for a file"""
        metadata = self.organizer.get_file_metadata(file)
        
        # Build display text
        display_text = f"{metadata['icon']} {file.basename}".strip()
        display_text += metadata['suffix']
        
        # Create tree item
        file_item = QtWidgets.QTreeWidgetItem([
            display_text,
            file.timestamp.strftime("%H:%M:%S"),
            file.state.name,
            self.format_size(file.size)
        ])
        
        # Store file reference
        file_item.setData(0, Qt.UserRole, file)
        
        # Setup checkbox if selectable
        if metadata['selectable']:
            file_item.setCheckState(0, Qt.Unchecked)
        
        # Disable if needed (merged, converted, or output files)
        if metadata['disabled']:
            file_item.setDisabled(True)
            # Use different colors for different disabled states
            if file.state == FileState.MERGED:
                # Darker gray for merged files with strikethrough effect
                for col in range(file_item.columnCount()):
                    file_item.setForeground(col, QtGui.QBrush(QColor(100, 100, 100)))
                    font = file_item.font(col)
                    font.setStrikeOut(True)
                    file_item.setFont(col, font)
            elif file.state == FileState.MERGED_OUTPUT:
                # Green tint for merged output files
                for col in range(file_item.columnCount()):
                    file_item.setForeground(col, QtGui.QBrush(QColor(40, 120, 40)))
                    font = file_item.font(col)
                    font.setBold(True)
                    file_item.setFont(col, font)
            else:
                # Light gray for converted files
                for col in range(file_item.columnCount()):
                    file_item.setForeground(col, QtGui.QBrush(QColor(150, 150, 150)))
        
        # Apply color based on adjusted date (for all files in the group)
        if group.color:
            file_item.setData(0, Qt.UserRole + 2, group.color)
        
        # Add tooltip if provided
        if 'tooltip' in metadata:
            file_item.setToolTip(0, metadata['tooltip'])
        
        return file_item
    
    
    def get_selected_files(self) -> List[AudioFile]:
        """Get currently checked audio files"""
        selected = []
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            date_item = root.child(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                if (file_item.checkState(0) == Qt.Checked and 
                    not file_item.isDisabled()):
                    file = file_item.data(0, Qt.UserRole)
                    # Double-check that file is not merged, converted, or output
                    if file and file.state not in [FileState.MERGED, FileState.CONVERTED, FileState.MERGED_OUTPUT]:
                        selected.append(file)
        return selected
    
    def select_all_files(self):
        """Check all enabled files"""
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            date_item = root.child(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                if not file_item.isDisabled():
                    file_item.setCheckState(0, Qt.Checked)
    
    def deselect_all_files(self):
        """Uncheck all files"""
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            date_item = root.child(i)
            for j in range(date_item.childCount()):
                file_item = date_item.child(j)
                if not file_item.isDisabled():
                    file_item.setCheckState(0, Qt.Unchecked)
    
    def get_selected_date(self) -> Optional[str]:
        """Get date from selection"""
        for item in self.file_tree.selectedItems():
            if item.parent() is None:  # Top-level date item
                return item.text(0).replace("📅 ", "")
            else:
                file = item.data(0, Qt.UserRole)
                if file:
                    return file.date_key
        return None
    
    def on_timezone_changed(self, timezone: str):
        """Handle timezone change"""
        self.selected_timezone = timezone
        self.organizer = FileOrganizer(timezone)  # Recreate with new timezone
        logging.info(f"Timezone changed to: {timezone}")
        self.refresh_files()
        # Force visual update
        self.file_tree.viewport().update()
    
    def on_thread_count_changed(self, count: int):
        """Update thread count"""
        self.processor.max_workers = count
    
    def start_task(self, task: ProcessingTask):
        """Start a processing task in thread"""
        if self.current_thread and self.current_thread.isRunning():
            QtWidgets.QMessageBox.warning(self, "Busy", "A task is already running")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        
        self.current_thread = ProcessingThread(self.processor, task)
        self.current_thread.progress.connect(self.on_progress)
        self.current_thread.finished.connect(self.on_task_finished)
        self.current_thread.start()
    
    def on_progress(self, message: str):
        """Handle progress updates"""
        self.status_label.setText(message)
    
    def on_task_finished(self, result):
        """Handle task completion"""
        self.progress_bar.setVisible(False)
        
        if result.success:
            self.status_label.setText(f"✓ Completed: {result.processed_count} files")
            
            # Track merged files
            if result.task.task_type == TaskType.MERGE:
                for file in result.task.files:
                    self.merged_files.add(file.path)
                # Track output files
                for output in result.output_files:
                    self.output_files[output] = [f.path for f in result.task.files]
        else:
            self.status_label.setText(f"✗ Failed: {result.error}")
            if result.error:
                QtWidgets.QMessageBox.warning(self, "Task Failed", result.error)
        
        self.refresh_files()
    
    def import_files(self):
        """Import files from OBS directory"""
        # First try auto-detection
        obs_dir = self.processor.find_obs_save_location()
        
        if obs_dir:
            reply = QtWidgets.QMessageBox.question(
                self, "OBS Directory Found",
                f"Found OBS recordings in:\n{obs_dir}\n\nImport from this directory?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                source_dir = obs_dir
            else:
                # User wants to select different directory
                source_dir = QtWidgets.QFileDialog.getExistingDirectory(
                    self, "Select OBS Recording Directory"
                )
                if not source_dir:
                    return
                source_dir = Path(source_dir)
        else:
            # No auto-detection, show dialog
            QtWidgets.QMessageBox.information(
                self, "OBS Directory Not Found",
                "Could not auto-detect OBS directory.\nPlease select the directory manually."
            )
            source_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select OBS Recording Directory"
            )
            if not source_dir:
                return
            source_dir = Path(source_dir)
        
        task = ProcessingTask(
            task_type=TaskType.IMPORT,
            files=[],
            output_dir=Path.cwd(),
            params={'source_dir': source_dir}
        )
        self.start_task(task)
    
    def convert_selected(self):
        """Convert selected files to MP3"""
        files = self.get_selected_files()
        # Filter only video files
        video_files = [f for f in files if f.is_video]
        
        if not video_files:
            QtWidgets.QMessageBox.information(self, "No Videos", 
                "Please select video files to convert")
            return
        
        task = ProcessingTask(
            task_type=TaskType.CONVERT,
            files=video_files,
            output_dir=Path.cwd()
        )
        self.start_task(task)
    
    def merge_selected(self):
        """Merge selected audio files"""
        files = self.get_selected_files()
        # Filter only audio files
        audio_files = [f for f in files if f.is_audio]
        
        if len(audio_files) < 2:
            QtWidgets.QMessageBox.information(self, "Selection", 
                "Please select at least 2 audio files to merge")
            return
        
        task = ProcessingTask(
            task_type=TaskType.MERGE,
            files=audio_files,
            output_dir=Path.cwd()
        )
        self.start_task(task)
    
    def merge_by_date(self):
        """Merge all unmerged files for selected date"""
        date_key = self.get_selected_date()
        if not date_key:
            QtWidgets.QMessageBox.information(self, "No Date", "Please select a date")
            return
        
        task = self.processor.create_merge_task_for_date(date_key)
        if not task:
            QtWidgets.QMessageBox.information(self, "No Files", 
                f"No unmerged files for {date_key}")
            return
        
        self.start_task(task)
    
    def remove_silence(self):
        """Remove silence from selected files"""
        files = self.get_selected_files()
        audio_files = [f for f in files if f.is_audio]
        
        if not audio_files:
            QtWidgets.QMessageBox.information(self, "No Audio", 
                "Please select audio files")
            return
        
        task = ProcessingTask(
            task_type=TaskType.REMOVE_SILENCE,
            files=audio_files,
            output_dir=Path.cwd()
        )
        self.start_task(task)
    
    def organize_files(self):
        """Organize files by date"""
        reply = QtWidgets.QMessageBox.question(
            self, "Organize Files",
            "Organize all files by date and create archives?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        task = ProcessingTask(
            task_type=TaskType.ORGANIZE,
            files=list(self.processor.library.files),
            output_dir=Path.cwd(),
            params={'create_archive': True}
        )
        self.start_task(task)
    
    @staticmethod
    def format_size(size: int) -> str:
        """Format file size for display"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"