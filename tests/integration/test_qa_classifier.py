"""Tests for QA Milestone 5: Flaky and regression intelligence."""
from __future__ import annotations

import pytest

from hound.qa.classifier import (
    check_duration_regression,
    classify_run_results,
    classify_test_result,
)
from hound.qa.history import upsert_results
from hound.qa.model import NormalizedTestResult, now_iso


def _res(
    suite: str,
    test: str,
    status: str = "passed",
    attempt: int = 1,
    duration_ms: int = 50,
    commit: str = "c0",
    branch: str = "main",
    environment: str = "os=linux",
    run_id: str = "r0",
) -> NormalizedTestResult:
    return NormalizedTestResult(
        suite=suite,
        test=test,
        status=status,
        attempt=attempt,
        duration_ms=duration_ms,
        runner="pytest",
        commit=commit,
        branch=branch,
        environment=environment,
        run_id=run_id,
        recorded_at=now_iso(),
    )


class TestDurationRegression:
    def test_duration_regression_insufficient_samples(self):
        is_regr, delta, median = check_duration_regression(
            candidate_duration_ms=500,
            history_durations={"count": 3, "median_ms": 100, "p95_ms": 150},
        )
        assert is_regr is False

    def test_duration_regression_detected(self):
        is_regr, delta, median = check_duration_regression(
            candidate_duration_ms=600,
            history_durations={"count": 10, "median_ms": 200, "p95_ms": 250},
        )
        assert is_regr is True
        assert delta == 400
        assert median == 200

    def test_duration_regression_small_ms_ignored(self):
        # Even if > 2x, if absolute delta < 100ms it should not flag as regression
        is_regr, delta, median = check_duration_regression(
            candidate_duration_ms=40,
            history_durations={"count": 10, "median_ms": 15, "p95_ms": 20},
        )
        assert is_regr is False


class TestQAClassifications:
    @pytest.fixture
    def store_path(self, tmp_path):
        return tmp_path / "test_history.sqlite3"

    def test_no_store_returns_insufficient_history(self):
        c = _res("tests/test_x.py", "test_foo", status="failed")
        res = classify_test_result(None, c)
        assert res.decision == "insufficient_history"
        assert res.confidence == "low"

    def test_single_run_retry_recovery(self):
        att1 = _res("tests/test_x.py", "test_foo", status="failed", attempt=1)
        att2 = _res("tests/test_x.py", "test_foo", status="passed", attempt=2)
        res = classify_test_result(None, att2, attempts_in_run=[att1, att2])
        assert res.decision == "retry_recovered"
        assert res.confidence == "high"

    def test_new_failure_pure_passes_in_history(self, store_path):
        for i in range(10):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="passed", run_id=f"r{i}")])
        candidate = _res("tests/test_x.py", "test_foo", status="failed", run_id="cand")
        res = classify_test_result(store_path, candidate)
        assert res.decision == "new_failure"
        assert res.confidence == "high"
        assert len(res.supporting_evidence) > 0

    def test_known_failure_high_historical_failure_rate(self, store_path):
        for i in range(10):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="failed", run_id=f"r{i}")])
        candidate = _res("tests/test_x.py", "test_foo", status="failed", run_id="cand")
        res = classify_test_result(store_path, candidate)
        assert res.decision == "known_failure"
        assert res.confidence == "high"

    def test_historically_flaky_mixed_results(self, store_path):
        for i in range(6):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="passed", run_id=f"rp{i}")])
        for i in range(4):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="failed", run_id=f"rf{i}")])
        candidate = _res("tests/test_x.py", "test_foo", status="failed", run_id="cand")
        res = classify_test_result(store_path, candidate)
        assert res.decision == "historically_flaky"
        assert res.confidence == "high"

    def test_environment_specific_failure(self, store_path):
        for i in range(5):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="passed", environment="os=linux", run_id=f"rl{i}")])
        for i in range(5):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="failed", environment="os=windows", run_id=f"rw{i}")])
        candidate = _res("tests/test_x.py", "test_foo", status="failed", environment="os=windows", run_id="cand")
        res = classify_test_result(store_path, candidate)
        assert res.decision == "environment_specific"
        assert res.confidence == "high"

    def test_likely_regression_from_baseline_commit(self, store_path):
        upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="passed", commit="base-100", run_id="rbase")])
        for i in range(6):
            upsert_results(store_path, [_res("tests/test_x.py", "test_foo", status="passed", commit=f"c{i}", run_id=f"r{i}")])
        candidate = _res("tests/test_x.py", "test_foo", status="failed", commit="cand-200", run_id="cand")
        res = classify_test_result(store_path, candidate, baseline_commit="base-100")
        assert res.decision == "likely_regression"
        assert res.confidence == "high"

    def test_classify_run_results_batch(self, store_path):
        results = [
            _res("tests/test_a.py", "test_1", status="passed", attempt=1),
            _res("tests/test_b.py", "test_2", status="failed", attempt=1),
            _res("tests/test_b.py", "test_2", status="passed", attempt=2),
        ]
        classifications = classify_run_results(store_path, results)
        assert len(classifications) == 2
        by_test = {c.test: c for c in classifications}
        assert by_test["test_1"].candidate_status == "passed"
        assert by_test["test_2"].decision == "retry_recovered"


class TestQACliAnalyze:
    def test_cli_qa_analyze_artifact(self, tmp_path, capsys):
        from hound.cli import main

        # Create a sample junit artifact
        junit_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" errors="0" failures="1" skipped="0">
    <testcase classname="tests.test_app" name="test_ok" time="0.05" />
    <testcase classname="tests.test_app" name="test_fail" time="0.10">
        <failure message="assert 1 == 2">def test_fail(): assert 1 == 2</failure>
    </testcase>
</testsuite>"""
        junit_file = tmp_path / "junit.xml"
        junit_file.write_text(junit_content, encoding="utf-8")

        code = main(["qa", "analyze", str(junit_file), "--json"])
        assert code == 0
        captured = capsys.readouterr()
        import json
        payload = json.loads(captured.out)
        assert payload["count"] == 2
        decisions = {c["test"]: c["decision"] for c in payload["classifications"]}
        assert "test_ok" in decisions
        assert "test_fail" in decisions
