from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from timeline_for_video_worker.activity_map import (
    analyze_activity_files,
    audio_activity_segments,
    inactive_segments_from_active,
    mean_abs_delta,
    merge_segments,
)
from timeline_for_video_worker.discovery import video_file_from_path


FFPROBE_FIXTURE = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 320,
            "height": 180,
            "duration": "601.000000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 1,
            "duration": "601.000000",
        },
    ],
    "format": {
        "format_name": "mov,mp4",
        "duration": "601.000000",
        "size": "5",
        "bit_rate": "40",
    },
}


def fake_ffprobe(directory: Path, fixture: dict = FFPROBE_FIXTURE) -> str:
    script = directory / "fake_ffprobe.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffprobe fake 1.0')",
                "else:",
                f"    print(json.dumps({fixture!r}))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def fake_ffmpeg_gray(directory: Path) -> str:
    script = directory / "fake_ffmpeg_gray.py"
    script.write_text(
        "\n".join(
            [
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffmpeg fake 1.0')",
                "    raise SystemExit(0)",
                "time_sec = 0.0",
                "if '-ss' in sys.argv:",
                "    time_sec = float(sys.argv[sys.argv.index('-ss') + 1])",
                "value = 0 if time_sec < 300 else 255",
                "sys.stdout.buffer.write(bytes([value]) * (160 * 90))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


class ActivityMapTests(unittest.TestCase):
    def test_merge_segments_with_padding_style_gaps(self) -> None:
        merged = merge_segments(
            [
                {"startSec": 0.0, "endSec": 1.0},
                {"startSec": 2.0, "endSec": 3.0},
                {"startSec": 10.0, "endSec": 11.0},
            ],
            max_gap_sec=2.0,
            duration_sec=20.0,
        )

        self.assertEqual(merged[0], {"startSec": 0.0, "endSec": 3.0, "durationSec": 3.0})
        self.assertEqual(merged[1], {"startSec": 10.0, "endSec": 11.0, "durationSec": 1.0})

    def test_audio_activity_segments_uses_speech_candidates(self) -> None:
        audio = {
            "speechActivity": {
                "speechCandidates": [
                    {"startSec": 10.0, "endSec": 12.0},
                    {"startSec": 13.0, "endSec": 14.0},
                ]
            }
        }

        result = audio_activity_segments(audio, 30.0)

        self.assertTrue(result["available"])
        self.assertEqual(result["speechCandidates"], 2)
        self.assertEqual(result["activeSegments"], [{"startSec": 9.0, "endSec": 15.0, "durationSec": 6.0}])

    def test_inactive_segments_complement_active_segments(self) -> None:
        inactive = inactive_segments_from_active(
            [{"startSec": 2.0, "endSec": 4.0, "durationSec": 2.0}],
            6.0,
        )

        self.assertEqual(
            inactive,
            [
                {"startSec": 0.0, "endSec": 2.0, "durationSec": 2.0},
                {"startSec": 4.0, "endSec": 6.0, "durationSec": 2.0},
            ],
        )

    def test_mean_abs_delta_is_normalized(self) -> None:
        self.assertEqual(mean_abs_delta(bytes([0, 0]), bytes([255, 255])), 1.0)

    def test_analyze_activity_files_writes_activity_map_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            source_before = source.read_bytes()
            output_root = root / "output"

            result = analyze_activity_files(
                [video_file_from_path(source, str(source.parent))],
                str(output_root),
                ffprobe_bin=fake_ffprobe(root),
                ffmpeg_bin=fake_ffmpeg_gray(root),
                max_items=1,
            )

            self.assertTrue(result["ok"])
            record = result["records"][0]
            activity_map_path = Path(record["outputs"]["activityMapJson"])
            self.assertTrue(activity_map_path.exists())
            self.assertEqual(source.read_bytes(), source_before)

            payload = json.loads(activity_map_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "timeline_for_video.activity_map.v1")
            self.assertFalse(payload["sourceVideoModified"])
            self.assertGreaterEqual(payload["activity"]["counts"]["visualSentinels"], 3)
            self.assertGreaterEqual(payload["activity"]["counts"]["visualActiveSegments"], 1)
            self.assertGreater(payload["activity"]["inactiveSec"], 0)

    def test_activity_map_warns_but_passes_when_duration_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mkv"
            source.parent.mkdir()
            source.write_bytes(b"video")
            unknown_duration = {
                "streams": FFPROBE_FIXTURE["streams"],
                "format": {"format_name": "matroska,webm", "size": "5000000000"},
            }

            result = analyze_activity_files(
                [video_file_from_path(source, str(source.parent))],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe(root, unknown_duration),
                ffmpeg_bin=fake_ffmpeg_gray(root),
                max_items=1,
            )

            self.assertTrue(result["ok"])
            record = result["records"][0]
            self.assertTrue(record["ok"])
            self.assertIn("duration_missing", record["warnings"])
            self.assertEqual(record["activity"]["counts"]["activeSegments"], 0)
            self.assertIn("duration was not available", record["activity"]["notes"][0])


if __name__ == "__main__":
    unittest.main()
