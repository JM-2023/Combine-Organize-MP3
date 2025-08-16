#!/usr/bin/env python3
"""
Main application entry point.
Simple, clean, no special cases.
"""
import sys
import json
import logging
from pathlib import Path
from PyQt5.QtWidgets import QApplication

from audio_gui_clean import AudioToolboxGUI


def load_config() -> dict:
    """Load configuration if it exists"""
    config_path = Path.cwd() / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load config: {e}")
    return {}


def setup_logging(level: str = "INFO"):
    """Configure logging"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )


def main():
    """Application entry point"""
    # Load configuration
    config = load_config()
    
    # Setup logging
    setup_logging(config.get('log_level', 'INFO'))
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Audio Toolbox")
    
    # Create and show main window
    window = AudioToolboxGUI(config)
    window.show()
    
    # Run event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()