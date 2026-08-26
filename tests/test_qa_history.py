"""M4: normalized test results and historical store."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hound_agent.cli import main
from hound_agent.ingest.tests import parse_failed_tests
from hound_agent.models import FailedTest
from hound_agent.qa.history import (
    count_by_status,
    default_history_store,
    duration_stats,
    environment_breakdown,
    export_history,
    failure_rate,
    first_last_seen,
    history_for_test,
    import_history,
    list_tests,
    record_doc_results,
    retain,
    upsert_results,
)
from hound_agent.qa.model import (
    INSUFFICIENT_HISTORY,
    NormalizedTestResult,
    failure_signature,
    normalize_runner,
    stable_test_identity,
)
from hound_agent.qa.normalize import (
    detect_runner,
    from_failed_tests,
    import_artifact,
    parse_junit_results,
    parse_test_json_results,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="tests.test_checkout" tests="5" failures="1" errors="1" skipped="1">
  <testcase classname="tests.test_checkout" name="test_discount_applied" time="0.012"/>
  <testcase classname="tests.test_checkout" name="test_cart_total" time="0.003">
    <failure message="assert 5 == 6">assert 5 == 6
Expected :6
Actual   :5</failure>
  </testcase>
  <testcase classname="tests.test_checkout" name="test_inventory_reserve" time="0.001">
    <error message="TimeoutError">socket timed out</error>
  </testcase>
  <testcase classname="tests.test_checkout" name="test_stock_lookup" time="0.0">
    <skipped message="no database"/>
  </testcase>
  <testcase classname="tests.test_checkout" name="test_payment_gateway" time="0.9">
    <flakyFailure message="timeout, then ok">first attempt timed out</flakyFailure>
  </testcase>
</testsuite>
"""


def _result(suite="tests.test_checkout", test="test_cart_total", status="failed", run_id="run-1",
            attempt=1, recorded_at=None, duration_ms=12, environment="os=linux"):
    return NormalizedTestResult(
        suite=suite, test=test, status=status, attempt=attempt, duration_ms=duration_ms,
        runner="pytest", commit="abc123", branch="main", environment=environment,
        failure_signature="sig", run_id=run_id,
        recorded_at=recorded_at or "2026-01-01T00:00:00+00:00",
    )


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _write_junit(tmp_path: Path) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(_JUNIT, encoding="utf-8")
    return path


class TestIdentityAndModel:
    def test_stable_identity_across_runners(self, tmp_path):
        # Same logical test, expressed with runner-specific prefixes.
        assert stable_test_identity("tests/test_checkout.py", "test_cart_total") == "test_cart_total"
        assert stable_test_identity("tests.test_checkout", "tests.test_checkout.test_cart_total") == "test_cart_total"
        assert stable_test_identity("github.com/acme/shop/checkout", "TestCheckout_TestCartTotal") == "TestCheckout_TestCartTotal"
        # Cross-runner consistency: same leaf from pytest text and JUnit classname.
        parsed = parse_failed_tests(
            "= FAILURES =\nFAILED tests/test_checkout.py::test_cart_total - assert 5 == 6\n"
        )
        junit = parse_junit_results(_write_junit(tmp_path), "r1", "abc", "main", "")
        leaf_from_pytest = stable_test_identity(parsed[0].file, parsed[0].name)
        leaf_from_junit = stable_test_identity("tests.test_checkout", "test_cart_total")
        assert leaf_from_pytest == leaf_from_junit == "test_cart_total"
        assert junit[1].test == "test_cart_total"

    def test_failure_signature_deterministic_and_redacted(self):
        a = failure_signature("assert 5 == 6\nExpected 6, got 5")
        b = failure_signature("assert 5 == 6 Expected 6, got 5")
        c = failure_signature("assert 5 == 6\nExpected 6, got 5  api_key=sk-abcdefghijklmnopqrstuvwxyz123456")
        assert a == b  # whitespace normalization
        assert a != c  # secret changes the message
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in c
        assert failure_signature("") == ""

    def test_runner_normalization(self):
        assert normalize_runner("Go test") == "go"
        assert normalize_runner("pytest") == "pytest"
        assert normalize_runner("jestjs") == "jest"
        assert normalize_runner("surefire") == "junit"
        assert normalize_runner("vstest") == "dotnet"
        assert normalize_runner("something-weird") == "unknown"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            NormalizedTestResult(suite="s", test="t", status="bogus")


