from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
import time
from typing import Any

from . import __version__
from .activity_map import analyze_activity_files
from .discovery import (
    SUPPORTED_VIDEO_EXTENSIONS,
    assess_output_root,
    discover_video_files,
)
from .audio_analysis import analyze_audio_files
from .audio_models import AUDIO_MODEL_MODES, audio_model_runtime_status
from .frame_ocr import OCR_MODES, analyze_frame_ocr_outputs, ocr_runtime_status
from .items import download_items, list_items, remove_items
from .model_inventory import build_model_inventory
from .probe import ffprobe_version, probe_video_files
from .processor import list_runs as list_processor_runs
from .processor import refresh_configured_items, show_run as show_processor_run
from .sampling import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_SAMPLES_PER_VIDEO,
    MAX_SAMPLES_PER_VIDEO,
    ffmpeg_version,
    sample_video_files,
)
from .settings import (
    PRODUCT_NAME,
    SettingsError,
    load_example_settings,
    load_settings,
    redact_settings,
    save_settings,
    settings_example_path,
    settings_path,
    SUPPORTED_COMPUTE_MODES,
)


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_result(args: argparse.Namespace, payload: dict[str, Any], message: str) -> None:
    if getattr(args, "json", False):
        emit_json(payload)
        return
    print(message)


def env_optional_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return int(value)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def env_choice(name: str, default: str | None, choices: tuple[str, ...]) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return normalized


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be 1 or greater")
    return parsed


