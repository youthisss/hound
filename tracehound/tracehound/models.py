"""Core data models and the RCA document schema (v1.1)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

SCHEMA_VERSION = "1.2"

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


@dataclass
class RootCause:
    hypothesis: str = ""
    confidence: str = "low"
    evidence: list[str] = field(default_factory=list)
    fix_suggestion: str = ""
    engine: str = "fallback"
    model: str | None = None
    usage: dict = field(default_factory=dict)


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


def build_doc(
    artifacts: Artifacts,
    root_cause: RootCause,
    triage: Triage,
    ticket: Ticket,
    generated_at: str,
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
            "owners": artifacts.git.owners,
        },
        "root_cause": {
            "hypothesis": root_cause.hypothesis,
            "confidence": root_cause.confidence,
            "evidence": root_cause.evidence,
            "fix_suggestion": root_cause.fix_suggestion,
        },
        "triage": asdict(triage),
        "ticket": asdict(ticket),
    }


def _check(value: bool, msg: str) -> None:
    if not value:
        raise ValueError(f"invalid RCA doc: {msg}")


def validate(doc: dict) -> None:
    """Validate a document dict against the current schema. Raises ValueError."""
    _check(isinstance(doc, dict), "not a dict")
    # Report malformed present sections before reporting fields added by a newer
    # schema version; this keeps validation errors actionable for consumers.
    for section in ("meta", "failure", "context", "root_cause", "triage", "ticket"):
        if section in doc:
            _check(isinstance(doc[section], dict), f"{section} must be an object")
    for key in ("schema_version", "meta", "failure", "context", "root_cause", "triage", "ticket"):
        _check(key in doc, f"missing key {key!r}")
    _check(doc["schema_version"] == SCHEMA_VERSION, f"schema_version must be {SCHEMA_VERSION}")

    meta = doc["meta"]
    for key in ("engine", "model", "log_file", "generated_at", "redacted", "usage"):
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
    }.items():
        value = context.get(section)
        _check(isinstance(value, dict), f"context.{section} must be an object")
        _check(fields.issubset(value), f"context.{section} missing fields")
        for key, item in value.items():
            if key in {"attempt", "duration_ms"}:
                _check(item is None or (type(item) is int and item > 0), "context.run.attempt invalid")
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
