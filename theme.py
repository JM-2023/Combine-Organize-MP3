#!/usr/bin/env python3
"""
Theme configuration - Data, not strings
Good programmers worry about data structures
"""

class Theme:
    """Single source of truth for all styling"""

    @staticmethod
    def _clamp_scale(scale: float) -> float:
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return 1.0
        return max(0.7, min(scale, 1.25))

    @staticmethod
    def _scaled(value: float, scale: float, *, minimum: int = 0) -> int:
        return max(minimum, int(round(value * scale)))
    
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
    def _action_button_stylesheet(cls, scale: float = 1.0) -> str:
        """Generate per-action button stylesheet blocks."""
        scale = cls._clamp_scale(scale)
        action_padding = cls._scaled(12, scale, minimum=1)
        blocks = []
        for action, (color, hover) in cls.ACTIONS.items():
            blocks.append(f"""
            QPushButton[action="{action}"] {{
                background-color: {color};
                text-align: left;
                font-weight: 600;
                padding: {action_padding}px;
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
    def stylesheet(cls, scale: float = 1.0):
        """Generate complete stylesheet from data"""
        scale = cls._clamp_scale(scale)

        base_font = cls._scaled(14, scale, minimum=10)
        title_font = cls._scaled(28, scale, minimum=14)
        title_pad_y = cls._scaled(18, scale)
        title_pad_x = cls._scaled(20, scale)
        title_border_radius = cls._scaled(10, scale, minimum=1)

        group_border_radius = cls._scaled(8, scale, minimum=1)
        group_margin_top = cls._scaled(12, scale)
        group_padding_top = cls._scaled(12, scale)
        group_title_left = cls._scaled(12, scale)
        group_title_pad_x = cls._scaled(8, scale)

        button_border_radius = cls._scaled(6, scale, minimum=1)
        button_pad_y = cls._scaled(10, scale, minimum=1)
        button_pad_x = cls._scaled(16, scale, minimum=1)
        button_min_height = cls._scaled(20, scale, minimum=1)

        tree_border_radius = cls._scaled(8, scale, minimum=1)
        tree_item_padding = cls._scaled(4, scale)
        tree_item_border_radius = cls._scaled(4, scale, minimum=1)

        header_padding = cls._scaled(8, scale)
        header_border_bottom = cls._scaled(2, scale, minimum=1)

        combo_border_radius = cls._scaled(6, scale, minimum=1)
        combo_pad_y = cls._scaled(6, scale)
        combo_pad_x = cls._scaled(12, scale)
        combo_min_width = cls._scaled(120, scale, minimum=60)

        progress_border_radius = cls._scaled(6, scale, minimum=1)
        progress_chunk_radius = cls._scaled(5, scale, minimum=1)
        status_top_border = cls._scaled(1, scale, minimum=1)
        status_label_pad_x = cls._scaled(6, scale)

        splitter_handle_width = cls._scaled(10, scale, minimum=4)

        scrollbar_width = cls._scaled(12, scale, minimum=8)
        scrollbar_radius = cls._scaled(6, scale, minimum=1)
        scrollbar_handle_min_height = cls._scaled(20, scale, minimum=10)

        tooltip_pad_y = cls._scaled(6, scale)
        tooltip_pad_x = cls._scaled(8, scale)
        tooltip_radius = cls._scaled(6, scale, minimum=1)

        return f"""
        QMainWindow {{
            background-color: {cls.COLORS['bg_primary']};
        }}
        
        QWidget {{
            background-color: {cls.COLORS['bg_primary']};
            color: {cls.COLORS['text']};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: {base_font}px;
        }}
        
        QLabel#appTitle {{
            color: {cls.COLORS['accent']};
            font-size: {title_font}px;
            font-weight: 700;
            padding: {title_pad_y}px {title_pad_x}px;
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: {title_border_radius}px;
        }}
        
        QGroupBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: {group_border_radius}px;
            margin-top: {group_margin_top}px;
            padding-top: {group_padding_top}px;
            font-weight: 600;
        }}
        
        QGroupBox::title {{
            color: {cls.COLORS['accent']};
            subcontrol-origin: margin;
            left: {group_title_left}px;
            padding: 0 {group_title_pad_x}px;
        }}
        
        QPushButton {{
            background-color: {cls.COLORS['accent']};
            color: white;
            border: none;
            border-radius: {button_border_radius}px;
            padding: {button_pad_y}px {button_pad_x}px;
            font-weight: 500;
            min-height: {button_min_height}px;
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
            border-radius: {tree_border_radius}px;
            selection-background-color: {cls.COLORS['accent']};
            alternate-background-color: #262626;
        }}
        
        QTreeWidget::item {{
            padding: {tree_item_padding}px;
            border-radius: {tree_item_border_radius}px;
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
            padding: {header_padding}px;
            border: none;
            border-bottom: {header_border_bottom}px solid {cls.COLORS['accent']};
            font-weight: 600;
        }}
        
        QComboBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: {combo_border_radius}px;
            padding: {combo_pad_y}px {combo_pad_x}px;
            min-width: {combo_min_width}px;
        }}
        
        QComboBox:hover {{
            border-color: {cls.COLORS['accent']};
        }}
        
        QSpinBox {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: {combo_border_radius}px;
            padding: {combo_pad_y}px {combo_pad_x}px;
        }}
        
        QSpinBox:hover {{
            border-color: {cls.COLORS['accent']};
        }}
        
        QProgressBar {{
            background-color: {cls.COLORS['bg_secondary']};
            border: 1px solid {cls.COLORS['border']};
            border-radius: {progress_border_radius}px;
            text-align: center;
            color: white;
        }}
        
        QProgressBar::chunk {{
            background-color: {cls.COLORS['accent']};
            border-radius: {progress_chunk_radius}px;
        }}
        
        QStatusBar {{
            background-color: {cls.COLORS['bg_primary']};
            border-top: {status_top_border}px solid {cls.COLORS['border']};
            color: {cls.COLORS['text_dim']};
        }}
        
        QLabel#statusLabel {{
            color: {cls.COLORS['accent']};
            font-weight: 500;
            padding: 0 {status_label_pad_x}px;
        }}
        
        QSplitter::handle {{
            background-color: {cls.COLORS['bg_primary']};
        }}
        
        QSplitter::handle:horizontal {{
            width: {splitter_handle_width}px;
        }}
        
        QScrollBar:vertical {{
            background-color: {cls.COLORS['bg_secondary']};
            width: {scrollbar_width}px;
            border-radius: {scrollbar_radius}px;
        }}
        
        QScrollBar::handle:vertical {{
            background-color: #4a4a4a;
            border-radius: {scrollbar_radius}px;
            min-height: {scrollbar_handle_min_height}px;
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
            padding: {tooltip_pad_y}px {tooltip_pad_x}px;
            border-radius: {tooltip_radius}px;
        }}
        """ + cls._action_button_stylesheet(scale)
