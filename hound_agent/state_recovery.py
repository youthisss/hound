"""Helpers for preserving damaged SQLite state before operator recovery."""
from __future__ import annotations

from pathlib import Path
import shutil
import time


def preserve_corrupt_sqlite(path: str | Path) -> Path:
    source = Path(path)
    recovery = source.with_name(f"{source.name}.corrupt-{time.time_ns()}")
    recovery.mkdir(parents=False, exist_ok=False)
    for candidate in (source, Path(f"{source}-wal"), Path(f"{source}-shm")):
        if candidate.exists() and not candidate.is_symlink():
            shutil.move(str(candidate), recovery / candidate.name)
    return recovery
