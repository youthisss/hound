"""Severity classification and priority assignment."""
from __future__ import annotations

import re

from hound.models import Artifacts
from hound.pathutil import path_matches

_CRASH_RE = re.compile(r"segmentation fault|segfault|SIGSEGV|SIGABRT|panic:", re.IGNORECASE)

_PRIORITY = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def _frame_hits_changed_file(artifacts: Artifacts) -> bool:
    changed = set(artifacts.git.changed_files)
    return any(path_matches(f.file, changed) for f in artifacts.frames)


def classify(artifacts: Artifacts) -> tuple[str, int]:
    kind = artifacts.kind
    if kind in {"import_error", "compilation_error", "image_pull_error", "registry_auth_failure", "migration_failed", "config_missing", "dependency_resolution"}:
        severity = "high"
    elif kind in {"ci_failure", "deployment_failed", "rollback", "permission_error", "health_check_failed", "readiness_timeout", "oom_killed", "crash_loop", "liveness_probe_failed", "readiness_probe_failed", "scheduling_failed", "quota_exceeded", "network_failure", "disk_full", "tls_certificate_error"}:
        severity = "high"
    elif kind in {"timeout", "api_rate_limited"}:
        severity = "medium"
    elif kind == "flaky":
        severity = "low"
    elif _CRASH_RE.search(artifacts.message):
        severity = "high"
    elif kind == "test_failure":
        severity = "high" if _frame_hits_changed_file(artifacts) else "medium"
    else:
        severity = "low"
    severity, _ = apply_customer_impact(artifacts, severity)
    return severity, _PRIORITY[severity]


def apply_customer_impact(artifacts: Artifacts, severity: str) -> tuple[str, list[str]]:
    """Escalate only with production environment and customer-impact context."""
    deployment = artifacts.deployment
    environment = (deployment.environment or "").strip().lower()
    impact = (deployment.customer_impact or "").strip().lower()
    # Missing environment is not evidence of a production incident.
    if environment not in {"production", "prod", "live"}:
        return severity, []
    target = {"outage": "critical", "degraded": "high"}.get(impact)
    if target:
        reasons = [
            f"production customer impact: {impact}; impact context may be operator-supplied "
            "or inferred from untrusted log text (provenance is not recorded)",
        ]
        return target if _PRIORITY[target] < _PRIORITY[severity] else severity, reasons
    return severity, []
