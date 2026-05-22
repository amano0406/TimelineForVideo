from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import __version__
from .activity_map import analyze_activity_files
from .audio_analysis import analyze_audio_files
from .discovery import VideoFile, discover_video_files, resolve_configured_path
from .frame_ocr import analyze_frame_ocr_outputs
from .items import PIPELINE_VERSION, generated_item_files, refresh_items as refresh_item_records
from .locks import exclusive_lock
from .probe import item_id_from_fingerprint, source_fingerprint, source_identity, utc_now_iso
from .sampling import DEFAULT_SAMPLES_PER_VIDEO, sample_video_files
from .settings import PRODUCT_NAME, internal_state_root


CATALOG_SCHEMA_VERSION = "timeline_for_video.catalog.v1"
RUN_RESULT_SCHEMA_VERSION = "timeline_for_video.run_result.v1"


def refresh_configured_items(
    settings: dict[str, Any],
    *,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    max_items: int | None = None,
    samples_per_video: int = DEFAULT_SAMPLES_PER_VIDEO,
    ocr_mode: str = "auto",
    audio_model_mode: str | None = None,
    reprocess_duplicates: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    state_root = internal_state_root()
    with exclusive_lock(state_root, "catalog"):
        return refresh_configured_items_unlocked(
            settings,
            ffprobe_bin=ffprobe_bin,
            ffmpeg_bin=ffmpeg_bin,
            max_items=max_items,
            samples_per_video=samples_per_video,
            ocr_mode=ocr_mode,
            audio_model_mode=audio_model_mode,
            reprocess_duplicates=reprocess_duplicates,
            run_id=run_id,
        )


def refresh_configured_items_unlocked(
    settings: dict[str, Any],
    *,
    ffprobe_bin: str,
    ffmpeg_bin: str,
    max_items: int | None,
    samples_per_video: int,
    ocr_mode: str,
    audio_model_mode: str | None,
    reprocess_duplicates: bool,
    run_id: str | None,
) -> dict[str, Any]:
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")

    generated_at = utc_now_iso()
    output_root = resolve_configured_path(settings["outputRoot"])
    output_root.mkdir(parents=True, exist_ok=True)
    state_root = internal_state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    active_run_ids = {run_id} if run_id else None
    mark_stale_running_runs(state_root, active_run_ids=active_run_ids)

    discovery = discover_video_files(settings)
    catalog = load_catalog(state_root)
    source_rows = [source_row(video_file, output_root) for video_file in discovery.files]
    candidates = [
        row
        for row in source_rows
        if needs_processing(catalog, row, output_root, reprocess_duplicates=reprocess_duplicates)
    ]
    if max_items is not None:
        candidates = candidates[:max_items]

    if not candidates:
        result = {
            "schemaVersion": RUN_RESULT_SCHEMA_VERSION,
            "product": PRODUCT_NAME,
            "version": __version__,
            "generatedAt": generated_at,
            "runId": None,
            "state": "skipped_no_changes",
            "ok": True,
            "outputRoot": {
                "configuredPath": settings["outputRoot"],
                "resolvedPath": str(output_root),
            },
            "counts": {
                "sourceFiles": len(discovery.files),
                "candidateItems": 0,
                "processedItems": 0,
                "skippedItems": len(discovery.files),
                "failedItems": 0,
            },
            "discovery": discovery.to_dict(),
            "steps": {},
            "records": [],
        }
        if run_id:
            run_dir = state_root / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            write_json(run_dir / "result.json", result)
            write_run_status(
                run_dir,
                run_id=run_id,
                state="completed",
                current_stage="completed",
                started_at=generated_at,
                items_total=0,
                items_done=0,
                completed_at=utc_now_iso(),
                message="No changed video files were found.",
                progress_percent=100.0,
            )
        write_worker_status(state_root, result)
        return result

    run_id = run_id or unique_run_id()
    run_dir = state_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="start",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        message="Preparing video refresh.",
        progress_percent=1.0,
    )

    candidate_files = [row["videoFile"] for row in candidates]
    candidate_item_ids = {row["itemId"] for row in candidates}
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="sample",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        message="Sampling video frames.",
        progress_percent=10.0,
    )

    def sample_progress(event: dict[str, Any]) -> None:
        total = max(1, int(event.get("total") or len(candidates)))
        done = max(0, min(total, int(event.get("itemsDone") or 0)))
        progress_percent = 10.0 + ((done / total) * 15.0)
        item_stage = str(event.get("itemStage") or "").strip()
        message = str(event.get("message") or "Sampling video frames.")
        if item_stage and item_stage not in {"completed"}:
            message = f"{message} ({item_stage})"
        write_run_status(
            run_dir,
            run_id=run_id,
            state="running",
            current_stage="sample",
            started_at=generated_at,
            items_total=len(candidates),
            items_done=done,
            current_item=str(event.get("currentItem") or "") or None,
            message=message,
            progress_percent=progress_percent,
        )

    sample_result = sample_video_files(
        candidate_files,
        settings["outputRoot"],
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        max_items=len(candidate_files),
        samples_per_video=samples_per_video,
        progress_callback=sample_progress,
    )
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="frame_ocr",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        step_status={"sample": sample_result["ok"]},
        message="Reading text from sampled video frames.",
        progress_percent=25.0,
    )

    def frame_ocr_progress(event: dict[str, Any]) -> None:
        total = max(1, int(event.get("total") or len(candidates)))
        done = max(0, min(total, int(event.get("itemsDone") or 0)))
        progress_percent = 25.0 + ((done / total) * 20.0)
        item_stage = str(event.get("itemStage") or "").strip()
        message = str(event.get("message") or "Reading text from sampled video frames.")
        if item_stage and item_stage not in {"completed"}:
            message = f"{message} ({item_stage})"
        write_run_status(
            run_dir,
            run_id=run_id,
            state="running",
            current_stage="frame_ocr",
            started_at=generated_at,
            items_total=len(candidates),
            items_done=done,
            current_item=str(event.get("currentItem") or "") or None,
            step_status={"sample": sample_result["ok"]},
            message=message,
            progress_percent=progress_percent,
        )

    frame_ocr_result = analyze_frame_ocr_outputs(
        settings["outputRoot"],
        max_items=None,
        mode=ocr_mode,
        item_ids=candidate_item_ids,
        progress_callback=frame_ocr_progress,
    )
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="audio",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        step_status={"sample": sample_result["ok"], "frameOcr": frame_ocr_result["ok"]},
        message="Analyzing video audio.",
        progress_percent=45.0,
    )

    def audio_progress(event: dict[str, Any]) -> None:
        total = max(1, int(event.get("total") or len(candidates)))
        done = max(0, min(total, int(event.get("itemsDone") or 0)))
        progress_percent = 45.0 + ((done / total) * 25.0)
        item_stage = str(event.get("itemStage") or "").strip()
        message = str(event.get("message") or "Analyzing video audio.")
        if item_stage and item_stage not in {"prepare", "completed"}:
            message = f"{message} ({item_stage})"
        write_run_status(
            run_dir,
            run_id=run_id,
            state="running",
            current_stage="audio",
            started_at=generated_at,
            items_total=len(candidates),
            items_done=done,
            current_item=str(event.get("currentItem") or "") or None,
            step_status={"sample": sample_result["ok"], "frameOcr": frame_ocr_result["ok"]},
            message=message,
            progress_percent=progress_percent,
        )

    audio_result = analyze_audio_files(
        candidate_files,
        settings["outputRoot"],
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        max_items=len(candidate_files),
        settings=settings,
        audio_model_mode=audio_model_mode,
        progress_callback=audio_progress,
    )
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="activity",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        step_status={
            "sample": sample_result["ok"],
            "frameOcr": frame_ocr_result["ok"],
            "audio": audio_result["ok"],
        },
        message="Analyzing video activity.",
        progress_percent=70.0,
    )
    activity_result = analyze_activity_files(
        candidate_files,
        settings["outputRoot"],
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        max_items=len(candidate_files),
    )
    write_run_status(
        run_dir,
        run_id=run_id,
        state="running",
        current_stage="refresh",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=0,
        step_status={
            "sample": sample_result["ok"],
            "frameOcr": frame_ocr_result["ok"],
            "audio": audio_result["ok"],
            "activity": activity_result["ok"],
        },
        message="Building Timeline item records.",
        progress_percent=88.0,
    )
    item_result = refresh_item_records(
        candidate_files,
        settings["outputRoot"],
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
        max_items=len(candidate_files),
    )

    ok = (
        sample_result["ok"]
        and frame_ocr_result["ok"]
        and audio_result["ok"]
        and activity_result["ok"]
        and item_result["ok"]
    )
    failed_steps = failed_step_names(
        {
            "sample": sample_result,
            "frameOcr": frame_ocr_result,
            "audio": audio_result,
            "activity": activity_result,
            "refresh": item_result,
        }
    )
    processed_records = item_result["records"]
    complete_ids = complete_item_ids([sample_result, frame_ocr_result, audio_result, activity_result, item_result])
    for row in candidates:
        if row["itemId"] in complete_ids:
            update_catalog_item(catalog, row, output_root)
    save_catalog(state_root, catalog)

    failed_items = len(candidates) - len(complete_ids)
    result = {
        "schemaVersion": RUN_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "runId": run_id,
        "state": "completed" if ok else "completed_with_errors",
        "ok": ok,
        "failedSteps": failed_steps,
        "outputRoot": {
            "configuredPath": settings["outputRoot"],
            "resolvedPath": str(output_root),
        },
        "counts": {
            "sourceFiles": len(discovery.files),
            "candidateItems": len(candidates),
            "processedItems": len(processed_records),
            "skippedItems": max(len(discovery.files) - len(candidates), 0),
            "failedItems": failed_items,
            "completedItems": len(complete_ids),
        },
        "discovery": discovery.to_dict(),
        "steps": {
            "sample": sample_result,
            "frameOcr": frame_ocr_result,
            "audio": audio_result,
            "activity": activity_result,
            "refresh": item_result,
        },
        "records": processed_records,
    }
    write_json(run_dir / "result.json", result)
    write_run_status(
        run_dir,
        run_id=run_id,
        state=result["state"],
        current_stage="completed",
        started_at=generated_at,
        items_total=len(candidates),
        items_done=len(complete_ids),
        items_failed=failed_items,
        completed_at=utc_now_iso(),
        step_status={
            "sample": sample_result["ok"],
            "frameOcr": frame_ocr_result["ok"],
            "audio": audio_result["ok"],
            "activity": activity_result["ok"],
            "refresh": item_result["ok"],
        },
        failed_steps=failed_steps,
        message="Video refresh completed." if ok else "Video refresh completed with errors.",
        progress_percent=100.0,
    )
    write_worker_status(state_root, result)
    return result


