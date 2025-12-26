#!/bin/bash
# Audio Toolbox - macOS Double-Click Launcher

# Change to script directory
cd "$(dirname "$0")"

# Display startup info
echo "🎵 Starting Audio Toolbox..."
echo "================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8 or later."
    echo "Press Enter to exit..."
    read
    exit 1
fi

# Check/create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    if ! ./.venv/bin/python -c "import sys" >/dev/null 2>&1; then
        echo "Refreshing virtual environment..."
        python3 -m venv --clear .venv
    fi
fi

# Activate and install dependencies
echo "Checking dependencies..."

# Set proxy for Clash (you can change port if needed)
PROXY_PORT=7897
echo "Configuring proxy settings for Clash (port $PROXY_PORT)..."
export HTTP_PROXY=http://127.0.0.1:$PROXY_PORT
export HTTPS_PROXY=http://127.0.0.1:$PROXY_PORT
export ALL_PROXY=socks5://127.0.0.1:$PROXY_PORT

# Upgrade pip with proxy and disable SSL verification
echo "Upgrading pip with proxy..."
./.venv/bin/pip config set global.proxy http://127.0.0.1:$PROXY_PORT
./.venv/bin/pip config set global.trusted-host "pypi.org files.pythonhosted.org"
./.venv/bin/pip install -q --upgrade pip

# Install required packages in virtual environment
# Check if already installed first to avoid unnecessary downloads
echo "Checking required packages..."

if ! ./.venv/bin/python -c "import PyQt5" 2>/dev/null; then
    echo "Installing PyQt5 (this may take a few minutes)..."
    ./.venv/bin/pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com PyQt5
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install PyQt5. Please check your internet connection."
        echo "You can try installing manually with:"
        echo "  ./.venv/bin/pip install PyQt5"
        echo "Press Enter to exit..."
        read
        exit 1
    fi
else
    echo "✓ PyQt5 already installed"
fi

if ! ./.venv/bin/python -c "import pytz" 2>/dev/null; then
    echo "Installing pytz..."
    ./.venv/bin/pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com pytz
else
    echo "✓ pytz already installed"
fi

# Check for moviepy if needed for compatibility
if ! ./.venv/bin/python -c "import moviepy" 2>/dev/null; then
    echo "Note: moviepy not installed (not required in clean version)"
fi

# Run the application
echo "================================"
echo "Starting application..."
./.venv/bin/python main.py

# Keep terminal open on error
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Program exited with error. Press Enter to close..."
    read
fi
