"""M9 release, observability, trace, SLO, and runbook correlation."""
from __future__ import annotations

from hound.devops.timeline import classify_customer_impact
from hound.models import Artifacts, SEVERITIES

_RELEASE_FIELDS = (
    ("revision", "revision", "previous_revision"),
    ("commit", "commit", "previous_commit"),
    ("image_digest", "image_digest", "previous_image_digest"),
    ("manifest_digest", "manifest_digest", "previous_manifest_digest"),
    ("resource_fingerprint", "resource_fingerprint", "previous_resource_fingerprint"),
    ("migration_version", "migration_version", "previous_migration_version"),
    ("runtime_version", "runtime_version", "previous_runtime_version"),
    ("dependency_fingerprint", "dependency_fingerprint", "previous_dependency_fingerprint"),
    ("feature_flag_version", "feature_flag_version", "previous_feature_flag_version"),
)
_SEVERITY_RANK = {severity: index for index, severity in enumerate(("low", "medium", "high", "critical"))}


def build_investigation(artifacts: Artifacts, static_severity: str, runbook_url: str = "") -> dict:
    deployment = artifacts.deployment
    release_changes = []
    for label, current_field, previous_field in _RELEASE_FIELDS:
        current = getattr(deployment, current_field)
        previous = getattr(deployment, previous_field)
        if not previous:
            continue
        release_changes.append({
            "field": label,
            "current": current,
            "previous": previous,
            "status": "unknown" if not current else "changed" if current != previous else "unchanged",
        })

    boundaries = sorted({span.get("service", "") for span in artifacts.trace_spans if span.get("service")})
    versions = {
        span["service"]: span["version"]
        for span in artifacts.trace_spans
        if span.get("service") and span.get("version")
    }
    impact = classify_customer_impact(artifacts)
    budget = _number(deployment.error_budget_remaining)
    effective_severity, reasons = _effective_severity(static_severity, impact, budget)
    return {
        "release_changes": release_changes,
        "metric_samples": artifacts.metric_samples,
        "trace_spans": artifacts.trace_spans,
        "service_boundaries": boundaries,
        "service_versions": versions,
        "critical_path": _critical_path(artifacts.trace_spans),
        "slo": {
            "target": deployment.slo_target,
            "error_budget_remaining": budget,
            "customer_impact": impact,
            "uncertainty": "SLO evidence is operator-supplied; metric correlation does not prove causality",
        },
        "static_severity": static_severity,
        "effective_severity": effective_severity,
        "severity_reasons": reasons,
        "runbook": {
            "service": deployment.service or deployment.target,
            "url": deployment.runbook_url or runbook_url,
            "source": "explicit_trusted_configuration" if deployment.runbook_url or runbook_url else "missing",
        },
    }


def _effective_severity(static: str, impact: str, budget: float | None) -> tuple[str, list[str]]:
    desired = static if static in SEVERITIES else "medium"
    reasons = [f"static severity: {desired}"]
    if impact == "outage" or (budget is not None and budget <= 0):
        desired = _max_severity(desired, "critical")
        reasons.append("observed outage or exhausted error budget")
    elif impact == "degraded" or (budget is not None and budget < 10):
        desired = _max_severity(desired, "high")
        reasons.append("degraded impact or error budget below 10 percent")
    return desired, reasons


def _max_severity(left: str, right: str) -> str:
    return left if _SEVERITY_RANK[left] >= _SEVERITY_RANK[right] else right


def _number(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return None


def _critical_path(spans: list[dict]) -> dict:
    by_id = {str(span.get("span_id")): span for span in spans if span.get("span_id")}
    best: list[dict] = []
    best_duration = 0
    cycle_detected = False
    for span in by_id.values():
        chain: list[dict] = []
        visited: set[str] = set()
        current: dict | None = span
        while current is not None:
            span_id = str(current.get("span_id") or "")
            if span_id in visited:
                cycle_detected = True
                break
            visited.add(span_id)
            chain.append(current)
            current = by_id.get(str(current.get("parent_span_id") or ""))
        chain.reverse()
        starts = [int(item.get("start_ns") or 0) for item in chain if int(item.get("start_ns") or 0) > 0]
        ends = [int(item.get("end_ns") or 0) for item in chain if int(item.get("end_ns") or 0) > 0]
        if starts and ends and max(ends) >= min(starts):
            duration = max(ends) - min(starts)
        else:
            # Parent spans normally include child time, so summing nested spans
            # overstates elapsed latency when timestamps are unavailable.
            duration = max((int(item.get("duration_ns") or 0) for item in chain), default=0)
        if duration > best_duration:
            best, best_duration = chain, duration
    return {
        "span_ids": [str(span.get("span_id") or "") for span in best],
        "services": [str(span.get("service") or "") for span in best if span.get("service")],
        "duration_ns": best_duration,
        "cycle_detected": cycle_detected,
        "uncertainty": "elapsed estimate from available parent links; partial traces may omit the true critical path",
    }