def source_row(video_file: VideoFile, output_root: Path) -> dict[str, Any]:
    identity = source_identity(video_file)
    fingerprint = source_fingerprint(identity)
    item_id = item_id_from_fingerprint(fingerprint)
    return {
        "itemId": item_id,
        "videoFile": video_file,
        "sourceIdentity": identity,
        "sourceFingerprint": fingerprint,
        "sourcePath": identity["sourcePath"],
        "itemRoot": str(output_root / "items" / item_id),
        "pipelineVersion": PIPELINE_VERSION,
        "productVersion": __version__,
    }


def needs_processing(
    catalog: dict[str, Any],
    row: dict[str, Any],
    output_root: Path,
    *,
    reprocess_duplicates: bool,
) -> bool:
    if reprocess_duplicates:
        return True
    items = catalog.get("items") if isinstance(catalog.get("items"), dict) else {}
    previous = items.get(row["itemId"]) if isinstance(items, dict) else None
    if not isinstance(previous, dict):
        return True
    if previous.get("sourceFingerprint") != row["sourceFingerprint"]["value"]:
        return True
    if previous.get("pipelineVersion") != PIPELINE_VERSION:
        return True
    return not item_output_complete(output_root / "items" / row["itemId"])


def item_output_complete(item_root: Path) -> bool:
    required = [
        item_root / "video_record.json",
        item_root / "timeline.json",
        item_root / "convert_info.json",
        item_root / "raw_outputs" / "ffprobe.json",
        item_root / "raw_outputs" / "frame_samples.json",
        item_root / "raw_outputs" / "frame_ocr.json",
        item_root / "raw_outputs" / "audio_analysis.json",
        item_root / "raw_outputs" / "activity_map.json",
        item_root / "artifacts" / "contact_sheet.jpg",
    ]
    return item_root.is_dir() and all(path.is_file() for path in required)


