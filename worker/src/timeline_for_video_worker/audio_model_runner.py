from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .audio_models import failed_audio_model_process_result
from .audio_models import run_audio_reference_models


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m timeline_for_video_worker.audio_model_runner <request_json> <result_json>", file=sys.stderr)
        return 2

    request_path = Path(args[0])
    result_path = Path(args[1])
    request = load_request(request_path)

    try:
        result = run_audio_reference_models(
            audio_path=Path(str(request.get("audioPath") or "")),
            speech_candidates=normalize_speech_candidates(request.get("speechCandidates")),
            source_name=str(request.get("sourceName") or ""),
            settings=request.get("settings") if isinstance(request.get("settings"), dict) else {},
            mode=str(request.get("mode") or "required"),
        )
        write_result(result_path, result)
        return 0
    except Exception as exc:
        try:
            result = failed_audio_model_process_result(
                audio_path=Path(str(request.get("audioPath") or "")),
                speech_candidates=normalize_speech_candidates(request.get("speechCandidates")),
                source_name=str(request.get("sourceName") or ""),
                settings=request.get("settings") if isinstance(request.get("settings"), dict) else {},
                mode=str(request.get("mode") or "required"),
                error=f"audio_model_runner_failed:{exc}",
            )
            write_result(result_path, result)
        except Exception as nested_exc:
            print(f"failed to write audio model runner result: {nested_exc}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1


def load_request(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audio model request must be a JSON object")
    return payload


def normalize_speech_candidates(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return []
    candidates: list[dict[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("startSec", 0.0) or 0.0)
            end = float(item.get("endSec", start) or start)
            duration = float(item.get("durationSec", max(0.0, end - start)) or 0.0)
        except (TypeError, ValueError):
            continue
        candidates.append(
            {
                "startSec": round(start, 3),
                "endSec": round(end, 3),
                "durationSec": round(duration, 3),
            }
        )
    return candidates


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
