from __future__ import annotations

import unittest
from unittest.mock import patch

from timeline_for_video_worker.model_inventory import build_model_inventory


def ok_runtime(command_name: str) -> dict[str, object]:
    return {
        "ok": True,
        "command": [command_name, "-version"],
        "versionLine": f"{command_name} fake 1.0",
        "error": None,
    }


def audio_status(*, token_configured: bool = False) -> dict[str, object]:
    modules = {
        "pyannote.audio": True,
        "torch": True,
        "torchaudio": True,
        "faster_whisper": True,
        "ctranslate2": True,
        "huggingface_hub": True,
    }
    return {
        "ready": token_configured,
        "tokenConfigured": token_configured,
        "modules": modules,
        "diarization": {
            "backend": "pyannote.audio",
            "modelId": "pyannote/speaker-diarization-community-1",
            "ready": token_configured,
        },
        "transcription": {
            "backend": "faster-whisper",
            "modelId": "Systran/faster-whisper-large-v3",
            "modelAlias": "faster_whisper_large_v3",
            "ready": True,
        },
    }


class ModelInventoryTests(unittest.TestCase):
    def test_inventory_required_components_are_ready_without_audio_token(self) -> None:
        with patch("timeline_for_video_worker.model_inventory.ffprobe_version", return_value=ok_runtime("ffprobe")):
            with patch("timeline_for_video_worker.model_inventory.ffmpeg_version", return_value=ok_runtime("ffmpeg")):
                with patch(
                    "timeline_for_video_worker.model_inventory.ocr_runtime_status",
                    return_value={
                        "ok": True,
                        "mode": "auto",
                        "model": "tesseract:jpn+eng",
                        "languages": ["eng", "jpn"],
                        "message": "ready",
                    },
                ):
                    with patch(
                        "timeline_for_video_worker.model_inventory.audio_model_runtime_status",
                        return_value=audio_status(token_configured=False),
                    ):
                        payload = build_model_inventory(settings={})

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["pipeline"]["name"], "TimelineForVideo")
        self.assertEqual(len(payload["pipeline"]["generation_signature"]), 64)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["counts"]["components"], 10)
        self.assertEqual(payload["counts"]["requiredComponents"], 9)
        self.assertEqual(payload["counts"]["readyRequiredComponents"], 8)
        self.assertEqual(payload["counts"]["audioModelComponents"], 2)
        self.assertEqual(payload["counts"]["readyAudioModelComponents"], 1)
        rows = {row["role"]: row for row in payload["models"]}
        self.assertEqual(rows["speaker_diarization"]["model_id"], "pyannote/speaker-diarization-community-1")
        self.assertTrue(rows["speaker_diarization"]["requires_huggingface_token"])
        self.assertTrue(rows["speaker_diarization"]["requires_access_approval"])
        self.assertEqual(rows["speech_transcription"]["model_id"], "Systran/faster-whisper-large-v3")
        self.assertEqual(rows["speech_transcription"]["backend"], "faster-whisper")
        self.assertEqual(rows["frame_diff_vlm"]["model_id"], "Qwen/Qwen3.5-4B")
        self.assertFalse(rows["frame_diff_vlm"]["required"])
        self.assertEqual(rows["speech_candidate_detection"]["model_id"], "ffmpeg-silencedetect-noise-35db")
        self.assertEqual(rows["frame_ocr"]["model_id"], "tesseract:jpn+eng")
        self.assertFalse(payload["sourceVideoSafety"]["sourceVideoModified"])
        self.assertFalse(payload["sourceVideoSafety"]["sourceVideosIncludedInZip"])
        self.assertFalse(payload["sourceVideoSafety"]["generatedAudioIncludedInZip"])
        self.assertFalse(payload["sourceVideoSafety"]["externalAnalysisApiUsed"])
        components = {component["id"]: component for component in payload["components"]}
        self.assertTrue(components["frame_visual_features"]["runtime"]["ready"])
        self.assertTrue(components["frame_transition_gate"]["runtime"]["ready"])
        self.assertIn("frame_diff_vlm", components)
        self.assertFalse(components["frame_diff_vlm"]["execution"]["required"])
        self.assertFalse(components["speaker_diarization"]["runtime"]["details"]["componentReady"])
        self.assertTrue(components["speech_transcription"]["runtime"]["details"]["componentReady"])
        self.assertFalse(components["speech_transcription"]["runtime"]["details"]["audioModelsReady"])

    def test_inventory_marks_local_runtime_failure_as_not_ok(self) -> None:
        failed_ffmpeg = {
            "ok": False,
            "command": ["ffmpeg", "-version"],
            "versionLine": None,
            "error": "missing ffmpeg",
        }
        with patch("timeline_for_video_worker.model_inventory.ffprobe_version", return_value=ok_runtime("ffprobe")):
            with patch("timeline_for_video_worker.model_inventory.ffmpeg_version", return_value=failed_ffmpeg):
                with patch(
                    "timeline_for_video_worker.model_inventory.ocr_runtime_status",
                    return_value={
                        "ok": True,
                        "mode": "off",
                        "model": None,
                        "languages": [],
                        "message": "disabled",
                    },
                ):
                    with patch(
                        "timeline_for_video_worker.model_inventory.audio_model_runtime_status",
                        return_value=audio_status(token_configured=False),
                    ):
                        payload = build_model_inventory(settings={})

        self.assertFalse(payload["ok"])
        components = {component["id"]: component for component in payload["components"]}
        self.assertFalse(components["bounded_frame_sampling"]["runtime"]["ready"])
        self.assertFalse(components["audio_derivative"]["runtime"]["ready"])
        self.assertFalse(components["speech_candidate_detection"]["runtime"]["ready"])

    def test_inventory_can_include_remote_huggingface_metadata(self) -> None:
        remote = {
            "remote_status": "ok",
            "license": "cc-by-4.0",
            "gated": "auto",
        }
        with patch("timeline_for_video_worker.model_inventory.ffprobe_version", return_value=ok_runtime("ffprobe")):
            with patch("timeline_for_video_worker.model_inventory.ffmpeg_version", return_value=ok_runtime("ffmpeg")):
                with patch(
                    "timeline_for_video_worker.model_inventory.ocr_runtime_status",
                    return_value={
                        "ok": True,
                        "mode": "auto",
                        "model": "tesseract:jpn+eng",
                        "languages": ["eng", "jpn"],
                        "message": "ready",
                    },
                ):
                    with patch(
                        "timeline_for_video_worker.model_inventory.audio_model_runtime_status",
                        return_value=audio_status(token_configured=True),
                    ):
                        with patch(
                            "timeline_for_video_worker.model_inventory.fetch_huggingface_model_metadata",
                            return_value=remote,
                        ) as fetch:
                            payload = build_model_inventory(settings={}, include_remote=True)

        rows = {row["role"]: row for row in payload["models"]}
        self.assertEqual(rows["speaker_diarization"]["huggingface"], remote)
        self.assertEqual(rows["speech_transcription"]["huggingface"], remote)
        self.assertEqual(rows["frame_diff_vlm"]["huggingface"], remote)
        self.assertNotIn("huggingface", rows["speech_candidate_detection"])
        self.assertNotIn("huggingface", rows["frame_ocr"])
        self.assertEqual(fetch.call_count, 3)


if __name__ == "__main__":
    unittest.main()
