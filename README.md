# Audio Toolbox Pro

Professional audio file management with Claude-themed modern UI.

## Features

- **Import** - Auto-detect and import OBS recordings
- **Convert** - MP4/MKV to MP3 conversion with FFmpeg
- **Merge** - Combine multiple audio files by selection or date
- **Silence Removal** - Clean up recordings automatically
- **Organize** - Group files by date with timezone support
- **Modern UI** - Claude's signature orange theme with dark mode

## Quick Start

### macOS
```bash
# Double-click run.command or:
./run.command
```

### Other Systems
```bash
# Create virtual environment
python3 -m venv .venv

# Install dependencies
.venv/bin/pip install PyQt5 pytz

# Run
.venv/bin/python main.py
```

## Architecture

**Clean separation, no special cases** - Following Linus Torvalds' philosophy

```
Core (Business Logic)
├── audio_models.py      # Data structures - no logic
├── audio_processor.py   # Processing engine
├── file_organizer.py    # Date/timezone handling
└── external_tools.py    # FFmpeg/7-Zip wrapper

UI (Presentation Only)  
├── audio_gui.py         # Main window (320 lines)
├── ui_components.py     # Dumb UI components
├── file_presenter.py    # Data transformation
└── theme.py            # Claude theme configuration

Entry
└── main.py             # Application entry point
```

## Key Design Principles

1. **Data-Driven Design**
   - Theme is data, not strings
   - State mappings use lookups, not if/else chains
   - Configuration over conditionals

2. **Separation of Concerns**
   - UI components know nothing about business logic
   - Presenters transform data for display
   - Each module does ONE thing

3. **No Special Cases**
   - Single task dispatcher for all operations
   - Unified file state management
   - Consistent error handling

4. **Simple and Clear**
   - No function over 100 lines
   - No class over 320 lines
   - No nested conditionals beyond 2 levels

## Configuration

Optional `config.json`:
```json
{
  "ffmpeg_path": null,        // Auto-detected
  "sevenzip_path": null,      // Auto-detected
  "max_workers": 4,           // Thread pool size
  "default_timezone": "Asia/Shanghai",
  "log_level": "INFO"
}
```

## Dependencies

- Python 3.8+
- PyQt5 - GUI framework
- pytz - Timezone support
- FFmpeg - Media conversion (auto-detected)
- 7-Zip - Archive creation (optional)

## File Organization

Files are organized by recording date with timezone adjustment:
- Files recorded before 4 AM belong to previous day
- Timezone conversion from Beijing time (source) to selected timezone
- Automatic grouping with visual color coding

## Thread Safety

- All file operations are thread-safe
- Concurrent processing with configurable worker threads
- Progress updates via Qt signals

## Error Handling

- Graceful degradation when tools are missing
- Clear error messages in UI
- Detailed logging for debugging

## Code Quality

Following Linus Torvalds' principles:
- **"Good taste"** - Eliminate special cases
- **"Data structures matter"** - Clean models, not string parsing
- **"Keep it simple"** - Each component does one thing well

Total: ~1200 lines of clean, maintainable code vs 2000+ lines of spaghetti.

## License

MIT

## Contributing

Keep it simple. No special cases. Good taste wins.