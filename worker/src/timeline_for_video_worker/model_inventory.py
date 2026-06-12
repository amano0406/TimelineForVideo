from __future__ import annotations

import hashlib
import json
import importlib.util
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from . import __version__
from .audio_analysis import (
    SILENCE_DETECT_BACKEND,
    SILENCE_DETECT_MODEL_ID,
)
from .audio_models import (
    DIARIZATION_BACKEND,
    DIARIZATION_MODEL_ID,
    TRANSCRIPTION_BACKEND,
    TRANSCRIPTION_MODEL_ALIAS,
    TRANSCRIPTION_MODEL_ID,
    audio_model_runtime_status,
    normalize_compute_mode,
)
from .frame_diff_vlm import DEFAULT_FRAME_DIFF_VLM_MODEL_ID, frame_diff_vlm_runtime_status
from .frame_ocr import OCR_MODEL_ID, ocr_runtime_status
from .items import PIPELINE_VERSION
from .probe import ffprobe_version, utc_now_iso
from .sampling import ffmpeg_version
from .settings import PRODUCT_NAME, load_huggingface_token


MODEL_INVENTORY_SCHEMA_VERSION = "timeline_for_video.model_inventory.v1"
HUGGING_FACE_MODEL_URL = "https://huggingface.co/{model_id}"
HUGGING_FACE_MODEL_API_URL = "https://huggingface.co/api/models/{model_id}"


@dataclass(frozen=True)
class ModelInventoryRow:
    role: str
    display_name: str
    source: str
    model_id: str
    backend: str
    required: bool
    configured: bool
    requires_huggingface_token: bool
    requires_access_approval: bool
    url: str | None = None
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_inventory(
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    ocr_mode: str = "auto",
    settings: dict[str, Any] | None = None,
    include_remote: bool = False,
) -> dict[str, Any]:
    generated_at = utc_now_iso()
    settings_payload = settings or {}
    compute_mode = normalize_compute_mode(settings_payload.get("computeMode"))
    ffprobe_status = ffprobe_version(ffprobe_bin)
    ffmpeg_status = ffmpeg_version(ffmpeg_bin)
    ocr_status = ocr_runtime_status(ocr_mode)
    visual_status = visual_feature_runtime_status()
    frame_diff_vlm_status = frame_diff_vlm_runtime_status()
    audio_model_status = audio_model_runtime_status(settings)
    audio_model_required = True
    components = [
        local_component(
            component_id="ffprobe_metadata",
            display_name="ffprobe metadata",
            role="Read source video metadata.",
            ready=ffprobe_status["ok"],
            backend="ffprobe",
            runtime=ffprobe_status,
        ),
        local_component(
            component_id="bounded_frame_sampling",
            display_name="bounded frame sampling",
            role="Extract bounded JPEG frame evidence from source videos.",
            ready=ffmpeg_status["ok"],
            backend="ffmpeg",
            runtime=ffmpeg_status,
        ),
        local_component(
            component_id="frame_ocr",
            display_name="frame OCR",
            role="Run local OCR over generated frame artifacts.",
            ready=ocr_status["ok"],
            backend="pytesseract",
            model_id=OCR_MODEL_ID,
            runtime=ocr_status,
            reference_product="TimelineForImage",
        ),
        local_component(
            component_id="frame_visual_features",
            display_name="frame visual features",
            role="Measure brightness, contrast, dominant colors, and a 3x3 color grid over generated frame artifacts.",
            ready=visual_status["ok"],
            backend="Pillow",
            runtime=visual_status,
            reference_product="TimelineForImage",
        ),
        local_component(
            component_id="frame_transition_gate",
            display_name="frame transition gate",
            role="Classify adjacent sampled frame transitions before optional Qwen3.5-class VLM processing.",
            ready=visual_status["ok"],
            backend="Pillow",
            model_id="Qwen/Qwen3.5-4B target gate",
            runtime=visual_status,
        ),
        optional_model_component(
            component_id="frame_diff_vlm",
            display_name="frame diff VLM",
            role="Describe meaningful differences between adjacent sampled frames that pass the visual gate.",
            backend="transformers",
            model_id=DEFAULT_FRAME_DIFF_VLM_MODEL_ID,
            ready=frame_diff_vlm_status["ready"],
            runtime=frame_diff_vlm_status,
        ),
        local_component(
            component_id="audio_derivative",
            display_name="audio derivative",
            role="Create a local MP3 evidence artifact under outputRoot.",
            ready=ffmpeg_status["ok"],
            backend="ffmpeg",
            runtime=ffmpeg_status,
        ),
        local_component(
            component_id="speech_candidate_detection",
            display_name="speech candidate detection",
            role="Detect non-silent audio ranges for timeline evidence.",
            ready=ffmpeg_status["ok"],
            backend=SILENCE_DETECT_BACKEND,
            model_id=SILENCE_DETECT_MODEL_ID,
            runtime=ffmpeg_status,
            reference_product="TimelineForAudio",
        ),
        audio_model_component(
            component_id="speaker_diarization",
            display_name="speaker diarization",
            role="Run TimelineForAudio-compatible speaker diarization over generated audio.",
            backend=DIARIZATION_BACKEND,
            model_id=DIARIZATION_MODEL_ID,
            ready=audio_model_status["diarization"]["ready"],
            runtime=audio_model_status,
            required=audio_model_required,
            requires_access_approval=True,
        ),
        audio_model_component(
            component_id="speech_transcription",
            display_name="speech transcription",
            role="Run Whisper transcription over generated audio without modifying text during speaker assignment.",
            backend=TRANSCRIPTION_BACKEND,
            model_id=TRANSCRIPTION_MODEL_ID,
            ready=audio_model_status["transcription"]["ready"],
            runtime=audio_model_status,
            required=audio_model_required,
        ),
    ]
    model_rows = [row.to_dict() for row in configured_model_rows()]
    if include_remote:
        token = load_huggingface_token(settings)
        for row in model_rows:
            if row.get("source") != "huggingface":
                continue
            row["huggingface"] = fetch_huggingface_model_metadata(
                str(row.get("model_id") or ""),
                token=token,
            )

    required_components = [component for component in components if component["execution"]["required"]]
    audio_model_components = [component for component in components if component["execution"]["kind"] == "audio_model"]
    return {
        "schema_version": 1,
        "schemaVersion": MODEL_INVENTORY_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generated_at": generated_at,
        "generatedAt": generated_at,
        "pipeline": {
            "name": PRODUCT_NAME,
            "pipeline_version": PIPELINE_VERSION,
            "compute_mode": compute_mode,
            "generation_signature": build_generation_signature(compute_mode=compute_mode),
        },
        "models": model_rows,
        "ok": all(component["runtime"]["ready"] for component in required_components),
        "sourceVideoSafety": {
            "sourceVideoModified": False,
            "sourceVideosIncludedInZip": False,
            "generatedAudioIncludedInZip": False,
            "externalAnalysisApiUsed": False,
        },
        "counts": {
            "components": len(components),
            "requiredComponents": len(required_components),
            "readyRequiredComponents": sum(1 for component in required_components if component["runtime"]["ready"]),
            "audioModelComponents": len(audio_model_components),
            "readyAudioModelComponents": sum(1 for component in audio_model_components if component["runtime"]["ready"]),
        },
        "components": components,
    }


