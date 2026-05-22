from __future__ import annotations

from math import ceil, sqrt
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from . import __version__
from .discovery import VideoFile, resolve_configured_path
from .probe import analysis_source_path, command_prefix, probe_video_files, utc_now_iso
from .settings import PRODUCT_NAME


FRAME_SAMPLES_SCHEMA_VERSION = "timeline_for_video.frame_samples.v1"
SAMPLE_RESULT_SCHEMA_VERSION = "timeline_for_video.sample_result.v1"
PIPELINE_VERSION = "timeline_for_video.pipeline.m4"
DEFAULT_SAMPLES_PER_VIDEO = 5
MAX_SAMPLES_PER_VIDEO = 12
DEFAULT_MAX_ITEMS = 1
CONTACT_SHEET_THUMB_WIDTH = 320
CONTACT_SHEET_THUMB_HEIGHT = 180


def ffmpeg_version(ffmpeg_bin: str = "ffmpeg") -> dict[str, Any]:
    command = command_prefix(ffmpeg_bin) + ["-version"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "versionLine": None, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "versionLine": None, "error": "ffmpeg -version timed out"}

    output = (completed.stdout or completed.stderr).splitlines()
    version_line = output[0] if output else None
    return {
        "ok": completed.returncode == 0,
        "command": command,
        "versionLine": version_line,
        "error": None if completed.returncode == 0 else completed.stderr.strip(),
    }


def compute_sample_times(duration_sec: float | None, samples_per_video: int) -> list[float]:
    sample_count = normalize_samples_per_video(samples_per_video)
    if duration_sec is None or duration_sec <= 0:
        return [0.0]
    return [round(((index + 1) * duration_sec) / (sample_count + 1), 3) for index in range(sample_count)]


def normalize_samples_per_video(value: int) -> int:
    if value < 1:
        raise ValueError("samples_per_video must be at least 1")
    if value > MAX_SAMPLES_PER_VIDEO:
        raise ValueError(f"samples_per_video must be {MAX_SAMPLES_PER_VIDEO} or less")
    return value


def run_ffmpeg_frame_extract(
    source_path: str,
    output_path: Path,
    time_sec: float,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
        "-q:v",
        "2",
        "-y",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "error": "ffmpeg frame extraction timed out"}

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f"ffmpeg exited with {completed.returncode}"
        return {"ok": False, "command": command, "error": error}

    return {"ok": output_path.exists(), "command": command, "error": None if output_path.exists() else "frame missing"}


