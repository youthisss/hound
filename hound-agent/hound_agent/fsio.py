"""Shared low-level filesystem helpers.

Lives outside the ``output/`` package so configuration and collection code
can use atomic persistence without depending on the reporting layer.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via temp file + ``os.replace``."""
    target = Path(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    except Exception:
        # os.fdopen owns the fd; the with-block already closed it on error.
        # Never close it again: on a loaded system the descriptor number may
        # have been reused, and a second close would hit an unrelated file.
        temporary.unlink(missing_ok=True)
        raise