class TestNormalize:
    def test_from_failed_tests(self):
        tests = [FailedTest(name="tests/test_checkout.py::test_cart_total",
                            file="tests/test_checkout.py", assertion="assert 5 == 6")]
        results = from_failed_tests("pytest", "run-9", "abc", "main", "os=linux", tests)
        assert len(results) == 1
        assert results[0].identity() == ("tests/test_checkout.py", "test_cart_total")
        assert results[0].status == "failed"
        assert results[0].failure_signature

    def test_parse_junit_full_spectrum(self, tmp_path):
        results = parse_junit_results(_write_junit(tmp_path), "run-1", "abc", "main", "os=linux")
        by_name = {r.test: r for r in results}
        assert by_name["test_discount_applied"].status == "passed"
        assert by_name["test_cart_total"].status == "failed"
        assert by_name["test_inventory_reserve"].status == "error"
        assert by_name["test_stock_lookup"].status == "skipped"
        flaky = [r for r in results if r.test == "test_payment_gateway"]
        assert [(r.status, r.attempt) for r in flaky] == [("failed", 1), ("passed", 2)]
        assert by_name["test_discount_applied"].duration_ms == 12

    def test_parse_junit_rejects_doctype(self, tmp_path):
        path = tmp_path / "evil.xml"
        path.write_text('<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "y">]><testsuites/>', encoding="utf-8")
        with pytest.raises(ValueError):
            parse_junit_results(path, "r1", "abc", "main", "")

    def test_parse_test_json(self, tmp_path):
        report = {
            "tests": [
                {"name": "test_cart_total", "classname": "tests/test_checkout.py",
                 "outcome": "passed", "time": 0.01},
                {"name": "test_stock_lookup", "classname": "tests/test_checkout.py",
                 "outcome": "failed", "message": "assert 5 == 6"},
            ]
        }
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        results = parse_test_json_results(path, "run-1", "abc", "main", "")
        assert len(results) == 2
        assert {r.status for r in results} == {"passed", "failed"}

    def test_detect_runner(self):
        assert detect_runner("short test summary info\nFAILED tests/a.py::t", "out.log") == "pytest"
        assert detect_runner("> jest --ci", "out.log") == "jest"
        assert detect_runner("RUN  v1.6.0 /workspace", "out.log") == "vitest"
        assert detect_runner("--- FAIL: TestFoo (0.00s)", "out.log") == "go"
        assert detect_runner("anything", "report.xml") == "junit"
        assert detect_runner("mystery text", "out.log") == "unknown"