def paginate_rows(
    rows: list[dict[str, Any]],
    *,
    page: int | None,
    page_size: int | None,
    total_key: str,
    returned_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    if page is None and page_size is None:
        returned_rows = rows
        pagination = {
            "mode": "all",
            "page": None,
            "pageSize": None,
            "total": total,
            "totalPages": 1 if total else 0,
            "returned": total,
            "offset": 0,
            "rangeStart": 1 if total else 0,
            "rangeEnd": total,
            "hasPrevious": False,
            "hasNext": False,
        }
    else:
        effective_page = page or 1
        effective_page_size = page_size or 100
        start = (effective_page - 1) * effective_page_size
        end = start + effective_page_size
        returned_rows = rows[start:end] if start < total else []
        returned_count = len(returned_rows)
        pagination = {
            "mode": "page",
            "page": effective_page,
            "pageSize": effective_page_size,
            "total": total,
            "totalPages": (total + effective_page_size - 1) // effective_page_size if total else 0,
            "returned": returned_count,
            "offset": start,
            "rangeStart": start + 1 if returned_count else 0,
            "rangeEnd": start + returned_count if returned_count else 0,
            "hasPrevious": effective_page > 1 and total > 0,
            "hasNext": end < total,
        }
    pagination[total_key] = pagination["total"]
    pagination[returned_key] = pagination["returned"]
    return returned_rows, pagination


def page_summary(pagination: dict[str, Any], noun: str) -> str:
    if pagination["mode"] == "all":
        return f"Showing all {pagination['total']} {noun}(s)."
    return (
        f"Showing {pagination['rangeStart']}-{pagination['rangeEnd']} "
        f"of {pagination['total']} {noun}(s), "
        f"page {pagination['page']}/{pagination['totalPages']} "
        f"page-size={pagination['pageSize']}."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timeline-for-video",
        description="Local TimelineForVideo worker operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health", help="Check worker health.")
    health_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    health_parser.set_defaults(handler=handle_health)

    doctor_parser = subparsers.add_parser("doctor", help="Check runtime and configured paths.")
    doctor_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    doctor_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    doctor_parser.add_argument("--ocr-mode", choices=OCR_MODES, default="auto", help="OCR mode to check.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    doctor_parser.set_defaults(handler=handle_doctor)

    files_parser = subparsers.add_parser("files", help="Inspect source video files.")
    files_subparsers = files_parser.add_subparsers(dest="files_command", required=True)

    files_list_parser = files_subparsers.add_parser("list", help="List configured video files.")
    files_list_parser.add_argument("--page", type=positive_int, default=None, help="Return one result page.")
    files_list_parser.add_argument("--page-size", type=positive_int, default=None, help="Rows per result page.")
    files_list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    files_list_parser.set_defaults(handler=handle_files_list)

    probe_parser = subparsers.add_parser("probe", help="Read source video metadata with ffprobe.")
    probe_subparsers = probe_parser.add_subparsers(dest="probe_command", required=True)

    probe_list_parser = probe_subparsers.add_parser("list", help="Probe configured video files.")
    probe_list_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    probe_list_parser.add_argument("--max-items", type=int, default=None, help="Limit probed files.")
    probe_list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    probe_list_parser.set_defaults(handler=handle_probe_list)

    sample_parser = subparsers.add_parser("sample", help="Extract bounded review frames.")
    sample_subparsers = sample_parser.add_subparsers(dest="sample_command", required=True)

    sample_frames_parser = sample_subparsers.add_parser("frames", help="Extract bounded frame samples.")
    sample_frames_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    sample_frames_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    sample_frames_parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help=f"Limit sampled videos. Default: {DEFAULT_MAX_ITEMS}.",
    )
    sample_frames_parser.add_argument(
        "--samples-per-video",
        type=int,
        default=DEFAULT_SAMPLES_PER_VIDEO,
        help=f"Frames per video, 1-{MAX_SAMPLES_PER_VIDEO}. Default: {DEFAULT_SAMPLES_PER_VIDEO}.",
    )
    sample_frames_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    sample_frames_parser.set_defaults(handler=handle_sample_frames)

    ocr_parser = subparsers.add_parser("ocr", help="Run local OCR over generated frame samples.")
    ocr_subparsers = ocr_parser.add_subparsers(dest="ocr_command", required=True)

    ocr_frames_parser = ocr_subparsers.add_parser("frames", help="OCR generated frame samples.")
    ocr_frames_parser.add_argument("--max-items", type=int, default=None, help="Limit item folders.")
    ocr_frames_parser.add_argument(
        "--mode",
        choices=OCR_MODES,
        default="auto",
        help="OCR mode. Default: auto.",
    )
    ocr_frames_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    ocr_frames_parser.set_defaults(handler=handle_ocr_frames)

    audio_parser = subparsers.add_parser("audio", help="Analyze source-video audio as generated evidence.")
    audio_subparsers = audio_parser.add_subparsers(dest="audio_command", required=True)

    audio_analyze_parser = audio_subparsers.add_parser("analyze", help="Extract MP3 derivative and speech ranges.")
    audio_analyze_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    audio_analyze_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    audio_analyze_parser.add_argument("--max-items", type=int, default=None, help="Limit analyzed files.")
    audio_analyze_parser.add_argument(
        "--audio-model-mode",
        choices=AUDIO_MODEL_MODES,
        default=None,
        help="Audio model execution mode. Default: required.",
    )
    audio_analyze_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    audio_analyze_parser.set_defaults(handler=handle_audio_analyze)

    activity_parser = subparsers.add_parser("activity", help="Build source-safe activity maps.")
    activity_subparsers = activity_parser.add_subparsers(dest="activity_command", required=True)

    activity_map_parser = activity_subparsers.add_parser("map", help="Build activity maps from audio and visual sentinels.")
    activity_map_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    activity_map_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    activity_map_parser.add_argument("--max-items", type=int, default=None, help="Limit mapped files.")
    activity_map_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    activity_map_parser.set_defaults(handler=handle_activity_map)

    process_parser = subparsers.add_parser("process", help="Run sampling, OCR, audio, activity mapping, and item refresh.")
    process_subparsers = process_parser.add_subparsers(dest="process_command", required=True)

    process_all_parser = process_subparsers.add_parser("all", help="Run the full local video evidence pipeline.")
    process_all_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    process_all_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    process_all_parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help=f"Limit processed videos. Default: {DEFAULT_MAX_ITEMS}.",
    )
    process_all_parser.add_argument(
        "--samples-per-video",
        type=int,
        default=DEFAULT_SAMPLES_PER_VIDEO,
        help=f"Frames per video, 1-{MAX_SAMPLES_PER_VIDEO}. Default: {DEFAULT_SAMPLES_PER_VIDEO}.",
    )
    process_all_parser.add_argument(
        "--ocr-mode",
        choices=OCR_MODES,
        default="auto",
        help="Frame OCR mode. Default: auto.",
    )
    process_all_parser.add_argument(
        "--audio-model-mode",
        choices=AUDIO_MODEL_MODES,
        default=None,
        help="Audio model execution mode. Default: required.",
    )
    process_all_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    process_all_parser.set_defaults(handler=handle_process_all)

    models_parser = subparsers.add_parser("models", help="Inspect local and reference processing components.")
    models_subparsers = models_parser.add_subparsers(dest="models_command", required=True)

    models_list_parser = models_subparsers.add_parser("list", help="List processing components.")
    models_list_parser.add_argument(
        "--include-remote",
        "--remote",
        action="store_true",
        help="Fetch Hugging Face metadata such as license and gated status.",
    )
    models_list_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    models_list_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    models_list_parser.add_argument("--ocr-mode", choices=OCR_MODES, default="auto", help="OCR mode to check.")
    models_list_parser.add_argument("--output", type=Path, required=False, help="Write JSON payload to this path.")
    models_list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    models_list_parser.set_defaults(handler=handle_models_list)

    items_parser = subparsers.add_parser("items", help="Refresh and list item records.")
    items_subparsers = items_parser.add_subparsers(dest="items_command", required=True)

    items_refresh_parser = items_subparsers.add_parser("refresh", help="Process changed video items.")
    items_refresh_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    items_refresh_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    items_refresh_parser.add_argument("--max-items", type=int, default=None, help="Limit refreshed files.")
    items_refresh_parser.add_argument(
        "--samples-per-video",
        type=int,
        default=DEFAULT_SAMPLES_PER_VIDEO,
        help=f"Frames per video, 1-{MAX_SAMPLES_PER_VIDEO}. Default: {DEFAULT_SAMPLES_PER_VIDEO}.",
    )
    items_refresh_parser.add_argument("--ocr-mode", choices=OCR_MODES, default="auto", help="Frame OCR mode.")
    items_refresh_parser.add_argument(
        "--audio-model-mode",
        choices=AUDIO_MODEL_MODES,
        default=None,
        help="Audio model execution mode. Default: required.",
    )
    items_refresh_parser.add_argument("--reprocess-duplicates", action="store_true", help="Process items even when catalog state is current.")
    items_refresh_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    items_refresh_parser.set_defaults(handler=handle_items_refresh)

    items_list_parser = items_subparsers.add_parser("list", help="List refreshed item records.")
    items_list_parser.add_argument("--page", type=positive_int, default=None, help="Return one result page.")
    items_list_parser.add_argument("--page-size", type=positive_int, default=None, help="Rows per result page.")
    items_list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    items_list_parser.set_defaults(handler=handle_items_list)

    items_download_parser = items_subparsers.add_parser("download", help="Create a source-safe item ZIP.")
    items_download_parser.add_argument("--item-id", action="append", default=[], help="Item id to include. Repeat or comma-separate.")
    items_download_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    items_download_parser.set_defaults(handler=handle_items_download)

    items_remove_parser = items_subparsers.add_parser("remove", help="Remove generated item artifacts.")
    items_remove_parser.add_argument("--item-id", action="append", default=[], help="Item id to remove. Repeat or comma-separate.")
    items_remove_parser.add_argument("--dry-run", action="store_true", help="Report targets without deleting.")
    items_remove_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    items_remove_parser.set_defaults(handler=handle_items_remove)

    runs_parser = subparsers.add_parser("runs", help="Inspect worker runs.")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list_parser = runs_subparsers.add_parser("list", help="List worker runs.")
    runs_list_parser.add_argument("--limit", type=int, default=None, help="Limit returned runs.")
    runs_list_parser.add_argument("--page", type=positive_int, default=None, help="Return one result page.")
    runs_list_parser.add_argument("--page-size", type=positive_int, default=None, help="Rows per result page.")
    runs_list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    runs_list_parser.set_defaults(handler=handle_runs_list)
    runs_show_parser = runs_subparsers.add_parser("show", help="Show one worker run.")
    runs_show_parser.add_argument("--run-id", required=True, help="Run id.")
    runs_show_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    runs_show_parser.set_defaults(handler=handle_runs_show)

    serve_parser = subparsers.add_parser("serve", help="Run the resident processing worker.")
    serve_parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe command path.")
    serve_parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg command path.")
    serve_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.environ.get("TIMELINE_FOR_VIDEO_WORKER_INTERVAL_SECONDS", "60")),
    )
    serve_parser.add_argument(
        "--max-items",
        type=int,
        default=env_optional_int("TIMELINE_FOR_VIDEO_WORKER_MAX_ITEMS"),
        help="Limit items per refresh. Default: TIMELINE_FOR_VIDEO_WORKER_MAX_ITEMS or unlimited.",
    )
    serve_parser.add_argument(
        "--samples-per-video",
        type=int,
        default=env_int("TIMELINE_FOR_VIDEO_WORKER_SAMPLES_PER_VIDEO", DEFAULT_SAMPLES_PER_VIDEO),
        help=(
            f"Frames per video, 1-{MAX_SAMPLES_PER_VIDEO}. "
            f"Default: TIMELINE_FOR_VIDEO_WORKER_SAMPLES_PER_VIDEO or {DEFAULT_SAMPLES_PER_VIDEO}."
        ),
    )
    serve_parser.add_argument(
        "--ocr-mode",
        choices=OCR_MODES,
        default=env_choice("TIMELINE_FOR_VIDEO_WORKER_OCR_MODE", "auto", OCR_MODES),
        help="Frame OCR mode. Default: TIMELINE_FOR_VIDEO_WORKER_OCR_MODE or auto.",
    )
    serve_parser.add_argument(
        "--audio-model-mode",
        choices=AUDIO_MODEL_MODES,
        default=env_choice("TIMELINE_FOR_VIDEO_WORKER_AUDIO_MODEL_MODE", None, AUDIO_MODEL_MODES),
        help="Audio model execution mode. Default: TIMELINE_FOR_VIDEO_WORKER_AUDIO_MODEL_MODE or required.",
    )
    serve_parser.add_argument("--once", action="store_true", help="Run one refresh cycle and exit.")
    serve_parser.add_argument("--json", action="store_true", help="Emit JSON events.")
    serve_parser.set_defaults(handler=handle_serve)

    settings_parser = subparsers.add_parser("settings", help="Manage local settings.")
    settings_subparsers = settings_parser.add_subparsers(
        dest="settings_command",
        required=True,
    )

    init_parser = settings_subparsers.add_parser("init", help="Create settings.json.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing settings.")
    init_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    init_parser.set_defaults(handler=handle_settings_init)

    status_parser = settings_subparsers.add_parser("status", help="Show settings status.")
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    status_parser.set_defaults(handler=handle_settings_status)

    save_parser = settings_subparsers.add_parser("save", help="Update settings.json.")
    save_parser.add_argument(
        "--input-root",
        action="append",
        default=None,
        help="Input video root. Repeat to set multiple roots.",
    )
    save_parser.add_argument("--output-root", default=None, help="Output root.")
    save_parser.add_argument("--token", default=None, help="Hugging Face token for audio models.")
    save_parser.add_argument("--clear-token", action="store_true", help="Clear the stored Hugging Face token.")
    save_parser.add_argument(
        "--compute-mode",
        choices=SUPPORTED_COMPUTE_MODES,
        default=None,
        help="Audio model compute mode.",
    )
    save_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    save_parser.set_defaults(handler=handle_settings_save)

    return parser


