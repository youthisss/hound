"""Core analysis pipeline. Single entry point for CLI and TUI."""
from __future__ import annotations

import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from hound_agent.analyze.rca import run_analysis
from hound_agent.analyze.fallback import build_root_cause
from hound_agent.analyze.llm import build_request_preview
from hound_agent.config import Config, load_config
from hound_agent.connectors.observability import collect_observability_bundle
from hound_agent.devops.investigation import build_investigation
from hound_agent.devops.timeline import build_timeline, timeline_to_dict
from hound_agent.ingest.context import load_context
from hound_agent.ingest.entity import extract_entity_context
from hound_agent.ingest.enrich import collect_deployment_evidence
from hound_agent.ingest.git import correlated_commit_subjects, gather
from hound_agent.ingest.logs import extract_events, parse_log, read_log_window
from hound_agent.ingest.owners import resolve_owners
from hound_agent.ingest.redact import redact_text
from hound_agent.ingest.structured import parse_structured_artifact
from hound_agent.ingest.stacktrace import attach_snippets, dedupe_repo_paths, parse_stacktrace
from hound_agent.ingest.tests import parse_failed_tests
from hound_agent.feedback import default_feedback_store, find_known_issue
from hound_agent.fsio import atomic_write
from hound_agent.models import ENGINES, Artifacts, GitInfo, RootCause, Triage, build_doc, validate
from hound_agent.output.report import ensure_outdir, write_json, write_md
from hound_agent.output.tickets import build_ticket, write_ticket
from hound_agent.source.context import collect_source_evidence
from hound_agent.source.impact import build_test_impact
from hound_agent.triage.component import assign
from hound_agent.triage.dedup import check_duplicate, configure_store, fingerprint, lookup_incident, record_triage
from hound_agent.triage.severity import classify
from hound_agent.telemetry import telemetry


def default_state_path(out: Path, config_state: str | None, no_dedup: bool, backend: str = "file") -> str | None:
    if no_dedup:
        return None
    if config_state:
        return str(Path(config_state).resolve())
    state_dir = out / ".hound-agent"
    state_file = state_dir / ("state.sqlite3" if backend == "sqlite" else "state.json")
    # A checked-out output directory is attacker-controlled in CI. Never let
    # the default state location follow a pre-seeded symlink outside `out`.
    if state_dir.is_symlink() or state_file.is_symlink():
        raise ValueError("refusing symlinked default dedup state path")
    return str(state_file.resolve())


def _root_cause_snapshot(root_cause: RootCause) -> dict:
    """Serialize an RCA for the dedup store (cost-control reuse). Usage is
    deliberately excluded: a reused run spends zero tokens right now."""
    return {
        "hypothesis": root_cause.hypothesis,
        "confidence": root_cause.confidence,
        "evidence": list(root_cause.evidence),
        "fix_suggestion": root_cause.fix_suggestion,
        "engine": root_cause.engine,
        "model": root_cause.model,
        "evidence_refs": list(root_cause.evidence_refs),
        "contradicting_evidence_refs": list(root_cause.contradicting_evidence_refs),
        "missing_information": list(root_cause.missing_information),
        "recommended_checks": list(root_cause.recommended_checks),
    }


def _root_cause_from_snapshot(snapshot: dict) -> RootCause | None:
    """Rebuild a RootCause from a persisted snapshot, or None when corrupt."""
    try:
        confidence = snapshot.get("confidence")
        engine = snapshot.get("engine")
        model = snapshot.get("model")
        missing_information = list(dict.fromkeys([
            *[str(item) for item in snapshot.get("missing_information", [])],
            "Stored hypothesis was reused; evidence references are scoped to the original run.",
        ]))
        return RootCause(
            hypothesis=str(snapshot.get("hypothesis", "")),
            confidence=confidence if confidence in {"high", "medium", "low"} else "low",
            evidence=[str(item) for item in snapshot.get("evidence", [])],
            fix_suggestion=str(snapshot.get("fix_suggestion", "")),
            engine=engine if engine in ENGINES else "fallback",
            model=str(model) if isinstance(model, str) and model else None,
            usage={},
            llm_status="reused",
            # Evidence IDs are scoped to the report that created the snapshot.
            # Reusing them in a later run could silently cite a different item
            # that happens to receive the same counter ID.
            evidence_refs=[],
            contradicting_evidence_refs=[],
            missing_information=missing_information,
            recommended_checks=[str(item) for item in snapshot.get("recommended_checks", [])],
        )
    except (TypeError, ValueError):
        return None


