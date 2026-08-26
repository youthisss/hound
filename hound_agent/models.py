"""Core data models and versioned RCA document schemas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from hound_agent.pathutil import path_matches

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


def build_evidence_items(artifacts: Artifacts, observed_at: str = "") -> list[dict]:
    """Return bounded deterministic evidence with stable run-scoped IDs."""
    items: list[dict] = []

    def add(kind: str, value, source_type: str, locator: str, collector: str) -> None:
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
                "observed_at": observed_at or None,
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
    if any(vars(artifacts.run).values()):
        add("run_context", asdict(artifacts.run), "context", "context.run", "ingest.context")
    if any(vars(artifacts.deployment).values()):
        add("deployment_context", asdict(artifacts.deployment), "context", "context.deployment", "ingest.context")
    return items


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


def score_confidence(artifacts: Artifacts) -> tuple[float, list[str]]:
    """Score only deterministic observations; never score an LLM assertion."""
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


def _analysis_section(artifacts: Artifacts, root_cause: RootCause, generated_at: str) -> dict:
    evidence = build_evidence_items(artifacts, generated_at)
    available = {item["id"] for item in evidence}
    supporting = [ref for ref in root_cause.evidence_refs if ref in available]
    contradicting = [ref for ref in root_cause.contradicting_evidence_refs if ref in available]
    if supporting:
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
    score, reasons = score_confidence(artifacts)
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
    }


def _check(value: bool, msg: str) -> None:
    if not value:
        raise ValueError(f"invalid RCA doc: {msg}")


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
    _check(isinstance(context.get("owners"), list) and all(isinstance(owner, str) for owner in context["owners"]), "context.owners must be list[str]")
    for section, fields in {
        "run": {"provider", "run_id", "run_url", "job_id", "job_name", "workflow", "branch", "commit_sha", "step_name", "attempt", "conclusion", "duration_ms", "pr_number", "base_sha", "head_sha"},
        "deployment": {"platform", "environment", "cluster", "target", "namespace", "release", "revision", "previous_revision", "artifact", "strategy", "started_at", "migration_version", "outcome", "recovery"},
        "request": {"request_id", "trace_id", "session_id", "user_id", "users", "method", "path"},
    }.items():
        value = context.get(section)
        _check(isinstance(value, dict), f"context.{section} must be an object")
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

    rc = doc["root_cause"]
    for key in ("confidence", "hypothesis", "evidence", "fix_suggestion"):
        _check(key in rc, f"root_cause.{key} missing")
    _check(rc["confidence"] in CONFIDENCES, f"confidence {rc['confidence']!r} invalid")
    for key in ("hypothesis", "fix_suggestion"):
        _check(isinstance(rc.get(key), str), f"root_cause.{key} must be str")
    _check(isinstance(rc.get("evidence"), list), "evidence must be list")
    _check(all(isinstance(item, str) for item in rc["evidence"]), "evidence entries must be str")

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
    for key in ("observed_facts", "evidence", "hypotheses", "missing_information", "recommended_checks"):
        _check(key in analysis, f"analysis.{key} missing")
    for key in ("observed_facts", "evidence", "hypotheses", "missing_information", "recommended_checks"):
        _check(isinstance(analysis[key], list), f"analysis.{key} must be a list")
    _check(all(isinstance(value, str) for value in analysis["missing_information"]),
           "analysis.missing_information must be list[str]")
    _check(all(isinstance(value, str) for value in analysis["recommended_checks"]),
           "analysis.recommended_checks must be list[str]")

    evidence_ids: set[str] = set()
    for item in analysis["evidence"]:
        _check(isinstance(item, dict), "analysis.evidence entries must be objects")
        assert isinstance(item, dict)
        evidence_id = item.get("id")
        _check(isinstance(evidence_id, str) and evidence_id.startswith("ev-"), "analysis.evidence.id invalid")
        assert isinstance(evidence_id, str)
        _check(evidence_id not in evidence_ids, "analysis.evidence IDs must be unique")
        evidence_ids.add(evidence_id)
        _check(isinstance(item.get("kind"), str) and bool(item["kind"]), "analysis.evidence.kind invalid")
        _check("value" in item, "analysis.evidence.value missing")
        provenance = item.get("provenance")
        _check(isinstance(provenance, dict), "analysis.evidence.provenance must be an object")
        assert isinstance(provenance, dict)
        for key in ("source_type", "artifact", "locator", "collector", "observed_at"):
            _check(key in provenance, f"analysis.evidence.provenance.{key} missing")
        for key in ("source_type", "artifact", "locator", "collector"):
            _check(isinstance(provenance[key], str), f"analysis.evidence.provenance.{key} must be str")
        observed_at = provenance["observed_at"]
        _check(observed_at is None or isinstance(observed_at, str), "analysis.evidence.provenance.observed_at must be str or null")
        if isinstance(observed_at, str):
            try:
                datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("invalid RCA doc: evidence observed_at must be ISO 8601") from exc

    fact_ids: set[str] = set()
    for fact in analysis["observed_facts"]:
        _check(isinstance(fact, dict), "analysis.observed_facts entries must be objects")
        assert isinstance(fact, dict)
        fact_id = fact.get("id")
        _check(isinstance(fact_id, str) and fact_id.startswith("fact-"), "analysis.observed_facts.id invalid")
        assert isinstance(fact_id, str)
        _check(fact_id not in fact_ids, "analysis.observed_facts IDs must be unique")
        fact_ids.add(fact_id)
        _check(isinstance(fact.get("kind"), str) and "value" in fact, "analysis.observed_facts fields invalid")
        refs = fact.get("evidence_refs")
        _check(isinstance(refs, list) and all(ref in evidence_ids for ref in refs),
               "analysis.observed_facts contains an unresolved evidence reference")

    _check(bool(analysis["hypotheses"]), "analysis.hypotheses cannot be empty")
    hypothesis_ids: set[str] = set()
    for hypothesis in analysis["hypotheses"]:
        _check(isinstance(hypothesis, dict), "analysis.hypotheses entries must be objects")
        assert isinstance(hypothesis, dict)
        hypothesis_id = hypothesis.get("id")
        _check(isinstance(hypothesis_id, str) and hypothesis_id.startswith("hyp-"), "analysis.hypotheses.id invalid")
        assert isinstance(hypothesis_id, str)
        _check(hypothesis_id not in hypothesis_ids, "analysis.hypothesis IDs must be unique")
        hypothesis_ids.add(hypothesis_id)
        _check(isinstance(hypothesis.get("statement"), str) and bool(hypothesis["statement"]),
               "analysis.hypotheses.statement invalid")
        _check(hypothesis.get("source") in {"deterministic", "llm"}, "analysis.hypotheses.source invalid")
        status = hypothesis.get("support_status")
        _check(status in {"supported", "unsupported", "insufficient_evidence"},
               "analysis.hypotheses.support_status invalid")
        supporting = hypothesis.get("supporting_evidence_refs")
        contradicting = hypothesis.get("contradicting_evidence_refs")
        _check(isinstance(supporting, list) and all(ref in evidence_ids for ref in supporting),
               "analysis.hypotheses contains an unresolved supporting evidence reference")
        _check(isinstance(contradicting, list) and all(ref in evidence_ids for ref in contradicting),
               "analysis.hypotheses contains an unresolved contradicting evidence reference")
        _check(status != "supported" or bool(supporting), "supported hypothesis must reference evidence")
        confidence = hypothesis.get("confidence")
        _check(isinstance(confidence, dict), "analysis.hypotheses.confidence must be an object")
        assert isinstance(confidence, dict)
        _check(confidence.get("band") in CONFIDENCES, "analysis.hypotheses.confidence.band invalid")
        score = confidence.get("score")
        _check(type(score) is float and 0.0 <= score <= 1.0, "analysis.hypotheses.confidence.score invalid")
        _check(isinstance(confidence.get("reasons"), list)
               and all(isinstance(reason, str) for reason in confidence["reasons"]),
               "analysis.hypotheses.confidence.reasons must be list[str]")
        for key in ("missing_information", "recommended_checks"):
            _check(isinstance(hypothesis.get(key), list)
                   and all(isinstance(value, str) for value in hypothesis[key]),
                   f"analysis.hypotheses.{key} must be list[str]")
