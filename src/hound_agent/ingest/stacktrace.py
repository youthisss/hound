"""Parse source and deployment-config locations from CI/CD failures."""
from __future__ import annotations

import re
from pathlib import Path

from hound_agent.models import StackFrame

MAX_STACK_FRAMES = 100
MAX_SNIPPET_FRAMES = 20

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in (.+))?')
_PY_FRAME2 = re.compile(r"\s+([^:\n]+\.py):(\d+):\s+in (\S+)")
_PY_FRAME3 = re.compile(r"^([^:\n]+\.py):(\d+):\s*(.+)?$")
_CC_FRAME = re.compile(r"([^:\n]+\.(?:c|cpp|cc|h|ts|js|go|rs|java)):(\d+):(\d+):\s+error:?\s+(.+)", re.IGNORECASE)
_JAVA_FRAME = re.compile(
    r"^\s*at\s+([\w$.]+)\(([\w./\\$-]+\.java):(\d+)\)",
)
_V8_FRAME = re.compile(
    r"^\s*at\s+(.+?)\s+\(([^\s()]+):(\d+):(\d+)\)\s*$",
)
_CSHARP_FRAME = re.compile(
    r"^\s*at\s+.+?\sin\s+([^\s:]+\.cs):line\s+(\d+)",
    re.IGNORECASE,
)
_CONFIG_PATH = r"(?:[A-Za-z]:[\\/]|/)?(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.(?:yaml|yml|tf|tpl)"
_CONFIG_FRAME = re.compile(
    rf"(?<![A-Za-z0-9_./-])(?P<file>{_CONFIG_PATH}):(?P<line>[1-9]\d*)(?::[1-9]\d*)?(?=\s|$|:)",
    re.IGNORECASE,
)
_TERRAFORM_FRAME = re.compile(
    rf"\bon\s+(?P<file>{_CONFIG_PATH})\s+line\s+(?P<line>[1-9]\d*)\b",
    re.IGNORECASE,
)


def parse_stacktrace(text: str) -> list[StackFrame]:
    frames: list[StackFrame] = []
    seen: set[tuple[str, int, str | None]] = set()
    for line in text.splitlines():
        f = _match_frame(line)
        if f is None:
            continue
        key = (f.file, f.line, f.function)
        if key in seen:
            continue
        seen.add(key)
        frames.append(f)
        if len(frames) >= MAX_STACK_FRAMES:
            break
    return frames


def _qualified_function(qualified: str) -> str:
    """Keep the last two segments of a qualified JVM method name."""
    parts = [p for p in qualified.split(".") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return parts[-1] if parts else ""


def _match_frame(line: str) -> StackFrame | None:
    m = _PY_FRAME.search(line)
    if m:
        return StackFrame(file=m.group(1), line=int(m.group(2)), function=m.group(3))
    m = _PY_FRAME2.search(line)
    if m:
        return StackFrame(file=m.group(1), line=int(m.group(2)), function=m.group(3))
    m = _PY_FRAME3.search(line)
    if m:
        return StackFrame(file=m.group(1), line=int(m.group(2)), function=m.group(3))
    m = _CC_FRAME.search(line)
    if m:
        return StackFrame(file=m.group(1), line=int(m.group(2)), function=None)
    m = _CONFIG_FRAME.search(line)
    if m:
        return StackFrame(file=m.group("file"), line=int(m.group("line")), function=None)
    m = _TERRAFORM_FRAME.search(line)
    if m:
        return StackFrame(file=m.group("file"), line=int(m.group("line")), function=None)
    # Java: "at com.pkg.Class.method(com/pkg/File.java:12)"
    m = _JAVA_FRAME.match(line)
    if m:
        return StackFrame(
            file=m.group(2).replace("\\", "/"),
            line=int(m.group(3)),
            function=_qualified_function(m.group(1)),
        )
    # JavaScript V8/Bun/Deno: "at fn (path/file.js:12:34)"
    m = _V8_FRAME.match(line)
    if m:
        return StackFrame(file=m.group(2), line=int(m.group(3)), function=m.group(1).strip() or None)
    # C#: "at Ns.Class.Method(...) in /src/File.cs:line 18"
    m = _CSHARP_FRAME.match(line)
    if m:
        return StackFrame(file=m.group(1), line=int(m.group(2)), function=None)
    return None


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
SNIPPET_SUFFIXES = {
    ".py",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".ts",
    ".js",
    ".go",
    ".rs",
    ".java",
    ".yaml",
    ".yml",
    ".tf",
    ".tpl",
}


def attach_snippets(frames: list[StackFrame], repo_dir: str | None = None) -> list[StackFrame]:
    """Attach ±``SNIPPET_PAD`` source lines around each frame's file:line.

    Frames must already be repo-relative (see ``dedupe_repo_paths``). Missing
    or unreadable files are skipped silently; the frame is left unchanged.
    Snippet attachment is bounded to the first ``MAX_SNIPPET_FRAMES`` frames
    so source reads cannot exhaust the analyzer; all frames are preserved.
    """
    if not repo_dir:
        return frames
    base = Path(repo_dir).resolve()
    cache: dict[str, list[str]] = {}
    for index, f in enumerate(frames):
        if index >= MAX_SNIPPET_FRAMES:
            break
        if not f.file or f.line <= 0:
            continue
        try:
            candidate = Path(f.file)
            full = candidate.resolve(strict=True) if candidate.is_absolute() else (base / candidate).resolve(strict=True)
            full.relative_to(base)
        except (ValueError, OSError):
            continue
        if not full.is_file() or full.suffix.lower() not in SNIPPET_SUFFIXES:
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
