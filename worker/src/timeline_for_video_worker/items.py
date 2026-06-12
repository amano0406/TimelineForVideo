from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any
import zipfile

from . import __version__
from .discovery import VideoFile, resolve_configured_path
from .probe import canonical_json, probe_video_files, sha256_hex, utc_now_iso
from .settings import PRODUCT_NAME


VIDEO_RECORD_SCHEMA_VERSION = "timeline_for_video.video_record.v1"
TIMELINE_SCHEMA_VERSION = "timeline_for_video.timeline.v1"
CONVERT_INFO_SCHEMA_VERSION = "timeline_for_video.convert_info.v1"
ITEM_REFRESH_RESULT_SCHEMA_VERSION = "timeline_for_video.item_refresh_result.v1"
ITEM_LIST_RESULT_SCHEMA_VERSION = "timeline_for_video.item_list_result.v1"
ITEM_DOWNLOAD_RESULT_SCHEMA_VERSION = "timeline_for_video.item_download_result.v1"
ITEM_REMOVE_RESULT_SCHEMA_VERSION = "timeline_for_video.item_remove_result.v1"
PIPELINE_VERSION = "timeline_for_video.pipeline.m13"


def refresh_items(
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
    records: list[dict[str, Any]] = []

    for probe_record in probe_result["records"]:
        records.append(refresh_probe_record(probe_record, output_root, output_root_text, generated_at))

    failed_items = sum(1 for record in records if not record["ok"])
    return {
        "schemaVersion": ITEM_REFRESH_RESULT_SCHEMA_VERSION,
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
            "refreshedItems": len(records),
            "failedItems": failed_items,
            "skippedByMaxItems": probe_result["counts"]["skippedByMaxItems"],
        },
        "records": records,
    }


def refresh_probe_record(
    probe_record: dict[str, Any],
    output_root: Path,
    output_root_text: str,
    generated_at: str,
) -> dict[str, Any]:
    item_id = probe_record["itemId"]
    item_root = output_root / "items" / item_id
    raw_outputs_dir = item_root / "raw_outputs"
    artifacts_dir = item_root / "artifacts"
    frames_dir = artifacts_dir / "frames"
    ffprobe_path = raw_outputs_dir / "ffprobe.json"
    frame_samples_path = raw_outputs_dir / "frame_samples.json"
    frame_ocr_path = raw_outputs_dir / "frame_ocr.json"
    frame_diff_vlm_path = raw_outputs_dir / "frame_diff_vlm.json"
    audio_analysis_path = raw_outputs_dir / "audio_analysis.json"
    activity_map_path = raw_outputs_dir / "activity_map.json"
    contact_sheet_path = artifacts_dir / "contact_sheet.jpg"
    audio_artifact_path = artifacts_dir / "audio" / "source_audio.mp3"
    video_record_path = item_root / "video_record.json"
    timeline_path = item_root / "timeline.json"
    convert_info_path = item_root / "convert_info.json"

    frame_samples, frame_samples_warning = read_optional_json(frame_samples_path)
    frame_ocr, frame_ocr_warning = read_optional_json(frame_ocr_path)
    frame_diff_vlm, frame_diff_vlm_warning = read_optional_json(frame_diff_vlm_path)
    audio_analysis, audio_analysis_warning = read_optional_json(audio_analysis_path)
    activity_map, activity_map_warning = read_optional_json(activity_map_path)
    warnings = list(probe_record.get("recordSeed", {}).get("processing", {}).get("warnings", []))
    if frame_samples_warning:
        warnings.append(frame_samples_warning)
    if frame_ocr_warning:
        warnings.append(frame_ocr_warning)
    if frame_diff_vlm_warning:
        warnings.append(frame_diff_vlm_warning)
    if audio_analysis_warning:
        warnings.append(audio_analysis_warning)
    if activity_map_warning:
        warnings.append(activity_map_warning)

    paths = {
        "itemRoot": str(item_root),
        "videoRecordJson": str(video_record_path),
        "timelineJson": str(timeline_path),
        "convertInfoJson": str(convert_info_path),
        "rawOutputsDir": str(raw_outputs_dir),
        "ffprobeJson": str(ffprobe_path),
        "frameSamplesJson": str(frame_samples_path),
        "frameOcrJson": str(frame_ocr_path),
        "frameDiffVlmJson": str(frame_diff_vlm_path),
        "audioAnalysisJson": str(audio_analysis_path),
        "activityMapJson": str(activity_map_path),
        "artifactsDir": str(artifacts_dir),
        "framesDir": str(frames_dir),
        "contactSheet": str(contact_sheet_path),
        "audioArtifact": str(audio_artifact_path),
        "outputRootConfiguredPath": output_root_text,
    }

    raw_outputs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(ffprobe_path, probe_record)

    video_record = build_video_record(
        probe_record,
        frame_samples,
        frame_ocr,
        frame_diff_vlm,
        audio_analysis,
        activity_map,
        paths,
        generated_at,
        warnings,
    )
    timeline = build_timeline(
        probe_record,
        frame_samples,
        frame_ocr,
        frame_diff_vlm,
        audio_analysis,
        activity_map,
        paths,
        generated_at,
    )
    convert_info = build_convert_info(
        probe_record,
        frame_samples,
        frame_ocr,
        frame_diff_vlm,
        audio_analysis,
        activity_map,
        paths,
        generated_at,
        warnings,
    )

    write_json(video_record_path, video_record)
    write_json(timeline_path, timeline)
    write_json(convert_info_path, convert_info)

    return {
        "itemId": item_id,
        "ok": probe_record["ffprobe"]["ok"],
        "sourcePath": probe_record["sourceIdentity"]["sourcePath"],
        "itemRoot": str(item_root),
        "outputFiles": output_file_entries(paths),
        "counts": {
            "frames": len(video_record["frames"]),
            "visualEvents": len(timeline["lanes"]["visual"]),
            "audioEvents": len(timeline["lanes"]["audio"]),
            "textEvents": len(timeline["lanes"]["text"]),
            "activityEvents": len(timeline["lanes"].get("activity", [])),
        },
        "warnings": warnings,
    }


