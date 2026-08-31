"""Write report.json and report.md into an output directory."""
from __future__ import annotations

import json
from pathlib import Path

from hound_agent.fsio import atomic_write as _atomic_write  # noqa: F401 (back-compat alias)
from hound_agent.output.markdown import escape_code, escape_text, sanitize_text

OUTPUT_MARKER = ".hound-agent-owned"
OUTPUT_MARKER_CONTENT = "Hound Agent managed output directory\n"


def ensure_outdir(outdir: str | Path) -> Path:
    p = Path(outdir)
    if p.is_symlink():
        raise ValueError(f"output path must not be a symlink: {p}")
    if p.exists() and not p.is_dir():
        raise ValueError(f"output path is not a directory: {p}")
    marker = p / OUTPUT_MARKER
    if p.exists():
        marker_present = marker.exists() or marker.is_symlink()
        if marker_present:
            try:
                valid_marker = not marker.is_symlink() and marker.read_text(encoding="utf-8") == OUTPUT_MARKER_CONTENT
            except OSError:
                valid_marker = False
            if not valid_marker:
                raise ValueError(f"invalid output ownership marker: {marker}")
        elif any(p.iterdir()):
            raise ValueError(f"refusing to use non-empty unowned output directory: {p}")
    p.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        _atomic_write(marker, OUTPUT_MARKER_CONTENT)
    return p


def write_json(doc: dict, outdir: str | Path) -> Path:
    path = ensure_outdir(outdir) / "report.json"
    _atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False))
    return path


