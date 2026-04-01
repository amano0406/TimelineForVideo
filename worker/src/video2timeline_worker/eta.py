from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .contracts import ManifestItem

_TERMINAL_ITEM_STATES = {"completed", "failed", "skipped_duplicate"}
_MAX_MATCH_SCORE = 13.5
_STAGE_ORDER = [
    "extract_audio",
    "trim_silence",
    "transcribe",
    "screen_extract",
    "timeline_render",
]
_DEFAULT_STAGE_SHARES = {
    "extract_audio": 0.12,
    "trim_silence": 0.12,
    "transcribe": 0.48,
    "screen_extract": 0.22,
    "timeline_render": 0.06,
}


def _normalize_text(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _resolution_bucket(width: int | None, height: int | None) -> str:
    max_dimension = max(width or 0, height or 0)
    if max_dimension <= 0:
        return "unknown"
    if max_dimension <= 720:
        return "sd"
    if max_dimension <= 1080:
        return "hd"
    if max_dimension <= 1440:
        return "qhd"
    return "uhd"


def _frame_rate_bucket(frame_rate: float | None) -> str:
    if frame_rate is None or frame_rate <= 0:
        return "unknown"
    if frame_rate <= 24.5:
        return "cinema"
    if frame_rate <= 30.5:
        return "standard"
    if frame_rate <= 60.5:
        return "high"
    return "ultra"


def _scale_sample_total(sample_duration_sec: float, sample_total_sec: float, target_duration_sec: float) -> float:
    safe_sample_duration = max(1.0, sample_duration_sec)
    safe_target_duration = max(1.0, target_duration_sec)
    duration_ratio = max(0.25, min(4.0, safe_target_duration / safe_sample_duration))
    fixed_overhead = min(12.0, sample_total_sec * 0.35)
    variable_component = max(0.0, sample_total_sec - fixed_overhead) * duration_ratio
    return max(1.0, round(fixed_overhead + variable_component, 3))


@dataclass(frozen=True)
class EtaPrediction:
    total_seconds: float
    confidence: float
    sample_count: int
    stage_seconds: dict[str, float]


@dataclass(frozen=True)
class HistoricalSample:
    compute_mode: str
    processing_quality: str
    container_name: str | None
    video_codec: str | None
    audio_codec: str | None
    resolution_bucket: str
    frame_rate_bucket: str
    has_video: bool | None
    has_audio: bool | None
    duration_seconds: float
    processing_wall_seconds: float
    stage_elapsed_seconds: dict[str, float]


class EtaPredictor:
    def __init__(self, samples: Iterable[HistoricalSample], compute_mode: str, processing_quality: str) -> None:
        self._samples = list(samples)
        self._compute_mode = _normalize_text(compute_mode) or "cpu"
        self._processing_quality = _normalize_text(processing_quality) or "standard"

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def predict_item(self, item: ManifestItem) -> EtaPrediction | None:
        candidates = [
            sample
            for sample in self._samples
            if sample.compute_mode == self._compute_mode
            and sample.processing_quality == self._processing_quality
        ]
        if not candidates:
            return None

        item_container = _normalize_text(item.container_name)
        item_video_codec = _normalize_text(item.video_codec)
        item_audio_codec = _normalize_text(item.audio_codec)
        item_resolution_bucket = _resolution_bucket(item.width, item.height)
        item_frame_rate_bucket = _frame_rate_bucket(item.frame_rate)
        item_has_video = item.has_video
        item_has_audio = item.has_audio

        scored: list[tuple[float, HistoricalSample]] = []
        for sample in candidates:
            score = 1.0
            if item_video_codec and sample.video_codec == item_video_codec:
                score += 4.0
            if item_audio_codec and sample.audio_codec == item_audio_codec:
                score += 1.5
            if sample.resolution_bucket == item_resolution_bucket:
                score += 3.5
            if sample.frame_rate_bucket == item_frame_rate_bucket:
                score += 1.5
            if item_container and sample.container_name == item_container:
                score += 1.0
            if item_has_video is not None and sample.has_video == item_has_video:
                score += 0.5
            if item_has_audio is not None and sample.has_audio == item_has_audio:
                score += 0.5
            scored.append((score, sample))

        scored.sort(key=lambda row: row[0], reverse=True)
        top_matches = scored[: min(12, len(scored))]
        total_weight = sum(score for score, _ in top_matches)
        weighted_prediction = sum(
            score
            * _scale_sample_total(
                sample.duration_seconds,
                sample.processing_wall_seconds,
                item.duration_seconds,
            )
            for score, sample in top_matches
        ) / max(total_weight, 0.1)
        average_score = total_weight / max(len(top_matches), 1)
        sample_factor = min(1.0, len(top_matches) / 5.0)
        feature_factor = min(1.0, average_score / _MAX_MATCH_SCORE)
        confidence = min(0.9, 0.15 + (0.55 * sample_factor) + (0.30 * feature_factor))
        stage_shares = _weighted_stage_shares(top_matches)
        stage_seconds = {
            stage_name: round(weighted_prediction * share, 3)
            for stage_name, share in stage_shares.items()
        }
        return EtaPrediction(
            total_seconds=max(1.0, round(weighted_prediction, 3)),
            confidence=round(confidence, 3),
            sample_count=len(top_matches),
            stage_seconds=stage_seconds,
        )


def build_eta_predictor(
    *,
    output_root: Path,
    current_job_id: str,
    compute_mode: str,
    processing_quality: str,
) -> EtaPredictor:
    samples: list[HistoricalSample] = []
    normalized_compute_mode = _normalize_text(compute_mode) or "cpu"
    normalized_processing_quality = _normalize_text(processing_quality) or "standard"
    if not output_root.exists():
        return EtaPredictor(samples, normalized_compute_mode, normalized_processing_quality)

    job_dirs = sorted(output_root.glob("job-*")) + sorted(output_root.glob("run-*"))
    seen_dirs: set[Path] = set()
    for run_dir in job_dirs:
        resolved = run_dir.resolve()
        if resolved in seen_dirs or resolved.name == current_job_id or not resolved.is_dir():
            continue
        seen_dirs.add(resolved)

        request_path = resolved / "request.json"
        manifest_path = resolved / "manifest.json"
        if not request_path.exists() or not manifest_path.exists():
            continue

        try:
            request = json.loads(request_path.read_text(encoding="utf-8-sig", errors="replace"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue

        if (_normalize_text(request.get("compute_mode")) or "cpu") != normalized_compute_mode:
            continue
        if (_normalize_text(request.get("processing_quality")) or "standard") != normalized_processing_quality:
            continue

        for item in manifest.get("items", []):
            if str(item.get("status") or "").lower() != "completed":
                continue
            processing_wall_seconds = float(item.get("processing_wall_seconds") or 0.0)
            duration_seconds = float(item.get("duration_seconds") or 0.0)
            if processing_wall_seconds <= 0 or duration_seconds <= 0:
                continue

            samples.append(
                HistoricalSample(
                    compute_mode=normalized_compute_mode,
                    processing_quality=normalized_processing_quality,
                    container_name=_normalize_text(item.get("container_name")),
                    video_codec=_normalize_text(item.get("video_codec")),
                    audio_codec=_normalize_text(item.get("audio_codec")),
                    resolution_bucket=_resolution_bucket(
                        _to_optional_int(item.get("width")),
                        _to_optional_int(item.get("height")),
                    ),
                    frame_rate_bucket=_frame_rate_bucket(_to_optional_float(item.get("frame_rate"))),
                    has_video=_to_optional_bool(item.get("has_video")),
                    has_audio=_to_optional_bool(item.get("has_audio")),
                    duration_seconds=duration_seconds,
                    processing_wall_seconds=processing_wall_seconds,
                    stage_elapsed_seconds=_normalize_stage_elapsed(item.get("stage_elapsed_seconds")),
                )
            )

    return EtaPredictor(samples, normalized_compute_mode, normalized_processing_quality)


def estimate_remaining_seconds(
    *,
    predictor: EtaPredictor,
    manifest_items: list[ManifestItem],
    legacy_remaining_sec: float | None,
    current_item_index: int | None = None,
    current_item_elapsed_sec: float = 0.0,
    current_stage_name: str | None = None,
    current_stage_elapsed_sec: float = 0.0,
    include_export_stage: bool = True,
) -> float | None:
    history_remaining = 0.0
    confidences: list[float] = []
    predicted_any = False

    if current_item_index is not None and 0 <= current_item_index < len(manifest_items):
        current_item = manifest_items[current_item_index]
        if str(current_item.status).lower() not in _TERMINAL_ITEM_STATES and current_item.duplicate_status != "duplicate_skip":
            prediction = predictor.predict_item(current_item)
            if prediction is not None:
                if current_stage_name:
                    history_remaining += _remaining_for_current_stage(
                        prediction.stage_seconds,
                        current_stage_name,
                        current_stage_elapsed_sec,
                    )
                else:
                    history_remaining += max(
                        0.0,
                        prediction.total_seconds - max(0.0, current_item_elapsed_sec),
                    )
                confidences.append(prediction.confidence)
                predicted_any = True

    for index, item in enumerate(manifest_items):
        if current_item_index is not None and index <= current_item_index:
            continue
        if item.duplicate_status == "duplicate_skip" or str(item.status).lower() in _TERMINAL_ITEM_STATES:
            continue
        prediction = predictor.predict_item(item)
        if prediction is None:
            continue
        history_remaining += prediction.total_seconds
        confidences.append(prediction.confidence)
        predicted_any = True

    if predicted_any and include_export_stage:
        history_remaining += 5.0
        confidences.append(0.4)

    if not predicted_any:
        return legacy_remaining_sec

    history_confidence = sum(confidences) / max(len(confidences), 1)
    history_remaining = round(max(0.0, history_remaining), 3)
    if legacy_remaining_sec is None:
        return history_remaining

    blended = (history_remaining * history_confidence) + (legacy_remaining_sec * (1.0 - history_confidence))
    return round(max(0.0, blended), 3)


def _to_optional_int(value: object) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_optional_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if str(value).strip() == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _normalize_stage_elapsed(payload: object) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, float] = {}
    for stage_name in _STAGE_ORDER:
        value = _to_optional_float(payload.get(stage_name))
        if value is not None and value >= 0:
            normalized[stage_name] = value
    return normalized


def _weighted_stage_shares(top_matches: list[tuple[float, HistoricalSample]]) -> dict[str, float]:
    weighted_shares = {stage_name: 0.0 for stage_name in _STAGE_ORDER}
    total_weight = sum(score for score, _ in top_matches)
    if total_weight <= 0:
        return dict(_DEFAULT_STAGE_SHARES)

    for score, sample in top_matches:
        sample_total = max(sample.processing_wall_seconds, 0.001)
        for stage_name in _STAGE_ORDER:
            stage_elapsed = sample.stage_elapsed_seconds.get(stage_name)
            if stage_elapsed is not None and stage_elapsed >= 0:
                share = max(0.0, min(1.0, stage_elapsed / sample_total))
            else:
                share = _DEFAULT_STAGE_SHARES[stage_name]
            weighted_shares[stage_name] += score * share

    summed = sum(weighted_shares.values())
    if summed <= 0:
        return dict(_DEFAULT_STAGE_SHARES)
    return {stage_name: value / summed for stage_name, value in weighted_shares.items()}


def _remaining_for_current_stage(
    stage_seconds: dict[str, float], current_stage_name: str, current_stage_elapsed_sec: float
) -> float:
    remaining = 0.0
    current_seen = False
    for stage_name in _STAGE_ORDER:
        stage_total = max(0.0, stage_seconds.get(stage_name, 0.0))
        if stage_name == current_stage_name:
            current_seen = True
            remaining += max(0.0, stage_total - max(0.0, current_stage_elapsed_sec))
            continue
        if current_seen:
            remaining += stage_total
    if not current_seen:
        stage_total = sum(stage_seconds.values())
        remaining = max(0.0, stage_total - max(0.0, current_stage_elapsed_sec))
    return round(max(0.0, remaining), 3)
