from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _read_env(primary_key: str, legacy_key: str, default: str) -> str:
    value = os.getenv(primary_key)
    if value:
        return value
    value = os.getenv(legacy_key)
    if value:
        return value
    return default


def appdata_root() -> Path:
    return Path(
        _read_env("TIMELINEFORVIDEO_APPDATA_ROOT", "VIDEO2TIMELINE_APPDATA_ROOT", "/data/app-data")
    )


def uploads_root() -> Path:
    return Path(
        _read_env("TIMELINEFORVIDEO_UPLOADS_ROOT", "VIDEO2TIMELINE_UPLOADS_ROOT", "/data/input")
    )


def outputs_root() -> Path:
    return Path(
        _read_env(
            "TIMELINEFORVIDEO_OUTPUTS_ROOT",
            "VIDEO2TIMELINE_OUTPUTS_ROOT",
            "/data/output",
        )
    )


def runtime_defaults_path() -> Path:
    return Path(
        _read_env(
            "TIMELINEFORVIDEO_RUNTIME_DEFAULTS",
            "VIDEO2TIMELINE_RUNTIME_DEFAULTS",
            "/app/config/runtime.defaults.json",
        )
    )


def load_runtime_defaults() -> dict[str, Any]:
    path = runtime_defaults_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def settings_path() -> Path:
    return appdata_root() / "settings.json"


def token_path() -> Path:
    return appdata_root() / "secrets" / "huggingface.token"


def worker_capabilities_path() -> Path:
    return appdata_root() / "worker-capabilities.json"


def load_settings() -> dict[str, Any]:
    if settings_path().exists():
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    else:
        defaults = load_runtime_defaults()
        payload = {
            "schemaVersion": 1,
            "inputRoots": defaults.get("inputRoots", []),
            "outputRoots": defaults.get("outputRoots", []),
            "videoExtensions": defaults.get("videoExtensions", []),
            "huggingfaceTermsConfirmed": False,
            "computeMode": "cpu",
            "processingQuality": "standard",
            "uiLanguage": "en",
        }
    payload["inputRoots"] = [
        {
            "id": "input",
            "displayName": "Input",
            "path": str(uploads_root()),
            "enabled": True,
        }
    ]
    payload["outputRoots"] = [
        {
            "id": "runs",
            "displayName": "Runs",
            "path": str(outputs_root()),
            "enabled": True,
        }
    ]
    payload["computeMode"] = str(payload.get("computeMode") or "cpu").strip().lower()
    if payload["computeMode"] not in {"cpu", "gpu"}:
        payload["computeMode"] = "cpu"
    payload["processingQuality"] = (
        str(payload.get("processingQuality") or "standard").strip().lower()
    )
    if payload["processingQuality"] not in {"standard", "high"}:
        payload["processingQuality"] = "standard"
    payload["uiLanguage"] = str(payload.get("uiLanguage") or "en").strip() or "en"
    return payload


def load_huggingface_token() -> str | None:
    path = token_path()
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8", errors="replace").strip()
    return value or None


def save_settings(payload: dict[str, Any]) -> None:
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_huggingface_token(token: str | None) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if token and token.strip():
        path.write_text(token.strip(), encoding="utf-8")
        return
    if path.exists():
        path.unlink()


def save_worker_capabilities(payload: dict[str, Any]) -> None:
    path = worker_capabilities_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