def render_md(doc: dict) -> str:
    """Render the canonical Markdown report from a report document."""
    f = doc["failure"]
    rc = doc["root_cause"]
    analysis = doc.get("analysis") if isinstance(doc.get("analysis"), dict) else None
    hypothesis = analysis["hypotheses"][0] if analysis and analysis.get("hypotheses") else None
    tr = doc["triage"]
    t = doc["ticket"]

    lines = [
        "# RCA Report",
        "",
        f"- **Engine**: {doc['meta']['engine']}" + (f" ({doc['meta']['model']})" if doc["meta"]["model"] else ""),
        f"- **Log**: {escape_text(doc['meta']['log_file'])}",
        f"- **Generated**: {doc['meta']['generated_at']}",
    ]
    if doc["meta"].get("redacted"):
        lines.append("- **Redacted**: secrets/PII scrubbed from log (default on)")
    usage = doc["meta"].get("usage") or {}
    if usage.get("total_tokens"):
        lines.append(
            f"- **Usage**: {usage.get('prompt_tokens', 0)} prompt / "
            f"{usage.get('completion_tokens', 0)} completion tokens"
        )
    lines.append("")
    lines += [
        "## Failure",
        f"- **Stage**: {f['stage']}",
        f"- **Kind**: {f['kind']}",
        f"- **Summary**: {escape_text(f['summary'])}",
        "",
        "## Root cause",
        f"- **Hypothesis**: {escape_text(rc['hypothesis'])}",
        f"- **Confidence**: {rc['confidence']}",
        *(
            [
                f"- **Evidence score**: {hypothesis['confidence']['score']:.2f}",
                f"- **Support status**: {hypothesis['support_status']}",
                f"- **Evidence refs**: {', '.join(hypothesis['supporting_evidence_refs']) or '(none)'}",
            ]
            if hypothesis else []
        ),
        f"- **Fix suggestion**: {escape_text(rc['fix_suggestion'])}",
        "",
        "### Evidence",
    ]
    if hypothesis:
        assert analysis is not None
        evidence_by_id = {item["id"]: item for item in analysis["evidence"]}
        for ref in hypothesis["supporting_evidence_refs"]:
            item = evidence_by_id[ref]
            lines.append(f"- `{ref}` **{escape_text(item['kind'])}**: {escape_text(item['value'])}")
        if not hypothesis["supporting_evidence_refs"]:
            lines.append(f"- ({hypothesis['support_status']})")
        if hypothesis["missing_information"]:
            lines += ["", "### Missing information"]
            lines += [f"- {escape_text(value)}" for value in hypothesis["missing_information"]]
        if hypothesis["recommended_checks"]:
            lines += ["", "### Recommended checks"]
            lines += [f"- {escape_text(value)}" for value in hypothesis["recommended_checks"]]
    elif rc["evidence"]:
        for ev in rc["evidence"]:
            lines.append(f"- {escape_text(ev)}")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Technical details",
        "",
        "### Message",
        "```",
        f["message"].replace("```", "'''") if f.get("message") else "",
        "```",
        "",
        "### Stacktrace",
    ]
    context = doc["context"]
    run = context["run"]
    deployment = context["deployment"]
    request = context.get("request", {})
    if any(run.values()):
        lines += ["", "## CI context"]
        for key in ("provider", "run_id", "run_url", "job_name", "step_name", "attempt", "conclusion", "pr_number", "base_sha", "head_sha"):
            if run[key] is not None and run[key] != "":
                lines.append(f"- **{key.replace('_', ' ').title()}**: {escape_text(str(run[key]))}")
    if any(deployment.values()):
        lines += ["", "## Deployment context"]
        # M7: render outcome, recovery, and customer-impact status separately so
        # operators can distinguish deployment success from recovery from impact.
        separated = ("outcome", "recovery", "customer_impact")
        for key, value in deployment.items():
            if value and key not in separated:
                lines.append(f"- **{key.title()}**: {escape_text(value)}")
        for key in separated:
            if deployment.get(key):
                lines.append(f"- **{key.title()}**: {escape_text(deployment[key])}")
    connector_audits = context.get("connector_audits", [])
    if isinstance(connector_audits, list) and connector_audits:
        lines += ["", "## Connector audit"]
        for audit in connector_audits:
            if not isinstance(audit, dict):
                continue
            target = audit.get("resource") or "(none)"
            namespace = f" namespace={audit['namespace']}" if audit.get("namespace") else ""
            lines.append(
                f"- **{escape_text(str(audit.get('connector') or 'connector'))} / "
                f"{escape_text(str(audit.get('operation') or 'operation'))}**: "
                f"{escape_text(str(audit.get('status') or 'unknown'))} "
                f"resource={escape_text(str(target))}{escape_text(namespace)} "
                f"({audit.get('duration_ms', 0)} ms, {audit.get('output_bytes', 0)} bytes)"
            )
            if audit.get("error"):
                lines.append(f"  - **Error**: {escape_text(str(audit['error']))}")
    source_evidence = context.get("source_evidence", [])
    if isinstance(source_evidence, list) and source_evidence:
        lines += ["", "## Bounded source context"]
        for source in source_evidence:
            if not isinstance(source, dict):
                continue
            raw_symbol = source.get("symbol")
            symbol = raw_symbol if isinstance(raw_symbol, dict) else {}
            name = symbol.get("name") or "(text fallback)"
            lines.append(
                f"- **{escape_text(str(source.get('file') or 'file'))}:{source.get('line', 0)}** "
                f"symbol={escape_text(str(name))} changed={source.get('changed', False)}"
            )
            if source.get("owners"):
                lines.append(f"  - **Owners**: {', '.join(escape_text(str(owner)) for owner in source['owners'])}")
            if source.get("commit"):
                lines.append(f"  - **Commit**: {escape_text(str(source['commit']))}")
            if source.get("related_tests"):
                lines.append(f"  - **Related tests**: {', '.join(escape_text(str(test)) for test in source['related_tests'])}")
            lines.append(f"  - **Uncertainty**: {escape_text(str(source.get('uncertainty') or ''))}")
    if isinstance(request, dict) and any(request.values()):
        lines += ["", "## Request context"]
        for key in ("request_id", "trace_id", "session_id", "user_id", "users", "method", "path"):
            value = request.get(key)
            if isinstance(value, list):
                value = ", ".join(value)
            if value:
                lines.append(f"- **{key.replace('_', ' ').title()}**: {escape_text(str(value))}")
    devops = doc.get("devops") if isinstance(doc.get("devops"), dict) else None
    if devops:
        lines += ["", "## Operational correlation"]
        lines.append(f"- **Static severity**: {escape_text(devops.get('static_severity') or '')}")
        lines.append(f"- **Effective severity**: {escape_text(devops.get('effective_severity') or '')}")
        for reason in devops.get("severity_reasons") or []:
            lines.append(f"- **Severity evidence**: {escape_text(str(reason))}")
        release_changes = devops.get("release_changes") or []
        if release_changes:
            lines.append("- **Release comparison**:")
            for change in release_changes:
                lines.append(
                    f"  - {escape_text(str(change.get('field') or 'field'))}: "
                    f"{escape_text(str(change.get('status') or 'unknown'))} "
                    f"({escape_text(str(change.get('previous') or '(missing)'))} -> "
                    f"{escape_text(str(change.get('current') or '(missing)'))})"
                )
        lines.append(f"- **Metric samples**: {len(devops.get('metric_samples') or [])}")
        lines.append(f"- **Trace spans**: {len(devops.get('trace_spans') or [])}")
        critical = devops.get("critical_path") or {}
        if critical.get("span_ids"):
            lines.append(
                f"- **Estimated critical path**: {' -> '.join(escape_text(str(value)) for value in critical['span_ids'])} "
                f"({critical.get('duration_ns', 0)} ns)"
            )
        slo = devops.get("slo") or {}
        if slo.get("target") or slo.get("error_budget_remaining") is not None:
            lines.append(
                f"- **SLO / error budget**: target={escape_text(str(slo.get('target') or '(missing)'))}, "
                f"remaining={escape_text(str(slo.get('error_budget_remaining')))}"
            )
        runbook = devops.get("runbook") or {}
        if runbook.get("url"):
            lines.append(f"- **Runbook**: {escape_text(str(runbook['url']))}")
    test_impact = doc.get("test_impact") if isinstance(doc.get("test_impact"), dict) else None
    if test_impact:
        lines += ["", "## Test impact recommendations"]
        lines.append("- **Mode**: advisory; CI test execution is unchanged")
        lines.append(f"- **Language**: {escape_text(str(test_impact.get('language') or ''))}")
        lines.append(f"- **Missing coverage**: {test_impact.get('missing_coverage', True)}")
        lines.append(f"- **Uncertainty**: {escape_text(str(test_impact.get('uncertainty') or ''))}")
        for recommendation in test_impact.get("recommendations") or []:
            lines.append(
                f"- `{escape_code(str(recommendation.get('test') or ''))}` "
                f"score={recommendation.get('score', 0)}: "
                f"{'; '.join(escape_text(str(reason)) for reason in recommendation.get('reasons') or [])}"
            )
    timeline = doc.get("timeline") if isinstance(doc.get("timeline"), dict) else None
    if timeline:
        lines += ["", "## Timeline"]
        entries = timeline.get("entries") if isinstance(timeline.get("entries"), list) else []
        if timeline.get("grouping"):
            lines.append(f"- **Grouping**: {escape_text(timeline['grouping'])}")
        if timeline.get("ordering_basis"):
            lines.append(f"- **Ordering basis**: {escape_text(timeline['ordering_basis'])}")
        if timeline.get("has_cycles"):
            lines.append(f"- **Cycle warning**: {escape_text(timeline.get('cycle_warning') or '')}")
        if timeline.get("customer_impact"):
            lines.append(f"- **Customer impact**: {escape_text(timeline['customer_impact'])}")
        if timeline.get("release_changed") is not None:
            fields = ", ".join(timeline.get("release_changed_fields") or [])
            lines.append(f"- **Release changed**: {timeline['release_changed']}" + (f" ({fields})" if fields else ""))
        if timeline.get("primary_event_id"):
            lines.append(f"- **Primary**: `{escape_text(timeline['primary_event_id'])}`")
        downstream = timeline.get("downstream_event_ids") or []
        if downstream:
            lines.append(f"- **Downstream symptoms**: {', '.join(escape_text(i) for i in downstream)}")
        recovery = timeline.get("recovery_event_ids") or []
        if recovery:
            lines.append(f"- **Recovery**: {', '.join(escape_text(i) for i in recovery)}")
        if not timeline.get("primary_event_id") and not downstream:
            lines.append("- (no failure events observed)")
        for entry in entries:
            loc = f"`{escape_code(entry['event_id'])}`"
            when = ""
            if entry.get("timestamp"):
                when = f" at {escape_text(entry['timestamp'])}"
            elif entry.get("timestamp_ns") is not None:
                when = f" at ns={entry['timestamp_ns']}"
            elif entry.get("sequence") is not None:
                when = f" (seq {entry['sequence']})"
            label = entry.get("role", "").title() if entry.get("role") not in {"unknown", ""} else "Event"
            lines.append(f"- {loc} **{label}**: {escape_text(entry.get('message') or '')}{when}")
            if entry.get("trace_id"):
                lines.append(f"  - **trace_id**: `{escape_text(entry['trace_id'])}`")
            if entry.get("span_id"):
                lines.append(f"  - **span_id**: `{escape_text(entry['span_id'])}`")
            if entry.get("parent_span_id"):
                lines.append(f"  - **parent_span_id**: `{escape_text(entry['parent_span_id'])}`")
            if entry.get("uncertainty"):
                lines.append(f"  - **uncertainty**: {escape_text(entry['uncertainty'])}")
    if context["owners"]:
        lines += ["", "## Ownership", f"- **CODEOWNERS**: {', '.join(escape_text(owner) for owner in context['owners'])}"]
    if f["stacktrace"]:
        for frame in f["stacktrace"]:
            loc = f"{escape_code(frame['file'])}:{frame['line']}"
            if frame.get("function"):
                loc += f" ({escape_code(frame['function'])})"
            lines.append(f"- `{loc}`")
            if frame.get("code"):
                lines.append("  ```")
                lines.extend("  " + line.replace("```", "'''") for line in frame["code"].splitlines())
                lines.append("  ```")
    else:
        lines.append("- (none)")
    lines.append("")

    if f["failed_tests"]:
        lines.append("### Failed tests")
        for tst in f["failed_tests"]:
            lines.append(f"- `{escape_code(tst['name'])}`" + (f" - {escape_text(tst['assertion'])}" if tst["assertion"] else ""))
        lines.append("")

    lines += [
        "## Triage",
        f"- **Severity**: {tr['severity']}",
        f"- **Component**: {escape_text(tr['component'])}",
        f"- **Priority**: {tr['priority']}",
        f"- **Dedup key**: `{tr['dedup_key']}`",
    ]
    if tr["is_duplicate_of"]:
        lines.append(f"- **Duplicate of**: `{tr['is_duplicate_of']}`")
    if tr["flaky_suspect"]:
        lines.append("- **Flaky test**: a failed test was followed by a passing retry")
    if tr["recurring_incident"]:
        lines.append(f"- **Recurring incident**: {tr['occurrence_count']} occurrences")
    lines += ["", "## Ticket draft", f"### {escape_text(t['title'])}", ""]
    for ln in t["body_md"].splitlines():
        lines.append(f"> {ln}" if ln else ">")
    lines.append("")

    return sanitize_text("\n".join(lines))


def write_md(doc: dict, outdir: str | Path) -> Path:
    path = ensure_outdir(outdir) / "report.md"
    _atomic_write(path, render_md(doc))
    return path
