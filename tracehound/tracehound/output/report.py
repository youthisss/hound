"""Write report.json and report.md into an output directory."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tracehound.output.markdown import escape_code, escape_text

OUTPUT_MARKER = ".tracehound-owned"
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


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def write_json(doc: dict, outdir: str | Path) -> Path:
    path = ensure_outdir(outdir) / "report.json"
    _atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False))
    return path


def write_md(doc: dict, outdir: str | Path) -> Path:
    path = ensure_outdir(outdir) / "report.md"
    f = doc["failure"]
    rc = doc["root_cause"]
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
    if any(run.values()):
        lines += ["", "## CI context"]
        for key in ("provider", "run_id", "run_url", "job_name", "step_name", "attempt", "conclusion", "pr_number", "base_sha", "head_sha"):
            if run[key] is not None and run[key] != "":
                lines.append(f"- **{key.replace('_', ' ').title()}**: {escape_text(str(run[key]))}")
    if any(deployment.values()):
        lines += ["", "## Deployment context"]
        for key, value in deployment.items():
            if value:
                lines.append(f"- **{key.title()}**: {escape_text(value)}")
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
        "## Root cause",
        f"- **Hypothesis**: {escape_text(rc['hypothesis'])}",
        f"- **Confidence**: {rc['confidence']}",
        "",
        "### Evidence",
    ]
    if rc["evidence"]:
        for ev in rc["evidence"]:
            lines.append(f"- {escape_text(ev)}")
    else:
        lines.append("- (none)")
    lines += ["", f"**Fix suggestion**: {escape_text(rc['fix_suggestion'])}", ""]

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

    _atomic_write(path, "\n".join(lines))
    return path
