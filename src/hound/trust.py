"""Fail-closed trust profiles for artifact sources and optional capabilities."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SOURCE_CLASSES = {"trusted_branch", "fork_pr", "local_artifact"}
MAX_EVENT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TrustPolicy:
    source_class: str
    allow_source_context: bool
    allow_enrichment: bool
    allow_llm: bool
    allow_delivery: bool


_POLICIES = {
    "trusted_branch": TrustPolicy("trusted_branch", True, True, True, True),
    "local_artifact": TrustPolicy("local_artifact", True, True, True, True),
    "fork_pr": TrustPolicy("fork_pr", False, False, False, False),
}


def policy_for(source_class: str) -> TrustPolicy:
    try:
        return _POLICIES[source_class]
    except KeyError as exc:
        raise ValueError(f"source class must be one of {sorted(SOURCE_CLASSES)}") from exc


def resolve_source_class(
    explicit: str | None = None,
    configured: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Resolve explicit/configured policy, then detect untrusted CI forks."""
    env = environment if environment is not None else os.environ
    selected = explicit or configured or env.get("HOUND_SOURCE_CLASS")
    if selected is None and "TH_SOURCE_CLASS" in env:
        sys.stderr.write("Warning: TH_SOURCE_CLASS is deprecated; use HOUND_SOURCE_CLASS.\n")
        selected = env.get("TH_SOURCE_CLASS")
    if selected:
        selected = selected.strip().lower()
        if selected not in SOURCE_CLASSES:
            raise ValueError(f"source class must be one of {sorted(SOURCE_CLASSES)}")
        return selected

    github_event = env.get("GITHUB_EVENT_NAME", "").lower()
    if github_event in {"pull_request", "pull_request_target"}:
        # A missing or malformed PR event is treated as untrusted. This is
        # intentionally conservative because source access and delivery are
        # higher-risk than an offline fallback analysis.
        event = _github_event(env.get("GITHUB_EVENT_PATH", ""))
        head = _nested(event, "pull_request", "head", "repo", "full_name")
        base = _nested(event, "pull_request", "base", "repo", "full_name")
        if not head or not base or head != base:
            return "fork_pr"
        return "trusted_branch"

    source_project = env.get("CI_MERGE_REQUEST_SOURCE_PROJECT_ID")
    target_project = env.get("CI_PROJECT_ID")
    if source_project and target_project:
        return "fork_pr" if source_project != target_project else "trusted_branch"
    return "local_artifact"


def _github_event(value: str) -> dict:
    if not value:
        return {}
    path = Path(value)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVENT_BYTES:
            return {}
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _nested(value: dict, *keys: str) -> str:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current if isinstance(current, str) else ""
