from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from hound_agent.analyze.fallback import build_root_cause
from hound_agent.cli import main
from hound_agent.feedback import default_feedback_store, export_feedback, read_feedback
from hound_agent.models import Triage, build_doc
from hound_agent.output.report import ensure_outdir
from hound_agent.output.tickets import build_ticket
from tests.conftest import make_artifacts


def _stored_report(root: Path, run_id: str = "run-001") -> Path:
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    triage = Triage(severity="medium", component="tests", dedup_key="a" * 64)
    ticket = build_ticket(artifacts, root_cause, triage)
    document = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z")
    ensure_outdir(root)
    report = ensure_outdir(root / run_id) / "report.json"
    report.write_text(json.dumps(document), encoding="utf-8")
    return report


def test_feedback_cli_records_and_exports_reviewed_candidate(tmp_path, capsys):
    out = tmp_path / "out"
    report = _stored_report(out)
    before = hashlib.sha256(report.read_bytes()).hexdigest()
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"

    assert main([
        "feedback", "record", "--out", str(out), "--run-id", "run-001",
        "--usefulness", "useful", "--kind-correct", "correct",
        "--severity-correct", "incorrect", "--owner-correct", "correct",
        "--duplicate-correct", "correct", "--actual-kind", "test_failure",
        "--actual-severity", "high", "--actual-owner", secret,
        "--actual-outcome", "root_cause_confirmed", "--review-status", "reviewed",
        "--reviewer", secret,
    ]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["run_id"] == "run-001"
    assert secret not in json.dumps(record)
    assert record["actual_owner"].startswith("[REDACTED:")
    assert hashlib.sha256(report.read_bytes()).hexdigest() == before

    store = default_feedback_store(out)
    assert store.is_file()
    assert store.name == "feedback.sqlite3"
    assert not (store.parent / "state.sqlite3").exists()
    with sqlite3.connect(store) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"feedback"}

    assert main([
        "feedback", "export", "--out", str(out), "--candidate-fixtures"
    ]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["count"] == 1
    assert exported["candidates"][0]["source"]["run_id"] == "run-001"
    assert exported["candidates"][0]["requires_manual_sanitized_artifact"] is True
    assert "hypothesis" not in json.dumps(exported)
    assert secret not in json.dumps(exported)
    assert secret.encode() not in store.read_bytes()


def test_candidate_export_excludes_pending_feedback(tmp_path, capsys):
    out = tmp_path / "out"
    _stored_report(out)
    assert main(["feedback", "record", "--out", str(out), "--run-id", "run-001"]) == 0
    capsys.readouterr()

    payload = export_feedback(default_feedback_store(out), candidates=True)
    assert payload == {"candidate_export_version": "1.0", "count": 0, "candidates": []}
    assert len(read_feedback(default_feedback_store(out))) == 1


def test_feedback_rejects_run_traversal(tmp_path, capsys):
    assert main([
        "feedback", "record", "--out", str(tmp_path), "--run-id", "../outside"
    ]) == 2
    assert "single directory name" in capsys.readouterr().err


def test_feedback_help_is_available():
    with pytest.raises(SystemExit) as exc:
        main(["feedback", "--help"])
    assert exc.value.code == 0


def test_feedback_store_remains_cleanable_owned_state(tmp_path, capsys):
    out = tmp_path / "out"
    _stored_report(out)
    assert main(["feedback", "record", "--out", str(out), "--run-id", "run-001"]) == 0
    capsys.readouterr()
    assert main(["clean", "--out", str(out), "--yes"]) == 0
    assert not out.exists()
