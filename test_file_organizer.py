import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from audio_models import AudioFile
from file_organizer import FileOrganizer


class FileOrganizerPrepareFilesTests(unittest.TestCase):
    def _make_file(self, root: Path, name: str, timestamp: datetime) -> AudioFile:
        path = root / name
        path.write_bytes(name.encode("utf-8"))
        return AudioFile.from_path(path, timestamp)

    def test_prepare_files_hides_matching_video_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            timestamp = datetime(2026, 3, 6, 9, 0)
            mp3 = self._make_file(root, "2026-03-06 09-00.mp3", timestamp)
            mp4 = self._make_file(root, "2026-03-06 09-00.mp4", timestamp)

            organizer = FileOrganizer("Asia/Shanghai")
            files = organizer.prepare_files({mp3, mp4})

        self.assertEqual([file.basename for file in files], ["2026-03-06 09-00.mp3"])

    def test_prepare_files_keeps_matching_video_when_filter_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_timestamp = datetime(2026, 3, 6, 9, 0)
            mp3 = self._make_file(root, "2026-03-06 09-00.mp3", base_timestamp)
            mp4 = self._make_file(root, "2026-03-06 09-00.mp4", base_timestamp)
            later = self._make_file(root, "2026-03-06 09-01.mp3", datetime(2026, 3, 6, 9, 1))

            organizer = FileOrganizer("Asia/Shanghai")
            files = organizer.prepare_files({later, mp4, mp3}, hide_videos_with_matching_mp3=False)

        self.assertEqual(
            [file.basename for file in files],
            [
                "2026-03-06 09-00.mp3",
                "2026-03-06 09-00.mp4",
                "2026-03-06 09-01.mp3",
            ],
        )


if __name__ == "__main__":
    unittest.main()
