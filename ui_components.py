#!/usr/bin/env python3
"""
UI Components - Dumb views that just display
No business logic, no special cases
"""
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from theme import Theme


class ActionButton(QtWidgets.QPushButton):
    """A button that knows its action type"""
    
    def __init__(self, text, action_type, callback):
        super().__init__(text)
        self.action_type = action_type
        self.setProperty("action", action_type)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(callback)


class SecondaryButton(QtWidgets.QPushButton):
    """Secondary action button with outline style"""
    
    def __init__(self, text, callback):
        super().__init__(text)
        self.clicked.connect(callback)
        self.setProperty("class", "secondary")
        self.setCursor(Qt.PointingHandCursor)


class FileTreeWidget(QtWidgets.QTreeWidget):
    """Tree widget for file display - just display, no logic"""
    
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["File", "Time", "State", "Size"])
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
    
    def add_group(self, date_key, timezone=None):
        """Add a date group"""
        display = f"📅 {date_key}"
        if timezone and timezone != 'Asia/Shanghai':
            display += f" ({timezone})"
        
        item = QtWidgets.QTreeWidgetItem([display])
        item.setFirstColumnSpanned(True)
        
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QtGui.QBrush(QtGui.QColor(Theme.COLORS['accent'])))
        
        self.addTopLevelItem(item)
        item.setExpanded(True)
        return item
    
    def add_file(self, parent, file_data):
        """Add a file to the tree - just display"""
        item = QtWidgets.QTreeWidgetItem([
            file_data['display'],
            file_data['time'],
            file_data['state'],
            file_data['size']
        ])
        
        # Store reference
        item.setData(0, Qt.UserRole, file_data.get('ref'))
        
        # Apply style
        self._apply_style(item, file_data['style'])
        
        # Checkbox if needed
        if file_data.get('checkable'):
            item.setCheckState(0, Qt.Unchecked)
        
        # Disabled state
        if file_data.get('disabled'):
            item.setDisabled(True)
        
        parent.addChild(item)
        return item
    
    def _apply_style(self, item, style_key):
        """Apply style from theme - no if/else"""
        style = Theme.FILE_STYLES.get(style_key, Theme.FILE_STYLES['normal'])
        
        brush = QtGui.QBrush(QtGui.QColor(style['color']))
        for col in range(item.columnCount()):
            item.setForeground(col, brush)
            
            font = item.font(col)
            font.setBold(style['weight'] == 'bold')
            font.setStrikeOut(style['decoration'] == 'strikethrough')
            item.setFont(col, font)
    
    def get_checked_items(self):
        """Get all checked items"""
        checked = []
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                item = group.child(j)
                if item.checkState(0) == Qt.Checked and not item.isDisabled():
                    ref = item.data(0, Qt.UserRole)
                    if ref:
                        checked.append(ref)
        return checked
    
    def set_all_checked(self, checked):
        """Set check state for all items"""
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                item = group.child(j)
                if not item.isDisabled():
                    item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)


class ControlPanel(QtWidgets.QWidget):
    """Control panel - just a container for buttons"""
    
    def __init__(self):
        super().__init__()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.groups = {}
    
    def add_group(self, title):
        """Add a control group"""
        group = QtWidgets.QGroupBox(title)
        group_layout = QtWidgets.QVBoxLayout(group)
        self.layout.addWidget(group)
        self.groups[title] = group_layout
        return group_layout
    
    def add_button(self, group_title, button):
        """Add button to group"""
        if group_title in self.groups:
            self.groups[group_title].addWidget(button)


class SettingsPanel(QtWidgets.QGroupBox):
    """Settings panel - simple form layout"""
    
    def __init__(self):
        super().__init__("Settings")
        self.form = QtWidgets.QFormLayout(self)
    
    def add_combo(self, label, items, current, callback):
        """Add combo box setting"""
        combo = QtWidgets.QComboBox()
        combo.addItems(items)
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(callback)
        self.form.addRow(label, combo)
        return combo
    
    def add_spin(self, label, min_val, max_val, current, callback):
        """Add spin box setting"""
        spin = QtWidgets.QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(current)
        spin.valueChanged.connect(callback)
        self.form.addRow(label, spin)
        return spin


class StatusDisplay(QtWidgets.QWidget):
    """Status display - progress and messages"""
    
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        self.label = QtWidgets.QLabel("Ready")
        self.label.setObjectName("statusLabel")
        layout.addWidget(self.label, stretch=1)
        
        self.progress = QtWidgets.QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        layout.addWidget(self.progress)
    
    def show_progress(self, determinate=False):
        """Show progress bar"""
        self.progress.setVisible(True)
        if not determinate:
            self.progress.setRange(0, 0)
    
    def hide_progress(self):
        """Hide progress bar"""
        self.progress.setVisible(False)
    
    def set_message(self, text):
        """Update status message"""
        self.label.setText(text)
