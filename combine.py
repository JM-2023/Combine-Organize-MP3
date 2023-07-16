from moviepy.editor import concatenate_audioclips, AudioFileClip
import os
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

directory = os.getcwd()  # Current directory

# List comprehension to get all mp3 files
mp3_files = [f for f in os.listdir(directory) if f.endswith('.mp3')]

# Group files by date
grouped_files = defaultdict(list)
for mp3_file in mp3_files:
    # Extract date and time from filename
    base_name = os.path.splitext(mp3_file)[0]  # Removes .mp3
    parts = base_name.split(" ")

    if len(parts) < 2:
        continue  # Skip files that don't have the expected format

    date_string = parts[0]
    date = datetime.strptime(date_string, "%Y-%m-%d").date()

    grouped_files[date].append(mp3_file)

def process_files(date, files):
    # Sort the list based on time in the filename
    files.sort(key=lambda x: parse_time_from_filename(x))

    print(f"Sorted list for {date.strftime('%Y-%m-%d')} is {files}")  # Print the sorted list

    audio_clips = [AudioFileClip(os.path.join(directory, mp3_file)) for mp3_file in files]

    final_clip = concatenate_audioclips(audio_clips)
    final_clip.write_audiofile(os.path.join(directory, f"{date.strftime('%Y%m%d')}.mp3"))

def parse_time_from_filename(filename):
    time_str = os.path.splitext(filename.split(" ")[1])[0]
    try:
        # Try to parse time with milliseconds
        return datetime.strptime(time_str, "%H-%M-%S-%f")
    except ValueError:
        # If it fails, parse time without milliseconds
        return datetime.strptime(time_str, "%H-%M-%S")

# Process files concurrently
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(process_files, date, files) for date, files in grouped_files.items()]
    # Wait for all tasks to complete
    for future in futures:
        future.result()
