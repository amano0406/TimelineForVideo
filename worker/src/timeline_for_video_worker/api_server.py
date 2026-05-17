from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .discovery import SUPPORTED_VIDEO_EXTENSIONS
from .discovery import discover_video_files
from .items import download_items
from .items import list_items
from .items import remove_items
from .model_inventory import build_model_inventory
from .operations import paginate_rows
from .processor import refresh_configured_items
from .sampling import DEFAULT_SAMPLES_PER_VIDEO
from .settings import PRODUCT_NAME
from .settings import load_example_settings
from .settings import load_settings
from .settings import redact_settings
from .settings import save_settings
from .settings import settings_example_path
from .settings import settings_path


def handle_request(method: str, path: str, request: dict[str, Any] | None) -> tuple[int, Any]:
    route = path.rstrip("/") or "/"
    if method == "GET" and route == "/health":
        return HTTPStatus.OK, health_payload()
    if method != "POST":
        return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")

    try:
        payload = request or {}
        if route == "/settings/init":
            return HTTPStatus.OK, settings_init_payload(payload)
        if route == "/settings/status":
            return HTTPStatus.OK, settings_status_payload()
        if route == "/settings/save":
            return HTTPStatus.OK, settings_save_payload(payload)
        if route == "/files/list":
            return HTTPStatus.OK, files_list_payload(payload)
        if route == "/items/list":
            return HTTPStatus.OK, items_list_payload(payload)
        if route == "/items/refresh":
            return status_for_operation_payload(items_refresh_payload(payload))
        if route == "/items/download":
            return status_for_operation_payload(items_download_payload(payload))
        if route == "/items/remove":
            return status_for_operation_payload(items_remove_payload(payload))
        if route == "/models/list":
            return HTTPStatus.OK, models_list_payload(payload)
    except Exception as exc:
        return HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)

    return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")


def health_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "product": PRODUCT_NAME,
        "version": __version__,
        "inDocker": os.environ.get("TIMELINE_FOR_VIDEO_IN_DOCKER") == "1",
        "settingsPath": str(settings_path()),
    }


def settings_init_payload(request: dict[str, Any]) -> dict[str, Any]:
    target = settings_path()
    force = get_bool_any(request, ["force"], False)
    created = False
    overwritten = False

    if target.exists() and not force:
        settings = load_settings(target)
    else:
        overwritten = target.exists()
        settings = save_settings(load_example_settings(), target)
        created = not overwritten

    return {
        "ok": True,
        "created": created,
        "overwritten": overwritten,
        "settingsPath": str(target),
        "settingsExamplePath": str(settings_example_path()),
        "settings": redact_settings(settings),
    }


def settings_status_payload() -> dict[str, Any]:
    target = settings_path()
    exists = target.exists()
    settings = load_settings(target) if exists else None
    return {
        "ok": True,
        "exists": exists,
        "settingsPath": str(target),
        "settingsExamplePath": str(settings_example_path()),
        "settings": redact_settings(settings),
    }


def settings_save_payload(request: dict[str, Any]) -> dict[str, Any]:
    target = settings_path()
    settings = load_settings(target) if target.exists() else load_example_settings()

    input_roots = get_string_array_any(request, ["inputRoots", "input_roots", "inputRoot", "input_root"])
    if input_roots:
        settings["inputRoots"] = input_roots
    output_root = get_string_any(request, ["outputRoot", "output_root"])
    if output_root:
        settings["outputRoot"] = output_root
    if get_bool_any(request, ["clearToken", "clear_token"], False):
        settings["huggingFaceToken"] = ""
    token = get_string_any(request, ["token", "huggingFaceToken", "huggingfaceToken"])
    if token:
        settings["huggingFaceToken"] = token
    compute_mode = get_string_any(request, ["computeMode", "compute_mode"])
    if compute_mode:
        settings["computeMode"] = compute_mode

    settings = save_settings(settings, target)
    return {
        "ok": True,
        "settingsPath": str(target),
        "settings": redact_settings(settings),
    }


def files_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    discovery_payload = discover_video_files(settings).to_dict()
    files, pagination = paginate_rows(
        discovery_payload["files"],
        page=get_optional_positive_int(request, ["page"]),
        page_size=get_optional_positive_int(request, ["pageSize", "page_size"]),
        total_key="totalFiles",
        returned_key="returnedFiles",
    )
    discovery_payload["files"] = files
    discovery_payload["pagination"] = pagination
    discovery_payload["counts"] = {
        **discovery_payload["counts"],
        "returnedFiles": len(files),
    }
    return {
        "ok": True,
        "settingsPath": str(settings_path()),
        "supportedExtensions": list(SUPPORTED_VIDEO_EXTENSIONS),
        **discovery_payload,
    }


def items_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    result = list_items(settings["outputRoot"])
    items, pagination = paginate_rows(
        result["items"],
        page=get_optional_positive_int(request, ["page"]),
        page_size=get_optional_positive_int(request, ["pageSize", "page_size"]),
        total_key="totalItems",
        returned_key="returnedItems",
    )
    return {
        "settingsPath": str(settings_path()),
        **result,
        "counts": {
            **result["counts"],
            "returnedItems": len(items),
        },
        "pagination": pagination,
        "items": items,
    }


