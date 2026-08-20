"""Parse stack frames from Python tracebacks and compiler errors."""
from __future__ import annotations

import re
from pathlib import Path

from hound_agent.models import StackFrame

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in (.+))?')
_PY_FRAME2 = re.compile(r"\s+([^:\n]+\.py):(\d+):\s+in (\S+)")
_PY_FRAME3 = re.compile(r"^([^:\n]+\.py):(\d+):\s*(.+)?$")
_CC_FRAME = re.compile(r"([^:\n]+\.(?:c|cpp|cc|h|ts|js|go|rs|java)):(\d+):(\d+):\s+error:?\s+(.+)", re.IGNORECASE)


def parse_stacktrace(text: str) -> list[StackFrame]:
    frames: list[StackFrame] = []
    seen: set[tuple[str, int, str | None]] = set()
    for line in text.splitlines():
        m = _PY_FRAME.search(line)
        if m:
            f = StackFrame(
                file=m.group(1),
                line=int(m.group(2)),
                function=m.group(3),
            )
        else:
            m2 = _PY_FRAME2.search(line)
            if m2:
                f = StackFrame(file=m2.group(1), line=int(m2.group(2)), function=m2.group(3))
            else:
                m3 = _PY_FRAME3.search(line)
                if m3:
                    f = StackFrame(file=m3.group(1), line=int(m3.group(2)), function=m3.group(3))
                else:
                    m4 = _CC_FRAME.search(line)
                    if m4:
                        f = StackFrame(file=m4.group(1), line=int(m4.group(2)), function=None)
                    else:
                        continue
        key = (f.file, f.line, f.function)
        if key in seen:
            continue
        seen.add(key)
        frames.append(f)
    return frames


def dedupe_repo_paths(frames: list[StackFrame], repo_dir: str | None = None) -> list[StackFrame]:
    """Resolve/trim frame paths relative to a repo dir; keep as-is if absent."""
    if not repo_dir:
        return frames
    base = Path(repo_dir).resolve()
    out: list[StackFrame] = []
    for f in frames:
        try:
            candidate = Path(f.file)
            resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
            f.file = str(resolved.relative_to(base)).replace("\\", "/")
        except (ValueError, OSError):
            continue
        out.append(f)
    return out


SNIPPET_PAD = 2
MAX_SOURCE_FILE_BYTES = 1024 * 1024


def attach_snippets(frames: list[StackFrame], repo_dir: str | None = None) -> list[StackFrame]:
    """Attach ±``SNIPPET_PAD`` source lines around each frame's file:line.

    Frames must already be repo-relative (see ``dedupe_repo_paths``). Missing
    or unreadable files are skipped silently; the frame is left unchanged.
    """
    if not repo_dir:
        return frames
    base = Path(repo_dir).resolve()
    cache: dict[str, list[str]] = {}
    for f in frames:
        if not f.file or f.line <= 0:
            continue
        try:
            candidate = Path(f.file)
            full = candidate.resolve(strict=True) if candidate.is_absolute() else (base / candidate).resolve(strict=True)
            full.relative_to(base)
        except (ValueError, OSError):
            continue
        if not full.is_file():
            continue
        key = str(full)
        if key not in cache:
            try:
                cache[key] = (
                    full.read_text(encoding="utf-8", errors="replace").splitlines()
                    if full.stat().st_size <= MAX_SOURCE_FILE_BYTES else []
                )
            except OSError:
                cache[key] = []
        lines = cache[key]
        if not lines:
            continue
        start = max(f.line - 1 - SNIPPET_PAD, 0)
        end = min(f.line - 1 + SNIPPET_PAD + 1, len(lines))
        if start >= end:
            continue
        f.code = "\n".join(f"{i + 1} | {lines[i]}" for i in range(start, end))
    return frames
