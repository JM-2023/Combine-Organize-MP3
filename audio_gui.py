#!/usr/bin/env python3
"""
Clean GUI - Separation of concerns
Each class does ONE thing
"""
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import logging

from theme import Theme
from ui_components import (
    ActionButton, SecondaryButton, FileTreeWidget,
    ControlPanel, SettingsPanel, StatusDisplay
)
from file_presenter import FilePresenter
from audio_models import TaskType, ProcessingTask, FileState
from audio_processor import AudioProcessor
from file_organizer import FileOrganizer


class TaskThread(QThread):
    """Simple task runner - one job"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    
    def __init__(self, processor, task):
        super().__init__()
        self.processor = processor
        self.task = task
    
    def run(self):
        result = self.processor.process_task(
            self.task,
            progress_callback=self.progress.emit
        )
        self.finished.emit(result)


class AudioToolboxGUI(QtWidgets.QMainWindow):
    """Main window - Just coordinates, no business logic"""
    
    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        self.processor = AudioProcessor(config)
        self.organizer = FileOrganizer(self.config.get('default_timezone', 'Asia/Shanghai'))
        self.presenter = FilePresenter()
        self.current_thread = None
        
        # Track state
        self.merged_files = set()
        self.output_files = {}
        
        self._init_ui()
        self._connect_signals()
        self.refresh()
    
    def _init_ui(self):
        """Build UI - just assembly"""
        self.setWindowTitle("Audio Toolbox")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(Theme.stylesheet())
        
        # Main layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Title
        title = QtWidgets.QLabel("🎵 Audio Toolbox Pro")
        title.setStyleSheet(f"""
            QLabel {{
                color: {Theme.COLORS['accent']};
                font-size: 28px;
                font-weight: 700;
                padding: 20px;
                background-color: #252525;
                border-radius: 10px;
                margin: 10px;
            }}
        """)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Content area
        content = QtWidgets.QHBoxLayout()
        
        # File tree
        tree_group = QtWidgets.QGroupBox("Files by Date")
        tree_layout = QtWidgets.QVBoxLayout(tree_group)
        self.file_tree = FileTreeWidget()
        tree_layout.addWidget(self.file_tree)
        content.addWidget(tree_group, stretch=3)
        
        # Controls
        self.controls = self._build_controls()
        content.addLayout(self.controls, stretch=1)
        
        layout.addLayout(content)
        
        # Status
        self.status = StatusDisplay()
        layout.addWidget(self.status)
        
        self.statusBar().addWidget(self.status.label)
    
    def _build_controls(self):
        """Build control panel"""
        layout = QtWidgets.QVBoxLayout()
        
        # Operations
        ops = ControlPanel()
        ops_layout = ops.add_group("Operations")
        
        operations = [
            ("📥 Import OBS", "import", self.import_files),
            ("🎬 Convert to MP3", "convert", self.convert_selected),
            ("🎵 Merge Selected", "merge", self.merge_selected),
            ("📅 Merge by Date", "date", self.merge_by_date),
            ("🔇 Remove Silence", "silence", self.remove_silence),
            ("📦 Organize", "organize", self.organize_files),
        ]
        
        for text, action_type, callback in operations:
            btn = ActionButton(text, action_type, callback)
            ops_layout.addWidget(btn)
        
        layout.addWidget(ops)
        
        # Selection
        sel = ControlPanel()
        sel_layout = sel.add_group("Selection")
        
        sel_layout.addWidget(SecondaryButton("✓ Select All", self.select_all))
        sel_layout.addWidget(SecondaryButton("✗ Deselect All", self.deselect_all))
        sel_layout.addWidget(SecondaryButton("↻ Refresh", self.refresh))
        
        layout.addWidget(sel)
        
        # Settings
        self.settings = SettingsPanel()
        
        self.timezone_combo = self.settings.add_combo(
            "Timezone:",
            ["UTC", "US/Eastern", "US/Pacific", "Europe/London", 
             "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney"],
            self.config.get('default_timezone', 'Asia/Shanghai'),
            self.on_timezone_changed
        )
        
        self.thread_spin = self.settings.add_spin(
            "Threads:",
            1, 16,
            self.processor.max_workers,
            self.on_thread_changed
        )
        
        layout.addWidget(self.settings)
        layout.addStretch()
        
        return layout
    
    def _connect_signals(self):
        """Connect signals - kept separate"""
        pass  # All connections done in control creation
    
    def refresh(self):
        """Refresh file display"""
        self.processor.scan_directory()
        self._restore_states()
        self._update_tree()
    
    def _restore_states(self):
        """Restore tracked file states"""
        for file in self.processor.library.files:
            if file.path in self.merged_files:
                self.processor.library.update_state(file, FileState.MERGED)
            if file.path in self.output_files:
                self.processor.library.update_state(file, FileState.MERGED_OUTPUT)
    
    def _update_tree(self):
        """Update tree display"""
        self.file_tree.clear()
        
        files = self.organizer.prepare_files(self.processor.library.files)
        groups = self.organizer.group_files(files)
        
        for group in groups:
            parent = self.file_tree.add_group(group.date_key, self.config.get('default_timezone', 'Asia/Shanghai'))
            for file in group.files:
                file_data = self.presenter.present(file)
                self.file_tree.add_file(parent, file_data)
    
    # Action handlers - Simple delegators
    def select_all(self):
        self.file_tree.set_all_checked(True)
    
    def deselect_all(self):
        self.file_tree.set_all_checked(False)
    
    def on_timezone_changed(self, tz):
        self.organizer = FileOrganizer(tz)
        self.refresh()
    
    def on_thread_changed(self, count):
        self.processor.max_workers = count
    
    def get_selected(self):
        """Get selected files"""
        return self.file_tree.get_checked_items()
    
    def run_task(self, task):
        """Run a task"""
        if self.current_thread and self.current_thread.isRunning():
            QtWidgets.QMessageBox.warning(self, "Busy", "Task in progress")
            return
        
        self.status.show_progress()
        self.current_thread = TaskThread(self.processor, task)
        self.current_thread.progress.connect(self.status.set_message)
        self.current_thread.finished.connect(self.on_task_done)
        self.current_thread.start()
    
    def on_task_done(self, result):
        """Handle task completion"""
        self.status.hide_progress()
        
        if result.success:
            self.status.set_message(f"✓ Done: {result.processed_count} files")
            
            # Update tracking
            if result.task.task_type == TaskType.MERGE:
                for file in result.task.files:
                    self.merged_files.add(file.path)
                for output in result.output_files:
                    self.output_files[output] = [f.path for f in result.task.files]
        else:
            self.status.set_message(f"✗ Failed: {result.error}")
            if result.error:
                QtWidgets.QMessageBox.warning(self, "Error", result.error)
        
        self.refresh()
    
    # Task creators - minimal logic
    def import_files(self):
        """Import from OBS"""
        obs_dir = self.processor.find_obs_save_location()
        
        if obs_dir:
            reply = QtWidgets.QMessageBox.question(
                self, "OBS Found",
                f"Import from:\n{obs_dir}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply != QtWidgets.QMessageBox.Yes:
                obs_dir = QtWidgets.QFileDialog.getExistingDirectory(
                    self, "Select Directory"
                )
                if not obs_dir:
                    return
                obs_dir = Path(obs_dir)
        else:
            obs_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select OBS Directory"
            )
            if not obs_dir:
                return
            obs_dir = Path(obs_dir)
        
        task = ProcessingTask(
            task_type=TaskType.IMPORT,
            files=[],
            output_dir=Path.cwd(),
            params={'source_dir': obs_dir}
        )
        self.run_task(task)
    
    def convert_selected(self):
        """Convert to MP3"""
        files = [f for f in self.get_selected() if f.is_video]
        if not files:
            QtWidgets.QMessageBox.information(self, "No Videos", "Select video files")
            return
        
        task = ProcessingTask(TaskType.CONVERT, files, Path.cwd())
        self.run_task(task)
    
    def merge_selected(self):
        """Merge audio files"""
        files = [f for f in self.get_selected() if f.is_audio]
        
        task = ProcessingTask(TaskType.MERGE, files, Path.cwd())
        self.run_task(task)
    
    def merge_by_date(self):
        """Merge by date"""
        # Get selected date from tree
        selected = self.file_tree.selectedItems()
        if not selected:
            QtWidgets.QMessageBox.information(self, "No Date", "Select a date")
            return
        
        item = selected[0]
        if item.parent():  # File item, get parent
            item = item.parent()
        
        date_key = item.text(0).replace("📅 ", "").split(" (")[0]
        
        task = self.processor.create_merge_task_for_date(date_key)
        if not task:
            QtWidgets.QMessageBox.information(self, "No Files", f"No files for {date_key}")
            return
        
        self.run_task(task)
    
    def remove_silence(self):
        """Remove silence"""
        files = [f for f in self.get_selected() if f.is_audio]
        if not files:
            QtWidgets.QMessageBox.information(self, "No Audio", "Select audio files")
            return
        
        task = ProcessingTask(TaskType.REMOVE_SILENCE, files, Path.cwd())
        self.run_task(task)
    
    def organize_files(self):
        """Organize files"""
        reply = QtWidgets.QMessageBox.question(
            self, "Organize",
            "Organize all files by date and create a compressed archive for each folder?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        task = ProcessingTask(
            TaskType.ORGANIZE,
            list(self.processor.library.files),
            Path.cwd(),
            params={'create_archive': True}
        )
        self.run_task(task)
