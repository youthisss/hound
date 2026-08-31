"""Deterministic deployment timeline builder (Milestone 7).

The timeline aggregates CI metadata, deployment context, and extracted failure
events into one stable, reproducible sequence. Ordering is never invented:

- ``timestamp_ns`` (high-precision clock) is the primary sort key when present;
- ``sequence`` is the fallback ordering when clocks are unreliable or too coarse;
- otherwise entries keep their original (log) order.

All ordering choices are recorded on each entry via ``ordering_basis`` and
``uncertainty`` so consumers can distinguish authoritative clocks from fallback
ordering. Parent links (``span_id`` -> ``parent_span_id``) are surfaced for
causal tracing but never used to force order; a mis-assigned parent that would
create a cycle is detected and reported via ``has_cycles``/``cycle_warning``
with a safe fallback to the flat deterministic list.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from hound.models import Artifacts, DeploymentContext, Timeline, TimelineEntry

_IMPACT_OUTAGE = re.compile(
    r"\b(?:outage|service disruption|major incident|customer[- ]?facing|"
    r"unavailable(?: to customers)?|error budget(?: exhausted)?|sla breach)\b",
    re.IGNORECASE,
)
_IMPACT_DEGRADED = re.compile(
    r"\b(?:degraded|partial(?:ly)?|error rate|latency|p95|p99|slow(?:ing|ed)?|"
    r"intermittent|impacted(?: customers)?)\b",
    re.IGNORECASE,
)
_RECOVERY_OK = {
    "rollback_succeeded",
    "recovered",
    "completed",
    "succeeded",
    "successful",
    "healthy",
}

_MAX_TIMELINE_ENTRIES = 40


@dataclass
class _RawEntry:
    """Internal staging entry before deterministic ordering is applied."""

    event_id: str
    message: str
    stage: str
    kind: str
    role: str
    source: str
    timestamp_ns: int | None = None
    timestamp: str = ""
    sequence: int | None = None
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str | None = None
    service: str = ""
    original_index: int = 0


def build_timeline(artifacts: Artifacts) -> Timeline:
    """Aggregate CI/deployment/failure evidence into a deterministic timeline."""
    raw: list[_RawEntry] = []
    index = 0

    run = artifacts.run
    deployment = artifacts.deployment

    if run.job_name or run.workflow or run.run_id:
        parts = []
        if run.workflow:
            parts.append(run.workflow)
        if run.job_name:
            parts.append(run.job_name)
        message = f"CI job: {' / '.join(parts)}" if parts else "CI run"
        raw.append(_RawEntry(
            event_id="ctx-ci",
            message=message,
            stage="ci",
            kind="unknown",
            role="context",
            source="ci",
            original_index=index,
        ))
        index += 1

    deployment_fields = _non_empty_deployment(deployment)
    if deployment_fields:
        raw.append(_RawEntry(
            event_id="ctx-deploy",
            message=_deployment_summary(deployment),
            stage="deploy",
            kind="unknown",
            role="context",
            source="deployment",
            timestamp_ns=_parse_iso_ns(deployment.started_at),
            timestamp=deployment.started_at,
            original_index=index,
        ))
        index += 1

    for event in artifacts.events[: _MAX_TIMELINE_ENTRIES - 2]:
        raw.append(_RawEntry(
            event_id=event.event_id or f"ev-{index + 1:03d}",
            message=event.message,
            stage=event.stage,
            kind=event.kind,
            role=event.role,
            source="failure_event",
            timestamp_ns=event.timestamp_ns,
            timestamp=event.timestamp,
            sequence=event.sequence,
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            service=event.service,
            original_index=index,
        ))
        index += 1

    if deployment.recovery:
        raw.append(_RawEntry(
            event_id="rec-001",
            message=f"Recovery: {deployment.recovery}",
            stage="deploy",
            kind="rollback" if "rollback" in deployment.recovery else "unknown",
            role="recovery",
            source="recovery",
            original_index=index,
        ))
        index += 1

    ordering_basis = _ordering_basis(raw)
    entries = [
        _to_entry(item, position=position, ordering_basis=_entry_basis(item))
        for position, item in enumerate(_sort_entries(raw))
    ]

    has_cycles, cycle_warning = _detect_cycles(entries)
    grouping = _classify_grouping(entries)

    primary = next((entry for entry in entries if entry.role == "primary"), None)
    downstream = [entry for entry in entries if entry.role == "downstream"]
    recovery = [entry for entry in entries if entry.role == "recovery"]

    customer_impact = classify_customer_impact(artifacts)
    release_changed, release_changed_fields = compare_releases(deployment)

    return Timeline(
        entries=entries,
        grouping=grouping,
        ordering_basis=ordering_basis,
        has_cycles=has_cycles,
        cycle_warning=cycle_warning,
        primary_event_id=primary.event_id if primary else "",
        downstream_event_ids=[entry.event_id for entry in downstream],
        recovery_event_ids=[entry.event_id for entry in recovery],
        customer_impact=customer_impact,
        release_changed=release_changed,
        release_changed_fields=release_changed_fields,
    )


def timeline_to_dict(timeline: Timeline) -> dict:
    """Serialize a Timeline into the RCA document's ``timeline`` section."""
    return asdict(timeline)


