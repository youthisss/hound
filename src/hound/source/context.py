"""Bounded symbol context for repository-contained stack frames."""
from __future__ import annotations

import ast
from pathlib import Path

from hound.ingest.git import blame_line, correlated_commit_subjects
from hound.ingest.owners import resolve_owners
from hound.models import StackFrame
from hound.pathutil import path_matches

MAX_FILES = 20
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 256 * 1024
MAX_SYMBOL_LINES = 80
MAX_TEST_FILES = 100
MAX_TEST_SCAN_BYTES = 256 * 1024
ALLOWED_SUFFIXES = {".py", ".js", ".ts", ".go", ".rs", ".java", ".cs", ".yaml", ".yml", ".tf", ".tpl"}
TEST_SUFFIXES = {".py", ".js", ".ts", ".go", ".rs", ".java", ".cs"}
_BLOCKED_NAMES = {".env", ".npmrc", ".pypirc", "credentials", "id_rsa", "id_ed25519"}
_BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def collect_source_evidence(
    repo_dir: str | Path,
    frames: list[StackFrame],
    changed_files: list[str],
    *,
    send_to_llm: bool = False,
) -> list[dict]:
    """Resolve only recognized frame files under strict containment and byte limits."""
    repo = Path(repo_dir).resolve()
    evidence: list[dict] = []
    seen: set[str] = set()
    total_bytes = 0
    for frame in frames:
        normalized = frame.file.replace("\\", "/")
        if normalized in seen or len(evidence) >= MAX_FILES:
            continue
        seen.add(normalized)
        full = _safe_file(repo, normalized)
        if full is None:
            continue
        try:
            size = full.stat().st_size
            if size > MAX_FILE_BYTES or total_bytes + size > MAX_TOTAL_BYTES:
                continue
            raw = full.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        total_bytes += len(raw)
        symbol = _symbol_context(full.suffix.lower(), text, frame.line)
        related_tests = _related_tests(repo, normalized, symbol["name"])
        commits = correlated_commit_subjects(str(repo), [normalized], changed_files, limit=1)
        evidence.append({
            "file": normalized,
            "line": frame.line,
            "symbol": symbol,
            "changed": path_matches(normalized, set(changed_files)),
            "owners": resolve_owners(repo, [normalized]),
            "commit": commits[0] if commits else "",
            "blame": blame_line(repo, normalized, frame.line),
            "related_tests": related_tests,
            "language_mode": "python_ast" if full.suffix.lower() == ".py" else "bounded_text_fallback",
            "uncertainty": "static repository context; not proof of runtime causality",
            "send_to_llm": send_to_llm,
        })
    return evidence


def _safe_file(repo: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not relative:
        return None
    unresolved = repo / candidate
    if unresolved.is_symlink():
        return None
    try:
        full = unresolved.resolve(strict=True)
        full.relative_to(repo)
    except (OSError, ValueError):
        return None
    if not full.is_file() or full.suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    lower_parts = {part.lower() for part in full.relative_to(repo).parts}
    if any(part.startswith(".") for part in lower_parts):
        return None
    if full.name.lower() in _BLOCKED_NAMES or full.suffix.lower() in _BLOCKED_SUFFIXES:
        return None
    return full


def _symbol_context(suffix: str, text: str, line: int) -> dict:
    lines = text.splitlines()
    start = max(1, line - 2)
    end = min(len(lines), line + 2)
    name = ""
    if suffix == ".py":
        try:
            tree = ast.parse(text)
            candidates = [
                node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.lineno <= line <= (node.end_lineno or node.lineno)
            ]
            if candidates:
                node = min(candidates, key=lambda item: (item.end_lineno or item.lineno) - item.lineno)
                name = node.name
                start = node.lineno
                end = min(node.end_lineno or node.lineno, start + MAX_SYMBOL_LINES - 1)
        except (SyntaxError, ValueError):
            pass
    snippet = "\n".join(f"{index} | {lines[index - 1]}" for index in range(start, end + 1))
    return {"name": name, "start_line": start, "end_line": end, "snippet": snippet}


def _related_tests(repo: Path, source_path: str, symbol: str) -> list[str]:
    stem = Path(source_path).stem
    needles = {stem, symbol} - {""}
    if not needles:
        return []
    matches: list[str] = []
    scanned_bytes = 0
    candidates = sorted(
        path for path in repo.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEST_SUFFIXES
        and "test" in path.relative_to(repo).as_posix().lower()
        and not path.is_symlink()
    )
    for path in candidates[:MAX_TEST_FILES]:
        relative = path.relative_to(repo).as_posix()
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or scanned_bytes + size > MAX_TEST_SCAN_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned_bytes += size
        if any(needle in content for needle in needles):
            matches.append(relative)
            if len(matches) >= 10:
                break
    return matches
