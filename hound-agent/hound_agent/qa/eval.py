"""QA history evaluation suite for regression and flaky test classification."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from hound_agent.qa.classifier import classify_test_result
from hound_agent.qa.history import upsert_results
from hound_agent.qa.model import NormalizedTestResult, now_iso

QA_EVAL_VERSION = "1.0"


def _generate_synthetic_cases(store_path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # 1. new_failure: 15 passing runs, candidate fails
    for i in range(15):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_auth.py",
                test="test_login",
                status="passed",
                attempt=1,
                duration_ms=50,
                runner="pytest",
                commit=f"c{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-pass-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_new_fail = NormalizedTestResult(
        suite="tests/test_auth.py",
        test="test_login",
        status="failed",
        attempt=1,
        duration_ms=52,
        runner="pytest",
        commit="cand-01",
        branch="feat-login",
        environment="os=linux",
        run_id="run-cand-01",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-01-new-failure",
        "candidate": candidate_new_fail,
        "attempts": None,
        "baseline_commit": None,
        "expected_decision": "new_failure",
    })

    # 2. known_failure: 15 failed runs, candidate fails
    for i in range(15):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_legacy.py",
                test="test_deprecated_endpoint",
                status="failed",
                attempt=1,
                duration_ms=120,
                runner="pytest",
                commit=f"c{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-fail-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_known_fail = NormalizedTestResult(
        suite="tests/test_legacy.py",
        test="test_deprecated_endpoint",
        status="failed",
        attempt=1,
        duration_ms=115,
        runner="pytest",
        commit="cand-02",
        branch="fix-endpoint",
        environment="os=linux",
        run_id="run-cand-02",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-02-known-failure",
        "candidate": candidate_known_fail,
        "attempts": None,
        "baseline_commit": None,
        "expected_decision": "known_failure",
    })

    # 3. retry_recovered: attempt 1 failed, attempt 2 passed in same run
    att1 = NormalizedTestResult(
        suite="tests/test_ui.py",
        test="test_button_click",
        status="failed",
        attempt=1,
        duration_ms=200,
        runner="jest",
        commit="cand-03",
        branch="feat-ui",
        environment="os=linux",
        run_id="run-cand-03",
        recorded_at=now_iso(),
    )
    att2 = NormalizedTestResult(
        suite="tests/test_ui.py",
        test="test_button_click",
        status="passed",
        attempt=2,
        duration_ms=190,
        runner="jest",
        commit="cand-03",
        branch="feat-ui",
        environment="os=linux",
        run_id="run-cand-03",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-03-retry-recovered",
        "candidate": att2,
        "attempts": [att1, att2],
        "baseline_commit": None,
        "expected_decision": "retry_recovered",
    })

    # 4. historically_flaky: 10 passes, 5 failures historically
    for i in range(10):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_worker.py",
                test="test_async_job",
                status="passed",
                attempt=1,
                duration_ms=80,
                runner="pytest",
                commit=f"c{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-worker-pass-{i}",
                recorded_at=now_iso(),
            )
        ])
    for i in range(5):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_worker.py",
                test="test_async_job",
                status="failed",
                attempt=1,
                duration_ms=85,
                runner="pytest",
                commit=f"c-fail-{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-worker-fail-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_flaky = NormalizedTestResult(
        suite="tests/test_worker.py",
        test="test_async_job",
        status="failed",
        attempt=1,
        duration_ms=82,
        runner="pytest",
        commit="cand-04",
        branch="feat-worker",
        environment="os=linux",
        run_id="run-cand-04",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-04-historically-flaky",
        "candidate": candidate_flaky,
        "attempts": None,
        "baseline_commit": None,
        "expected_decision": "historically_flaky",
    })

    # 5. environment_specific: passed in linux, failed in windows
    for i in range(5):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_fs.py",
                test="test_path_separator",
                status="passed",
                attempt=1,
                duration_ms=10,
                runner="pytest",
                commit=f"c{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-fs-linux-{i}",
                recorded_at=now_iso(),
            )
        ])
    for i in range(5):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_fs.py",
                test="test_path_separator",
                status="failed",
                attempt=1,
                duration_ms=12,
                runner="pytest",
                commit=f"c-win-{i:03d}",
                branch="main",
                environment="os=windows",
                run_id=f"run-fs-win-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_env = NormalizedTestResult(
        suite="tests/test_fs.py",
        test="test_path_separator",
        status="failed",
        attempt=1,
        duration_ms=11,
        runner="pytest",
        commit="cand-05",
        branch="feat-paths",
        environment="os=windows",
        run_id="run-cand-05",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-05-environment-specific",
        "candidate": candidate_env,
        "attempts": None,
        "baseline_commit": None,
        "expected_decision": "environment_specific",
    })

    # 6. likely_regression (baseline comparison): baseline passed, candidate fails
    upsert_results(store_path, [
        NormalizedTestResult(
            suite="tests/test_billing.py",
            test="test_calculate_tax",
            status="passed",
            attempt=1,
            duration_ms=30,
            runner="pytest",
            commit="base-sha-123",
            branch="main",
            environment="os=linux",
            run_id="run-base-tax",
            recorded_at=now_iso(),
        )
    ])
    for i in range(8):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_billing.py",
                test="test_calculate_tax",
                status="passed",
                attempt=1,
                duration_ms=32,
                runner="pytest",
                commit=f"c-tax-{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-tax-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_regr = NormalizedTestResult(
        suite="tests/test_billing.py",
        test="test_calculate_tax",
        status="failed",
        attempt=1,
        duration_ms=35,
        runner="pytest",
        commit="cand-sha-456",
        branch="feat-tax-update",
        environment="os=linux",
        run_id="run-cand-tax",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-06-likely-regression",
        "candidate": candidate_regr,
        "attempts": None,
        "baseline_commit": "base-sha-123",
        "expected_decision": "likely_regression",
    })

    # 7. insufficient_history: only 2 runs recorded (< 5)
    for i in range(2):
        upsert_results(store_path, [
            NormalizedTestResult(
                suite="tests/test_new_feature.py",
                test="test_fresh",
                status="passed",
                attempt=1,
                duration_ms=40,
                runner="pytest",
                commit=f"c-fresh-{i:03d}",
                branch="main",
                environment="os=linux",
                run_id=f"run-fresh-{i}",
                recorded_at=now_iso(),
            )
        ])
    candidate_insufficient = NormalizedTestResult(
        suite="tests/test_new_feature.py",
        test="test_fresh",
        status="failed",
        attempt=1,
        duration_ms=45,
        runner="pytest",
        commit="cand-07",
        branch="feat-fresh",
        environment="os=linux",
        run_id="run-cand-07",
        recorded_at=now_iso(),
    )
    cases.append({
        "id": "qa-07-insufficient-history",
        "candidate": candidate_insufficient,
        "attempts": None,
        "baseline_commit": None,
        "expected_decision": "insufficient_history",
    })

    return cases


def evaluate_qa_history() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = Path(tmpdir) / "eval_qa_history.sqlite3"
        cases = _generate_synthetic_cases(store)

        results: list[dict[str, Any]] = []
        correct_count = 0
        flaky_tp = flaky_fp = flaky_fn = 0
        regr_tp = regr_fp = regr_fn = 0

        for case in cases:
            c = classify_test_result(
                store_path=store,
                candidate=case["candidate"],
                attempts_in_run=case["attempts"],
                baseline_commit=case["baseline_commit"],
            )
            is_correct = c.decision == case["expected_decision"]
            if is_correct:
                correct_count += 1

            # Precision/Recall tracking for flaky
            is_flaky_expected = case["expected_decision"] in ("historically_flaky", "flaky_suspect", "retry_recovered")
            is_flaky_predicted = c.decision in ("historically_flaky", "flaky_suspect", "retry_recovered")
            if is_flaky_expected and is_flaky_predicted:
                flaky_tp += 1
            elif not is_flaky_expected and is_flaky_predicted:
                flaky_fp += 1
            elif is_flaky_expected and not is_flaky_predicted:
                flaky_fn += 1

            # Precision/Recall tracking for regression / new failure
            is_regr_expected = case["expected_decision"] in ("likely_regression", "new_failure")
            is_regr_predicted = c.decision in ("likely_regression", "new_failure")
            if is_regr_expected and is_regr_predicted:
                regr_tp += 1
            elif not is_regr_expected and is_regr_predicted:
                regr_fp += 1
            elif is_regr_expected and not is_regr_predicted:
                regr_fn += 1

            results.append({
                "id": case["id"],
                "expected": case["expected_decision"],
                "predicted": c.decision,
                "confidence": c.confidence,
                "correct": is_correct,
                "reason": c.reason,
            })

        flaky_precision = round(flaky_tp / (flaky_tp + flaky_fp), 4) if (flaky_tp + flaky_fp) > 0 else 1.0
        flaky_recall = round(flaky_tp / (flaky_tp + flaky_fn), 4) if (flaky_tp + flaky_fn) > 0 else 1.0
        regr_precision = round(regr_tp / (regr_tp + regr_fp), 4) if (regr_tp + regr_fp) > 0 else 1.0
        regr_recall = round(regr_tp / (regr_tp + regr_fn), 4) if (regr_tp + regr_fn) > 0 else 1.0

        return {
            "evaluation_version": QA_EVAL_VERSION,
            "suite": "qa-history",
            "case_count": len(cases),
            "accuracy": round(correct_count / len(cases), 4),
            "metrics": {
                "flaky": {
                    "precision": flaky_precision,
                    "recall": flaky_recall,
                },
                "regression": {
                    "precision": regr_precision,
                    "recall": regr_recall,
                },
            },
            "cases": results,
        }
