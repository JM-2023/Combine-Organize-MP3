import os
import sys
import re
import json
import logging
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# Only works well on Windows for arrow keys; remove or adapt if on another platform.
import msvcrt

from moviepy.editor import concatenate_audioclips, AudioFileClip

# ANSI Escape Code Definitions for Coloring
RESET = "\033[0m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_BLUE = "\033[44m"

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

# Load configuration if available
def load_config():
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning("Failed to load config.json: %s", e)
    return {}

config = load_config()

# Configuration Defaults
DATE_TIME_REGEX = config.get("date_time_regex", r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
DEFAULT_DATE_FORMAT = config.get("default_date_format", "%Y-%m-%d")
DEFAULT_TIME_FORMAT = config.get("default_time_format", "%H-%M-%S")
OUTPUT_DIR = config.get("default_output_dir", None)  # None means current directory

directory = os.getcwd()  # Current directory
if OUTPUT_DIR and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# Compile the date time pattern
date_time_pattern = re.compile(DATE_TIME_REGEX)

# List comprehension to get all mp3 files
mp3_files = [f for f in os.listdir(directory) if f.endswith('.mp3')]

def parse_date_and_time_from_filename(filename):
    match = date_time_pattern.search(filename)
    if match:
        date_str, time_str = match.groups()[:2]
        try:
            date = datetime.strptime(date_str, DEFAULT_DATE_FORMAT).date()
        except ValueError:
            return None, None
        # Try parsing time with seconds first
        try:
            time = datetime.strptime(time_str, DEFAULT_TIME_FORMAT).time()
        except ValueError:
            # If it fails, parse time without seconds (HH-MM)
            try:
                time = datetime.strptime(time_str, "%H-%M").time()
            except ValueError:
                return None, None
        return date, time
    else:
        return None, None

def parse_time_from_filename(filename):
    date, time = parse_date_and_time_from_filename(filename)
    if date and time:
        return datetime.combine(date, time)
    return datetime.min  # fallback to a minimal datetime if parsing fails

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_file_list(files, selected_files, merged_files, current_index):
    """Print the file list with checkboxes and highlight the current selection.
       Already merged files appear in MAGENTA and cannot be selected again.
    """
    clear_screen()
    # Instructions in bold blue
    print(f"\n{BOLD}{BLUE}Select files to merge (Use ↑↓ to navigate, Space to select/deselect, Enter to confirm):{RESET}\n")
    for i, file in enumerate(files):
        # Determine checkbox state and color
        if file in merged_files:
            # Already merged files - show as [*] in MAGENTA
            checkbox = f"{MAGENTA}[*]{RESET}"
            file_color = MAGENTA
        else:
            # Regular files
            checkbox = f"{GREEN}[x]{RESET}" if file in selected_files else f"{RED}[ ]{RESET}"
            file_color = WHITE
        
        line_str = f"{checkbox} {file_color}{file}{RESET}"

        if i == current_index:
            # Highlight the current line with a blue background
            print(f"{BG_BLUE}{line_str}{RESET}")
        else:
            print(line_str)
    
    # Show the count of selected files in bold yellow
    print(f"\n{BOLD}{YELLOW}Selected files:{RESET}", len([f for f in selected_files if f not in merged_files]))
    # Instructions for other keys
    print(f"\nPress '{RED}q{RESET}' to quit, '{GREEN}a{RESET}' to select all non-merged, '{RED}d{RESET}' to deselect all")

def interactive_file_selection(files, merged_files):
    """
    Provide an interactive file selection interface with checkboxes.
    Already merged files are shown differently and cannot be re-selected.
    Returns a list of selected files.
    """
    selected_files = set()
    current_index = 0
    
    while True:
        print_file_list(files, selected_files, merged_files, current_index)
        
        try:
            key = msvcrt.getch()  # Get keypress without Enter
            
            if key == b'\xe0':  # Special key prefix
                key = msvcrt.getch()  # Get the actual special key
                if key == b'H':  # Up arrow
                    current_index = (current_index - 1) % len(files)
                elif key == b'P':  # Down arrow
                    current_index = (current_index + 1) % len(files)
            elif key == b' ':  # Space
                current_file = files[current_index]
                if current_file in merged_files:
                    # Already merged, do not toggle
                    pass
                else:
                    if current_file in selected_files:
                        selected_files.remove(current_file)
                    else:
                        selected_files.add(current_file)
            elif key == b'\r':  # Enter
                # Return only non-merged selected files
                final_selection = [f for f in selected_files if f not in merged_files]
                if final_selection:
                    return final_selection
            elif key == b'q':  # Quit
                return None
            elif key == b'a':  # Select all non-merged
                selected_files = set(f for f in files if f not in merged_files)
            elif key == b'd':  # Deselect all
                selected_files.clear()
                
        except Exception as e:
            logging.error(f"Error during selection: {e}")
            return None

def select_files_to_merge(grouped_files):
    if not grouped_files:
        logging.info("No MP3 files found with the expected date-time format.")
        return None

    # Display available dates
    dates = sorted(grouped_files.keys())
    clear_screen()
    print("\nAvailable dates:")
    for i, date in enumerate(dates, 1):
        print(f"{i}. {date.strftime('%Y-%m-%d')} ({len(grouped_files[date])} files)")
        print(f"{i}a. Merge all files for {date.strftime('%Y-%m-%d')}")

    # Select date
    while True:
        try:
            choice = input("\nSelect a choice (number or number+a) or 0 to exit: ").strip().lower()
            if choice == '0':
                return None
                
            # Check if it's a "merge all" choice
            if choice.endswith('a'):
                try:
                    date_num = int(choice[:-1])
                    if 1 <= date_num <= len(dates):
                        selected_date = dates[date_num - 1]
                        # Return all files for the selected date, sorted by time
                        return selected_date, sorted(grouped_files[selected_date], key=parse_time_from_filename)
                except ValueError:
                    print("Invalid selection. Please try again.")
                    continue
            else:
                # Regular selection for individual file choosing
                date_choice = int(choice)
                if 1 <= date_choice <= len(dates):
                    selected_date = dates[date_choice - 1]
                    # Return the date, and we'll handle interactive selection outside
                    return selected_date, None
                
            print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number or number+a (e.g., '1' or '1a').")

def load_audio_clip(file_path):
    try:
        clip = AudioFileClip(file_path)
        return clip
    except Exception as e:
        logging.error("Error loading clip %s: %s", file_path, e)
        return None

def process_files(date, files, output_dir):
    # Sort the list based on time in the filename
    files.sort(key=lambda x: parse_time_from_filename(x))
    file_paths = [os.path.join(directory, f) for f in files]

    # Parallel loading with progress
    audio_clips = []
    with ThreadPoolExecutor() as executor:
        # Map with progress bar
        futures = list(tqdm(executor.map(load_audio_clip, file_paths), total=len(file_paths), desc="Loading Clips"))
        for clip in futures:
            if clip and clip.duration > 0:
                audio_clips.append(clip)

    if not audio_clips:
        logging.warning(f"No valid audio clips found for {date}")
        return False

    # Calculate total duration
    total_duration = sum(clip.duration for clip in audio_clips if clip)
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    logging.info(f"Total merged duration: {minutes} minutes and {seconds} seconds.")

    # Get the first audio clip filename
    first_clip_filename = files[0]

    # Extract date and time from the first audio clip filename
    first_clip_date, first_clip_time = parse_date_and_time_from_filename(first_clip_filename)

    if first_clip_date is None or first_clip_time is None:
        logging.error(f"Could not parse date and time from filename: {first_clip_filename}")
        return False

    # Format the date and time for the output filename
    output_filename = f"{first_clip_date.strftime('%Y%m%d')} {first_clip_time.strftime('%H-%M')}.mp3"

    if output_dir:
        output_path = os.path.join(output_dir, output_filename)
    else:
        output_path = os.path.join(directory, output_filename)

    logging.info(f"Merging files into: {output_filename}")

    try:
        final_clip = concatenate_audioclips(audio_clips)
        final_clip.write_audiofile(output_path)
        # Close all clips
        for c in audio_clips:
            c.close()
        final_clip.close()
        logging.info(f"Merge complete! Output saved as: {output_path}")
        return True
    except Exception as e:
        logging.error("Error during merging: %s", e)
        return False

# Group files by date
grouped_files = defaultdict(list)
for mp3_file in mp3_files:
    date, _ = parse_date_and_time_from_filename(mp3_file)
    if date is not None:
        grouped_files[date].append(mp3_file)

def main():
    logging.info("MP3 File Merger Started")
    print(f"{BOLD}{YELLOW}MP3 File Merger{RESET}")
    print("=" * 15)

    if not mp3_files:
        logging.info("No MP3 files found in the current directory.")
        return

    while True:
        selection = select_files_to_merge(grouped_files)
        if selection is None:
            break
            
        date, files = selection
        if files is not None:
            # "Merge all" choice was selected
            success = process_files(date, files, OUTPUT_DIR)
            if input("\nWould you like to merge more files? (y/n): ").lower() != 'y':
                break
        else:
            # Interactive selection on this date
            day_files = sorted(grouped_files[date], key=parse_time_from_filename)
            merged_files = set()  # keep track of all merged files for this date

            while True:
                selected_files = interactive_file_selection(day_files, merged_files)
                if not selected_files:
                    # No selection, ask user if they want to return to main menu
                    proceed = input("\nNo files selected. Return to main menu? (y/n): ").lower()
                    if proceed == 'y':
                        break
                    else:
                        continue
                
                success = process_files(date, selected_files, OUTPUT_DIR)
                if success:
                    # Mark selected files as merged
                    merged_files.update(selected_files)

                # Ask if user wants to merge more files from the same day
                more = input("\nWould you like to merge more files from the same day? (y/n): ").lower()
                if more != 'y':
                    # Exit to main menu
                    break

        # After finishing with this date
        if input("\nWould you like to merge files from another date? (y/n): ").lower() != 'y':
            break

    logging.info("Thank you for using MP3 File Merger!")
    print(f"\n{BOLD}{GREEN}Thank you for using MP3 File Merger!{RESET}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")
        sys.exit(0)
    except Exception as e:
        logging.error("An unexpected error occurred: %s", e)
        sys.exit(1)
