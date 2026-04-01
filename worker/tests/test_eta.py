from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from video2timeline_worker.contracts import ManifestItem
from video2timeline_worker.eta import build_eta_predictor, estimate_remaining_seconds


def _write_run(
    root: Path,
    *,
    job_id: str,
    compute_mode: str,
    processing_quality: str,
    items: list[dict[str, object]],
) -> None:
    run_dir = root / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "schema_version": 1,
        "job_id": job_id,
        "created_at": "2026-04-01T10:00:00+09:00",
        "output_root_id": "runs",
        "output_root_path": str(root),
        "profile": "quality-first",
        "compute_mode": compute_mode,
        "processing_quality": processing_quality,
        "reprocess_duplicates": False,
        "token_enabled": False,
        "input_items": [],
    }
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "generated_at": "2026-04-01T10:00:00+09:00",
        "items": items,
    }
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class EtaPredictorTests(unittest.TestCase):
    def test_predictor_prefers_similar_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-1080",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 4.0,
                        "processing_wall_seconds": 36.0,
                        "container_name": "mov",
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "width": 1920,
                        "height": 1080,
                        "frame_rate": 60.0,
                        "has_video": True,
                        "has_audio": True,
                    }
                ],
            )
            _write_run(
                root,
                job_id="job-old-720",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 4.0,
                        "processing_wall_seconds": 43.0,
                        "container_name": "mov",
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "width": 1280,
                        "height": 720,
                        "frame_rate": 30.0,
                        "has_video": True,
                        "has_audio": True,
                    }
                ],
            )

            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            high_res_item = ManifestItem(
                input_id="input-1",
                source_kind="upload",
                original_path="reencode-001.mp4",
                file_name="reencode-001.mp4",
                size_bytes=600_000,
                duration_seconds=4.0,
                sha256="a" * 64,
                duplicate_status="new",
                media_id="media-1",
                status="queued",
                container_name="mov",
                video_codec="h264",
                audio_codec="aac",
                width=1920,
                height=1080,
                frame_rate=60.0,
                has_video=True,
                has_audio=True,
            )
            low_res_item = ManifestItem(
                input_id="input-2",
                source_kind="upload",
                original_path="reencode-002.mp4",
                file_name="reencode-002.mp4",
                size_bytes=4_400_000,
                duration_seconds=4.0,
                sha256="b" * 64,
                duplicate_status="new",
                media_id="media-2",
                status="queued",
                container_name="mov",
                video_codec="h264",
                audio_codec="aac",
                width=1280,
                height=720,
                frame_rate=30.0,
                has_video=True,
                has_audio=True,
            )

            high_prediction = predictor.predict_item(high_res_item)
            low_prediction = predictor.predict_item(low_res_item)

            self.assertIsNotNone(high_prediction)
            self.assertIsNotNone(low_prediction)
            assert high_prediction is not None
            assert low_prediction is not None
            self.assertLess(high_prediction.total_seconds, low_prediction.total_seconds)
            self.assertGreaterEqual(high_prediction.sample_count, 2)

    def test_remaining_estimate_blends_history_with_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-1",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 5.0,
                        "processing_wall_seconds": 10.0,
                        "container_name": "mov",
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "width": 1280,
                        "height": 720,
                        "frame_rate": 30.0,
                        "has_video": True,
                        "has_audio": True,
                    }
                ],
            )
            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            items = [
                ManifestItem(
                    input_id="input-1",
                    source_kind="upload",
                    original_path="clip-1.mp4",
                    file_name="clip-1.mp4",
                    size_bytes=1_000,
                    duration_seconds=5.0,
                    sha256="c" * 64,
                    duplicate_status="new",
                    media_id="media-1",
                    status="queued",
                    container_name="mov",
                    video_codec="h264",
                    audio_codec="aac",
                    width=1280,
                    height=720,
                    frame_rate=30.0,
                    has_video=True,
                    has_audio=True,
                ),
                ManifestItem(
                    input_id="input-2",
                    source_kind="upload",
                    original_path="clip-2.mp4",
                    file_name="clip-2.mp4",
                    size_bytes=2_000,
                    duration_seconds=5.0,
                    sha256="d" * 64,
                    duplicate_status="new",
                    media_id="media-2",
                    status="queued",
                    container_name="mov",
                    video_codec="h264",
                    audio_codec="aac",
                    width=1280,
                    height=720,
                    frame_rate=30.0,
                    has_video=True,
                    has_audio=True,
                ),
            ]

            remaining = estimate_remaining_seconds(
                predictor=predictor,
                manifest_items=items,
                legacy_remaining_sec=40.0,
                current_item_index=0,
                current_item_elapsed_sec=3.0,
                include_export_stage=True,
            )

            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertGreater(remaining, 12.0)
            self.assertLess(remaining, 40.0)

    def test_remaining_estimate_respects_current_stage_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-stage-aware",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 5.0,
                        "processing_wall_seconds": 10.0,
                        "container_name": "mov",
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "width": 1280,
                        "height": 720,
                        "frame_rate": 30.0,
                        "has_video": True,
                        "has_audio": True,
                        "stage_elapsed_seconds": {
                            "extract_audio": 1.0,
                            "trim_silence": 1.0,
                            "transcribe": 5.0,
                            "screen_extract": 2.0,
                            "timeline_render": 1.0,
                        },
                    }
                ],
            )
            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            items = [
                ManifestItem(
                    input_id="input-1",
                    source_kind="upload",
                    original_path="clip-1.mp4",
                    file_name="clip-1.mp4",
                    size_bytes=1_000,
                    duration_seconds=5.0,
                    sha256="e" * 64,
                    duplicate_status="new",
                    media_id="media-1",
                    status="queued",
                    container_name="mov",
                    video_codec="h264",
                    audio_codec="aac",
                    width=1280,
                    height=720,
                    frame_rate=30.0,
                    has_video=True,
                    has_audio=True,
                )
            ]

            remaining = estimate_remaining_seconds(
                predictor=predictor,
                manifest_items=items,
                legacy_remaining_sec=None,
                current_item_index=0,
                current_item_elapsed_sec=6.0,
                current_stage_name="transcribe",
                current_stage_elapsed_sec=1.0,
                include_export_stage=False,
            )

            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertAlmostEqual(remaining, 7.0, places=3)


if __name__ == "__main__":
    unittest.main()
