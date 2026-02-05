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
# Web UI (recommended): double-click run.command or:
./run.command
```

Desktop UI (optional):
```bash
./run_desktop.command
```

### Other Systems
```bash
# Web UI (standard library only)
python3 web_server.py
```

## UI Tips

- Web UI runs locally on `127.0.0.1` and opens in your browser.
- Desktop UI remembers window/split sizes; if it ever opens too small/off-screen, use `View → Reset Window Layout`.

## Behavior & Naming

### Scan & Timestamp Extraction

- The app scans the current working directory for media files (`.mp3`, `.mp4`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.avi`, `.mov`, `.mkv`).
- For most files, timestamps are extracted from the filename using `date_pattern` (see `config.json`). If no match is found, the file modification time (mtime) is used.
- Some files are treated specially as **merge outputs** (see below) so they don’t get merged/organized again.

### Merge Details

- Inputs are sorted chronologically by the extracted timestamp.
- Merge uses FFmpeg concat demuxer with stream copy (`-c copy`) to avoid re-encoding.
- A temporary `concat_list.txt` is created next to the output and removed after the merge completes.

### Merge Output Filename Rules

- Base name: the first input file’s timestamp formatted as `YYYYMMDD HH-MM`.
- Comment propagation: any comment groups found in input filenames are appended to the output name.
  - Recognizes both ASCII `(...)` and fullwidth `（...）` in *source* filenames.
  - Output always uses ASCII parentheses `(...)` (fullwidth is normalized).
  - If a filename contains multiple groups, all groups are appended.
  - Duplicate groups across multiple inputs are de-duplicated (first-seen order).
- Example: `20251226 10-00 (intro) (Q&A).mp3`

### Merged Output Detection

- Files matching `YYYYMMDD HH-MM` with optional trailing comment groups are treated as merge outputs:
  - Marked as `MERGED_OUTPUT` on scan
  - Skipped by **Organize** (so packaged outputs aren’t moved into date folders)
- For backward compatibility, detection also accepts fullwidth `（...）` in existing merge outputs.

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

Web UI (Presentation Only)
├── web_server.py        # Local web server + JSON API
└── webui/               # Static HTML/CSS/JS

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
  "date_pattern": null,       // Optional filename timestamp regex override
  "default_timezone": "Asia/Shanghai",
  "ui_window_scale": 0.4,     // Default window size relative to screen
  "ui_scale": 1.0,            // Base UI scale (fonts/padding)
  "ui_auto_scale": true,      // Auto-adjust UI scale with window size
  "log_level": "INFO"
}
```

## Dependencies

- Python 3.9+
- Web UI: standard library only (no pip dependencies)
- Desktop UI (optional): PyQt5
- FFmpeg - Media conversion (auto-detected)
- 7-Zip - Optional for `.7z` archives (otherwise `.zip`)

## File Organization

### UI Date Grouping (Timezone + Cutoff)

- Files are grouped in the UI by a timezone-adjusted date (default `Asia/Shanghai`).
- A 4 AM cutoff is applied: files before cutoff are shown under the previous day.
- Assumes source timestamps are in Beijing time (naive datetimes are treated as `Asia/Shanghai`).

### Organize Operation (Filesystem)

- Moves source files into folders under the current working directory.
- Folder name format: `YYYYMMDD HH-MM` (based on the first file in that date group).
- Merge output files are skipped so merged `.mp3` outputs stay at top level.

## Thread Safety

- All file operations are thread-safe
- Concurrent processing with configurable worker threads
- Progress updates via background task logs (Web UI) or Qt signals (Desktop UI)

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
