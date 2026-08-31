"""Global OpenAI-compatible provider registry and model discovery."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml
from platformdirs import user_cache_path, user_config_path

from hound_agent.fsio import atomic_write

PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REGISTRY_PATH = user_config_path("hound-agent") / "providers.yml"
CACHE_PATH = user_cache_path("hound-agent") / "models.json"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(_NoRedirect()).open


def validate_base_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an HTTP(S) URL")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("remote provider base URL must use HTTPS")
    return value


def load_custom_providers(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read provider registry: {exc}") from exc
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("provider registry must contain a providers mapping")
    return {str(key): dict(value) for key, value in providers.items() if isinstance(value, dict)}


def save_custom_provider(provider_id: str, definition: dict, path: Path = REGISTRY_PATH) -> None:
    if not PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("provider ID must use lowercase letters, digits, hyphen, or underscore")
    base_url = validate_base_url(str(definition.get("base_url", "")))
    providers = load_custom_providers(path)
    providers[provider_id] = {
        "name": str(definition.get("name") or provider_id),
        "base_url": base_url,
        "default_model": str(definition.get("default_model") or ""),
        "models": sorted({str(item) for item in definition.get("models", []) if str(item).strip()}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({"version": 1, "providers": providers}, sort_keys=False))


def remove_custom_provider(provider_id: str, path: Path = REGISTRY_PATH) -> None:
    providers = load_custom_providers(path)
    providers.pop(provider_id, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({"version": 1, "providers": providers}, sort_keys=False))


def discover_models(base_url: str, api_key: str = "", timeout: float = 10.0) -> list[str]:
    base_url = validate_base_url(base_url)
    endpoint = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with urlopen(Request(endpoint, headers=headers), timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("authentication failed") from exc
        raise ValueError(f"provider returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise ValueError(f"provider unavailable: {exc}") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("model response is too large")
    try:
        data = json.loads(raw)
        models = sorted({str(item["id"]) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")}, key=str.lower)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("provider returned an invalid model catalog") from exc
    if not models:
        raise ValueError("provider returned no models")
    return models[:5000]


def cache_models(provider_id: str, base_url: str, models: list[str], path: Path = CACHE_PATH) -> None:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[provider_id] = {"base_url": base_url, "models": models, "updated_at": time.time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2))


def cached_models(provider_id: str, path: Path = CACHE_PATH) -> list[str]:
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get(provider_id, {}).get("models", []))
    except (OSError, ValueError, TypeError):
        return []
