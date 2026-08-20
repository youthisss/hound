"""Core analysis pipeline. Single entry point for CLI and TUI."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tracehound.analyze.rca import run_analysis
from tracehound.config import Config, load_config
from tracehound.ingest.context import load_context
from tracehound.ingest.enrich import collect_deployment_evidence
from tracehound.ingest.git import gather
from tracehound.ingest.logs import extract_events, parse_log, read_log_window
from tracehound.ingest.owners import resolve_owners
from tracehound.ingest.redact import redact_text
from tracehound.ingest.structured import parse_structured_artifact
from tracehound.ingest.stacktrace import attach_snippets, dedupe_repo_paths, parse_stacktrace
from tracehound.ingest.tests import parse_failed_tests
from tracehound.models import Artifacts, build_doc, validate
from tracehound.output.report import ensure_outdir, write_json, write_md
from tracehound.output.tickets import build_ticket, write_ticket
from tracehound.triage.component import assign
from tracehound.triage.dedup import check_duplicate, record_triage
from tracehound.triage.severity import classify


def default_state_path(out: Path, config_state: str | None, no_dedup: bool) -> str | None:
    if no_dedup:
        return None
    if config_state:
        return str(Path(config_state).resolve())
    state_dir = out / ".tracehound"
    state_file = state_dir / "state.json"
    # A checked-out output directory is attacker-controlled in CI. Never let
    # the default state location follow a pre-seeded symlink outside `out`.
    if state_dir.is_symlink() or state_file.is_symlink():
        raise ValueError("refusing symlinked default dedup state path")
    return str(state_file.resolve())


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
    source_context: bool = False,
    context_path: str | None = None,
    enrich: bool = False,
    _config: Config | None = None,
) -> dict:
    """Run the full pipeline for one log. Returns the validated RCA document."""
    log_path = Path(log_path)
    if log_path.is_symlink() or not log_path.is_file():
        raise FileNotFoundError(f"log file not found: {log_path}")
    out = ensure_outdir(out_dir)

    config = _config or load_config(
        offline=offline,
        config_path=config_path,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        redact=redact,
        max_retries=max_retries,
    )
    if config.state_backend not in {"", "file"}:
        raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")
    text = read_log_window(log_path)

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
    run, deployment = load_context(log_path, text, context_path)
    # Log-derived deployment names are untrusted. Enrichment requires an
    # operator-supplied context file, which establishes the query boundary.
    enrichment = collect_deployment_evidence(deployment) if enrich and context_path and stage == "deploy" else []
    if enrichment:
        text = text + "\n\n--- read-only deployment evidence ---\n" + "\n\n".join(enrichment)
    frames = parse_stacktrace(text)
    git = gather(str(repo_dir) if repo_dir else None, run.base_sha, run.head_sha)
    if repo_dir:
        git.owners = resolve_owners(repo_dir, [frame.file for frame in frames] + git.changed_files)
        frames = dedupe_repo_paths(frames, str(repo_dir))
    if repo_dir and source_context:
        frames = attach_snippets(frames, str(repo_dir))
        if config.redact:
            for frame in frames:
                if frame.code:
                    frame.code, snippet_hits = redact_text(frame.code)
                    redacted = redacted or snippet_hits > 0

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
        events=extract_events(text, stage, kind, message),
        enrichment=enrichment,
        log_path=str(log_path.resolve()),
        redacted=redacted,
    )
    if config.redact:
        artifact_hits = _redact_artifacts(artifacts)
        artifacts.redacted = artifacts.redacted or artifact_hits > 0

    root_cause = run_analysis(artifacts, config)

    severity, priority = classify(artifacts)
    environment_overrides = config.severity_overrides.get(artifacts.deployment.environment, {})
    if override := environment_overrides.get(artifacts.kind):
        if override in {"critical", "high", "medium", "low"}:
            severity = override
            priority = {"critical": 1, "high": 2, "medium": 3, "low": 4}[severity]
    component = assign(artifacts, config.components)
    if state_path is None:
        state_path = default_state_path(out, config.state_file, no_dedup)
    triage = check_duplicate(artifacts, root_cause, state_path, config.recurrence_threshold)
    triage.severity = severity
    triage.priority = priority
    triage.component = component
    # Flakiness is evidence from a test retry, not a synonym for recurrence.
    triage.flaky_suspect = artifacts.kind == "flaky"
    if triage.flaky_suspect:
        triage.priority = 5

    ticket = build_ticket(artifacts, root_cause, triage)
    record_triage(state_path, triage, component, ticket.title)

    doc = build_doc(
        artifacts,
        root_cause,
        triage,
        ticket,
        generated_at=datetime.now(timezone.utc).isoformat(),
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
    return doc


def _ticket_from_doc(doc: dict):
    from tracehound.models import Ticket

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
        items = {}
        for key, item in value.items():
            redacted, item_hits = _redact_document(item)
            items[key] = redacted
            hits += item_hits
        return items, hits
    return value, 0


def _redact_artifacts(artifacts: Artifacts) -> int:
    """Redact every untrusted string before prompt construction or persistence."""
    hits = 0

    def scrub(value: str) -> str:
        nonlocal hits
        redacted_value, count = redact_text(value)
        hits += count
        return redacted_value

    artifacts.log_text = scrub(artifacts.log_text)
    artifacts.summary = scrub(artifacts.summary)
    artifacts.message = scrub(artifacts.message)
    artifacts.log_path = scrub(artifacts.log_path)
    for frame in artifacts.frames:
        frame.file = scrub(frame.file)
        frame.function = scrub(frame.function) if frame.function else None
        frame.code = scrub(frame.code)
    for test in artifacts.failed_tests:
        test.name = scrub(test.name)
        test.file = scrub(test.file)
        test.assertion = scrub(test.assertion)
    artifacts.enrichment = [scrub(item) for item in artifacts.enrichment]
    artifacts.git.branch = scrub(artifacts.git.branch) if artifacts.git.branch else None
    artifacts.git.head = scrub(artifacts.git.head)
    artifacts.git.changed_files = [scrub(path) for path in artifacts.git.changed_files]
    artifacts.git.owners = [scrub(owner) for owner in artifacts.git.owners]
    for context in (artifacts.run, artifacts.deployment):
        for key, value in vars(context).items():
            if isinstance(value, str):
                setattr(context, key, scrub(value))
    return hits