def handle_health(args: argparse.Namespace) -> int:
    payload = {
        "ok": True,
        "product": PRODUCT_NAME,
        "version": __version__,
        "python": platform.python_version(),
        "inDocker": os.environ.get("TIMELINE_FOR_VIDEO_IN_DOCKER") == "1",
        "settingsPath": str(settings_path()),
    }
    emit_result(args, payload, f"{PRODUCT_NAME} worker OK")
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = [
        {
            "name": "runtime.python",
            "ok": True,
            "message": f"Python {platform.python_version()}",
        }
    ]

    target = settings_path()
    payload: dict[str, Any] = {
        "ok": False,
        "product": PRODUCT_NAME,
        "version": __version__,
        "settingsPath": str(target),
        "supportedExtensions": list(SUPPORTED_VIDEO_EXTENSIONS),
        "checks": checks,
    }

    if not target.exists():
        checks.append(
            {
                "name": "settings",
                "ok": False,
                "message": f"Settings file is missing: {target}",
            }
        )
        output_doctor(args, payload)
        return 1

    try:
        settings = load_settings(target)
    except SettingsError as exc:
        checks.append({"name": "settings", "ok": False, "message": str(exc)})
        output_doctor(args, payload)
        return 1

    checks.append({"name": "settings", "ok": True, "message": f"Settings file is valid: {target}"})
    ffprobe_status = ffprobe_version(args.ffprobe_bin)
    checks.append(
        {
            "name": "runtime.ffprobe",
            "ok": ffprobe_status["ok"],
            "message": ffprobe_message(ffprobe_status),
            "details": ffprobe_status,
        }
    )
    ffmpeg_status = ffmpeg_version(args.ffmpeg_bin)
    checks.append(
        {
            "name": "runtime.ffmpeg",
            "ok": ffmpeg_status["ok"],
            "message": ffprobe_message(ffmpeg_status),
            "details": ffmpeg_status,
        }
    )
    ocr_status = ocr_runtime_status(args.ocr_mode)
    checks.append(
        {
            "name": "runtime.ocr",
            "ok": ocr_status["ok"] or args.ocr_mode == "auto",
            "message": ocr_status["message"],
            "details": ocr_status,
        }
    )
    audio_model_status = audio_model_runtime_status(settings)
    audio_model_required = True
    checks.append(
        {
            "name": "runtime.audio_models",
            "ok": audio_model_status["ready"] or not audio_model_required,
            "message": audio_model_message(audio_model_status, audio_model_required),
            "details": audio_model_status,
        }
    )
    discovery = discover_video_files(settings)
    output_status = assess_output_root(settings["outputRoot"])

    for root in discovery.input_roots:
        root_ok = (
            root.exists
            and root.readable
            and root.kind in {"file", "directory"}
            and "unsupported_extension" not in root.warnings
        )
        checks.append(
            {
                "name": "input_root",
                "ok": root_ok,
                "message": input_root_message(root.to_dict()),
                "details": root.to_dict(),
            }
        )

    checks.append(
        {
            "name": "output_root",
            "ok": output_status["ok"],
            "message": output_root_message(output_status),
            "details": output_status,
        }
    )

    payload.update(
        {
            "ok": all(check["ok"] for check in checks),
            "settings": redact_settings(settings),
            "discovery": discovery.to_dict(),
            "outputRoot": output_status,
            "ffprobeVersion": ffprobe_status,
            "ffmpegVersion": ffmpeg_status,
            "ocr": ocr_status,
            "audioModels": audio_model_status,
        }
    )
    output_doctor(args, payload)
    return 0 if payload["ok"] else 1


