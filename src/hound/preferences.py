"""Persistent, non-secret preferences for the interactive TUI."""
from __future__ import annotations

from pathlib import Path

import yaml
from platformdirs import user_config_path

from hound.fsio import atomic_write, read_bounded_text
from hound.pathutil import path_has_symlink

PREFERENCES_PATH = user_config_path("hound") / "tui.yml"
MAX_PREFERENCES_BYTES = 256 * 1024

_DEFAULTS = {
    "offline": True,
    "provider": None,
    "model": None,
    "base_url": None,
    "repo_dir": None,
    "context_path": None,
    "source_class": None,
    "source_context": False,
    "enrich": False,
    "jobs": 1,
    "max_llm_calls": None,
    "max_cost_usd": None,
    "redact": None,
    "no_dedup": False,
    "max_retries": None,
}


def load_tui_preferences(path: Path = PREFERENCES_PATH) -> dict:
    defaults = dict(_DEFAULTS)
    if path_has_symlink(path) or path.is_symlink() or not path.exists():
        return defaults
    try:
        data = yaml.safe_load(read_bounded_text(path, MAX_PREFERENCES_BYTES, encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    def optional_text(key: str) -> str | None:
        value = data.get(key)
        return str(value).strip() or None if value is not None else None

    def optional_positive_int(key: str, default: int | None) -> int | None:
        value = data.get(key)
        if value is None:
            return default
        try:
            return int(value) if int(value) > 0 else default
        except (TypeError, ValueError):
            return default

    def optional_positive_float(key: str) -> float | None:
        value = data.get(key)
        if value is None:
            return None
        try:
            return float(value) if float(value) > 0 else None
        except (TypeError, ValueError):
            return None

    def optional_retry_count() -> int | None:
        value = data.get("max_retries")
        if value is None:
            return None
        try:
            retries = int(value)
        except (TypeError, ValueError):
            return None
        return retries if 0 <= retries <= 10 else None

    return {
        "offline": data.get("offline") if isinstance(data.get("offline"), bool) else True,
        "provider": optional_text("provider"),
        "model": optional_text("model"),
        "base_url": optional_text("base_url"),
        "repo_dir": optional_text("repo_dir"),
        "context_path": optional_text("context_path"),
        "source_class": optional_text("source_class"),
        "source_context": data.get("source_context") if isinstance(data.get("source_context"), bool) else False,
        "enrich": data.get("enrich") if isinstance(data.get("enrich"), bool) else False,
        "jobs": optional_positive_int("jobs", 1) or 1,
        "max_llm_calls": optional_positive_int("max_llm_calls", None),
        "max_cost_usd": optional_positive_float("max_cost_usd"),
        "redact": data.get("redact") if isinstance(data.get("redact"), bool) else None,
        "no_dedup": data.get("no_dedup") if isinstance(data.get("no_dedup"), bool) else False,
        "max_retries": optional_retry_count(),
    }


def save_tui_preferences(
    offline: bool,
    provider: str | None,
    model: str | None,
    path: Path = PREFERENCES_PATH,
    *,
    base_url: str | None = None,
    repo_dir: str | None = None,
    context_path: str | None = None,
    source_class: str | None = None,
    source_context: bool = False,
    enrich: bool = False,
    jobs: int = 1,
    max_llm_calls: int | None = None,
    max_cost_usd: float | None = None,
    redact: bool | None = None,
    no_dedup: bool = False,
    max_retries: int | None = None,
) -> Path:
    """Persist the complete non-secret TUI settings snapshot atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({
        "version": 3,
        "offline": bool(offline),
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "repo_dir": repo_dir,
        "context_path": context_path,
        "source_class": source_class,
        "source_context": bool(source_context),
        "enrich": bool(enrich),
        "jobs": jobs,
        "max_llm_calls": max_llm_calls,
        "max_cost_usd": max_cost_usd,
        "redact": redact,
        "no_dedup": bool(no_dedup),
        "max_retries": max_retries,
    }, sort_keys=False))
    return path
