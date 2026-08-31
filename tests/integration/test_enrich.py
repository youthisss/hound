"""M8 bounded Kubernetes and Helm connector tests."""
from __future__ import annotations

import subprocess

import pytest

from hound.connectors import deployment as connector
from hound.connectors.deployment import collect_deployment_bundle
from hound.ingest.enrich import collect_deployment_evidence
from hound.models import DeploymentContext
from hound.pipeline import analyze


def _available(monkeypatch):
    monkeypatch.setattr(connector, "trusted_executable", lambda executable: f"/bin/{executable}")


def test_kubernetes_commands_are_direct_read_only_and_bounded(monkeypatch):
    _available(monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    context = DeploymentContext(
        platform="kubernetes",
        namespace="production",
        workload="statefulset/api",
    )
    bundle = collect_deployment_bundle(context)

    assert len(bundle.evidence) == 7
    assert len(bundle.audits) == 7
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all(kwargs["timeout"] == connector.TIMEOUT_SECONDS for _, kwargs in calls)
    assert calls[0][0][0].endswith("kubectl")
    assert calls[0][0][1:4] == ["get", "statefulset", "api"]
    assert calls[-1][0][2] == "statefulset/api"
    assert f"--tail={connector.LOG_TAIL_LINES}" in calls[-1][0]
    assert f"--since={connector.LOG_WINDOW}" in calls[-1][0]
    assert not any(set(command) & connector._MUTATING_TOKENS for command, _ in calls)


def test_helm_commands_are_status_and_bounded_history_only(monkeypatch):
    _available(monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="release data", stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    context = DeploymentContext(platform="helm", namespace="production", release="api")
    bundle = collect_deployment_bundle(context)

    assert [command[1] for command in calls] == ["status", "history"]
    assert "--max" in calls[1]
    assert len(bundle.evidence) == 2


@pytest.mark.parametrize("target", ["api;delete", "../api", "api value", "-all", "api/other"])
def test_malicious_or_out_of_scope_resource_is_rejected(monkeypatch, target):
    _available(monkeypatch)
    monkeypatch.setattr(connector.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not execute"))
    context = DeploymentContext(platform="kubernetes", target=target)
    assert collect_deployment_bundle(context).evidence == []


@pytest.mark.parametrize("command", [
    ("kubectl", "exec", "deployment/api", "--", "sh"),
    ("kubectl", "apply", "-f", "manifest.yml"),
    ("kubectl", "delete", "deployment", "api"),
    ("kubectl", "scale", "deployment", "api", "--replicas=0"),
    ("kubectl", "rollout", "restart", "deployment/api"),
    ("helm", "upgrade", "api", "chart"),
    ("helm", "rollback", "api", "1"),
])
def test_mutating_commands_are_never_allowlisted(command):
    assert connector._is_read_only(command) is False


def test_connector_output_is_redacted_before_return(monkeypatch):
    _available(monkeypatch)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Authorization: Bearer secret-token-value\npassword=supersecret",
            stderr="",
        )

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    bundle = collect_deployment_bundle(DeploymentContext(platform="helm", release="api"))
    rendered = "\n".join(bundle.rendered_evidence())
    assert "secret-token-value" not in rendered
    assert "supersecret" not in rendered
    assert all(item.redaction_count > 0 for item in bundle.evidence)


def test_output_respects_aggregate_byte_limit(monkeypatch):
    _available(monkeypatch)
    monkeypatch.setattr(connector, "MAX_ITEM_BYTES", 16)
    monkeypatch.setattr(connector, "MAX_TOTAL_BYTES", 24)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="x" * 100, stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    bundle = collect_deployment_bundle(DeploymentContext(platform="helm", release="api"))
    assert sum(len(item.value.encode("utf-8")) for item in bundle.evidence) <= 24
    assert any(item.truncated for item in bundle.evidence)


def test_partial_failure_is_audited_and_other_evidence_survives(monkeypatch):
    _available(monkeypatch)
    attempts = 0

    def fake_run(command, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout="healthy evidence", stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    bundle = collect_deployment_bundle(DeploymentContext(platform="kubernetes", target="api"))
    assert bundle.audits[0].status == "timeout"
    assert len(bundle.evidence) == 6
    assert all(audit.error != "" for audit in bundle.audits if audit.status != "collected")


def test_compatibility_adapter_returns_rendered_strings(monkeypatch):
    _available(monkeypatch)
    monkeypatch.setattr(
        connector.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="status", stderr=""),
    )
    evidence = collect_deployment_evidence(DeploymentContext(platform="helm", release="api"))
    assert len(evidence) == 2
    assert all(item.startswith("$ helm ") for item in evidence)


def test_pipeline_persists_connector_audit_without_credentials(tmp_path, monkeypatch):
    _available(monkeypatch)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="password=connector-secret", stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    log = tmp_path / "deploy.log"
    log.write_text("helm upgrade api chart\nrelease api failed", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text('{"deployment":{"platform":"helm","release":"api"}}', encoding="utf-8")

    doc = analyze(
        log,
        tmp_path / "out",
        context_path=str(context),
        offline=True,
        no_dedup=True,
        enrich=True,
    )

    audits = doc["context"]["connector_audits"]
    assert len(audits) == 2
    assert all(audit["status"] == "collected" for audit in audits)
    assert "connector-secret" not in str(doc)
    assert any(item["kind"] == "connector_audit" for item in doc["analysis"]["evidence"])
    assert "## Connector audit" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_pipeline_keeps_local_analysis_when_one_connector_times_out(tmp_path, monkeypatch):
    _available(monkeypatch)
    attempts = 0

    def fake_run(command, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout="bounded evidence", stderr="")

    monkeypatch.setattr(connector.subprocess, "run", fake_run)
    log = tmp_path / "deploy.log"
    log.write_text("kubectl rollout status deployment/api\ndeployment api failed", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(
        '{"deployment":{"platform":"kubernetes","namespace":"production","target":"api"}}',
        encoding="utf-8",
    )

    doc = analyze(
        log,
        tmp_path / "out",
        context_path=str(context),
        offline=True,
        no_dedup=True,
        enrich=True,
    )

    assert doc["failure"]["kind"] == "deployment_failed"
    assert doc["root_cause"]["hypothesis"]
    assert doc["context"]["connector_audits"][0]["status"] == "timeout"
    assert any(audit["status"] == "collected" for audit in doc["context"]["connector_audits"])
