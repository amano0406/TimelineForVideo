from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor, GenerationConfig


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_video_worker.frame_diff_vlm import DEFAULT_FRAME_DIFF_VLM_MODEL_ID, FRAME_DIFF_PROMPT_JA


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe local VLM frame-diff output for sample pairs.")
    parser.add_argument("--model-id", default=DEFAULT_FRAME_DIFF_VLM_MODEL_ID)
    parser.add_argument("--sample-root", required=True)
    parser.add_argument("--pair-id", default="pair-01")
    parser.add_argument("--all-pairs", action="store_true")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--prompt-file", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-suffix", default=None)
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--max-pixels", type=int, default=640 * 360)
    parser.add_argument("--model-dtype", default="auto", choices=["auto", "float32", "float16", "bfloat16"])
    args = parser.parse_args()

    started = time.time()
    sample_root = Path(args.sample_root)
    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        prompt_path = sample_root / "prompt.ja.txt"
        prompt = prompt_path.read_text(encoding="utf-8").strip() if prompt_path.is_file() else FRAME_DIFF_PROMPT_JA
    pair_ids = sample_pair_ids(sample_root) if args.all_pairs else [args.pair_id]

    print(
        json.dumps(
            {
                "stage": "load_model",
                "modelId": args.model_id,
                "cuda": torch.cuda.is_available(),
                "pairs": pair_ids,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    processor = load_processor(args.model_id, min_pixels=224 * 224, max_pixels=args.max_pixels)
    model = load_model(args.model_id, model_dtype=args.model_dtype)

    results = []
    for pair_id in pair_ids:
        results.append(
            run_pair(
                model=model,
                processor=processor,
                sample_root=sample_root,
                pair_id=pair_id,
                model_id=args.model_id,
                prompt=prompt,
                output_path=output_path_for(args, sample_root, pair_id),
                max_new_tokens=args.max_new_tokens,
            )
        )

    print(
        json.dumps(
            {
                "ok": True,
                "modelId": args.model_id,
                "pairs": len(results),
                "elapsedSec": round(time.time() - started, 3),
                "outputs": [result["output"] for result in results],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


def run_pair(
    *,
    model: object,
    processor: object,
    sample_root: Path,
    pair_id: str,
    model_id: str,
    prompt: str,
    output_path: Path,
    max_new_tokens: int,
) -> dict[str, str]:
    if model_id.startswith("microsoft/Phi-4-multimodal-instruct"):
        return run_pair_phi4(
            model=model,
            processor=processor,
            sample_root=sample_root,
            pair_id=pair_id,
            model_id=model_id,
            prompt=prompt,
            output_path=output_path,
            max_new_tokens=max_new_tokens,
        )

    started = time.time()
    pair_dir = sample_root / pair_id
    left = pair_dir / "left.jpg"
    right = pair_dir / "right.jpg"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "url": str(left)},
                {"type": "image", "url": str(right)},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    print(
        json.dumps(
            {"stage": "prepare_inputs", "pairId": pair_id, "left": str(left), "right": str(right)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    inputs = apply_chat_template(processor, messages, model_id)
    inputs.pop("token_type_ids", None)
    inputs = inputs.to(model.device)

    print(
        json.dumps(
            {"stage": "generate", "pairId": pair_id, "inputTokens": int(inputs["input_ids"].shape[-1])},
            ensure_ascii=False,
        ),
        flush=True,
    )
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
    trimmed = [out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
    text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
    result = {
        "schemaVersion": 1,
        "kind": "timeline_for_video.frame_diff_vlm_probe_result",
        "modelId": model_id,
        "pairId": pair_id,
        "left": str(left),
        "right": str(right),
        "prompt": prompt,
        "rawText": text,
        "elapsedSec": round(time.time() - started, 3),
        "cuda": torch.cuda.is_available(),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "pairId": pair_id, "output": str(output_path), "elapsedSec": result["elapsedSec"]}, ensure_ascii=False), flush=True)
    print(text, flush=True)
    return {"pairId": pair_id, "output": str(output_path)}


def apply_chat_template(processor: object, messages: list[dict[str, object]], model_id: str) -> object:
    base_kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_dict": True,
        "return_tensors": "pt",
    }
    if model_id.startswith("Qwen/Qwen3.5-"):
        attempts = [
            {**base_kwargs, "enable_thinking": False},
            {**base_kwargs, "chat_template_kwargs": {"enable_thinking": False}},
            base_kwargs,
        ]
    else:
        attempts = [base_kwargs]

    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return processor.apply_chat_template(messages, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("Failed to apply chat template.")


def run_pair_phi4(
    *,
    model: object,
    processor: object,
    sample_root: Path,
    pair_id: str,
    model_id: str,
    prompt: str,
    output_path: Path,
    max_new_tokens: int,
) -> dict[str, str]:
    from PIL import Image

    started = time.time()
    pair_dir = sample_root / pair_id
    left = pair_dir / "left.jpg"
    right = pair_dir / "right.jpg"
    text_prompt = f"<|user|><|image_1|><|image_2|>{prompt}<|end|><|assistant|>"
    print(
        json.dumps(
            {"stage": "prepare_inputs", "pairId": pair_id, "left": str(left), "right": str(right)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    images = [Image.open(left).convert("RGB"), Image.open(right).convert("RGB")]
    inputs = processor(text=text_prompt, images=images, return_tensors="pt")
    device = next(model.parameters()).device
    inputs = inputs.to(device)

    print(
        json.dumps(
            {"stage": "generate", "pairId": pair_id, "inputTokens": int(inputs["input_ids"].shape[-1])},
            ensure_ascii=False,
        ),
        flush=True,
    )
    generation_config = GenerationConfig.from_pretrained(model_id, trust_remote_code=True)
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            generation_config=generation_config,
        )
    generated_ids = generated_ids[:, inputs["input_ids"].shape[1] :]
    text = processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
    result = {
        "schemaVersion": 1,
        "kind": "timeline_for_video.frame_diff_vlm_probe_result",
        "modelId": model_id,
        "pairId": pair_id,
        "left": str(left),
        "right": str(right),
        "prompt": prompt,
        "rawText": text,
        "elapsedSec": round(time.time() - started, 3),
        "cuda": torch.cuda.is_available(),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "pairId": pair_id, "output": str(output_path), "elapsedSec": result["elapsedSec"]}, ensure_ascii=False), flush=True)
    print(text, flush=True)
    return {"pairId": pair_id, "output": str(output_path)}


def output_path_for(args: argparse.Namespace, sample_root: Path, pair_id: str) -> Path:
    if args.output and not args.all_pairs:
        return Path(args.output)
    suffix = args.output_suffix or f"{safe_slug(args.model_id)}-output"
    return sample_root / pair_id / f"{suffix}.json"


def sample_pair_ids(sample_root: Path) -> list[str]:
    return [
        path.name
        for path in sorted(sample_root.glob("pair-*"))
        if path.is_dir() and (path / "left.jpg").is_file() and (path / "right.jpg").is_file()
    ]


def safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def load_processor(model_id: str, *, min_pixels: int, max_pixels: int) -> object:
    try:
        return AutoProcessor.from_pretrained(
            model_id,
            trust_remote_code=True,
            min_pixels=min_pixels,
            max_pixels=max_pixels,
        )
    except TypeError:
        return AutoProcessor.from_pretrained(model_id, trust_remote_code=True)


def load_model(model_id: str, *, model_dtype: str = "auto") -> object:
    if model_id.startswith("Qwen/Qwen3-VL"):
        from transformers import Qwen3VLForConditionalGeneration

        return load_with_fallback(Qwen3VLForConditionalGeneration, model_id, model_dtype=model_dtype)
    if model_id.startswith("Qwen/Qwen2.5-VL"):
        from transformers import Qwen2_5_VLForConditionalGeneration

        return load_with_fallback(Qwen2_5_VLForConditionalGeneration, model_id, model_dtype=model_dtype)
    if model_id.startswith("Qwen/Qwen2-VL"):
        from transformers import Qwen2VLForConditionalGeneration

        return load_with_fallback(Qwen2VLForConditionalGeneration, model_id, model_dtype=model_dtype)
    if model_id.startswith("Qwen/Qwen3.5-"):
        from transformers import AutoModelForMultimodalLM

        return load_with_fallback(AutoModelForMultimodalLM, model_id, model_dtype=model_dtype)
    if model_id.startswith("google/gemma-3") or model_id.startswith("google/gemma-4"):
        from transformers import AutoModelForMultimodalLM

        return load_with_fallback(AutoModelForMultimodalLM, model_id, model_dtype=model_dtype)
    if model_id.startswith("microsoft/Phi-4-multimodal-instruct"):
        return load_phi4_model(model_id, model_dtype=model_dtype)
    return load_with_fallback(AutoModelForImageTextToText, model_id, model_dtype=model_dtype)


def load_phi4_model(model_id: str, *, model_dtype: str) -> object:
    dtype_value = torch_dtype_value(model_dtype)
    dtype_arg = dtype_value if dtype_value is not None else "auto"
    attempts = [
        {"device_map": "cuda", "dtype": dtype_arg, "_attn_implementation": "eager"},
        {"device_map": "auto", "dtype": dtype_arg, "_attn_implementation": "eager"},
        {"device_map": "cuda", "torch_dtype": dtype_arg, "_attn_implementation": "eager"},
        {"device_map": "auto", "torch_dtype": dtype_arg, "_attn_implementation": "eager"},
        {"dtype": dtype_arg, "_attn_implementation": "eager"},
        {"torch_dtype": dtype_arg, "_attn_implementation": "eager"},
    ]
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            loaded = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True, **kwargs)
            if "device_map" not in kwargs and torch.cuda.is_available():
                return loaded.cuda()
            return loaded
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to load model: {model_id}")


def load_with_fallback(model_class: object, model_id: str, *, model_dtype: str) -> object:
    base_kwargs = {
        "device_map": "auto",
        "trust_remote_code": True,
    }
    dtype_value = torch_dtype_value(model_dtype)
    if dtype_value is None:
        attempts = [
            {"dtype": "auto", "attn_implementation": "sdpa"},
            {"dtype": "auto"},
            {"torch_dtype": "auto", "attn_implementation": "sdpa"},
            {"torch_dtype": "auto"},
            {},
        ]
    else:
        attempts = [
            {"dtype": dtype_value, "attn_implementation": "sdpa"},
            {"dtype": dtype_value},
            {"torch_dtype": dtype_value, "attn_implementation": "sdpa"},
            {"torch_dtype": dtype_value},
        ]
    last_error: Exception | None = None
    for extra in attempts:
        try:
            return model_class.from_pretrained(model_id, **base_kwargs, **extra)
        except TypeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to load model: {model_id}")


def torch_dtype_value(model_dtype: str) -> torch.dtype | None:
    if model_dtype == "float32":
        return torch.float32
    if model_dtype == "float16":
        return torch.float16
    if model_dtype == "bfloat16":
        return torch.bfloat16
    return None


if __name__ == "__main__":
    raise SystemExit(main())
