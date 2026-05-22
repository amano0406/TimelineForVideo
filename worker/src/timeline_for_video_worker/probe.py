from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from . import __version__
from .discovery import VideoFile, display_path, resolve_configured_path
from .settings import PRODUCT_NAME


PROBE_RECORD_SCHEMA_VERSION = "timeline_for_video.probe_record.v1"
SOURCE_IDENTITY_SCHEMA_VERSION = "timeline_for_video.source_identity.v1"
MEDIA_NORMALIZATION_SCHEMA_VERSION = "timeline_for_video.media_normalization.v1"
SOURCE_FINGERPRINT_ALGORITHM = "source-stat-v1"
PIPELINE_VERSION = "timeline_for_video.pipeline.m4"
NORMALIZED_MEDIA_DIR_NAME = "normalized_media"
NORMALIZED_MEDIA_FILE_NAME = "source.remux.mkv"
MIN_REMUX_TIMEOUT_SEC = 180
MAX_REMUX_TIMEOUT_SEC = 3600
REMUX_TIMEOUT_SIZE_DIVISOR_BYTES = 5 * 1024 * 1024
REMUX_TIMEOUT_MARGIN_SEC = 120


@dataclass(frozen=True)
class FfprobeRun:
    ok: bool
    command: list[str]
    raw: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class MediaNormalizationResult:
    ffprobe_run: FfprobeRun
    media_normalization: dict[str, Any]
    analysis_input: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def command_prefix(command: str) -> list[str]:
    if os.name == "nt":
        return [_strip_wrapping_quotes(part) for part in shlex.split(command, posix=False)]
    return shlex.split(command)


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def ffprobe_version(ffprobe_bin: str = "ffprobe") -> dict[str, Any]:
    command = command_prefix(ffprobe_bin) + ["-version"]
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
        return {"ok": False, "command": command, "versionLine": None, "error": "ffprobe -version timed out"}

    output = (completed.stdout or completed.stderr).splitlines()
    version_line = output[0] if output else None
    return {
        "ok": completed.returncode == 0,
        "command": command,
        "versionLine": version_line,
        "error": None if completed.returncode == 0 else completed.stderr.strip(),
    }