def build_video_record(
    probe_record: dict[str, Any],
    frame_samples: dict[str, Any] | None,
    frame_ocr: dict[str, Any] | None,
    frame_diff_vlm: dict[str, Any] | None,
    audio_analysis: dict[str, Any] | None,
    activity_map: dict[str, Any] | None,
    paths: dict[str, str],
    generated_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    summary = probe_record["ffprobe"]["summary"]
    frames = frame_entries(frame_samples, frame_ocr)
    contact_sheet_exists = Path(paths["contactSheet"]).exists()
    text_blocks = text_blocks_from_frame_ocr(frame_ocr)
    audio_text = audio_text_summary(audio_analysis)
    return {
        "schema_version": VIDEO_RECORD_SCHEMA_VERSION,
        "record_id": probe_record["itemId"],
        "asset": {
            "source_path": probe_record["sourceIdentity"]["sourcePath"],
            "source_fingerprint": probe_record["sourceFingerprint"]["value"],
            "source_identity": probe_record["sourceIdentity"],
            "analysis_input": probe_record.get("analysisInput"),
            "source_video_modified": False,
        },
        "timeline": {
            "coordinate": "source_video_relative_time",
            "timeline_json": paths["timelineJson"],
        },
        "video": {
            "format": summary["format"] if summary else None,
            "streams": [stream for stream in summary["streams"] if stream["codecType"] == "video"] if summary else [],
        },
        "audio": {
            "streams": [stream for stream in summary["streams"] if stream["codecType"] == "audio"] if summary else [],
            "analysis": audio_analysis_summary(audio_analysis),
        },
        "activity": activity_map_summary(activity_map),
        "visual": {
            "frame_features": frame_visual_summary_from_entries(frames),
            "frame_transition_gate": frame_transition_gate_summary(frame_samples),
            "frame_diff_vlm": frame_diff_vlm_summary(frame_diff_vlm),
        },
        "processing": {
            "stage": "item_refresh",
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": generated_at,
            "source_video_modified": False,
            "analysis_input": probe_record.get("analysisInput"),
            "media_normalization": probe_record.get("mediaNormalization"),
            "raw_outputs": {
                "ffprobe_json": paths["ffprobeJson"],
                "frame_samples_json": paths["frameSamplesJson"],
                "frame_ocr_json": paths["frameOcrJson"],
                "frame_diff_vlm_json": paths["frameDiffVlmJson"],
                "audio_analysis_json": paths["audioAnalysisJson"],
                "activity_map_json": paths["activityMapJson"],
            },
            "artifacts": {
                "contact_sheet": paths["contactSheet"],
                "frames_dir": paths["framesDir"],
                "audio_artifact": paths["audioArtifact"],
            },
            "warnings": warnings,
        },
        "segments": [],
        "frames": frames,
        "text": {
            "mode": "frame_ocr_and_audio_reference",
            "ocr": bool(frame_ocr),
            "transcription": bool(audio_text["readableText"]),
            "full_text": "\n".join(
                part
                for part in [
                    "\n".join(block["text"] for block in text_blocks),
                    audio_text["readableText"],
                ]
                if part
            ),
            "blocks": text_blocks,
            "audio": audio_text,
        },
        "review": {
            "contact_sheet": paths["contactSheet"],
            "contact_sheet_exists": contact_sheet_exists,
            "frame_count": len(frames),
        },
    }


def build_timeline(
    probe_record: dict[str, Any],
    frame_samples: dict[str, Any] | None,
    frame_ocr: dict[str, Any] | None,
    frame_diff_vlm: dict[str, Any] | None,
    audio_analysis: dict[str, Any] | None,
    activity_map: dict[str, Any] | None,
    paths: dict[str, str],
    generated_at: str,
) -> dict[str, Any]:
    summary = probe_record["ffprobe"]["summary"]
    duration_sec = summary["format"]["durationSec"] if summary else None
    visual_events: list[dict[str, Any]] = [
        {
            "eventType": "video_observed",
            "timeSec": 0.0,
            "sourcePath": probe_record["sourceIdentity"]["sourcePath"],
            "ffprobeJson": paths["ffprobeJson"],
        },
        {
            "eventType": "video_interval",
            "startSec": 0.0,
            "endSec": duration_sec,
            "durationSec": duration_sec,
        },
    ]

    for frame in frame_entries(frame_samples, frame_ocr):
        visual_events.append(
            {
                "eventType": "frame_sample",
                "timeSec": frame["time_sec"],
                "frameId": frame["frame_id"],
                "artifactPath": frame["artifact_path"],
                "ok": frame["ok"],
                "visual": frame["visual"],
            }
        )
    visual_events.extend(frame_transition_gate_events(frame_samples))
    visual_events.extend(frame_diff_vlm_events(frame_diff_vlm))

    audio_streams = [stream for stream in summary["streams"] if stream["codecType"] == "audio"] if summary else []
    audio_events = [
        {
            "eventType": "audio_reference",
            "startSec": 0.0,
            "endSec": duration_sec,
            "streamCount": len(audio_streams),
        }
    ]
    if audio_analysis:
        audio_events.append(
            {
                "eventType": "audio_derivative",
                "timeSec": 0.0,
                "artifactPath": audio_analysis.get("audioArtifact", {}).get("path"),
                "ok": bool(audio_analysis.get("audioArtifact", {}).get("ok")),
                "includedInDownloadZip": False,
            }
        )
        for candidate_event in audio_speech_events(audio_analysis):
            audio_events.append(candidate_event)

    activity_events = activity_timeline_events(activity_map)

    text_events = frame_ocr_events(frame_ocr)
    for segment in audio_text_summary(audio_analysis)["segments"]:
        text_events.append(
            {
                "eventType": "audio_transcript_segment",
                "startSec": segment.get("start_sec"),
                "endSec": segment.get("end_sec"),
                "text": segment.get("text") or "",
                "speaker": segment.get("speaker"),
                "speakerAssignment": segment.get("speakerAssignment"),
                "source": "audio_analysis",
            }
        )

    return {
        "schemaVersion": TIMELINE_SCHEMA_VERSION,
        "itemId": probe_record["itemId"],
        "generatedAt": generated_at,
        "timelineCoordinate": "source_video_relative_time",
        "sourceFingerprint": probe_record["sourceFingerprint"]["value"],
        "durationSec": duration_sec,
        "lanes": {
            "visual": visual_events,
            "audio": audio_events,
            "activity": activity_events,
            "text": text_events,
        },
    }


def build_convert_info(
    probe_record: dict[str, Any],
    frame_samples: dict[str, Any] | None,
    frame_ocr: dict[str, Any] | None,
    frame_diff_vlm: dict[str, Any] | None,
    audio_analysis: dict[str, Any] | None,
    activity_map: dict[str, Any] | None,
    paths: dict[str, str],
    generated_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    summary = probe_record["ffprobe"]["summary"]
    output_files = output_file_entries(paths)
    signature_material = {
        "itemId": probe_record["itemId"],
        "sourceFingerprint": probe_record["sourceFingerprint"]["value"],
        "pipelineVersion": PIPELINE_VERSION,
        "productVersion": __version__,
        "outputFiles": output_files,
    }
    frame_count = len(frame_entries(frame_samples, frame_ocr))
    text_blocks = text_blocks_from_frame_ocr(frame_ocr)
    speech_candidates = audio_analysis_speech_candidate_count(audio_analysis)
    frame_transition_gate = frame_transition_gate_summary(frame_samples)
    frame_diff_vlm_info = frame_diff_vlm_summary(frame_diff_vlm)
    return {
        "schemaVersion": CONVERT_INFO_SCHEMA_VERSION,
        "product": {
            "name": PRODUCT_NAME,
            "version": __version__,
        },
        "generatedAt": generated_at,
        "sourceFingerprint": probe_record["sourceFingerprint"],
        "sourceFileIdentity": probe_record["sourceIdentity"],
        "analysisInput": probe_record.get("analysisInput"),
        "mediaNormalization": probe_record.get("mediaNormalization"),
        "ffprobeVersion": probe_record["ffprobe"]["version"],
        "ffmpegVersion": frame_samples.get("ffmpeg", {}).get("version") if frame_samples else None,
        "pipelineVersion": PIPELINE_VERSION,
        "generationSignature": "sha256:" + sha256_hex(canonical_json(signature_material)),
        "samplingParameters": frame_samples.get("samplingParameters") if frame_samples else None,
        "imageProcessing": {
            "frameOcr": frame_ocr_summary(frame_ocr),
            "frameVisualFeatures": frame_visual_summary(frame_ocr),
            "frameTransitionGate": frame_transition_gate,
            "frameDiffVlm": frame_diff_vlm_info,
        },
        "audioProcessing": audio_analysis_summary(audio_analysis),
        "activityProcessing": activity_map_summary(activity_map),
        "outputFiles": output_files,
        "counts": {
            "videoStreams": summary["counts"]["videoStreams"] if summary else 0,
            "audioStreams": summary["counts"]["audioStreams"] if summary else 0,
            "frames": frame_count,
            "framesWithVisualFeatures": frame_visual_summary(frame_ocr)["framesWithVisualFeatures"],
            "frameTransitions": frame_transition_gate["transitions"],
            "frameTransitionsForVlm": frame_transition_gate["wouldSendToVlm"],
            "frameTransitionsSkipped": frame_transition_gate["wouldSkip"],
            "frameDiffVlmCandidates": frame_diff_vlm_info["candidateTransitions"],
            "frameDiffVlmAnalyzed": frame_diff_vlm_info["analyzedTransitions"],
            "frameDiffVlmChanged": frame_diff_vlm_info["changedTransitions"],
            "ocrTextBlocks": len(text_blocks),
            "audioSpeechCandidates": speech_candidates,
            "activitySegments": activity_map_summary(activity_map)["activeSegments"],
            "inactiveSegments": activity_map_summary(activity_map)["inactiveSegments"],
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "source_video_modified": False,
    }


def list_items(output_root_text: str) -> dict[str, Any]:
    output_root = resolve_configured_path(output_root_text)
    items_root = output_root / "items"
    items: list[dict[str, Any]] = []

    if items_root.is_dir():
        for item_dir in sorted((path for path in items_root.iterdir() if path.is_dir()), key=lambda path: path.name):
            record_path = item_dir / "video_record.json"
            record, warning = read_optional_json(record_path)
            if record is None:
                items.append(
                    {
                        "itemId": item_dir.name,
                        "ok": False,
                        "itemRoot": str(item_dir),
                        "videoRecordJson": str(record_path),
                        "sourcePath": None,
                        "durationSec": None,
                        "frameCount": 0,
                        "contactSheet": None,
                        "text": empty_text_summary(),
                        "audioAnalysis": empty_audio_list_summary(),
                        "warnings": [warning or "video_record_missing"],
                    }
                )
                continue

            items.append(item_summary(item_dir, record_path, record))

    return {
        "schemaVersion": ITEM_LIST_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "ok": True,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "counts": {
            "items": len(items),
        },
        "items": items,
    }


def download_items(output_root_text: str, item_ids: list[str] | None = None) -> dict[str, Any]:
    generated_at = utc_now_iso()
    output_root = resolve_configured_path(output_root_text)
    downloads_dir = output_root / "downloads"
    latest_dir = output_root / "latest"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = expand_item_ids(item_ids or [])
    item_dirs, missing_item_ids = selected_item_roots(output_root, selected_ids)
    archive_name = f"timeline-for-video-items-{timestamp_slug(generated_at)}.zip"
    archive_path = downloads_dir / archive_name
    latest_archive_path = latest_dir / "items.zip"
    latest_manifest_path = latest_dir / "download_manifest.json"
    output_files = [
        {"kind": "download_zip", "path": str(archive_path), "exists": True},
        {"kind": "latest_zip", "path": str(latest_archive_path), "exists": True},
        {"kind": "latest_manifest", "path": str(latest_manifest_path), "exists": True},
    ]
    manifest = {
        "schemaVersion": ITEM_DOWNLOAD_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "sourceVideosIncluded": False,
        "imageArtifactsIncluded": False,
        "requestedItemIds": selected_ids,
        "missingItemIds": missing_item_ids,
        "outputFiles": output_files,
        "items": [],
        "files": [],
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item_dir in item_dirs:
            item_files = [path for path in generated_item_files(item_dir) if path.is_file()]
            manifest["items"].append(
                {
                    "itemId": item_dir.name,
                    "itemRoot": str(item_dir),
                    "fileCount": len(item_files),
                }
            )
            for path in item_files:
                archive_path_text = path.relative_to(output_root).as_posix()
                archive.write(path, archive_path_text)
                manifest["files"].append(
                    {
                        "path": str(path),
                        "archivePath": archive_path_text,
                        "sizeBytes": path.stat().st_size,
                    }
                )
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    shutil.copy2(archive_path, latest_archive_path)
    write_json(latest_manifest_path, manifest)

    return {
        "schemaVersion": ITEM_DOWNLOAD_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ok": not missing_item_ids,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "archivePath": str(archive_path),
        "latestArchivePath": str(latest_archive_path),
        "latestManifestPath": str(latest_manifest_path),
        "sourceVideosIncluded": False,
        "imageArtifactsIncluded": False,
        "counts": {
            "items": len(item_dirs),
            "missingItems": len(missing_item_ids),
            "files": len(manifest["files"]),
            "bytes": archive_path.stat().st_size,
        },
        "requestedItemIds": selected_ids,
        "missingItemIds": missing_item_ids,
        "outputFiles": output_files,
        "items": manifest["items"],
    }


def remove_items(output_root_text: str, dry_run: bool = False, item_ids: list[str] | None = None) -> dict[str, Any]:
    output_root = resolve_configured_path(output_root_text)
    selected_ids = expand_item_ids(item_ids or [])
    targets = removal_targets(output_root, item_ids=selected_ids)
    missing_item_ids = targets["missingItemIds"]
    deleted_files: list[str] = []
    skipped_files: list[str] = []
    pruned_dirs: list[str] = []
    skipped_dirs: list[str] = []

    if not dry_run:
        for path in targets["files"]:
            if not safe_generated_path(output_root, path) or path.is_symlink():
                skipped_files.append(str(path))
                continue
            try:
                path.unlink()
                deleted_files.append(str(path))
            except FileNotFoundError:
                continue
            except OSError:
                skipped_files.append(str(path))

        for path in targets["directories"]:
            if not safe_generated_path(output_root, path) or path.is_symlink():
                skipped_dirs.append(str(path))
                continue
            try:
                path.rmdir()
                pruned_dirs.append(str(path))
            except FileNotFoundError:
                continue
            except OSError:
                skipped_dirs.append(str(path))

    return {
        "schemaVersion": ITEM_REMOVE_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": utc_now_iso(),
        "ok": not skipped_files and not skipped_dirs and not missing_item_ids,
        "dryRun": dry_run,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "sourceVideosRemoved": False,
        "counts": {
            "targetFiles": len(targets["files"]),
            "targetDirectories": len(targets["directories"]),
            "requestedItems": len(selected_ids),
            "missingItems": len(missing_item_ids),
            "deletedFiles": len(deleted_files),
            "prunedDirectories": len(pruned_dirs),
            "skippedFiles": len(skipped_files),
            "skippedDirectories": len(skipped_dirs),
        },
        "targets": {
            "files": [str(path) for path in targets["files"]],
            "directories": [str(path) for path in targets["directories"]],
        },
        "requestedItemIds": selected_ids,
        "missingItemIds": missing_item_ids,
        "deletedFiles": deleted_files,
        "prunedDirectories": pruned_dirs,
        "skippedFiles": skipped_files,
        "skippedDirectories": skipped_dirs,
    }


def item_summary(item_dir: Path, record_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    asset = record.get("asset") if isinstance(record.get("asset"), dict) else {}
    video_format = record.get("video", {}).get("format") if isinstance(record.get("video"), dict) else None
    frames = record.get("frames") if isinstance(record.get("frames"), list) else []
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    processing = record.get("processing") if isinstance(record.get("processing"), dict) else {}
    text = record.get("text") if isinstance(record.get("text"), dict) else {}
    visual = record.get("visual") if isinstance(record.get("visual"), dict) else {}
    audio = record.get("audio") if isinstance(record.get("audio"), dict) else {}
    audio_analysis = audio.get("analysis") if isinstance(audio.get("analysis"), dict) else {}
    warnings = processing.get("warnings") if isinstance(processing.get("warnings"), list) else []
    return {
        "itemId": record.get("record_id") or item_dir.name,
        "ok": True,
        "itemRoot": str(item_dir),
        "videoRecordJson": str(record_path),
        "sourcePath": asset.get("source_path"),
        "durationSec": video_format.get("durationSec") if isinstance(video_format, dict) else None,
        "frameCount": len(frames),
        "contactSheet": review.get("contact_sheet"),
        "text": text_list_summary(text),
        "visual": visual_list_summary(visual),
        "audioAnalysis": audio_list_summary(audio_analysis),
        "activity": activity_map_summary(record.get("activity") if isinstance(record.get("activity"), dict) else None),
        "warnings": warnings,
    }


def empty_text_summary() -> dict[str, Any]:
    return {
        "mode": None,
        "ocr": False,
        "transcription": False,
        "textBlockCount": 0,
        "fullTextLength": 0,
    }


def text_list_summary(text: dict[str, Any]) -> dict[str, Any]:
    blocks = text.get("blocks") if isinstance(text.get("blocks"), list) else []
    full_text = str(text.get("full_text") or "")
    return {
        "mode": text.get("mode"),
        "ocr": bool(text.get("ocr")),
        "transcription": bool(text.get("transcription")),
        "textBlockCount": len(blocks),
        "fullTextLength": len(full_text),
    }


def visual_list_summary(visual: dict[str, Any]) -> dict[str, Any]:
    gate = visual.get("frame_transition_gate") if isinstance(visual.get("frame_transition_gate"), dict) else {}
    vlm = visual.get("frame_diff_vlm") if isinstance(visual.get("frame_diff_vlm"), dict) else {}
    return {
        "frameTransitionGate": {
            "available": bool(gate.get("available")),
            "targetModel": gate.get("targetModel"),
            "transitions": int(gate.get("transitions") or 0),
            "wouldSendToVlm": int(gate.get("wouldSendToVlm") or 0),
            "wouldSkip": int(gate.get("wouldSkip") or 0),
            "failedTransitions": int(gate.get("failedTransitions") or 0),
            "byDecision": gate.get("byDecision") if isinstance(gate.get("byDecision"), dict) else {},
        },
        "frameDiffVlm": {
            "available": bool(vlm.get("available")),
            "status": vlm.get("status"),
            "modelId": vlm.get("modelId"),
            "candidateTransitions": int(vlm.get("candidateTransitions") or 0),
            "analyzedTransitions": int(vlm.get("analyzedTransitions") or 0),
            "changedTransitions": int(vlm.get("changedTransitions") or 0),
            "failedTransitions": int(vlm.get("failedTransitions") or 0),
        }
    }


def empty_audio_list_summary() -> dict[str, Any]:
    return {
        "available": False,
        "speechCandidates": 0,
        "diarizationStatus": None,
        "transcriptionStatus": None,
        "audioArtifact": None,
        "audioArtifactIncludedInDownloadZip": False,
    }


def audio_list_summary(audio_analysis: dict[str, Any]) -> dict[str, Any]:
    if not audio_analysis:
        return empty_audio_list_summary()
    artifact = audio_analysis.get("audioArtifact") if isinstance(audio_analysis.get("audioArtifact"), dict) else {}
    return {
        "available": bool(audio_analysis.get("available")),
        "speechCandidates": int(audio_analysis.get("speechCandidates") or 0),
        "diarizationStatus": audio_analysis.get("diarizationStatus"),
        "transcriptionStatus": audio_analysis.get("transcriptionStatus"),
        "audioArtifact": artifact.get("path"),
        "audioArtifactIncludedInDownloadZip": bool(artifact.get("includedInDownloadZip", False)),
    }


def item_roots(output_root: Path) -> list[Path]:
    items_root = output_root / "items"
    if not items_root.is_dir():
        return []
    return sorted((path for path in items_root.iterdir() if path.is_dir()), key=lambda path: path.name)


def selected_item_roots(output_root: Path, item_ids: list[str]) -> tuple[list[Path], list[str]]:
    roots = item_roots(output_root)
    if not item_ids:
        return roots, []
    by_id = {root.name: root for root in roots}
    selected = [by_id[item_id] for item_id in item_ids if item_id in by_id]
    missing = [item_id for item_id in item_ids if item_id not in by_id]
    return selected, missing


def expand_item_ids(values: list[str]) -> list[str]:
    item_ids: list[str] = []
    for value in values:
        for part in str(value).split(","):
            normalized = part.strip()
            if normalized and normalized not in item_ids:
                item_ids.append(normalized)
    return item_ids


def generated_item_files(
    item_dir: Path,
    include_audio_artifacts: bool = False,
    include_image_artifacts: bool = False,
) -> list[Path]:
    frames_dir = item_dir / "artifacts" / "frames"
    ocr_dir = item_dir / "artifacts" / "ocr"
    files = [
        item_dir / "video_record.json",
        item_dir / "timeline.json",
        item_dir / "convert_info.json",
        item_dir / "raw_outputs" / "ffprobe.json",
        item_dir / "raw_outputs" / "frame_samples.json",
        item_dir / "raw_outputs" / "frame_ocr.json",
        item_dir / "raw_outputs" / "frame_diff_vlm.json",
        item_dir / "raw_outputs" / "audio_analysis.json",
        item_dir / "raw_outputs" / "activity_map.json",
    ]
    if include_image_artifacts:
        files.append(item_dir / "artifacts" / "contact_sheet.jpg")
        if frames_dir.is_dir():
            files.extend(sorted(frames_dir.glob("frame-*.jpg")))
        if ocr_dir.is_dir():
            files.extend(sorted(ocr_dir.glob("*.jpg")))
    if include_audio_artifacts:
        files.append(item_dir / "artifacts" / "audio" / "source_audio.mp3")
    return files


def removal_targets(output_root: Path, item_ids: list[str] | None = None) -> dict[str, Any]:
    files: list[Path] = []
    directories: list[Path] = []
    selected_ids = item_ids or []
    selected_roots, missing_item_ids = selected_item_roots(output_root, selected_ids)

    for item_dir in selected_roots:
        files.extend(generated_removal_files(item_dir))
        directories.extend(generated_removal_directories(item_dir))

    if not selected_ids:
        downloads_dir = output_root / "downloads"
        if downloads_dir.is_dir():
            files.extend(sorted(downloads_dir.glob("timeline-for-video-items-*.zip")))
            directories.append(downloads_dir)

        latest_dir = output_root / "latest"
        if latest_dir.is_dir():
            files.extend(
                path
                for path in [
                    latest_dir / "items.zip",
                    latest_dir / "download_manifest.json",
                ]
                if path.exists()
            )
            directories.append(latest_dir)

        items_dir = output_root / "items"
        if items_dir.is_dir():
            directories.append(items_dir)

    return {
        "files": unique_existing_paths(files),
        "directories": sorted(unique_existing_paths(directories), key=lambda path: len(path.parts), reverse=True),
        "missingItemIds": missing_item_ids,
    }


def generated_removal_files(root: Path) -> list[Path]:
    if root.is_file() or root.is_symlink():
        return [root]
    if not root.is_dir():
        return []
    return sorted((path for path in root.rglob("*") if path.is_file() or path.is_symlink()), key=lambda path: str(path))


def generated_removal_directories(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    directories = [path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]
    directories.append(root)
    return directories


def unique_existing_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        unique.append(path)
    return unique


def safe_generated_path(output_root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(output_root.resolve(strict=False))
    except ValueError:
        return False
    return True


def timestamp_slug(value: str) -> str:
    return (
        value.replace("+00:00", "Z")
        .replace("-", "")
        .replace(":", "")
        .replace(".", "")
    )


def frame_entries(
    frame_samples: dict[str, Any] | None,
    frame_ocr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not frame_samples:
        return []

    frames_raw = frame_samples.get("frames")
    if not isinstance(frames_raw, list):
        return []

    ocr_by_frame = frame_ocr_by_frame_id(frame_ocr)
    frames: list[dict[str, Any]] = []
    for raw in frames_raw:
        if not isinstance(raw, dict):
            continue
        frame_id = raw.get("frameId")
        ocr = ocr_by_frame.get(str(frame_id)) if frame_id is not None else None
        frames.append(
            {
                "frame_id": frame_id,
                "time_sec": raw.get("timeSec"),
                "ok": bool(raw.get("ok")),
                "artifact_path": raw.get("outputPath"),
                "source": "frame_samples",
                "ocr": {
                    "has_text": bool(ocr and ocr.get("ocr", {}).get("has_text")),
                    "block_count": len(ocr.get("ocr", {}).get("blocks", [])) if ocr else 0,
                    "debug_overlay_path": ocr.get("debug_overlay_path") if ocr else None,
                },
                "visual": visual_entry_from_frame_ocr(ocr),
            }
        )
    return frames


def frame_ocr_by_frame_id(frame_ocr: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not frame_ocr:
        return {}
    frames = frame_ocr.get("frames")
    if not isinstance(frames, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for frame in frames:
        if isinstance(frame, dict) and frame.get("frameId"):
            result[str(frame["frameId"])] = frame
    return result


def text_blocks_from_frame_ocr(frame_ocr: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not frame_ocr:
        return []
    blocks: list[dict[str, Any]] = []
    for frame in frame_ocr.get("frames", []):
        if not isinstance(frame, dict):
            continue
        frame_id = frame.get("frameId")
        time_sec = frame.get("timeSec")
        ocr = frame.get("ocr") if isinstance(frame.get("ocr"), dict) else {}
        for block in ocr.get("blocks", []):
            if not isinstance(block, dict):
                continue
            blocks.append(
                {
                    "block_id": f"{frame_id}_{block.get('block_id')}",
                    "text": str(block.get("text") or ""),
                    "frame_id": frame_id,
                    "time_sec": time_sec,
                    "bbox_norm": block.get("bbox_norm", []),
                    "confidence": block.get("confidence", {}),
                    "evidence": {
                        "channel": "frame_ocr",
                        "stage": "ocr",
                        "frame_path": frame.get("source_frame_path"),
                        "debug_overlay_path": frame.get("debug_overlay_path"),
                    },
                }
            )
    return blocks


def frame_ocr_events(frame_ocr: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text_blocks_from_frame_ocr(frame_ocr):
        if not block["text"]:
            continue
        events.append(
            {
                "eventType": "frame_ocr_text",
                "timeSec": block["time_sec"],
                "frameId": block["frame_id"],
                "text": block["text"],
                "bbox_norm": block["bbox_norm"],
                "confidence": block["confidence"],
                "source": "frame_ocr",
            }
        )
    return events


def frame_transition_gate_events(frame_samples: dict[str, Any] | None) -> list[dict[str, Any]]:
    gate = frame_transition_gate_payload(frame_samples)
    if not gate:
        return []
    events: list[dict[str, Any]] = []
    for transition in gate.get("transitions", []):
        if not isinstance(transition, dict):
            continue
        events.append(
            {
                "eventType": "frame_transition_gate",
                "startSec": transition.get("fromTimeSec"),
                "endSec": transition.get("toTimeSec"),
                "fromFrameId": transition.get("fromFrameId"),
                "toFrameId": transition.get("toFrameId"),
                "ok": bool(transition.get("ok")),
                "decision": transition.get("decision"),
                "wouldSendToVlm": bool(transition.get("wouldSendToVlm")),
                "reasons": transition.get("reasons") if isinstance(transition.get("reasons"), list) else [],
                "metrics": {
                    "raw": transition.get("raw") if isinstance(transition.get("raw"), dict) else {},
                    "masked": transition.get("masked") if isinstance(transition.get("masked"), dict) else {},
                },
                "source": "frame_transition_gate",
                "targetModel": gate.get("targetModel"),
            }
        )
    return events


def frame_diff_vlm_events(frame_diff_vlm: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not frame_diff_vlm:
        return []
    model = frame_diff_vlm.get("model") if isinstance(frame_diff_vlm.get("model"), dict) else {}
    events: list[dict[str, Any]] = []
    for transition in frame_diff_vlm.get("transitions", []):
        if not isinstance(transition, dict):
            continue
        if transition.get("status") not in {"completed", "failed"}:
            continue
        events.append(
            {
                "eventType": "frame_diff_vlm",
                "startSec": transition.get("startSec"),
                "endSec": transition.get("endSec"),
                "fromFrameId": transition.get("fromFrameId"),
                "toFrameId": transition.get("toFrameId"),
                "ok": bool(transition.get("ok")),
                "status": transition.get("status"),
                "changed": transition.get("changed"),
                "changeLevel": transition.get("changeLevel"),
                "summary": transition.get("summary") or "",
                "differences": transition.get("differences") if isinstance(transition.get("differences"), list) else [],
                "confidence": transition.get("confidence"),
                "gate": transition.get("gate") if isinstance(transition.get("gate"), dict) else {},
                "inputFrames": transition.get("inputFrames") if isinstance(transition.get("inputFrames"), dict) else {},
                "modelId": model.get("modelId"),
                "source": "frame_diff_vlm",
            }
        )
    return events


def audio_speech_events(audio_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not audio_analysis:
        return []
    speech_activity = audio_analysis.get("speechActivity")
    if not isinstance(speech_activity, dict):
        return []
    events: list[dict[str, Any]] = []
    for candidate in speech_activity.get("speechCandidates", []):
        if not isinstance(candidate, dict):
            continue
        events.append(
            {
                "eventType": "audio_speech_candidate",
                "startSec": candidate.get("startSec"),
                "endSec": candidate.get("endSec"),
                "durationSec": candidate.get("durationSec"),
                "source": "ffmpeg_silencedetect",
            }
        )
    return events


def activity_timeline_events(activity_map: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not activity_map:
        return []
    activity = activity_map.get("activity") if isinstance(activity_map.get("activity"), dict) else activity_map
    if not isinstance(activity, dict):
        return []
    events: list[dict[str, Any]] = []
    for segment in activity.get("activeSegments", []):
        if not isinstance(segment, dict):
            continue
        events.append(
            {
                "eventType": "activity_candidate_interval",
                "startSec": segment.get("startSec"),
                "endSec": segment.get("endSec"),
                "durationSec": segment.get("durationSec"),
                "source": "activity_map",
            }
        )
    for segment in activity.get("inactiveSegments", []):
        if not isinstance(segment, dict):
            continue
        events.append(
            {
                "eventType": "activity_skipped_interval",
                "startSec": segment.get("startSec"),
                "endSec": segment.get("endSec"),
                "durationSec": segment.get("durationSec"),
                "reason": "silent_audio_and_static_visual_sentinel",
                "source": "activity_map",
            }
        )
    return events


def frame_ocr_summary(frame_ocr: dict[str, Any] | None) -> dict[str, Any]:
    if not frame_ocr:
        return {
            "available": False,
            "frameOcrJson": None,
            "ocrMode": None,
            "model": None,
            "framesWithText": 0,
            "framesWithVisualFeatures": 0,
            "textBlocks": 0,
        }
    return {
        "available": True,
        "frameOcrJson": frame_ocr.get("outputs", {}).get("frameOcrJson"),
        "ocrMode": frame_ocr.get("ocrMode"),
        "model": frame_ocr.get("ocrRuntime", {}).get("model"),
        "framesWithText": frame_ocr.get("counts", {}).get("framesWithText", 0),
        "framesWithVisualFeatures": frame_ocr.get("counts", {}).get("framesWithVisualFeatures", 0),
        "textBlocks": frame_ocr.get("counts", {}).get("textBlocks", 0),
    }


def visual_entry_from_frame_ocr(frame_ocr_entry: dict[str, Any] | None) -> dict[str, Any]:
    if not frame_ocr_entry or not isinstance(frame_ocr_entry.get("visual"), dict):
        return empty_visual_entry()
    visual = frame_ocr_entry["visual"]
    return {
        "available": bool(visual.get("available")),
        "quality": visual.get("quality") if isinstance(visual.get("quality"), dict) else {},
        "color_palette": visual.get("color_palette") if isinstance(visual.get("color_palette"), list) else [],
        "grid": visual.get("grid") if isinstance(visual.get("grid"), list) else [],
        "warnings": visual.get("warnings") if isinstance(visual.get("warnings"), list) else [],
    }


def empty_visual_entry() -> dict[str, Any]:
    return {
        "available": False,
        "quality": {},
        "color_palette": [],
        "grid": [],
        "warnings": [],
    }


def frame_visual_summary(frame_ocr: dict[str, Any] | None) -> dict[str, Any]:
    if not frame_ocr:
        return {
            "available": False,
            "framesWithVisualFeatures": 0,
            "quality": {"brightnessAvg": None, "contrastAvg": None},
        }
    frames = frame_ocr.get("frames") if isinstance(frame_ocr.get("frames"), list) else []
    return frame_visual_summary_from_entries(
        [
            {
                "visual": visual_entry_from_frame_ocr(frame if isinstance(frame, dict) else None),
            }
            for frame in frames
        ]
    )


def frame_transition_gate_payload(frame_samples: dict[str, Any] | None) -> dict[str, Any]:
    if not frame_samples or not isinstance(frame_samples.get("visualGate"), dict):
        return {}
    return frame_samples["visualGate"]


def frame_transition_gate_summary(frame_samples: dict[str, Any] | None) -> dict[str, Any]:
    gate = frame_transition_gate_payload(frame_samples)
    if not gate:
        return {
            "available": False,
            "targetModel": None,
            "strategy": None,
            "transitions": 0,
            "wouldSendToVlm": 0,
            "wouldSkip": 0,
            "failedTransitions": 0,
            "byDecision": {},
            "warnings": [],
        }
    counts = gate.get("counts") if isinstance(gate.get("counts"), dict) else {}
    return {
        "available": bool(gate.get("available")),
        "targetModel": gate.get("targetModel"),
        "strategy": gate.get("strategy"),
        "transitions": int(counts.get("transitions") or 0),
        "wouldSendToVlm": int(counts.get("wouldSendToVlm") or 0),
        "wouldSkip": int(counts.get("wouldSkip") or 0),
        "failedTransitions": int(counts.get("failedTransitions") or 0),
        "byDecision": counts.get("byDecision") if isinstance(counts.get("byDecision"), dict) else {},
        "warnings": gate.get("warnings") if isinstance(gate.get("warnings"), list) else [],
    }


def frame_diff_vlm_summary(frame_diff_vlm: dict[str, Any] | None) -> dict[str, Any]:
    if not frame_diff_vlm:
        return {
            "available": False,
            "status": None,
            "mode": None,
            "modelId": None,
            "candidateTransitions": 0,
            "analyzedTransitions": 0,
            "skippedTransitions": 0,
            "failedTransitions": 0,
            "changedTransitions": 0,
            "unchangedTransitions": 0,
            "warnings": [],
        }
    counts = frame_diff_vlm.get("counts") if isinstance(frame_diff_vlm.get("counts"), dict) else {}
    model = frame_diff_vlm.get("model") if isinstance(frame_diff_vlm.get("model"), dict) else {}
    analyzed = int(counts.get("analyzedTransitions") or 0)
    return {
        "available": analyzed > 0,
        "status": frame_diff_vlm.get("status"),
        "mode": frame_diff_vlm.get("mode"),
        "modelId": model.get("modelId"),
        "candidateTransitions": int(counts.get("candidateTransitions") or 0),
        "analyzedTransitions": analyzed,
        "skippedTransitions": int(counts.get("skippedTransitions") or 0),
        "failedTransitions": int(counts.get("failedTransitions") or 0),
        "changedTransitions": int(counts.get("changedTransitions") or 0),
        "unchangedTransitions": int(counts.get("unchangedTransitions") or 0),
        "warnings": frame_diff_vlm.get("warnings") if isinstance(frame_diff_vlm.get("warnings"), list) else [],
    }


def frame_visual_summary_from_entries(frames: list[dict[str, Any]]) -> dict[str, Any]:
    visual_entries = [
        frame.get("visual", {})
        for frame in frames
        if isinstance(frame.get("visual"), dict) and frame.get("visual", {}).get("available")
    ]
    brightness_values = [
        float(entry.get("quality", {}).get("brightness"))
        for entry in visual_entries
        if entry.get("quality", {}).get("brightness") is not None
    ]
    contrast_values = [
        float(entry.get("quality", {}).get("contrast"))
        for entry in visual_entries
        if entry.get("quality", {}).get("contrast") is not None
    ]
    return {
        "available": bool(visual_entries),
        "framesWithVisualFeatures": len(visual_entries),
        "quality": {
            "brightnessAvg": round(sum(brightness_values) / len(brightness_values), 3) if brightness_values else None,
            "contrastAvg": round(sum(contrast_values) / len(contrast_values), 3) if contrast_values else None,
        },
    }


def audio_analysis_summary(audio_analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not audio_analysis:
        return {
            "available": False,
            "audioAnalysisJson": None,
            "audioArtifact": None,
            "speechCandidates": 0,
            "diarizationStatus": None,
            "transcriptionStatus": None,
        }
    return {
        "available": True,
        "audioAnalysisJson": audio_analysis.get("outputs", {}).get("audioAnalysisJson"),
        "audioArtifact": audio_analysis.get("audioArtifact", {}),
        "speechCandidates": audio_analysis_speech_candidate_count(audio_analysis),
        "diarizationStatus": audio_analysis.get("diarization", {}).get("status"),
        "transcriptionStatus": audio_analysis.get("transcription", {}).get("status"),
    }


def audio_text_summary(audio_analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not audio_analysis or not isinstance(audio_analysis.get("text"), dict):
        return {
            "mode": None,
            "readableText": "",
            "segments": [],
            "warnings": [],
        }
    text = audio_analysis["text"]
    return {
        "mode": text.get("mode"),
        "readableText": str(text.get("readableText") or ""),
        "segments": text.get("segments") if isinstance(text.get("segments"), list) else [],
        "warnings": text.get("warnings") if isinstance(text.get("warnings"), list) else [],
    }


def audio_analysis_speech_candidate_count(audio_analysis: dict[str, Any] | None) -> int:
    if not audio_analysis:
        return 0
    return int(audio_analysis.get("speechActivity", {}).get("counts", {}).get("speechCandidates", 0) or 0)


def activity_map_summary(activity_map: dict[str, Any] | None) -> dict[str, Any]:
    if not activity_map:
        return {
            "available": False,
            "activityMapJson": None,
            "strategy": None,
            "activeSegments": 0,
            "inactiveSegments": 0,
            "activeSec": 0.0,
            "inactiveSec": 0.0,
            "activeRatio": 0.0,
            "estimatedReductionRatio": None,
            "visualSentinels": 0,
        }
    if "activity" not in activity_map and (
        "activityMapJson" in activity_map
        or "activeSec" in activity_map
        or "activeSegments" in activity_map
    ):
        return {
            "available": bool(activity_map.get("available")),
            "activityMapJson": activity_map.get("activityMapJson"),
            "strategy": activity_map.get("strategy"),
            "activeSegments": segment_count_summary(None, activity_map.get("activeSegments")),
            "inactiveSegments": segment_count_summary(None, activity_map.get("inactiveSegments")),
            "activeSec": float(activity_map.get("activeSec") or 0.0),
            "inactiveSec": float(activity_map.get("inactiveSec") or 0.0),
            "activeRatio": float(activity_map.get("activeRatio") or 0.0),
            "estimatedReductionRatio": activity_map.get("estimatedReductionRatio"),
            "visualSentinels": int(activity_map.get("visualSentinels") or 0),
        }
    activity = activity_map.get("activity") if isinstance(activity_map.get("activity"), dict) else activity_map
    counts = activity.get("counts") if isinstance(activity.get("counts"), dict) else {}
    outputs = activity_map.get("outputs") if isinstance(activity_map.get("outputs"), dict) else {}
    return {
        "available": True,
        "activityMapJson": outputs.get("activityMapJson"),
        "strategy": activity.get("strategy"),
        "activeSegments": segment_count_summary(counts.get("activeSegments"), activity.get("activeSegments")),
        "inactiveSegments": segment_count_summary(counts.get("inactiveSegments"), activity.get("inactiveSegments")),
        "activeSec": float(activity.get("activeSec") or 0.0),
        "inactiveSec": float(activity.get("inactiveSec") or 0.0),
        "activeRatio": float(activity.get("activeRatio") or 0.0),
        "estimatedReductionRatio": activity.get("estimatedReductionRatio"),
        "visualSentinels": int(counts.get("visualSentinels") or 0),
    }


def segment_count_summary(count_value: Any, segment_value: Any) -> int:
    if isinstance(count_value, int):
        return count_value
    if isinstance(segment_value, int):
        return segment_value
    if isinstance(segment_value, list):
        return len(segment_value)
    return 0


def output_file_entries(paths: dict[str, str]) -> list[dict[str, Any]]:
    keys = [
        ("video_record", "videoRecordJson"),
        ("timeline", "timelineJson"),
        ("convert_info", "convertInfoJson"),
        ("ffprobe_raw", "ffprobeJson"),
        ("frame_samples", "frameSamplesJson"),
        ("frame_ocr", "frameOcrJson"),
        ("frame_diff_vlm", "frameDiffVlmJson"),
        ("audio_analysis", "audioAnalysisJson"),
        ("activity_map", "activityMapJson"),
        ("contact_sheet", "contactSheet"),
        ("frames_dir", "framesDir"),
        ("audio_artifact", "audioArtifact"),
    ]
    written_by_refresh = {"video_record", "timeline", "convert_info", "ffprobe_raw"}
    return [
        {
            "kind": kind,
            "path": paths[key],
            "exists": True if kind in written_by_refresh else Path(paths[key]).exists(),
        }
        for kind, key in keys
    ]


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
