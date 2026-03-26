from __future__ import annotations

import gc
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .fs_utils import now_iso, write_text
from .settings import load_huggingface_token, load_settings


def normalize_processing_quality(value: str | None) -> str:
    return "high" if str(value or "").strip().lower() == "high" else "standard"


def resolve_model_name_for_quality(value: str | None) -> str:
    return "large-v3" if normalize_processing_quality(value) == "high" else "medium"


@dataclass
class SegmentRecord:
    index: int
    trimmed_start: float
    trimmed_end: float
    original_start: float
    original_end: float
    speaker: str
    text: str


def _map_trimmed_to_original(seconds: float, cut_map: list[dict[str, float]]) -> float:
    if not cut_map:
        return seconds
    for item in cut_map:
        if item["trimmed_start"] <= seconds <= item["trimmed_end"]:
            return item["original_start"] + (seconds - item["trimmed_start"])
    last = cut_map[-1]
    if seconds > last["trimmed_end"]:
        return last["original_end"]
    return seconds


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _build_records(
    segments: list[dict[str, Any]],
    diarization_rows: list[dict[str, Any]] | None,
    cut_map: list[dict[str, float]],
) -> list[SegmentRecord]:
    records: list[SegmentRecord] = []
    for idx, segment in enumerate(segments, start=1):
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        text = _normalize_text(segment.get("text"))
        if not text:
            continue
        speaker = str(segment.get("speaker") or "SPEAKER_00")
        if diarization_rows:
            best_overlap = 0.0
            for row in diarization_rows:
                overlap = max(0.0, min(end, float(row["end"])) - max(start, float(row["start"])))
                if overlap > best_overlap:
                    best_overlap = overlap
                    speaker = str(row["speaker"])
        records.append(
            SegmentRecord(
                index=idx,
                trimmed_start=start,
                trimmed_end=end,
                original_start=_map_trimmed_to_original(start, cut_map),
                original_end=_map_trimmed_to_original(end, cut_map),
                speaker=speaker,
                text=text,
            )
        )
    return records


def _render_markdown(
    source_name: str, metadata: dict[str, Any], segments: list[SegmentRecord]
) -> str:
    lines = [
        f"# Transcript: {source_name}",
        "",
        "## Metadata",
        "",
        f"- Model: `{metadata['model']}`",
        f"- Processing quality: `{metadata.get('processing_quality', 'standard')}`",
        f"- Language: `{metadata['language']}`",
        f"- Device: `{metadata['device']}`",
        f"- Requested compute mode: `{metadata.get('requested_compute_mode', 'cpu')}`",
        f"- Effective compute mode: `{metadata.get('effective_compute_mode', metadata['device'])}`",
        f"- GPU available: `{metadata.get('gpu_available', False)}`",
        f"- Compute type: `{metadata['compute_type']}`",
        f"- Alignment used: `{metadata['alignment_used']}`",
        f"- Diarization used: `{metadata['diarization_used']}`",
        f"- Diarization error: `{metadata.get('diarization_error') or ''}`",
        "",
        "## Transcript",
        "",
    ]
    if not segments:
        lines.append("_No transcript segments generated._")
        return "\n".join(lines) + "\n"
    for segment in segments:
        lines.append(
            f"- [{_timestamp_label(segment.original_start)} - {_timestamp_label(segment.original_end)}] "
            f"{segment.speaker}: {segment.text}"
        )
    return "\n".join(lines) + "\n"


def transcribe_audio(
    *,
    source_name: str,
    trimmed_audio_path: Path,
    transcript_dir: Path,
    cut_map: list[dict[str, float]],
    compute_mode: str | None = None,
    processing_quality: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    token = load_huggingface_token()
    terms_confirmed = bool(settings.get("huggingfaceTermsConfirmed"))

    try:
        import torch
        import whisperx
        from whisperx.diarize import DiarizationPipeline
    except Exception as exc:
        payload = {
            "status": "error",
            "error": f"whisperx is not available: {exc}",
            "generated_at": now_iso(),
            "model": resolve_model_name_for_quality(processing_quality),
            "processing_quality": normalize_processing_quality(processing_quality),
            "device": "cpu",
            "compute_type": "int8",
            "language": "ja",
            "alignment_used": False,
            "diarization_used": False,
            "segments": [],
            "speaker_turns": [],
        }
        transcript_dir.mkdir(parents=True, exist_ok=True)
        (transcript_dir / "raw.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_text(transcript_dir / "raw.md", _render_markdown(source_name, payload, []))
        return payload

    requested_compute_mode = str(compute_mode or settings.get("computeMode") or "cpu").lower()
    gpu_available = torch.cuda.is_available()
    device = "cuda" if requested_compute_mode == "gpu" and gpu_available else "cpu"
    effective_compute_mode = "gpu" if device == "cuda" else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    batch_size = 16 if device == "cuda" else 8
    resolved_quality = normalize_processing_quality(
        processing_quality or settings.get("processingQuality")
    )
    model_name = resolve_model_name_for_quality(resolved_quality)
    language = "ja"
    try:
        model = whisperx.load_model(
            model_name, device, compute_type=compute_type, language=language
        )
    except Exception:
        if device == "cuda":
            compute_type = "int8_float16"
            batch_size = 8
            model = whisperx.load_model(
                model_name, device, compute_type=compute_type, language=language
            )
        else:
            raise
    audio = whisperx.load_audio(str(trimmed_audio_path))
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    aligned_segments = result.get("segments", [])
    alignment_used = False
    try:
        model_a, metadata = whisperx.load_align_model(language_code=language, device=device)
        aligned = whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        aligned_segments = aligned["segments"]
        alignment_used = True
    except Exception:
        aligned_segments = result.get("segments", [])

    diarization_rows: list[dict[str, Any]] | None = None
    diarization_used = False
    diarization_error: str | None = None
    if token and terms_confirmed:
        try:
            diarizer = DiarizationPipeline(token=token, device=torch.device(device))
            diarization_df = diarizer(audio)
            diarization_rows = [
                {
                    "start": float(row["start"]),
                    "end": float(row["end"]),
                    "speaker": str(row["speaker"]),
                }
                for _, row in diarization_df.iterrows()
            ]
            diarization_used = True
        except Exception as exc:
            diarization_rows = None
            diarization_error = str(exc)
    elif not token:
        diarization_error = "Hugging Face token is not configured."
    elif not terms_confirmed:
        diarization_error = "Hugging Face gated model terms are not confirmed."

    records = _build_records(aligned_segments, diarization_rows, cut_map)
    payload = {
        "status": "ok",
        "generated_at": now_iso(),
        "model": model_name,
        "processing_quality": resolved_quality,
        "device": device,
        "requested_compute_mode": requested_compute_mode,
        "effective_compute_mode": effective_compute_mode,
        "gpu_available": gpu_available,
        "compute_type": compute_type,
        "language": language,
        "alignment_used": alignment_used,
        "diarization_used": diarization_used,
        "diarization_error": diarization_error,
        "segments": [asdict(record) for record in records],
        "speaker_turns": diarization_rows or [],
    }
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "raw.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_text(transcript_dir / "raw.md", _render_markdown(source_name, payload, records))
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return payload