def run_ffprobe(source_path: str, ffprobe_bin: str = "ffprobe") -> FfprobeRun:
    command = command_prefix(ffprobe_bin) + [
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        source_path,
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
        return FfprobeRun(ok=False, command=command, error=str(exc))
    except subprocess.TimeoutExpired:
        return FfprobeRun(ok=False, command=command, error="ffprobe timed out")

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f"ffprobe exited with {completed.returncode}"
        return FfprobeRun(ok=False, command=command, error=error)

    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return FfprobeRun(ok=False, command=command, error=f"ffprobe returned invalid JSON: {exc}")

    if not isinstance(raw, dict):
        return FfprobeRun(ok=False, command=command, error="ffprobe JSON root was not an object")

    return FfprobeRun(ok=True, command=command, raw=raw)


def source_identity(video_file: VideoFile) -> dict[str, Any]:
    path = Path(video_file.resolved_path)
    stat_result = path.stat()
    modified_time = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat()
    return {
        "schemaVersion": SOURCE_IDENTITY_SCHEMA_VERSION,
        "sourcePath": display_path(path),
        "resolvedPath": str(path),
        "inputRoot": video_file.input_root,
        "extension": path.suffix.casefold(),
        "sizeBytes": stat_result.st_size,
        "modifiedTime": modified_time,
        "modifiedTimeNs": stat_result.st_mtime_ns,
        "fileSystem": {
            "device": str(getattr(stat_result, "st_dev", "")),
            "inode": str(getattr(stat_result, "st_ino", "")),
        },
    }


def source_fingerprint(identity: dict[str, Any]) -> dict[str, Any]:
    material = {
        "algorithm": SOURCE_FINGERPRINT_ALGORITHM,
        "sourcePath": identity["sourcePath"],
        "sizeBytes": identity["sizeBytes"],
        "modifiedTimeNs": identity["modifiedTimeNs"],
    }
    value = "sha256:" + sha256_hex(canonical_json(material))
    return {
        "algorithm": SOURCE_FINGERPRINT_ALGORITHM,
        "value": value,
        "material": material,
        "contentHash": {
            "computed": False,
            "reason": "not_computed_by_default_for_large_video_safety",
        },
    }


def item_id_from_fingerprint(fingerprint: dict[str, Any]) -> str:
    digest = sha256_hex(fingerprint["value"])
    return f"video-{digest[:16]}"


def parse_duration(value: Any) -> float | None:
    if value in (None, "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ffprobe_summary(raw: dict[str, Any]) -> dict[str, Any]:
    format_info = raw.get("format") if isinstance(raw.get("format"), dict) else {}
    streams = raw.get("streams") if isinstance(raw.get("streams"), list) else []
    stream_summaries: list[dict[str, Any]] = []

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        stream_summaries.append(
            {
                "index": stream.get("index"),
                "codecType": stream.get("codec_type"),
                "codecName": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "durationSec": parse_duration(stream.get("duration")),
                "sampleRate": stream.get("sample_rate"),
                "channels": stream.get("channels"),
            }
        )

    return {
        "format": {
            "formatName": format_info.get("format_name"),
            "formatLongName": format_info.get("format_long_name"),
            "durationSec": parse_duration(format_info.get("duration")),
            "sizeBytes": int(format_info["size"]) if str(format_info.get("size", "")).isdigit() else None,
            "bitRate": int(format_info["bit_rate"]) if str(format_info.get("bit_rate", "")).isdigit() else None,
        },
        "streams": stream_summaries,
        "counts": {
            "streams": len(stream_summaries),
            "videoStreams": sum(1 for stream in stream_summaries if stream["codecType"] == "video"),
            "audioStreams": sum(1 for stream in stream_summaries if stream["codecType"] == "audio"),
            "subtitleStreams": sum(1 for stream in stream_summaries if stream["codecType"] == "subtitle"),
        },
    }


def summary_duration_sec(summary: dict[str, Any] | None) -> float | None:
    if not summary:
        return None
    format_info = summary.get("format") if isinstance(summary.get("format"), dict) else {}
    duration_sec = format_info.get("durationSec")
    return duration_sec if isinstance(duration_sec, (int, float)) and duration_sec > 0 else None


def ffprobe_run_duration_sec(ffprobe_run: FfprobeRun) -> float | None:
    if not ffprobe_run.ok or not ffprobe_run.raw:
        return None
    return summary_duration_sec(ffprobe_summary(ffprobe_run.raw))


def original_analysis_input(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "original_source",
        "resolvedPath": identity["resolvedPath"],
        "sourcePath": identity["sourcePath"],
        "sourceVideoModified": False,
        "mediaNormalizationApplied": False,
    }


def normalized_analysis_input(identity: dict[str, Any], normalized_path: Path) -> dict[str, Any]:
    return {
        "kind": "normalized_media",
        "resolvedPath": str(normalized_path),
        "sourcePath": display_path(normalized_path),
        "originalSourcePath": identity["sourcePath"],
        "sourceVideoModified": False,
        "mediaNormalizationApplied": True,
    }


def analysis_source_path(probe_record: dict[str, Any]) -> str:
    analysis_input = probe_record.get("analysisInput") if isinstance(probe_record.get("analysisInput"), dict) else {}
    return str(analysis_input.get("resolvedPath") or probe_record["sourceIdentity"]["resolvedPath"])


def media_normalization_not_attempted(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": MEDIA_NORMALIZATION_SCHEMA_VERSION,
        "attempted": False,
        "ok": False,
        "reason": "",
        "strategy": "remux_copy_when_duration_missing",
        "sourcePath": identity["sourcePath"],
        "sourceVideoModified": False,
        "normalizedPath": "",
        "cached": False,
        "command": [],
        "timeoutSec": 0,
        "error": None,
        "warnings": [],
    }


def remux_timeout_seconds(source_size_bytes: int | None) -> int:
    if isinstance(source_size_bytes, int) and source_size_bytes > 0:
        scaled_by_size = int(source_size_bytes / REMUX_TIMEOUT_SIZE_DIVISOR_BYTES) + REMUX_TIMEOUT_MARGIN_SEC
        return min(MAX_REMUX_TIMEOUT_SEC, max(MIN_REMUX_TIMEOUT_SEC, scaled_by_size))
    return MIN_REMUX_TIMEOUT_SEC


def normalized_media_path(output_root_text: str, item_id: str) -> Path:
    output_root = resolve_configured_path(output_root_text)
    return output_root / "items" / item_id / "artifacts" / NORMALIZED_MEDIA_DIR_NAME / NORMALIZED_MEDIA_FILE_NAME


def run_remux_copy(
    source_path: str,
    normalized_path: Path,
    ffmpeg_bin: str,
    source_size_bytes: int | None,
) -> dict[str, Any]:
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_sec = remux_timeout_seconds(source_size_bytes)
    command = command_prefix(ffmpeg_bin) + [
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts",
        "-i",
        source_path,
        "-map",
        "0",
        "-c",
        "copy",
        "-y",
        str(normalized_path),
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_sec)
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "timeoutSec": timeout_sec, "error": str(exc)}
    except subprocess.TimeoutExpired:
        remove_partial_file(normalized_path)
        return {"ok": False, "command": command, "timeoutSec": timeout_sec, "error": "ffmpeg remux timed out"}

    if completed.returncode != 0:
        remove_partial_file(normalized_path)
        return {
            "ok": False,
            "command": command,
            "timeoutSec": timeout_sec,
            "error": completed.stderr.strip() or completed.stdout.strip() or f"ffmpeg exited with {completed.returncode}",
        }
    return {
        "ok": normalized_path.exists(),
        "command": command,
        "timeoutSec": timeout_sec,
        "error": None if normalized_path.exists() else "normalized media missing",
    }


def remove_partial_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def normalize_media_when_duration_missing(
    *,
    video_file: VideoFile,
    original_ffprobe_run: FfprobeRun,
    identity: dict[str, Any],
    item_id: str,
    output_root_text: str | None,
    ffprobe_bin: str,
    ffmpeg_bin: str,
) -> MediaNormalizationResult:
    analysis_input = original_analysis_input(identity)
    media_normalization = media_normalization_not_attempted(identity)
    if not original_ffprobe_run.ok or ffprobe_run_duration_sec(original_ffprobe_run) is not None:
        return MediaNormalizationResult(original_ffprobe_run, media_normalization, analysis_input)

    if not output_root_text:
        media_normalization = {
            **media_normalization,
            "attempted": False,
            "reason": "duration_missing_without_output_root",
            "warnings": ["duration_missing_without_media_normalization"],
        }
        return MediaNormalizationResult(original_ffprobe_run, media_normalization, analysis_input)

    normalized_path = normalized_media_path(output_root_text, item_id)
    media_normalization = {
        **media_normalization,
        "attempted": True,
        "reason": "duration_missing",
        "normalizedPath": str(normalized_path),
    }

    if normalized_path.exists():
        cached_probe = run_ffprobe(str(normalized_path), ffprobe_bin)
        if ffprobe_run_duration_sec(cached_probe) is not None:
            return MediaNormalizationResult(
                cached_probe,
                {
                    **media_normalization,
                    "ok": True,
                    "cached": True,
                    "warnings": ["duration_missing_resolved_by_cached_normalized_media"],
                },
                normalized_analysis_input(identity, normalized_path),
            )
        remove_partial_file(normalized_path)

    remux_result = run_remux_copy(
        video_file.resolved_path,
        normalized_path,
        ffmpeg_bin=ffmpeg_bin,
        source_size_bytes=identity.get("sizeBytes"),
    )
    media_normalization = {
        **media_normalization,
        "command": remux_result["command"],
        "timeoutSec": remux_result["timeoutSec"],
        "error": remux_result["error"],
    }
    if not remux_result["ok"]:
        return MediaNormalizationResult(
            original_ffprobe_run,
            {
                **media_normalization,
                "ok": False,
                "warnings": ["duration_missing_media_normalization_failed"],
            },
            analysis_input,
        )

    normalized_probe = run_ffprobe(str(normalized_path), ffprobe_bin)
    if ffprobe_run_duration_sec(normalized_probe) is None:
        return MediaNormalizationResult(
            original_ffprobe_run,
            {
                **media_normalization,
                "ok": False,
                "warnings": ["duration_missing_after_media_normalization"],
            },
            analysis_input,
        )

    return MediaNormalizationResult(
        normalized_probe,
        {
            **media_normalization,
            "ok": True,
            "warnings": ["duration_missing_resolved_by_media_normalization"],
        },
        normalized_analysis_input(identity, normalized_path),
    )


def build_probe_record(
    video_file: VideoFile,
    ffprobe_run: FfprobeRun,
    version_info: dict[str, Any],
    generated_at: str | None = None,
    media_normalization: dict[str, Any] | None = None,
    analysis_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = source_identity(video_file)
    fingerprint = source_fingerprint(identity)
    item_id = item_id_from_fingerprint(fingerprint)
    generated_at = generated_at or utc_now_iso()
    summary = ffprobe_summary(ffprobe_run.raw) if ffprobe_run.raw else None
    warnings = [] if ffprobe_run.ok else ["ffprobe_failed"]
    media_normalization = media_normalization or media_normalization_not_attempted(identity)
    analysis_input = analysis_input or original_analysis_input(identity)
    warnings.extend(str(warning) for warning in media_normalization.get("warnings", []))

    return {
        "schemaVersion": PROBE_RECORD_SCHEMA_VERSION,
        "itemId": item_id,
        "recordId": item_id,
        "generatedAt": generated_at,
        "sourceIdentity": identity,
        "sourceFingerprint": fingerprint,
        "analysisInput": analysis_input,
        "mediaNormalization": media_normalization,
        "ffprobe": {
            "ok": ffprobe_run.ok,
            "command": ffprobe_run.command,
            "version": version_info,
            "summary": summary,
            "raw": ffprobe_run.raw,
            "error": ffprobe_run.error,
        },
        "recordSeed": build_record_seed(item_id, identity, fingerprint, summary, generated_at, warnings),
        "convertInfoSeed": build_convert_info_seed(
            item_id,
            identity,
            fingerprint,
            version_info,
            generated_at,
            warnings,
        ),
    }


def build_record_seed(
    item_id: str,
    identity: dict[str, Any],
    fingerprint: dict[str, Any],
    summary: dict[str, Any] | None,
    generated_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "timeline_for_video.video_record.v1",
        "record_id": item_id,
        "asset": {
            "source_path": identity["sourcePath"],
            "source_fingerprint": fingerprint["value"],
            "source_video_modified": False,
        },
        "timeline": {
            "coordinate": "source_video_relative_time",
        },
        "video": {
            "format": summary["format"] if summary else None,
            "streams": [stream for stream in summary["streams"] if stream["codecType"] == "video"] if summary else [],
        },
        "audio": {
            "streams": [stream for stream in summary["streams"] if stream["codecType"] == "audio"] if summary else [],
        },
        "processing": {
            "stage": "ffprobe_metadata",
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": generated_at,
            "warnings": warnings,
        },
        "segments": [],
        "frames": [],
        "text": {
            "mode": "pending_frame_ocr_and_audio_reference",
        },
        "review": {},
    }


def build_convert_info_seed(
    item_id: str,
    identity: dict[str, Any],
    fingerprint: dict[str, Any],
    version_info: dict[str, Any],
    generated_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    generation_signature_material = {
        "itemId": item_id,
        "sourceFingerprint": fingerprint["value"],
        "pipelineVersion": PIPELINE_VERSION,
        "productVersion": __version__,
    }
    return {
        "product": {
            "name": PRODUCT_NAME,
            "version": __version__,
        },
        "generatedAt": generated_at,
        "sourceFingerprint": fingerprint,
        "sourceFileIdentity": identity,
        "ffprobeVersion": version_info,
        "pipelineVersion": PIPELINE_VERSION,
        "generationSignature": "sha256:" + sha256_hex(canonical_json(generation_signature_material)),
        "samplingParameters": None,
        "outputFiles": [],
        "counts": {},
        "warnings": warnings,
        "source_video_modified": False,
    }


def probe_video_files(
    video_files: list[VideoFile],
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    output_root_text: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    selected_files = video_files[:max_items] if max_items is not None else video_files
    generated_at = utc_now_iso()
    version_info = ffprobe_version(ffprobe_bin)
    records: list[dict[str, Any]] = []

    for video_file in selected_files:
        identity = source_identity(video_file)
        fingerprint = source_fingerprint(identity)
        item_id = item_id_from_fingerprint(fingerprint)
        if version_info["ok"]:
            ffprobe_run = run_ffprobe(video_file.resolved_path, ffprobe_bin)
        else:
            ffprobe_run = FfprobeRun(
                ok=False,
                command=version_info["command"],
                error=version_info["error"] or "ffprobe is not available",
            )
        normalized = normalize_media_when_duration_missing(
            video_file=video_file,
            original_ffprobe_run=ffprobe_run,
            identity=identity,
            item_id=item_id,
            output_root_text=output_root_text,
            ffprobe_bin=ffprobe_bin,
            ffmpeg_bin=ffmpeg_bin,
        )
        records.append(
            build_probe_record(
                video_file,
                normalized.ffprobe_run,
                version_info,
                generated_at,
                media_normalization=normalized.media_normalization,
                analysis_input=normalized.analysis_input,
            )
        )

    failed = sum(1 for record in records if not record["ffprobe"]["ok"])
    return {
        "schemaVersion": "timeline_for_video.probe_result.v1",
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ffprobeVersion": version_info,
        "counts": {
            "discoveredFiles": len(video_files),
            "probedFiles": len(records),
            "failedProbes": failed,
            "skippedByMaxItems": max(len(video_files) - len(records), 0),
        },
        "records": records,
    }
