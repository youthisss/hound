from __future__ import annotations

import json
from pathlib import Path
import pytest

from hound.analyze.fallback import build_root_cause
from hound.feedback import default_feedback_store, record_feedback
from hound.models import Triage, build_doc
from hound.output.report import ensure_outdir
from hound.output.tickets import build_ticket
from hound.validation import (
    default_validation_store,
    format_validation_markdown,
    get_latest_validation,
    count_validations,
    validate_report,
)
from tests.conftest import make_artifacts


def _make_valid_report(out_dir: Path, run_id: str = "run-001") -> Path:
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    triage = Triage(severity="medium", component="tests", dedup_key="a" * 64)
    ticket = build_ticket(artifacts, root_cause, triage)
    document = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z")
    ensure_outdir(out_dir)
    run_dir = ensure_outdir(out_dir / run_id)
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return report_path


def test_validate_valid_v2_report(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-001")

    record = validate_report(report_path, output_root=out)
    assert record.status in {"PASS", "WARN"}
    assert record.run_id == "run-001"
    assert record.schema_version == "2.0"
    assert len(record.report_sha256) == 64
    assert not record.is_stale(report_path)

    # Check store persistence
    store = default_validation_store(out)
    assert store.is_file()
    latest = get_latest_validation(store, "run-001")
    assert latest is not None
    assert latest.validation_id == record.validation_id
    assert latest.status == record.status

    counts = count_validations(store)
    assert counts["total"] == 1

    markdown = format_validation_markdown(record)
    assert "Report Validation Summary" in markdown
    assert record.run_id in markdown


def test_validate_detects_staleness(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-002")

    record = validate_report(report_path, output_root=out)
    assert not record.is_stale(report_path)

    # Modify the report file
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["failure"]["summary"] = "Tampered summary after validation"
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert record.is_stale(report_path)


def test_validate_fork_pr_fail_closed_violation(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-003")

    # Inject trust violation: source_class is fork_pr, but llm was marked True
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["meta"]["trust"] = {
        "source_class": "fork_pr",
        "source_context": False,
        "enrichment": False,
        "llm": True,  # VIOLATION: fork_pr must not allow LLM
        "delivery": False,
    }
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    record = validate_report(report_path, output_root=out)
    assert record.status == "FAIL"
    trust_checks = [c for c in record.checks if c.name == "trust_profile"]
    assert len(trust_checks) == 1
    assert trust_checks[0].status == "FAIL"
    assert "Trust policy violation" in trust_checks[0].message


def test_validate_credential_leak_in_connector(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-004")

    # Inject unredacted sensitive token into connector audit
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["context"]["connector_audits"] = [
        {
            "command": "kubectl get secret",
            "output": "Bearer ya29.a0AfH6SMAexampleunredactedtoken1234567890",
        }
    ]
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    record = validate_report(report_path, output_root=out)
    assert record.status == "FAIL"
    hygiene_checks = [c for c in record.checks if c.name == "connector_hygiene"]
    assert len(hygiene_checks) == 1
    assert hygiene_checks[0].status == "FAIL"
    assert "credentials" in hygiene_checks[0].message.lower()


def test_validate_timeline_cycles_emits_warn(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-005")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    timeline = data.setdefault("timeline", {})
    timeline["has_cycles"] = True
    timeline["cycle_warning"] = "Loop between span-1 and span-2"
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    record = validate_report(report_path, output_root=out)
    assert record.status in {"WARN", "FAIL"}
    timeline_checks = [c for c in record.checks if c.name == "timeline_causality"]
    assert len(timeline_checks) == 1
    assert timeline_checks[0].status == "WARN"
    assert "cycle" in timeline_checks[0].message.lower()


def test_feedback_blocks_reviewed_status_on_failing_report(tmp_path):
    out = tmp_path / "out"
    report_path = _make_valid_report(out, "run-006")

    # Create report with trust policy violation (valid schema, but fails validation audit)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["meta"]["trust"] = {
        "source_class": "fork_pr",
        "source_context": False,
        "enrichment": False,
        "llm": True,  # Trust violation
        "delivery": False,
    }
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    fb_store = default_feedback_store(out)

    # Attempting to save as 'reviewed' should be blocked by fail-closed gate
    with pytest.raises(ValueError, match="cannot mark feedback as 'reviewed' for invalid report"):
        record_feedback(
            fb_store,
            report_path,
            "run-006",
            review_status="reviewed",
            usefulness="useful",
        )

    # But saving as 'pending' or 'rejected' is permitted for audit recording
    pending_record = record_feedback(
        fb_store,
        report_path,
        "run-006",
        review_status="pending",
        usefulness="useful",
    )
    assert pending_record["review_status"] == "pending"
