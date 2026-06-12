from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PRODUCT_NAME = "TimelineForVideo"
SCHEMA_VERSION = 1

SETTINGS_PATH_ENV = "TIMELINE_FOR_VIDEO_SETTINGS_PATH"
SETTINGS_EXAMPLE_PATH_ENV = "TIMELINE_FOR_VIDEO_SETTINGS_EXAMPLE_PATH"
INTERNAL_STATE_ROOT_ENV = "TIMELINE_FOR_VIDEO_INTERNAL_STATE_ROOT"
HUGGING_FACE_TOKEN_ENV = "TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN"
SUPPORTED_COMPUTE_MODES = ("cpu", "gpu")
DEFAULT_API_PORT = 19500
TOKEN_SETTING_KEY = "huggingfaceToken"
LEGACY_TOKEN_SETTING_KEY = "huggingFaceToken"

DEFAULT_SETTINGS: dict[str, Any] = {
    "schemaVersion": SCHEMA_VERSION,
    "runtime": {
        "instanceName": "",
        "apiPort": DEFAULT_API_PORT,
    },
    "inputRoots": ["C:\\TimelineData\\input-video\\"],
    "outputRoot": "C:\\TimelineData\\video",
    TOKEN_SETTING_KEY: "",
    "computeMode": "gpu",
}


class SettingsError(ValueError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def settings_path() -> Path:
    configured = os.environ.get(SETTINGS_PATH_ENV)
    if configured:
        return Path(configured)
    return repo_root() / "settings.json"


def settings_example_path() -> Path:
    configured = os.environ.get(SETTINGS_EXAMPLE_PATH_ENV)
    if configured:
        return Path(configured)
    return repo_root() / "settings.example.json"


def internal_state_root() -> Path:
    configured = os.environ.get(INTERNAL_STATE_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    if os.environ.get("TIMELINE_FOR_VIDEO_IN_DOCKER") == "1":
        return Path("/shared/app-data/timeline-for-video-state")
    return (repo_root() / ".timeline-for-video-state").resolve()


def default_settings() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SettingsError(f"Settings file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SettingsError(f"Settings file is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise SettingsError(f"Settings file must contain a JSON object: {path}")
    return raw


def load_example_settings() -> dict[str, Any]:
    path = settings_example_path()
    if path.exists():
        return normalize_settings(read_json(path))
    return default_settings()


def load_settings(path: Path | None = None) -> dict[str, Any]:
    return normalize_settings(read_json(path or settings_path()))


def normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    schema_version = raw.get("schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SettingsError(f"Unsupported schemaVersion: {schema_version!r}")

    input_roots_raw = raw.get("inputRoots")
    if not isinstance(input_roots_raw, list):
        raise SettingsError("inputRoots must be a list of path strings.")

    input_roots: list[str] = []
    seen: set[str] = set()
    for value in input_roots_raw:
        if not isinstance(value, str):
            raise SettingsError("inputRoots must contain only path strings.")
        normalized = value.strip()
        if not normalized:
            raise SettingsError("inputRoots cannot contain empty paths.")
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            input_roots.append(normalized)

    output_root_raw = raw.get("outputRoot")
    if not isinstance(output_root_raw, str) or not output_root_raw.strip():
        raise SettingsError("outputRoot must be a non-empty path string.")

    token_raw = raw.get(TOKEN_SETTING_KEY, raw.get(LEGACY_TOKEN_SETTING_KEY, ""))
    if token_raw is None:
        token_raw = ""
    if not isinstance(token_raw, str):
        raise SettingsError(f"{TOKEN_SETTING_KEY} must be a string when configured.")

    compute_mode = str(raw.get("computeMode", "gpu") or "gpu").strip().casefold()
    if compute_mode not in SUPPORTED_COMPUTE_MODES:
        raise SettingsError(f"computeMode must be one of: {', '.join(SUPPORTED_COMPUTE_MODES)}")

    runtime = normalize_runtime_settings(raw.get("runtime"))
    normalized: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
    }
    if runtime:
        normalized["runtime"] = runtime
    normalized.update(
        {
            "inputRoots": input_roots,
            "outputRoot": output_root_raw.strip(),
            TOKEN_SETTING_KEY: token_raw.strip(),
            "computeMode": compute_mode,
        }
    )

    return normalized


def normalize_runtime_settings(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError("runtime must be an object when configured.")

    normalized: dict[str, Any] = {}

    instance_name = raw.get("instanceName", "")
    if instance_name is None:
        instance_name = ""
    if not isinstance(instance_name, str):
        raise SettingsError("runtime.instanceName must be a string when configured.")
    instance_name = instance_name.strip().lower()
    if instance_name.startswith("local-"):
        instance_name = instance_name[6:]
    if instance_name:
        normalized["instanceName"] = instance_name

    api_port = raw.get("apiPort", DEFAULT_API_PORT)
    if api_port is None or api_port == "":
        api_port = DEFAULT_API_PORT
    if not isinstance(api_port, int):
        raise SettingsError("runtime.apiPort must be an integer when configured.")
    if api_port < 1 or api_port > 65535:
        raise SettingsError("runtime.apiPort must be between 1 and 65535.")
    normalized["apiPort"] = api_port

    return normalized


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    normalized = normalize_settings(settings)
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def load_huggingface_token(settings: dict[str, Any] | None = None) -> str | None:
    env_token = os.environ.get(HUGGING_FACE_TOKEN_ENV) or os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    if settings:
        token = settings.get(TOKEN_SETTING_KEY, settings.get(LEGACY_TOKEN_SETTING_KEY))
        if isinstance(token, str) and token.strip():
            return token.strip()
    return None


def redact_settings(settings: dict[str, Any] | None) -> dict[str, Any] | None:
    if settings is None:
        return None
    redacted = dict(settings)
    legacy_token = redacted.pop(LEGACY_TOKEN_SETTING_KEY, None)
    token = redacted.get(TOKEN_SETTING_KEY, legacy_token)
    redacted[TOKEN_SETTING_KEY] = {
        "configured": bool(isinstance(token, str) and token.strip()),
        "source": "settings" if isinstance(token, str) and token.strip() else None,
    }
    if load_huggingface_token(settings) and not (isinstance(token, str) and token.strip()):
        redacted[TOKEN_SETTING_KEY] = {
            "configured": True,
            "source": "environment",
        }
    return redacted
