from __future__ import annotations

import unittest

from video2timeline_worker.screens import (
    candidate_timestamps,
    normalize_processing_quality,
    resolve_caption_model_id_for_quality,
)


class CandidateTimestampsTests(unittest.TestCase):
    def test_short_videos_keep_single_zero_timestamp(self) -> None:
        self.assertEqual(candidate_timestamps(0.8), [0.0])

    def test_last_timestamp_is_clamped_before_duration(self) -> None:
        timestamps = candidate_timestamps(8.783)
        self.assertGreater(len(timestamps), 1)
        self.assertLess(timestamps[-1], 8.783)
        self.assertAlmostEqual(timestamps[-1], 8.733, places=3)


class ProcessingQualityTests(unittest.TestCase):
    def test_normalize_processing_quality_defaults_to_standard(self) -> None:
        self.assertEqual(normalize_processing_quality(None), "standard")
        self.assertEqual(normalize_processing_quality(""), "standard")
        self.assertEqual(normalize_processing_quality("medium"), "standard")

    def test_normalize_processing_quality_accepts_high(self) -> None:
        self.assertEqual(normalize_processing_quality("high"), "high")
        self.assertEqual(normalize_processing_quality("HIGH"), "high")

    def test_caption_model_stays_on_stable_default(self) -> None:
        self.assertEqual(
            resolve_caption_model_id_for_quality("standard"),
            "florence-community/Florence-2-base",
        )
        self.assertEqual(
            resolve_caption_model_id_for_quality("high"),
            "florence-community/Florence-2-base",
        )


if __name__ == "__main__":
    unittest.main()