def handle_files_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    discovery = discover_video_files(settings)
    discovery_payload = discovery.to_dict()
    files, pagination = paginate_rows(
        discovery_payload["files"],
        page=args.page,
        page_size=args.page_size,
        total_key="totalFiles",
        returned_key="returnedFiles",
    )
    discovery_payload["files"] = files
    discovery_payload["pagination"] = pagination
    discovery_payload["counts"] = {
        **discovery_payload["counts"],
        "returnedFiles": len(files),
    }
    payload = {
        "ok": True,
        "settingsPath": str(settings_path()),
        **discovery_payload,
    }

    if args.json:
        emit_json(payload)
        return 0

    print(f"Found {payload['counts']['files']} video file(s).")
    print(page_summary(payload["pagination"], "video file"))
    print(f"Supported extensions: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}")
    print("")
    print("Input roots:")
    for root in payload["inputRoots"]:
        status = "OK" if root["exists"] and root["readable"] and root["kind"] in {"file", "directory"} else "ISSUE"
        print(
            f"  [{status}] {root['configuredPath']} "
            f"({root['kind']}, {root['videoFileCount']} video file(s))"
        )
        if root["resolvedPath"] != root["configuredPath"]:
            print(f"        resolved: {root['resolvedPath']}")
        for warning in root["warnings"]:
            print(f"        warning: {warning}")

    if payload["files"]:
        print("")
        print("Files:")
        for video_file in payload["files"]:
            print(f"  {video_file['sourcePath']} ({video_file['sizeBytes']} bytes)")

    return 0


def handle_probe_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    discovery = discover_video_files(settings)
    result = probe_video_files(
        discovery.files,
        ffprobe_bin=args.ffprobe_bin,
        max_items=args.max_items,
    )
    payload = {
        "ok": result["counts"]["failedProbes"] == 0,
        "settingsPath": str(settings_path()),
        "discovery": discovery.to_dict(),
        **result,
    }

    if args.json:
        emit_json(payload)
    else:
        print(
            f"Probed {result['counts']['probedFiles']} of "
            f"{result['counts']['discoveredFiles']} discovered video file(s)."
        )
        if result["counts"]["skippedByMaxItems"]:
            print(f"Skipped by --max-items: {result['counts']['skippedByMaxItems']}")
        print(f"ffprobe: {ffprobe_message(result['ffprobeVersion'])}")
        print("")
        for record in result["records"]:
            status = "OK" if record["ffprobe"]["ok"] else "FAIL"
            summary = record["ffprobe"]["summary"]
            duration = summary["format"]["durationSec"] if summary else None
            streams = summary["counts"]["streams"] if summary else 0
            print(
                f"  [{status}] {record['itemId']} "
                f"{record['sourceIdentity']['sourcePath']} "
                f"duration={duration} streams={streams}"
            )
            if record["ffprobe"]["error"]:
                print(f"        error: {record['ffprobe']['error']}")

    return 0 if payload["ok"] else 1


