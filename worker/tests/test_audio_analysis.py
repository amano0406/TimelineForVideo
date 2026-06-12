from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_video_worker.audio_analysis import (
    analyze_audio_files,
    audio_model_skip_reason,
    ffmpeg_timeout_seconds,
    MAX_AUDIO_MODEL_SPEECH_CANDIDATES,
    parse_silences,
    run_audio_extract,
    speech_candidates_from_silences,
)
from timeline_for_video_worker.discovery import video_file_from_path


FFPROBE_WITH_AUDIO = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 320,
            "height": 180,
            "duration": "4.000000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 1,
            "duration": "4.000000",
        },
    ],
    "format": {
        "format_name": "mov,mp4",
        "duration": "4.000000",
        "size": "5",
        "bit_rate": "40",
    },
}

FFPROBE_WITHOUT_AUDIO = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 320,
            "height": 180,
            "duration": "4.000000",
        },
    ],
    "format": {
        "format_name": "mov,mp4",
        "duration": "4.000000",
        "size": "5",
        "bit_rate": "40",
    },
}


def fake_ffprobe(directory: Path, fixture: dict = FFPROBE_WITH_AUDIO) -> str:
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


def fake_ffmpeg(directory: Path) -> str:
    script = directory / "fake_ffmpeg.py"
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
                "    print('[silencedetect @ x] silence_start: 1.000', file=sys.stderr)",
                "    print('[silencedetect @ x] silence_end: 2.000 | silence_duration: 1.000', file=sys.stderr)",
                "    raise SystemExit(0)",
                "Path(sys.argv[-1]).write_bytes(b'mp3')",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


