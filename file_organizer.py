#!/usr/bin/env python3
"""
File organization and presentation logic.
Handles timezone adjustment, grouping, and visual organization.
No GUI dependencies - pure data transformation.
"""
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
import pytz
import logging

from audio_models import AudioFile, FileState


class TimeZoneAdapter:
    """Handles all timezone-related logic in one place"""
    
    def __init__(self, timezone: str = 'UTC', cutoff_hour: int = 5):
        """
        Args:
            timezone: Target timezone for adjustment
            cutoff_hour: Hour before which files belong to previous day
        """
        self.timezone = timezone
        self.cutoff_hour = cutoff_hour
        self._tz = pytz.timezone(timezone)
    
    def get_adjusted_date(self, dt: datetime) -> date:
        """
        Get timezone-adjusted date with cutoff logic.
        Files before cutoff_hour belong to the previous day.
        """
        # Get local timezone
        local_tz = datetime.now().astimezone().tzinfo
        
        # Make datetime timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz)
        
        # Convert to target timezone
        tz_dt = dt.astimezone(self._tz)
        
        # Apply cutoff logic
        if tz_dt.hour < self.cutoff_hour:
            return (tz_dt - timedelta(days=1)).date()
        return tz_dt.date()
    
    def group_by_adjusted_date(self, files: List[AudioFile]) -> Dict[date, List[AudioFile]]:
        """Group files by timezone-adjusted date"""
        groups = {}
        for file in files:
            adjusted = self.get_adjusted_date(file.timestamp)
            if adjusted not in groups:
                groups[adjusted] = []
            groups[adjusted].append(file)
        return groups


@dataclass
class FileGroup:
    """A group of files for display"""
    date_key: str
    display_date: date
    files: List[AudioFile]
    color: Optional[str] = None


class FileOrganizer:
    """Organizes files for presentation without GUI dependencies"""
    
    # Default color palette - can be overridden via config
    DEFAULT_COLORS = [
        "#FFB3B3", "#B3D9FF", "#B3FFB3", "#FFFFB3", "#E6B3FF",
        "#FFB3E6", "#B3FFE6", "#FFE6B3", "#B3B3FF", "#E6FFB3"
    ]
    
    def __init__(self, timezone: str = 'UTC', colors: List[str] = None):
        self.timezone_adapter = TimeZoneAdapter(timezone)
        self.colors = colors or self.DEFAULT_COLORS
        self._mp3_stems_cache = set()
    
    def prepare_files(self, files: Set[AudioFile]) -> List[AudioFile]:
        """
        Prepare files for display:
        1. Filter out MP4s that have corresponding MP3s
        2. Sort by timestamp
        """
        # Update MP3 stems cache
        self._mp3_stems_cache = {f.path.stem for f in files if f.format == 'mp3'}
        
        # Filter and sort
        display_files = []
        for file in files:
            # Skip MP4 if MP3 exists
            if file.is_video and file.path.stem in self._mp3_stems_cache:
                continue
            display_files.append(file)
        
        return sorted(display_files, key=lambda f: f.timestamp)
    
    def group_files(self, files: List[AudioFile]) -> List[FileGroup]:
        """
        Group files by date and assign colors.
        Returns groups sorted chronologically.
        """
        # Group by original date
        date_groups = {}
        for file in files:
            date_key = file.date_key
            if date_key not in date_groups:
                date_groups[date_key] = []
            date_groups[date_key].append(file)
        
        # Get timezone-adjusted dates for unmerged files
        adjusted_dates = {}
        for file in files:
            if file.state == FileState.UNPROCESSED:
                adjusted_dates[file.path] = self.timezone_adapter.get_adjusted_date(file.timestamp)
        
        # Assign colors based on unique adjusted dates
        unique_days = set(adjusted_dates.values())
        sorted_days = sorted(unique_days)
        day_colors = {day: self.colors[i % len(self.colors)] 
                      for i, day in enumerate(sorted_days)}
        
        # Create FileGroup objects
        groups = []
        for date_key in sorted(date_groups.keys()):
            files_in_group = sorted(date_groups[date_key], key=lambda f: f.timestamp)
            
            # Determine group color (from first unmerged file)
            group_color = None
            for file in files_in_group:
                if file.path in adjusted_dates:
                    group_color = day_colors.get(adjusted_dates[file.path])
                    break
            
            groups.append(FileGroup(
                date_key=date_key,
                display_date=datetime.strptime(date_key, "%Y-%m-%d").date(),
                files=files_in_group,
                color=group_color
            ))
        
        return groups
    
    def get_file_color(self, file: AudioFile, adjusted_dates: Dict[Path, date]) -> Optional[str]:
        """Get display color for a specific file"""
        if file.path not in adjusted_dates:
            return None
        
        adjusted_date = adjusted_dates[file.path]
        unique_days = sorted(set(adjusted_dates.values()))
        
        try:
            day_index = unique_days.index(adjusted_date)
            return self.colors[day_index % len(self.colors)]
        except (ValueError, IndexError):
            return None
    
    def get_file_metadata(self, file: AudioFile) -> Dict[str, any]:
        """Get display metadata for a file"""
        metadata = {
            'icon': self._get_file_icon(file),
            'suffix': self._get_file_suffix(file),
            'selectable': file.state in [FileState.UNPROCESSED, FileState.PROCESSED],
            'disabled': file.state in [FileState.MERGED, FileState.CONVERTED],
        }
        
        # Add timezone info if needed
        if file.state == FileState.UNPROCESSED:
            adjusted = self.timezone_adapter.get_adjusted_date(file.timestamp)
            original = file.timestamp.date()
            if adjusted != original:
                metadata['tooltip'] = (f"Original: {original}\n"
                                     f"In {self.timezone_adapter.timezone}: {adjusted} "
                                     f"({self.timezone_adapter.cutoff_hour}am cutoff)")
            else:
                metadata['tooltip'] = f"Date in {self.timezone_adapter.timezone}: {adjusted}"
        
        return metadata
    
    def _get_file_icon(self, file: AudioFile) -> str:
        """Determine icon for file based on state and type"""
        if file.is_video:
            return "🎬"
        elif file.state == FileState.MERGED:
            return "🔒"
        elif file.state == FileState.CONVERTED:
            return "✓"
        elif file.source_file:
            return "🎵"
        return ""
    
    def _get_file_suffix(self, file: AudioFile) -> str:
        """Determine suffix text for file"""
        if file.source_file:
            return " [CONVERTED]"
        elif file.state == FileState.MERGED:
            return " [MERGED]"
        return ""