def handle_sample_frames(args: argparse.Namespace) -> int:
    settings = load_settings()
    discovery = discover_video_files(settings)
    try:
        result = sample_video_files(
            discovery.files,
            settings["outputRoot"],
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
            max_items=args.max_items,
            samples_per_video=args.samples_per_video,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
            "discovery": discovery.to_dict(),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Sampling failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        "discovery": discovery.to_dict(),
        **result,
    }

    if args.json:
        emit_json(payload)
    else:
        print(
            f"Sampled {result['counts']['sampledItems']} of "
            f"{result['counts']['discoveredFiles']} discovered video file(s)."
        )
        if result["counts"]["skippedByMaxItems"]:
            print(f"Skipped by --max-items: {result['counts']['skippedByMaxItems']}")
        print(f"Extracted frames: {result['counts']['extractedFrames']}")
        print(f"Failed frames: {result['counts']['failedFrames']}")
        print("")
        for record in result["records"]:
            status = "OK" if record["ok"] else "FAIL"
            print(
                f"  [{status}] {record['itemId']} "
                f"frames={record['counts']['extractedFrames']}/"
                f"{record['counts']['requestedFrames']}"
            )
            print(f"        frame_samples: {record['outputs']['frameSamplesJson']}")
            print(f"        contact_sheet: {record['outputs']['contactSheet']}")
            for warning in record["warnings"]:
                print(f"        warning: {warning}")

    return 0 if result["ok"] else 1


