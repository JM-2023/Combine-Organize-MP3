import os
import shutil
import re

# Get all mp3 files in current directory
mp3_files = [f for f in os.listdir() if f.endswith('.mp3')]

# Regular expression to find the date
date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')

for file in mp3_files:
    match = date_pattern.search(file)
    if match:
        date = match.group()
        if not os.path.exists(date):
            os.makedirs(date)
        shutil.move(file, date)
