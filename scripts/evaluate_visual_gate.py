from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter


SCHEMA_VERSION = 1
KIND = "timeline_for_video.frame_diff_visual_gate_eval"
DEFAULT_WIDTH = 480
DEFAULT_HEIGHT = 270
DEFAULT_PIXEL_THRESHOLD = 18


@dataclass(frozen=True)
class GatePolicy:
    pixel_threshold: int
    mean_same_max: float = 0.00055
    changed_ratio_same_max: float = 0.0012
    largest_component_ratio_same_max: float = 0.00055
    volatile_masked_ratio_max: float = 0.18
    needs_vlm_changed_ratio_min: float = 0.006
    needs_vlm_mean_min: float = 0.0018
    needs_vlm_largest_component_ratio_min: float = 0.0025
    needs_vlm_largest_bbox_area_min: float = 0.02


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a cheap visual gate before VLM frame-diff processing.")
    parser.add_argument("--sample-root", required=True)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--pixel-threshold", type=int, default=DEFAULT_PIXEL_THRESHOLD)
    parser.add_argument("--summary-output", default="visual_gate_eval_summary.json")
    parser.add_argument("--html-output", default="visual_gate_report.html")
    args = parser.parse_args()

    sample_root = Path(args.sample_root)
    summary = evaluate_sample_root(
        sample_root=sample_root,
        size=(args.width, args.height),
        policy=GatePolicy(pixel_threshold=args.pixel_threshold),
    )
    summary_path = sample_root / args.summary_output
    html_path = sample_root / args.html_output
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "summary": str(summary_path),
                "html": str(html_path),
                "counts": summary["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def evaluate_sample_root(*, sample_root: Path, size: tuple[int, int], policy: GatePolicy) -> dict[str, Any]:
    multi_model = read_json(sample_root / "multi_model_eval_summary.json")
    qwen_by_pair = qwen35_results_by_pair(multi_model)
    manifest_pairs = pairs_from_summary_or_manifest(sample_root, multi_model)
    pairs: list[dict[str, Any]] = []
    for pair in manifest_pairs:
        pair_id = pair["pairId"]
        pair_dir = sample_root / pair_id
        left = pair_dir / "left.jpg"
        right = pair_dir / "right.jpg"
        gate = evaluate_pair(left, right, size=size, policy=policy)
        write_gate_mask(pair_dir / "visual_gate_mask.png", gate["images"]["mask"])
        gate["images"]["mask"] = f"{pair_id}/visual_gate_mask.png"
        qwen = qwen_by_pair.get(pair_id)
        pairs.append(
            {
                "pairId": pair_id,
                "category": pair.get("category"),
                "leftTimeSec": pair.get("leftTimeSec"),
                "rightTimeSec": pair.get("rightTimeSec"),
                "images": {
                    "left": f"{pair_id}/left.jpg",
                    "right": f"{pair_id}/right.jpg",
                    "diff": f"{pair_id}/diff_overlay.jpg",
                    "gateMask": gate["images"]["mask"],
                },
                "sourceMetrics": pair.get("metrics"),
                "gate": without_image_objects(gate),
                "qwen35": qwen,
            }
        )

    counts = count_pairs(pairs)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "generatedAtLocal": datetime.now().replace(microsecond=0).isoformat(),
        "sampleRoot": str(sample_root),
        "policy": {
            "strategy": "cheap_visual_gate_before_qwen3_5_4b",
            "size": {"width": size[0], "height": size[1]},
            **policy.__dict__,
            "volatileMasks": volatile_masks(),
            "decisionSemantics": {
                "skip_same": "High-confidence near-identical pair. Do not send to Qwen3.5.",
                "skip_volatile_only": "Raw difference exists but is mostly inside known volatile UI zones.",
                "needs_vlm": "Meaningful visual movement is large enough to send to Qwen3.5.",
                "uncertain": "Cheap gate cannot decide safely. Send to Qwen3.5.",
            },
        },
        "counts": counts,
        "pairs": pairs,
    }


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def qwen35_results_by_pair(summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not summary:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for pair in summary.get("pairs", []):
        if not isinstance(pair, dict):
            continue
        pair_id = str(pair.get("pairId") or "")
        qwen = (pair.get("results") or {}).get("qwen3.5-4b")
        if pair_id and isinstance(qwen, dict):
            result[pair_id] = qwen
    return result


def pairs_from_summary_or_manifest(sample_root: Path, summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if summary and isinstance(summary.get("pairs"), list):
        return [
            pair
            for pair in summary["pairs"]
            if isinstance(pair, dict) and pair.get("pairId")
        ]
    manifest = read_json(sample_root / "manifest.json")
    if manifest and isinstance(manifest.get("pairs"), list):
        return [
            {
                "pairId": pair.get("sampleId"),
                "category": pair.get("category"),
                "leftTimeSec": pair.get("leftTimeSec"),
                "rightTimeSec": pair.get("rightTimeSec"),
                "metrics": pair.get("metrics"),
            }
            for pair in manifest["pairs"]
            if isinstance(pair, dict) and pair.get("sampleId")
        ]
    return [
        {"pairId": path.name, "category": None, "leftTimeSec": None, "rightTimeSec": None, "metrics": None}
        for path in sorted(sample_root.glob("pair-*"))
        if path.is_dir()
    ]


def evaluate_pair(left_path: Path, right_path: Path, *, size: tuple[int, int], policy: GatePolicy) -> dict[str, Any]:
    left = normalized_frame(left_path, size)
    right = normalized_frame(right_path, size)
    raw_diff = ImageChops.difference(left, right)
    masked_diff = raw_diff.copy()
    apply_volatile_masks(masked_diff)

    raw = diff_metrics(raw_diff, policy.pixel_threshold)
    masked = diff_metrics(masked_diff, policy.pixel_threshold)
    decision, reasons = decide(raw, masked, policy)
    return {
        "decision": decision,
        "wouldSendToVlm": decision in {"needs_vlm", "uncertain"},
        "reasons": reasons,
        "raw": raw,
        "masked": masked,
        "images": {"mask": binary_mask(masked_diff, policy.pixel_threshold)},
    }


def normalized_frame(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as raw:
        image = raw.convert("L").resize(size, Image.Resampling.BILINEAR)
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
    components = connected_components(changed, diff.size)
    largest = components[0] if components else empty_component()
    return {
        "meanDiff": round(sum(data) / (total * 255.0), 8) if total else 0.0,
        "changedPixels": sum(1 for value in changed if value),
        "changedRatio": round(sum(1 for value in changed if value) / total, 8) if total else 0.0,
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


def empty_component() -> dict[str, Any]:
    return {
        "pixels": 0,
        "bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
        "bboxArea": 0.0,
    }


def binary_mask(diff: Image.Image, threshold: int) -> Image.Image:
    return diff.point(lambda value: 255 if value >= threshold else 0).convert("L")


def write_gate_mask(path: Path, mask: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path)


def decide(raw: dict[str, Any], masked: dict[str, Any], policy: GatePolicy) -> tuple[str, list[str]]:
    reasons: list[str] = []
    raw_ratio = float(raw["changedRatio"])
    masked_ratio = float(masked["changedRatio"])
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
        and masked_ratio <= policy.changed_ratio_same_max
        and masked["largestComponentRatio"] <= policy.largest_component_ratio_same_max
    ):
        return "skip_same", ["masked_difference_below_safe_same_thresholds"]

    if (
        masked_ratio >= policy.needs_vlm_changed_ratio_min
        or masked["meanDiff"] >= policy.needs_vlm_mean_min
        or masked["largestComponentRatio"] >= policy.needs_vlm_largest_component_ratio_min
        or masked["largestBboxArea"] >= policy.needs_vlm_largest_bbox_area_min
    ):
        if masked_ratio >= policy.needs_vlm_changed_ratio_min:
            reasons.append("changed_ratio_exceeds_vlm_threshold")
        if masked["meanDiff"] >= policy.needs_vlm_mean_min:
            reasons.append("mean_diff_exceeds_vlm_threshold")
        if masked["largestComponentRatio"] >= policy.needs_vlm_largest_component_ratio_min:
            reasons.append("component_size_exceeds_vlm_threshold")
        if masked["largestBboxArea"] >= policy.needs_vlm_largest_bbox_area_min:
            reasons.append("component_bbox_exceeds_vlm_threshold")
        return "needs_vlm", reasons

    return "uncertain", ["cheap_gate_cannot_safely_skip"]


def without_image_objects(gate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in gate.items() if key != "images"}


def count_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    by_decision: dict[str, int] = {}
    qwen_changed_by_decision: dict[str, dict[str, int]] = {}
    for pair in pairs:
        decision = pair["gate"]["decision"]
        by_decision[decision] = by_decision.get(decision, 0) + 1
        qwen = pair.get("qwen35") or {}
        bucket = qwen_changed_by_decision.setdefault(decision, {"changedTrue": 0, "changedFalse": 0, "unknown": 0})
        if qwen.get("changed") is True:
            bucket["changedTrue"] += 1
        elif qwen.get("changed") is False:
            bucket["changedFalse"] += 1
        else:
            bucket["unknown"] += 1
    return {
        "pairs": len(pairs),
        "byDecision": by_decision,
        "wouldSendToVlm": sum(1 for pair in pairs if pair["gate"]["wouldSendToVlm"]),
        "wouldSkip": sum(1 for pair in pairs if not pair["gate"]["wouldSendToVlm"]),
        "qwen35ChangedByDecision": qwen_changed_by_decision,
    }


def render_html(summary: dict[str, Any]) -> str:
    style = """:root{color-scheme:light;--line:#d8dee8;--soft:#f5f7fa;--ink:#172033;--muted:#667085;--send:#0f766e;--skip:#475569;--uncertain:#a16207;--bad:#b42318}body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;color:var(--ink);background:#fff}header.page{padding:24px 28px 18px;border-bottom:1px solid var(--line);background:#f8fafc;position:sticky;top:0;z-index:2}main{padding:0 28px 40px}h1{font-size:22px;margin:0 0 8px}h2{font-size:18px;margin:0 0 4px}h3{font-size:16px;margin:22px 0 8px}.subtle,.metrics{color:var(--muted);font-size:12px}.note{max-width:1120px;line-height:1.65;font-size:14px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid var(--line);padding:7px 8px;vertical-align:top}th{background:#eef2f7;text-align:left}.num{text-align:right;white-space:nowrap}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:600;background:#e5e7eb;color:#374151;white-space:nowrap}.badge.needs_vlm{background:#ccfbf1;color:var(--send)}.badge.uncertain{background:#fef3c7;color:var(--uncertain)}.badge.skip_same,.badge.skip_volatile_only{background:#e2e8f0;color:var(--skip)}.badge.yes{background:#ccfbf1;color:var(--send)}.badge.no{background:#e2e8f0;color:var(--skip)}.pair{margin-top:28px;padding-top:18px;border-top:2px solid #e5e7eb}.images{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 14px}figure{margin:0;border:1px solid var(--line);background:var(--soft)}figcaption{padding:4px 8px;font-size:12px;color:var(--muted)}img{width:100%;height:auto;display:block;cursor:zoom-in}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.panel{border:1px solid var(--line);border-radius:6px;padding:9px}.kv{font-size:12px;line-height:1.55}.lightbox{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(15,23,42,.88);z-index:10;padding:28px}.lightbox.open{display:flex}.lightbox img{max-width:96vw;max-height:90vh;width:auto;height:auto;cursor:zoom-out;box-shadow:0 20px 60px rgba(0,0,0,.45);background:white}.lightbox button{position:fixed;top:18px;right:20px;border:1px solid rgba(255,255,255,.45);background:rgba(15,23,42,.7);color:white;border-radius:6px;padding:8px 12px;cursor:pointer}@media(max-width:1000px){.images{grid-template-columns:1fr 1fr}header.page{position:static}main{padding:0 14px 28px}}"""
    parts = [
        '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Visual Gate Eval</title>",
        f"<style>{style}</style></head><body>",
        f'<header class="page"><h1>Visual Gate Eval</h1><div class="subtle">Generated {escape(summary["generatedAtLocal"])} / sample root: {escape(summary["sampleRoot"])}</div></header>',
        "<main>",
        '<p class="note">This report evaluates a cheap pre-filter before Qwen3.5-4B. The gate only skips high-confidence near-identical pairs; uncertain pairs are intentionally still routed to Qwen3.5.</p>',
    ]
    counts = summary["counts"]
    parts.append("<h3>Summary</h3><table><tbody>")
    parts.append(f'<tr><th>Pairs</th><td class="num">{counts["pairs"]}</td></tr>')
    parts.append(f'<tr><th>Would send to Qwen3.5</th><td class="num">{counts["wouldSendToVlm"]}</td></tr>')
    parts.append(f'<tr><th>Would skip</th><td class="num">{counts["wouldSkip"]}</td></tr>')
    for decision, count in counts["byDecision"].items():
        parts.append(f'<tr><th>{escape(decision)}</th><td class="num">{count}</td></tr>')
    parts.append("</tbody></table>")
    parts.append("<h3>Pair Index</h3><table><thead><tr><th>Pair</th><th>Category</th><th>Gate</th><th>Qwen3.5</th><th>Masked Changed Ratio</th><th>Largest Component</th><th>Reason</th></tr></thead><tbody>")
    for pair in summary["pairs"]:
        gate = pair["gate"]
        qwen = pair.get("qwen35") or {}
        qwen_badge = "yes" if qwen.get("changed") is True else "no" if qwen.get("changed") is False else ""
        parts.append(
            "<tr>"
            f'<td><a href="#{escape(pair["pairId"])}">{escape(pair["pairId"])}</a></td>'
            f'<td>{escape(str(pair.get("category") or ""))}</td>'
            f'<td><span class="badge {escape(gate["decision"])}">{escape(gate["decision"])}</span></td>'
            f'<td><span class="badge {qwen_badge}">{escape(str(qwen.get("changed")))}</span></td>'
            f'<td class="num">{gate["masked"]["changedRatio"]:.6f}</td>'
            f'<td class="num">{gate["masked"]["largestComponentRatio"]:.6f}</td>'
            f'<td>{escape(", ".join(gate["reasons"]))}</td>'
            "</tr>"
        )
    parts.append("</tbody></table>")
    for pair in summary["pairs"]:
        parts.append(render_pair(pair))
    parts.append("</main>")
    parts.append('<div class="lightbox" id="image-lightbox" aria-hidden="true"><button type="button">Close</button><img alt="expanded image"></div>')
    parts.append("<script>const lightbox=document.getElementById('image-lightbox');const expanded=lightbox.querySelector('img');const closeButton=lightbox.querySelector('button');function closeLightbox(){lightbox.classList.remove('open');lightbox.setAttribute('aria-hidden','true');expanded.removeAttribute('src')}document.querySelectorAll('.images img').forEach((img)=>{img.addEventListener('click',()=>{expanded.src=img.src;expanded.alt=img.alt;lightbox.classList.add('open');lightbox.setAttribute('aria-hidden','false')})});lightbox.addEventListener('click',(event)=>{if(event.target===lightbox||event.target===expanded)closeLightbox()});closeButton.addEventListener('click',closeLightbox);document.addEventListener('keydown',(event)=>{if(event.key==='Escape')closeLightbox()});</script>")
    parts.append("</body></html>")
    return "".join(parts)


def render_pair(pair: dict[str, Any]) -> str:
    gate = pair["gate"]
    qwen = pair.get("qwen35") or {}
    qwen_badge = "yes" if qwen.get("changed") is True else "no" if qwen.get("changed") is False else ""
    images = pair["images"]
    parts = [
        f'<section class="pair" id="{escape(pair["pairId"])}">',
        f'<h2>{escape(pair["pairId"])}</h2>',
        f'<div class="subtle">{escape(str(pair.get("category") or ""))} / {escape(str(pair.get("leftTimeSec")))}s -&gt; {escape(str(pair.get("rightTimeSec")))}s</div>',
        '<div class="images">',
    ]
    for key, caption in [("left", "A"), ("right", "B"), ("diff", "existing diff"), ("gateMask", "gate mask")]:
        parts.append(f'<figure><img src="{escape(images[key])}" alt="{escape(pair["pairId"])} {caption}"><figcaption>{escape(caption)}</figcaption></figure>')
    parts.append("</div><div class=\"grid\">")
    parts.append(
        '<div class="panel">'
        f'<strong>Gate</strong> <span class="badge {escape(gate["decision"])}">{escape(gate["decision"])}</span>'
        f'<div class="kv">wouldSendToVlm: {escape(str(gate["wouldSendToVlm"]))}<br>'
        f'reasons: {escape(", ".join(gate["reasons"]))}<br>'
        f'masked meanDiff: {gate["masked"]["meanDiff"]:.8f}<br>'
        f'masked changedRatio: {gate["masked"]["changedRatio"]:.8f}<br>'
        f'largest component ratio: {gate["masked"]["largestComponentRatio"]:.8f}<br>'
        f'largest bbox area: {gate["masked"]["largestBboxArea"]:.8f}</div>'
        "</div>"
    )
    parts.append(
        '<div class="panel">'
        f'<strong>Qwen3.5-4B</strong> <span class="badge {qwen_badge}">{escape(str(qwen.get("changed")))}</span>'
        f'<div class="kv">level: {escape(str(qwen.get("changeLevel")))}<br>'
        f'confidence: {escape(str(qwen.get("confidence")))}<br>'
        f'summary: {escape(str(qwen.get("summary") or ""))}</div>'
        "</div>"
    )
    source = pair.get("sourceMetrics") or {}
    parts.append(
        '<div class="panel">'
        '<strong>Original sample metrics</strong>'
        f'<div class="kv">meanDiff: {escape(str(source.get("meanDiff")))}<br>'
        f'changedRatio: {escape(str(source.get("changedRatio")))}<br>'
        f'bboxArea: {escape(str(source.get("bboxArea")))}</div>'
        "</div>"
    )
    parts.append("</div></section>")
    return "".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