def _analyze_with_reuse(
    artifacts: Artifacts,
    config: Config,
    state_path: str | None,
    feedback_store_path: str | Path | None = None,
    feedback_output_root: str | Path | None = None,
) -> tuple[RootCause, str | None]:
    """Dedup-first analysis: reuse a stored root cause for a well-established
    recurring incident instead of spending another LLM call. Returns
    ``(root_cause, reused_from_key)`` where the key is None for fresh analysis.

    Logs without a recognized failure kind never touch the store: they are
    not recorded as occurrences and therefore cannot be "reused" either."""
    if config.reuse and artifacts.kind != "unknown":
        key = fingerprint(artifacts)
        known = (
            find_known_issue(feedback_store_path, feedback_output_root, key)
            if feedback_store_path and feedback_output_root else None
        )
        if known is not None:
            snapshot = known["report"].get("root_cause")
            if isinstance(snapshot, dict):
                reused = _root_cause_from_snapshot(snapshot)
                if reused is not None:
                    reused.missing_information = list(dict.fromkeys([
                        *reused.missing_information,
                        "Known issue matched reviewed feedback; verify the recorded resolution still applies.",
                    ]))
                    return reused, key
        entry = lookup_incident(state_path, key) if state_path else None
        if entry is not None:
            try:
                count = int(entry.get("count", 0))
            except (TypeError, ValueError):
                count = 0
            snapshot = entry.get("root_cause")
            if count >= config.reuse_after_occurrences and isinstance(snapshot, dict):
                reused = _root_cause_from_snapshot(snapshot)
                if reused is not None:
                    return reused, key
    return run_analysis(artifacts, config), None


