"""Coverage tests for the failure-event fixtures."""

import json

import pytest

from tracehound.ingest.logs import parse_log
from tracehound.pipeline import analyze
from tracehound.triage.severity import classify
from tracehound.triage.component import assign
from tracehound.models import build_doc, validate
from tracehound.analyze.fallback import build_root_cause
from tracehound.output.tickets import build_ticket
from tracehound.output.report import write_json, write_md
from tests.conftest import fixture, make_artifacts

FIXTURE_ROOT = __import__("pathlib").Path(__file__).parent / "fixtures"

# name -> (stage, kind, severity, priority)
CASES = {
    "import_error.log": ("build", "import_error", "critical", 1),
    "timeout.log": ("test", "timeout", "medium", 3),
    "segfault.log": ("test", "test_failure", "high", 2),
    "npm_build_error.log": ("build", "compilation_error", "critical", 1),
    "ci_generic.log": ("ci", "ci_failure", "high", 2),
    "mixed_build_test.log": ("test", "test_failure", "medium", 3),
    "kubernetes_rollout.log": ("deploy", "readiness_timeout", "high", 2),
    "image_pull.log": ("deploy", "image_pull_error", "critical", 1),
    "migration_failed.log": ("deploy", "migration_failed", "critical", 1),
    "terraform_apply.log": ("deploy", "deployment_failed", "high", 2),
}


def test_parse_log_unique_events():
    for name, (stage, kind, _, _) in CASES.items():
        got_stage, got_kind, _, _ = parse_log(fixture(name))
        assert got_stage == stage, f"{name}: stage {got_stage} != {stage}"
        assert got_kind == kind, f"{name}: kind {got_kind} != {kind}"


def test_classify_unique_events():
    for name, (_, _, severity, priority) in CASES.items():
        a = make_artifacts(name)
        got_sev, got_pri = classify(a)
        assert got_sev == severity, f"{name}: severity {got_sev} != {severity}"
        assert got_pri == priority, f"{name}: priority {got_pri} != {priority}"


def test_failed_tests_parsed():
    from tracehound.ingest.tests import parse_failed_tests

    for name, (_, kind, _, _) in CASES.items():
        tests = parse_failed_tests(fixture(name))
        if kind == "test_failure" or kind == "timeout" or name == "segfault.log":
            assert tests, f"{name}: expected failed tests, got none"
        else:
            assert not tests, f"{name}: expected no failed tests, got {tests}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_analyze_pipeline_validates(name, tmp_path):
    doc = analyze(
        FIXTURE_ROOT / name,
        tmp_path,
        offline=True,
        no_dedup=True,
    )
    validate(doc)
    assert doc["failure"]["kind"] == CASES[name][1]
    assert doc["triage"]["severity"] == CASES[name][2]
    # Outputs were written.
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "ticket.md").exists()
    # report.json is valid JSON and matches the returned doc.
    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert on_disk["triage"]["dedup_key"] == doc["triage"]["dedup_key"]


def test_mixed_build_test_prefers_test_stage():
    # INFO #18: logs with both build and test markers are labeled "test".
    stage, kind, _, _ = parse_log(fixture("mixed_build_test.log"))
    assert stage == "test"
    assert kind == "test_failure"


def test_ci_generic_no_mislabel():
    # Generic CI pipeline failure must not be classified as build/test.
    stage, kind, _, _ = parse_log(fixture("ci_generic.log"))
    assert stage == "ci"
    assert kind == "ci_failure"


def test_segfault_detected_as_crash_high():
    a = make_artifacts("segfault.log")
    rc = build_root_cause(a)
    severity, priority = classify(a)
    assert severity == "high"
    assert priority == 2
    assert rc.confidence  # hypothesis exists
