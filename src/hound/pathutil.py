"""Shared path-matching helper used by fallback analysis and severity triage."""
from __future__ import annotations

from pathlib import Path


def path_matches(file: str, changed: set[str]) -> bool:
    """True if ``file`` (a stack frame path) matches any changed file path.

    Matching is done on normalized (forward-slash) paths and is symmetrical:
    either side may be the shorter path. Returns False for empty input.
    """
    if not file:
        return False
    f = file.replace("\\", "/")
    for raw_c in changed:
        c = raw_c.replace("\\", "/")
        if not c:
            continue
        if c == f or f.endswith("/" + c) or c.endswith("/" + f):
            return True
    return False


def path_has_symlink(path: str | Path) -> bool:
    """Return whether an existing component of ``path`` is a symlink.

    ``Path.resolve()`` intentionally follows links, which is useful for
    containment checks but loses the information needed to reject an input
    alias.  Walk the original components first so callers can fail closed
    before resolving a trusted-root path.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor) if candidate.anchor else Path.cwd()
    for part in candidate.parts:
        if part == candidate.anchor:
            continue
        current /= part
        if current.is_symlink():
            return True
    return False
