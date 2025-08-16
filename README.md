4. **No special cases** - Single dispatcher for all operations
- **Clean data structures** - Proper models instead of string manipulation
- **Clear separation** - GUI, business logic, and external tools are separate
- **No global state** - Configuration passed explicitly

## Architecture

```
main.py                 # Entry point (50 lines)
├── audio_models.py     # Data structures (150 lines)
├── audio_processor.py  # Core logic (350 lines)
├── external_tools.py   # FFmpeg/7-Zip wrapper (200 lines)
└── audio_gui_clean.py  # GUI only (300 lines)
```



## Key Improvements

1. **Data Model First**
   - `AudioFile` class with proper state tracking
   - `AudioLibrary` with efficient lookups
   - No more regex parsing scattered everywhere

2. **Unified Processing**
   - Single `ProcessingTask` type for all operations
   - One dispatcher, not 5 different worker classes
   - Consistent error handling

3. **Clean External Tools**
   - `ToolManager` handles all FFmpeg/7-Zip operations
   - Single place for path detection
   - No global variables

4. **Minimal GUI**
   - Only presentation logic
   - Emits tasks, displays results
   - No business logic mixed in

## Usage

```bash
python main.py
```

## Configuration

Edit `config.json`:

- `ffmpeg_path`: Path to FFmpeg (auto-detected if null)
- `sevenzip_path`: Path to 7-Zip (auto-detected if null)
- `max_workers`: Thread pool size
- `date_pattern`: Regex for parsing timestamps from filenames