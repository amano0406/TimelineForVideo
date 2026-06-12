from __future__ import annotations

import importlib.util
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .probe import utc_now_iso
from .settings import PRODUCT_NAME, load_huggingface_token


FRAME_DIFF_VLM_SCHEMA_VERSION = "timeline_for_video.frame_diff_vlm.v1"
FRAME_DIFF_VLM_RESULT_SCHEMA_VERSION = "timeline_for_video.frame_diff_vlm_result.v1"
DEFAULT_FRAME_DIFF_VLM_MODEL_ID = "Qwen/Qwen3.5-4B"
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_MAX_PIXELS = 640 * 360
SUPPORTED_FRAME_DIFF_VLM_MODES = {"off", "auto", "required"}

FRAME_DIFF_PROMPT_JA = """\
2枚の動画フレーム画像A/Bを比較し、画面上の意味のある変化だけを抽出してください。
右下の時計、録画タイマー、動画プレイヤーの経過時間、圧縮ノイズ、カーソルの数px移動だけなら changed は false にしてください。
入力文字の追加、選択状態、画面遷移、ダイアログ、表示内容の変化、UI部品の増減は changed を true にしてください。
人物の識別や顔認識は行わないでください。

次のJSONだけを返してください。
{
  "changed": true,
  "changeLevel": "none|minor|meaningful|major",
  "summary": "日本語で1文",
  "differences": ["日本語の短い差分説明"],
  "confidence": 0.0
}
"""


@dataclass(frozen=True)
class FrameDiffVlmOptions:
    mode: str = "auto"
    model_id: str = DEFAULT_FRAME_DIFF_VLM_MODEL_ID
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    max_pixels: int = DEFAULT_MAX_PIXELS
    model_dtype: str = "auto"


class FrameDiffVlmRunnerProtocol:
    def analyze(self, left_path: Path, right_path: Path, prompt: str) -> dict[str, Any]:
        raise NotImplementedError