# --------------------------------------------------------------------------- ordering


def _sort_key(item: _RawEntry) -> tuple[int, int, int, int]:
    """Deterministic sort key.

    Group 0: entries with an authoritative high-precision clock, ordered by it.
    Group 1: entries with a sequence fallback, ordered by it.
    Group 2: entries with neither, kept in original (log) order.
    Inter-group order (clocked before sequenced before unclocked) is an explicit,
    documented policy; we never reorder entries within a group.
    """
    if item.timestamp_ns is not None:
        return (0, item.timestamp_ns, item.sequence or 0, item.original_index)
    if item.sequence is not None:
        return (1, 0, item.sequence, item.original_index)
    return (2, 0, 0, item.original_index)


def _sort_entries(items: list[_RawEntry]) -> list[_RawEntry]:
    return sorted(items, key=_sort_key)


def _entry_basis(item: _RawEntry) -> str:
    if item.timestamp_ns is not None:
        return "timestamp_ns"
    if item.sequence is not None:
        return "sequence"
    return "log_order"


def _ordering_basis(items: list[_RawEntry]) -> str:
    bases = {_entry_basis(item) for item in items if item.source == "failure_event"}
    if not bases:
        bases = {_entry_basis(item) for item in items}
    if len(bases) > 1:
        return "mixed"
    return next(iter(bases)) if bases else "log_order"


def _to_entry(item: _RawEntry, position: int, ordering_basis: str) -> TimelineEntry:
    uncertainty = ""
    if ordering_basis == "sequence" and item.timestamp_ns is None:
        uncertainty = "clock not available; ordered by sequence fallback"
    elif ordering_basis == "log_order":
        uncertainty = "no clock or sequence; ordered by source order"
    return TimelineEntry(
        event_id=item.event_id,
        position=position,
        timestamp_ns=item.timestamp_ns,
        timestamp=item.timestamp,
        sequence=item.sequence,
        stage=item.stage,
        kind=item.kind,
        role=item.role,
        message=item.message[:1000],
        trace_id=item.trace_id,
        span_id=item.span_id,
        parent_span_id=item.parent_span_id,
        service=item.service,
        source=item.source,
        ordering_basis=ordering_basis,
        uncertainty=uncertainty,
    )


# -------------------------------------------------------------------- cycle guard


