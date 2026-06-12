from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import gc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from .probe import utc_now_iso
from .settings import load_huggingface_token


AUDIO_MODEL_RESULT_SCHEMA_VERSION = "timeline_for_video.audio_model_result.v1"
AUDIO_MODEL_MODES = ("auto", "off", "required")
DIARIZATION_BACKEND = "pyannote.audio"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
TRANSCRIPTION_BACKEND = "faster-whisper"
TRANSCRIPTION_MODEL_ID = "Systran/faster-whisper-large-v3"
TRANSCRIPTION_MODEL_ALIAS = "faster_whisper_large_v3"
DIARIZATION_ACTIVITY_PADDING_SEC = 1.0
DIARIZATION_ACTIVITY_MERGE_GAP_SEC = 2.0
MAX_DIARIZATION_ACTIVITY_SPANS = 48
TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD = "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"
WORKER_FLAVOR_ENV = "TIMELINE_FOR_VIDEO_WORKER_FLAVOR"
AUDIO_MODEL_IN_PROCESS_ENV = "TIMELINE_FOR_VIDEO_AUDIO_MODELS_IN_PROCESS"
NONFATAL_DIARIZATION_STATUSES = {"ok", "no_speaker_turns"}
NONFATAL_TRANSCRIPTION_STATUSES = {"ok", "no_segments"}
MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC = 0.1
HIGH_NO_SPEECH_PROBABILITY = 0.6
LOW_TRANSCRIPT_CONFIDENCE = -0.6
KNOWN_SILENCE_HALLUCINATION_PHRASES = {
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "ありがとうございました",
    "Thank you for watching",
    "Thanks for watching",
}


def normalize_audio_model_mode(mode: str | None) -> str:
    normalized = str(mode or "required").strip().casefold()
    if normalized not in AUDIO_MODEL_MODES:
        raise ValueError(f"audio model mode must be one of: {', '.join(AUDIO_MODEL_MODES)}")
    return normalized


def normalize_compute_mode(mode: str | None) -> str:
    normalized = str(mode or "gpu").strip().casefold()
    if normalized not in {"cpu", "gpu"}:
        raise ValueError("compute mode must be one of: cpu, gpu")
    return normalized


def audio_model_runtime_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    compute_mode = normalize_compute_mode(settings.get("computeMode") if settings else None)
    modules = {
        "pyannote.audio": module_available("pyannote.audio"),
        "torch": module_available("torch"),
        "torchaudio": module_available("torchaudio"),
        "faster_whisper": module_available("faster_whisper"),
        "ctranslate2": module_available("ctranslate2"),
        "huggingface_hub": module_available("huggingface_hub"),
    }
    token_ready = bool(load_huggingface_token(settings))
    compute = compute_runtime_status(compute_mode, modules)
    ready = token_ready and all(modules.values()) and compute["ready"]
    return {
        "ready": ready,
        "computeMode": compute_mode,
        "compute": compute,
        "tokenConfigured": token_ready,
        "modules": modules,
        "diarization": {
            "backend": DIARIZATION_BACKEND,
            "modelId": DIARIZATION_MODEL_ID,
            "ready": token_ready and modules["pyannote.audio"] and modules["torch"] and modules["torchaudio"] and compute["ready"],
        },
        "transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "modelId": TRANSCRIPTION_MODEL_ID,
            "modelAlias": TRANSCRIPTION_MODEL_ALIAS,
            "ready": compute["ready"] and all(
                modules[name]
                for name in ["faster_whisper", "ctranslate2", "huggingface_hub"]
            ),
        },
    }


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def compute_runtime_status(compute_mode: str, modules: dict[str, bool]) -> dict[str, Any]:
    worker_flavor = str(os.getenv(WORKER_FLAVOR_ENV) or "cpu").strip().casefold()
    if compute_mode == "cpu":
        return {
            "ready": True,
            "mode": "cpu",
            "workerFlavor": worker_flavor,
            "torchCudaAvailable": None,
            "ctranslate2CudaDeviceCount": None,
            "warnings": [],
        }

    warnings: list[str] = []
    if worker_flavor != "gpu":
        warnings.append("computeMode gpu requires the GPU worker flavor.")

    torch_cuda_available = False
    if modules.get("torch"):
        try:
            import torch

            torch_cuda_available = bool(getattr(torch.cuda, "is_available", lambda: False)())
        except Exception as exc:
            warnings.append(f"torch_cuda_check_failed:{exc}")
    else:
        warnings.append("torch is not available.")

    if not torch_cuda_available:
        warnings.append("CUDA is not available to torch.")

    ctranslate2_cuda_device_count = None
    if modules.get("ctranslate2"):
        try:
            import ctranslate2

            ctranslate2_cuda_device_count = int(getattr(ctranslate2, "get_cuda_device_count", lambda: 0)())
        except Exception as exc:
            warnings.append(f"ctranslate2_cuda_check_failed:{exc}")
    else:
        warnings.append("ctranslate2 is not available.")

    if not ctranslate2_cuda_device_count:
        warnings.append("CUDA is not available to CTranslate2.")

    return {
        "ready": not warnings,
        "mode": "gpu",
        "workerFlavor": worker_flavor,
        "torchCudaAvailable": torch_cuda_available,
        "ctranslate2CudaDeviceCount": ctranslate2_cuda_device_count,
        "warnings": warnings,
    }


