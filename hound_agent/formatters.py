"""Pure output formatters for analysis documents."""
from __future__ import annotations

import json

from hound_agent.output.markdown import escape_code, escape_text
from hound_agent.service import AnalysisRun


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
        return "\n\n".join(_format_markdown_run(run) for run in runs)
    return "\n\n".join(_format_text_run(run) for run in runs)


def format_document(document: dict, output_format: str = "text") -> str:
    """Format one stored document without reconstructing analysis state."""
    if output_format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False)
    failure = document["failure"]
    root_cause = document["root_cause"]
    triage = document["triage"]
    if output_format == "markdown":
        return (
            f"# Hound Agent report\n\n"
            f"- **Severity:** {triage['severity']}\n"
            f"- **Failed step:** {failure['stage']} / {failure['kind']}\n"
            f"- **Confidence:** {root_cause['confidence']}\n\n"
            f"## Root cause\n\n{escape_text(root_cause['hypothesis'])}\n\n"
            f"## Recommended action\n\n{escape_text(root_cause['fix_suggestion'])}"
        )
    return _format_fields(document)


def _format_text_run(run: AnalysisRun) -> str:
    return f"run: {run.run_id}\n{_format_fields(run.document)}"


def _format_fields(document: dict) -> str:
    failure = document["failure"]
    root_cause = document["root_cause"]
    triage = document["triage"]
    return "\n".join(
        [
            f"severity: {triage['severity']}",
            f"root cause: {root_cause['hypothesis']}",
            f"failed step: {failure['stage']} / {failure['kind']}",
            f"confidence: {root_cause['confidence']}",
            f"recommended action: {root_cause['fix_suggestion']}",
        ]
    )


def _format_markdown_run(run: AnalysisRun) -> str:
    return f"# Run `{escape_code(run.run_id)}`\n\n{format_document(run.document, 'markdown')}"
