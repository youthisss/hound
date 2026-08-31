import json

import pytest

from hound.ingest.logs import parse_log
from hound.pipeline import analyze
from tests.conftest import FIXTURES


def test_junit_report_produces_test_failure(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text("<testsuite><testcase classname='cart' name='total'><failure message='expected 5'>trace</failure></testcase></testsuite>", encoding="utf-8")
    doc = analyze(report, tmp_path / "out", offline=True, no_dedup=True)
    assert doc["failure"]["stage"] == "test"
    assert doc["failure"]["failed_tests"][0]["name"] == "total"


def test_json_test_report_produces_test_failure(tmp_path):
    report = tmp_path / "playwright-results.json"
    report.write_text(json.dumps({"suites": [{"tests": [{"title": "checkout", "status": "failed", "message": "timeout"}]}]}), encoding="utf-8")
    doc = analyze(report, tmp_path / "out", offline=True, no_dedup=True)
    assert doc["failure"]["kind"] == "test_failure"
    assert doc["failure"]["failed_tests"][0]["name"] == "checkout"


@pytest.mark.parametrize("text,kind", [
    ("kubectl rollout status deployment/api\ndeployment \"api\" exceeded its progress deadline", "readiness_timeout"),
    ("pod/api OOMKilled", "oom_killed"),
    ("pod/api CrashLoopBackOff", "crash_loop"),
    ("Warning FailedScheduling 0/3 nodes are available", "scheduling_failed"),
    ("exceeded quota: compute-resources", "quota_exceeded"),
    ("image pull access denied: registry authentication required", "registry_auth_failure"),
    ("configmap app-config not found", "config_missing"),
])
def test_specific_deployment_kinds(text, kind):
    assert parse_log(text)[1] == kind


def test_successful_rollback_is_recovery_not_failure():
    stage, kind, _, _ = parse_log("kubectl rollout undo deployment/api\nrollback completed successfully")
    assert stage == "deploy"
    assert kind == "unknown"


def test_context_sidecar_pr_diff_owners_and_events(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CODEOWNERS").write_text("src/* @platform\n", encoding="utf-8")
    source = repo / "src"
    source.mkdir()
    (source / "app.py").write_text("raise ValueError('bad')\n", encoding="utf-8")
    log = tmp_path / "run.log"
    log.write_text("Traceback\n File \"src/app.py\", line 1, in run\nValueError: bad\ncleanup failed", encoding="utf-8")
    log.with_suffix(".json").write_text(json.dumps({"run": {"provider": "github-actions", "run_id": "42", "pr_number": "9", "base_sha": "base", "head_sha": "head", "workflow": "verify"}, "deployment": {"environment": "production", "target": "api"}}), encoding="utf-8")
    doc = analyze(log, tmp_path / "out", repo_dir=repo, context_path=str(log.with_suffix(".json")), offline=True, no_dedup=True)
    assert doc["context"]["run"]["run_id"] == "42"
    assert doc["context"]["owners"] == ["@platform"]
    assert doc["failure"]["events"]


def test_deployment_fixture_produces_stable_distinct_timeline(tmp_path):
    log = tmp_path / "deployment.log"
    log.write_text((FIXTURES / "deployment_timeline.log").read_text(encoding="utf-8"), encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({
        "run": {"provider": "github-actions", "run_id": "42", "job_name": "deploy"},
        "deployment": {
            "environment": "production",
            "service": "api",
            "workload": "deployment/api",
            "release": "api-42",
            "revision": "42",
            "previous_revision": "41",
            "outcome": "failed",
            "recovery": "rollback_pending",
        },
    }), encoding="utf-8")

    first = analyze(log, tmp_path / "out-1", context_path=str(context), offline=True, no_dedup=True)
    second = analyze(log, tmp_path / "out-2", context_path=str(context), offline=True, no_dedup=True)

    timeline = first["timeline"]
    assert timeline == second["timeline"]
    assert timeline["primary_event_id"] == "ev-001"
    assert timeline["downstream_event_ids"]
    assert timeline["recovery_event_ids"] == ["rec-001"]
    assert timeline["customer_impact"] == "unknown"
    assert timeline["release_changed"] is True


def test_environment_policy_overrides_severity(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("kubectl rollout status deployment/api\ndeployment failed", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"deployment": {"environment": "production"}}), encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text("policy:\n  severity_overrides:\n    production:\n      deployment_failed: critical\n  recurrence_threshold: 2\n", encoding="utf-8")
    doc = analyze(log, tmp_path / "out", context_path=str(context), config_path=str(config), offline=True, no_dedup=True)
    assert doc["triage"]["severity"] == "critical"


def test_github_output_is_published(tmp_path, monkeypatch):
    from hound.cli import _write_github_outputs
    from hound import service

    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    document = {
        "failure": {"kind": "ci_failure", "stage": "ci"},
        "triage": {"severity": "high", "dedup_key": "key"},
    }
    run = service.AnalysisRun("run", tmp_path / "run.log", tmp_path / "out", document)
    _write_github_outputs([run])
    values = output.read_text(encoding="utf-8")
    assert "severity<<TRACEHOUND_" in values
    assert "\nhigh\n" in values
    assert "report<<TRACEHOUND_" in values


def test_github_output_uses_multiline_safe_encoding(tmp_path, monkeypatch):
    from hound.cli import _write_github_outputs
    from hound import service

    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    document = {"failure": {"kind": "ci_failure", "stage": "ci"}, "triage": {"severity": "high", "dedup_key": "key"}}
    run = service.AnalysisRun("run", tmp_path / "line\ninjected.log", tmp_path / "line\ninjected", document)
    _write_github_outputs([run])
    assert "\ninjected=\n" not in output.read_text(encoding="utf-8")


def test_context_is_redacted_and_helm_release_detected(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text("helm upgrade --install api chart\nrelease api failed", encoding="utf-8")
    log.with_suffix(".json").write_text(json.dumps({"run": {"run_url": "https://user:password@example.test/run"}}), encoding="utf-8")
    doc = analyze(log, tmp_path / "out", context_path=str(log.with_suffix(".json")), offline=True, no_dedup=True)
    assert doc["context"]["deployment"]["release"] == "api"
    assert "password" not in doc["context"]["run"]["run_url"]


def test_malformed_sarif_is_ignored_not_crash(tmp_path):
    report = tmp_path / "broken.sarif"
    report.write_text('{"runs":[{"results":"not-a-list"}]}', encoding="utf-8")
    doc = analyze(report, tmp_path / "out", offline=True, no_dedup=True)
    assert doc["failure"]["kind"] == "unknown"


def test_go_json_report_produces_test_failure(tmp_path):
    report = tmp_path / "go-results.json"
    report.write_text('{"Action":"output","Test":"TestCart","Output":"expected 5\\n"}\n{"Action":"fail","Test":"TestCart","Package":"example/cart"}\n', encoding="utf-8")
    doc = analyze(report, tmp_path / "out", offline=True, no_dedup=True)
    assert doc["failure"]["failed_tests"][0]["name"] == "TestCart"