def _detect_cycles(entries: list[TimelineEntry]) -> tuple[bool, str]:
    """Detect mis-assigned ``parent_span_id`` cycles without blocking analysis.

    Uses iterative DFS with three-color marking. A cycle is reported via
    ``has_cycles``/``cycle_warning``; the caller keeps the flat deterministic
    list, which is the documented safe fallback.
    """
    parent_of: dict[str, str] = {}
    for entry in entries:
        if entry.span_id and entry.parent_span_id:
            parent_of[entry.span_id] = entry.parent_span_id
    if not parent_of:
        return False, ""

    GRAY, BLACK = 1, 2
    color: dict[str, int] = {}
    for node in parent_of:
        stack = [(node, 0)]
        while stack:
            current, state = stack.pop()
            if state == 1:
                color[current] = BLACK
                continue
            if color.get(current) == BLACK:
                continue
            if color.get(current) == GRAY:
                return True, (
                    f"causal link cycle detected at span_id {current}; "
                    "treating events as a flat list (parent_span_id may be mis-assigned)"
                )
            color[current] = GRAY
            stack.append((current, 1))
            parent = parent_of.get(current)
            if parent:
                if color.get(parent) == GRAY:
                    return True, (
                        f"causal link cycle detected at span_id {current}; "
                        "treating events as a flat list (parent_span_id may be mis-assigned)"
                    )
                if color.get(parent) != BLACK:
                    stack.append((parent, 0))
    return False, ""


# ------------------------------------------------------------------ classification


def _classify_grouping(entries: list[TimelineEntry]) -> str:
    failure = [entry for entry in entries if entry.source == "failure_event"]
    if not failure:
        return "none"
    linked = [entry for entry in failure if entry.trace_id or entry.span_id]
    if linked and len(linked) < len(failure):
        return "mixed"  # partial trace: some services instrumented, some not
    if linked:
        return "runtime"
    return "pipeline"


def classify_customer_impact(artifacts: Artifacts) -> str:
    """Derive customer-impact status, fail-closed to ``unknown``.

    An operator-supplied ``deployment.customer_impact`` wins; otherwise markers
    in the log text are used deterministically. Confirmed recovery downgrades a
    response to ``none`` only when no impact markers are present.
    """
    explicit = (artifacts.deployment.customer_impact or "").strip().lower()
    if explicit in {"unknown", "none", "degraded", "outage"}:
        return explicit
    text = artifacts.log_text or ""
    if _IMPACT_OUTAGE.search(text):
        return "outage"
    if _IMPACT_DEGRADED.search(text):
        return "degraded"
    if (artifacts.deployment.recovery or "").lower() in _RECOVERY_OK:
        return "none"
    return "unknown"


def release_identity(deployment: DeploymentContext) -> dict[str, str]:
    """Return the current release identity for comparison (non-empty fields only)."""
    return {
        key: getattr(deployment, key)
        for key in ("revision", "commit", "image_digest", "migration_version", "artifact")
        if getattr(deployment, key)
    }


def compare_releases(deployment: DeploymentContext) -> tuple[bool | None, list[str]]:
    """Compare current vs previous release identity when explicitly supplied.

    Returns ``(None, [])`` when no previous identity is supplied (not
    comparable), ``(False, [])`` when identities match, or
    ``(True, [fields])`` when they differ.
    """
    current = release_identity(deployment)
    previous = {
        "revision": deployment.previous_revision,
        "commit": deployment.previous_commit,
        "image_digest": deployment.previous_image_digest,
    }
    if not any(previous.values()):
        return None, []
    changed: list[str] = []
    comparable = False
    for field, previous_value in previous.items():
        current_value = current.get(field, "")
        if previous_value and current_value:
            comparable = True
            if previous_value != current_value:
                changed.append(field)
    if not comparable:
        return None, changed
    return (bool(changed), changed)


# ---------------------------------------------------------------------- helpers


def _non_empty_deployment(deployment: DeploymentContext) -> dict[str, str]:
    return {
        key: value
        for key, value in vars(deployment).items()
        if isinstance(value, str) and value
    }


def _deployment_summary(deployment: DeploymentContext) -> str:
    parts = []
    if deployment.platform:
        parts.append(deployment.platform)
    if deployment.environment:
        parts.append(f"env={deployment.environment}")
    if deployment.service or deployment.target:
        parts.append(deployment.service or deployment.target)
    if deployment.release:
        parts.append(f"release={deployment.release}")
    if deployment.revision:
        parts.append(f"revision={deployment.revision}")
    if deployment.outcome:
        parts.append(f"outcome={deployment.outcome}")
    return "Deployment: " + " ".join(parts)


def _parse_iso_ns(value: str) -> int | None:
    if not value:
        return None
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None  # naive clock: cannot establish an authoritative order
    return int(parsed.timestamp() * 1_000_000_000)
