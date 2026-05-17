from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_video_worker.api_server import handle_request


FFPROBE_FIXTURE = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 320, "height": 180},
    ],
    "format": {"format_name": "mov,mp4", "duration": "1.000000", "size": "5"},
}

FFPROBE_WITH_AUDIO_FIXTURE = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 320, "height": 180},
        {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 1},
    ],
    "format": {"format_name": "mov,mp4", "duration": "1.000000", "size": "5"},
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


def write_fake_ffprobe_with_audio(directory: Path) -> str:
    script = directory / "fake_ffprobe_with_audio.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffprobe fake 1.0')",
                "else:",
                f"    print(json.dumps({FFPROBE_WITH_AUDIO_FIXTURE!r}))",
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
                "if sys.argv[-1] == '-':",
                "    raise SystemExit(0)",
                "Path(sys.argv[-1]).write_bytes(b'jpeg')",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def write_fake_ffmpeg_failing_silencedetect(directory: Path) -> str:
    script = directory / "fake_ffmpeg_audio_fail.py"
    script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "args = ' '.join(sys.argv)",
                "if '-version' in sys.argv:",
                "    print('ffmpeg fake 1.0')",
                "    raise SystemExit(0)",
                "if 'silencedetect' in args:",
                "    print('silencedetect failed', file=sys.stderr)",
                "    raise SystemExit(2)",
                "if sys.argv[-1] == '-':",
                "    raise SystemExit(0)",
                "Path(sys.argv[-1]).write_bytes(b'jpeg')",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def write_example_settings(
    tmp_path: Path,
    input_roots: list[str] | None = None,
    output_root: str | None = None,
) -> tuple[Path, Path]:
    settings_path = tmp_path / "settings.json"
    example_path = tmp_path / "settings.example.json"
    example_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "inputRoots": input_roots or ["C:\\TimelineData\\input-video\\"],
                "outputRoot": output_root or "C:\\TimelineData\\video",
                "computeMode": "cpu",
            }
        ),
        encoding="utf-8",
    )
    return settings_path, example_path


class VideoApiServerTests(unittest.TestCase):
    def test_api_server_dispatches_items_refresh_without_process_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(source.parent)],
                output_root=str(output_root),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT": str(root / "state"),
            }

            with patch.dict(os.environ, env, clear=False):
                status, init_payload = handle_request("POST", "/settings/init", {})
                self.assertEqual(int(status), 200)
                self.assertTrue(init_payload["created"])

                status, files_payload = handle_request("POST", "/files/list", {})
                self.assertEqual(int(status), 200)
                self.assertEqual(files_payload["counts"]["files"], 1)

                status, refresh_payload = handle_request(
                    "POST",
                    "/items/refresh",
                    {
                        "ffprobeBin": fake_ffprobe,
                        "ffmpegBin": fake_ffmpeg,
                        "maxItems": 1,
                        "samplesPerVideo": 1,
                        "ocrMode": "off",
                        "audioModelMode": "off",
                    },
                )
                self.assertEqual(int(status), 200)
                self.assertEqual(refresh_payload["counts"]["processedItems"], 1)

                status, list_payload = handle_request("POST", "/items/list", {"page": 1, "pageSize": 10})
                self.assertEqual(int(status), 200)
                self.assertEqual(list_payload["counts"]["items"], 1)
                self.assertEqual(list_payload["counts"]["returnedItems"], 1)

                status, download_payload = handle_request("POST", "/items/download", {})
                self.assertEqual(int(status), 200)
                self.assertFalse(download_payload["sourceVideosIncluded"])
                self.assertTrue(Path(download_payload["archivePath"]).exists())

    def test_api_server_maps_failed_refresh_to_error_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe_with_audio(root)
            fake_ffmpeg = write_fake_ffmpeg_failing_silencedetect(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(source.parent)],
                output_root=str(output_root),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT": str(root / "state"),
            }

            with patch.dict(os.environ, env, clear=False):
                status, _ = handle_request("POST", "/settings/init", {})
                self.assertEqual(int(status), 200)
                status, payload = handle_request(
                    "POST",
                    "/items/refresh",
                    {
                        "ffprobeBin": fake_ffprobe,
                        "ffmpegBin": fake_ffmpeg,
                        "maxItems": 1,
                        "samplesPerVideo": 1,
                        "ocrMode": "off",
                        "audioModelMode": "off",
                    },
                )

            self.assertEqual(int(status), 500)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["state"], "completed_with_errors")
            self.assertEqual(payload["failedSteps"], ["audio"])


if __name__ == "__main__":
    unittest.main()
