"""Persistent, cross-platform configuration shared by all application tools."""

# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json

from platformdirs import user_config_path


APP_NAME = "world-stage-recap-maker"
CONFIG_FILENAME = "config.json"
LEGACY_PREPARE_S3_FILENAME = "prepare-s3.json"

RECAP_DEFAULTS: dict[str, str | bool] = {
    "card_renderer": "inkscape",
    "inkscape": "inkscape",
    "resvg": "rsvg-convert",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "browser": "",
    "po_token": "",
    "av1_preset": "8",
    "av1_crf": "30",
    "av1_threads": "0",
    "opus_bitrate": "160k",
    "audio_normalization": "two-pass",
    "jobs": "0",
}


def config_directory() -> Path:
    return Path(user_config_path(APP_NAME, appauthor=False, ensure_exists=True))


def config_path() -> Path:
    return config_directory() / CONFIG_FILENAME


def _read_config() -> dict[str, object]:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid configuration in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid configuration in {path}: expected a JSON object")
    return data


def _write_config(data: Mapping[str, object]) -> Path:
    path = config_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def recap_settings() -> dict[str, str | bool]:
    """Return recap defaults with persisted values overlaid."""
    values = RECAP_DEFAULTS.copy()
    stored = _read_config().get("recap", {})
    if isinstance(stored, dict):
        for key, default in RECAP_DEFAULTS.items():
            value = stored.get(key)
            if isinstance(value, type(default)):
                values[key] = value
    return values


def update_recap_settings(values: Mapping[str, object]) -> Path:
    """Persist only recognized recap settings, keeping other sections intact."""
    data = _read_config()
    stored = data.get("recap")
    recap = dict(stored) if isinstance(stored, dict) else {}
    for key, default in RECAP_DEFAULTS.items():
        if key in values and isinstance(values[key], type(default)):
            recap[key] = values[key]
    data["recap"] = recap
    return _write_config(data)


def s3_settings() -> dict[str, str] | None:
    """Return persisted S3 settings, migrating the former prepare-only file."""
    data = _read_config()
    stored = data.get("s3")
    if isinstance(stored, dict) and all(isinstance(stored.get(key), str) for key in ("endpoint_url", "bucket", "profile")):
        return {key: str(stored[key]).strip() for key in ("endpoint_url", "bucket", "profile")}

    legacy_path = config_directory() / LEGACY_PREPARE_S3_FILENAME
    try:
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid legacy S3 configuration in {legacy_path}: {exc}") from exc
    if not isinstance(legacy, dict):
        raise RuntimeError(f"Invalid legacy S3 configuration in {legacy_path}: expected a JSON object")
    values = {key: str(legacy.get(key, "")).strip() for key in ("endpoint_url", "bucket", "profile")}
    if not all(values.values()):
        raise RuntimeError(f"Invalid legacy S3 configuration in {legacy_path}")
    update_s3_settings(values)
    return values


def update_s3_settings(values: Mapping[str, object]) -> Path:
    required = ("endpoint_url", "bucket", "profile")
    s3 = {key: str(values.get(key, "")).strip() for key in required}
    if not all(s3.values()):
        raise ValueError("S3 endpoint URL, bucket, and profile are all required")
    data = _read_config()
    data["s3"] = s3
    return _write_config(data)
