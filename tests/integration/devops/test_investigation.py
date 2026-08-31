"""M9 release and operational correlation tests."""
from __future__ import annotations

import json

from hound_agent.connectors import observability
from hound_agent.config import load_config
from hound_agent.devops.investigation import build_investigation
from hound_agent.models import Artifacts, DeploymentContext
from hound_agent.pipeline import analyze


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_release_diff_and_slo_preserve_static_severity():
    artifacts = Artifacts(deployment=DeploymentContext(
        revision="42",
        previous_revision="41",
        image_digest="sha256:new",
        previous_image_digest="sha256:old",
        manifest_digest="manifest-same",
        previous_manifest_digest="manifest-same",
        error_budget_remaining="0",
    ))
    result = build_investigation(artifacts, "high")
    assert result["static_severity"] == "high"
    assert result["effective_severity"] == "critical"
    assert {change["field"]: change["status"] for change in result["release_changes"]} == {
        "revision": "changed",
        "image_digest": "changed",
        "manifest_digest": "unchanged",
    }


def test_critical_path_uses_available_parent_links_and_marks_uncertainty():
    artifacts = Artifacts(trace_spans=[
        {"span_id": "root", "parent_span_id": "", "service": "gateway", "duration_ns": 100},
        {"span_id": "child", "parent_span_id": "root", "service": "api", "duration_ns": 200},
    ])
    result = build_investigation(artifacts, "medium")
    assert result["critical_path"]["span_ids"] == ["root", "child"]
    assert result["critical_path"]["duration_ns"] == 200
    assert "partial traces" in result["critical_path"]["uncertainty"]
    assert result["service_boundaries"] == ["api", "gateway"]


def test_critical_path_uses_elapsed_timestamp_range():
    artifacts = Artifacts(trace_spans=[
        {"span_id": "root", "parent_span_id": "", "start_ns": 100, "end_ns": 500, "duration_ns": 400},
        {"span_id": "child", "parent_span_id": "root", "start_ns": 200, "end_ns": 450, "duration_ns": 250},
    ])
    result = build_investigation(artifacts, "medium")
    assert result["critical_path"]["duration_ns"] == 400


def test_pipeline_correlates_release_metrics_trace_slo_and_runbook(tmp_path, monkeypatch):
    def fake_urlopen(request, timeout):
        if "/query_range?" in request.full_url:
            return _Response({"data": {"result": [{"metric": {}, "values": [[1787919300, "1.25"]]}]}})
        return _Response({"spans": [
            {"spanId": "root", "service": "gateway", "start_ns": 100, "end_ns": 200, "version": "1"},
            {"spanId": "child", "parentSpanId": "root", "service": "api", "start_ns": 200, "end_ns": 500, "version": "42", "status": "ERROR"},
        ]})

    monkeypatch.setattr(observability, "urlopen", fake_urlopen)
    log = tmp_path / "deploy.log"
    log.write_text(
        f"2026-08-28T12:31:00Z trace_id={'a' * 32} span_id={'b' * 16} error: deployment api failed",
        encoding="utf-8",
    )
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"deployment": {
        "service": "api",
        "revision": "42",
        "previous_revision": "41",
        "image_digest": "sha256:new",
        "previous_image_digest": "sha256:old",
        "started_at": "2026-08-28T12:30:00Z",
        "finished_at": "2026-08-28T12:35:00Z",
        "slo_target": "99.9",
        "error_budget_remaining": "0",
    }}), encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(
        "observability:\n"
        "  prometheus_url: https://prometheus.example.test\n"
        "  tempo_url: https://tempo.example.test\n"
        "  window_minutes: 15\n"
        "runbooks:\n"
        "  api: https://runbooks.example.test/api\n",
        encoding="utf-8",
    )

    doc = analyze(
        log,
        tmp_path / "out",
        context_path=str(context),
        config_path=str(config),
        offline=True,
        no_dedup=True,
        enrich=True,
    )

    devops = doc["devops"]
    assert any(change["field"] == "revision" and change["status"] == "changed" for change in devops["release_changes"])
    assert len(devops["metric_samples"]) == 1
    assert len(devops["trace_spans"]) == 2
    assert devops["critical_path"]["span_ids"] == ["root", "child"]
    assert devops["static_severity"] == "high"
    assert devops["effective_severity"] == "critical"
    assert doc["triage"]["severity"] == "critical"
    assert devops["runbook"]["url"] == "https://runbooks.example.test/api"
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "## Operational correlation" in report
    assert "correlation only" in str(devops["metric_samples"])


def test_observability_and_runbook_urls_require_https(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "observability:\n  prometheus_url: http://remote.example.test\n"
        "runbooks:\n  api: javascript:alert(1)\n",
        encoding="utf-8",
    )
    try:
        load_config(offline=True, config_path=str(config))
    except ValueError as exc:
        assert "must use HTTPS" in str(exc) or "HTTP(S) URL" in str(exc)
    else:
        raise AssertionError("unsafe observability/runbook URL must be rejected")
