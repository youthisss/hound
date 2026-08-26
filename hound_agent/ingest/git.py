"""Gather git context without honoring repository-configured executable helpers."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import re

from hound_agent.models import GitInfo
from hound_agent.pathutil import path_matches

_GIT_TIMEOUT = 10
_REVISION = re.compile(r"[0-9a-fA-F]{7,64}")
_MAX_CORRELATED_COMMITS = 3
_MAX_COMMIT_SUBJECT_CHARS = 240


def _warn(context: str, exc: Exception) -> None:
    sys.stderr.write(f"Warning: git {context} unavailable: {exc}\n")


def _run(repo: Path, *args: str) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
        and key not in {"SSH_ASKPASS"}
    }
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    command = [
        "git", "-C", str(repo),
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={os.devnull}",
        *args,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=_GIT_TIMEOUT,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout.strip()


def gather(repo_dir: str | None, base_sha: str = "", head_sha: str = "") -> GitInfo:
    if not repo_dir:
        return GitInfo()
    repo = Path(repo_dir).resolve()
    if not repo.is_dir():
        return GitInfo()
    try:
        if _run(repo, "rev-parse", "--is-inside-work-tree") != "true":
            return GitInfo()
    except (OSError, subprocess.SubprocessError) as exc:
        _warn("repository", exc)
        return GitInfo()

    info = GitInfo()
    base_sha = base_sha if _REVISION.fullmatch(base_sha) else ""
    head_sha = head_sha if _REVISION.fullmatch(head_sha) else ""
    try:
        info.branch = _run(repo, "symbolic-ref", "--quiet", "--short", "HEAD") or None
    except (OSError, subprocess.SubprocessError):
        info.branch = None
    try:
        info.head = _run(repo, "rev-parse", "--verify", f"{head_sha or 'HEAD'}^{{commit}}")
    except (OSError, subprocess.SubprocessError) as exc:
        _warn("head commit", exc)
    try:
        diff_target = f"{base_sha}...{head_sha or 'HEAD'}" if base_sha else "HEAD"
        changed = _run(repo, "diff", "--no-ext-diff", "--name-only", diff_target).splitlines()
        untracked = _run(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        info.changed_files = sorted(set(filter(None, changed + untracked)))
    except (OSError, subprocess.SubprocessError) as exc:
        _warn("changed files", exc)
    return info


def correlated_commit_subjects(
    repo_dir: str | None,
    frame_files: list[str],
    changed_files: list[str],
    limit: int = _MAX_CORRELATED_COMMITS,
) -> list[str]:
    """Return recent commit subjects for changed files referenced by frames.

    This is bounded, read-only context for offline RCA: only changed files
    matching a parsed, repository-contained stack frame are queried. A failed
    optional lookup (for example an untracked file) is silently omitted rather
    than making analysis fail.
    """
    if not repo_dir or not frame_files or not changed_files or limit <= 0:
        return []
    repo = Path(repo_dir).resolve()
    if not repo.is_dir():
        return []
    matched = [
        path for path in sorted(set(changed_files))
        if _safe_repo_path(path) and any(path_matches(frame, {path}) for frame in frame_files)
    ]
    subjects: list[str] = []
    for path in matched:
        if len(subjects) >= limit:
            break
        try:
            output = _run(repo, "log", "-1", "--format=%h%x09%s", "--", path)
        except (OSError, subprocess.SubprocessError):
            continue
        short_sha, separator, subject = output.partition("\t")
        subject = " ".join(subject.split())[:_MAX_COMMIT_SUBJECT_CHARS]
        if not separator or not short_sha or not subject:
            continue
        subjects.append(f"{path} ({short_sha} {subject})")
    return subjects


def _safe_repo_path(path: str) -> bool:
    """Allow only non-empty, repo-relative paths before a `git log -- path` call."""
    normalized = path.replace("\\", "/")
    return (
        bool(normalized)
        and not normalized.startswith("/")
        and re.match(r"^[A-Za-z]:/", normalized) is None
        and ".." not in normalized.split("/")
        and "\x00" not in normalized
    )