class TestHistoryStore:
    def test_upsert_atomicity(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        upsert_results(store, [_result(run_id="r1")])
        upsert_results(store, [_result(run_id="r1", status="passed")])  # same key, new status
        with sqlite3.connect(store) as conn:
            count = conn.execute("SELECT COUNT(*) FROM test_results").fetchone()[0]
            status = conn.execute("SELECT status FROM test_results").fetchone()[0]
        assert count == 1
        assert status == "passed"

    def test_concurrent_writes_wal(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        errors: list[BaseException] = []

        def writer(worker: int) -> None:
            try:
                results = [
                    _result(suite=f"suite-{worker}", test=f"test-{i}", run_id=f"run-{worker}",
                            recorded_at=_days_ago(0), duration_ms=i)
                    for i in range(50)
                ]
                upsert_results(store, results)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        with sqlite3.connect(store) as conn:
            count = conn.execute("SELECT COUNT(*) FROM test_results").fetchone()[0]
        assert count == 200

    def test_retention_does_not_corrupt_aggregates(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        results = [
            _result(run_id="old-1", recorded_at=_days_ago(200), status="failed"),
            _result(run_id="old-2", recorded_at=_days_ago(120), status="failed"),
            _result(run_id="new-1", recorded_at=_days_ago(2), status="passed"),
            _result(run_id="new-2", recorded_at=_days_ago(1), status="failed"),
        ]
        upsert_results(store, results)
        assert failure_rate(store, "tests.test_checkout", "test_cart_total") == 0.75
        deleted = retain(store, days=90)
        assert deleted == 2
        counts = count_by_status(store, "tests.test_checkout", "test_cart_total")
        assert counts["passed"] == 1 and counts["failed"] == 1
        assert failure_rate(store, "tests.test_checkout", "test_cart_total") == 0.5

    def test_failure_rate_insufficient_history(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        assert failure_rate(store, "suite", "test") is None
        counts = count_by_status(store, "suite", "test")
        assert sum(counts.values()) == 0
        assert INSUFFICIENT_HISTORY == "insufficient_history"

    def test_queries(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        upsert_results(store, [
            _result(run_id="a", duration_ms=10, status="passed", environment="os=linux"),
            _result(run_id="b", duration_ms=30, status="passed", environment="os=linux"),
            _result(run_id="c", duration_ms=50, status="failed", environment="os=win"),
        ])
        counts = count_by_status(store, "tests.test_checkout", "test_cart_total")
        assert counts["passed"] == 2 and counts["failed"] == 1
        assert failure_rate(store, "tests.test_checkout", "test_cart_total") == pytest.approx(1 / 3)
        stats = duration_stats(store, "tests.test_checkout", "test_cart_total")
        assert stats["count"] == 3 and stats["median_ms"] == 30
        assert first_last_seen(store, "tests.test_checkout", "test_cart_total")[0] == "2026-01-01T00:00:00+00:00"
        envs = environment_breakdown(store, "tests.test_checkout", "test_cart_total")
        assert envs == {"os=linux": 2, "os=win": 1}
        listed = list_tests(store)
        assert listed[0]["test"] == "test_cart_total" and listed[0]["failures"] == 1
        assert len(history_for_test(store, "tests.test_checkout", "test_cart_total")) == 3

    def test_import_export_roundtrip(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        upsert_results(store, [_result(run_id="r1"), _result(run_id="r2", status="passed")])
        export_path = tmp_path / "history.json"
        manifest = export_history(store, export_path)
        assert manifest["count"] == 2
        store2 = tmp_path / "history2.sqlite3"
        assert import_history(store2, export_path) == 2
        assert failure_rate(store2, "tests.test_checkout", "test_cart_total") == 0.5

    def test_record_doc_results(self, tmp_path):
        store = tmp_path / "history.sqlite3"
        doc = {
            "meta": {"run_id": "run-x", "generated_at": "2026-02-01T00:00:00+00:00"},
            "context": {"run": {"commit_sha": "abc", "branch": "main"}},
            "failure": {"failed_tests": [
                {"name": "tests/test_a.py::test_alpha", "file": "tests/test_a.py"}
            ]},
        }
        assert record_doc_results(doc, store) == 1
        assert count_by_status(store, "tests/test_a.py", "test_alpha")["failed"] == 1


class TestCli:
    def test_cli_import_history_stats(self, tmp_path):
        out = tmp_path / "out"
        artifact = _write_junit(tmp_path)
        code = main(["qa", "import", str(artifact), "--run-id", "run-1", "--commit", "abc",
                     "--branch", "main", "--out", str(out)])
        assert code == 0
        store = default_history_store(out)
        assert store.exists()
        assert main(["qa", "stats", "tests.test_checkout", "test_cart_total", "--out", str(out)]) == 0
        assert main(["qa", "history", "tests.test_checkout", "test_cart_total",
                     "--out", str(out), "--json"]) == 0
        assert main(["qa", "tests", "--out", str(out)]) == 0

    def test_cli_qa_export(self, tmp_path):
        out = tmp_path / "out"
        artifact = _write_junit(tmp_path)
        assert main(["qa", "import", str(artifact), "--run-id", "run-1", "--out", str(out)]) == 0
        export_file = tmp_path / "history.json"
        assert main(["qa", "export", "--out", str(out), "--output", str(export_file)]) == 0
        payload = json.loads(export_file.read_text(encoding="utf-8"))
        assert payload["count"] >= 6

    def test_cli_import_text_log(self, tmp_path):
        out = tmp_path / "out"
        log = tmp_path / "pytest.log"
        log.write_text("short test summary info\n"
                       "FAILED tests/test_checkout.py::test_cart_total - assert 5 == 6\n", encoding="utf-8")
        assert main(["qa", "import", str(log), "--run-id", "run-1", "--out", str(out)]) == 0
        store = default_history_store(out)
        assert count_by_status(store, "tests/test_checkout.py", "test_cart_total")["failed"] == 1

    def test_cli_qa_import_directory(self, tmp_path):
        out = tmp_path / "out"
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "a.xml").write_text(_JUNIT, encoding="utf-8")
        (artifacts / "b.log").write_text("short test summary info\nFAILED tests/test_b.py::test_beta - boom\n",
                                         encoding="utf-8")
        assert main(["qa", "import", str(artifacts), "--run-id", "run-1", "--out", str(out)]) == 0
        store = default_history_store(out)
        assert count_by_status(store, "tests.test_checkout", "test_cart_total")["failed"] == 1
        assert count_by_status(store, "tests/test_b.py", "test_beta")["failed"] == 1


def test_import_artifact_rejects_missing_and_unsupported(tmp_path):
    with pytest.raises(ValueError):
        import_artifact(tmp_path / "missing.log", "r1", "abc", "main", "")
    (tmp_path / "readme.md").write_text("# hi", encoding="utf-8")
    with pytest.raises(ValueError):
        import_artifact(tmp_path / "readme.md", "r1", "abc", "main", "")
