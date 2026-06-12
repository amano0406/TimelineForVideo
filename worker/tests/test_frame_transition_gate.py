from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from timeline_for_video_worker.frame_transition_gate import (
    FrameTransitionGatePolicy,
    analyze_frame_transition_gate,
)


class FrameTransitionGateTests(unittest.TestCase):
    def test_identical_adjacent_frames_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "frame-000001.jpg"
            second = root / "frame-000002.jpg"
            Image.new("RGB", (320, 180), "white").save(first)
            Image.new("RGB", (320, 180), "white").save(second)

            result = analyze_frame_transition_gate(
                [frame_record(first, 1, 1.0), frame_record(second, 2, 2.0)],
                policy=FrameTransitionGatePolicy(width=160, height=90),
            )

            self.assertTrue(result["available"])
            self.assertEqual(result["counts"]["transitions"], 1)
            self.assertEqual(result["counts"]["wouldSkip"], 1)
            transition = result["transitions"][0]
            self.assertEqual(transition["decision"], "skip_same")
            self.assertFalse(transition["wouldSendToVlm"])

    def test_large_local_change_is_sent_to_vlm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "frame-000001.jpg"
            second = root / "frame-000002.jpg"
            Image.new("RGB", (320, 180), "white").save(first)
            changed = Image.new("RGB", (320, 180), "white")
            draw = ImageDraw.Draw(changed)
            draw.rectangle([80, 40, 210, 120], fill="black")
            changed.save(second)

            result = analyze_frame_transition_gate(
                [frame_record(first, 1, 1.0), frame_record(second, 2, 2.0)],
                policy=FrameTransitionGatePolicy(width=160, height=90),
            )

            transition = result["transitions"][0]
            self.assertEqual(transition["decision"], "needs_vlm")
            self.assertTrue(transition["wouldSendToVlm"])
            self.assertGreater(transition["masked"]["changedRatio"], 0.05)

    def test_unreadable_images_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "frame-000001.jpg"
            second = root / "frame-000002.jpg"
            first.write_bytes(b"not an image")
            second.write_bytes(b"not an image")

            result = analyze_frame_transition_gate(
                [frame_record(first, 1, 1.0), frame_record(second, 2, 2.0)],
                policy=FrameTransitionGatePolicy(width=160, height=90),
            )

            self.assertFalse(result["available"])
            self.assertEqual(result["counts"]["failedTransitions"], 1)
            transition = result["transitions"][0]
            self.assertEqual(transition["decision"], "unavailable")
            self.assertTrue(transition["wouldSendToVlm"])
            self.assertTrue(result["warnings"])


def frame_record(path: Path, index: int, time_sec: float) -> dict[str, object]:
    return {
        "index": index,
        "frameId": f"frame-{index:06d}",
        "timeSec": time_sec,
        "ok": True,
        "outputPath": str(path),
    }


if __name__ == "__main__":
    unittest.main()
