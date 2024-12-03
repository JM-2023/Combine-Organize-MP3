from moviepy.editor import AudioFileClip
import os
import concurrent.futures

def convert_mp4_to_mp3(video_file):
    # Remove .mp4 from video_file string and add .mp3
    audio_file = os.path.splitext(video_file)[0] + '.mp3'
    clip = AudioFileClip(video_file)
    clip.write_audiofile(audio_file, codec='mp3')

def convert_all_mp4_in_directory():
    # Get all files in the current directory
    files = os.listdir()

    # Filter the list to only .mp4 files
    mp4_files = [f for f in files if f.endswith('.mp4')]

    # Use a ThreadPoolExecutor to convert multiple files at the same time
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.map(convert_mp4_to_mp3, mp4_files)

# Call the function to convert all .mp4 files in the current directory
convert_all_mp4_in_directory()