def analyze(
    log_path: str | Path,
    out_dir: str | Path,
    *,
    repo_dir: str | Path | None = None,
    offline: bool = False,
    config_path: str | None = None,
    no_dedup: bool = False,
    state_path: str | None = None,
    write: bool = True,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    redact: bool | None = None,
    max_retries: int | None = None,
    require_llm: bool | None = None,
    source_context: bool = False,
    context_path: str | None = None,
    enrich: bool = False,
    source_class: str | None = None,
    llm_preview: bool = False,
    feedback_store_path: str | Path | None = None,
    feedback_output_root: str | Path | None = None,
    _config: Config | None = None,
) -> dict:
    analysis_started = time.perf_counter()
    """Run the full pipeline for one log. Returns the validated RCA document."""
    log_path = Path(log_path)
    if log_path.is_symlink() or not log_path.is_file():
        raise FileNotFoundError(f"log file not found: {log_path}")

    config = _config or load_config(
        offline=offline,
        config_path=config_path,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        redact=redact,
        max_retries=max_retries,
        require_llm=require_llm,
        source_class=source_class,
    )

    text = read_log_window(log_path)
    request = extract_entity_context(text)

    run, deployment = load_context(log_path, text, context_path)
    unique_id = run.run_id if run and getattr(run, "run_id", None) else None
    if not unique_id:
        import hashlib
        # if out_dir is an instance of Path, it's safe to use / with it
        # but in test_cli_run_analyze_namespace out_dir is just out
        unique_id = hashlib.sha256(str(log_path.resolve()).encode()).hexdigest()[:12]

    out = ensure_outdir(out_dir)

    if config.state_backend not in {"", "file", "sqlite"}:
        raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")
    configure_store(
        backend=config.state_backend or "file",
        max_entries=config.dedup_max_entries,
        retention_days=config.dedup_retention_days,
    )
    if state_path is None:
        state_path = default_state_path(out, config.state_file, no_dedup, backend=config.state_backend)

    redacted = False
    if config.redact:
        text, hits = redact_text(text)
        redacted = hits > 0

    structured = parse_structured_artifact(log_path)
    if structured:
        stage, kind, summary, message, failed_tests = structured
    else:
        stage, kind, summary, message = parse_log(text)
        failed_tests = parse_failed_tests(text)

    if not deployment.runbook_url:
        deployment.runbook_url = config.runbooks.get(deployment.service or deployment.target, "")
    trusted_repo = repo_dir if config.allow_source_context else None
    allow_enrichment = enrich and config.allow_enrichment
    # Log-derived deployment names are untrusted. Enrichment requires an
    # operator-supplied context file, which establishes the query boundary.
    enrichment = collect_deployment_evidence(deployment) if allow_enrichment and context_path and stage == "deploy" else []
    connector_audits = [asdict(audit) for audit in getattr(enrichment, "audits", [])]
    if enrichment:
        text = text + "\n\n--- read-only deployment evidence ---\n" + "\n\n".join(enrichment)
    frames = parse_stacktrace(text)
    git = gather(str(trusted_repo), run.base_sha, run.head_sha) if trusted_repo else GitInfo()
    if trusted_repo:
        git.owners = resolve_owners(trusted_repo, [frame.file for frame in frames] + git.changed_files)
        frames = dedupe_repo_paths(frames, str(trusted_repo))
        git.correlated_commits = correlated_commit_subjects(
            str(trusted_repo),
            [frame.file for frame in frames],
            git.changed_files,
        )
    if trusted_repo and source_context:
        frames = attach_snippets(frames, str(trusted_repo))
        if config.redact:
            for frame in frames:
                if frame.code:
                    frame.code, snippet_hits = redact_text(frame.code)
                    redacted = redacted or snippet_hits > 0

    source_evidence = (
        collect_source_evidence(
            trusted_repo,
            frames,
            git.changed_files,
            send_to_llm=config.source_send_to_llm,
        )
        if trusted_repo and source_context else []
    )
    test_impact = (
        build_test_impact(trusted_repo, source_evidence)
        if trusted_repo and source_context and source_evidence else None
    )

    artifacts = Artifacts(
        log_text=text,
        stage=stage,
        kind=kind,
        summary=summary,
        message=message,
        frames=frames,
        failed_tests=failed_tests,
        git=git,
        run=run,
        deployment=deployment,
        request=request,
        events=extract_events(text, stage, kind, message),
        enrichment=enrichment,
        connector_audits=connector_audits,
        source_evidence=source_evidence,
        log_path=str(log_path.resolve()),
        redacted=redacted,
    )
    if allow_enrichment and context_path and stage == "deploy" and (config.prometheus_url or config.tempo_url):
        observability = collect_observability_bundle(
            artifacts,
            prometheus_url=config.prometheus_url,
            prometheus_token=config.prometheus_token,
            tempo_url=config.tempo_url,
            tempo_token=config.tempo_token,
            window_minutes=config.observability_window_minutes,
        )
        artifacts.metric_samples = observability.metric_samples
        artifacts.trace_spans = observability.trace_spans
        artifacts.connector_audits.extend(asdict(audit) for audit in observability.audits)
    if config.redact:
        artifact_hits = _redact_artifacts(artifacts)
        artifacts.redacted = artifacts.redacted or artifact_hits > 0

    if feedback_output_root is None:
        feedback_output_root = out
    if feedback_store_path is None:
        feedback_store_path = default_feedback_store(feedback_output_root)
    if llm_preview:
        preview = build_request_preview(artifacts, config)
        atomic_write(out / "llm-preview.json", __import__("json").dumps(preview, indent=2, ensure_ascii=False))
        root_cause, reused_from_key = build_root_cause(artifacts), None
    else:
        root_cause, reused_from_key = _analyze_with_reuse(
            artifacts,
            config,
            state_path,
            feedback_store_path,
            feedback_output_root,
        )

    severity, priority = classify(artifacts)
    environment_overrides = config.severity_overrides.get(artifacts.deployment.environment, {})
    if override := environment_overrides.get(artifacts.kind):
        if override in {"critical", "high", "medium", "low"}:
            severity = override
            priority = {"critical": 1, "high": 2, "medium": 3, "low": 4}[severity]
    devops = build_investigation(artifacts, severity, deployment.runbook_url)
    severity = devops["effective_severity"]
    priority = min(priority, {"critical": 1, "high": 2, "medium": 3, "low": 4}[severity])
    component = assign(artifacts, config.components)
    # Healthy/unrecognized logs must not consume dedup slots: recording them
    # would evict real incidents under MAX_STATE_ENTRIES pressure (rev-6 G3).
    if artifacts.kind == "unknown":
        triage = Triage(dedup_key=fingerprint(artifacts))
    else:
        triage = check_duplicate(artifacts, state_path, config.recurrence_threshold)
    triage.severity = severity
    triage.priority = priority
    triage.component = component
    # Flakiness is evidence from a test retry, not a synonym for recurrence.
    triage.flaky_suspect = artifacts.kind == "flaky"
    if triage.flaky_suspect:
        triage.priority = 5

    ticket = build_ticket(artifacts, root_cause, triage)
    if artifacts.kind != "unknown":
        persisted = record_triage(
            state_path,
            triage,
            component,
            ticket.title,
            root_cause=_root_cause_snapshot(root_cause),
            artifacts=artifacts,
        )
        if state_path and not persisted:
            sys.stderr.write(
                "Warning: root-cause reuse snapshot was not persisted; "
                "a later matching incident may require fresh analysis.\n"
            )

    timeline = timeline_to_dict(build_timeline(artifacts))

    doc = build_doc(
        artifacts,
        root_cause,
        triage,
        ticket,
        generated_at=datetime.now(timezone.utc).isoformat(),
        reused=bool(reused_from_key),
        reused_from_key=reused_from_key,
        trust_context={
            "source_class": config.source_class,
            "source_context": config.allow_source_context,
            "enrichment": config.allow_enrichment,
            "llm": config.allow_llm,
            "delivery": config.allow_delivery,
        },
        timeline=timeline,
        devops=devops,
        test_impact=test_impact,
    )
    if config.redact:
        doc, output_hits = _redact_document(doc)
        doc["meta"]["redacted"] = doc["meta"]["redacted"] or output_hits > 0
    validate(doc)

    if write:
        write_json(doc, out)
        write_md(doc, out)
        # The ticket file must use the redacted document, not the pre-redaction
        # object retained for document construction above.
        write_ticket(_ticket_from_doc(doc), out)

    telemetry.increment("analysis_total")
    telemetry.observe("analysis_latency_ms", (time.perf_counter() - analysis_started) * 1000)
    telemetry.increment("unknown_total", 1 if artifacts.kind == "unknown" else 0)
    telemetry.increment("fallback_total", 1 if root_cause.engine == "fallback" else 0)
    telemetry.increment("redacted_runs_total", 1 if doc["meta"].get("redacted") else 0)
    telemetry.increment("dedup_hits_total", 1 if triage.is_duplicate_of else 0)
    telemetry.increment(
        "connector_errors_total",
        sum(1 for audit in artifacts.connector_audits if audit.get("status") != "collected"),
    )
    usage = doc["meta"].get("usage") or {}
    telemetry.increment("llm_tokens_total", float(usage.get("total_tokens") or 0))
    if write:
        output_bytes = sum(path.stat().st_size for path in out.glob("*.json") if path.is_file())
        telemetry.gauge("last_output_bytes", float(output_bytes))
    return doc


