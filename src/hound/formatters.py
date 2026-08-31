"""Pure output formatters for analysis documents."""
from __future__ import annotations

import json

from hound.output.markdown import escape_code, escape_text, sanitize_text
from hound.models import validate
from hound.service import AnalysisRun


def format_runs(runs: list[AnalysisRun], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "count": len(runs),
                "runs": [
                    {
                        "run_id": run.run_id,
                        "log_file": run.document["meta"]["log_file"],
                        "report": str(run.output_dir / "report.json"),
                        "analysis": run.document,
                    }
                    for run in runs
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    if output_format == "markdown":
        return sanitize_text("\n\n".join(_format_markdown_run(run) for run in runs))
    return sanitize_text("\n\n".join(_format_text_run(run) for run in runs))


def format_document(document: dict, output_format: str = "text") -> str:
    """Format one stored document without reconstructing analysis state."""
    validate(document)
    if output_format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False)
    failure = document["failure"]
    root_cause = document["root_cause"]
    triage = document["triage"]
    request = _request_summary(document)
    hypothesis = _hypothesis(document)
    if output_format == "markdown":
        lines = [
            "# Hound report",
            "",
            f"- **Severity:** {triage['severity']}",
            f"- **Failed step:** {failure['stage']} / {failure['kind']}",
            f"- **Confidence:** {root_cause['confidence']}",
        ]
        if hypothesis:
            lines += [
                f"- **Support:** {hypothesis['support_status']}",
                f"- **Evidence refs:** {', '.join(hypothesis['supporting_evidence_refs']) or '(none)'}",
            ]
        if request:
            lines.append(f"- **Request:** {escape_text(request)}")
        lines += [
            "",
            "## Root cause",
            "",
            escape_text(root_cause["hypothesis"]),
            "",
            "## Recommended action",
            "",
            escape_text(root_cause["fix_suggestion"]),
        ]
        return sanitize_text("\n".join(lines))
    return sanitize_text(_format_fields(document, request))


def _format_text_run(run: AnalysisRun) -> str:
    return f"run: {run.run_id}\n{_format_fields(run.document)}"


def _request_summary(document: dict) -> str:
    context = document.get("context")
    request = context.get("request") if isinstance(context, dict) else None
    if not isinstance(request, dict):
        return ""
    fields = []
    for key in ("request_id", "trace_id", "session_id", "user_id", "method", "path"):
        value = request.get(key)
        if value:
            fields.append(f"{key}={value}")
    users = request.get("users")
    if isinstance(users, list) and users:
        fields.append(f"users={','.join(str(user) for user in users)}")
    return " ".join(fields)


def _format_fields(document: dict, request: str | None = None) -> str:
    failure = document["failure"]
    root_cause = document["root_cause"]
    triage = document["triage"]
    fields = [
        f"severity: {triage['severity']}",
        f"root cause: {root_cause['hypothesis']}",
        f"failed step: {failure['stage']} / {failure['kind']}",
        f"confidence: {root_cause['confidence']}",
    ]
    hypothesis = _hypothesis(document)
    if hypothesis:
        fields.append(f"support: {hypothesis['support_status']}")
        fields.append(f"evidence refs: {','.join(hypothesis['supporting_evidence_refs']) or '(none)'}")
    if request:
        fields.append(f"request: {request}")
    fields.append(f"recommended action: {root_cause['fix_suggestion']}")
    return "\n".join(fields)


def _hypothesis(document: dict) -> dict | None:
    analysis = document.get("analysis")
    hypotheses = analysis.get("hypotheses") if isinstance(analysis, dict) else None
    if isinstance(hypotheses, list) and hypotheses and isinstance(hypotheses[0], dict):
        return hypotheses[0]
    return None


def _format_markdown_run(run: AnalysisRun) -> str:
    return f"# Run `{escape_code(run.run_id)}`\n\n{format_document(run.document, 'markdown')}"
