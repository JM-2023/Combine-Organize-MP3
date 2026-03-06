import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from audio_models import AudioFile, FileState, ProcessingTask, TaskType
from audio_processor import AudioProcessor


class AudioProcessorNamingTests(unittest.TestCase):
    def setUp(self):
        self.processor = AudioProcessor({})

    def test_build_time_range_comment_uses_minute_precision_and_rounds_up(self):
        comment = self.processor._build_time_range_comment("2026-03-06 09-00", 61)
        self.assertEqual(comment, "(20260306 09-00_09-02)")

    def test_build_time_range_comment_from_seconds_filename_still_uses_minute_note_format(self):
        comment = self.processor._build_time_range_comment("2026-03-06_09-00-05", 61.2)
        self.assertEqual(comment, "(20260306 09-00_09-02)")

    def test_build_time_range_comment_uses_full_end_timestamp_when_crossing_day(self):
        comment = self.processor._build_time_range_comment("2026-03-06 23-58", 181)
        self.assertEqual(comment, "(20260306 23-58_20260307 00-02)")

    def test_build_merge_output_stem_compacts_and_deduplicates_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "2026-03-06 09-00(intro).mp3"
            second_path = root / "2026-03-06 09-05(Q&A)(intro).mp3"
            first_path.write_bytes(b"one")
            second_path.write_bytes(b"two")

            first = AudioFile.from_path(first_path, datetime(2026, 3, 6, 9, 0))
            second = AudioFile.from_path(second_path, datetime(2026, 3, 6, 9, 5))

            stem = self.processor._build_merge_output_stem([first, second])

        self.assertEqual(stem, "20260306 09-00(intro)(Q&A)")

    def test_annotate_time_range_appends_after_existing_text_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "2026-03-06 09-00(note).mp3"
            source_path.write_bytes(b"audio")
            audio_file = AudioFile.from_path(source_path, datetime(2026, 3, 6, 9, 0))

            self.processor.tools._ffprobe_path = Path("/mock/ffprobe")
            self.processor.tools.probe_duration_seconds = lambda _path: 61

            task = ProcessingTask(TaskType.ANNOTATE_TIME_RANGE, [audio_file], root)
            result = self.processor._annotate_time_range(task)

            expected_name = "2026-03-06 09-00(note)(20260306 09-00_09-02).mp3"
            self.assertTrue(result.success)
            self.assertEqual(result.processed_count, 1)
            self.assertEqual(result.output_files[0].name, expected_name)
            self.assertTrue((root / expected_name).exists())

    def test_annotate_time_range_appends_again_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "2026-03-06 09-00.mp3"
            source_path.write_bytes(b"audio")
            audio_file = AudioFile.from_path(source_path, datetime(2026, 3, 6, 9, 0))

            self.processor.tools._ffprobe_path = Path("/mock/ffprobe")
            self.processor.tools.probe_duration_seconds = lambda _path: 61

            first_task = ProcessingTask(TaskType.ANNOTATE_TIME_RANGE, [audio_file], root)
            first_result = self.processor._annotate_time_range(first_task)
            self.assertTrue(first_result.success)

            second_task = ProcessingTask(TaskType.ANNOTATE_TIME_RANGE, [audio_file], root)
            second_result = self.processor._annotate_time_range(second_task)

            expected_name = (
                "2026-03-06 09-00"
                "(20260306 09-00_09-02)"
                "(20260306 09-00_09-02).mp3"
            )
            self.assertTrue(second_result.success)
            self.assertEqual(second_result.output_files[0].name, expected_name)
            self.assertTrue((root / expected_name).exists())

    def test_merged_output_detection_accepts_spaced_and_unspaced_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_space = root / "20260306 09-00(intro).mp3"
            with_space = root / "20260306 09-00 (intro).mp3"
            no_space.write_bytes(b"one")
            with_space.write_bytes(b"two")

            no_space_file = self.processor._create_audio_file(no_space)
            with_space_file = self.processor._create_audio_file(with_space)

        self.assertIsNotNone(no_space_file)
        self.assertIsNotNone(with_space_file)
        self.assertEqual(no_space_file.state, FileState.MERGED_OUTPUT)
        self.assertEqual(with_space_file.state, FileState.MERGED_OUTPUT)


if __name__ == "__main__":
    unittest.main()
