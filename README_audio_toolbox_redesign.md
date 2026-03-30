# Audio Toolbox Web UI Redesign

## Included
- `index.html`, `styles.css`, `app.js`: redesigned modern UI
- `webui/`: modern UI files for `web_server.py`
- `webui_classic/`: backup of the previous UI so `/classic/` still works

## Added
- Light / Dark / Auto theme switch
- Compact search + filter bar
- Richer status feedback and stronger task panel
- Keyboard shortcuts:
  - `/` or `Ctrl/Cmd + K`: focus search
  - `Enter` / `Space`: toggle focused row
  - `Esc`: clear search / close organize confirm
- Improved density and motion polish with reduced-motion support

## Preserved core features
- Import OBS
- Convert to MP3
- Merge selected
- Merge by date
- Add time notes
- Remove silence
- Organize library
- Settings / telemetry / live task log
