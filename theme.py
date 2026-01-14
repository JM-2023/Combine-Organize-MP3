#!/usr/bin/env python3
"""
Theme configuration - Data, not strings
Good programmers worry about data structures
"""

class Theme:
    """Single source of truth for all styling"""
    
    # Core colors - Claude palette
    COLORS = {
        'bg_primary': '#1a1a1a',
        'bg_secondary': '#2a2a2a',
        'bg_hover': '#3a3a3a',
        'border': '#3a3a3a',
        'text': '#e0e0e0',
        'text_dim': '#b0b0b0',
        'accent': '#DC8862',
        'accent_hover': '#E59B7A',
        'accent_pressed': '#C97550',
    }
    
    # Action colors - Each action has its identity
    ACTIONS = {
        'import': ('#DC8862', '#E59B7A'),
        'convert': ('#6B89E5', '#7D9AE8'),
        'merge': ('#5FB86E', '#6FC57D'),
        'date': ('#E5B45F', '#E8C070'),
        'silence': ('#B85F9E', '#C570AC'),
        'organize': ('#5FB8B8', '#6FC5C5'),
    }
    
    # File state styles - No if/else needed
    FILE_STYLES = {
        'normal': {
            'color': COLORS['text'],
            'weight': 'normal',
            'decoration': 'none',
        },
        'merged': {
            'color': '#505050',
            'weight': 'normal',
            'decoration': 'strikethrough',
        },
        'output': {
            'color': '#5FB86E',
            'weight': 'bold',
            'decoration': 'none',
        },
        'converted': {
            'color': '#969696',
            'weight': 'normal',
            'decoration': 'none',
        },
    }
    
    @classmethod
    def _action_button_stylesheet(cls) -> str:
        """Generate per-action button stylesheet blocks."""
        blocks = []
        for action, (color, hover) in cls.ACTIONS.items():
            blocks.append(f"""
            QPushButton[action="{action}"] {{
                background-color: {color};
                text-align: left;
                font-weight: 600;
                padding: 12px;
            }}
            
            QPushButton[action="{action}"]:hover {{
                background-color: {hover};
            }}
            
            QPushButton[action="{action}"]:pressed {{
                background-color: {color};
            }}
            """)
        return "\n".join(blocks)
    
    @classmethod
    def stylesheet(cls):
        """Generate complete stylesheet from data"""
        return f"""
        QMainWindow {{
            background-color: {cls.COLORS['bg_primary']};
        }}
        
        QWidget {{
            background-color: {cls.COLORS['bg_primary']};
            color: {cls.COLORS['text']};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 14px;
        }}
        
        QLabel#appTitle {{
            color: {cls.COLORS['accent']};
            font-size: 28px;
            font-weight: 700;
            padding: 18px 20px;
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 10px;
        }}
        
        QGroupBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }}
        
        QGroupBox::title {{
            color: {cls.COLORS['accent']};
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
        }}
        
        QPushButton {{
            background-color: {cls.COLORS['accent']};
            color: white;
            border: none;
            border-radius: 6px;
            padding: 10px 16px;
            font-weight: 500;
            min-height: 20px;
        }}
        
        QPushButton:hover {{
            background-color: {cls.COLORS['accent_hover']};
        }}
        
        QPushButton:pressed {{
            background-color: {cls.COLORS['accent_pressed']};
        }}
        
        QPushButton.secondary,
        QPushButton[class="secondary"] {{
            background-color: {cls.COLORS['bg_hover']};
            border: 1px solid {cls.COLORS['accent']};
        }}
        
        QPushButton.secondary:hover,
        QPushButton[class="secondary"]:hover {{
            background-color: #4a4a4a;
            border-color: {cls.COLORS['accent_hover']};
        }}
        
        QPushButton.secondary:pressed,
        QPushButton[class="secondary"]:pressed {{
            background-color: {cls.COLORS['bg_secondary']};
            border-color: {cls.COLORS['accent_pressed']};
        }}
        
        QPushButton:disabled {{
            background-color: {cls.COLORS['border']};
            color: {cls.COLORS['text_dim']};
        }}
        
        QTreeWidget {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 8px;
            selection-background-color: {cls.COLORS['accent']};
            alternate-background-color: #262626;
        }}
        
        QTreeWidget::item {{
            padding: 4px;
            border-radius: 4px;
        }}
        
        QTreeWidget::item:selected {{
            background-color: {cls.COLORS['accent']};
            color: white;
        }}
        
        QTreeWidget::item:hover {{
            background-color: {cls.COLORS['bg_hover']};
        }}
        
        QHeaderView::section {{
            background-color: {cls.COLORS['bg_secondary']};
            color: {cls.COLORS['accent']};
            padding: 8px;
            border: none;
            border-bottom: 2px solid {cls.COLORS['accent']};
            font-weight: 600;
        }}
        
        QComboBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 6px;
            padding: 6px 12px;
            min-width: 120px;
        }}
        
        QComboBox:hover {{
            border-color: {cls.COLORS['accent']};
        }}
        
        QSpinBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        
        QSpinBox:hover {{
            border-color: {cls.COLORS['accent']};
        }}
        
        QProgressBar {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: 6px;
            text-align: center;
            color: white;
        }}
        
        QProgressBar::chunk {{
            background-color: {cls.COLORS['accent']};
            border-radius: 5px;
        }}
        
        QStatusBar {{
            background-color: {cls.COLORS['bg_primary']};
            border-top: 1px solid {cls.COLORS['border']};
            color: {cls.COLORS['text_dim']};
        }}
        
        QLabel#statusLabel {{
            color: {cls.COLORS['accent']};
            font-weight: 500;
            padding: 0 6px;
        }}
        
        QSplitter::handle {{
            background-color: {cls.COLORS['bg_primary']};
        }}
        
        QSplitter::handle:horizontal {{
            width: 10px;
        }}
        
        QScrollBar:vertical {{
            background-color: {cls.COLORS['bg_secondary']};
            width: 12px;
            border-radius: 6px;
        }}
        
        QScrollBar::handle:vertical {{
            background-color: #4a4a4a;
            border-radius: 6px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background-color: {cls.COLORS['accent']};
        }}
        
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        QToolTip {{
            background-color: {cls.COLORS['bg_secondary']};
            color: {cls.COLORS['text']};
            border: 1px solid {cls.COLORS['border']};
            padding: 6px 8px;
            border-radius: 6px;
        }}
        """ + cls._action_button_stylesheet()
