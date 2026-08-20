"""Gather git context without honoring repository-configured executable helpers."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import re

from hound_agent.models import GitInfo

_GIT_TIMEOUT = 10
_REVISION = re.compile(r"[0-9a-fA-F]{7,64}")


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