class QwenFrameDiffVlmRunner(FrameDiffVlmRunnerProtocol):
    def __init__(self, options: FrameDiffVlmOptions, *, token: str | None = None) -> None:
        self.options = options
        self.token = token
        self._processor: Any | None = None
        self._model: Any | None = None

    def analyze(self, left_path: Path, right_path: Path, prompt: str) -> dict[str, Any]:
        import torch

        started = time.time()
        processor = self.processor
        model = self.model
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": str(left_path)},
                    {"type": "image", "url": str(right_path)},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = apply_chat_template(processor, messages, self.options.model_id)
        inputs.pop("token_type_ids", None)
        inputs = inputs.to(model_device(model))
        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=self.options.max_new_tokens,
                do_sample=False,
            )
        trimmed = [out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
        raw_text = processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        parsed: dict[str, Any] = {}
        parse_error = None
        try:
            parsed = parse_vlm_json(raw_text)
        except Exception as exc:
            parse_error = f"{exc.__class__.__name__}:{exc}"
        return {
            "rawText": raw_text,
            "parsed": parsed,
            "parseError": parse_error,
            "elapsedSec": round(time.time() - started, 3),
        }

    @property
    def processor(self) -> Any:
        if self._processor is None:
            from transformers import AutoProcessor

            kwargs: dict[str, Any] = {
                "trust_remote_code": True,
                "min_pixels": 224 * 224,
                "max_pixels": self.options.max_pixels,
            }
            if self.token:
                kwargs["token"] = self.token
            try:
                self._processor = AutoProcessor.from_pretrained(self.options.model_id, **kwargs)
            except TypeError:
                kwargs.pop("min_pixels", None)
                kwargs.pop("max_pixels", None)
                self._processor = AutoProcessor.from_pretrained(self.options.model_id, **kwargs)
        return self._processor

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = load_model(self.options, token=self.token)
        return self._model


def analyze_frame_diff_vlm_outputs(
    output_root_text: str,
    *,
    max_items: int | None = None,
    item_ids: set[str] | None = None,
    settings: dict[str, Any] | None = None,
    options: FrameDiffVlmOptions | None = None,
    runner: FrameDiffVlmRunnerProtocol | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    options = options or FrameDiffVlmOptions()
    generated_at = utc_now_iso()
    output_root = resolve_path(output_root_text)
    roots = selected_item_roots(output_root, item_ids)
    if max_items is not None:
        roots = roots[:max_items]

    records: list[dict[str, Any]] = []
    runtime = frame_diff_vlm_runtime_status()
    shared_runner: FrameDiffVlmRunnerProtocol | None = runner
    total = len(roots)
    for index, item_root in enumerate(roots, start=1):
        emit_progress(
            progress_callback,
            total=total,
            items_done=index - 1,
            current_item=item_root.name,
            item_stage="frame_diff_vlm",
            message="Analyzing visual frame differences.",
        )
        record = analyze_item_frame_diff_vlm(
            item_root,
            generated_at=generated_at,
            settings=settings or {},
            options=options,
            runtime=runtime,
            runner=shared_runner,
        )
        if shared_runner is None and record.get("_runner") is not None:
            shared_runner = record.pop("_runner")
        records.append(record)
        emit_progress(
            progress_callback,
            total=total,
            items_done=index,
            current_item=item_root.name,
            item_stage="completed",
            message="Analyzed visual frame differences.",
        )

    failed_items = sum(1 for record in records if not record["ok"])
    return {
        "schemaVersion": FRAME_DIFF_VLM_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ok": failed_items == 0,
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "mode": options.mode,
        "model": {
            "modelId": options.model_id,
            "maxNewTokens": options.max_new_tokens,
            "maxPixels": options.max_pixels,
            "modelDtype": options.model_dtype,
        },
        "runtime": runtime,
        "counts": {
            "items": len(records),
            "failedItems": failed_items,
            "candidateTransitions": sum(record["counts"]["candidateTransitions"] for record in records),
            "analyzedTransitions": sum(record["counts"]["analyzedTransitions"] for record in records),
            "skippedTransitions": sum(record["counts"]["skippedTransitions"] for record in records),
            "failedTransitions": sum(record["counts"]["failedTransitions"] for record in records),
            "changedTransitions": sum(record["counts"]["changedTransitions"] for record in records),
        },
        "records": records,
    }


def analyze_item_frame_diff_vlm(
    item_root: Path,
    *,
    generated_at: str,
    settings: dict[str, Any],
    options: FrameDiffVlmOptions,
    runtime: dict[str, Any],
    runner: FrameDiffVlmRunnerProtocol | None,
) -> dict[str, Any]:
    raw_outputs_dir = item_root / "raw_outputs"
    frame_samples_path = raw_outputs_dir / "frame_samples.json"
    output_path = raw_outputs_dir / "frame_diff_vlm.json"
    warnings: list[str] = []
    frame_samples = read_json(frame_samples_path)
    if frame_samples is None:
        record = base_record(item_root, generated_at, frame_samples_path, output_path, options)
        record["ok"] = options.mode != "required"
        record["status"] = "skipped_missing_frame_samples"
        record["warnings"] = ["frame_samples_missing"]
        return write_record(output_path, record)

    transitions = candidate_transitions(frame_samples)
    record = base_record(item_root, generated_at, frame_samples_path, output_path, options)
    record["source"] = {
        "frameSamplesJson": str(frame_samples_path),
        "gateSchemaVersion": frame_samples.get("visualGate", {}).get("schemaVersion")
        if isinstance(frame_samples.get("visualGate"), dict)
        else None,
    }
    record["counts"]["candidateTransitions"] = len(transitions)

    if options.mode == "off":
        record["ok"] = True
        record["status"] = "skipped_disabled"
        record["warnings"] = ["frame_diff_vlm_disabled"]
        record["transitions"] = [skipped_transition(candidate, "skipped_disabled") for candidate in transitions]
        record["counts"] = count_record_transitions(record["transitions"])
        return write_record(output_path, record)

    if not runtime["ready"]:
        record["ok"] = options.mode != "required"
        record["status"] = "skipped_dependency_unavailable"
        record["runtime"] = runtime
        record["warnings"] = ["frame_diff_vlm_dependencies_unavailable"]
        record["transitions"] = [skipped_transition(candidate, "skipped_dependency_unavailable") for candidate in transitions]
        record["counts"] = count_record_transitions(record["transitions"])
        return write_record(output_path, record)

    if not transitions:
        record["ok"] = True
        record["status"] = "completed_no_candidates"
        return write_record(output_path, record)

    local_runner = runner
    if local_runner is None:
        try:
            local_runner = QwenFrameDiffVlmRunner(options, token=load_huggingface_token(settings))
        except Exception as exc:
            record["ok"] = options.mode != "required"
            record["status"] = "skipped_model_unavailable"
            record["warnings"] = [f"frame_diff_vlm_model_unavailable:{exc.__class__.__name__}:{exc}"]
            record["transitions"] = [skipped_transition(candidate, "skipped_model_unavailable") for candidate in transitions]
            record["counts"] = count_record_transitions(record["transitions"])
            return write_record(output_path, record)

    results: list[dict[str, Any]] = []
    for candidate in transitions:
        try:
            results.append(run_transition(local_runner, candidate))
        except Exception as exc:
            results.append(failed_transition(candidate, exc))
            warnings.append(f"frame_diff_vlm_transition_failed:{candidate['fromFrameId']}:{candidate['toFrameId']}")

    counts = count_record_transitions(results)
    record["ok"] = options.mode != "required" or counts["failedTransitions"] == 0
    record["status"] = "completed" if counts["failedTransitions"] == 0 else "completed_with_errors"
    record["transitions"] = results
    record["counts"] = counts
    record["warnings"] = sorted(set(warnings))
    if runner is None:
        record["_runner"] = local_runner
    return write_record(output_path, record)


def base_record(
    item_root: Path,
    generated_at: str,
    frame_samples_path: Path,
    output_path: Path,
    options: FrameDiffVlmOptions,
) -> dict[str, Any]:
    return {
        "schemaVersion": FRAME_DIFF_VLM_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "itemId": item_root.name,
        "generatedAt": generated_at,
        "ok": False,
        "status": "pending",
        "mode": options.mode,
        "model": {
            "modelId": options.model_id,
            "maxNewTokens": options.max_new_tokens,
            "maxPixels": options.max_pixels,
            "modelDtype": options.model_dtype,
        },
        "prompt": {
            "language": "ja",
            "task": "compare_adjacent_video_frames",
            "text": FRAME_DIFF_PROMPT_JA,
        },
        "source": {
            "frameSamplesJson": str(frame_samples_path),
            "gateSchemaVersion": None,
        },
        "outputs": {
            "frameDiffVlmJson": str(output_path),
        },
        "runtime": frame_diff_vlm_runtime_status(),
        "counts": empty_counts(),
        "transitions": [],
        "warnings": [],
    }


def candidate_transitions(frame_samples: dict[str, Any]) -> list[dict[str, Any]]:
    frames_by_id = {
        str(frame.get("frameId")): frame
        for frame in frame_samples.get("frames", [])
        if isinstance(frame, dict) and frame.get("frameId")
    }
    gate = frame_samples.get("visualGate") if isinstance(frame_samples.get("visualGate"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for transition in gate.get("transitions", []):
        if not isinstance(transition, dict) or not transition.get("wouldSendToVlm"):
            continue
        left = frames_by_id.get(str(transition.get("fromFrameId")))
        right = frames_by_id.get(str(transition.get("toFrameId")))
        candidates.append(
            {
                "index": transition.get("index"),
                "fromFrameId": transition.get("fromFrameId"),
                "toFrameId": transition.get("toFrameId"),
                "startSec": transition.get("fromTimeSec"),
                "endSec": transition.get("toTimeSec"),
                "gateDecision": transition.get("decision"),
                "gateReasons": transition.get("reasons") if isinstance(transition.get("reasons"), list) else [],
                "gateMetrics": {
                    "raw": transition.get("raw") if isinstance(transition.get("raw"), dict) else {},
                    "masked": transition.get("masked") if isinstance(transition.get("masked"), dict) else {},
                },
                "leftPath": Path(str(left.get("outputPath"))) if isinstance(left, dict) and left.get("outputPath") else None,
                "rightPath": Path(str(right.get("outputPath"))) if isinstance(right, dict) and right.get("outputPath") else None,
            }
        )
    return candidates


def run_transition(runner: FrameDiffVlmRunnerProtocol, candidate: dict[str, Any]) -> dict[str, Any]:
    left_path = candidate.get("leftPath")
    right_path = candidate.get("rightPath")
    if not isinstance(left_path, Path) or not isinstance(right_path, Path):
        raise FileNotFoundError("candidate frame paths are missing")
    if not left_path.is_file() or not right_path.is_file():
        raise FileNotFoundError(f"candidate frame image is missing: {left_path} / {right_path}")

    result = runner.analyze(left_path, right_path, FRAME_DIFF_PROMPT_JA)
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    if result.get("parseError"):
        return transition_payload(
            candidate,
            ok=False,
            status="parse_failed",
            changed=None,
            change_level=None,
            summary="",
            differences=[],
            confidence=None,
            raw_text=str(result.get("rawText") or ""),
            parsed=parsed,
            elapsed_sec=result.get("elapsedSec"),
            warnings=[str(result["parseError"])],
        )
    return transition_payload(
        candidate,
        ok=True,
        status="completed",
        changed=normalize_changed(parsed.get("changed")),
        change_level=normalize_change_level(parsed.get("changeLevel")),
        summary=str(parsed.get("summary") or ""),
        differences=normalize_string_list(parsed.get("differences")),
        confidence=normalize_confidence(parsed.get("confidence")),
        raw_text=str(result.get("rawText") or ""),
        parsed=parsed,
        elapsed_sec=result.get("elapsedSec"),
        warnings=[],
    )


def skipped_transition(candidate: dict[str, Any], status: str) -> dict[str, Any]:
    return transition_payload(
        candidate,
        ok=True,
        status=status,
        changed=None,
        change_level=None,
        summary="",
        differences=[],
        confidence=None,
        raw_text="",
        parsed={},
        elapsed_sec=None,
        warnings=[status],
    )


def failed_transition(candidate: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return transition_payload(
        candidate,
        ok=False,
        status="failed",
        changed=None,
        change_level=None,
        summary="",
        differences=[],
        confidence=None,
        raw_text="",
        parsed={},
        elapsed_sec=None,
        warnings=[f"{exc.__class__.__name__}:{exc}"],
    )


def transition_payload(
    candidate: dict[str, Any],
    *,
    ok: bool,
    status: str,
    changed: bool | None,
    change_level: str | None,
    summary: str,
    differences: list[str],
    confidence: float | None,
    raw_text: str,
    parsed: dict[str, Any],
    elapsed_sec: Any,
    warnings: list[str],
) -> dict[str, Any]:
    left_path = candidate.get("leftPath")
    right_path = candidate.get("rightPath")
    return {
        "index": candidate.get("index"),
        "fromFrameId": candidate.get("fromFrameId"),
        "toFrameId": candidate.get("toFrameId"),
        "startSec": candidate.get("startSec"),
        "endSec": candidate.get("endSec"),
        "ok": ok,
        "status": status,
        "changed": changed,
        "changeLevel": change_level,
        "summary": summary,
        "differences": differences,
        "confidence": confidence,
        "gate": {
            "decision": candidate.get("gateDecision"),
            "reasons": candidate.get("gateReasons"),
            "metrics": candidate.get("gateMetrics"),
        },
        "inputFrames": {
            "leftPath": str(left_path) if isinstance(left_path, Path) else None,
            "rightPath": str(right_path) if isinstance(right_path, Path) else None,
        },
        "rawText": raw_text,
        "parsed": parsed,
        "elapsedSec": elapsed_sec,
        "warnings": warnings,
        "source": "frame_diff_vlm",
    }


def count_record_transitions(transitions: list[dict[str, Any]]) -> dict[str, int]:
    counts = empty_counts()
    counts["candidateTransitions"] = len(transitions)
    counts["analyzedTransitions"] = sum(1 for transition in transitions if transition.get("status") == "completed")
    counts["skippedTransitions"] = sum(1 for transition in transitions if str(transition.get("status", "")).startswith("skipped"))
    counts["failedTransitions"] = sum(1 for transition in transitions if not transition.get("ok"))
    counts["changedTransitions"] = sum(1 for transition in transitions if transition.get("changed") is True)
    counts["unchangedTransitions"] = sum(1 for transition in transitions if transition.get("changed") is False)
    return counts


def empty_counts() -> dict[str, int]:
    return {
        "candidateTransitions": 0,
        "analyzedTransitions": 0,
        "skippedTransitions": 0,
        "failedTransitions": 0,
        "changedTransitions": 0,
        "unchangedTransitions": 0,
    }


def normalize_frame_diff_vlm_options(
    *,
    mode: str | None = None,
    model_id: str | None = None,
    max_new_tokens: int | None = None,
    max_pixels: int | None = None,
    model_dtype: str | None = None,
) -> FrameDiffVlmOptions:
    env_mode = os.environ.get("TIMELINE_FOR_VIDEO_FRAME_DIFF_VLM_MODE")
    env_model_id = os.environ.get("TIMELINE_FOR_VIDEO_FRAME_DIFF_VLM_MODEL_ID")
    normalized_mode = normalize_frame_diff_vlm_mode(mode or env_mode or "auto")
    normalized_model_id = str(model_id or env_model_id or DEFAULT_FRAME_DIFF_VLM_MODEL_ID).strip()
    return FrameDiffVlmOptions(
        mode=normalized_mode,
        model_id=normalized_model_id or DEFAULT_FRAME_DIFF_VLM_MODEL_ID,
        max_new_tokens=max(64, int(max_new_tokens or DEFAULT_MAX_NEW_TOKENS)),
        max_pixels=max(224 * 224, int(max_pixels or DEFAULT_MAX_PIXELS)),
        model_dtype=str(model_dtype or "auto").strip() or "auto",
    )


def normalize_frame_diff_vlm_mode(value: str | None) -> str:
    text = str(value or "auto").strip().casefold()
    aliases = {
        "disabled": "off",
        "disable": "off",
        "false": "off",
        "0": "off",
        "enabled": "auto",
        "true": "auto",
        "1": "auto",
    }
    text = aliases.get(text, text)
    if text not in SUPPORTED_FRAME_DIFF_VLM_MODES:
        raise ValueError(f"frameDiffVlmMode must be one of: {', '.join(sorted(SUPPORTED_FRAME_DIFF_VLM_MODES))}")
    return text


def frame_diff_vlm_runtime_status() -> dict[str, Any]:
    modules = {
        "torch": importlib.util.find_spec("torch") is not None,
        "torchvision": importlib.util.find_spec("torchvision") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "qwen_vl_utils": importlib.util.find_spec("qwen_vl_utils") is not None,
        "PIL": importlib.util.find_spec("PIL") is not None,
    }
    cuda_available = False
    if modules["torch"]:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    ready = all(modules.values())
    return {
        "ok": ready,
        "ready": ready,
        "backend": "transformers",
        "modelId": DEFAULT_FRAME_DIFF_VLM_MODEL_ID,
        "modules": modules,
        "cudaAvailable": cuda_available,
        "message": "Frame-diff VLM dependencies are ready." if ready else "Frame-diff VLM dependencies are not installed.",
    }


def parse_vlm_json(text: str) -> dict[str, Any]:
    candidate = strip_json_fence(text).strip()
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("VLM output JSON root must be an object.")
    return payload


def strip_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return stripped


def normalize_changed(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"true", "yes", "1", "changed"}:
            return True
        if text in {"false", "no", "0", "same", "unchanged"}:
            return False
    return None


def normalize_change_level(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if text in {"none", "minor", "meaningful", "major"}:
        return text
    return text or None


def normalize_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(max(0.0, min(1.0, float(value))), 4)
    if isinstance(value, str):
        try:
            return round(max(0.0, min(1.0, float(value))), 4)
        except ValueError:
            return None
    return None


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def apply_chat_template(processor: object, messages: list[dict[str, object]], model_id: str) -> object:
    base_kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_dict": True,
        "return_tensors": "pt",
    }
    attempts = [
        {**base_kwargs, "enable_thinking": False},
        {**base_kwargs, "chat_template_kwargs": {"enable_thinking": False}},
        base_kwargs,
    ] if model_id.startswith("Qwen/Qwen3.5-") else [base_kwargs]
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return processor.apply_chat_template(messages, **kwargs)
        except TypeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Failed to apply chat template.")


def load_model(options: FrameDiffVlmOptions, *, token: str | None = None) -> object:
    import torch
    import transformers

    model_class = getattr(transformers, "AutoModelForMultimodalLM", None)
    if model_class is None:
        model_class = getattr(transformers, "AutoModelForImageTextToText")
    base_kwargs: dict[str, Any] = {
        "device_map": "auto",
        "trust_remote_code": True,
    }
    if token:
        base_kwargs["token"] = token
    dtype = torch_dtype_value(torch, options.model_dtype)
    attempts: list[dict[str, Any]]
    if dtype is None:
        attempts = [
            {"dtype": "auto", "attn_implementation": "sdpa"},
            {"dtype": "auto"},
            {"torch_dtype": "auto", "attn_implementation": "sdpa"},
            {"torch_dtype": "auto"},
            {},
        ]
    else:
        attempts = [
            {"dtype": dtype, "attn_implementation": "sdpa"},
            {"dtype": dtype},
            {"torch_dtype": dtype, "attn_implementation": "sdpa"},
            {"torch_dtype": dtype},
        ]
    last_error: Exception | None = None
    for extra in attempts:
        try:
            return model_class.from_pretrained(options.model_id, **base_kwargs, **extra)
        except TypeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to load model: {options.model_id}")


def torch_dtype_value(torch_module: Any, model_dtype: str) -> Any:
    if model_dtype == "float32":
        return torch_module.float32
    if model_dtype == "float16":
        return torch_module.float16
    if model_dtype == "bfloat16":
        return torch_module.bfloat16
    return None


def model_device(model: Any) -> Any:
    device = getattr(model, "device", None)
    if device is not None:
        return device
    return next(model.parameters()).device


def selected_item_roots(output_root: Path, item_ids: set[str] | None) -> list[Path]:
    items_root = output_root / "items"
    if not items_root.is_dir():
        return []
    roots = sorted((path for path in items_root.iterdir() if path.is_dir()), key=lambda path: path.name)
    if not item_ids:
        return roots
    return [path for path in roots if path.name in item_ids]


def resolve_path(path_text: str) -> Path:
    text = str(path_text)
    if os.name != "nt" and len(text) >= 3 and text[1:3] == ":\\":
        drive = text[0].lower()
        rest = text[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(text).expanduser()


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    serializable = {key: value for key, value in record.items() if key != "_runner"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    total: int,
    items_done: int,
    current_item: str,
    item_stage: str,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "total": total,
            "itemsDone": items_done,
            "currentItem": current_item,
            "itemStage": item_stage,
            "message": message,
        }
    )
