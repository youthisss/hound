"""Shared path-matching helper used by fallback analysis and severity triage."""
from __future__ import annotations


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
