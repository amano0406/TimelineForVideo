from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Any

from . import __version__
from .discovery import VideoFile, resolve_configured_path
from .probe import analysis_source_path, command_prefix, probe_video_files, utc_now_iso
from .settings import PRODUCT_NAME


ACTIVITY_MAP_SCHEMA_VERSION = "timeline_for_video.activity_map.v1"
ACTIVITY_MAP_RESULT_SCHEMA_VERSION = "timeline_for_video.activity_map_result.v1"
DEFAULT_AUDIO_PADDING_SEC = 1.0
DEFAULT_AUDIO_MERGE_GAP_SEC = 2.0
DEFAULT_VISUAL_INTERVAL_SEC = 300.0
DEFAULT_VISUAL_WIDTH = 160
DEFAULT_VISUAL_HEIGHT = 90
DEFAULT_VISUAL_DELTA_THRESHOLD = 0.001
MAX_VISUAL_SENTINELS = 500
FRAME_TIMEOUT_SEC = 30


def analyze_activity_files(
    video_files: list[VideoFile],
    output_root_text: str,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    max_items: int | None = None,
) -> dict[str, Any]:
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")

    generated_at = utc_now_iso()
    output_root = resolve_configured_path(output_root_text)
    probe_result = probe_video_files(
        video_files,
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        output_root_text=output_root_text,
        max_items=max_items,
    )
    records = [
        analyze_probe_record_activity(
            probe_record,
            output_root=output_root,
            output_root_text=output_root_text,
            ffmpeg_bin=ffmpeg_bin,
            generated_at=generated_at,
        )
        for probe_record in probe_result["records"]
    ]
    failed_items = sum(1 for record in records if not record["ok"])
    return {
        "schemaVersion": ACTIVITY_MAP_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ok": failed_items == 0,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "ffprobeVersion": probe_result["ffprobeVersion"],
        "counts": {
            "discoveredFiles": len(video_files),
            "processedItems": len(records),
            "failedItems": failed_items,
            "skippedByMaxItems": probe_result["counts"]["skippedByMaxItems"],
            "activeSec": round(sum(record["activity"]["activeSec"] for record in records), 3),
            "inactiveSec": round(sum(record["activity"]["inactiveSec"] for record in records), 3),
            "activitySegments": sum(record["activity"]["counts"]["activeSegments"] for record in records),
            "skippedSegments": sum(record["activity"]["counts"]["inactiveSegments"] for record in records),
        },
        "records": records,
    }


