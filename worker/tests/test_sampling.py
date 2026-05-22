from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from timeline_for_video_worker.discovery import video_file_from_path
from timeline_for_video_worker.sampling import (
    MAX_SAMPLES_PER_VIDEO,
    build_contact_sheet_filter,
    compute_sample_times,
    sample_video_files,
)


FFPROBE_FIXTURE = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 320,
            "height": 180,
            "duration": "10.000000",
        }
    ],
    "format": {
        "format_name": "mov,mp4",
        "format_long_name": "QuickTime / MOV",
        "duration": "10.000000",
        "size": "5",
        "bit_rate": "40",
    },
}


def write_fake_ffprobe(directory: Path) -> str:
    script = directory / "fake_ffprobe.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffprobe fake 1.0')",
                "else:",
                f"    print(json.dumps({FFPROBE_FIXTURE!r}))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def write_fake_ffmpeg(directory: Path) -> str:
    script = directory / "fake_ffmpeg.py"
    script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffmpeg fake 1.0')",
                "    raise SystemExit(0)",
                "Path(sys.argv[-1]).write_bytes(b'jpeg')",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


class SamplingTests(unittest.TestCase):
    def test_compute_sample_times_are_bounded_and_evenly_spaced(self) -> None:
        self.assertEqual(compute_sample_times(10.0, 4), [2.0, 4.0, 6.0, 8.0])
        self.assertEqual(compute_sample_times(None, 4), [0.0])
        with self.assertRaises(ValueError):
            compute_sample_times(10.0, MAX_SAMPLES_PER_VIDEO + 1)

    def test_build_contact_sheet_filter_uses_fixed_thumbnail_grid(self) -> None:
        filter_complex, output_label = build_contact_sheet_filter(3)

        self.assertEqual(output_label, "[out]")
        self.assertIn("xstack=inputs=3", filter_complex)
        self.assertIn("scale=320:180", filter_complex)

    def test_sample_video_files_writes_outputs_under_output_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            source_before = source.read_bytes()
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            video_file = video_file_from_path(source, str(source.parent))

            result = sample_video_files(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=1,
                samples_per_video=3,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["extractedFrames"], 3)
            record = result["records"][0]
            frame_samples = Path(record["outputs"]["frameSamplesJson"])
            contact_sheet = Path(record["outputs"]["contactSheet"])
            frames_dir = Path(record["outputs"]["framesDir"])

            self.assertTrue(frame_samples.exists())
            self.assertTrue(contact_sheet.exists())
            self.assertTrue((frames_dir / "frame-000001.jpg").exists())
            self.assertTrue(str(frame_samples).startswith(str(output_root)))
            self.assertTrue(str(contact_sheet).startswith(str(output_root)))
            self.assertEqual(source.read_bytes(), source_before)

            saved = json.loads(frame_samples.read_text(encoding="utf-8"))
            self.assertEqual(saved["schemaVersion"], "timeline_for_video.frame_samples.v1")
            self.assertIs(saved["sourceVideoModified"], False)
            self.assertEqual(saved["counts"]["requestedFrames"], 3)

    def test_sample_video_files_returns_structured_error_when_ffmpeg_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe(root)
            video_file = video_file_from_path(source, str(source.parent))

            result = sample_video_files(
                [video_file],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=str(root / "missing-ffmpeg"),
                max_items=1,
                samples_per_video=2,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["counts"]["failedItems"], 1)
            self.assertIn("ffmpeg_unavailable", result["records"][0]["warnings"])

    def test_sample_video_files_reports_item_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            input_root.mkdir()
            first = input_root / "first.mp4"
            second = input_root / "second.mp4"
            first.write_bytes(b"video")
            second.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            events: list[dict[str, object]] = []

            sample_video_files(
                [
                    video_file_from_path(first, str(input_root)),
                    video_file_from_path(second, str(input_root)),
                ],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=2,
                samples_per_video=1,
                progress_callback=events.append,
            )

            self.assertGreaterEqual(len(events), 4)
            self.assertEqual(events[0]["itemsDone"], 0)
            self.assertEqual(events[-1]["itemsDone"], 2)
            self.assertEqual(events[-1]["total"], 2)


if __name__ == "__main__":
    unittest.main()
