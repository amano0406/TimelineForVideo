from __future__ import annotations

import unittest
from pathlib import Path

from video2timeline_worker.ffmpeg_utils import summarize_probe_payload


class ProbeSummaryTests(unittest.TestCase):
    def test_summarize_probe_payload_extracts_lightweight_eta_metadata(self) -> None:
        payload = {
            "format": {
                "duration": "120.5",
                "size": "987654321",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "tags": {
                    "creation_time": "2026-03-25T01:02:03Z",
                },
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

        summary = summarize_probe_payload(payload, Path("/tmp/example.mp4"))

        self.assertEqual(120.5, summary["duration_seconds"])
        self.assertEqual(987654321, summary["size_bytes"])
        self.assertEqual("mov", summary["container_name"])
        self.assertEqual("h264", summary["video_codec"])
        self.assertEqual("aac", summary["audio_codec"])
        self.assertEqual(1920, summary["width"])
        self.assertEqual(1080, summary["height"])
        self.assertEqual(29.97, summary["frame_rate"])
        self.assertEqual(2, summary["audio_channels"])
        self.assertEqual(48000, summary["audio_sample_rate"])
        self.assertTrue(summary["has_video"])
        self.assertTrue(summary["has_audio"])
        self.assertEqual("2026-03-25T01:02:03Z", summary["captured_at"])


if __name__ == "__main__":
    unittest.main()
