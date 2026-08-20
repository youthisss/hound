"""Assign a component to the failure using a glob map or path heuristic."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from hound_agent.models import Artifacts

DEFAULT_COMPONENT = "unowned"


def _first_match(path: str, comp_map: dict[str, str]) -> str | None:
    for pattern, component in comp_map.items():
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/") + "/*"):
            return component
    return None


def assign(artifacts: Artifacts, components: dict[str, str]) -> str:
    if components:
        for path in _candidate_paths(artifacts):
            comp = _first_match(path, components)
            if comp:
                return comp

    for f in artifacts.frames:
        if not f.file:
            continue
        top = _top_dir(f.file)
        if top:
            return top
    for t in artifacts.failed_tests:
        if t.file:
            top = _top_dir(t.file)
            if top:
                return top
    return DEFAULT_COMPONENT


def _candidate_paths(artifacts: Artifacts) -> list[str]:
    paths = [f.file for f in artifacts.frames if f.file]
    paths += [t.file for t in artifacts.failed_tests if t.file]
    paths += artifacts.git.changed_files
    return paths


def _top_dir(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if parts else ""
