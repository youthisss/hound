"""Resolve external tools without searching untrusted working directories."""
from __future__ import annotations

import os
from pathlib import Path


def trusted_executable(name: str, *excluded_roots: str | Path) -> str | None:
    """Return an absolute executable path from trusted absolute PATH entries."""
    if Path(name).name != name:
        return None
    blocked = [Path.cwd().resolve(), *(Path(root).resolve() for root in excluded_roots)]
    safe_entries: list[Path] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry).expanduser()
        if not directory.is_absolute():
            continue
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if any(resolved == root or root in resolved.parents for root in blocked):
            continue
        safe_entries.append(resolved)
    names = [name]
    if os.name == "nt" and not Path(name).suffix:
        names = [name + suffix.lower() for suffix in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)]
    for directory in safe_entries:
        for executable_name in names:
            candidate = directory / executable_name
            try:
                if not candidate.is_file() or (os.name != "nt" and not os.access(candidate, os.X_OK)):
                    continue
                resolved_candidate = candidate.resolve()
            except OSError:
                continue
            if any(resolved_candidate == root or root in resolved_candidate.parents for root in blocked):
                continue
            return str(resolved_candidate)
    return None
