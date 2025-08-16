#!/usr/bin/env python3
"""
Data models for audio processing.
No business logic, just data structures.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum, auto
from typing import Optional, List, Set


class FileState(Enum):
    """Simple state machine for file lifecycle"""
    UNPROCESSED = auto()
    PROCESSING = auto()
    PROCESSED = auto()
    CONVERTED = auto()  # MP4 converted to MP3
    MERGED = auto()
    MERGED_OUTPUT = auto()  # Output file from merge operation
    FAILED = auto()


class TaskType(Enum):
    """All possible operations on files"""
    IMPORT = auto()
    CONVERT = auto()
    MERGE = auto()
    REMOVE_SILENCE = auto()
    ORGANIZE = auto()


@dataclass
class AudioFile:
    """Single source of truth for an audio file"""
    path: Path
    timestamp: datetime
    state: FileState = FileState.UNPROCESSED
    duration: Optional[float] = None
    size: int = 0
    format: str = ""
    source_file: Optional[Path] = None  # For tracking conversions
    output_files: List[Path] = field(default_factory=list)  # Files created from this
    
    def __post_init__(self):
        # Only type conversion, no I/O
        if isinstance(self.path, str):
            self.path = Path(self.path)
        if not self.format:
            self.format = self.path.suffix.lower().lstrip('.')
    
    @classmethod
    def from_path(cls, path: Path, timestamp: Optional[datetime] = None) -> 'AudioFile':
        """Factory method that handles I/O operations"""
        if isinstance(path, str):
            path = Path(path)
        
        # Get file size (I/O operation)
        size = path.stat().st_size if path.exists() else 0
        
        # Use provided timestamp or file modification time
        if timestamp is None:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime)
        
        return cls(
            path=path,
            timestamp=timestamp,
            size=size,
            format=path.suffix.lower().lstrip('.')
        )
    
    @property
    def basename(self) -> str:
        return self.path.name
    
    @property
    def date_key(self) -> str:
        """Group files by date"""
        return self.timestamp.strftime("%Y-%m-%d")
    
    @property
    def is_video(self) -> bool:
        """Check if file is a video format"""
        return self.format in ['mp4', 'avi', 'mov', 'mkv']
    
    @property
    def is_audio(self) -> bool:
        """Check if file is an audio format"""
        return self.format in ['mp3', 'wav', 'm4a', 'flac', 'ogg']
    
    def __hash__(self):
        return hash(self.path)
    
    def __eq__(self, other):
        if not isinstance(other, AudioFile):
            return False
        return self.path == other.path


@dataclass
class ProcessingTask:
    """A unit of work to be processed"""
    task_type: TaskType
    files: List[AudioFile]
    output_dir: Path
    params: dict = field(default_factory=dict)
    
    @property
    def task_id(self) -> str:
        """Unique identifier for this task"""
        file_hash = hash(tuple(f.path for f in self.files))
        return f"{self.task_type.name}_{file_hash}"


@dataclass
class TaskResult:
    """Result of a processing task"""
    task: ProcessingTask
    success: bool
    output_files: List[Path] = field(default_factory=list)
    error: Optional[str] = None
    processed_count: int = 0
    
    @property
    def failed_count(self) -> int:
        return len(self.task.files) - self.processed_count


@dataclass
class AudioLibrary:
    """Collection of audio files with efficient lookups"""
    files: Set[AudioFile] = field(default_factory=set)
    _by_date: dict = field(default_factory=dict, init=False)
    _by_state: dict = field(default_factory=dict, init=False)
    
    def add(self, file: AudioFile):
        """Add file and update indexes"""
        self.files.add(file)
        self._index_file(file)
    
    def remove(self, file: AudioFile):
        """Remove file and update indexes"""
        self.files.discard(file)
        self._deindex_file(file)
    
    def update_state(self, file: AudioFile, new_state: FileState):
        """Update file state and maintain indexes"""
        old_state = file.state
        file.state = new_state
        
        # Update state index
        if old_state in self._by_state:
            self._by_state[old_state].discard(file)
        
        if new_state not in self._by_state:
            self._by_state[new_state] = set()
        self._by_state[new_state].add(file)
    
    def get_by_date(self, date_str: str) -> Set[AudioFile]:
        """Get all files for a specific date"""
        return self._by_date.get(date_str, set())
    
    def get_by_state(self, state: FileState) -> Set[AudioFile]:
        """Get all files in a specific state"""
        return self._by_state.get(state, set())
    
    def get_unmerged_for_date(self, date_str: str) -> List[AudioFile]:
        """Get unprocessed files for merging on a specific date"""
        date_files = self.get_by_date(date_str)
        return sorted(
            [f for f in date_files if f.state == FileState.UNPROCESSED],
            key=lambda f: f.timestamp
        )
    
    def _index_file(self, file: AudioFile):
        """Add file to internal indexes"""
        # Date index
        date_key = file.date_key
        if date_key not in self._by_date:
            self._by_date[date_key] = set()
        self._by_date[date_key].add(file)
        
        # State index
        if file.state not in self._by_state:
            self._by_state[file.state] = set()
        self._by_state[file.state].add(file)
    
    def _deindex_file(self, file: AudioFile):
        """Remove file from internal indexes"""
        date_key = file.date_key
        if date_key in self._by_date:
            self._by_date[date_key].discard(file)
        
        if file.state in self._by_state:
            self._by_state[file.state].discard(file)
    
    def clear(self):
        """Clear all files and indexes"""
        self.files.clear()
        self._by_date.clear()
        self._by_state.clear()