class AudioAnalysisTests(unittest.TestCase):
    def test_parse_silences_and_speech_candidates(self) -> None:
        silences = parse_silences(
            "\n".join(
                [
                    "[silencedetect @ x] silence_start: 1.000",
                    "[silencedetect @ x] silence_end: 2.500 | silence_duration: 1.500",
                ]
            )
        )

        candidates = speech_candidates_from_silences(4.0, silences)

        self.assertEqual(silences[0]["startSec"], 1.0)
        self.assertEqual(candidates, [
            {"startSec": 0.0, "endSec": 1.0, "durationSec": 1.0},
            {"startSec": 2.5, "endSec": 4.0, "durationSec": 1.5},
        ])

    def test_ffmpeg_timeout_scales_for_long_video(self) -> None:
        self.assertEqual(ffmpeg_timeout_seconds(None), 180)
        self.assertEqual(ffmpeg_timeout_seconds(4.0), 180)
        self.assertGreater(ffmpeg_timeout_seconds(61709.3), 780)

    def test_required_audio_models_do_not_skip_for_many_speech_candidates(self) -> None:
        speech_result = {
            "ok": True,
            "speechCandidates": [
                {"startSec": float(index), "endSec": float(index) + 0.5}
                for index in range(MAX_AUDIO_MODEL_SPEECH_CANDIDATES + 1)
            ],
        }

        self.assertEqual(audio_model_skip_reason(3600.0, speech_result, mode="required"), "")
        self.assertEqual(
            audio_model_skip_reason(3600.0, speech_result, mode="auto"),
            "too_many_speech_candidates",
        )

    def test_audio_extract_timeout_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "audio" / "source_audio.mp3"
            output_path.parent.mkdir()
            output_path.write_bytes(b"partial")

            with patch(
                "timeline_for_video_worker.audio_analysis.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1),
            ):
                result = run_audio_extract("source.mp4", output_path, ffmpeg_bin="ffmpeg", duration_sec=61709.3)

            self.assertFalse(result["ok"])
            self.assertGreater(result["timeoutSec"], 780)
            self.assertFalse(output_path.exists())

    def test_analyze_audio_files_writes_audio_analysis_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            source_before = source.read_bytes()
            output_root = root / "output"

            with patch.dict(
                "os.environ",
                {"TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HF_TOKEN": ""},
                clear=False,
            ):
                result = analyze_audio_files(
                    [video_file_from_path(source, str(source.parent))],
                    str(output_root),
                    ffprobe_bin=fake_ffprobe(root),
                    ffmpeg_bin=fake_ffmpeg(root),
                    max_items=1,
                    settings={"computeMode": "cpu", "huggingfaceToken": ""},
                    audio_model_mode="auto",
                )

            self.assertTrue(result["ok"])
            record = result["records"][0]
            analysis_path = Path(record["outputs"]["audioAnalysisJson"])
            audio_artifact_path = Path(record["audioArtifact"]["path"])
            self.assertTrue(analysis_path.exists())
            self.assertTrue(audio_artifact_path.exists())
            self.assertEqual(source.read_bytes(), source_before)

            payload = json.loads(analysis_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "timeline_for_video.audio_analysis.v1")
            self.assertFalse(payload["audioArtifact"]["includedInDownloadZip"])
            model_input_path = Path(payload["audioModelInput"]["path"])
            self.assertEqual(model_input_path.name, "normalized_audio.wav")
            self.assertFalse(model_input_path.exists())
            self.assertTrue(payload["audioModelInput"]["removedAfterProcessing"])
            self.assertIn("normalized_audio.wav", " ".join(payload["speechActivity"]["command"]))
            self.assertEqual(payload["speechActivity"]["counts"]["speechCandidates"], 2)
            self.assertEqual(payload["audioModels"]["mode"], "auto")
            self.assertEqual(payload["diarization"]["status"], "not_configured")
            self.assertEqual(payload["transcription"]["status"], "not_configured")
            self.assertTrue(payload["ok"])

    def test_audio_model_mode_off_skips_normalized_audio_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")

            result = analyze_audio_files(
                [video_file_from_path(source, str(source.parent))],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe(root),
                ffmpeg_bin=fake_ffmpeg(root),
                max_items=1,
                settings={"computeMode": "cpu", "huggingfaceToken": ""},
                audio_model_mode="off",
            )

            self.assertTrue(result["ok"])
            payload = json.loads(Path(result["records"][0]["outputs"]["audioAnalysisJson"]).read_text(encoding="utf-8"))
            self.assertTrue(payload["audioModelInput"]["skipped"])
            self.assertTrue(payload["audioModelInput"]["removedAfterProcessing"])
            self.assertNotIn("normalized_audio.wav", " ".join(payload["speechActivity"]["command"]))
            self.assertIn("audio.mp3", " ".join(payload["speechActivity"]["command"]))
            self.assertEqual(payload["audioModels"]["mode"], "off")
            self.assertEqual(payload["transcription"]["status"], "disabled")

    def test_audio_model_mode_off_skips_very_long_audio_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "long.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            long_fixture = {
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 320,
                        "height": 180,
                        "duration": "14400.000000",
                    },
                    {
                        "index": 1,
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 1,
                        "duration": "14400.000000",
                    },
                ],
                "format": {
                    "format_name": "mov,mp4",
                    "duration": "14400.000000",
                    "size": "5000000000",
                    "bit_rate": "2777777",
                },
            }

            result = analyze_audio_files(
                [video_file_from_path(source, str(source.parent))],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe(root, long_fixture),
                ffmpeg_bin=fake_ffmpeg(root),
                max_items=1,
                settings={"computeMode": "cpu", "huggingfaceToken": ""},
                audio_model_mode="off",
            )

            self.assertTrue(result["ok"])
            payload = json.loads(Path(result["records"][0]["outputs"]["audioAnalysisJson"]).read_text(encoding="utf-8"))
            self.assertTrue(payload["audioArtifact"]["skipped"])
            self.assertEqual(payload["audioArtifact"]["skipReason"], "duration_too_long")
            self.assertTrue(payload["audioModelInput"]["skipped"])
            self.assertTrue(payload["speechActivity"]["skipped"])
            self.assertEqual(payload["speechActivity"]["counts"]["speechCandidates"], 0)
            self.assertIn("audio_analysis_skipped_duration_too_long", payload["warnings"])
            self.assertEqual(payload["transcription"]["status"], "disabled")

    def test_required_audio_models_warn_when_duration_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mkv"
            source.parent.mkdir()
            source.write_bytes(b"video")
            unknown_duration = {
                "streams": FFPROBE_WITH_AUDIO["streams"],
                "format": {"format_name": "matroska,webm", "size": "5000000000"},
            }

            result = analyze_audio_files(
                [video_file_from_path(source, str(source.parent))],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe(root, unknown_duration),
                ffmpeg_bin=fake_ffmpeg(root),
                max_items=1,
                settings={"computeMode": "cpu", "huggingfaceToken": ""},
                audio_model_mode="required",
            )

            self.assertTrue(result["ok"])
            record = result["records"][0]
            self.assertIn("audio_models_skipped_duration_unknown", record["warnings"])
            self.assertEqual(record["audioModels"]["mode"], "off")
            self.assertTrue(record["audioModels"]["ok"])
            self.assertIn("duration_unknown_required_audio_models", record["audioModels"]["warnings"])

    def test_audio_analysis_reports_item_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            events: list[dict[str, object]] = []

            analyze_audio_files(
                [video_file_from_path(source, str(source.parent))],
                str(root / "output"),
                ffprobe_bin=fake_ffprobe(root),
                ffmpeg_bin=fake_ffmpeg(root),
                max_items=1,
                settings={"computeMode": "cpu", "huggingfaceToken": ""},
                audio_model_mode="off",
                progress_callback=events.append,
            )

            stages = [event.get("itemStage") for event in events]
            self.assertIn("prepare", stages)
            self.assertIn("extract_audio", stages)
            self.assertIn("completed", stages)
            self.assertEqual(events[-1]["itemsDone"], 1)

    def test_required_audio_models_fail_when_video_has_no_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")

            with patch.dict(
                "os.environ",
                {"TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HF_TOKEN": ""},
                clear=False,
            ):
                result = analyze_audio_files(
                    [video_file_from_path(source, str(source.parent))],
                    str(root / "output"),
                    ffprobe_bin=fake_ffprobe(root, FFPROBE_WITHOUT_AUDIO),
                    ffmpeg_bin=fake_ffmpeg(root),
                    max_items=1,
                    settings={"computeMode": "cpu", "huggingfaceToken": ""},
                    audio_model_mode="required",
                )

            self.assertFalse(result["ok"])
            record = result["records"][0]
            self.assertIn("no_audio_streams", record["warnings"])
            self.assertEqual(record["diarization"]["status"], "audio_missing")
            self.assertFalse(record["sourceVideoModified"])


if __name__ == "__main__":
    unittest.main()
