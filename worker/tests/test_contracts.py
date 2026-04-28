from __future__ import annotations

import unittest

from timelineforvideo_worker.contracts import InputItem, JobRequest


class ContractsTests(unittest.TestCase):
    def test_job_request_round_trip_preserves_input_items(self) -> None:
        request = JobRequest(
            schema_version=1,
            job_id="run-123",
            created_at="2026-03-23T18:00:00+09:00",
            output_root_id="default",
            output_root_path="/data/output",
            profile="quality-first",
            compute_mode="gpu",
            processing_quality="high",
            reprocess_duplicates=False,
            token_enabled=True,
            input_items=[
                InputItem(
                    input_id="scan-0001",
                    source_kind="mounted_root",
                    source_id="primary",
                    original_path="/data/input/example.mp4",
                    display_name="example.mp4",
                    size_bytes=1234,
                )
            ],
        )

        payload = request.to_dict()
        restored = JobRequest.from_dict(payload)

        self.assertEqual("run-123", restored.job_id)
        self.assertEqual("quality-first", restored.profile)
        self.assertEqual("gpu", restored.compute_mode)
        self.assertEqual("high", restored.processing_quality)
        self.assertEqual(1, len(restored.input_items))
        self.assertEqual("example.mp4", restored.input_items[0].display_name)


if __name__ == "__main__":
    unittest.main()
