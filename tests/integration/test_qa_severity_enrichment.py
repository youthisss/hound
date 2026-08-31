from __future__ import annotations

import json
from pathlib import Path

from hound.qa.classifier import QAClassification, classify_test_result
from hound.qa.gate import evaluate_gate
from hound.qa.model import NormalizedTestResult, now_iso
from hound.feedback import record_feedback


def test_qa_classifier_attaches_codeowners_and_related_incidents(tmp_path: Path):
    # Setup CODEOWNERS in repo
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CODEOWNERS").write_text("tests/test_auth.py @security-team\n", encoding="utf-8")

    # Setup Feedback DB with reviewed incident
    out = tmp_path / "out"
    fb_store = out / ".hound" / "feedback.sqlite3"
    report_dir = out / "run-1"
    report_dir.mkdir(parents=True)
    report_file = report_dir / "report.json"
    golden = json.loads(Path("tests/golden/rca-v2.0.json").read_text(encoding="utf-8"))
    golden["triage"]["dedup_key"] = "auth-sig-123"
    golden["triage"]["severity"] = "critical"
    golden["triage"]["component"] = "auth"
    golden["failure"]["kind"] = "test_failure"
    golden["context"]["owners"] = ["@security-team"]
    report_file.write_text(json.dumps(golden), encoding="utf-8")

    record_feedback(
        fb_store,
        report_file,
        "run-1",
        usefulness="useful",
        actual_severity="critical",
        actual_owner="alice",
        actual_outcome="root_cause_confirmed",
        review_status="reviewed",
    )

    cand = NormalizedTestResult(
        suite="tests/test_auth.py",
        test="test_login",
        status="failed",
        attempt=1,
        duration_ms=120,
        runner="pytest",
        commit="head1",
        branch="feat",
        environment="linux",
        run_id="run-2",
        recorded_at=now_iso(),
        failure_signature="auth-sig-123",
    )

    res = classify_test_result(
        store_path=None,
        candidate=cand,
        repo_dir=repo,
        feedback_store_path=fb_store,
    )

    assert res.owners == ["@security-team"]
    assert len(res.related_incidents) == 1
    assert res.related_incidents[0]["actual_severity"] == "critical"
    assert res.related_incidents[0]["actual_owner"] == "alice"


def test_gate_policy_evaluates_severity_rules(tmp_path: Path):
    policy = {
        "version": "1.0",
        "rules": {
            "critical_severity": "block",
            "high_severity": "warn",
        },
        "environments": {},
    }

    cls_crit = QAClassification(
        suite="tests/test_auth.py",
        test="test_login",
        decision="likely_regression",
        confidence="high",
        reason="regression",
        candidate_status="failed",
        sample_count=10,
        historical_failure_rate=0.0,
        related_incidents=[{"actual_severity": "critical", "run_id": "run-1"}],
    )

    res = evaluate_gate(policy, [cls_crit], None, None, None)
    assert res.policy_outcome == "block"
    assert any(r.rule == "critical_severity" for r in res.reasons)
