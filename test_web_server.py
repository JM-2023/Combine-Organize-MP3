import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from web_server import AudioToolboxApp


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class WebServerFilesPayloadTests(unittest.TestCase):
    def test_files_payload_includes_matching_mp4_and_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-03-06 09-00.mp3").write_bytes(b"audio")
            (root / "2026-03-06 09-00.mp4").write_bytes(b"video")

            with working_directory(root):
                app = AudioToolboxApp(Path(__file__).resolve().parent)
                payload = app.get_files_payload()

        self.assertEqual(len(payload["groups"]), 1)
        files = payload["groups"][0]["files"]
        self.assertEqual(
            [file["path"] for file in files],
            ["2026-03-06 09-00.mp3", "2026-03-06 09-00.mp4"],
        )

        mp4_file = next(file for file in files if file["format"] == "mp4")
        self.assertTrue(mp4_file["is_video"])
        self.assertFalse(mp4_file["is_audio"])


if __name__ == "__main__":
    unittest.main()
