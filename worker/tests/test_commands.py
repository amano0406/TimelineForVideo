from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_video_worker.commands import main


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


def run_json(args: list[str], env: dict[str, str] | None = None) -> tuple[int, dict]:
    output = io.StringIO()
    run_env = dict(env or {})
    settings_path_text = run_env.get("TIMELINE_FOR_VIDEO_SETTINGS_PATH")
    if settings_path_text and "TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT" not in run_env:
        run_env["TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT"] = str(Path(settings_path_text).parent / "state")
    with patch.dict(os.environ, run_env, clear=False):
        with contextlib.redirect_stdout(output):
            exit_code = main(args)
    return exit_code, json.loads(output.getvalue())


class CommandTests(unittest.TestCase):
    def test_health_json(self) -> None:
        exit_code, payload = run_json(["health", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["product"], "TimelineForVideo")

    def test_settings_init_status_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path, example_path = write_example_settings(Path(temp_dir))
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, init_payload = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertIs(init_payload["created"], True)
            self.assertTrue(settings_path.exists())

            exit_code, status_payload = run_json(["settings", "status", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertIs(status_payload["exists"], True)

            exit_code, save_payload = run_json(
                [
                    "settings",
                    "save",
                    "--input-root",
                    "C:\\Videos\\A",
                    "--input-root",
                    "D:\\Videos\\B",
                    "--output-root",
                    "E:\\TimelineVideo",
                    "--token",
                    "hf_test_token",
                    "--compute-mode",
                    "cpu",
                    "--json",
                ],
                env,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                save_payload["settings"]["inputRoots"],
                ["C:\\Videos\\A", "D:\\Videos\\B"],
            )
            self.assertEqual(save_payload["settings"]["outputRoot"], "E:\\TimelineVideo")
            self.assertEqual(save_payload["settings"]["computeMode"], "cpu")
            self.assertEqual(
                save_payload["settings"]["huggingFaceToken"],
                {"configured": True, "source": "settings"},
            )

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["huggingFaceToken"], "hf_test_token")
            self.assertEqual(
                set(saved),
                {"schemaVersion", "inputRoots", "outputRoot", "huggingFaceToken", "computeMode"},
            )

    def test_files_list_json_uses_settings_input_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(root)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(["files", "list", "--json"], env)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["files"], 1)
            self.assertEqual(payload["files"][0]["resolvedPath"], str(source))

    def test_files_list_json_paginates_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ["a.mp4", "b.mp4", "c.mp4"]:
                (root / name).write_bytes(b"video")
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(root)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                ["files", "list", "--json", "--page", "2", "--page-size", "1"],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["files"], 3)
            self.assertEqual(payload["counts"]["returnedFiles"], 1)
            self.assertEqual(payload["pagination"]["page"], 2)
            self.assertEqual(payload["pagination"]["pageSize"], 1)
            self.assertEqual(payload["pagination"]["totalFiles"], 3)
            self.assertEqual(payload["pagination"]["returnedFiles"], 1)
            self.assertTrue(payload["pagination"]["hasPrevious"])
            self.assertTrue(payload["pagination"]["hasNext"])
            self.assertTrue(payload["files"][0]["sourcePath"].endswith("b.mp4"))

    def test_doctor_json_reports_ok_for_existing_input_and_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mov"
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe_with_audio(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(root)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "",
                "HUGGING_FACE_HUB_TOKEN": "",
                "HF_TOKEN": "",
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "doctor",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--ocr-mode",
                    "off",
                ],
                env,
            )

            self.assertEqual(exit_code, 1)
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["discovery"]["counts"]["files"], 1)
            self.assertTrue(payload["ffprobeVersion"]["ok"])
            self.assertIn("audioModels", payload)

    def test_doctor_required_audio_models_fails_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mov"
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe_with_audio(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(root)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "",
                "HUGGING_FACE_HUB_TOKEN": "",
                "HF_TOKEN": "",
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "doctor",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--ocr-mode",
                    "off",
                ],
                env,
            )

            self.assertEqual(exit_code, 1)
            check = next(check for check in payload["checks"] if check["name"] == "runtime.audio_models")
            self.assertFalse(check["ok"])
            self.assertIn("token", check["message"].casefold())

    def test_models_list_json_reports_local_and_contract_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(root)
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }
            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "models",
                    "list",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--ocr-mode",
                    "off",
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["pipeline"]["name"], "TimelineForVideo")
            self.assertEqual(len(payload["pipeline"]["generation_signature"]), 64)
            model_rows = {row["role"]: row for row in payload["models"]}
            self.assertEqual(model_rows["speaker_diarization"]["model_id"], "pyannote/speaker-diarization-community-1")
            self.assertEqual(model_rows["speech_transcription"]["model_id"], "Systran/faster-whisper-large-v3")
            self.assertEqual(model_rows["frame_ocr"]["model_id"], "tesseract:jpn+eng")
            self.assertEqual(model_rows["speech_candidate_detection"]["model_id"], "ffmpeg-silencedetect-noise-35db")
            self.assertEqual(payload["counts"]["requiredComponents"], 8)
            self.assertEqual(payload["counts"]["audioModelComponents"], 2)
            components = {component["id"]: component for component in payload["components"]}
            self.assertTrue(components["frame_ocr"]["execution"]["implementedInVideoWorker"])
            self.assertTrue(components["frame_visual_features"]["execution"]["implementedInVideoWorker"])
            self.assertTrue(components["speaker_diarization"]["execution"]["implementedInVideoWorker"])

    def test_doctor_json_fails_for_missing_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing"
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(missing)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "doctor",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--ocr-mode",
                    "off",
                ],
                env,
            )

            self.assertEqual(exit_code, 1)
            self.assertIs(payload["ok"], False)
            input_root_check = next(check for check in payload["checks"] if check["name"] == "input_root")
            self.assertIn("missing", input_root_check["message"])

    def test_probe_list_json_uses_discovered_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(root)],
                output_root=str(root / "out"),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                ["probe", "list", "--json", "--ffprobe-bin", fake_ffprobe],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["probedFiles"], 1)
            self.assertTrue(payload["records"][0]["itemId"].startswith("video-"))
            self.assertEqual(payload["records"][0]["ffprobe"]["summary"]["counts"]["videoStreams"], 1)

    def test_sample_frames_json_writes_frame_samples_under_output_root(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "sample",
                    "frames",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "2",
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["extractedFrames"], 2)
            frame_samples = Path(payload["records"][0]["outputs"]["frameSamplesJson"])
            self.assertTrue(frame_samples.exists())
            self.assertTrue(str(frame_samples).startswith(str(output_root)))

    def test_sample_frames_json_returns_structured_error_for_unbounded_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            output_root = root / "output"
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(source.parent)],
                output_root=str(output_root),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "sample",
                    "frames",
                    "--json",
                    "--samples-per-video",
                    "13",
                ],
                env,
            )

            self.assertEqual(exit_code, 2)
            self.assertFalse(payload["ok"])
            self.assertIn("samples_per_video", payload["error"])

    def test_activity_map_json_writes_activity_map_under_output_root(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "activity",
                    "map",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["processedItems"], 1)
            activity_map = Path(payload["records"][0]["outputs"]["activityMapJson"])
            self.assertTrue(activity_map.exists())
            self.assertTrue(str(activity_map).startswith(str(output_root)))

    def test_items_refresh_and_list_json_use_output_root_records(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, refresh_payload = run_json(
                [
                    "items",
                    "refresh",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(refresh_payload["counts"]["processedItems"], 1)
            self.assertEqual(refresh_payload["steps"]["refresh"]["counts"]["refreshedItems"], 1)

            exit_code, list_payload = run_json(["items", "list", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertEqual(list_payload["counts"]["items"], 1)
            self.assertTrue(list_payload["items"][0]["itemId"].startswith("video-"))

    def test_items_list_json_paginates_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_root = root / "output"
            items_root = output_root / "items"
            settings_path, example_path = write_example_settings(root, output_root=str(output_root))
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
            }
            for item_id, source_path in [
                ("video-a", "C:\\Videos\\a.mp4"),
                ("video-b", "C:\\Videos\\b.mp4"),
            ]:
                item_root = items_root / item_id
                item_root.mkdir(parents=True)
                (item_root / "video_record.json").write_text(
                    json.dumps(
                        {
                            "record_id": item_id,
                            "asset": {"source_path": source_path},
                            "video": {"format": {"durationSec": 1.0}},
                            "audio": {"analysis": {}},
                            "processing": {"warnings": []},
                            "frames": [],
                            "text": {},
                            "review": {},
                        }
                    ),
                    encoding="utf-8",
                )

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                ["items", "list", "--json", "--page", "1", "--page-size", "1"],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["items"], 2)
            self.assertEqual(payload["counts"]["returnedItems"], 1)
            self.assertEqual(payload["pagination"]["totalItems"], 2)
            self.assertEqual(payload["pagination"]["returnedItems"], 1)
            self.assertEqual(payload["pagination"]["totalPages"], 2)
            self.assertFalse(payload["pagination"]["hasPrevious"])
            self.assertTrue(payload["pagination"]["hasNext"])
            self.assertEqual(len(payload["items"]), 1)

    def test_runs_list_json_paginates_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path, example_path = write_example_settings(root)
            state_root = root / "state"
            runs_root = state_root / "runs"
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT": str(state_root),
            }
            for run_id in ["run-001", "run-002", "run-003"]:
                run_root = runs_root / run_id
                run_root.mkdir(parents=True)
                (run_root / "result.json").write_text(
                    json.dumps(
                        {
                            "state": "completed",
                            "ok": True,
                            "generatedAt": f"2026-05-08T00:00:0{run_id[-1]}Z",
                            "counts": {"processedItems": 1, "failedItems": 0},
                        }
                    ),
                    encoding="utf-8",
                )

            exit_code, payload = run_json(
                ["runs", "list", "--json", "--page", "2", "--page-size", "1"],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["counts"]["runs"], 3)
            self.assertEqual(payload["counts"]["returnedRuns"], 1)
            self.assertEqual(payload["pagination"]["totalRuns"], 3)
            self.assertEqual(payload["pagination"]["returnedRuns"], 1)
            self.assertEqual(payload["runs"][0]["runId"], "run-002")

    def test_process_all_json_runs_sampling_ocr_audio_and_refresh(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, payload = run_json(
                [
                    "process",
                    "all",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "mock",
                    "--audio-model-mode",
                    "auto",
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["steps"]["sample"]["counts"]["sampledItems"], 1)
            self.assertEqual(payload["steps"]["frameOcr"]["counts"]["processedItems"], 1)
            self.assertEqual(payload["steps"]["audio"]["counts"]["processedItems"], 1)
            self.assertEqual(payload["steps"]["refresh"]["counts"]["refreshedItems"], 1)

    def test_serve_once_processes_and_runs_are_listed(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, event = run_json(
                [
                    "serve",
                    "--once",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(event["ok"])
            self.assertEqual(event["event"], "refresh_completed")
            self.assertEqual(event["counts"]["processedItems"], 1)

            exit_code, runs_payload = run_json(["runs", "list", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertEqual(runs_payload["counts"]["runs"], 1)
            self.assertEqual(runs_payload["runs"][0]["state"], "completed")

            exit_code, second_event = run_json(
                [
                    "serve",
                    "--once",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(second_event["event"], "refresh_skipped_no_changes")
            self.assertEqual(second_event["counts"]["processedItems"], 0)

    def test_serve_uses_worker_environment_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "input" / "a.mp4"
            source_b = root / "input" / "b.mp4"
            source_a.parent.mkdir()
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            settings_path, example_path = write_example_settings(
                root,
                input_roots=[str(source_a.parent)],
                output_root=str(output_root),
            )
            env = {
                "TIMELINE_FOR_VIDEO_SETTINGS_PATH": str(settings_path),
                "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH": str(example_path),
                "TIMELINE_FOR_VIDEO_WORKER_MAX_ITEMS": "1",
                "TIMELINE_FOR_VIDEO_WORKER_SAMPLES_PER_VIDEO": "1",
                "TIMELINE_FOR_VIDEO_WORKER_OCR_MODE": "off",
                "TIMELINE_FOR_VIDEO_WORKER_AUDIO_MODEL_MODE": "off",
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            exit_code, event = run_json(
                [
                    "serve",
                    "--once",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                ],
                env,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(event["counts"]["sourceFiles"], 2)
            self.assertEqual(event["counts"]["processedItems"], 1)
            self.assertEqual(event["counts"]["skippedItems"], 1)

    def test_failed_pipeline_step_is_not_cataloged_as_complete(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)

            first_exit, first_event = run_json(
                [
                    "serve",
                    "--once",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )
            self.assertEqual(first_exit, 1)
            self.assertFalse(first_event["ok"])
            self.assertEqual(first_event["state"], "completed_with_errors")
            self.assertEqual(first_event["failedSteps"], ["audio"])

            second_exit, second_event = run_json(
                [
                    "serve",
                    "--once",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )
            self.assertEqual(second_exit, 1)
            self.assertEqual(second_event["event"], "refresh_completed")
            self.assertEqual(second_event["counts"]["processedItems"], 1)

    def test_items_download_and_remove_dry_run_json(self) -> None:
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
            }

            exit_code, _ = run_json(["settings", "init", "--json"], env)
            self.assertEqual(exit_code, 0)
            exit_code, _ = run_json(
                [
                    "items",
                    "refresh",
                    "--json",
                    "--ffprobe-bin",
                    fake_ffprobe,
                    "--ffmpeg-bin",
                    fake_ffmpeg,
                    "--max-items",
                    "1",
                    "--samples-per-video",
                    "1",
                    "--ocr-mode",
                    "off",
                    "--audio-model-mode",
                    "off",
                ],
                env,
            )
            self.assertEqual(exit_code, 0)

            exit_code, download_payload = run_json(["items", "download", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertFalse(download_payload["sourceVideosIncluded"])
            self.assertTrue(Path(download_payload["archivePath"]).exists())

            exit_code, remove_payload = run_json(["items", "remove", "--dry-run", "--json"], env)
            self.assertEqual(exit_code, 0)
            self.assertTrue(remove_payload["dryRun"])
            self.assertGreater(remove_payload["counts"]["targetFiles"], 0)


if __name__ == "__main__":
    unittest.main()
