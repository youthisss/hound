"""Severity classification and priority assignment."""
from __future__ import annotations

import re

from tracehound.models import Artifacts
from tracehound.pathutil import path_matches

_CRASH_RE = re.compile(r"segmentation fault|segfault|SIGSEGV|SIGABRT|panic:", re.IGNORECASE)

_PRIORITY = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def _frame_hits_changed_file(artifacts: Artifacts) -> bool:
    changed = set(artifacts.git.changed_files)
    return any(path_matches(f.file, changed) for f in artifacts.frames)


def classify(artifacts: Artifacts) -> tuple[str, int]:
    kind = artifacts.kind
    if kind in {"import_error", "compilation_error", "image_pull_error", "registry_auth_failure", "migration_failed", "config_missing"}:
        severity = "critical"
    elif kind in {"ci_failure", "deployment_failed", "rollback", "permission_error", "health_check_failed", "readiness_timeout", "oom_killed", "crash_loop", "liveness_probe_failed", "readiness_probe_failed", "scheduling_failed", "quota_exceeded", "network_failure"}:
        severity = "high"
    elif kind == "timeout":
        severity = "medium"
    elif kind == "flaky":
        severity = "low"
    elif _CRASH_RE.search(artifacts.message):
        severity = "high"
    elif kind == "test_failure":
        severity = "high" if _frame_hits_changed_file(artifacts) else "medium"
    else:
        severity = "low"
    return severity, _PRIORITY[severity]
