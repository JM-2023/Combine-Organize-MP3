import os
import shutil
import re
from collections import defaultdict

# Regular expression to find the date and time
date_time_pattern = re.compile(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}-\d{2})')

# Create a dictionary to store files by date
files_by_date = defaultdict(list)

# Get all mp3 files in the current directory
mp3_files = [f for f in os.listdir() if f.endswith('.mp3')]

# Extract date and time and organize files by date
for file in mp3_files:
    match = date_time_pattern.search(file)
    if match:
        year, month, day, time = match.groups()
        # Formatting the date as YYYYMMDD
        formatted_date = f"{year}{month}{day}"
        files_by_date[formatted_date].append((time, file))

# Sort files by date and time, and move to corresponding folders
for date, files in files_by_date.items():
    # Sort files by time
    files.sort()
    # Create folder with the earliest file time
    folder_name = f"{date} {files[0][0]}"
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
    # Move files to the created folder
    for _, file in files:
        shutil.move(file, folder_name)
