from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from timeline_for_video_worker.frame_ocr import (
    analyze_frame_ocr_outputs,
    ocr_runtime_status,
)


class FrameOcrTests(unittest.TestCase):
    def test_analyze_frame_ocr_outputs_writes_mock_ocr_under_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "output"
            item_root = output_root / "items" / "video-test"
            frames_dir = item_root / "artifacts" / "frames"
            raw_outputs_dir = item_root / "raw_outputs"
            frame_path = frames_dir / "frame-000001.jpg"
            frames_dir.mkdir(parents=True)
            raw_outputs_dir.mkdir(parents=True)
            Image.new("RGB", (120, 80), "white").save(frame_path)
            (raw_outputs_dir / "frame_samples.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {
                                "frameId": "frame-000001",
                                "timeSec": 1.0,
                                "ok": True,
                                "outputPath": str(frame_path),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = analyze_frame_ocr_outputs(str(output_root), mode="mock")

            frame_ocr_path = raw_outputs_dir / "frame_ocr.json"
            overlay_path = item_root / "artifacts" / "ocr" / "frame-000001-ocr.jpg"
            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["textBlocks"], 1)
            self.assertTrue(frame_ocr_path.exists())
            self.assertTrue(overlay_path.exists())
            frame_ocr = json.loads(frame_ocr_path.read_text(encoding="utf-8"))
            self.assertEqual(frame_ocr["schemaVersion"], "timeline_for_video.frame_ocr.v1")
            self.assertTrue(frame_ocr["frames"][0]["ocr"]["has_text"])
            visual = frame_ocr["frames"][0]["visual"]
            self.assertTrue(visual["available"])
            self.assertEqual(visual["quality"]["brightness_level"], "bright")
            self.assertGreater(len(visual["color_palette"]), 0)
            self.assertEqual(len(visual["grid"]), 9)
            self.assertEqual(visual["grid"][0]["cell_id"], "grid_0_0")

    def test_ocr_runtime_status_off_is_ready_without_tesseract(self) -> None:
        status = ocr_runtime_status("off")

        self.assertTrue(status["ok"])
        self.assertEqual(status["mode"], "off")

    def test_analyze_frame_ocr_outputs_reports_item_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "output"
            events: list[dict[str, object]] = []
            for item_id in ("video-first", "video-second"):
                raw_outputs_dir = output_root / "items" / item_id / "raw_outputs"
                raw_outputs_dir.mkdir(parents=True)
                (raw_outputs_dir / "frame_samples.json").write_text(
                    json.dumps({"frames": []}),
                    encoding="utf-8",
                )

            analyze_frame_ocr_outputs(
                str(output_root),
                mode="off",
                progress_callback=events.append,
            )

            self.assertGreaterEqual(len(events), 4)
            self.assertEqual(events[0]["itemsDone"], 0)
            self.assertEqual(events[-1]["itemsDone"], 2)
            self.assertEqual(events[-1]["total"], 2)


if __name__ == "__main__":
    unittest.main()