def run_audio_reference_models(
    *,
    audio_path: Path,
    speech_candidates: list[dict[str, float]],
    source_name: str,
    settings: dict[str, Any],
    mode: str | None = None,
) -> dict[str, Any]:
    return _run_audio_reference_models_direct(
        audio_path=audio_path,
        speech_candidates=speech_candidates,
        source_name=source_name,
        settings=settings,
        mode=mode,
    )


def run_audio_reference_models_isolated(
    *,
    audio_path: Path,
    speech_candidates: list[dict[str, float]],
    source_name: str,
    settings: dict[str, Any],
    mode: str | None = None,
) -> dict[str, Any]:
    model_mode = normalize_audio_model_mode(mode)
    if model_mode == "off" or os.getenv(AUDIO_MODEL_IN_PROCESS_ENV) == "1":
        return _run_audio_reference_models_direct(
            audio_path=audio_path,
            speech_candidates=speech_candidates,
            source_name=source_name,
            settings=settings,
            mode=model_mode,
        )

    with tempfile.TemporaryDirectory(prefix="timeline-video-audio-model-") as temp_dir:
        temp_root = Path(temp_dir)
        request_path = temp_root / "request.json"
        result_path = temp_root / "result.json"
        stdout_path = temp_root / "stdout.log"
        stderr_path = temp_root / "stderr.log"
        request_path.write_text(
            json.dumps(
                {
                    "audioPath": str(audio_path),
                    "speechCandidates": speech_candidates,
                    "sourceName": source_name,
                    "settings": settings,
                    "mode": model_mode,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            env = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[1])
            current_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = source_root if not current_pythonpath else source_root + os.pathsep + current_pythonpath
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "timeline_for_video_worker.audio_model_runner",
                    str(request_path),
                    str(result_path),
                ],
                check=False,
                stdout=stdout,
                stderr=stderr,
                env=env,
            )

        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(result, dict):
                    if completed.returncode != 0:
                        result["ok"] = False
                        result.setdefault("warnings", []).append(f"audio_model_subprocess_exit:{completed.returncode}")
                        append_subprocess_log_warning(result, stderr_path)
                    return result
            except json.JSONDecodeError:
                pass

        error = f"audio_model_subprocess_failed_exit:{completed.returncode}"
        result = failed_audio_model_process_result(
            audio_path=audio_path,
            speech_candidates=speech_candidates,
            source_name=source_name,
            settings=settings,
            mode=model_mode,
            error=error,
        )
        append_subprocess_log_warning(result, stderr_path)
        return result