def _ticket_from_doc(doc: dict):
    from hound_agent.models import Ticket

    ticket = doc["ticket"]
    return Ticket(title=ticket["title"], body_md=ticket["body_md"], labels=ticket["labels"])


def _redact_document(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        hits = 0
        items = []
        for item in value:
            redacted, item_hits = _redact_document(item)
            items.append(redacted)
            hits += item_hits
        return items, hits
    if isinstance(value, dict):
        hits = 0
        mapping: dict = {}
        for key, item in value.items():
            redacted, item_hits = _redact_document(item)
            mapping[key] = redacted
            hits += item_hits
        return mapping, hits
    return value, 0


def _redact_artifacts(artifacts: Artifacts) -> int:
    """Redact every untrusted string before prompt construction or persistence."""
    hits = 0

    def scrub(value: str) -> str:
        nonlocal hits
        redacted_value, count = redact_text(value)
        hits += count
        return redacted_value

    def scrub_nested(value):
        if isinstance(value, str):
            return scrub(value)
        if isinstance(value, list):
            return [scrub_nested(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub_nested(item) for key, item in value.items()}
        return value

    artifacts.log_text = scrub(artifacts.log_text)
    artifacts.summary = scrub(artifacts.summary)
    artifacts.message = scrub(artifacts.message)
    artifacts.log_path = scrub(artifacts.log_path)
    for event in artifacts.events:
        for key, value in vars(event).items():
            if isinstance(value, str):
                setattr(event, key, scrub(value))

    for frame in artifacts.frames:
        frame.file = scrub(frame.file)
        frame.function = scrub(frame.function) if frame.function else None
        frame.code = scrub(frame.code)
    for test in artifacts.failed_tests:
        test.name = scrub(test.name)
        test.file = scrub(test.file)
        test.assertion = scrub(test.assertion)
    artifacts.enrichment = [scrub(item) for item in artifacts.enrichment]
    for audit in artifacts.connector_audits:
        for key, value in audit.items():
            if isinstance(value, str):
                audit[key] = scrub(value)
    for collection in (artifacts.metric_samples, artifacts.trace_spans):
        for item in collection:
            for key, value in item.items():
                if isinstance(value, str):
                    item[key] = scrub(value)
    artifacts.source_evidence = [scrub_nested(item) for item in artifacts.source_evidence]
    artifacts.git.branch = scrub(artifacts.git.branch) if artifacts.git.branch else None
    artifacts.git.head = scrub(artifacts.git.head)
    artifacts.git.changed_files = [scrub(path) for path in artifacts.git.changed_files]
    artifacts.git.owners = [scrub(owner) for owner in artifacts.git.owners]
    artifacts.git.correlated_commits = [scrub(commit) for commit in artifacts.git.correlated_commits]
    for context in (artifacts.run, artifacts.deployment, artifacts.request):
        for key, value in vars(context).items():
            if isinstance(value, str):
                setattr(context, key, scrub(value))
            elif isinstance(value, list):
                scrubbed = [scrub(item) for item in value if isinstance(item, str)]
                setattr(context, key, list(dict.fromkeys(scrubbed)))
    return hits