def handle_ocr_frames(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        result = analyze_frame_ocr_outputs(
            settings["outputRoot"],
            max_items=args.max_items,
            mode=args.mode,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Frame OCR failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        **result,
    }
    if args.json:
        emit_json(payload)
    else:
        print(f"OCR processed {result['counts']['processedItems']} item(s).")
        print(f"Frames: {result['counts']['frames']}")
        print(f"Frames with text: {result['counts']['framesWithText']}")
        print(f"Text blocks: {result['counts']['textBlocks']}")
        print(f"OCR: {result['ocrRuntime']['message']}")
        print("")
        for record in result["records"]:
            status = "OK" if record["ok"] else "FAIL"
            print(
                f"  [{status}] {record['itemId']} "
                f"frames={record['counts']['frames']} blocks={record['counts']['textBlocks']}"
            )
            print(f"        frame_ocr: {record['outputs']['frameOcrJson']}")
            for warning in record["warnings"]:
                print(f"        warning: {warning}")
    return 0 if result["ok"] else 1


def handle_audio_analyze(args: argparse.Namespace) -> int:
    settings = load_settings()
    discovery = discover_video_files(settings)
    try:
        result = analyze_audio_files(
            discovery.files,
            settings["outputRoot"],
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
            max_items=args.max_items,
            settings=settings,
            audio_model_mode=args.audio_model_mode,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
            "discovery": discovery.to_dict(),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Audio analysis failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        "discovery": discovery.to_dict(),
        **result,
    }
    if args.json:
        emit_json(payload)
    else:
        print(
            f"Audio analyzed {result['counts']['processedItems']} of "
            f"{result['counts']['discoveredFiles']} discovered video file(s)."
        )
        if result["counts"]["skippedByMaxItems"]:
            print(f"Skipped by --max-items: {result['counts']['skippedByMaxItems']}")
        print(f"Audio artifacts: {result['counts']['audioArtifacts']}")
        print(f"Speech candidates: {result['counts']['speechCandidates']}")
        print(f"Diarization turns: {result['counts']['diarizationTurns']}")
        print(f"Transcript segments: {result['counts']['transcriptionSegments']}")
        print("")
        for record in result["records"]:
            status = "OK" if record["ok"] else "FAIL"
            print(
                f"  [{status}] {record['itemId']} "
                f"audio_streams={record['inputs']['audioStreamCount']}"
            )
            print(f"        audio_analysis: {record['outputs']['audioAnalysisJson']}")
            print(f"        audio_artifact: {record['audioArtifact']['path']}")
            print(
                f"        audio_models: {record['audioModels']['mode']} "
                f"diarization={record['diarization']['status']} "
                f"transcription={record['transcription']['status']}"
            )
            for warning in record["warnings"]:
                print(f"        warning: {warning}")
    return 0 if result["ok"] else 1


def handle_activity_map(args: argparse.Namespace) -> int:
    settings = load_settings()
    discovery = discover_video_files(settings)
    try:
        result = analyze_activity_files(
            discovery.files,
            settings["outputRoot"],
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
            max_items=args.max_items,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
            "discovery": discovery.to_dict(),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Activity mapping failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        "discovery": discovery.to_dict(),
        **result,
    }
    if args.json:
        emit_json(payload)
    else:
        print(
            f"Activity mapped {result['counts']['processedItems']} of "
            f"{result['counts']['discoveredFiles']} discovered video file(s)."
        )
        if result["counts"]["skippedByMaxItems"]:
            print(f"Skipped by --max-items: {result['counts']['skippedByMaxItems']}")
        print(f"Active duration: {result['counts']['activeSec']} sec")
        print(f"Skipped inactive duration: {result['counts']['inactiveSec']} sec")
        print("")
        for record in result["records"]:
            status = "OK" if record["ok"] else "FAIL"
            print(
                f"  [{status}] {record['itemId']} "
                f"active={record['activity']['activeSec']}s "
                f"inactive={record['activity']['inactiveSec']}s"
            )
            print(f"        activity_map: {record['outputs']['activityMapJson']}")
            for warning in record["warnings"]:
                print(f"        warning: {warning}")
    return 0 if result["ok"] else 1


def handle_process_all(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        result = refresh_configured_items(
            settings,
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
            max_items=args.max_items,
            samples_per_video=args.samples_per_video,
            ocr_mode=args.ocr_mode,
            audio_model_mode=args.audio_model_mode,
            reprocess_duplicates=True,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Processing failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        **result,
    }
    if args.json:
        emit_json(payload)
    else:
        print(f"Process all: {'OK' if result['ok'] else 'ISSUES FOUND'}")
        print(f"Run: {result['runId'] or 'none'}")
        print(f"State: {result['state']}")
        print(f"Source files: {result['counts']['sourceFiles']}")
        print(f"Candidate items: {result['counts']['candidateItems']}")
        print(f"Processed items: {result['counts']['processedItems']}")
        print(f"Skipped items: {result['counts']['skippedItems']}")
        print(f"Failed items: {result['counts']['failedItems']}")
    return 0 if result["ok"] else 1


def handle_models_list(args: argparse.Namespace) -> int:
    settings = load_settings() if settings_path().exists() else None
    payload = build_model_inventory(
        ffprobe_bin=args.ffprobe_bin,
        ffmpeg_bin=args.ffmpeg_bin,
        ocr_mode=args.ocr_mode,
        settings=settings,
        include_remote=args.include_remote,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        emit_json(payload)
    else:
        print(f"pipeline_version: {payload['pipeline']['pipeline_version']}")
        print(f"compute_mode: {payload['pipeline']['compute_mode']}")
        print(f"generation_signature: {payload['pipeline']['generation_signature']}")
        for row in payload["models"]:
            print(
                f"{row['role']}: {row['model_id']} | "
                f"{row['source']} | {row['backend']} | required={row['required']}"
            )
            if row.get("url"):
                print(f"  url: {row['url']}")
            remote = row.get("huggingface")
            if isinstance(remote, dict):
                license_value = remote.get("license") or "unknown"
                gated = remote.get("gated")
                print(f"  hf: status={remote.get('remote_status')} license={license_value} gated={gated}")
        print("")
        print(f"Processing components: {'OK' if payload['ok'] else 'ISSUES FOUND'}")
        print(
            "Required components: "
            f"{payload['counts']['readyRequiredComponents']}/{payload['counts']['requiredComponents']} ready"
        )
        print(
            "Audio model components: "
            f"{payload['counts']['readyAudioModelComponents']}/{payload['counts']['audioModelComponents']} ready"
        )
        print("")
        for component in payload["components"]:
            status = component_status(component)
            model = f" model={component['modelId']}" if component.get("modelId") else ""
            print(f"  [{status}] {component['id']} ({component['backend']}){model}")
            print(f"        {component['role']}")
            if component["execution"]["kind"] == "audio_model":
                print("        status: runs when dependencies and Hugging Face token are available")
    return 0


def handle_items_refresh(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        result = refresh_configured_items(
            settings,
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
            max_items=args.max_items,
            samples_per_video=args.samples_per_video,
            ocr_mode=args.ocr_mode,
            audio_model_mode=args.audio_model_mode,
            reprocess_duplicates=args.reprocess_duplicates,
        )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"Item refresh failed: {exc}")
        return 2

    payload = {
        "settingsPath": str(settings_path()),
        **result,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"Refresh: {'OK' if result['ok'] else 'ISSUES FOUND'}")
        print(f"Run: {result['runId'] or 'none'}")
        print(f"State: {result['state']}")
        print(f"Source files: {result['counts']['sourceFiles']}")
        print(f"Candidate items: {result['counts']['candidateItems']}")
        print(f"Processed items: {result['counts']['processedItems']}")
        print(f"Skipped items: {result['counts']['skippedItems']}")
        print(f"Failed items: {result['counts']['failedItems']}")
        for record in result["records"]:
            status = "OK" if record["ok"] else "FAIL"
            print(f"  [{status}] {record['itemId']} {record['sourcePath']}")
            print(f"        item_root: {record['itemRoot']}")
            print(f"        frames: {record['counts']['frames']}")
            for warning in record["warnings"]:
                print(f"        warning: {warning}")

    return 0 if result["ok"] else 1


def handle_items_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = list_items(settings["outputRoot"])
    items, pagination = paginate_rows(
        result["items"],
        page=args.page,
        page_size=args.page_size,
        total_key="totalItems",
        returned_key="returnedItems",
    )
    payload = {
        "settingsPath": str(settings_path()),
        **result,
        "counts": {
            **result["counts"],
            "returnedItems": len(items),
        },
        "pagination": pagination,
        "items": items,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"Found {result['counts']['items']} item record(s).")
        print(page_summary(pagination, "item"))
        print("")
        for item in items:
            status = "OK" if item["ok"] else "ISSUE"
            print(f"  [{status}] {item['itemId']} {item['sourcePath'] or ''}".rstrip())
            print(f"        item_root: {item['itemRoot']}")
            print(f"        frames: {item['frameCount']}")
            print(f"        ocr_text_blocks: {item['text']['textBlockCount']}")
            print(f"        audio_speech_candidates: {item['audioAnalysis']['speechCandidates']}")
            if item["audioAnalysis"]["available"]:
                print(f"        audio_analysis: yes")
            if item["contactSheet"]:
                print(f"        contact_sheet: {item['contactSheet']}")
            for warning in item["warnings"]:
                print(f"        warning: {warning}")

    return 0


def handle_items_download(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = download_items(settings["outputRoot"], item_ids=args.item_id)
    payload = {
        "settingsPath": str(settings_path()),
        **result,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"Created item ZIP: {result['archivePath']}")
        print(f"Latest ZIP: {result['latestArchivePath']}")
        print(f"Items: {result['counts']['items']}")
        if result["missingItemIds"]:
            print(f"Missing items: {', '.join(result['missingItemIds'])}")
        print(f"Files: {result['counts']['files']}")
        print("Source videos included: no")

    return 0 if result["ok"] else 1


def handle_items_remove(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = remove_items(settings["outputRoot"], dry_run=args.dry_run, item_ids=args.item_id)
    payload = {
        "settingsPath": str(settings_path()),
        **result,
    }

    if args.json:
        emit_json(payload)
    else:
        action = "Would remove" if args.dry_run else "Removed"
        print(f"{action} generated item artifacts.")
        print(f"Files targeted: {result['counts']['targetFiles']}")
        print(f"Directories targeted: {result['counts']['targetDirectories']}")
        if result["missingItemIds"]:
            print(f"Missing items: {', '.join(result['missingItemIds'])}")
        if not args.dry_run:
            print(f"Files deleted: {result['counts']['deletedFiles']}")
            print(f"Directories pruned: {result['counts']['prunedDirectories']}")
        print("Source videos removed: no")

    return 0 if result["ok"] else 1


def handle_runs_list(args: argparse.Namespace) -> int:
    result = list_processor_runs(limit=args.limit)
    runs, pagination = paginate_rows(
        result["runs"],
        page=args.page,
        page_size=args.page_size,
        total_key="totalRuns",
        returned_key="returnedRuns",
    )
    result = {
        **result,
        "counts": {
            **result["counts"],
            "returnedRuns": len(runs),
        },
        "pagination": pagination,
        "runs": runs,
    }
    if args.json:
        emit_json(result)
    else:
        print(f"Runs: {result['counts']['runs']}")
        print(page_summary(pagination, "run"))
        for run in runs:
            counts = run.get("counts") or {}
            print(
                f"  {run['runId']} {run['state']} "
                f"processed={counts.get('processedItems', 0)} failed={counts.get('failedItems', 0)}"
            )
    return 0


def handle_runs_show(args: argparse.Namespace) -> int:
    try:
        result = show_processor_run(args.run_id)
    except FileNotFoundError as exc:
        payload = {"ok": False, "error": str(exc), "runId": args.run_id}
        if args.json:
            emit_json(payload)
        else:
            print(str(exc))
        return 1
    if args.json:
        emit_json(result)
    else:
        state = (result.get("result") or result.get("status") or {}).get("state", "unknown")
        print(f"Run: {result['runId']}")
        print(f"State: {state}")
        counts = (result.get("result") or {}).get("counts") or {}
        for key in ["sourceFiles", "candidateItems", "processedItems", "skippedItems", "failedItems"]:
            print(f"{key}: {counts.get(key, 0)}")
    return 0


def handle_serve(args: argparse.Namespace) -> int:
    interval = max(args.interval_seconds, 1.0)
    if not getattr(args, "json", False):
        print(f"{PRODUCT_NAME} worker is running. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            try:
                settings = load_settings()
                result = refresh_configured_items(
                    settings,
                    ffprobe_bin=args.ffprobe_bin,
                    ffmpeg_bin=args.ffmpeg_bin,
                    max_items=args.max_items,
                    samples_per_video=args.samples_per_video,
                    ocr_mode=args.ocr_mode,
                    audio_model_mode=args.audio_model_mode,
                )
                next_refresh_seconds = None if args.once else next_worker_refresh_seconds(result, interval)
                event = {
                    "event": "refresh_skipped_no_changes"
                    if result["state"] == "skipped_no_changes"
                    else "refresh_completed",
                    "ok": result["ok"],
                    "runId": result["runId"],
                    "state": result["state"],
                    "counts": result["counts"],
                    "failedSteps": result.get("failedSteps", []),
                    "nextRefreshSeconds": next_refresh_seconds,
                }
                write_worker_event(args, event)
                if args.once:
                    return 0 if result["ok"] else 1
            except Exception as exc:
                event = {
                    "event": "refresh_failed",
                    "ok": False,
                    "error": str(exc),
                    "nextRefreshSeconds": None if args.once else interval,
                }
                write_worker_event(args, event)
                if args.once:
                    return 1
            time.sleep(float(event["nextRefreshSeconds"] or 0.0))
    except KeyboardInterrupt:
        return 0


def next_worker_refresh_seconds(result: dict[str, Any], interval: float) -> float:
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    if result.get("ok") and int(counts.get("candidateItems") or 0) > 0:
        return 0.0
    return interval


def write_worker_event(args: argparse.Namespace, event: dict[str, Any]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(event, ensure_ascii=False), flush=True)
        return
    if event["ok"]:
        counts = event.get("counts") or {}
        print(
            "worker: "
            f"{event['event']} run={event.get('runId') or 'none'} "
            f"processed={counts.get('processedItems', 0)} "
            f"skipped={counts.get('skippedItems', 0)} "
            f"failed={counts.get('failedItems', 0)}",
            flush=True,
        )
    else:
        counts = event.get("counts") or {}
        failed_steps = event.get("failedSteps") or []
        detail = f" failed_steps={','.join(failed_steps)}" if failed_steps else ""
        error = event.get("error")
        error_detail = f" error={error}" if error else ""
        print(
            "worker: "
            f"{event['event']} run={event.get('runId') or 'none'} "
            f"state={event.get('state', 'unknown')} "
            f"processed={counts.get('processedItems', 0)} "
            f"skipped={counts.get('skippedItems', 0)} "
            f"failed={counts.get('failedItems', 0)}"
            f"{detail}{error_detail}",
            flush=True,
        )


def handle_settings_init(args: argparse.Namespace) -> int:
    target = settings_path()
    created = False
    overwritten = False

    if target.exists() and not args.force:
        settings = load_settings(target)
    else:
        overwritten = target.exists()
        settings = save_settings(load_example_settings(), target)
        created = not overwritten

    payload = {
        "ok": True,
        "created": created,
        "overwritten": overwritten,
        "settingsPath": str(target),
        "settingsExamplePath": str(settings_example_path()),
        "settings": redact_settings(settings),
    }
    action = "Created" if created else "Overwrote" if overwritten else "Already exists"
    emit_result(args, payload, f"{action}: {target}")
    return 0


def handle_settings_status(args: argparse.Namespace) -> int:
    target = settings_path()
    exists = target.exists()
    settings = load_settings(target) if exists else None
    payload = {
        "ok": True,
        "exists": exists,
        "settingsPath": str(target),
        "settingsExamplePath": str(settings_example_path()),
        "settings": redact_settings(settings),
    }
    message = f"Settings exist: {target}" if exists else f"Settings missing: {target}"
    emit_result(args, payload, message)
    return 0


def handle_settings_save(args: argparse.Namespace) -> int:
    target = settings_path()
    settings = load_settings(target) if target.exists() else load_example_settings()

    if args.input_root is not None:
        settings["inputRoots"] = args.input_root
    if args.output_root is not None:
        settings["outputRoot"] = args.output_root
    if args.clear_token:
        settings["huggingFaceToken"] = ""
    if args.token is not None:
        settings["huggingFaceToken"] = args.token
    if args.compute_mode is not None:
        settings["computeMode"] = args.compute_mode
    settings = save_settings(settings, target)
    payload = {
        "ok": True,
        "settingsPath": str(target),
        "settings": redact_settings(settings),
    }
    emit_result(args, payload, f"Saved: {target}")
    return 0


def input_root_message(root: dict[str, Any]) -> str:
    if not root["exists"]:
        return f"Input root is missing: {root['configuredPath']}"
    if not root["readable"]:
        return f"Input root is not readable: {root['configuredPath']}"
    if root["kind"] not in {"file", "directory"}:
        return f"Input root is not a file or directory: {root['configuredPath']}"
    if "unsupported_extension" in root["warnings"]:
        return f"Input file extension is not supported: {root['configuredPath']}"
    return f"Input root is readable: {root['configuredPath']}"


def output_root_message(output_root: dict[str, Any]) -> str:
    if output_root["ok"] and output_root["exists"]:
        return f"Output root exists and is writable: {output_root['configuredPath']}"
    if output_root["ok"]:
        return f"Output root can be created under existing parent: {output_root['configuredPath']}"
    if output_root["kind"] == "file":
        return f"Output root points to a file: {output_root['configuredPath']}"
    if not output_root["parentExists"]:
        return f"Output root parent is missing: {output_root['parentPath']}"
    return f"Output root is not writable: {output_root['configuredPath']}"


def ffprobe_message(ffprobe_status: dict[str, Any]) -> str:
    if ffprobe_status["ok"]:
        return ffprobe_status["versionLine"] or "ffprobe is available"
    return ffprobe_status["error"] or "ffprobe is not available"


def audio_model_message(status: dict[str, Any], required: bool) -> str:
    if status["ready"]:
        return "Audio models are ready."
    if not status["tokenConfigured"]:
        suffix = "required" if required else "optional"
        return f"Hugging Face token is not configured; audio models are {suffix}."
    missing = [name for name, available in status["modules"].items() if not available]
    if missing:
        return "Audio model dependencies are missing: " + ", ".join(sorted(missing))
    return "Audio models are not ready."


def component_status(component: dict[str, Any]) -> str:
    if component["execution"]["kind"] == "audio_model" and not component["runtime"]["ready"]:
        return "OPTIONAL"
    return "OK" if component["runtime"]["ready"] else "FAIL"


def output_doctor(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    if args.json:
        emit_json(payload)
        return

    print(f"Doctor: {'OK' if payload['ok'] else 'ISSUES FOUND'}")
    for check in payload["checks"]:
        status = "OK" if check["ok"] else "FAIL"
        print(f"  [{status}] {check['name']}: {check['message']}")


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SettingsError as exc:
        emit_json({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