def _run_audio_reference_models_direct(
    *,
    audio_path: Path,
    speech_candidates: list[dict[str, float]],
    source_name: str,
    settings: dict[str, Any],
    mode: str | None = None,
) -> dict[str, Any]:
    model_mode = normalize_audio_model_mode(mode)
    compute_mode = normalize_compute_mode(settings.get("computeMode"))
    generated_at = utc_now_iso()
    runtime = audio_model_runtime_status(settings)

    result = base_audio_model_result(
        model_mode=model_mode,
        compute_mode=compute_mode,
        runtime=runtime,
        generated_at=generated_at,
    )

    if model_mode == "off":
        result["diarization"] = empty_diarization("disabled")
        result["transcription"] = empty_transcription("disabled")
        result["warnings"].append("audio_model_mode_off")
        return result

    if not audio_path.exists():
        result["ok"] = False
        result["diarization"] = empty_diarization("audio_missing")
        result["transcription"] = empty_transcription("audio_missing")
        result["warnings"].append(f"audio_model_input_missing:{audio_path}")
        return result

    token = load_huggingface_token(settings)
    if not token:
        result["ok"] = model_mode != "required"
        result["diarization"] = empty_diarization("not_configured")
        result["transcription"] = empty_transcription("not_configured")
        result["warnings"].append("hugging_face_token_missing")
        return result

    missing = [name for name, available in runtime["modules"].items() if not available]
    if missing:
        result["ok"] = model_mode != "required"
        result["diarization"] = empty_diarization("dependencies_missing")
        result["transcription"] = empty_transcription("dependencies_missing")
        result["warnings"].append("missing_audio_model_dependencies:" + ",".join(sorted(missing)))
        return result

    if not runtime["compute"]["ready"]:
        result["ok"] = False
        result["diarization"] = empty_diarization("compute_runtime_unavailable")
        result["transcription"] = empty_transcription("compute_runtime_unavailable")
        result["warnings"].extend(f"gpu_runtime_unavailable:{warning}" for warning in runtime["compute"]["warnings"])
        return result

    try:
        diarization = run_diarization(audio_path, token, compute_mode, source_name, speech_candidates)
        result["diarization"] = diarization
        release_cached_audio_models()
    except Exception as exc:
        result["ok"] = False
        result["diarization"] = failed_diarization(str(exc))
        result["transcription"] = empty_transcription("not_run")
        result["warnings"].append(f"diarization_failed:{exc}")
        release_cached_audio_models()
        return result

    try:
        transcription = run_whisper_transcription(
            audio_path,
            compute_mode,
            diarization.get("turns", []),
            speech_candidates=speech_candidates,
        )
        result["transcription"] = transcription
        result["text"]["segments"] = transcription.get("segments", [])
        result["text"]["rejectedSegments"] = transcription.get("rejectedSegments", [])
        result["text"]["rawSegmentCount"] = transcription.get("raw_segment_count", 0)
        result["text"]["validatedSegmentCount"] = transcription.get("segment_count", 0)
        result["text"]["rejectedSegmentCount"] = transcription.get("rejected_segment_count", 0)
        result["text"]["readableText"] = readable_text_from_segments(result["text"]["segments"])
        release_cached_audio_models()
    except Exception as exc:
        result["ok"] = False
        result["transcription"] = failed_transcription(str(exc))
        result["warnings"].append(f"transcription_failed:{exc}")
        release_cached_audio_models()
        return result

    if (
        result["diarization"].get("status") not in NONFATAL_DIARIZATION_STATUSES
        or result["transcription"].get("status") not in NONFATAL_TRANSCRIPTION_STATUSES
    ):
        result["ok"] = model_mode != "required"
    return result