def update_catalog_item(catalog: dict[str, Any], row: dict[str, Any], output_root: Path) -> None:
    items = catalog.setdefault("items", {})
    item_root = output_root / "items" / row["itemId"]
    items[row["itemId"]] = {
        "itemId": row["itemId"],
        "sourcePath": row["sourcePath"],
        "sourceFingerprint": row["sourceFingerprint"]["value"],
        "sourceIdentity": row["sourceIdentity"],
        "pipelineVersion": PIPELINE_VERSION,
        "productVersion": __version__,
        "itemRoot": str(item_root),
        "updatedAt": utc_now_iso(),
        "outputFiles": [
            str(path)
            for path in generated_item_files(
                item_root,
                include_audio_artifacts=True,
                include_image_artifacts=True,
            )
            if path.exists()
        ],
    }


def failed_step_names(steps: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, result in steps.items() if not bool(result.get("ok"))]


def complete_item_ids(step_results: list[dict[str, Any]]) -> set[str]:
    complete: set[str] | None = None
    for result in step_results:
        ids = {
            str(record["itemId"])
            for record in result.get("records", [])
            if isinstance(record, dict) and record.get("ok") and record.get("itemId")
        }
        complete = ids if complete is None else complete & ids
    return complete or set()


def write_run_status(
    run_dir: Path,
    *,
    run_id: str,
    state: str,
    current_stage: str,
    started_at: str,
    items_total: int,
    items_done: int,
    items_failed: int = 0,
    current_item: str | None = None,
    completed_at: str | None = None,
    step_status: dict[str, bool] | None = None,
    failed_steps: list[str] | None = None,
    message: str = "",
    progress_percent: float | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schemaVersion": RUN_RESULT_SCHEMA_VERSION,
        "runId": run_id,
        "state": state,
        "currentStage": current_stage,
        "startedAt": started_at,
        "updatedAt": utc_now_iso(),
        "itemsTotal": items_total,
        "itemsDone": items_done,
        "itemsFailed": items_failed,
    }
    if message:
        payload["message"] = message
    if progress_percent is not None:
        payload["progressPercent"] = round(max(0.0, min(100.0, progress_percent)), 2)
    if current_item:
        payload["currentItem"] = current_item
    if completed_at is not None:
        payload["completedAt"] = completed_at
    if step_status is not None:
        payload["stepStatus"] = step_status
    if failed_steps is not None:
        payload["failedSteps"] = failed_steps
    write_json(run_dir / "status.json", payload)


