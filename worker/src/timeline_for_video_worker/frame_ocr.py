from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Callable

from . import __version__
from .discovery import resolve_configured_path
from .items import item_roots, read_optional_json, write_json
from .probe import utc_now_iso
from .settings import PRODUCT_NAME


FRAME_OCR_SCHEMA_VERSION = "timeline_for_video.frame_ocr.v1"
FRAME_OCR_RESULT_SCHEMA_VERSION = "timeline_for_video.frame_ocr_result.v1"
OCR_MODEL_ID = "tesseract:jpn+eng"
OCR_MODES = ("auto", "mock", "off")


def ocr_runtime_status(mode: str = "auto") -> dict[str, Any]:
    if mode == "off":
        return {
            "ok": True,
            "mode": mode,
            "model": None,
            "languages": [],
            "message": "OCR is disabled.",
        }

    try:
        import pytesseract

        languages = sorted(str(language) for language in pytesseract.get_languages(config=""))
    except Exception as exc:
        return {
            "ok": mode == "mock",
            "mode": mode,
            "model": OCR_MODEL_ID,
            "languages": [],
            "message": str(exc),
        }

    ready = "jpn" in languages and "eng" in languages
    return {
        "ok": ready or mode == "mock",
        "mode": mode,
        "model": OCR_MODEL_ID,
        "languages": languages,
        "message": "Tesseract OCR is ready." if ready else "Tesseract languages jpn+eng are not both available.",
    }


def analyze_frame_ocr_outputs(
    output_root_text: str,
    max_items: int | None = None,
    mode: str = "auto",
    item_ids: set[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")
    mode = normalize_ocr_mode(mode)

    generated_at = utc_now_iso()
    output_root = resolve_configured_path(output_root_text)
    roots = item_roots(output_root)
    if item_ids is not None:
        roots = [root for root in roots if root.name in item_ids]
    selected_roots = roots[:max_items] if max_items is not None else roots
    records: list[dict[str, Any]] = []
    total = len(selected_roots)
    for index, item_root in enumerate(selected_roots, start=1):
        emit_progress(
            progress_callback,
            total=total,
            items_done=index - 1,
            item_stage="ocr_frames",
            current_item=item_root.name,
            message="Reading text from sampled video frames.",
        )
        records.append(analyze_item_frame_ocr(item_root, mode=mode, generated_at=generated_at))
        emit_progress(
            progress_callback,
            total=total,
            items_done=index,
            item_stage="completed",
            current_item=item_root.name,
            message="Read text from sampled video frames.",
        )
    failed_items = sum(1 for record in records if not record["ok"])
    return {
        "schemaVersion": FRAME_OCR_RESULT_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "ok": failed_items == 0,
        "ocrMode": mode,
        "ocrRuntime": ocr_runtime_status(mode),
        "outputRoot": {
            "configuredPath": output_root_text,
            "resolvedPath": str(output_root),
        },
        "counts": {
            "availableItems": len(roots),
            "processedItems": len(records),
            "failedItems": failed_items,
            "skippedByMaxItems": max(len(roots) - len(records), 0),
            "frames": sum(record["counts"]["frames"] for record in records),
            "framesWithVisualFeatures": sum(record["counts"]["framesWithVisualFeatures"] for record in records),
            "textBlocks": sum(record["counts"]["textBlocks"] for record in records),
            "framesWithText": sum(record["counts"]["framesWithText"] for record in records),
        },
        "records": records,
    }


def emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    total: int,
    items_done: int,
    item_stage: str,
    current_item: str,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "total": total,
            "itemsDone": items_done,
            "itemStage": item_stage,
            "currentItem": current_item,
            "message": message,
        }
    )


def analyze_item_frame_ocr(item_root: Path, mode: str, generated_at: str) -> dict[str, Any]:
    raw_outputs_dir = item_root / "raw_outputs"
    artifacts_dir = item_root / "artifacts"
    ocr_dir = artifacts_dir / "ocr"
    frame_samples_path = raw_outputs_dir / "frame_samples.json"
    frame_ocr_path = raw_outputs_dir / "frame_ocr.json"
    frame_samples, warning = read_optional_json(frame_samples_path)
    warnings: list[str] = []
    if warning:
        warnings.append(warning)

    record = {
        "schemaVersion": FRAME_OCR_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "version": __version__,
        "generatedAt": generated_at,
        "itemId": item_root.name,
        "ok": False,
        "ocrMode": mode,
        "ocrRuntime": ocr_runtime_status(mode),
        "sourceVideoModified": False,
        "inputs": {
            "frameSamplesJson": str(frame_samples_path),
        },
        "outputs": {
            "frameOcrJson": str(frame_ocr_path),
            "ocrArtifactsDir": str(ocr_dir),
        },
        "frames": [],
        "counts": {
            "frames": 0,
            "framesWithVisualFeatures": 0,
            "framesWithText": 0,
            "textBlocks": 0,
            "warnings": 0,
        },
        "warnings": warnings,
    }

    if not frame_samples:
        warnings.append("frame_samples_missing")
        record["counts"]["warnings"] = len(warnings)
        return write_frame_ocr(record, frame_ocr_path)

    for sample_frame in frame_samples.get("frames", []):
        if not isinstance(sample_frame, dict) or not sample_frame.get("ok"):
            continue
        frame_path = Path(str(sample_frame.get("outputPath") or ""))
        overlay_path = ocr_dir / f"{sample_frame.get('frameId', 'frame')}-ocr.jpg"
        frame_record = analyze_frame_file(frame_path, overlay_path, sample_frame, mode)
        record["frames"].append(frame_record)

    record["counts"]["frames"] = len(record["frames"])
    record["counts"]["framesWithVisualFeatures"] = sum(
        1 for frame in record["frames"] if frame.get("visual", {}).get("available")
    )
    record["counts"]["framesWithText"] = sum(1 for frame in record["frames"] if frame["ocr"]["has_text"])
    record["counts"]["textBlocks"] = sum(len(frame["ocr"]["blocks"]) for frame in record["frames"])
    warnings.extend(
        warning
        for frame in record["frames"]
        for warning in frame["ocr"].get("warnings", [])
    )
    record["warnings"] = warnings
    record["counts"]["warnings"] = len(warnings)
    record["ok"] = True
    return write_frame_ocr(record, frame_ocr_path)


