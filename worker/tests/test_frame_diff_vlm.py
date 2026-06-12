from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_video_worker.frame_diff_vlm import (
    FrameDiffVlmOptions,
    analyze_frame_diff_vlm_outputs,
    normalize_frame_diff_vlm_mode,
    parse_vlm_json,
)


class FakeRunner:
    def analyze(self, left_path: Path, right_path: Path, prompt: str) -> dict[str, object]:
        parsed = {
            "changed": True,
            "changeLevel": "meaningful",
            "summary": "入力欄の文字が追加された。",
            "differences": ["入力欄に文字列が表示された"],
            "confidence": 0.91,
        }
        return {
            "rawText": json.dumps(parsed, ensure_ascii=False),
            "parsed": parsed,
            "elapsedSec": 0.123,
        }


class BadJsonRunner:
    def analyze(self, left_path: Path, right_path: Path, prompt: str) -> dict[str, object]:
        return {
            "rawText": "JSONではない説明文",
            "parsed": {},
            "parseError": "JSONDecodeError:invalid",
            "elapsedSec": 0.1,
        }


def ready_runtime() -> dict[str, object]:
    return {
        "ok": True,
        "ready": True,
        "backend": "transformers",
        "modelId": "Qwen/Qwen3.5-4B",
        "modules": {
            "torch": True,
            "torchvision": True,
            "transformers": True,
            "qwen_vl_utils": True,
            "PIL": True,
        },
        "cudaAvailable": True,
        "message": "ready",
    }


def missing_runtime() -> dict[str, object]:
    runtime = ready_runtime()
    runtime["ok"] = False
    runtime["ready"] = False
    runtime["modules"] = {
        "torch": True,
        "torchvision": False,
        "transformers": False,
        "qwen_vl_utils": False,
        "PIL": True,
    }
    return runtime


def write_frame_samples(item_root: Path) -> None:
    frames_dir = item_root / "artifacts" / "frames"
    raw_outputs = item_root / "raw_outputs"
    frames_dir.mkdir(parents=True)
    raw_outputs.mkdir(parents=True)
    left = frames_dir / "frame-000001.jpg"
    right = frames_dir / "frame-000002.jpg"
    left.write_bytes(b"left")
    right.write_bytes(b"right")
    (raw_outputs / "frame_samples.json").write_text(
        json.dumps(
            {
                "frames": [
                    {"frameId": "frame-000001", "timeSec": 1.0, "ok": True, "outputPath": str(left)},
                    {"frameId": "frame-000002", "timeSec": 2.0, "ok": True, "outputPath": str(right)},
                ],
                "visualGate": {
                    "schemaVersion": "timeline_for_video.frame_transition_gate.v1",
                    "transitions": [
                        {
                            "index": 1,
                            "fromFrameId": "frame-000001",
                            "toFrameId": "frame-000002",
                            "fromTimeSec": 1.0,
                            "toTimeSec": 2.0,
                            "ok": True,
                            "decision": "needs_vlm",
                            "wouldSendToVlm": True,
                            "reasons": ["changed_ratio_exceeds_vlm_threshold"],
                            "raw": {},
                            "masked": {},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


class FrameDiffVlmTests(unittest.TestCase):
    def test_parse_vlm_json_accepts_fenced_payload(self) -> None:
        payload = parse_vlm_json('```json\n{"changed": false, "summary": "同一"}\n```')

        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["summary"], "同一")

    def test_mode_aliases(self) -> None:
        self.assertEqual(normalize_frame_diff_vlm_mode("false"), "off")
        self.assertEqual(normalize_frame_diff_vlm_mode("true"), "auto")
        with self.assertRaises(ValueError):
            normalize_frame_diff_vlm_mode("invalid")

    def test_analyze_outputs_with_fake_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item_root = root / "items" / "video-test"
            write_frame_samples(item_root)

            with patch("timeline_for_video_worker.frame_diff_vlm.frame_diff_vlm_runtime_status", return_value=ready_runtime()):
                result = analyze_frame_diff_vlm_outputs(
                    str(root),
                    options=FrameDiffVlmOptions(mode="required"),
                    runner=FakeRunner(),
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["candidateTransitions"], 1)
            self.assertEqual(result["counts"]["analyzedTransitions"], 1)
            self.assertEqual(result["counts"]["changedTransitions"], 1)
            output = json.loads((item_root / "raw_outputs" / "frame_diff_vlm.json").read_text(encoding="utf-8"))
            self.assertEqual(output["status"], "completed")
            self.assertEqual(output["transitions"][0]["summary"], "入力欄の文字が追加された。")
            self.assertEqual(output["transitions"][0]["changeLevel"], "meaningful")

    def test_parse_failure_keeps_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item_root = root / "items" / "video-test"
            write_frame_samples(item_root)

            with patch("timeline_for_video_worker.frame_diff_vlm.frame_diff_vlm_runtime_status", return_value=ready_runtime()):
                result = analyze_frame_diff_vlm_outputs(
                    str(root),
                    options=FrameDiffVlmOptions(mode="required"),
                    runner=BadJsonRunner(),
                )

            self.assertFalse(result["ok"])
            output = json.loads((item_root / "raw_outputs" / "frame_diff_vlm.json").read_text(encoding="utf-8"))
            self.assertEqual(output["transitions"][0]["status"], "parse_failed")
            self.assertEqual(output["transitions"][0]["rawText"], "JSONではない説明文")

    def test_required_mode_fails_when_dependencies_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item_root = root / "items" / "video-test"
            write_frame_samples(item_root)

            with patch("timeline_for_video_worker.frame_diff_vlm.frame_diff_vlm_runtime_status", return_value=missing_runtime()):
                result = analyze_frame_diff_vlm_outputs(
                    str(root),
                    options=FrameDiffVlmOptions(mode="required"),
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["counts"]["skippedTransitions"], 1)
            output = json.loads((item_root / "raw_outputs" / "frame_diff_vlm.json").read_text(encoding="utf-8"))
            self.assertEqual(output["status"], "skipped_dependency_unavailable")
            self.assertFalse(output["ok"])


if __name__ == "__main__":
    unittest.main()