def analyze_probe_record_activity(
    probe_record: dict[str, Any],
    *,
    output_root: Path,
    output_root_text: str,
    ffmpeg_bin: str,
    generated_at: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    item_id = probe_record["itemId"]
    item_root = output_root / "items" / item_id
    raw_outputs_dir = item_root / "raw_outputs"
    activity_map_path = raw_outputs_dir / "activity_map.json"
    audio_analysis_path = raw_outputs_dir / "audio_analysis.json"
    warnings: list[str] = []

    summary = probe_record["ffprobe"]["summary"]
    duration_sec = summary["format"]["durationSec"] if summary else None
    record: dict[str, Any] = {
        "schemaVersion": ACTIVITY_MAP_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "itemId": item_id,
        "ok": False,
        "sourceVideoModified": False,
        "sourceIdentity": probe_record["sourceIdentity"],
        "sourceFingerprint": probe_record["sourceFingerprint"],
        "inputs": {
            "ffprobeOk": probe_record["ffprobe"]["ok"],
            "durationSec": duration_sec,
            "audioAnalysisJson": str(audio_analysis_path),
        },
        "parameters": {
            "audioPaddingSec": DEFAULT_AUDIO_PADDING_SEC,
            "audioMergeGapSec": DEFAULT_AUDIO_MERGE_GAP_SEC,
            "visualIntervalSec": DEFAULT_VISUAL_INTERVAL_SEC,
            "maxVisualSentinels": MAX_VISUAL_SENTINELS,
            "visualWidth": DEFAULT_VISUAL_WIDTH,
            "visualHeight": DEFAULT_VISUAL_HEIGHT,
            "visualDeltaThreshold": DEFAULT_VISUAL_DELTA_THRESHOLD,
        },
        "audio": empty_audio_activity(),
        "visual": empty_visual_activity(),
        "activity": empty_activity_summary(duration_sec),
        "outputs": {
            "activityMapJson": str(activity_map_path),
            "outputRootConfiguredPath": output_root_text,
        },
        "warnings": warnings,
    }

    raw_outputs_dir.mkdir(parents=True, exist_ok=True)
    if not probe_record["ffprobe"]["ok"]:
        warnings.append("ffprobe_failed")
        return write_activity_map(record, activity_map_path)
    if not isinstance(duration_sec, (int, float)) or duration_sec <= 0:
        warnings.append("duration_missing")
        record["activity"]["notes"].append("Activity map was skipped because the video duration was not available.")
        record["elapsedSec"] = round(time.perf_counter() - started, 3)
        record["ok"] = True
        return write_activity_map(record, activity_map_path)

    audio_analysis, audio_warning = read_optional_json(audio_analysis_path)
    if audio_warning:
        warnings.append(audio_warning)
    audio_segments = audio_activity_segments(audio_analysis, float(duration_sec))
    record["audio"] = audio_segments

    visual = visual_activity_segments(
        source_path=analysis_source_path(probe_record),
        duration_sec=float(duration_sec),
        ffmpeg_bin=ffmpeg_bin,
    )
    record["visual"] = visual
    warnings.extend(visual["warnings"])

    active_segments = merge_segments(
        audio_segments["activeSegments"] + visual["activeSegments"],
        max_gap_sec=0.0,
        duration_sec=float(duration_sec),
    )
    inactive_segments = inactive_segments_from_active(active_segments, float(duration_sec))
    active_sec = segment_total(active_segments)
    inactive_sec = segment_total(inactive_segments)
    record["activity"] = {
        "strategy": "audio_speech_activity_plus_visual_sentinel",
        "activeSegments": active_segments,
        "inactiveSegments": inactive_segments,
        "activeSec": round(active_sec, 3),
        "inactiveSec": round(inactive_sec, 3),
        "activeRatio": round(active_sec / float(duration_sec), 6) if duration_sec else 0.0,
        "inactiveRatio": round(inactive_sec / float(duration_sec), 6) if duration_sec else 0.0,
        "estimatedReductionRatio": round(float(duration_sec) / active_sec, 3) if active_sec > 0 else None,
        "counts": {
            "activeSegments": len(active_segments),
            "inactiveSegments": len(inactive_segments),
            "audioActiveSegments": len(audio_segments["activeSegments"]),
            "visualActiveSegments": len(visual["activeSegments"]),
            "visualSentinels": len(visual["sentinels"]),
        },
        "notes": [
            "Inactive intervals are skipped because audio is silent and visual sentinels show no meaningful screen change.",
            "Source video was only read; no source bytes were modified.",
        ],
    }
    record["elapsedSec"] = round(time.perf_counter() - started, 3)
    record["ok"] = True
    return write_activity_map(record, activity_map_path)


def empty_audio_activity() -> dict[str, Any]:
    return {
        "available": False,
        "source": "raw_outputs/audio_analysis.json",
        "speechCandidates": 0,
        "rawActiveSec": 0.0,
        "activeSegments": [],
        "parameters": {
            "paddingSec": DEFAULT_AUDIO_PADDING_SEC,
            "mergeGapSec": DEFAULT_AUDIO_MERGE_GAP_SEC,
        },
        "warnings": [],
    }


def empty_visual_activity() -> dict[str, Any]:
    return {
        "available": False,
        "strategy": "five_minute_gray_frame_delta",
        "intervalSec": DEFAULT_VISUAL_INTERVAL_SEC,
        "effectiveIntervalSec": DEFAULT_VISUAL_INTERVAL_SEC,
        "deltaThreshold": DEFAULT_VISUAL_DELTA_THRESHOLD,
        "width": DEFAULT_VISUAL_WIDTH,
        "height": DEFAULT_VISUAL_HEIGHT,
        "sentinels": [],
        "activeSegments": [],
        "counts": {
            "requestedSentinels": 0,
            "completedSentinels": 0,
            "failedSentinels": 0,
            "activeTransitions": 0,
        },
        "warnings": [],
    }


def empty_activity_summary(duration_sec: float | None) -> dict[str, Any]:
    duration = float(duration_sec) if isinstance(duration_sec, (int, float)) and duration_sec > 0 else 0.0
    return {
        "strategy": "audio_speech_activity_plus_visual_sentinel",
        "activeSegments": [],
        "inactiveSegments": [{"startSec": 0.0, "endSec": round(duration, 3), "durationSec": round(duration, 3)}] if duration else [],
        "activeSec": 0.0,
        "inactiveSec": round(duration, 3),
        "activeRatio": 0.0,
        "inactiveRatio": 1.0 if duration else 0.0,
        "estimatedReductionRatio": None,
        "counts": {
            "activeSegments": 0,
            "inactiveSegments": 1 if duration else 0,
            "audioActiveSegments": 0,
            "visualActiveSegments": 0,
            "visualSentinels": 0,
        },
        "notes": [],
    }


def audio_activity_segments(audio_analysis: dict[str, Any] | None, duration_sec: float) -> dict[str, Any]:
    result = empty_audio_activity()
    if not audio_analysis:
        result["warnings"].append("audio_analysis_missing")
        return result
    speech_activity = audio_analysis.get("speechActivity") if isinstance(audio_analysis.get("speechActivity"), dict) else {}
    candidates = [
        normalize_segment(candidate.get("startSec"), candidate.get("endSec"), duration_sec)
        for candidate in speech_activity.get("speechCandidates", [])
        if isinstance(candidate, dict)
    ]
    candidates = [segment for segment in candidates if segment is not None]
    active_segments = merge_segments(
        [
            {
                "startSec": max(0.0, segment["startSec"] - DEFAULT_AUDIO_PADDING_SEC),
                "endSec": min(duration_sec, segment["endSec"] + DEFAULT_AUDIO_PADDING_SEC),
            }
            for segment in candidates
        ],
        max_gap_sec=DEFAULT_AUDIO_MERGE_GAP_SEC,
        duration_sec=duration_sec,
    )
    result.update(
        {
            "available": True,
            "speechCandidates": len(candidates),
            "rawActiveSec": round(segment_total(candidates), 3),
            "activeSegments": active_segments,
        }
    )
    return result


def visual_activity_segments(source_path: str, duration_sec: float, ffmpeg_bin: str) -> dict[str, Any]:
    result = empty_visual_activity()
    interval_sec = effective_visual_interval(duration_sec)
    result["effectiveIntervalSec"] = interval_sec
    times = visual_sentinel_times(duration_sec, interval_sec)
    result["counts"]["requestedSentinels"] = len(times)
    previous_frame: bytes | None = None
    active_segments: list[dict[str, float]] = []

    for index, time_sec in enumerate(times):
        frame_result = run_ffmpeg_gray_frame(
            source_path=source_path,
            time_sec=time_sec,
            width=DEFAULT_VISUAL_WIDTH,
            height=DEFAULT_VISUAL_HEIGHT,
            ffmpeg_bin=ffmpeg_bin,
        )
        sentinel = {
            "index": index,
            "timeSec": round(time_sec, 3),
            "ok": frame_result["ok"],
            "deltaFromPrevious": None,
            "activeTransition": False,
            "command": frame_result["command"],
            "error": frame_result["error"],
        }
        if not frame_result["ok"]:
            result["warnings"].append(f"visual_sentinel_failed:{time_sec:.3f}:{frame_result['error']}")
            result["sentinels"].append(sentinel)
            continue

        frame = frame_result["frame"]
        delta = mean_abs_delta(previous_frame, frame) if previous_frame is not None else None
        active = delta is not None and delta >= DEFAULT_VISUAL_DELTA_THRESHOLD
        sentinel["deltaFromPrevious"] = round(delta, 6) if delta is not None else None
        sentinel["activeTransition"] = active
        if active:
            active_segments.append(
                {
                    "startSec": max(0.0, time_sec - interval_sec),
                    "endSec": min(duration_sec, time_sec + interval_sec),
                    "reason": "visual_frame_delta",
                    "deltaFromPrevious": round(delta, 6),
                }
            )
        result["sentinels"].append(sentinel)
        previous_frame = frame

    completed = sum(1 for sentinel in result["sentinels"] if sentinel["ok"])
    failed = len(result["sentinels"]) - completed
    active_segments = merge_segments(active_segments, max_gap_sec=0.0, duration_sec=duration_sec)
    result["available"] = completed > 0
    result["activeSegments"] = active_segments
    result["counts"] = {
        "requestedSentinels": len(times),
        "completedSentinels": completed,
        "failedSentinels": failed,
        "activeTransitions": sum(1 for sentinel in result["sentinels"] if sentinel["activeTransition"]),
    }
    return result


def effective_visual_interval(duration_sec: float) -> float:
    if duration_sec <= 0:
        return DEFAULT_VISUAL_INTERVAL_SEC
    return max(DEFAULT_VISUAL_INTERVAL_SEC, duration_sec / MAX_VISUAL_SENTINELS)


def visual_sentinel_times(duration_sec: float, interval_sec: float) -> list[float]:
    if duration_sec <= 0:
        return []
    times: list[float] = []
    cursor = 0.0
    while cursor < duration_sec and len(times) < MAX_VISUAL_SENTINELS:
        times.append(round(cursor, 3))
        cursor += interval_sec
    return times


def run_ffmpeg_gray_frame(
    *,
    source_path: str,
    time_sec: float,
    width: int,
    height: int,
    ffmpeg_bin: str,
) -> dict[str, Any]:
    command = command_prefix(ffmpeg_bin) + [
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{time_sec:.3f}",
        "-i",
        source_path,
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=FRAME_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "frame": b"", "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "frame": b"", "error": "ffmpeg visual sentinel timed out"}

    expected_bytes = width * height
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip() or f"ffmpeg exited with {completed.returncode}"
        return {"ok": False, "command": command, "frame": b"", "error": error}
    if len(completed.stdout) < expected_bytes:
        return {"ok": False, "command": command, "frame": b"", "error": "visual sentinel frame data missing"}
    return {"ok": True, "command": command, "frame": completed.stdout[:expected_bytes], "error": None}


def mean_abs_delta(previous: bytes | None, current: bytes) -> float | None:
    if previous is None or not previous or not current or len(previous) != len(current):
        return None
    return sum(abs(left - right) for left, right in zip(previous, current)) / (len(current) * 255.0)


def normalize_segment(start: Any, end: Any, duration_sec: float) -> dict[str, float] | None:
    try:
        start_sec = max(0.0, float(start))
        end_sec = min(duration_sec, float(end))
    except (TypeError, ValueError):
        return None
    if end_sec <= start_sec:
        return None
    return {
        "startSec": round(start_sec, 3),
        "endSec": round(end_sec, 3),
        "durationSec": round(end_sec - start_sec, 3),
    }


def merge_segments(
    segments: list[dict[str, Any]],
    *,
    max_gap_sec: float,
    duration_sec: float,
) -> list[dict[str, float]]:
    normalized = [
        normalize_segment(segment.get("startSec"), segment.get("endSec"), duration_sec)
        for segment in segments
        if isinstance(segment, dict)
    ]
    ordered = sorted((segment for segment in normalized if segment is not None), key=lambda item: item["startSec"])
    merged: list[dict[str, float]] = []
    for segment in ordered:
        if not merged or segment["startSec"] - merged[-1]["endSec"] > max_gap_sec:
            merged.append({"startSec": segment["startSec"], "endSec": segment["endSec"]})
            continue
        merged[-1]["endSec"] = max(merged[-1]["endSec"], segment["endSec"])
    return [with_duration(segment) for segment in merged]


def inactive_segments_from_active(active_segments: list[dict[str, Any]], duration_sec: float) -> list[dict[str, float]]:
    inactive: list[dict[str, float]] = []
    cursor = 0.0
    for segment in active_segments:
        start = float(segment["startSec"])
        end = float(segment["endSec"])
        if start > cursor:
            inactive.append(with_duration({"startSec": cursor, "endSec": start}))
        cursor = max(cursor, end)
    if cursor < duration_sec:
        inactive.append(with_duration({"startSec": cursor, "endSec": duration_sec}))
    return inactive


def with_duration(segment: dict[str, Any]) -> dict[str, float]:
    start = round(float(segment["startSec"]), 3)
    end = round(float(segment["endSec"]), 3)
    return {
        "startSec": start,
        "endSec": end,
        "durationSec": round(max(0.0, end - start), 3),
    }


def segment_total(segments: list[dict[str, Any]]) -> float:
    return sum(float(segment.get("durationSec", float(segment["endSec"]) - float(segment["startSec"]))) for segment in segments)


def read_optional_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except json.JSONDecodeError:
        return None, f"invalid_json:{path.name}"
    if not isinstance(payload, dict):
        return None, f"json_root_not_object:{path.name}"
    return payload, None


def write_activity_map(record: dict[str, Any], path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record
