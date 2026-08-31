"""Persistent, non-secret preferences for the interactive TUI."""
from __future__ import annotations

from pathlib import Path

import yaml
from platformdirs import user_config_path

from hound.fsio import atomic_write

PREFERENCES_PATH = user_config_path("hound") / "tui.yml"


def load_tui_preferences(path: Path = PREFERENCES_PATH) -> dict:
    defaults = {"offline": True, "provider": None, "model": None}
    if not path.exists():
        return defaults
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    offline = data.get("offline")
    return {
        "offline": offline if isinstance(offline, bool) else True,
        "provider": str(data["provider"]) if data.get("provider") else None,
        "model": str(data["model"]) if data.get("model") else None,
    }


def save_tui_preferences(offline: bool, provider: str | None, model: str | None, path: Path = PREFERENCES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({
        "version": 1,
        "offline": bool(offline),
        "provider": provider,
        "model": model,
    }, sort_keys=False))
    return path
