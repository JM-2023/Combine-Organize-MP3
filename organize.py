import os
import shutil
import re
import subprocess
from collections import defaultdict

# Path to 7z.exe - adjust this to the correct path on your system
path_to_7zip = ""

# Get the current working directory
working_directory = os.getcwd()

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
        formatted_date = f"{year}{month}{day}"  # Formatting the date as YYYYMMDD
        files_by_date[formatted_date].append((time, file))

# Sort files by date and time, move to corresponding folders, and ZIP them
for date, files in files_by_date.items():
    files.sort()  # Sort files by time
    folder_name = f"{date} {files[0][0]}"
    folder_path = os.path.join(working_directory, folder_name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    for _, file in files:
        shutil.move(file, folder_path)

    # Create ZIP using 7-Zip
    zip_command = f"{path_to_7zip} a \"{folder_name}.zip\" \"{folder_path}\""  # Command to create a ZIP file
    subprocess.run(zip_command, shell=True)  # Execute the ZIP command