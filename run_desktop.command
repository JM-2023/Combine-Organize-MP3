#!/bin/bash
# Audio Toolbox - macOS Double-Click Launcher (Desktop UI / PyQt5)

cd "$(dirname "$0")"

echo "Starting Audio Toolbox Desktop UI..."
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

echo "Checking dependencies..."
if ! ./.venv/bin/python -c "import PyQt5" 2>/dev/null; then
    echo "Installing PyQt5 (this may take a few minutes)..."
    ./.venv/bin/pip install -q --upgrade pip
    ./.venv/bin/pip install PyQt5
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install PyQt5."
        echo "Try manually:"
        echo "  ./.venv/bin/pip install PyQt5"
        echo "Press Enter to exit..."
        read
        exit 1
    fi
else
    echo "✓ PyQt5 already installed"
fi

echo "================================"
echo "Starting application..."
./.venv/bin/python main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Program exited with error. Press Enter to close..."
    read
fi

exit 0
