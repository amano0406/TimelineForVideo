from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, UnidentifiedImageError


FRAME_TRANSITION_GATE_SCHEMA_VERSION = "timeline_for_video.frame_transition_gate.v1"
DEFAULT_GATE_WIDTH = 480
DEFAULT_GATE_HEIGHT = 270
DEFAULT_PIXEL_THRESHOLD = 18


@dataclass(frozen=True)
class FrameTransitionGatePolicy:
    target_model: str = "Qwen/Qwen3.5-4B"
    width: int = DEFAULT_GATE_WIDTH
    height: int = DEFAULT_GATE_HEIGHT
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD
    mean_same_max: float = 0.00055
    changed_ratio_same_max: float = 0.0012
    largest_component_ratio_same_max: float = 0.00055
    volatile_masked_ratio_max: float = 0.18
    needs_vlm_changed_ratio_min: float = 0.006
    needs_vlm_mean_min: float = 0.0018
    needs_vlm_largest_component_ratio_min: float = 0.0025
    needs_vlm_largest_bbox_area_min: float = 0.02


def analyze_frame_transition_gate(
    frame_records: list[dict[str, Any]],
    *,
    policy: FrameTransitionGatePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FrameTransitionGatePolicy()
    usable_frames = [
        frame
        for frame in frame_records
        if isinstance(frame, dict) and frame.get("ok") and frame.get("outputPath")
    ]
    transitions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, (previous, current) in enumerate(zip(usable_frames, usable_frames[1:]), start=1):
        transition = analyze_frame_pair(previous, current, index=index, policy=policy)
        transitions.append(transition)
        warnings.extend(transition.get("warnings", []))

    counts = count_transitions(transitions)
    return {
        "schemaVersion": FRAME_TRANSITION_GATE_SCHEMA_VERSION,
        "available": bool(transitions) and not all(not transition["ok"] for transition in transitions),
        "strategy": "cheap_visual_gate_before_vlm",
        "targetModel": policy.target_model,
        "policy": asdict(policy),
        "volatileMasks": volatile_masks(),
        "counts": counts,
        "transitions": transitions,
        "warnings": sorted(set(warnings)),
    }


def analyze_frame_pair(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    index: int,
    policy: FrameTransitionGatePolicy,
) -> dict[str, Any]:
    base = {
        "index": index,
        "fromFrameId": previous.get("frameId"),
        "toFrameId": current.get("frameId"),
        "fromTimeSec": previous.get("timeSec"),
        "toTimeSec": current.get("timeSec"),
        "ok": False,
        "decision": "unavailable",
        "wouldSendToVlm": True,
        "reasons": ["visual_gate_unavailable"],
        "raw": empty_metrics(),
        "masked": empty_metrics(),
        "warnings": [],
    }
    try:
        left = normalized_frame(Path(str(previous["outputPath"])), policy)
        right = normalized_frame(Path(str(current["outputPath"])), policy)
    except (FileNotFoundError, OSError, UnidentifiedImageError) as exc:
        base["warnings"] = [f"visual_gate_image_unavailable:{base['fromFrameId']}:{base['toFrameId']}:{exc}"]
        return base

    raw_diff = ImageChops.difference(left, right)
    masked_diff = raw_diff.copy()
    apply_volatile_masks(masked_diff)
    raw = diff_metrics(raw_diff, policy.pixel_threshold)
    masked = diff_metrics(masked_diff, policy.pixel_threshold)
    decision, reasons = decide(raw, masked, policy)
    base.update(
        {
            "ok": True,
            "decision": decision,
            "wouldSendToVlm": decision in {"needs_vlm", "uncertain", "unavailable"},
            "reasons": reasons,
            "raw": raw,
            "masked": masked,
        }
    )
    return base


def normalized_frame(path: Path, policy: FrameTransitionGatePolicy) -> Image.Image:
    with Image.open(path) as raw:
        image = raw.convert("L").resize((policy.width, policy.height), Image.Resampling.BILINEAR)
    return image.filter(ImageFilter.GaussianBlur(radius=1.0))


def apply_volatile_masks(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for mask in volatile_masks():
        left = int(width * mask["x"])
        top = int(height * mask["y"])
        right = int(width * (mask["x"] + mask["width"]))
        bottom = int(height * (mask["y"] + mask["height"]))
        draw.rectangle([left, top, right, bottom], fill=0)


def volatile_masks() -> list[dict[str, Any]]:
    return [
        {
            "name": "taskbar_clock_or_capture_timer",
            "x": 0.78,
            "y": 0.90,
            "width": 0.22,
            "height": 0.10,
        },
        {
            "name": "video_player_elapsed_time",
            "x": 0.00,
            "y": 0.90,
            "width": 0.22,
            "height": 0.10,
        },
    ]


def diff_metrics(diff: Image.Image, threshold: int) -> dict[str, Any]:
    data = diff.tobytes()
    total = len(data)
    changed = bytearray(255 if value >= threshold else 0 for value in data)
    changed_pixels = sum(1 for value in changed if value)
    components = connected_components(changed, diff.size)
    largest = components[0] if components else empty_component()
    return {
        "meanDiff": round(sum(data) / (total * 255.0), 8) if total else 0.0,
        "changedPixels": changed_pixels,
        "changedRatio": round(changed_pixels / total, 8) if total else 0.0,
        "componentCount": len(components),
        "largestComponent": largest,
        "largestComponentRatio": round(largest["pixels"] / total, 8) if total else 0.0,
        "largestBboxArea": largest.get("bboxArea", 0.0),
    }


def connected_components(mask: bytearray, size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = size
    total = width * height
    visited = bytearray(total)
    components: list[dict[str, Any]] = []
    for start in range(total):
        if not mask[start] or visited[start]:
            continue
        queue: deque[int] = deque([start])
        visited[start] = 1
        pixels = 0
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0
        while queue:
            index = queue.popleft()
            pixels += 1
            x = index % width
            y = index // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            if x > 0:
                add_neighbor(index - 1, mask, visited, queue)
            if x < width - 1:
                add_neighbor(index + 1, mask, visited, queue)
            if y > 0:
                add_neighbor(index - width, mask, visited, queue)
            if y < height - 1:
                add_neighbor(index + width, mask, visited, queue)
        bbox_width = max_x - min_x + 1
        bbox_height = max_y - min_y + 1
        components.append(
            {
                "pixels": pixels,
                "bbox": {
                    "x": round(min_x / width, 6),
                    "y": round(min_y / height, 6),
                    "width": round(bbox_width / width, 6),
                    "height": round(bbox_height / height, 6),
                },
                "bboxArea": round((bbox_width * bbox_height) / total, 8),
            }
        )
    return sorted(components, key=lambda item: item["pixels"], reverse=True)


def add_neighbor(index: int, mask: bytearray, visited: bytearray, queue: deque[int]) -> None:
    if mask[index] and not visited[index]:
        visited[index] = 1
        queue.append(index)


def decide(
    raw: dict[str, Any],
    masked: dict[str, Any],
    policy: FrameTransitionGatePolicy,
) -> tuple[str, list[str]]:
    raw_ratio = float(raw["changedRatio"])
    raw_pixels = int(raw["changedPixels"])
    masked_pixels = int(masked["changedPixels"])
    if (
        raw_ratio > 0
        and masked_pixels <= max(4, int(raw_pixels * policy.volatile_masked_ratio_max))
        and masked["meanDiff"] <= policy.mean_same_max
        and masked["largestComponentRatio"] <= policy.largest_component_ratio_same_max
    ):
        return "skip_volatile_only", ["raw_difference_is_mostly_inside_volatile_masks"]

    if (
        masked["meanDiff"] <= policy.mean_same_max
        and masked["changedRatio"] <= policy.changed_ratio_same_max
        and masked["largestComponentRatio"] <= policy.largest_component_ratio_same_max
    ):
        return "skip_same", ["masked_difference_below_safe_same_thresholds"]

    reasons: list[str] = []
    if masked["changedRatio"] >= policy.needs_vlm_changed_ratio_min:
        reasons.append("changed_ratio_exceeds_vlm_threshold")
    if masked["meanDiff"] >= policy.needs_vlm_mean_min:
        reasons.append("mean_diff_exceeds_vlm_threshold")
    if masked["largestComponentRatio"] >= policy.needs_vlm_largest_component_ratio_min:
        reasons.append("component_size_exceeds_vlm_threshold")
    if masked["largestBboxArea"] >= policy.needs_vlm_largest_bbox_area_min:
        reasons.append("component_bbox_exceeds_vlm_threshold")
    if reasons:
        return "needs_vlm", reasons
    return "uncertain", ["cheap_gate_cannot_safely_skip"]


def count_transitions(transitions: list[dict[str, Any]]) -> dict[str, Any]:
    by_decision: dict[str, int] = {}
    for transition in transitions:
        decision = str(transition.get("decision") or "unknown")
        by_decision[decision] = by_decision.get(decision, 0) + 1
    return {
        "transitions": len(transitions),
        "byDecision": by_decision,
        "wouldSendToVlm": sum(1 for transition in transitions if transition.get("wouldSendToVlm")),
        "wouldSkip": sum(1 for transition in transitions if not transition.get("wouldSendToVlm")),
        "failedTransitions": sum(1 for transition in transitions if not transition.get("ok")),
    }


def empty_metrics() -> dict[str, Any]:
    return {
        "meanDiff": 0.0,
        "changedPixels": 0,
        "changedRatio": 0.0,
        "componentCount": 0,
        "largestComponent": empty_component(),
        "largestComponentRatio": 0.0,
        "largestBboxArea": 0.0,
    }


def empty_component() -> dict[str, Any]:
    return {
        "pixels": 0,
        "bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
        "bboxArea": 0.0,
    }