def load_catalog(state_root: Path) -> dict[str, Any]:
    path = state_root / "catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schemaVersion": CATALOG_SCHEMA_VERSION, "items": {}}
    except json.JSONDecodeError:
        return {"schemaVersion": CATALOG_SCHEMA_VERSION, "items": {}, "warnings": ["invalid_catalog_json"]}
    if not isinstance(payload, dict):
        return {"schemaVersion": CATALOG_SCHEMA_VERSION, "items": {}, "warnings": ["invalid_catalog_root"]}
    if not isinstance(payload.get("items"), dict):
        payload["items"] = {}
    return payload


def mark_stale_running_runs(state_root: Path, active_run_ids: set[str] | None = None) -> None:
    runs_root = state_root / "runs"
    if not runs_root.is_dir():
        return
    active_run_ids = active_run_ids or set()
    for status_path in runs_root.glob("*/status.json"):
        status = read_json(status_path)
        if not status or status.get("state") not in {"queued", "running"}:
            continue
        if status_path.parent.name in active_run_ids:
            continue
        status["state"] = "interrupted"
        status["currentStage"] = "interrupted"
        status["updatedAt"] = utc_now_iso()
        status["completedAt"] = status["updatedAt"]
        status["message"] = "Worker stopped before the job completed. Queue a new refresh to retry."
        status.setdefault("itemsFailed", status.get("itemsTotal", 0))
        status.setdefault("failedSteps", ["interrupted"])
        write_json(status_path, status)


