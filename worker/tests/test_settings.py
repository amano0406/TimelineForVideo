from __future__ import annotations

import unittest
from unittest.mock import patch

from timeline_for_video_worker.settings import (
    SettingsError,
    load_huggingface_token,
    normalize_settings,
    redact_settings,
)


class SettingsTests(unittest.TestCase):
    def test_normalize_settings_deduplicates_input_roots_case_insensitively(self) -> None:
        settings = normalize_settings(
            {
                "schemaVersion": 1,
                "inputRoots": [
                    " C:\\TimelineData\\input-video ",
                    "c:\\timelinedata\\input-video",
                ],
                "outputRoot": " C:\\TimelineData\\video ",
            }
        )

        self.assertEqual(
            settings,
            {
                "schemaVersion": 1,
                "inputRoots": ["C:\\TimelineData\\input-video"],
                "outputRoot": "C:\\TimelineData\\video",
                "huggingfaceToken": "",
                "computeMode": "gpu",
            },
        )

    def test_normalize_settings_preserves_runtime_metadata(self) -> None:
        settings = normalize_settings(
            {
                "schemaVersion": 1,
                "inputRoots": ["C:\\TimelineData\\input-video"],
                "outputRoot": "C:\\TimelineData\\video",
                "runtime": {
                    "instanceName": "LOCAL-ABC123",
                    "apiPort": 19500,
                },
            }
        )

        self.assertEqual(settings["runtime"], {"instanceName": "abc123", "apiPort": 19500})
        self.assertEqual(
            list(settings.keys()),
            ["schemaVersion", "runtime", "inputRoots", "outputRoot", "huggingfaceToken", "computeMode"],
        )

    def test_normalize_settings_rejects_invalid_runtime_port(self) -> None:
        with self.assertRaises(SettingsError):
            normalize_settings(
                {
                    "schemaVersion": 1,
                    "inputRoots": ["C:\\TimelineData\\input-video"],
                    "outputRoot": "C:\\TimelineData\\video",
                    "runtime": {
                        "apiPort": 70000,
                    },
                }
            )

    def test_normalize_settings_rejects_empty_output_root(self) -> None:
        with self.assertRaises(SettingsError):
            normalize_settings(
                {
                    "schemaVersion": 1,
                    "inputRoots": ["C:\\TimelineData\\input-video"],
                    "outputRoot": " ",
                }
            )

    def test_load_huggingface_token_prefers_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "hf_env_token",
                "HUGGING_FACE_HUB_TOKEN": "",
                "HF_TOKEN": "",
            },
            clear=False,
        ):
            token = load_huggingface_token({"huggingfaceToken": "hf_settings_token"})

        self.assertEqual(token, "hf_env_token")

    def test_load_huggingface_token_accepts_legacy_setting_key(self) -> None:
        token = load_huggingface_token({"huggingFaceToken": "hf_legacy_settings_token"})

        self.assertEqual(token, "hf_legacy_settings_token")

    def test_redact_settings_reports_token_source_without_leaking_value(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "",
                "HUGGING_FACE_HUB_TOKEN": "hf_env_secret",
                "HF_TOKEN": "",
            },
            clear=False,
        ):
            redacted = redact_settings(
                {
                    "schemaVersion": 1,
                    "inputRoots": ["C:\\TimelineData\\input-video"],
                    "outputRoot": "C:\\TimelineData\\video",
                    "huggingfaceToken": "",
                    "computeMode": "cpu",
                }
            )

        self.assertEqual(redacted["huggingfaceToken"], {"configured": True, "source": "environment"})
        self.assertNotIn("hf_env_secret", str(redacted))


if __name__ == "__main__":
    unittest.main()
