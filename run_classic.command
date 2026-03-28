#!/bin/bash
# Audio Toolbox - macOS Double-Click Launcher (Classic Web UI)

cd "$(dirname "$0")"

echo "Starting Audio Toolbox Classic Web UI..."
echo "================================"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8 or later."
    echo "Press Enter to exit..."
    read
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    if ! ./.venv/bin/python -c "import sys" >/dev/null 2>&1; then
        echo "Refreshing virtual environment..."
        python3 -m venv --clear .venv
    fi
fi

echo "================================"
echo "Starting server (it will open Chrome)..."
echo "Target route: classic Web UI"
./.venv/bin/python web_server.py --open-path /classic/

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Program exited with error. Press Enter to close..."
    read
fi

exit 0