def run_ffmpeg_contact_sheet(
    frame_paths: list[Path],
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[str, Any]:
    if not frame_paths:
        return {"ok": False, "command": [], "error": "no frames available for contact sheet"}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = command_prefix(ffmpeg_bin) + ["-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for frame_path in frame_paths:
        command += ["-i", str(frame_path)]

    filter_complex, output_label = build_contact_sheet_filter(len(frame_paths))
    command += ["-filter_complex", filter_complex, "-map", output_label, "-frames:v", "1", str(output_path)]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "error": "ffmpeg contact sheet generation timed out"}

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f"ffmpeg exited with {completed.returncode}"
        return {"ok": False, "command": command, "error": error}

    return {"ok": output_path.exists(), "command": command, "error": None if output_path.exists() else "contact sheet missing"}


def build_contact_sheet_filter(frame_count: int) -> tuple[str, str]:
    labels: list[str] = []
    parts: list[str] = []
    for index in range(frame_count):
        label = f"t{index}"
        labels.append(f"[{label}]")
        parts.append(
            f"[{index}:v]"
            f"scale={CONTACT_SHEET_THUMB_WIDTH}:{CONTACT_SHEET_THUMB_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={CONTACT_SHEET_THUMB_WIDTH}:{CONTACT_SHEET_THUMB_HEIGHT}:(ow-iw)/2:(oh-ih)/2:white"
            f"[{label}]"
        )

    if frame_count == 1:
        return parts[0], "[t0]"

    columns = ceil(sqrt(frame_count))
    layout_parts: list[str] = []
    for index in range(frame_count):
        row = index // columns
        column = index % columns
        layout_parts.append(f"{column * CONTACT_SHEET_THUMB_WIDTH}_{row * CONTACT_SHEET_THUMB_HEIGHT}")

    parts.append(
        f"{''.join(labels)}xstack=inputs={frame_count}:layout={'|'.join(layout_parts)}:fill=white[out]"
    )
    return ";".join(parts), "[out]"


def sample_video_files(
    video_files: list[VideoFile],
    output_root_text: str,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    max_items: int = DEFAULT_MAX_ITEMS,
    samples_per_video: int = DEFAULT_SAMPLES_PER_VIDEO,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if max_items < 1:
        raise ValueError("max_items must be at least 1")
    samples_per_video = normalize_samples_per_video(samples_per_video)

    generated_at = utc_now_iso()
    output_root = resolve_configured_path(output_root_text)
    probe_result = probe_video_files(
        video_files,
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        output_root_text=output_root_text,
        max_items=max_items,
    )
    ffmpeg_status = ffmpeg_version(ffmpeg_bin)
    records: list[dict[str, Any]] = []

    total = len(probe_result["records"])
    for index, probe_record in enumerate(probe_result["records"], start=1):
        emit_progress(
            progress_callback,
            total=total,
            items_done=index - 1,
            item_stage="sample_frames",
            current_item=str(probe_record.get("sourceIdentity", {}).get("sourcePath") or probe_record.get("itemId") or ""),
            message="Sampling video frames.",
        )
        records.append(
            sample_probe_record(
                probe_record,
                output_root,
                output_root_text,
                ffmpeg_status,
                ffmpeg_bin,
                samples_per_video,
                generated_at,
            )
        )
        emit_progress(
            progress_callback,
            total=total,
            items_done=index,
            item_stage="completed",
            current_item=str(probe_record.get("sourceIdentity", {}).get("sourcePath") or probe_record.get("itemId") or ""),
            message="Sampled video frames.",
        )

    failed_items = sum(1 for record in records if not record["ok"])
    extracted_frames = sum(record["counts"]["extractedFrames"] for record in records)
    failed_frames = sum(record["counts"]["failedFrames"] for record in records)
    return {
        "schemaVersion": SAMPLE_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ok": failed_items == 0,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "samplingParameters": {
            "strategy": "evenly_spaced_bounded",
            "maxItems": max_items,
            "samplesPerVideo": samples_per_video,
            "maxSamplesPerVideo": MAX_SAMPLES_PER_VIDEO,
        },
        "ffmpegVersion": ffmpeg_status,
        "ffprobeVersion": probe_result["ffprobeVersion"],
        "counts": {
            "discoveredFiles": len(video_files),
            "sampledItems": len(records),
            "failedItems": failed_items,
            "extractedFrames": extracted_frames,
            "failedFrames": failed_frames,
            "skippedByMaxItems": max(len(video_files) - len(records), 0),
        },
        "records": records,
    }


def sample_probe_record(
    probe_record: dict[str, Any],
    output_root: Path,
    output_root_text: str,
    ffmpeg_status: dict[str, Any],
    ffmpeg_bin: str,
    samples_per_video: int,
    generated_at: str,
) -> dict[str, Any]:
    item_id = probe_record["itemId"]
    item_root = output_root / "items" / item_id
    raw_outputs_dir = item_root / "raw_outputs"
    artifacts_dir = item_root / "artifacts"
    frames_dir = artifacts_dir / "frames"
    frame_samples_path = raw_outputs_dir / "frame_samples.json"
    contact_sheet_path = artifacts_dir / "contact_sheet.jpg"
    warnings: list[str] = []

    record = {
        "schemaVersion": FRAME_SAMPLES_SCHEMA_VERSION,
        "itemId": item_id,
        "generatedAt": generated_at,
        "ok": False,
        "sourceIdentity": probe_record["sourceIdentity"],
        "sourceFingerprint": probe_record["sourceFingerprint"],
        "sourceVideoModified": False,
        "samplingParameters": {
            "strategy": "evenly_spaced_bounded",
            "samplesPerVideo": samples_per_video,
        },
        "outputs": {
            "itemRoot": str(item_root),
            "rawOutputsDir": str(raw_outputs_dir),
            "frameSamplesJson": str(frame_samples_path),
            "framesDir": str(frames_dir),
            "contactSheet": str(contact_sheet_path),
            "outputRootConfiguredPath": output_root_text,
        },
        "ffprobe": {
            "ok": probe_record["ffprobe"]["ok"],
            "summary": probe_record["ffprobe"]["summary"],
            "error": probe_record["ffprobe"]["error"],
        },
        "ffmpeg": {
            "version": ffmpeg_status,
        },
        "frames": [],
        "contactSheet": {
            "ok": False,
            "outputPath": str(contact_sheet_path),
            "command": [],
            "error": None,
        },
        "counts": {
            "requestedFrames": 0,
            "extractedFrames": 0,
            "failedFrames": 0,
        },
        "warnings": warnings,
    }

    if not probe_record["ffprobe"]["ok"]:
        warnings.append("ffprobe_failed")
        record["contactSheet"]["error"] = "ffprobe failed"
        return write_frame_samples(record, frame_samples_path)

    if not ffmpeg_status["ok"]:
        warnings.append("ffmpeg_unavailable")
        record["contactSheet"]["error"] = ffmpeg_status["error"] or "ffmpeg is not available"
        return write_frame_samples(record, frame_samples_path)

    duration_sec = None
    summary = probe_record["ffprobe"]["summary"]
    if summary:
        duration_sec = summary["format"]["durationSec"]
    sample_times = compute_sample_times(duration_sec, samples_per_video)
    record["samplingParameters"]["timesSec"] = sample_times
    record["counts"]["requestedFrames"] = len(sample_times)

    extracted_paths: list[Path] = []
    for index, time_sec in enumerate(sample_times, start=1):
        output_path = frames_dir / f"frame-{index:06d}.jpg"
        extract_result = run_ffmpeg_frame_extract(
            analysis_source_path(probe_record),
            output_path,
            time_sec,
            ffmpeg_bin,
        )
        frame_record = {
            "index": index,
            "frameId": f"frame-{index:06d}",
            "timeSec": time_sec,
            "ok": extract_result["ok"],
            "outputPath": str(output_path),
            "command": extract_result["command"],
            "error": extract_result["error"],
        }
        record["frames"].append(frame_record)
        if extract_result["ok"]:
            extracted_paths.append(output_path)

    record["counts"]["extractedFrames"] = len(extracted_paths)
    record["counts"]["failedFrames"] = len(sample_times) - len(extracted_paths)
    if record["counts"]["failedFrames"]:
        warnings.append("frame_extraction_failed")

    if extracted_paths:
        contact_result = run_ffmpeg_contact_sheet(extracted_paths, contact_sheet_path, ffmpeg_bin)
        record["contactSheet"].update(contact_result)
        if not contact_result["ok"]:
            warnings.append("contact_sheet_failed")
    else:
        record["contactSheet"]["error"] = "no extracted frames"
        warnings.append("no_extracted_frames")

    record["ok"] = (
        record["counts"]["requestedFrames"] > 0
        and record["counts"]["failedFrames"] == 0
        and record["contactSheet"]["ok"]
    )
    return write_frame_samples(record, frame_samples_path)


def emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    total: int,
    items_done: int,
    item_stage: str,
    current_item: str,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "total": total,
            "itemsDone": items_done,
            "itemStage": item_stage,
            "currentItem": current_item,
            "message": message,
        }
    )


def write_frame_samples(record: dict[str, Any], frame_samples_path: Path) -> dict[str, Any]:
    frame_samples_path.parent.mkdir(parents=True, exist_ok=True)
    frame_samples_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return record
