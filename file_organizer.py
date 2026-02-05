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
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from audio_models import AudioFile, FileState


class TimeZoneAdapter:
    """Handles all timezone-related logic in one place"""
    
    def __init__(self, timezone: str = 'UTC', cutoff_hour: int = 4):
        """
        Args:
            timezone: Target timezone for adjustment
            cutoff_hour: Hour before which files belong to previous day
        """
        self.timezone = timezone
        self.cutoff_hour = cutoff_hour
        self._tz = self._get_zone(timezone)

    def _get_zone(self, timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            logging.warning(f"Unknown timezone '{timezone}', falling back to UTC")
            return ZoneInfo("UTC")
        except Exception:
            return ZoneInfo("UTC")
    
    def get_adjusted_date(self, dt: datetime) -> date:
        """
        Get timezone-adjusted date with cutoff logic.
        Files before cutoff_hour belong to the previous day.
        """
        # Assume input datetime is in Beijing timezone
        beijing_tz = ZoneInfo("Asia/Shanghai")
        
        # If datetime is naive, localize it to Beijing timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=beijing_tz)
        
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
    
    def __init__(self, timezone: str = 'UTC', colors: List[str] = None, cutoff_hour: int = 4):
        self.timezone_adapter = TimeZoneAdapter(timezone, cutoff_hour=cutoff_hour)
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
        # Get timezone-adjusted dates for ALL files to determine grouping and colors
        adjusted_dates = {}
        adjusted_groups = {}
        
        for file in files:
            # Calculate adjusted date for this file
            adjusted_date = self.timezone_adapter.get_adjusted_date(file.timestamp)
            adjusted_dates[file.path] = adjusted_date
            
            # Group by adjusted date
            adjusted_date_key = adjusted_date.strftime("%Y-%m-%d")
            if adjusted_date_key not in adjusted_groups:
                adjusted_groups[adjusted_date_key] = []
            adjusted_groups[adjusted_date_key].append(file)
        
        # Assign colors based on unique adjusted dates
        unique_days = sorted(set(adjusted_dates.values()))
        day_colors = {day: self.colors[i % len(self.colors)] 
                      for i, day in enumerate(unique_days)}
        
        # Create FileGroup objects grouped by adjusted date
        groups = []
        for adjusted_date_key in sorted(adjusted_groups.keys()):
            files_in_group = sorted(adjusted_groups[adjusted_date_key], key=lambda f: f.timestamp)
            
            # Get the adjusted date for this group
            display_date = datetime.strptime(adjusted_date_key, "%Y-%m-%d").date()
            
            # Get color for this adjusted date
            group_color = day_colors.get(display_date)
            
            groups.append(FileGroup(
                date_key=adjusted_date_key,
                display_date=display_date,
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
            'disabled': file.state in [FileState.MERGED, FileState.CONVERTED, FileState.MERGED_OUTPUT],
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
        elif file.state == FileState.MERGED_OUTPUT:
            metadata['tooltip'] = "Merged output file - contains multiple recordings combined"
        
        return metadata
    
    def _get_file_icon(self, file: AudioFile) -> str:
        """Determine icon for file based on state and type"""
        if file.state == FileState.MERGED_OUTPUT:
            return "📦"  # Package icon for merged output
        elif file.is_video:
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
        if file.state == FileState.MERGED_OUTPUT:
            return " [OUTPUT]"
        elif file.source_file:
            return " [CONVERTED]"
        elif file.state == FileState.MERGED:
            return " [MERGED]"
        return ""
