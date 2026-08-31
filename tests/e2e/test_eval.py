from __future__ import annotations

import json
from pathlib import Path

import pytest

from hound.eval import DEFAULT_CORPUS, MAX_ARTIFACT_BYTES, evaluate, load_case, main


def test_evaluator_reports_offline_baseline_without_secrets():
    report = evaluate(DEFAULT_CORPUS)

    assert report["case_count"] == 8
    assert report["split_counts"] == {"dev": 5, "held_out": 3}
    assert report["metrics"]["redaction_recall"] == 1.0
    assert report["metrics"]["failed_tests"] == {"precision": 1.0, "recall": 1.0}
    assert report["metrics"]["throughput_cases_per_second"] > 0
    assert report["metrics"]["peak_memory_bytes"] > 0
    calibration = report["confidence_calibration"]
    assert sum(row["support"] for row in calibration["bands"].values()) == report["case_count"]
    assert "proxy" in calibration["target"]
    serialized = json.dumps(report)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in serialized


def test_evaluator_can_select_held_out_split():
    report = evaluate(DEFAULT_CORPUS, "held_out")
    assert report["case_count"] == 3
    assert report["split_counts"] == {"held_out": 3}


def test_test_impact_suite_meets_labeled_recall_threshold():
    report = evaluate(DEFAULT_CORPUS, "test-impact")
    assert report["suite"] == "test-impact"
    assert report["metrics"]["recommendation_recall"] >= report["minimum_recall"]


def test_committed_baseline_matches_deterministic_metrics():
    report = evaluate(DEFAULT_CORPUS)
    baseline = json.loads(Path("tests/eval/baseline-v1.0.json").read_text(encoding="utf-8"))
    expected_metrics = {
        key: value
        for key, value in report["metrics"].items()
        if key not in {"throughput_cases_per_second", "peak_memory_bytes"}
    }

    assert baseline["evaluation_version"] == report["evaluation_version"]
    assert baseline["case_count"] == report["case_count"]
    assert baseline["split_counts"] == report["split_counts"]
    assert baseline["metrics"] == expected_metrics


def test_malformed_label_fails(tmp_path: Path):
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.log").write_text("healthy", encoding="utf-8")
    path = case_dir / "bad.json"
    path.write_text('{"eval_case_version":"0"}', encoding="utf-8")

    with pytest.raises(ValueError, match="eval_case_version"):
        load_case(path, tmp_path)


def test_missing_expected_secret_fails(tmp_path: Path):
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.log").write_text("pytest passed", encoding="utf-8")
    (case_dir / "case.json").write_text(json.dumps({
        "eval_case_version": "1.0",
        "id": "secret-contract",
        "artifact": "artifact.log",
        "expected": {
            "stage": "unknown", "kind": "unknown", "primary_event": None,
            "failed_tests": [], "stack_frames": [], "severity_range": ["low"],
            "duplicate_group": None, "redactions": ["sk-not-present-in-artifact"],
        },
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="absent from artifact"):
        evaluate(tmp_path)


def test_cli_requires_offline():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def _case_payload(**expected_overrides):
    expected = {
        "stage": "unknown", "kind": "unknown", "primary_event": None,
        "failed_tests": [], "stack_frames": [], "severity_range": ["low"],
        "duplicate_group": None, "redactions": [],
    }
    expected.update(expected_overrides)
    return {"eval_case_version": "1.0", "id": "case", "artifact": "artifact.log", "expected": expected}


def test_label_contract_rejects_missing_and_unknown_fields(tmp_path: Path):
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.log").write_text("healthy", encoding="utf-8")
    payload = _case_payload()
    del payload["expected"]["failed_tests"]
    payload["expected"]["typo"] = []
    path = case_dir / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="expected fields must be exactly"):
        load_case(path, tmp_path)


def test_primary_event_none_requires_no_predicted_primary(tmp_path: Path):
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.log").write_text("ERROR: request timed out", encoding="utf-8")
    (case_dir / "case.json").write_text(json.dumps(_case_payload()), encoding="utf-8")

    report = evaluate(tmp_path)
    assert report["cases"][0]["primary_event_match"] is False


def test_oversized_evaluation_artifact_fails_closed(tmp_path: Path):
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.log").write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
    (case_dir / "case.json").write_text(json.dumps(_case_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact exceeds"):
        evaluate(tmp_path)


def test_structured_results_are_redacted_before_reporting(tmp_path: Path):
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    case_dir = tmp_path / "dev"
    case_dir.mkdir()
    (case_dir / "artifact.json").write_text(json.dumps({
        "tests": [{"nodeid": "test_secret", "outcome": "failed", "longrepr": secret}],
    }), encoding="utf-8")
    payload = _case_payload(
        stage="test", kind="test_failure", primary_event={"stage": "test", "kind": "test_failure"},
        failed_tests=["test_secret"], severity_range=["medium"], redactions=[secret],
    )
    payload["artifact"] = "artifact.json"
    (case_dir / "case.json").write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate(tmp_path)
    assert secret not in json.dumps(report)
    assert report["metrics"]["redaction_recall"] == 1.0
