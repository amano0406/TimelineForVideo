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
from .discovery import VideoFile, display_path
from .settings import PRODUCT_NAME


PROBE_RECORD_SCHEMA_VERSION = "timeline_for_video.probe_record.v1"
SOURCE_IDENTITY_SCHEMA_VERSION = "timeline_for_video.source_identity.v1"
SOURCE_FINGERPRINT_ALGORITHM = "source-stat-v1"
PIPELINE_VERSION = "timeline_for_video.pipeline.m3"


@dataclass(frozen=True)
class FfprobeRun:
    ok: bool
    command: list[str]
    raw: dict[str, Any] | None = None
    error: str | None = None


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


def build_probe_record(
    video_file: VideoFile,
    ffprobe_run: FfprobeRun,
    version_info: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    identity = source_identity(video_file)
    fingerprint = source_fingerprint(identity)
    item_id = item_id_from_fingerprint(fingerprint)
    generated_at = generated_at or utc_now_iso()
    summary = ffprobe_summary(ffprobe_run.raw) if ffprobe_run.raw else None
    warnings = [] if ffprobe_run.ok else ["ffprobe_failed"]

    return {
        "schemaVersion": PROBE_RECORD_SCHEMA_VERSION,
        "itemId": item_id,
        "recordId": item_id,
        "generatedAt": generated_at,
        "sourceIdentity": identity,
        "sourceFingerprint": fingerprint,
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
    max_items: int | None = None,
) -> dict[str, Any]:
    selected_files = video_files[:max_items] if max_items is not None else video_files
    generated_at = utc_now_iso()
    version_info = ffprobe_version(ffprobe_bin)
    records: list[dict[str, Any]] = []

    for video_file in selected_files:
        if version_info["ok"]:
            ffprobe_run = run_ffprobe(video_file.resolved_path, ffprobe_bin)
        else:
            ffprobe_run = FfprobeRun(
                ok=False,
                command=version_info["command"],
                error=version_info["error"] or "ffprobe is not available",
            )
        records.append(build_probe_record(video_file, ffprobe_run, version_info, generated_at))

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
