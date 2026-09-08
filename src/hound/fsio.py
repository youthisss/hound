"""Shared low-level filesystem helpers.

Lives outside the ``output/`` package so configuration and collection code
can use atomic persistence without depending on the reporting layer.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from hound.pathutil import path_has_symlink


def open_verified_regular(path: str | Path, *, flags: int = os.O_RDONLY) -> int:
    """Open an existing regular file without accepting a symlink alias.

    The preflight checks provide useful diagnostics while ``O_NOFOLLOW`` (where
    the platform exposes it), descriptor/file identity checks, and a second
    path walk close the common check-then-open race.  Callers must consume the
    returned descriptor rather than reopening ``path``.
    """
    target = Path(path).expanduser()
    if path_has_symlink(target) or target.is_symlink():
        raise ValueError(f"path must not contain symlinks: {target}")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags | nofollow)
    try:
        descriptor_stat = os.fstat(fd)
        target_stat = os.stat(target, follow_symlinks=False)
        if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
            raise ValueError(f"path must be a regular file: {target}")
        if not os.path.samestat(descriptor_stat, target_stat):
            raise ValueError(f"path changed while it was opened: {target}")
        if path_has_symlink(target) or target.is_symlink():
            raise ValueError(f"path must not contain symlinks: {target}")
        return fd
    except Exception:
        os.close(fd)
        raise


def read_bounded_bytes(path: str | Path, limit: int) -> bytes:
    """Read at most ``limit`` bytes from one verified regular file.

    A byte beyond the limit is read only to distinguish an oversized file; it
    is never retained or returned.
    """
    if limit < 0:
        raise ValueError("read limit must not be negative")
    fd = open_verified_regular(path)
    try:
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(limit + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > limit:
        raise ValueError(f"file exceeds the {limit}-byte limit")
    return data


def read_bounded_text(path: str | Path, limit: int, *, encoding: str = "utf-8", errors: str = "strict") -> str:
    """Decode a bounded, descriptor-verified regular file."""
    return read_bounded_bytes(path, limit).decode(encoding, errors=errors)


def atomic_write(path: str | Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via temp file + ``os.replace``."""
    target = Path(path)
    if path_has_symlink(target) or target.is_symlink() or path_has_symlink(target.parent):
        raise ValueError(f"atomic write target must not contain symlinks: {target}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        # The destination and its parent are operator-controlled paths.  Check
        # again immediately before replacement so a newly inserted symlink is
        # rejected rather than silently replaced through an unsafe alias.
        if path_has_symlink(target) or target.is_symlink() or path_has_symlink(target.parent):
            raise ValueError(f"atomic write target must not contain symlinks: {target}")
        os.replace(temporary, target)
    except Exception:
        # os.fdopen owns the fd; the with-block already closed it on error.
        # Never close it again: on a loaded system the descriptor number may
        # have been reused, and a second close would hit an unrelated file.
        temporary.unlink(missing_ok=True)
        raise