def analyze_frame_file(
    frame_path: Path,
    overlay_path: Path,
    sample_frame: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    ocr_payload = run_frame_ocr(frame_path, mode)
    visual_payload = analyze_frame_visual_features(frame_path)
    overlay_result = write_debug_overlay(frame_path, overlay_path, ocr_payload)
    if overlay_result["warning"]:
        ocr_payload["warnings"].append(overlay_result["warning"])

    return {
        "frameId": sample_frame.get("frameId"),
        "timeSec": sample_frame.get("timeSec"),
        "source_frame_path": str(frame_path),
        "debug_overlay_path": overlay_result["path"],
        "ok": frame_path.exists(),
        "visual": visual_payload,
        "ocr": ocr_payload,
    }


def run_frame_ocr(frame_path: Path, mode: str) -> dict[str, Any]:
    mode = normalize_ocr_mode(mode)
    if mode == "off":
        return empty_ocr(mode=mode, model=None)
    if not frame_path.exists():
        payload = empty_ocr(mode=mode, model=OCR_MODEL_ID)
        payload["warnings"].append(f"frame_missing:{frame_path}")
        return payload
    if mode == "mock":
        text = f"Mock OCR for {frame_path.name}"
        return {
            "mode": mode,
            "model": None,
            "has_text": True,
            "full_text": text,
            "blocks": [
                {
                    "block_id": "ocr_0001",
                    "text": text,
                    "bbox_norm": [0.05, 0.05, 0.95, 0.18],
                    "confidence": {"score": None, "level": "unknown"},
                }
            ],
            "warnings": ["mock OCR; frame text was not inspected"],
        }

    try:
        import pytesseract
        from PIL import Image, ImageOps
        from pytesseract import Output

        with Image.open(frame_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            text = pytesseract.image_to_string(image, lang="jpn+eng").strip()
            data = pytesseract.image_to_data(image, lang="jpn+eng", output_type=Output.DICT)
            blocks = tesseract_blocks(data, image.size)
    except Exception as exc:
        payload = empty_ocr(mode=mode, model=OCR_MODEL_ID)
        payload["warnings"].append(f"OCR failed in auto mode: {exc}")
        return payload

    return {
        "mode": mode,
        "model": OCR_MODEL_ID,
        "has_text": bool(text or blocks),
        "full_text": text,
        "blocks": blocks,
        "warnings": [],
    }


def tesseract_blocks(data: dict[str, list[Any]], size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = size
    count = len(data.get("text", []))
    blocks: list[dict[str, Any]] = []
    for index in range(count):
        text = str(data["text"][index] or "").strip()
        if not text:
            continue
        confidence = parse_confidence(data.get("conf", ["-1"])[index])
        if confidence is not None and confidence < 0:
            continue
        left = float(data.get("left", [0])[index])
        top = float(data.get("top", [0])[index])
        right = left + float(data.get("width", [0])[index])
        bottom = top + float(data.get("height", [0])[index])
        blocks.append(
            {
                "block_id": f"ocr_{len(blocks) + 1:04d}",
                "text": text,
                "bbox_norm": normalized_bbox(left, top, right, bottom, width, height),
                "confidence": {"score": confidence, "level": confidence_level(confidence)},
            }
        )
    return blocks


def write_debug_overlay(frame_path: Path, overlay_path: Path, ocr_payload: dict[str, Any]) -> dict[str, Any]:
    if not frame_path.exists():
        return {"path": str(overlay_path), "warning": None}
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw

        with Image.open(frame_path) as raw:
            image = raw.convert("RGB")
            draw = ImageDraw.Draw(image)
            width, height = image.size
            for block in ocr_payload.get("blocks", []):
                left, top, right, bottom = denormalized_bbox(block.get("bbox_norm", []), width, height)
                draw.rectangle((left, top, right, bottom), outline="red", width=2)
            image.save(overlay_path, format="JPEG", quality=90)
        return {"path": str(overlay_path), "warning": None}
    except Exception as exc:
        try:
            shutil.copy2(frame_path, overlay_path)
        except Exception:
            pass
        return {"path": str(overlay_path), "warning": f"debug_overlay_failed:{exc}"}


def analyze_frame_visual_features(frame_path: Path) -> dict[str, Any]:
    if not frame_path.exists():
        return {
            "available": False,
            "quality": empty_quality([f"frame_missing:{frame_path}"]),
            "color_palette": [],
            "grid": [],
            "warnings": [f"frame_missing:{frame_path}"],
        }
    try:
        from PIL import Image, ImageOps

        with Image.open(frame_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            return {
                "available": True,
                "quality": frame_quality(image),
                "color_palette": frame_color_palette(image),
                "grid": frame_color_grid(image),
                "warnings": [],
            }
    except Exception as exc:
        return {
            "available": False,
            "quality": empty_quality([f"visual_feature_failed:{exc}"]),
            "color_palette": [],
            "grid": [],
            "warnings": [f"visual_feature_failed:{exc}"],
        }


def frame_quality(image: Any) -> dict[str, Any]:
    from PIL import ImageStat

    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    brightness = float(stat.mean[0])
    contrast = float(stat.stddev[0])
    return {
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "brightness_level": "dark" if brightness < 55 else "bright" if brightness > 205 else "normal",
        "contrast_level": "low" if contrast < 20 else "high" if contrast > 70 else "normal",
        "warnings": [],
    }


def empty_quality(warnings: list[str]) -> dict[str, Any]:
    return {
        "brightness": None,
        "contrast": None,
        "brightness_level": "unknown",
        "contrast_level": "unknown",
        "warnings": warnings,
    }


def frame_color_palette(image: Any, limit: int = 8) -> list[dict[str, Any]]:
    from PIL import Image

    sample = image.copy()
    sample.thumbnail((160, 160))
    quantized = sample.quantize(colors=limit, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    colors = quantized.getcolors(sample.width * sample.height) or []
    total = max(1, sum(count for count, _ in colors))
    result: list[dict[str, Any]] = []
    for count, index in sorted(colors, reverse=True):
        offset = int(index) * 3
        if offset + 2 >= len(palette):
            continue
        rgb = tuple(int(value) for value in palette[offset : offset + 3])
        result.append({"hex": hex_color(rgb), "rgb": list(rgb), "ratio": round(count / total, 4)})
    return result


def frame_color_grid(image: Any, rows: int = 3, cols: int = 3) -> list[dict[str, Any]]:
    from PIL import ImageStat

    width, height = image.size
    grid: list[dict[str, Any]] = []
    for row in range(rows):
        for col in range(cols):
            left = round((col * width) / cols)
            top = round((row * height) / rows)
            right = round(((col + 1) * width) / cols)
            bottom = round(((row + 1) * height) / rows)
            tile = image.crop((left, top, right, bottom))
            stat = ImageStat.Stat(tile)
            rgb = tuple(int(round(value)) for value in stat.mean[:3])
            grid.append(
                {
                    "cell_id": f"grid_{row}_{col}",
                    "row": row,
                    "col": col,
                    "bbox_norm": [
                        round(left / width, 6) if width else 0.0,
                        round(top / height, 6) if height else 0.0,
                        round(right / width, 6) if width else 0.0,
                        round(bottom / height, 6) if height else 0.0,
                    ],
                    "average_color": {"hex": hex_color(rgb), "rgb": list(rgb)},
                }
            )
    return grid


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, value)):02x}" for value in rgb)


def empty_ocr(mode: str, model: str | None) -> dict[str, Any]:
    return {
        "mode": mode,
        "model": model,
        "has_text": False,
        "full_text": "",
        "blocks": [],
        "warnings": [],
    }


def normalize_ocr_mode(mode: str) -> str:
    normalized = str(mode or "auto").strip().casefold()
    if normalized not in OCR_MODES:
        raise ValueError(f"ocr mode must be one of: {', '.join(OCR_MODES)}")
    return normalized


def parse_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence > 1:
        confidence /= 100.0
    return round(confidence, 4)


def confidence_level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.85:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def normalized_bbox(
    left: float,
    top: float,
    right: float,
    bottom: float,
    width: int,
    height: int,
) -> list[float]:
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(max(0.0, min(1.0, left / width)), 6),
        round(max(0.0, min(1.0, top / height)), 6),
        round(max(0.0, min(1.0, right / width)), 6),
        round(max(0.0, min(1.0, bottom / height)), 6),
    ]


def denormalized_bbox(values: list[Any], width: int, height: int) -> tuple[float, float, float, float]:
    if len(values) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        float(values[0]) * width,
        float(values[1]) * height,
        float(values[2]) * width,
        float(values[3]) * height,
    )


def write_frame_ocr(record: dict[str, Any], frame_ocr_path: Path) -> dict[str, Any]:
    write_json(frame_ocr_path, record)
    return record
