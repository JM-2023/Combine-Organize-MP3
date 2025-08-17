#!/usr/bin/env python3
"""
File Presenter - Transform data for display
No if/else chains, use lookup tables
"""
from audio_models import FileState


class FilePresenter:
    """Transform file data for UI display - no special cases"""
    
    # State to style mapping - data driven, no if/else
    STATE_CONFIG = {
        FileState.UNPROCESSED: {
            'style': 'normal',
            'checkable': True,
            'disabled': False,
            'icon': '🎵',
        },
        FileState.PROCESSED: {
            'style': 'normal',
            'checkable': True,
            'disabled': False,
            'icon': '🎵',
        },
        FileState.MERGED: {
            'style': 'merged',
            'checkable': False,
            'disabled': True,
            'icon': '✓',
        },
        FileState.MERGED_OUTPUT: {
            'style': 'output',
            'checkable': False,
            'disabled': True,
            'icon': '📦',
        },
        FileState.CONVERTED: {
            'style': 'converted',
            'checkable': False,
            'disabled': True,
            'icon': '🔄',
        },
    }
    
    # File type icons
    TYPE_ICONS = {
        'mp3': '🎵',
        'mp4': '🎬',
        'mkv': '🎬',
        'wav': '🎵',
        'flac': '🎵',
    }
    
    @classmethod
    def present(cls, file):
        """Transform file to display data - single path, no branches"""
        config = cls.STATE_CONFIG.get(file.state, cls.STATE_CONFIG[FileState.UNPROCESSED])
        
        # Get icon based on type and state
        if file.is_video:
            icon = '🎬'
        else:
            ext = file.path.suffix[1:].lower()
            icon = cls.TYPE_ICONS.get(ext, config['icon'])
        
        # Build display name
        display = f"{icon} {file.basename}"
        if file.state == FileState.MERGED:
            display += " (merged)"
        elif file.state == FileState.MERGED_OUTPUT:
            display += " (output)"
        
        return {
            'display': display,
            'time': file.timestamp.strftime("%H:%M:%S"),
            'state': file.state.name,
            'size': cls.format_size(file.size),
            'style': config['style'],
            'checkable': config['checkable'],
            'disabled': config['disabled'],
            'ref': file,
        }
    
    @staticmethod
    def format_size(size):
        """Format file size - simple iteration, no special cases"""
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        for unit in units[:-1]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}{units[-1]}"