def save_catalog(state_root: Path, catalog: dict[str, Any]) -> None:
    catalog["schemaVersion"] = CATALOG_SCHEMA_VERSION
    catalog["pipelineVersion"] = PIPELINE_VERSION
    catalog["updatedAt"] = utc_now_iso()
    write_json(state_root / "catalog.json", catalog)


def list_runs(limit: int | None = None) -> dict[str, Any]:
    runs_root = internal_state_root() / "runs"
    runs: list[dict[str, Any]] = []
    if runs_root.is_dir():
        for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True):
            result = read_json(run_dir / "result.json")
            status = read_json(run_dir / "status.json")
            runs.append(
                {
                    "runId": run_dir.name,
                    "state": (result or status or {}).get("state", "unknown"),
                    "ok": (result or {}).get("ok"),
                    "generatedAt": (result or {}).get("generatedAt") or (status or {}).get("startedAt"),
                    "counts": (result or {}).get("counts", {}),
                    "resultPath": str(run_dir / "result.json"),
                    "statusPath": str(run_dir / "status.json"),
                }
            )
    if limit is not None:
        runs = runs[:limit]
    return {
        "schemaVersion": "timeline_for_video.runs_list.v1",
        "product": PRODUCT_NAME,
        "version": __version__,
        "ok": True,
        "stateRoot": str(internal_state_root()),
        "counts": {"runs": len(runs)},
        "runs": runs,
    }


def show_run(run_id: str) -> dict[str, Any]:
    run_dir = internal_state_root() / "runs" / run_id
    result = read_json(run_dir / "result.json")
    status = read_json(run_dir / "status.json")
    if result is None and status is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    return {
        "schemaVersion": "timeline_for_video.run_show.v1",
        "product": PRODUCT_NAME,
        "version": __version__,
        "ok": True,
        "runId": run_id,
        "stateRoot": str(internal_state_root()),
        "status": status,
        "result": result,
    }


def write_worker_status(state_root: Path, result: dict[str, Any]) -> None:
    write_json(
        state_root / "worker-status.json",
        {
            "schemaVersion": RUN_RESULT_SCHEMA_VERSION,
            "product": PRODUCT_NAME,
            "version": __version__,
            "state": result["state"],
            "ok": result["ok"],
            "runId": result["runId"],
            "updatedAt": utc_now_iso(),
            "counts": result["counts"],
            "failedSteps": result.get("failedSteps", []),
        },
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique_run_id() -> str:
    return f"run-{utc_now_iso().replace(':', '').replace('+00:00', 'Z')}-{uuid4().hex[:8]}"
