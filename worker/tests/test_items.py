from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

from timeline_for_video_worker.discovery import display_path, video_file_from_path
from timeline_for_video_worker.items import download_items, list_items, refresh_items, remove_items
from timeline_for_video_worker.sampling import sample_video_files


FFPROBE_FIXTURE = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 640,
            "height": 360,
            "duration": "8.000000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
            "duration": "8.000000",
        },
    ],
    "format": {
        "format_name": "mov,mp4",
        "format_long_name": "QuickTime / MOV",
        "duration": "8.000000",
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


class ItemsTests(unittest.TestCase):
    def test_refresh_items_writes_item_contract_files_and_preserves_source(self) -> None:
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

            sample_result = sample_video_files(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=1,
                samples_per_video=2,
            )
            self.assertTrue(sample_result["ok"])
            sampled_item_root = Path(sample_result["records"][0]["outputs"]["itemRoot"])
            (sampled_item_root / "raw_outputs" / "frame_ocr.json").write_text(
                json.dumps(
                    {
                        "outputs": {"frameOcrJson": str(sampled_item_root / "raw_outputs" / "frame_ocr.json")},
                        "ocrMode": "mock",
                        "ocrRuntime": {"model": None},
                        "counts": {"framesWithText": 1, "textBlocks": 1},
                        "frames": [
                            {
                                "frameId": "frame-000001",
                                "timeSec": 2.667,
                                "source_frame_path": str(sampled_item_root / "artifacts" / "frames" / "frame-000001.jpg"),
                                "debug_overlay_path": str(sampled_item_root / "artifacts" / "ocr" / "frame-000001-ocr.jpg"),
                                "ocr": {
                                    "has_text": True,
                                    "full_text": "frame text",
                                    "blocks": [
                                        {
                                            "block_id": "ocr_0001",
                                            "text": "frame text",
                                            "bbox_norm": [0.1, 0.1, 0.8, 0.2],
                                            "confidence": {"score": None, "level": "unknown"},
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (sampled_item_root / "raw_outputs" / "audio_analysis.json").write_text(
                json.dumps(
                    {
                        "outputs": {
                            "audioAnalysisJson": str(sampled_item_root / "raw_outputs" / "audio_analysis.json")
                        },
                        "audioArtifact": {
                            "ok": True,
                            "path": str(sampled_item_root / "artifacts" / "audio" / "source_audio.mp3"),
                            "includedInDownloadZip": False,
                        },
                        "speechActivity": {
                            "counts": {"speechCandidates": 1},
                            "speechCandidates": [
                                {"startSec": 0.0, "endSec": 4.0, "durationSec": 4.0}
                            ],
                        },
                        "diarization": {"status": "not_run"},
                        "transcription": {"status": "ok"},
                        "text": {
                            "mode": "whisper_transcript",
                            "readableText": "こんにちは",
                            "segments": [
                                {
                                    "start_sec": 0.0,
                                    "end_sec": 4.0,
                                    "speaker": "SPEAKER_00",
                                    "speakerAssignment": {
                                        "method": "max_overlap",
                                        "speaker": "SPEAKER_00",
                                        "overlapSec": 4.0,
                                    },
                                    "text": "こんにちは",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (sampled_item_root / "raw_outputs" / "frame_diff_vlm.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "mode": "required",
                        "model": {"modelId": "Qwen/Qwen3.5-4B"},
                        "counts": {
                            "candidateTransitions": 1,
                            "analyzedTransitions": 1,
                            "skippedTransitions": 0,
                            "failedTransitions": 0,
                            "changedTransitions": 1,
                            "unchangedTransitions": 0,
                        },
                        "transitions": [
                            {
                                "index": 1,
                                "fromFrameId": "frame-000001",
                                "toFrameId": "frame-000002",
                                "startSec": 2.667,
                                "endSec": 5.333,
                                "ok": True,
                                "status": "completed",
                                "changed": True,
                                "changeLevel": "meaningful",
                                "summary": "入力欄の文字が追加された。",
                                "differences": ["入力欄の文字が増えた"],
                                "confidence": 0.9,
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            activity_map_path = sampled_item_root / "raw_outputs" / "activity_map.json"
            activity_map_path.write_text(
                json.dumps(
                    {
                        "outputs": {"activityMapJson": str(activity_map_path)},
                        "activity": {
                            "strategy": "audio_speech_activity_plus_visual_sentinel",
                            "activeSegments": [{"startSec": 0.0, "endSec": 4.0}],
                            "inactiveSegments": [{"startSec": 4.0, "endSec": 8.0}],
                            "activeSec": 4.0,
                            "inactiveSec": 4.0,
                            "activeRatio": 0.5,
                            "estimatedReductionRatio": 2.0,
                            "counts": {
                                "activeSegments": 1,
                                "inactiveSegments": 1,
                                "visualSentinels": 2,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            refresh_result = refresh_items(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                max_items=1,
            )

            self.assertTrue(refresh_result["ok"])
            self.assertEqual(refresh_result["counts"]["refreshedItems"], 1)
            record = refresh_result["records"][0]
            item_root = Path(record["itemRoot"])
            video_record_path = item_root / "video_record.json"
            timeline_path = item_root / "timeline.json"
            convert_info_path = item_root / "convert_info.json"
            ffprobe_path = item_root / "raw_outputs" / "ffprobe.json"

            self.assertTrue(video_record_path.exists())
            self.assertTrue(timeline_path.exists())
            self.assertTrue(convert_info_path.exists())
            self.assertTrue(ffprobe_path.exists())
            self.assertEqual(source.read_bytes(), source_before)

            video_record = json.loads(video_record_path.read_text(encoding="utf-8"))
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            convert_info = json.loads(convert_info_path.read_text(encoding="utf-8"))

            self.assertEqual(video_record["schema_version"], "timeline_for_video.video_record.v1")
            self.assertIs(video_record["asset"]["source_video_modified"], False)
            self.assertEqual(len(video_record["frames"]), 2)
            self.assertEqual(video_record["visual"]["frame_transition_gate"]["transitions"], 1)
            self.assertEqual(video_record["visual"]["frame_transition_gate"]["failedTransitions"], 1)
            self.assertEqual(video_record["visual"]["frame_diff_vlm"]["changedTransitions"], 1)
            self.assertTrue(video_record["text"]["ocr"])
            self.assertEqual(video_record["text"]["blocks"][0]["text"], "frame text")
            self.assertIn("visual", timeline["lanes"])
            self.assertIn("audio", timeline["lanes"])
            self.assertIn("text", timeline["lanes"])
            self.assertIn("frame_sample", {event["eventType"] for event in timeline["lanes"]["visual"]})
            self.assertIn("frame_transition_gate", {event["eventType"] for event in timeline["lanes"]["visual"]})
            self.assertIn("frame_diff_vlm", {event["eventType"] for event in timeline["lanes"]["visual"]})
            self.assertIn("frame_ocr_text", {event["eventType"] for event in timeline["lanes"]["text"]})
            self.assertIn("audio_transcript_segment", {event["eventType"] for event in timeline["lanes"]["text"]})
            self.assertIn("audio_speech_candidate", {event["eventType"] for event in timeline["lanes"]["audio"]})
            self.assertIs(convert_info["source_video_modified"], False)
            self.assertEqual(convert_info["ffmpegVersion"]["versionLine"], "ffmpeg fake 1.0")
            self.assertEqual(convert_info["counts"]["frames"], 2)
            self.assertEqual(convert_info["counts"]["frameTransitions"], 1)
            self.assertEqual(convert_info["counts"]["frameTransitionsForVlm"], 1)
            self.assertEqual(convert_info["counts"]["frameDiffVlmCandidates"], 1)
            self.assertEqual(convert_info["counts"]["frameDiffVlmAnalyzed"], 1)
            self.assertEqual(convert_info["counts"]["frameDiffVlmChanged"], 1)
            self.assertEqual(convert_info["counts"]["ocrTextBlocks"], 1)
            self.assertEqual(convert_info["counts"]["audioSpeechCandidates"], 1)
            required_outputs = {"video_record", "timeline", "convert_info", "ffprobe_raw"}
            output_files = {entry["kind"]: entry for entry in convert_info["outputFiles"]}
            self.assertTrue(all(output_files[kind]["exists"] for kind in required_outputs))

            listed = list_items(str(output_root))
            listed_item = listed["items"][0]
            self.assertEqual(listed_item["text"]["textBlockCount"], 1)
            self.assertEqual(listed_item["visual"]["frameTransitionGate"]["transitions"], 1)
            self.assertEqual(listed_item["visual"]["frameDiffVlm"]["changedTransitions"], 1)
            self.assertEqual(listed_item["audioAnalysis"]["speechCandidates"], 1)
            self.assertFalse(listed_item["audioAnalysis"]["audioArtifactIncludedInDownloadZip"])
            self.assertEqual(listed_item["activity"]["activityMapJson"], str(activity_map_path))
            self.assertEqual(listed_item["activity"]["visualSentinels"], 2)

    def test_list_items_reads_video_records_from_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            video_file = video_file_from_path(source, str(root))

            refresh_items([video_file], str(output_root), ffprobe_bin=fake_ffprobe, max_items=1)
            result = list_items(str(output_root))

            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["items"], 1)
            self.assertTrue(result["items"][0]["itemId"].startswith("video-"))
            self.assertEqual(result["items"][0]["sourcePath"], display_path(source))

    def test_download_items_exports_generated_files_without_source_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            video_file = video_file_from_path(source, str(source.parent))

            sample_video_files(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=1,
                samples_per_video=2,
            )
            refresh_items([video_file], str(output_root), ffprobe_bin=fake_ffprobe, max_items=1)
            item_root = Path(sample_video_files(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=1,
                samples_per_video=1,
            )["records"][0]["outputs"]["itemRoot"])
            audio_dir = item_root / "artifacts" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            (audio_dir / "source_audio.mp3").write_bytes(b"mp3")
            (item_root / "raw_outputs" / "audio_analysis.json").write_text(
                json.dumps({"audioArtifact": {"path": str(audio_dir / "source_audio.mp3")}}),
                encoding="utf-8",
            )

            result = download_items(str(output_root))

            archive_path = Path(result["archivePath"])
            latest_path = Path(result["latestArchivePath"])
            manifest_path = Path(result["latestManifestPath"])
            self.assertTrue(archive_path.exists())
            self.assertTrue(latest_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertFalse(result["sourceVideosIncluded"])
            self.assertFalse(result["imageArtifactsIncluded"])

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()

            self.assertIn("manifest.json", names)
            self.assertTrue(any(name.endswith("video_record.json") for name in names))
            self.assertTrue(any(name.endswith("timeline.json") for name in names))
            self.assertFalse(any(name.casefold().endswith(".jpg") for name in names))
            self.assertFalse(any(name.casefold().endswith(".mp4") for name in names))
            self.assertFalse(any(name.casefold().endswith(".mp3") for name in names))

    def test_download_items_can_select_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            input_root.mkdir()
            first = input_root / "first.mp4"
            second = input_root / "second.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            first_file = video_file_from_path(first, str(input_root))
            second_file = video_file_from_path(second, str(input_root))

            refresh_result = refresh_items([first_file, second_file], str(output_root), ffprobe_bin=fake_ffprobe)
            first_item_id = refresh_result["records"][0]["itemId"]
            second_item_id = refresh_result["records"][1]["itemId"]

            result = download_items(str(output_root), item_ids=[first_item_id])

            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["items"], 1)
            with zipfile.ZipFile(result["archivePath"]) as archive:
                names = archive.namelist()
            self.assertTrue(any(name.startswith(f"items/{first_item_id}/") for name in names))
            self.assertFalse(any(name.startswith(f"items/{second_item_id}/") for name in names))

    def test_remove_items_deletes_generated_artifacts_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            output_root = root / "output"
            output_root.mkdir()
            user_video = output_root / "keep-source.mp4"
            user_video.write_bytes(b"user video")
            fake_ffprobe = write_fake_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg(root)
            video_file = video_file_from_path(source, str(source.parent))

            sample_video_files(
                [video_file],
                str(output_root),
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                max_items=1,
                samples_per_video=1,
            )
            refresh_result = refresh_items([video_file], str(output_root), ffprobe_bin=fake_ffprobe, max_items=1)
            download_items(str(output_root))
            item_root = Path(refresh_result["records"][0]["itemRoot"])
            processing_dir = item_root / "artifacts" / "audio" / ".processing"
            processing_dir.mkdir(parents=True)
            (processing_dir / "normalized_audio.wav").write_bytes(b"temporary audio")

            dry_run = remove_items(str(output_root), dry_run=True)
            self.assertGreater(dry_run["counts"]["targetFiles"], 0)
            self.assertTrue((item_root / "video_record.json").exists())

            result = remove_items(str(output_root))

            self.assertTrue(result["ok"])
            self.assertFalse(result["sourceVideosRemoved"])
            self.assertFalse((item_root / "video_record.json").exists())
            self.assertFalse(processing_dir.exists())
            self.assertFalse(item_root.exists())
            self.assertFalse((output_root / "latest" / "items.zip").exists())
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"video")
            self.assertTrue(user_video.exists())
            self.assertEqual(user_video.read_bytes(), b"user video")

    def test_remove_items_can_select_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            input_root.mkdir()
            first = input_root / "first.mp4"
            second = input_root / "second.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output_root = root / "output"
            fake_ffprobe = write_fake_ffprobe(root)
            first_file = video_file_from_path(first, str(input_root))
            second_file = video_file_from_path(second, str(input_root))

            refresh_result = refresh_items([first_file, second_file], str(output_root), ffprobe_bin=fake_ffprobe)
            first_record, second_record = refresh_result["records"]
            first_root = Path(first_record["itemRoot"])
            second_root = Path(second_record["itemRoot"])

            result = remove_items(str(output_root), item_ids=[first_record["itemId"]])

            self.assertTrue(result["ok"])
            self.assertFalse(first_root.exists())
            self.assertTrue(second_root.exists())
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())


if __name__ == "__main__":
    unittest.main()
