from moviepy.editor import concatenate_audioclips, AudioFileClip
import os
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import re
import msvcrt  # For Windows
import sys

directory = os.getcwd()  # Current directory

# ANSI Escape Code Definitions
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

# List comprehension to get all mp3 files
mp3_files = [f for f in os.listdir(directory) if f.endswith('.mp3')]

def parse_time_from_filename(filename):
    date_time_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
    match = date_time_pattern.search(filename)
    if match:
        date_str, time_str = match.groups()[:2]
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        try:
            # Try to parse time with seconds
            time = datetime.strptime(time_str, "%H-%M-%S").time()
        except ValueError:
            # If it fails, parse time without seconds
            time = datetime.strptime(time_str, "%H-%M").time()
        return datetime.combine(date, time)
    else:
        return None

def parse_date_and_time_from_filename(filename):
    date_time_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
    match = date_time_pattern.search(filename)
    if match:
        date_str, time_str = match.groups()[:2]
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        try:
            # Try to parse time with seconds
            time = datetime.strptime(time_str, "%H-%M-%S").time()
        except ValueError:
            # If it fails, parse time without seconds
            time = datetime.strptime(time_str, "%H-%M").time()
        return date, time
    else:
        return None, None

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
            print(f"Error: {e}")
            return None

def select_files_to_merge():
    if not grouped_files:
        print("No MP3 files found with the expected date-time format.")
        return None

    # Display available dates
    dates = sorted(grouped_files.keys())
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

def process_files(date, files):
    # Sort the list based on time in the filename
    files.sort(key=lambda x: parse_time_from_filename(x))

    print(f"\nProcessing files for {date.strftime('%Y-%m-%d')}:")
    for file in files:
        print(f"- {file}")

    audio_clips = []
    for mp3_file in files:
        audio_clip = AudioFileClip(os.path.join(directory, mp3_file))
        if audio_clip.duration > 0:
            audio_clips.append(audio_clip)
        else:
            print(f"Skipping zero-duration clip: {mp3_file}")

    if not audio_clips:
        print(f"No valid audio clips found for {date}")
        return

    # Get the first audio clip filename
    first_clip_filename = files[0]

    # Extract date and time from the first audio clip filename
    first_clip_date, first_clip_time = parse_date_and_time_from_filename(first_clip_filename)

    if first_clip_date is None or first_clip_time is None:
        print(f"Could not parse date and time from filename: {first_clip_filename}")
        return

    # Format the date and time for the output filename
    output_filename = f"{first_clip_date.strftime('%Y%m%d')} {first_clip_time.strftime('%H-%M')}.mp3"

    print(f"\n{BOLD}{GREEN}Merging files into: {output_filename}{RESET}")
    final_clip = concatenate_audioclips(audio_clips)
    final_clip.write_audiofile(os.path.join(directory, output_filename))
    print(f"{BOLD}{CYAN}Merge complete! Output saved as: {output_filename}{RESET}")

    return True

# Group files by date
grouped_files = defaultdict(list)
for mp3_file in mp3_files:
    # Extract date and time from filename
    date, _ = parse_date_and_time_from_filename(mp3_file)
    if date is not None:
        grouped_files[date].append(mp3_file)

def main():
    print(f"{BOLD}{YELLOW}MP3 File Merger{RESET}")
    print(f"{'=' * 15}")
    
    if not mp3_files:
        print("No MP3 files found in the current directory.")
        return

    while True:
        selection = select_files_to_merge()
        if selection is None:
            break
            
        date, files = selection
        if files is not None:
            # "Merge all" choice was selected
            success = process_files(date, files)
            if input("\nWould you like to merge more files? (y/n): ").lower() != 'y':
                break
        else:
            # Interactive selection on this date
            day_files = sorted(grouped_files[date], key=parse_time_from_filename)
            merged_files = set()  # keep track of all merged files for this date

            while True:
                selected_files = interactive_file_selection(day_files, merged_files)
                if not selected_files:
                    # No selection, user might have quit or pressed Enter with no selection
                    # Ask if user wants to exit this date
                    proceed = input("\nNo files selected. Return to main menu? (y/n): ").lower()
                    if proceed == 'y':
                        break
                    else:
                        # Continue selecting
                        continue
                
                success = process_files(date, selected_files)
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

    print(f"\n{BOLD}{GREEN}Thank you for using MP3 File Merger!{RESET}")

if __name__ == "__main__":
    main()
