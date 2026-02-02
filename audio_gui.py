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

        self._ui_scale = None
        self._ui_scale_update_timer = QtCore.QTimer(self)
        self._ui_scale_update_timer.setSingleShot(True)
        self._ui_scale_update_timer.timeout.connect(self._on_ui_scale_update_timeout)
        self._force_ui_scale_update = False
        
        self._init_ui()
        self._connect_signals()
        self.refresh()

    def _is_busy(self) -> bool:
        return bool(self.current_thread and self.current_thread.isRunning())

    def _clamp(self, value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(value, max_value))

    def _compute_ui_scale(self) -> float:
        base_scale = self.config.get("ui_scale", 1.0)
        try:
            base_scale = float(base_scale)
        except (TypeError, ValueError):
            base_scale = 1.0

        auto_scale = self.config.get("ui_auto_scale", True)
        if not isinstance(auto_scale, bool):
            auto_scale = True

        if not auto_scale:
            return self._clamp(base_scale, 0.7, 1.25)

        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            return self._clamp(base_scale, 0.7, 1.25)

        available = screen.availableGeometry()
        if available.width() <= 0 or available.height() <= 0:
            return self._clamp(base_scale, 0.7, 1.25)

        ratio = min(self.width() / available.width(), self.height() / available.height())

        if ratio <= 0.25:
            auto_factor = 0.7
        elif ratio <= 0.4:
            auto_factor = 0.7 + (ratio - 0.25) * (0.1 / 0.15)
        elif ratio >= 0.85:
            auto_factor = 1.0
        else:
            auto_factor = 0.8 + (ratio - 0.4) * (0.2 / 0.45)

        return self._clamp(base_scale * auto_factor, 0.7, 1.25)

    def _apply_ui_scale(self, scale: float, *, force: bool = False):
        scale = self._clamp(scale, 0.7, 1.25)
        if not force and self._ui_scale is not None and abs(scale - self._ui_scale) < 0.02:
            return

        self._ui_scale = scale
        self.setStyleSheet(Theme.stylesheet(scale))

        if hasattr(self, "status") and hasattr(self.status, "set_scale"):
            self.status.set_scale(scale)

        def scaled_px(value: int) -> int:
            return max(0, int(round(value * scale)))

        if hasattr(self, "_root_layout"):
            self._root_layout.setContentsMargins(
                scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12)
            )
            self._root_layout.setSpacing(scaled_px(12))

        if hasattr(self, "_tree_layout"):
            self._tree_layout.setContentsMargins(
                scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(12)
            )

        if hasattr(self, "_controls_layout"):
            self._controls_layout.setSpacing(scaled_px(12))

    def _schedule_ui_scale_update(self, *, force: bool = False):
        self._force_ui_scale_update = self._force_ui_scale_update or force
        self._ui_scale_update_timer.start(75)

    def _on_ui_scale_update_timeout(self):
        force = self._force_ui_scale_update
        self._force_ui_scale_update = False
        self._apply_ui_scale(self._compute_ui_scale(), force=force)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_ui_scale_update()

    def _safe_min_size(self) -> QtCore.QSize:
        min_width, min_height = 560, 360
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            min_width = min(min_width, int(available.width() * 0.9))
            min_height = min(min_height, int(available.height() * 0.9))
        return QtCore.QSize(min_width, min_height)

    def _apply_default_geometry(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            self.resize(1200, 800)
            self._pending_default_splitter_sizes = True
            return

        available = screen.availableGeometry()
        max_width = int(available.width() * 0.95)
        max_height = int(available.height() * 0.95)

        scale = self.config.get("ui_window_scale", 0.4)
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = 0.4
        scale = max(0.2, min(scale, 0.95))

        target_width = min(
            max(int(available.width() * scale), self.minimumWidth()),
            max_width,
        )
        target_height = min(
            max(int(available.height() * scale), self.minimumHeight()),
            max_height,
        )

        self.resize(target_width, target_height)
        self.move(
            available.x() + (available.width() - target_width) // 2,
            available.y() + (available.height() - target_height) // 2,
        )
        self._pending_default_splitter_sizes = True

    def _restore_window_settings(self):
        settings = QtCore.QSettings()

        self._pending_show_maximized = settings.value(
            "ui/window_maximized", False, type=bool
        )

        geometry = settings.value("ui/window_geometry", None, type=QtCore.QByteArray)
        if geometry and self.restoreGeometry(geometry):
            if not self._is_visible_on_any_screen():
                self._apply_default_geometry()
        else:
            self._apply_default_geometry()

        splitter_state = settings.value(
            "ui/main_splitter_state", None, type=QtCore.QByteArray
        )
        if splitter_state and hasattr(self, "_main_splitter"):
            self._main_splitter.restoreState(splitter_state)
        else:
            self._pending_default_splitter_sizes = True

    def _is_visible_on_any_screen(self) -> bool:
        screens = QtWidgets.QApplication.screens()
        if not screens:
            return True

        rect = self.frameGeometry()
        for screen in screens:
            if rect.intersects(screen.availableGeometry()):
                return True
        return False

    def _apply_default_splitter_sizes(self):
        splitter = getattr(self, "_main_splitter", None)
        if not splitter:
            return

        total_width = splitter.width()
        if total_width <= 0 and self.centralWidget():
            total_width = self.centralWidget().width()
        if total_width <= 0:
            total_width = max(1, self.width() - 40)

        left = int(total_width * 0.65)
        splitter.setSizes([left, total_width - left])

    def showEvent(self, event):
        super().showEvent(event)

        if getattr(self, "_pending_show_maximized", False):
            self._pending_show_maximized = False
            self.showMaximized()
            self._schedule_ui_scale_update(force=True)
            return

        if getattr(self, "_pending_default_splitter_sizes", False):
            self._pending_default_splitter_sizes = False
            self._apply_default_splitter_sizes()
            self._schedule_ui_scale_update(force=True)

    def closeEvent(self, event):
        settings = QtCore.QSettings()
        settings.setValue("ui/window_maximized", self.isMaximized())
        settings.setValue("ui/window_geometry", self.saveGeometry())
        if hasattr(self, "_main_splitter"):
            settings.setValue("ui/main_splitter_state", self._main_splitter.saveState())
        super().closeEvent(event)

    def reset_window_layout(self):
        settings = QtCore.QSettings()
        settings.remove("ui/window_maximized")
        settings.remove("ui/window_geometry")
        settings.remove("ui/main_splitter_state")
        settings.sync()

        self.showNormal()
        self._pending_show_maximized = False
        self._apply_default_geometry()
        self._pending_default_splitter_sizes = False
        self._apply_default_splitter_sizes()
        self._apply_ui_scale(self._compute_ui_scale(), force=True)
        self.status.set_message("Layout reset")
    
    def _init_ui(self):
        """Build UI - just assembly"""
        self.setWindowTitle("Audio Toolbox")
        self.setMinimumSize(self._safe_min_size())
        self.setStyleSheet(Theme.stylesheet())
        
        # Main layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self._root_layout = QtWidgets.QVBoxLayout(central)
        layout = self._root_layout
        
        # Title
        title = QtWidgets.QLabel("🎵 Audio Toolbox Pro")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # File tree
        tree_group = QtWidgets.QGroupBox("Files by Date")
        self._tree_layout = QtWidgets.QVBoxLayout(tree_group)
        tree_layout = self._tree_layout
        self.file_tree = FileTreeWidget()
        tree_layout.addWidget(self.file_tree)
        
        # Controls (scrollable)
        controls_panel = self._build_controls()
        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        controls_scroll.setWidget(controls_panel)
        
        # Split view
        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(tree_group)
        splitter.addWidget(controls_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self._main_splitter = splitter
        
        layout.addWidget(splitter, stretch=1)
        
        # Status
        self.status = StatusDisplay()
        self.statusBar().addPermanentWidget(self.status, 1)

        view_menu = self.menuBar().addMenu("View")
        reset_layout_action = QtWidgets.QAction("Reset Window Layout", self)
        reset_layout_action.triggered.connect(self.reset_window_layout)
        view_menu.addAction(reset_layout_action)

        self._restore_window_settings()
        self._apply_ui_scale(self._compute_ui_scale(), force=True)
    
    def _build_controls(self):
        """Build control panel"""
        panel = QtWidgets.QWidget()
        self._controls_layout = QtWidgets.QVBoxLayout(panel)
        layout = self._controls_layout
        layout.setContentsMargins(0, 0, 0, 0)
        
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
        
        return panel
    
    def _connect_signals(self):
        """Connect signals - kept separate"""
        pass  # All connections done in control creation
    
    def refresh(self):
        """Refresh file display"""
        if self._is_busy():
            self.status.set_message("Task in progress - refresh disabled")
            return
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
