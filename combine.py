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

def parse_time_from_filename(filename):
    time_str = os.path.splitext(filename.split(" ")[1])[0]
    try:
        # Try to parse time with milliseconds
        return datetime.strptime(time_str, "%H-%M-%S-%f")
    except ValueError:
        try:
            # If it fails, parse time without milliseconds
            return datetime.strptime(time_str, "%H-%M-%S")
        except ValueError:
            # If it fails again, parse time without seconds
            return datetime.strptime(time_str, "%H-%M")

def parse_date_and_time_from_filename(filename):
    base_name = os.path.splitext(filename)[0]  # Removes .mp3
    date_str, time_str = base_name.split(" ")

    date = datetime.strptime(date_str, "%Y-%m-%d").date()

    try:
        # Try to parse time with milliseconds
        time = datetime.strptime(time_str, "%H-%M-%S-%f").time()
    except ValueError:
        # If it fails, parse time without milliseconds
        time = datetime.strptime(time_str, "%H-%M-%S").time()

    return date, time

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