def items_refresh_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    try:
        result = refresh_configured_items(
            settings,
            ffprobe_bin=get_string_any(request, ["ffprobeBin", "ffprobe_bin"]) or "ffprobe",
            ffmpeg_bin=get_string_any(request, ["ffmpegBin", "ffmpeg_bin"]) or "ffmpeg",
            max_items=get_optional_positive_int(request, ["maxItems", "max_items", "limit"]),
            samples_per_video=get_optional_positive_int(request, ["samplesPerVideo", "samples_per_video"])
            or DEFAULT_SAMPLES_PER_VIDEO,
            ocr_mode=get_string_any(request, ["ocrMode", "ocr_mode"]) or "auto",
            audio_model_mode=get_string_any(request, ["audioModelMode", "audio_model_mode"]) or None,
            reprocess_duplicates=get_bool_any(request, ["reprocessDuplicates", "reprocess_duplicates"], False),
        )
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "settingsPath": str(settings_path()),
            "error": str(exc),
        }

    return {
        "settingsPath": str(settings_path()),
        **result,
    }


def items_download_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    return {
        "settingsPath": str(settings_path()),
        **download_items(settings["outputRoot"], item_ids=get_item_ids(request)),
    }


def items_remove_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    return {
        "settingsPath": str(settings_path()),
        **remove_items(
            settings["outputRoot"],
            dry_run=get_bool_any(request, ["dryRun", "dry_run"], False),
            item_ids=get_item_ids(request),
        ),
    }


def models_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    output = get_string_any(request, ["outputPath", "output"])
    settings = load_settings() if settings_path().exists() else None
    payload = build_model_inventory(
        ffprobe_bin=get_string_any(request, ["ffprobeBin", "ffprobe_bin"]) or "ffprobe",
        ffmpeg_bin=get_string_any(request, ["ffmpegBin", "ffmpeg_bin"]) or "ffmpeg",
        ocr_mode=get_string_any(request, ["ocrMode", "ocr_mode"]) or "auto",
        settings=settings,
        include_remote=get_bool_any(request, ["includeRemote", "include_remote", "remote"], False),
    )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def status_for_operation_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    status = HTTPStatus.OK if payload.get("ok") is not False else HTTPStatus.INTERNAL_SERVER_ERROR
    return status, payload


def get_item_ids(request: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for value in get_string_array_any(request, ["itemIds", "item_ids", "itemId", "item_id"]):
        for part in value.split(","):
            stripped = part.strip()
            if stripped and stripped not in result:
                result.append(stripped)
    return result


def get_optional_positive_int(request: dict[str, Any], names: list[str]) -> int | None:
    for name in names:
        value = get_node(request, name)
        if value is None:
            continue
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                continue
            return parsed if parsed > 0 else None
    return None


def get_bool_any(request: dict[str, Any], names: list[str], fallback: bool) -> bool:
    for name in names:
        value = get_node(request, name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
    return fallback


def get_string_any(request: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = get_node(request, name)
        if value is None:
            continue
        text = convert_json_text(value)
        if text:
            return text
    return ""


def get_string_array_any(request: dict[str, Any], names: list[str]) -> list[str]:
    for name in names:
        values = get_string_array(request, name)
        if values:
            return values
    return []


def get_string_array(request: dict[str, Any], name: str) -> list[str]:
    value = get_node(request, name)
    if value is None:
        return []
    if isinstance(value, list):
        return [convert_json_text(item) for item in value if convert_json_text(item)]
    text = convert_json_text(value)
    if not text:
        return []
    return [part.strip() for part in text.replace("\r", ",").replace("\n", ",").split(",") if part.strip()]


def get_node(request: dict[str, Any], name: str) -> Any:
    if name in request:
        return request[name]
    lowered = name.lower()
    for key, value in request.items():
        if key.lower() == lowered:
            return value
    return None


def convert_json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False).strip()


def error_payload(message: str, error_type: str = "Error") -> dict[str, Any]:
    return {"ok": False, "error": {"type": error_type, "message": message}}


class TimelineForVideoApiHandler(BaseHTTPRequestHandler):
    server_version = "TimelineForVideoWorkerApi/1.0"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle(self) -> None:
        try:
            request = self._read_json()
            status_code, payload = handle_request(self.command, self.path.split("?", 1)[0], request)
        except Exception as exc:
            status_code, payload = HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)
        self._write_json(status_code, payload)

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        if not raw.strip():
            return None
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("JSON request body must be an object.")
        return loaded

    def _write_json(self, status_code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = os.environ.get("TIMELINE_FOR_VIDEO_API_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("TIMELINE_FOR_VIDEO_API_BIND_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), TimelineForVideoApiHandler)
    print(f"TimelineForVideo worker API listening on http://{host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