def base_audio_model_result(
    *,
    model_mode: str,
    compute_mode: str,
    runtime: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": AUDIO_MODEL_RESULT_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "ok": True,
        "mode": model_mode,
        "computeMode": compute_mode,
        "runtime": runtime,
        "diarization": empty_diarization("not_run"),
        "transcription": empty_transcription("not_run"),
        "text": {
            "mode": "whisper_transcript",
            "readableText": "",
            "segments": [],
            "rejectedSegments": [],
            "rawSegmentCount": 0,
            "validatedSegmentCount": 0,
            "rejectedSegmentCount": 0,
            "warnings": [],
        },
        "warnings": [],
    }


def failed_audio_model_process_result(
    *,
    audio_path: Path,
    speech_candidates: list[dict[str, float]],
    source_name: str,
    settings: dict[str, Any],
    mode: str | None,
    error: str,
) -> dict[str, Any]:
    del speech_candidates, source_name
    model_mode = normalize_audio_model_mode(mode)
    compute_mode = normalize_compute_mode(settings.get("computeMode"))
    result = base_audio_model_result(
        model_mode=model_mode,
        compute_mode=compute_mode,
        runtime=audio_model_runtime_status(settings),
        generated_at=utc_now_iso(),
    )
    result["ok"] = False
    result["diarization"] = failed_diarization(error)
    result["transcription"] = failed_transcription(error)
    result["text"]["warnings"].append(error)
    result["warnings"].append(error)
    result["warnings"].append(f"audio_model_input:{audio_path}")
    return result


def append_subprocess_log_warning(result: dict[str, Any], stderr_path: Path) -> None:
    try:
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return
    if not stderr:
        return
    tail = stderr[-2000:]
    result.setdefault("warnings", []).append(f"audio_model_subprocess_stderr_tail:{tail}")


def empty_diarization(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "backend": DIARIZATION_BACKEND,
        "model_id": DIARIZATION_MODEL_ID,
        "turns": [],
        "turn_count": 0,
        "warning_count": 0,
        "warnings": [],
        "error": None,
    }


def failed_diarization(error: str) -> dict[str, Any]:
    payload = empty_diarization("failed")
    payload["error"] = error
    payload["warnings"] = [error]
    payload["warning_count"] = 1
    return payload


def empty_transcription(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "backend": TRANSCRIPTION_BACKEND,
        "model_id": TRANSCRIPTION_MODEL_ID,
        "model_alias": TRANSCRIPTION_MODEL_ALIAS,
        "device": None,
        "compute_type": None,
        "language": {
            "detected": None,
            "probability": None,
        },
        "rawSegments": [],
        "segments": [],
        "rejectedSegments": [],
        "raw_segment_count": 0,
        "segment_count": 0,
        "rejected_segment_count": 0,
        "warning_count": 0,
        "warnings": [],
        "error": None,
    }


def failed_transcription(error: str) -> dict[str, Any]:
    payload = empty_transcription("failed")
    payload["error"] = error
    payload["warnings"] = [error]
    payload["warning_count"] = 1
    return payload


@contextmanager
def torch_checkpoint_loading_without_weights_only() -> Any:
    previous = os.environ.get(TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD)
    os.environ[TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD, None)
        else:
            os.environ[TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD] = previous


@lru_cache(maxsize=2)
def load_diarization_pipeline(token: str, compute_mode: str) -> Any:
    from pyannote.audio import Pipeline

    with torch_checkpoint_loading_without_weights_only():
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL_ID, token=token)
    if compute_mode == "gpu":
        import torch

        if getattr(torch.cuda, "is_available", lambda: False)() and hasattr(pipeline, "to"):
            pipeline.to(torch.device("cuda"))
    return pipeline