def build_generation_signature(*, compute_mode: str) -> str:
    payload = {
        "pipeline": PRODUCT_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "compute_mode": normalize_compute_mode(compute_mode),
        "frame_ocr": {
            "backend": "pytesseract",
            "model_id": OCR_MODEL_ID,
        },
        "visual_features": {
            "backend": "Pillow",
        },
        "frame_transition_gate": {
            "backend": "Pillow",
            "target_model": "Qwen/Qwen3.5-4B",
        },
        "frame_diff_vlm": {
            "backend": "transformers",
            "model_id": DEFAULT_FRAME_DIFF_VLM_MODEL_ID,
            "mode": "auto",
        },
        "transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "model_id": TRANSCRIPTION_MODEL_ID,
            "model_alias": TRANSCRIPTION_MODEL_ALIAS,
            "language": "auto",
        },
        "diarization": {
            "required": True,
            "model_id": DIARIZATION_MODEL_ID,
        },
        "vad": {
            "backend": SILENCE_DETECT_BACKEND,
            "model_id": SILENCE_DETECT_MODEL_ID,
        },
        "artifact": {
            "schema": "timeline_for_video.video_record.v1",
            "path": "video_record.json",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def configured_model_rows() -> list[ModelInventoryRow]:
    return [
        ModelInventoryRow(
            role="speaker_diarization",
            display_name="Speaker diarization",
            source="huggingface",
            model_id=DIARIZATION_MODEL_ID,
            backend=DIARIZATION_BACKEND,
            required=True,
            configured=True,
            requires_huggingface_token=True,
            requires_access_approval=True,
            url=HUGGING_FACE_MODEL_URL.format(model_id=DIARIZATION_MODEL_ID),
            notes=[
                "Used to assign mechanical speaker labels such as SPEAKER_00.",
                "Access approval on Hugging Face is required before processing.",
            ],
        ),
        ModelInventoryRow(
            role="speech_transcription",
            display_name="Speech transcription",
            source="huggingface",
            model_id=TRANSCRIPTION_MODEL_ID,
            backend=TRANSCRIPTION_BACKEND,
            required=True,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            url=HUGGING_FACE_MODEL_URL.format(model_id=TRANSCRIPTION_MODEL_ID),
            notes=[
                f"Uses {TRANSCRIPTION_MODEL_ALIAS} to create readable transcript segments.",
                "Speaker labels are assigned from diarization without changing Whisper text.",
            ],
        ),
        ModelInventoryRow(
            role="frame_ocr",
            display_name="Frame OCR",
            source="local_tool",
            model_id=OCR_MODEL_ID,
            backend="pytesseract",
            required=True,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            notes=[
                "Runs local OCR over generated frame artifacts.",
                "This follows the TimelineForImage-compatible frame OCR path.",
            ],
        ),
        ModelInventoryRow(
            role="frame_diff_vlm",
            display_name="Frame diff VLM",
            source="huggingface",
            model_id=DEFAULT_FRAME_DIFF_VLM_MODEL_ID,
            backend="transformers",
            required=False,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            url=HUGGING_FACE_MODEL_URL.format(model_id=DEFAULT_FRAME_DIFF_VLM_MODEL_ID),
            notes=[
                "Runs only for adjacent frame transitions selected by the cheap visual gate.",
                "No external analysis API is used; inference runs in the local worker when dependencies are installed.",
            ],
        ),
        ModelInventoryRow(
            role="speech_candidate_detection",
            display_name="Speech candidate detection",
            source="local_tool",
            model_id=SILENCE_DETECT_MODEL_ID,
            backend=SILENCE_DETECT_BACKEND,
            required=True,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            notes=[
                "This is an ffmpeg silencedetect configuration, not a Hugging Face model.",
            ],
        ),
    ]


def fetch_huggingface_model_metadata(
    model_id: str,
    *,
    token: str | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    if not model_id:
        return {
            "remote_status": "skipped",
            "error": "model_id is empty.",
        }
    request = urllib.request.Request(
        HUGGING_FACE_MODEL_API_URL.format(model_id=model_id),
        headers=huggingface_headers(token),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "remote_status": "error",
            "http_status": exc.code,
            "error": f"Hugging Face returned HTTP {exc.code}.",
        }
    except Exception as exc:
        return {
            "remote_status": "error",
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "remote_status": "error",
            "error": "Hugging Face response was not a JSON object.",
        }
    return summarize_huggingface_model_payload(payload)


def huggingface_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "TimelineForVideo/1.0",
    }
    value = str(token or "").strip()
    if value:
        headers["Authorization"] = f"Bearer {value}"
    return headers


def summarize_huggingface_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    card_data = payload.get("cardData") if isinstance(payload.get("cardData"), dict) else {}
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    license_value = card_data.get("license") or license_from_tags(tags)
    return {
        "remote_status": "ok",
        "id": payload.get("id"),
        "sha": payload.get("sha"),
        "last_modified": payload.get("lastModified"),
        "private": payload.get("private"),
        "gated": payload.get("gated"),
        "disabled": payload.get("disabled"),
        "pipeline_tag": payload.get("pipeline_tag"),
        "library_name": payload.get("library_name") or card_data.get("library_name"),
        "license": license_value,
        "license_source": "cardData.license" if card_data.get("license") else "tags",
        "tags": tags,
        "downloads": payload.get("downloads"),
        "likes": payload.get("likes"),
        "model_card_url": HUGGING_FACE_MODEL_URL.format(model_id=str(payload.get("id") or "")),
    }


def license_from_tags(tags: list[Any]) -> str | None:
    for tag in tags:
        text = str(tag or "")
        if text.startswith("license:"):
            return text.split(":", 1)[1] or None
    return None


def visual_feature_runtime_status() -> dict[str, Any]:
    ready = importlib.util.find_spec("PIL") is not None
    return {
        "ok": ready,
        "module": "PIL",
        "message": "Pillow is ready." if ready else "Pillow is not available.",
    }


def local_component(
    *,
    component_id: str,
    display_name: str,
    role: str,
    ready: bool,
    backend: str,
    runtime: dict[str, Any],
    model_id: str | None = None,
    reference_product: str | None = None,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "displayName": display_name,
        "role": role,
        "backend": backend,
        "modelId": model_id,
        "referenceProduct": reference_product,
        "execution": {
            "kind": "local",
            "required": True,
            "implementedInVideoWorker": True,
            "sourceSharing": False,
        },
        "runtime": {
            "ready": bool(ready),
            "details": runtime,
        },
    }


def audio_model_component(
    *,
    component_id: str,
    display_name: str,
    role: str,
    backend: str,
    model_id: str,
    ready: bool,
    runtime: dict[str, Any],
    required: bool,
    requires_access_approval: bool = False,
) -> dict[str, Any]:
    details = dict(runtime)
    details["audioModelsReady"] = bool(details.pop("ready", False))
    details["componentReady"] = bool(ready)
    details["requiresAccessApproval"] = requires_access_approval
    return {
        "id": component_id,
        "displayName": display_name,
        "role": role,
        "backend": backend,
        "modelId": model_id,
        "referenceProduct": "TimelineForAudio",
        "execution": {
            "kind": "audio_model",
            "required": required,
            "implementedInVideoWorker": True,
            "sourceSharing": False,
            "status": "required" if required else "runs_when_dependencies_and_token_are_available",
        },
        "runtime": {
            "ready": bool(ready),
            "details": details,
        },
    }


def optional_model_component(
    *,
    component_id: str,
    display_name: str,
    role: str,
    backend: str,
    model_id: str,
    ready: bool,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": component_id,
        "displayName": display_name,
        "role": role,
        "backend": backend,
        "modelId": model_id,
        "referenceProduct": None,
        "execution": {
            "kind": "vision_model",
            "required": False,
            "implementedInVideoWorker": True,
            "sourceSharing": False,
            "status": "runs_when_dependencies_are_available",
        },
        "runtime": {
            "ready": bool(ready),
            "details": runtime,
        },
    }
