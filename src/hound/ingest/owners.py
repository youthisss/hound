"""Small, dependency-free CODEOWNERS resolver for affected CI/CD paths."""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from hound.fsio import read_bounded_text
from hound.pathutil import path_has_symlink

MAX_CODEOWNERS_BYTES = 256 * 1024

def resolve_owners(repo_dir: str | Path, paths: list[str]) -> list[str]:
    if path_has_symlink(repo_dir):
        return []
    repo = Path(repo_dir).resolve()
    source = next((path for path in (repo / "CODEOWNERS", repo / ".github" / "CODEOWNERS", repo / "docs" / "CODEOWNERS") if _safe_codeowners(path, repo)), None)
    if source is None:
        return []
    rules: list[tuple[str, list[str]]] = []
    try:
        content = read_bounded_text(source, MAX_CODEOWNERS_BYTES, errors="replace")
        for line in content.splitlines():
            values = line.split("#", 1)[0].split()
            if len(values) >= 2:
                rules.append((values[0].lstrip("/"), values[1:]))
    except (OSError, ValueError):
        return []
    owners: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").lstrip("/")
        for pattern, rule_owners in rules:
            if fnmatch(normalized, pattern) or (pattern.endswith("/") and normalized.startswith(pattern)):
                owners = rule_owners  # CODEOWNERS uses the last matching rule.
    return owners


def _safe_codeowners(path: Path, repo: Path) -> bool:
    try:
        return not path_has_symlink(path) and path.is_file() and path.resolve(strict=True).is_relative_to(repo)
    except OSError:
        return False