def run_diarization(
    audio_path: Path,
    token: str,
    compute_mode: str,
    source_name: str,
    speech_candidates: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    pipeline = load_diarization_pipeline(token, compute_mode)
    scope = {
        "mode": "full_audio" if speech_candidates is None else "speech_candidates",
        "paddingSec": DIARIZATION_ACTIVITY_PADDING_SEC if speech_candidates is not None else None,
        "mergeGapSec": DIARIZATION_ACTIVITY_MERGE_GAP_SEC if speech_candidates is not None else None,
        "spans": 1,
        "activeSec": None,
    }
    if speech_candidates is None:
        audio_input = load_diarization_audio_input(audio_path)
        output = pipeline(audio_input)
        turns = diarization_turns(output)
        del output
        del audio_input
        release_audio_model_intermediates()
    else:
        spans = diarization_activity_spans(speech_candidates)
        scope["spans"] = len(spans)
        scope["activeSec"] = round(sum(end - start for start, end in spans), 3)
        scope["speechCandidateCount"] = len(speech_candidates)
        scope["maxActivitySpans"] = MAX_DIARIZATION_ACTIVITY_SPANS
        if not spans:
            return {
                "status": "no_speaker_turns",
                "source_name": source_name,
                "backend": DIARIZATION_BACKEND,
                "model_id": DIARIZATION_MODEL_ID,
                "scope": scope,
                "turns": [],
                "turn_count": 0,
                "warning_count": 1,
                "warnings": ["Speaker diarization skipped because no speech candidates were found."],
                "error": None,
            }
        if len(spans) > MAX_DIARIZATION_ACTIVITY_SPANS:
            scope["mode"] = "full_audio_many_speech_candidates"
            audio_input = load_diarization_audio_input(audio_path)
            output = pipeline(audio_input)
            turns = diarization_turns(output)
            del output
            del audio_input
            release_audio_model_intermediates()
        else:
            turns = []
            for start, end in spans:
                audio_input = load_diarization_audio_input(audio_path, start_sec=start, end_sec=end)
                output = pipeline(audio_input)
                turns.extend(diarization_turns(output, offset_sec=start))
                del output
                del audio_input
                release_audio_model_intermediates()
    status = "ok" if turns else "no_speaker_turns"
    warnings = [] if turns else ["Speaker diarization completed, but no speaker turns were found."]
    return {
        "status": status,
        "source_name": source_name,
        "backend": DIARIZATION_BACKEND,
        "model_id": DIARIZATION_MODEL_ID,
        "scope": scope,
        "turns": turns,
        "turn_count": len(turns),
        "warning_count": len(warnings),
        "warnings": warnings,
        "error": None,
    }


def load_diarization_audio_input(
    audio_path: Path,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> dict[str, Any]:
    import torchaudio

    if start_sec is None or end_sec is None:
        waveform, sample_rate = torchaudio.load(str(audio_path))
    else:
        metadata = torchaudio.info(str(audio_path))
        source_sample_rate = int(getattr(metadata, "sample_rate", 0) or 16000)
        frame_offset = max(0, int(round(start_sec * source_sample_rate)))
        num_frames = max(1, int(round((end_sec - start_sec) * source_sample_rate)))
        waveform, sample_rate = torchaudio.load(
            str(audio_path),
            frame_offset=frame_offset,
            num_frames=num_frames,
        )
    if hasattr(waveform, "dim") and callable(getattr(waveform, "dim")) and waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    return {
        "waveform": waveform,
        "sample_rate": int(sample_rate),
    }


def diarization_turns(output: Any, offset_sec: float = 0.0) -> list[dict[str, Any]]:
    annotation = getattr(output, "exclusive_speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = getattr(output, "speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = output
    turns: list[dict[str, Any]] = []
    for segment, _, speaker in annotation.itertracks(yield_label=True):
        turns.append(
            {
                "start": round(float(segment.start) + offset_sec, 3),
                "end": round(float(segment.end) + offset_sec, 3),
                "speaker": str(speaker),
            }
        )
    return turns


def diarization_activity_spans(speech_candidates: list[dict[str, float]]) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for candidate in speech_candidates:
        try:
            start = max(0.0, float(candidate.get("startSec", 0.0)) - DIARIZATION_ACTIVITY_PADDING_SEC)
            end = float(candidate.get("endSec", start)) + DIARIZATION_ACTIVITY_PADDING_SEC
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        spans.append((start, end))
    spans.sort(key=lambda span: span[0])
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if not merged or start - merged[-1][1] > DIARIZATION_ACTIVITY_MERGE_GAP_SEC:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return [(round(start, 3), round(end, 3)) for start, end in merged]


@lru_cache(maxsize=2)
def load_whisper_model(compute_mode: str) -> Any:
    from faster_whisper import WhisperModel

    device = "cuda" if compute_mode == "gpu" else "cpu"
    compute_type = "float16" if compute_mode == "gpu" else "int8"
    return WhisperModel(TRANSCRIPTION_MODEL_ID, device=device, compute_type=compute_type)


def run_whisper_transcription(
    audio_path: Path,
    compute_mode: str,
    speaker_turns: list[dict[str, Any]],
    speech_candidates: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    model = load_whisper_model(compute_mode)
    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=False,
        word_timestamps=False,
    )
    raw_segments = [
        transcript_segment_from_whisper(index, segment, speaker_turns)
        for index, segment in enumerate(segments_iter, start=1)
        if str(getattr(segment, "text", "") or "").strip()
    ]
    segments, rejected_segments = validate_transcript_segments(raw_segments, speech_candidates or [])
    warnings = [] if segments else ["Whisper transcription produced no text segments."]
    if rejected_segments:
        warnings.append(f"Whisper transcript validation rejected {len(rejected_segments)} segment(s).")
    return {
        "status": "ok" if segments else "no_segments",
        "backend": TRANSCRIPTION_BACKEND,
        "model_id": TRANSCRIPTION_MODEL_ID,
        "model_alias": TRANSCRIPTION_MODEL_ALIAS,
        "device": "cuda" if compute_mode == "gpu" else "cpu",
        "compute_type": "float16" if compute_mode == "gpu" else "int8",
        "language": {
            "detected": getattr(info, "language", None),
            "probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 6),
        },
        "rawSegments": raw_segments,
        "segments": segments,
        "rejectedSegments": rejected_segments,
        "raw_segment_count": len(raw_segments),
        "segment_count": len(segments),
        "rejected_segment_count": len(rejected_segments),
        "warning_count": len(warnings),
        "warnings": warnings,
        "error": None,
    }


def transcript_segment_from_whisper(index: int, segment: Any, speaker_turns: list[dict[str, Any]]) -> dict[str, Any]:
    start = round(float(getattr(segment, "start", 0.0) or 0.0), 3)
    end = round(float(getattr(segment, "end", start) or start), 3)
    assignment = speaker_assignment_for_interval(start, end, speaker_turns)
    return {
        "start_sec": start,
        "end_sec": end,
        "speaker": assignment["speaker"],
        "speakerAssignment": assignment,
        "text": str(getattr(segment, "text", "") or "").strip(),
        "confidence": whisper_segment_confidence(segment),
        "noSpeechProbability": whisper_no_speech_probability(segment),
        "index": index,
    }


def release_audio_model_intermediates() -> None:
    gc.collect()
    try:
        import torch

        if getattr(torch.cuda, "is_available", lambda: False)():
            torch.cuda.empty_cache()
    except Exception:
        pass


def release_cached_audio_models() -> None:
    for loader in (load_diarization_pipeline, load_whisper_model):
        cache_clear = getattr(loader, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
    release_audio_model_intermediates()


def whisper_segment_confidence(segment: Any) -> float | None:
    avg_logprob = getattr(segment, "avg_logprob", None)
    if avg_logprob is None:
        return None
    try:
        return round(float(avg_logprob), 6)
    except (TypeError, ValueError):
        return None


def whisper_no_speech_probability(segment: Any) -> float | None:
    value = getattr(segment, "no_speech_prob", None)
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def validate_transcript_segments(
    raw_segments: list[dict[str, Any]],
    speech_candidates: list[dict[str, float]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    repeated_texts = repeated_normalized_texts(raw_segments)

    for segment in raw_segments:
        reasons: list[str] = []
        start = float(segment.get("start_sec", 0.0) or 0.0)
        end = float(segment.get("end_sec", start) or start)
        text = str(segment.get("text") or "").strip()
        normalized_text = normalize_transcript_text(text)
        speech_overlap = interval_overlap_with_candidates(start, end, speech_candidates)
        speaker_assignment = segment.get("speakerAssignment") if isinstance(segment.get("speakerAssignment"), dict) else {}
        speaker_overlap = float(speaker_assignment.get("overlapSec", 0.0) or 0.0)
        confidence = optional_float(segment.get("confidence"))
        no_speech_probability = optional_float(segment.get("noSpeechProbability"))

        reject = False
        if speech_overlap < MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC:
            reasons.append("no_speech_candidate_overlap")
            reject = True
        if speaker_overlap <= 0:
            reasons.append("no_speaker_overlap")
        if confidence is not None and confidence < LOW_TRANSCRIPT_CONFIDENCE:
            reasons.append("low_confidence")
        if no_speech_probability is not None and no_speech_probability >= HIGH_NO_SPEECH_PROBABILITY:
            reasons.append("high_no_speech_probability")
            reject = True
        if (
            normalized_text in normalize_phrase_set(KNOWN_SILENCE_HALLUCINATION_PHRASES)
            and normalized_text in repeated_texts
            and (speech_overlap < MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC or speaker_overlap <= 0)
        ):
            reasons.append("known_silence_hallucination_phrase")
            reasons.append("repeated_hallucination_phrase")
            reject = True

        enriched = dict(segment)
        enriched["validation"] = {
            "speechOverlapSec": round(speech_overlap, 3),
            "speakerOverlapSec": round(speaker_overlap, 3),
            "reasons": reasons,
        }
        if reject:
            enriched["validation"]["state"] = "rejected"
            enriched["rejectionReasons"] = reasons
            rejected.append(enriched)
        else:
            enriched["validation"]["state"] = "validated"
            validated.append(enriched)

    return validated, rejected


def repeated_normalized_texts(segments: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    for segment in segments:
        normalized = normalize_transcript_text(str(segment.get("text") or ""))
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1
    return {text for text, count in counts.items() if count >= 3}


def normalize_phrase_set(phrases: set[str]) -> set[str]:
    return {normalize_transcript_text(phrase) for phrase in phrases}


def normalize_transcript_text(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def interval_overlap_with_candidates(
    start: float,
    end: float,
    candidates: list[dict[str, float]],
) -> float:
    if end <= start:
        return 0.0
    overlap = 0.0
    for candidate in candidates:
        candidate_start = float(candidate.get("startSec", 0.0) or 0.0)
        candidate_end = float(candidate.get("endSec", candidate_start) or candidate_start)
        overlap += max(0.0, min(end, candidate_end) - max(start, candidate_start))
    return overlap


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def speaker_assignment_for_interval(start: float, end: float, speaker_turns: list[dict[str, Any]]) -> dict[str, Any]:
    best_speaker: str | None = None
    best_overlap = 0.0
    for turn in speaker_turns:
        turn_start = float(turn.get("startSec", turn.get("start", 0.0)) or 0.0)
        turn_end = float(turn.get("endSec", turn.get("end", turn_start)) or turn_start)
        overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn.get("speaker")) if turn.get("speaker") is not None else None
    return {
        "method": "max_overlap" if best_overlap > 0 else "none",
        "speaker": best_speaker,
        "overlapSec": round(best_overlap, 3),
    }


def readable_text_from_segments(segments: list[dict[str, Any]]) -> str:
    return " ".join(str(segment.get("text") or "").strip() for segment in segments if str(segment.get("text") or "").strip())
