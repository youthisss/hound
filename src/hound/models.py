"""Core data models and versioned RCA document schemas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import math
import re

from hound.pathutil import path_matches
from hound.safety import validate_recommendation, validate_recommendations

SCHEMA_VERSION = "2.0"
LEGACY_SCHEMA_VERSION = "1.4"
SUPPORTED_SCHEMA_VERSIONS = {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}
MAX_REQUEST_USERS = 10

STAGES = {"ci", "build", "test", "deploy", "unknown"}
KINDS = {
    "compilation_error",
    "test_failure",
    "import_error",
    "timeout",
    "flaky",
    "deployment_failed",
    "rollback",
    "health_check_failed",
    "image_pull_error",
    "migration_failed",
    "permission_error",
    "readiness_timeout",
    "oom_killed",
    "crash_loop",
    "liveness_probe_failed",
    "readiness_probe_failed",
    "scheduling_failed",
    "quota_exceeded",
    "network_failure",
    "registry_auth_failure",
    "config_missing",
    "ci_failure",
    "dependency_resolution",
    "disk_full",
    "tls_certificate_error",
    "api_rate_limited",
    "unknown",
}
CONFIDENCES = {"high", "medium", "low"}
SEVERITIES = {"critical", "high", "medium", "low"}
ENGINES = {"llm", "fallback", "merged"}
_EVIDENCE_ID_RE = re.compile(r"^ev-[0-9]{3,6}$")
_FACT_ID_RE = re.compile(r"^fact-[0-9]{3,6}$")
_HYPOTHESIS_ID_RE = re.compile(r"^hyp-[0-9]{3,6}$")
_MAX_ANALYSIS_LIST_ITEMS = 256
_MAX_ANALYSIS_STRING_CHARS = 256 * 1024


@dataclass
class StackFrame:
    file: str = ""
    line: int = 0
    function: str | None = None
    code: str = ""


@dataclass
class FailedTest:
    name: str = ""
    file: str = ""
    line: int | None = None
    assertion: str = ""


@dataclass
class GitInfo:
    branch: str | None = None
    head: str = ""
    changed_files: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    correlated_commits: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    provider: str = ""
    run_id: str = ""
    run_url: str = ""
    job_id: str = ""
    job_name: str = ""
    workflow: str = ""
    branch: str = ""
    commit_sha: str = ""
    step_name: str = ""
    attempt: int | None = None
    conclusion: str = ""
    duration_ms: int | None = None
    pr_number: str = ""
    base_sha: str = ""
    head_sha: str = ""


@dataclass
class DeploymentContext:
    platform: str = ""
    environment: str = ""
    cluster: str = ""
    target: str = ""
    namespace: str = ""
    release: str = ""
    revision: str = ""
    previous_revision: str = ""
    artifact: str = ""
    strategy: str = ""
    started_at: str = ""
    migration_version: str = ""
    outcome: str = ""
    recovery: str = ""
    # M7: explicit deployment context for the DevOps investigation contract.
    # Legacy sidecars that omit these fields remain readable; every field below
    # is optional and additive relative to schema v2.0.
    service: str = ""
    workload: str = ""
    commit: str = ""
    image_digest: str = ""
    finished_at: str = ""
    previous_commit: str = ""
    previous_image_digest: str = ""
    customer_impact: str = ""
    manifest_digest: str = ""
    previous_manifest_digest: str = ""
    resource_fingerprint: str = ""
    previous_resource_fingerprint: str = ""
    previous_migration_version: str = ""
    runtime_version: str = ""
    previous_runtime_version: str = ""
    dependency_fingerprint: str = ""
    previous_dependency_fingerprint: str = ""
    feature_flag_version: str = ""
    previous_feature_flag_version: str = ""
    slo_target: str = ""
    error_budget_remaining: str = ""
    runbook_url: str = ""


@dataclass
class RequestContext:
    request_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    user_id: str = ""
    users: list[str] = field(default_factory=list)
    method: str = ""
    path: str = ""


@dataclass
class FailureEvent:
    stage: str = "unknown"
    kind: str = "unknown"
    message: str = ""
    role: str = "primary"
    # M7 causal-link wire format. ``trace_id`` scopes one execution/request/pipeline
    # run; ``span_id`` identifies the event's own span; ``parent_span_id`` (nullable)
    # links to the causal parent and supports partial traces. ``timestamp_ns`` is an
    # optional high-precision clock; ``sequence`` is the fallback ordering when clocks
    # are unreliable or too coarse for concurrency. ``event_id`` is a stable run-scoped
    # identifier used by the timeline builder.
    event_id: str = ""
    service: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str | None = None
    timestamp: str = ""
    timestamp_ns: int | None = None
    sequence: int | None = None


@dataclass
class Artifacts:
    log_text: str = ""
    stage: str = "unknown"
    kind: str = "unknown"
    summary: str = ""
    message: str = ""
    frames: list[StackFrame] = field(default_factory=list)
    failed_tests: list[FailedTest] = field(default_factory=list)
    git: GitInfo = field(default_factory=GitInfo)
    run: RunContext = field(default_factory=RunContext)
    deployment: DeploymentContext = field(default_factory=DeploymentContext)
    events: list[FailureEvent] = field(default_factory=list)
    enrichment: list[str] = field(default_factory=list)
    connector_audits: list[dict] = field(default_factory=list)
    metric_samples: list[dict] = field(default_factory=list)
    trace_spans: list[dict] = field(default_factory=list)
    source_evidence: list[dict] = field(default_factory=list)
    log_path: str = ""
    redacted: bool = False
    request: RequestContext = field(default_factory=RequestContext)


@dataclass
class RootCause:
    hypothesis: str = ""
    confidence: str = "low"
    evidence: list[str] = field(default_factory=list)
    fix_suggestion: str = ""
    engine: str = "fallback"
    model: str | None = None
    usage: dict = field(default_factory=dict)
    llm_status: str = "not_requested"
    fallback_reason: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    contradicting_evidence_refs: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    recommended_checks: list[str] = field(default_factory=list)
    original_run: dict = field(default_factory=dict)


@dataclass
class Triage:
    severity: str = "medium"
    component: str = "unowned"
    priority: int = 3
    dedup_key: str = ""
    is_duplicate_of: str | None = None
    flaky_suspect: bool = False
    recurring_incident: bool = False
    occurrence_count: int = 1


@dataclass
class Ticket:
    title: str = ""
    body_md: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class TimelineEntry:
    """One event in the deterministic deployment timeline.

    Ordering is deterministic and never invented: ``timestamp_ns`` is used when
    available, else ``sequence``, else the original (log) order. ``ordering_basis``
    and ``uncertainty`` record *why* the entry is where it is so consumers can
    distinguish high-confidence clocks from fallback ordering.
    """

    event_id: str = ""
    position: int = 0
    timestamp_ns: int | None = None
    timestamp: str = ""
    sequence: int | None = None
    stage: str = "unknown"
    kind: str = "unknown"
    role: str = "downstream"
    message: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str | None = None
    service: str = ""
    source: str = ""  # "failure_event" | "deployment" | "ci" | "recovery"
    ordering_basis: str = "log_order"  # timestamp_ns | sequence | log_order
    uncertainty: str = ""


@dataclass
class Timeline:
    """Aggregated, deterministically ordered event timeline.

    ``grouping`` reports the causal-linking scheme observed: ``runtime``
    (request-level ``trace_id``), ``pipeline`` (CI job/step structure),
    ``mixed`` (partial instrumentation), or ``none``. ``has_cycles`` surfaces
    mis-assigned ``parent_span_id`` values without failing the build — the
    fallback is a flat, deterministic list. ``distinction`` separates the
    primary failure, downstream symptoms, recovery, and unknown-impact status
    per the M7 exit criteria.
    """

    entries: list[TimelineEntry] = field(default_factory=list)
    grouping: str = "none"  # runtime | pipeline | mixed | none
    ordering_basis: str = "log_order"  # timestamp_ns | sequence | log_order | mixed
    has_cycles: bool = False
    cycle_warning: str = ""
    primary_event_id: str = ""
    downstream_event_ids: list[str] = field(default_factory=list)
    recovery_event_ids: list[str] = field(default_factory=list)
    customer_impact: str = "unknown"  # unknown | none | degraded | outage
    release_changed: bool | None = None
    release_changed_fields: list[str] = field(default_factory=list)


def build_evidence_items(artifacts: Artifacts, observed_at: str = "") -> list[dict]:
    """Return bounded deterministic evidence with stable run-scoped IDs."""
    items: list[dict] = []

    def add(
        kind: str,
        value,
        source_type: str,
        locator: str,
        collector: str,
        evidence_observed_at: str | None = None,
    ) -> None:
        if value in (None, "", [], {}):
            return
        items.append({
            "id": f"ev-{len(items) + 1:03d}",
            "kind": kind,
            "value": value,
            "provenance": {
                "source_type": source_type,
                "artifact": artifacts.log_path,
                "locator": locator,
                "collector": collector,
                "observed_at": (evidence_observed_at if evidence_observed_at is not None else observed_at) or None,
            },
        })

    add("failure_message", artifacts.message, "artifact", "failure.message", "ingest.logs")
    for index, event in enumerate(artifacts.events[:20]):
        add("failure_event", asdict(event), "artifact", f"failure.events[{index}]", "ingest.logs")
    for index, frame in enumerate(artifacts.frames[:15]):
        add("stack_frame", asdict(frame), "artifact", f"failure.stacktrace[{index}]", "ingest.stacktrace")
    for index, failed_test in enumerate(artifacts.failed_tests[:20]):
        add("failed_test", asdict(failed_test), "artifact", f"failure.failed_tests[{index}]", "ingest.tests")
    add("changed_files", list(artifacts.git.changed_files[:20]), "repository", "git.changed_files", "ingest.git")
    add("owners", list(artifacts.git.owners[:20]), "repository", "context.owners", "ingest.owners")
    add("correlated_commits", list(artifacts.git.correlated_commits[:10]), "repository", "git.correlated_commits", "ingest.git")
    for index, value in enumerate(artifacts.enrichment[:20]):
        add("connector_observation", value, "connector", f"enrichment[{index}]", "ingest.enrich")
    for index, audit in enumerate(artifacts.connector_audits[:20]):
        add(
            "connector_audit",
            audit,
            "connector",
            f"context.connector_audits[{index}]",
            "connectors.deployment",
            str(audit.get("observed_at") or ""),
        )
    for index, sample in enumerate(artifacts.metric_samples[:20]):
        add("metric_sample", sample, "connector", f"devops.metric_samples[{index}]", "connectors.observability")
    for index, span in enumerate(artifacts.trace_spans[:20]):
        add("trace_span", span, "connector", f"devops.trace_spans[{index}]", "connectors.observability")
    for index, source in enumerate(artifacts.source_evidence[:20]):
        add("source_context", source, "repository", f"context.source_evidence[{index}]", "source.context")
    if any(vars(artifacts.run).values()):
        add("run_context", asdict(artifacts.run), "context", "context.run", "ingest.context")
    if any(vars(artifacts.deployment).values()):
        add("deployment_context", asdict(artifacts.deployment), "context", "context.deployment", "ingest.context")
    return items


def visible_evidence_items(artifacts: Artifacts, observed_at: str = "") -> list[dict]:
    """Return evidence explicitly permitted in an LLM request.

    Repository source context remains available to local reports, but each
    item must opt in before it can cross the provider boundary. This predicate
    is shared by prompt construction and response validation.
    """
    return [
        item
        for item in build_evidence_items(artifacts, observed_at)
        if item.get("kind") != "source_context"
        or (isinstance(item.get("value"), dict) and item["value"].get("send_to_llm") is True)
    ]


def _observed_facts(artifacts: Artifacts, evidence: list[dict]) -> list[dict]:
    by_kind: dict[str, list[str]] = {}
    for item in evidence:
        by_kind.setdefault(item["kind"], []).append(item["id"])
    facts = [{
        "id": "fact-001",
        "kind": "failure_classification",
        "value": {"stage": artifacts.stage, "kind": artifacts.kind},
        "evidence_refs": by_kind.get("failure_event", by_kind.get("failure_message", []))[:1],
    }]
    for failed_test, evidence_ref in zip(artifacts.failed_tests[:20], by_kind.get("failed_test", [])):
        facts.append({
            "id": f"fact-{len(facts) + 1:03d}",
            "kind": "failed_test",
            "value": asdict(failed_test),
            "evidence_refs": [evidence_ref],
        })
    for frame, evidence_ref in zip(artifacts.frames[:15], by_kind.get("stack_frame", [])):
        facts.append({
            "id": f"fact-{len(facts) + 1:03d}",
            "kind": "stack_frame",
            "value": asdict(frame),
            "evidence_refs": [evidence_ref],
        })
    return facts


def supporting_evidence_ids(artifacts: Artifacts) -> set[str]:
    """Evidence of failure, excluding administrative metadata and change lists."""
    kinds = {"failure_message", "failure_event", "stack_frame", "failed_test",
             "connector_observation", "metric_sample", "trace_span"}
    refs: set[str] = set()
    for item in build_evidence_items(artifacts):
        kind, value = item["kind"], item["value"]
        if kind not in kinds:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if kind == "stack_frame" and not value.get("file", "").strip():
            continue
        if kind == "failed_test" and not any(value.get(key) for key in ("name", "assertion")):
            continue
        if kind == "failure_event" and not value.get("message", "").strip():
            continue
        refs.add(item["id"])
    return refs


def score_evidence_completeness(artifacts: Artifacts) -> tuple[float, list[str]]:
    """Measure collected observations, not the probability a hypothesis is true."""
    score = 0.1
    reasons: list[str] = []
    if artifacts.kind != "unknown":
        score += 0.2
        reasons.append("recognized failure kind")
    if any(event.role == "primary" for event in artifacts.events):
        score += 0.15
        reasons.append("primary failure event observed")
    if artifacts.message:
        score += 0.1
        reasons.append("concrete failure message observed")
    if artifacts.frames or artifacts.failed_tests:
        score += 0.2
        reasons.append("stack frame or failed test observed")
    changed = set(artifacts.git.changed_files)
    if changed and any(path_matches(frame.file, changed) for frame in artifacts.frames):
        score += 0.15
        reasons.append("stack frame intersects the explicit repository diff")
    if artifacts.enrichment:
        score += 0.1
        reasons.append("bounded connector evidence observed")
    return round(min(score, 0.95), 2), reasons or ["no deterministic failure evidence"]


def score_confidence(artifacts: Artifacts) -> tuple[float, list[str]]:
    """Compatibility alias for the historical evidence-completeness score."""
    return score_evidence_completeness(artifacts)


def _analysis_section(artifacts: Artifacts, root_cause: RootCause, generated_at: str) -> dict:
    evidence = build_evidence_items(artifacts, generated_at)
    available = {item["id"] for item in evidence}
    supporting = [ref for ref in root_cause.evidence_refs if ref in available]
    contradicting = [ref for ref in root_cause.contradicting_evidence_refs if ref in available]
    if artifacts.kind == "unknown" and root_cause.engine == "fallback":
        support_status = "insufficient_evidence"
    elif contradicting:
        # A contradiction invalidates a positive support claim. The v2 schema
        # intentionally keeps the older status vocabulary; ``unsupported``
        # plus explicit contradicting refs is the backwards-compatible wire
        # representation of a conflicted hypothesis.
        support_status = "unsupported"
    elif set(supporting) & supporting_evidence_ids(artifacts):
        support_status = "supported"
    elif artifacts.kind == "unknown" or not evidence:
        support_status = "insufficient_evidence"
    else:
        support_status = "unsupported"
    missing = list(dict.fromkeys(root_cause.missing_information))
    if support_status != "supported" and not missing:
        missing = ["No collected evidence reference directly supports this hypothesis."]
    checks = list(dict.fromkeys(root_cause.recommended_checks))
    if not checks and root_cause.fix_suggestion:
        checks = [root_cause.fix_suggestion]
    score, reasons = score_evidence_completeness(artifacts)
    reasons = [
        "score measures evidence completeness, not hypothesis probability; band reports hypothesis confidence",
        *reasons,
    ]
    hypothesis = {
        "id": "hyp-001",
        "statement": root_cause.hypothesis,
        "source": "llm" if root_cause.engine in {"llm", "merged"} else "deterministic",
        "support_status": support_status,
        "supporting_evidence_refs": supporting,
        "contradicting_evidence_refs": contradicting,
        "confidence": {
            "band": root_cause.confidence,
            "score": score,
            "reasons": reasons,
        },
        "missing_information": missing,
        "recommended_checks": checks,
    }
    return {
        "observed_facts": _observed_facts(artifacts, evidence),
        "evidence": evidence,
        "hypotheses": [hypothesis],
        "missing_information": missing,
        "recommended_checks": checks,
    }


def build_doc(
    artifacts: Artifacts,
    root_cause: RootCause,
    triage: Triage,
    ticket: Ticket,
    generated_at: str,
    *,
    reused: bool = False,
    reused_from_key: str | None = None,
    trust_context: dict | None = None,
    timeline: dict | None = None,
    devops: dict | None = None,
    test_impact: dict | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "engine": root_cause.engine,
            "model": root_cause.model,
            "log_file": artifacts.log_path,
            "generated_at": generated_at,
            "redacted": artifacts.redacted,
            "usage": root_cause.usage,
            "reused": bool(reused),
            "reused_from_key": reused_from_key,
            "llm": {
                "status": root_cause.llm_status,
                "fallback_reason": root_cause.fallback_reason,
            },
            "trust": trust_context or {
                "source_class": "local_artifact",
                "source_context": True,
                "enrichment": True,
                "llm": True,
                "delivery": True,
            },
        },
        "failure": {
            "stage": artifacts.stage,
            "kind": artifacts.kind,
            "summary": artifacts.summary,
            "message": artifacts.message,
            "stacktrace": [
                asdict(f) for f in artifacts.frames
            ],
            "failed_tests": [asdict(t) for t in artifacts.failed_tests],
            "events": [asdict(event) for event in artifacts.events],
        },
        "context": {
            "run": asdict(artifacts.run),
            "deployment": asdict(artifacts.deployment),
            "request": asdict(artifacts.request),
            "owners": artifacts.git.owners,
            "connector_audits": artifacts.connector_audits,
            "source_evidence": artifacts.source_evidence,
        },
        "root_cause": {
            "hypothesis": root_cause.hypothesis,
            "confidence": root_cause.confidence,
            "evidence": root_cause.evidence,
            "fix_suggestion": root_cause.fix_suggestion,
        },
        "analysis": _analysis_section(artifacts, root_cause, generated_at),
        "triage": asdict(triage),
        "ticket": asdict(ticket),
        **({"timeline": timeline} if timeline is not None else {}),
        **({"devops": devops} if devops is not None else {}),
        **({"test_impact": test_impact} if test_impact is not None else {}),
    }


def _check(value: bool, msg: str) -> None:
    if not value:
        raise ValueError(f"invalid RCA doc: {msg}")


def _validate_analysis_value(value: object, location: str, depth: int = 0) -> None:
    """Reject non-JSON, non-finite, or oversized structured evidence.

    Renderers own terminal-control sanitization. Keeping those bytes valid in
    the in-memory document preserves the formatter's safe-output contract while
    JSON serialization still escapes them.
    """
    _check(depth <= 12, f"{location} is nested too deeply")
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        _check(math.isfinite(value), f"{location} must contain a finite number")
        return
    if isinstance(value, str):
        _check(len(value) <= _MAX_ANALYSIS_STRING_CHARS, f"{location} string is too long")
        return
    if isinstance(value, list):
        _check(len(value) <= _MAX_ANALYSIS_LIST_ITEMS, f"{location} contains too many items")
        for index, child in enumerate(value):
            _validate_analysis_value(child, f"{location}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        _check(len(value) <= _MAX_ANALYSIS_LIST_ITEMS, f"{location} contains too many fields")
        for key, child in value.items():
            _check(isinstance(key, str) and bool(key), f"{location} contains an invalid field name")
            _validate_analysis_value(child, f"{location}.{key}", depth + 1)
        return
    _check(False, f"{location} contains an unsupported value")


def validate(doc: dict) -> None:
    """Validate current v2.0 or persisted v1.4 documents. Raises ValueError."""
    _check(isinstance(doc, dict), "not a dict")
    # Report malformed present sections before reporting fields added by a newer
    # schema version; this keeps validation errors actionable for consumers.
    for section in ("meta", "failure", "context", "root_cause", "triage", "ticket"):
        if section in doc:
            _check(isinstance(doc[section], dict), f"{section} must be an object")
    for key in ("schema_version", "meta", "failure", "context", "root_cause", "triage", "ticket"):
        _check(key in doc, f"missing key {key!r}")
    _check(doc["schema_version"] in SUPPORTED_SCHEMA_VERSIONS,
           f"schema_version must be one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}")

    current_schema = doc["schema_version"] == SCHEMA_VERSION
    if current_schema:
        _check(
            set(doc) <= {
                "schema_version", "meta", "failure", "context", "root_cause",
                "analysis", "triage", "ticket", "timeline", "devops", "test_impact",
            },
            "document contains unsupported fields",
        )
    meta = doc["meta"]
    for key in ("engine", "model", "log_file", "generated_at", "redacted", "usage"):
        _check(key in meta, f"meta.{key} missing")
    if current_schema:
        for key in ("reused", "reused_from_key", "llm"):
            _check(key in meta, f"meta.{key} missing")
    _check(meta["engine"] in ENGINES, f"engine {meta['engine']!r} not in {ENGINES}")
    _check(meta["model"] is None or isinstance(meta["model"], str), "meta.model must be str or null")
    _check(isinstance(meta["log_file"], str), "meta.log_file must be str")
    _check(isinstance(meta["generated_at"], str), "meta.generated_at must be str")
    try:
        datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid RCA doc: meta.generated_at must be ISO 8601") from exc
    _check(isinstance(meta["redacted"], bool), "meta.redacted must be bool")
    _check(isinstance(meta["usage"], dict), "meta.usage must be dict")
    for key, value in meta["usage"].items():
        _check(key in {"prompt_tokens", "completion_tokens", "total_tokens"}, f"meta.usage.{key} invalid")
        _check(type(value) is int and value >= 0, f"meta.usage.{key} must be a non-negative int")
    if "reused" in meta:
        _check(isinstance(meta["reused"], bool), "meta.reused must be bool")
    if "reused_from_key" in meta:
        _check(meta["reused_from_key"] is None or isinstance(meta["reused_from_key"], str),
               "meta.reused_from_key must be str or null")
    if "llm" in meta:
        _check(isinstance(meta["llm"], dict), "meta.llm must be an object")
        _check(meta["llm"].get("status") in {"succeeded", "failed", "not_requested", "reused"},
               "meta.llm.status invalid")
        _check(meta["llm"].get("fallback_reason") is None or isinstance(meta["llm"].get("fallback_reason"), str),
               "meta.llm.fallback_reason must be str or null")
    if "trust" in meta:
        trust = meta["trust"]
        _check(isinstance(trust, dict), "meta.trust must be an object")
        assert isinstance(trust, dict)
        _check(set(trust) == {"source_class", "source_context", "enrichment", "llm", "delivery"},
               "meta.trust fields invalid")
        _check(trust["source_class"] in {"trusted_branch", "fork_pr", "local_artifact"},
               "meta.trust.source_class invalid")
        for key in ("source_context", "enrichment", "llm", "delivery"):
            _check(isinstance(trust[key], bool), f"meta.trust.{key} must be bool")

    failure = doc["failure"]
    for key in ("stage", "kind", "summary", "message", "stacktrace", "failed_tests", "events"):
        _check(key in failure, f"failure.{key} missing")
    _check(failure["stage"] in STAGES, f"stage {failure['stage']!r} invalid")
    _check(failure["kind"] in KINDS, f"kind {failure['kind']!r} invalid")
    for key in ("summary", "message"):
        _check(isinstance(failure.get(key), str), f"failure.{key} must be str")
    _check(isinstance(failure.get("stacktrace"), list), "stacktrace must be list")
    _check(isinstance(failure.get("failed_tests"), list), "failed_tests must be list")
    _check(isinstance(failure.get("events"), list), "events must be list")
    for event in failure["events"]:
        _check(isinstance(event, dict), "events entries must be objects")
        _check(event.get("stage") in STAGES, "event stage invalid")
        _check(event.get("kind") in KINDS, "event kind invalid")
        _check(isinstance(event.get("message"), str), "event message must be str")
        _check(event.get("role") in {"primary", "downstream"}, "event role invalid")
        # M7 causal-link wire format (optional, additive; legacy events may omit it).
        if "event_id" in event:
            _check(isinstance(event["event_id"], str), "event event_id must be str")
        if "service" in event:
            _check(isinstance(event["service"], str), "event service must be str")
        if "trace_id" in event:
            _check(isinstance(event["trace_id"], str), "event trace_id must be str")
        if "span_id" in event:
            _check(isinstance(event["span_id"], str), "event span_id must be str")
        if "parent_span_id" in event:
            _check(event["parent_span_id"] is None or isinstance(event["parent_span_id"], str),
                   "event parent_span_id must be str or null")
        if "timestamp" in event:
            _check(isinstance(event["timestamp"], str), "event timestamp must be str")
        if "timestamp_ns" in event:
            _check(event["timestamp_ns"] is None or (type(event["timestamp_ns"]) is int and event["timestamp_ns"] >= 0),
                   "event timestamp_ns must be a non-negative int or null")
        if "sequence" in event:
            _check(event["sequence"] is None or (type(event["sequence"]) is int and event["sequence"] >= 0),
                   "event sequence must be a non-negative int or null")
    for frame in failure["stacktrace"]:
        _check(isinstance(frame, dict), "stacktrace entries must be objects")
        _check(isinstance(frame.get("file"), str), "stacktrace.file must be str")
        _check(type(frame.get("line")) is int, "stacktrace.line must be int")
        _check(frame.get("function") is None or isinstance(frame.get("function"), str), "stacktrace.function must be str or null")
        _check(isinstance(frame.get("code"), str), "stacktrace.code must be str")
    for test in failure["failed_tests"]:
        _check(isinstance(test, dict), "failed_tests entries must be objects")
        _check(isinstance(test.get("name"), str), "failed_tests.name must be str")
        _check(isinstance(test.get("file"), str), "failed_tests.file must be str")
        _check(test.get("line") is None or type(test.get("line")) is int, "failed_tests.line must be int or null")
        _check(isinstance(test.get("assertion"), str), "failed_tests.assertion must be str")

    context = doc["context"]
    if current_schema:
        _check(
            set(context) <= {
                "run", "deployment", "request", "owners", "connector_audits", "source_evidence",
            },
            "context contains unsupported fields",
        )
    _check(isinstance(context.get("owners"), list) and all(isinstance(owner, str) for owner in context["owners"]), "context.owners must be list[str]")
    context_fields = {
        "run": {"provider", "run_id", "run_url", "job_id", "job_name", "workflow", "branch", "commit_sha", "step_name", "attempt", "conclusion", "duration_ms", "pr_number", "base_sha", "head_sha"},
        "deployment": {"platform", "environment", "cluster", "target", "namespace", "release", "revision", "previous_revision", "artifact", "strategy", "started_at", "migration_version", "outcome", "recovery"},
        "request": {"request_id", "trace_id", "session_id", "user_id", "users", "method", "path"},
    }
    deployment_fields = context_fields["deployment"] | {
        "service", "workload", "commit", "image_digest", "finished_at",
        "previous_commit", "previous_image_digest", "customer_impact",
        "manifest_digest", "previous_manifest_digest", "resource_fingerprint",
        "previous_resource_fingerprint", "previous_migration_version",
        "runtime_version", "previous_runtime_version", "dependency_fingerprint",
        "previous_dependency_fingerprint", "feature_flag_version",
        "previous_feature_flag_version", "slo_target", "error_budget_remaining",
        "runbook_url",
    }
    for section, fields in context_fields.items():
        value = context.get(section)
        _check(isinstance(value, dict), f"context.{section} must be an object")
        if current_schema:
            allowed_fields = deployment_fields if section == "deployment" else fields
            _check(set(value) <= allowed_fields, f"context.{section} contains unsupported fields")
        _check(fields.issubset(value), f"context.{section} missing fields")
        for key, item in value.items():
            if key in {"attempt", "duration_ms"}:
                _check(item is None or (type(item) is int and item > 0),
                       f"context.run.{key} must be a positive integer or null")
            elif section == "request" and key == "users":
                _check(isinstance(item, list) and all(isinstance(user, str) for user in item),
                       "context.request.users must be list[str]")
                _check(len(item) <= MAX_REQUEST_USERS,
                       f"context.request.users must contain at most {MAX_REQUEST_USERS} users")
            else:
                _check(isinstance(item, str), f"context.{section}.{key} must be str")
    # M7 additive deployment fields (optional; legacy v2.0 sidecars omit them).
    deployment = context.get("deployment")
    assert isinstance(deployment, dict)
    if current_schema:
        _check(set(deployment) <= deployment_fields, "context.deployment contains unsupported fields")
    for key in deployment_fields:
        if key in deployment:
            if key == "customer_impact" and current_schema:
                _check(
                    deployment[key] in {"", "unknown", "none", "degraded", "outage"},
                    "context.deployment.customer_impact invalid",
                )
            else:
                _check(isinstance(deployment[key], str), f"context.deployment.{key} must be str")

    if "connector_audits" in context:
        connector_audits = context["connector_audits"]
        _check(isinstance(connector_audits, list), "context.connector_audits must be a list")
        assert isinstance(connector_audits, list)
        for audit in connector_audits:
            _check(isinstance(audit, dict), "context.connector_audits entries must be objects")
            assert isinstance(audit, dict)
            for key in ("connector", "operation", "resource", "namespace", "status", "observed_at", "error"):
                _check(isinstance(audit.get(key), str), f"context.connector_audits.{key} must be str")
            _check(type(audit.get("duration_ms")) is int and audit["duration_ms"] >= 0,
                   "context.connector_audits.duration_ms must be a non-negative int")
            _check(type(audit.get("output_bytes")) is int and audit["output_bytes"] >= 0,
                   "context.connector_audits.output_bytes must be a non-negative int")
            _check(audit.get("returncode") is None or type(audit.get("returncode")) is int,
                   "context.connector_audits.returncode must be int or null")
    if "source_evidence" in context:
        source_evidence = context["source_evidence"]
        _check(isinstance(source_evidence, list), "context.source_evidence must be a list")
        assert isinstance(source_evidence, list)
        for source in source_evidence:
            _check(isinstance(source, dict), "context.source_evidence entries must be objects")
            assert isinstance(source, dict)
            _check(isinstance(source.get("file"), str), "context.source_evidence.file must be str")
            _check(type(source.get("line")) is int and source["line"] >= 0,
                   "context.source_evidence.line must be a non-negative int")
            _check(type(source.get("send_to_llm")) is bool,
                   "context.source_evidence.send_to_llm must be bool")

    if "timeline" in doc:
        _validate_timeline(doc["timeline"])
    if "devops" in doc:
        _validate_devops(doc["devops"])
    if "test_impact" in doc:
        _validate_test_impact(doc["test_impact"])

    rc = doc["root_cause"]
    for key in ("confidence", "hypothesis", "evidence", "fix_suggestion"):
        _check(key in rc, f"root_cause.{key} missing")
    _check(rc["confidence"] in CONFIDENCES, f"confidence {rc['confidence']!r} invalid")
    for key in ("hypothesis", "fix_suggestion"):
        _check(isinstance(rc.get(key), str), f"root_cause.{key} must be str")
    _check(isinstance(rc.get("evidence"), list), "evidence must be list")
    _check(all(isinstance(item, str) for item in rc["evidence"]), "evidence entries must be str")
    try:
        validate_recommendation(rc["fix_suggestion"], field="root_cause.fix_suggestion")
    except ValueError as exc:
        raise ValueError(f"invalid RCA doc: {exc}") from exc

    triage = doc["triage"]
    for key in ("severity", "priority", "dedup_key", "component", "is_duplicate_of", "flaky_suspect", "recurring_incident", "occurrence_count"):
        _check(key in triage, f"triage.{key} missing")
    _check(triage["severity"] in SEVERITIES, f"severity {triage['severity']!r} invalid")
    _check(type(triage["priority"]) is int and 1 <= triage["priority"] <= 5,
           "priority must be int in 1..5")
    _check(isinstance(triage.get("dedup_key"), str), "dedup_key must be str")
    _check(isinstance(triage.get("component"), str), "component must be str")
    _check(triage.get("is_duplicate_of") is None or isinstance(triage.get("is_duplicate_of"), str), "is_duplicate_of must be str or null")
    _check(isinstance(triage.get("flaky_suspect"), bool), "flaky_suspect must be bool")
    _check(isinstance(triage.get("recurring_incident"), bool), "recurring_incident must be bool")
    _check(type(triage.get("occurrence_count")) is int and triage["occurrence_count"] >= 1, "occurrence_count must be positive int")

    ticket = doc["ticket"]
    for key in ("title", "body_md", "labels"):
        _check(key in ticket, f"ticket.{key} missing")
    _check(isinstance(ticket.get("title"), str), "ticket.title must be str")
    _check(isinstance(ticket.get("body_md"), str), "ticket.body_md must be str")
    _check(isinstance(ticket.get("labels"), list) and all(isinstance(label, str) for label in ticket["labels"]), "ticket.labels must be list[str]")

    if current_schema:
        _validate_analysis(doc)


def _validate_analysis(doc: dict) -> None:
    analysis = doc.get("analysis")
    _check(isinstance(analysis, dict), "analysis must be an object")
    assert isinstance(analysis, dict)
    analysis_fields = {"observed_facts", "evidence", "hypotheses", "missing_information", "recommended_checks"}
    _check(set(analysis) == analysis_fields, "analysis contains unsupported fields")
    for key in analysis_fields:
        _check(key in analysis, f"analysis.{key} missing")
    for key in analysis_fields:
        _check(isinstance(analysis[key], list), f"analysis.{key} must be a list")
        _check(len(analysis[key]) <= _MAX_ANALYSIS_LIST_ITEMS, f"analysis.{key} contains too many items")
    _check(all(isinstance(value, str) for value in analysis["missing_information"]),
           "analysis.missing_information must be list[str]")
    _check(all(isinstance(value, str) for value in analysis["recommended_checks"]),
           "analysis.recommended_checks must be list[str]")
    for index, value in enumerate(analysis["missing_information"]):
        _validate_analysis_value(value, f"analysis.missing_information[{index}]")
    try:
        validate_recommendations(analysis["recommended_checks"], field="analysis.recommended_checks")
    except ValueError as exc:
        raise ValueError(f"invalid RCA doc: {exc}") from exc
    for index, value in enumerate(analysis["recommended_checks"]):
        _validate_analysis_value(value, f"analysis.recommended_checks[{index}]")

    evidence_ids: set[str] = set()
    for item in analysis["evidence"]:
        _check(isinstance(item, dict), "analysis.evidence entries must be objects")
        assert isinstance(item, dict)
        _check(set(item) == {"id", "kind", "value", "provenance"}, "analysis.evidence fields invalid")
        evidence_id = item.get("id")
        _check(
            isinstance(evidence_id, str)
            and len(evidence_id) <= 64
            and _EVIDENCE_ID_RE.fullmatch(evidence_id) is not None,
            "analysis.evidence.id invalid",
        )
        assert isinstance(evidence_id, str)
        _check(evidence_id not in evidence_ids, "analysis.evidence IDs must be unique")
        evidence_ids.add(evidence_id)
        _check(isinstance(item.get("kind"), str) and bool(item["kind"]), "analysis.evidence.kind invalid")
        _check("value" in item, "analysis.evidence.value missing")
        _validate_analysis_value(item["value"], f"analysis.evidence.{evidence_id}.value")
        provenance = item.get("provenance")
        _check(isinstance(provenance, dict), "analysis.evidence.provenance must be an object")
        assert isinstance(provenance, dict)
        _check(
            set(provenance) == {"source_type", "artifact", "locator", "collector", "observed_at"},
            "analysis.evidence.provenance fields invalid",
        )
        _check(
            isinstance(provenance["source_type"], str)
            and provenance["source_type"] in {"artifact", "repository", "connector", "context"},
            "analysis.evidence.provenance.source_type invalid",
        )
        for key in ("source_type", "artifact", "locator", "collector", "observed_at"):
            if key == "observed_at":
                continue
            _check(
                isinstance(provenance[key], str)
                and (key == "artifact" or bool(provenance[key].strip())),
                f"analysis.evidence.provenance.{key} must be a non-empty str"
                if key != "artifact"
                else "analysis.evidence.provenance.artifact must be str",
            )
            _validate_analysis_value(provenance[key], f"analysis.evidence.{evidence_id}.provenance.{key}")
        observed_at = provenance["observed_at"]
        _check(
            observed_at is None or (isinstance(observed_at, str) and bool(observed_at.strip())),
            "analysis.evidence.provenance.observed_at must be a non-empty str or null",
        )
        if isinstance(observed_at, str):
            _validate_analysis_value(observed_at, f"analysis.evidence.{evidence_id}.provenance.observed_at")
            try:
                datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("invalid RCA doc: evidence observed_at must be ISO 8601") from exc

    fact_ids: set[str] = set()
    for fact in analysis["observed_facts"]:
        _check(isinstance(fact, dict), "analysis.observed_facts entries must be objects")
        assert isinstance(fact, dict)
        _check(set(fact) == {"id", "kind", "value", "evidence_refs"}, "analysis.observed_facts fields invalid")
        fact_id = fact.get("id")
        _check(
            isinstance(fact_id, str)
            and len(fact_id) <= 64
            and _FACT_ID_RE.fullmatch(fact_id) is not None,
            "analysis.observed_facts.id invalid",
        )
        assert isinstance(fact_id, str)
        _check(fact_id not in fact_ids, "analysis.observed_facts IDs must be unique")
        fact_ids.add(fact_id)
        _check(isinstance(fact.get("kind"), str) and bool(fact["kind"]), "analysis.observed_facts fields invalid")
        _validate_analysis_value(fact["value"], f"analysis.observed_facts.{fact_id}.value")
        refs = fact.get("evidence_refs")
        _check(
            isinstance(refs, list)
            and len(refs) <= _MAX_ANALYSIS_LIST_ITEMS
            and all(isinstance(ref, str) for ref in refs),
            "analysis.observed_facts evidence_refs must be a list of strings",
        )
        assert isinstance(refs, list)
        _check(all(ref in evidence_ids for ref in refs),
               "analysis.observed_facts contains an unresolved evidence reference")
        _check(len(refs) == len(set(refs)),
               "analysis.observed_facts contains duplicate evidence references")

    _check(bool(analysis["hypotheses"]), "analysis.hypotheses cannot be empty")
    hypothesis_ids: set[str] = set()
    for hypothesis in analysis["hypotheses"]:
        _check(isinstance(hypothesis, dict), "analysis.hypotheses entries must be objects")
        assert isinstance(hypothesis, dict)
        _check(
            set(hypothesis) == {
                "id", "statement", "source", "support_status", "supporting_evidence_refs",
                "contradicting_evidence_refs", "confidence", "missing_information", "recommended_checks",
            },
            "analysis.hypotheses fields invalid",
        )
        hypothesis_id = hypothesis.get("id")
        _check(
            isinstance(hypothesis_id, str)
            and len(hypothesis_id) <= 64
            and _HYPOTHESIS_ID_RE.fullmatch(hypothesis_id) is not None,
            "analysis.hypotheses.id invalid",
        )
        assert isinstance(hypothesis_id, str)
        _check(hypothesis_id not in hypothesis_ids, "analysis.hypothesis IDs must be unique")
        hypothesis_ids.add(hypothesis_id)
        _check(isinstance(hypothesis.get("statement"), str) and bool(hypothesis["statement"].strip()),
               "analysis.hypotheses.statement invalid")
        _validate_analysis_value(hypothesis["statement"], f"analysis.hypotheses.{hypothesis_id}.statement")
        _check(hypothesis.get("source") in {"deterministic", "llm"}, "analysis.hypotheses.source invalid")
        status = hypothesis.get("support_status")
        _check(status in {"supported", "unsupported", "insufficient_evidence"},
               "analysis.hypotheses.support_status invalid")
        supporting = hypothesis.get("supporting_evidence_refs")
        contradicting = hypothesis.get("contradicting_evidence_refs")
        _check(
            isinstance(supporting, list)
            and len(supporting) <= _MAX_ANALYSIS_LIST_ITEMS
            and all(isinstance(ref, str) for ref in supporting),
            "analysis.hypotheses supporting_evidence_refs must be a list of strings",
        )
        assert isinstance(supporting, list)
        _check(all(ref in evidence_ids for ref in supporting),
               "analysis.hypotheses contains an unresolved supporting evidence reference")
        _check(len(supporting) == len(set(supporting)),
               "analysis.hypotheses contains duplicate supporting evidence references")
        _check(
            isinstance(contradicting, list)
            and len(contradicting) <= _MAX_ANALYSIS_LIST_ITEMS
            and all(isinstance(ref, str) for ref in contradicting),
            "analysis.hypotheses contradicting_evidence_refs must be a list of strings",
        )
        assert isinstance(contradicting, list)
        _check(all(ref in evidence_ids for ref in contradicting),
               "analysis.hypotheses contains an unresolved contradicting evidence reference")
        _check(len(contradicting) == len(set(contradicting)),
               "analysis.hypotheses contains duplicate contradicting evidence references")
        _check(not set(supporting) & set(contradicting),
               "analysis.hypotheses cannot support and contradict the same evidence")
        _check(status != "supported" or bool(supporting), "supported hypothesis must reference evidence")
        _check(status != "supported" or not contradicting, "supported hypothesis cannot contradict evidence")
        confidence = hypothesis.get("confidence")
        _check(isinstance(confidence, dict), "analysis.hypotheses.confidence must be an object")
        assert isinstance(confidence, dict)
        _check(set(confidence) == {"band", "score", "reasons"}, "analysis.hypotheses.confidence fields invalid")
        _check(confidence.get("band") in CONFIDENCES, "analysis.hypotheses.confidence.band invalid")
        score = confidence.get("score")
        _check(
            (type(score) is int or type(score) is float)
            and math.isfinite(float(score))
            and 0.0 <= float(score) <= 1.0,
            "analysis.hypotheses.confidence.score invalid",
        )
        reasons = confidence.get("reasons")
        _check(
            isinstance(reasons, list)
            and len(reasons) <= _MAX_ANALYSIS_LIST_ITEMS
            and all(isinstance(reason, str) and bool(reason.strip()) for reason in reasons),
            "analysis.hypotheses.confidence.reasons must be a list of non-empty strings",
        )
        assert isinstance(reasons, list)
        for index, reason in enumerate(reasons):
            _validate_analysis_value(reason, f"analysis.hypotheses.{hypothesis_id}.confidence.reasons[{index}]")
        for key in ("missing_information", "recommended_checks"):
            values = hypothesis.get(key)
            _check(
                isinstance(values, list)
                and len(values) <= _MAX_ANALYSIS_LIST_ITEMS
                and all(isinstance(value, str) for value in values),
                f"analysis.hypotheses.{key} must be list[str]",
            )
            assert isinstance(values, list)
            for index, value in enumerate(values):
                _validate_analysis_value(value, f"analysis.hypotheses.{hypothesis_id}.{key}[{index}]")
        try:
            validate_recommendations(hypothesis["recommended_checks"], field="analysis.hypotheses.recommended_checks")
        except ValueError as exc:
            raise ValueError(f"invalid RCA doc: {exc}") from exc

    primary = analysis["hypotheses"][0]
    _check(primary["statement"] == doc["root_cause"]["hypothesis"],
           "analysis primary hypothesis must match root_cause.hypothesis")
    _check(primary["confidence"]["band"] == doc["root_cause"]["confidence"],
           "analysis primary confidence must match root_cause.confidence")
    _check(primary["source"] == ("llm" if doc["meta"]["engine"] in {"llm", "merged"} else "deterministic"),
           "analysis primary source must match meta.engine")
    _check(primary["missing_information"] == analysis["missing_information"],
           "analysis primary missing_information must match analysis summary")
    _check(primary["recommended_checks"] == analysis["recommended_checks"],
           "analysis primary recommended_checks must match analysis summary")


def _validate_timeline(timeline: object) -> None:
    """Validate the M7 timeline section when present (optional for legacy docs)."""
    _check(isinstance(timeline, dict), "timeline must be an object")
    assert isinstance(timeline, dict)
    _check(timeline.get("grouping") in {"runtime", "pipeline", "mixed", "none"},
           "timeline.grouping invalid")
    _check(timeline.get("ordering_basis") in {"timestamp_ns", "sequence", "log_order", "mixed"},
           "timeline.ordering_basis invalid")
    _check(type(timeline.get("has_cycles")) is bool, "timeline.has_cycles must be bool")
    _check(isinstance(timeline.get("cycle_warning"), str), "timeline.cycle_warning must be str")
    _check(isinstance(timeline.get("primary_event_id"), str), "timeline.primary_event_id must be str")
    for key in ("downstream_event_ids", "recovery_event_ids", "release_changed_fields"):
        _check(isinstance(timeline.get(key), list)
               and all(isinstance(item, str) for item in timeline[key]),
               f"timeline.{key} must be list[str]")
    _check(timeline.get("customer_impact") in {"unknown", "none", "degraded", "outage"},
           "timeline.customer_impact invalid")
    _check(timeline.get("release_changed") is None or type(timeline.get("release_changed")) is bool,
           "timeline.release_changed must be bool or null")
    entries = timeline.get("entries")
    _check(isinstance(entries, list), "timeline.entries must be a list")
    assert isinstance(entries, list)
    for entry in entries:
        _check(isinstance(entry, dict), "timeline.entries entries must be objects")
        assert isinstance(entry, dict)
        _check(isinstance(entry.get("event_id"), str), "timeline entry event_id must be str")
        _check(type(entry.get("position")) is int and entry["position"] >= 0,
               "timeline entry position must be a non-negative int")
        if "timestamp_ns" in entry:
            _check(entry["timestamp_ns"] is None or (type(entry["timestamp_ns"]) is int and entry["timestamp_ns"] >= 0),
                   "timeline entry timestamp_ns must be a non-negative int or null")
        _check(isinstance(entry.get("stage"), str) and entry["stage"] in STAGES, "timeline entry stage invalid")
        _check(entry.get("kind") in KINDS, "timeline entry kind invalid")
        _check(entry.get("role") in {"primary", "downstream", "recovery", "context", "unknown"},
               "timeline entry role invalid")
        _check(isinstance(entry.get("message"), str), "timeline entry message must be str")
        _check(entry.get("parent_span_id") is None or isinstance(entry.get("parent_span_id"), str),
               "timeline entry parent_span_id must be str or null")
        _check(entry.get("ordering_basis") in {"timestamp_ns", "sequence", "log_order"},
               "timeline entry ordering_basis invalid")
        _check(isinstance(entry.get("uncertainty"), str), "timeline entry uncertainty must be str")

        # Validate optional TimelineEntry attributes when present.
        _check(entry.get("timestamp") is None or isinstance(entry.get("timestamp"), str), "timeline entry timestamp must be str or null")
        _check(entry.get("sequence") is None or type(entry.get("sequence")) is int, "timeline entry sequence must be int or null")
        _check(entry.get("trace_id") is None or isinstance(entry.get("trace_id"), str), "timeline entry trace_id must be str or null")
        _check(entry.get("span_id") is None or isinstance(entry.get("span_id"), str), "timeline entry span_id must be str or null")
        _check(entry.get("service") is None or isinstance(entry.get("service"), str), "timeline entry service must be str or null")
        _check(entry.get("source") is None or isinstance(entry.get("source"), str), "timeline entry source must be str or null")


def _validate_devops(devops: object) -> None:
    _check(isinstance(devops, dict), "devops must be an object")
    assert isinstance(devops, dict)
    for key in ("release_changes", "metric_samples", "trace_spans", "service_boundaries"):
        _check(isinstance(devops.get(key), list), f"devops.{key} must be a list")
    for key in ("critical_path", "slo", "runbook"):
        _check(isinstance(devops.get(key), dict), f"devops.{key} must be an object")
    _check(isinstance(devops.get("static_severity"), str), "devops.static_severity must be str")
    _check(isinstance(devops.get("effective_severity"), str), "devops.effective_severity must be str")


def _validate_test_impact(test_impact: object) -> None:
    _check(isinstance(test_impact, dict), "test_impact must be an object")
    assert isinstance(test_impact, dict)
    _check(type(test_impact.get("advisory")) is bool, "test_impact.advisory must be bool")
    _check(test_impact.get("language") == "python", "test_impact.language invalid")
    _check(isinstance(test_impact.get("call_graph"), list), "test_impact.call_graph must be a list")
    _check(isinstance(test_impact.get("recommendations"), list), "test_impact.recommendations must be a list")
    _check(type(test_impact.get("missing_coverage")) is bool, "test_impact.missing_coverage must be bool")
