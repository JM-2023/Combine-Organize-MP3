from moviepy.editor import concatenate_audioclips, AudioFileClip
import os
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import re

directory = os.getcwd()  # Current directory

# List comprehension to get all mp3 files
mp3_files = [f for f in os.listdir(directory) if f.endswith('.mp3')]

def parse_time_from_filename(filename):
    date_time_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}(-\d{2})?)')
    match = date_time_pattern.search(filename)
    if match:
        date_str, time_str = match.groups()[:2]  # Use the first two groups, which include the date and the optional seconds
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
        date_str, time_str = match.groups()[:2]  # Use the first two groups, which include the date and the optional seconds
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

# Group files by date
grouped_files = defaultdict(list)
for mp3_file in mp3_files:
    # Extract date and time from filename
    date, _ = parse_date_and_time_from_filename(mp3_file)
    if date is not None:
        grouped_files[date].append(mp3_file)

def process_files(date, files):
    # Sort the list based on time in the filename
    files.sort(key=lambda x: parse_time_from_filename(x))

    print(f"Sorted list for {date.strftime('%Y-%m-%d')} is {files}")  # Print the sorted list

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

    final_clip = concatenate_audioclips(audio_clips)
    final_clip.write_audiofile(os.path.join(directory, output_filename))

# Process files concurrently
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(process_files, date, files) for date, files in grouped_files.items()]
    # Wait for all tasks to complete
    for future in futures:
        future.result()
