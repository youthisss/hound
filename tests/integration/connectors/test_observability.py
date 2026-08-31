"""M9 bounded Prometheus and Tempo connector tests."""
from __future__ import annotations

import json

from hound.connectors import observability
from hound.connectors.observability import collect_observability_bundle
from hound.models import Artifacts, DeploymentContext, FailureEvent


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def _artifacts() -> Artifacts:
    return Artifacts(
        deployment=DeploymentContext(
            service="api",
            started_at="2026-08-28T12:30:00Z",
            finished_at="2026-08-28T12:35:00Z",
        ),
        events=[FailureEvent(trace_id="a" * 32)],
    )


def test_collects_bounded_metric_samples_and_trace_spans(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.headers, timeout))
        if "/query_range?" in request.full_url:
            return _Response({
                "status": "success",
                "data": {"result": [{"metric": {"__name__": "http_5xx_rate"}, "values": [[1787919300, "2.5"]]}]},
            })
        return _Response({
            "spans": [{
                "traceId": "a" * 32,
                "spanId": "b" * 16,
                "service": "api",
                "name": "POST /checkout",
                "startTimeUnixNano": "100",
                "endTimeUnixNano": "300",
                "status": "ERROR",
                "version": "42",
            }],
        })

    monkeypatch.setattr(observability, "urlopen", fake_urlopen)
    bundle = collect_observability_bundle(
        _artifacts(),
        prometheus_url="https://prometheus.example.test",
        prometheus_token="secret-prom-token",
        tempo_url="https://tempo.example.test",
        tempo_token="secret-tempo-token",
    )

    assert len(bundle.metric_samples) == 1
    assert bundle.metric_samples[0]["value"] == 2.5
    assert "correlation only" in bundle.metric_samples[0]["uncertainty"]
    assert len(bundle.trace_spans) == 1
    assert bundle.trace_spans[0]["duration_ns"] == 200
    assert all(timeout == observability.TIMEOUT_SECONDS for _, _, timeout in calls)
    assert all(audit.status == "collected" for audit in bundle.audits)
    assert "secret-prom-token" not in str(bundle)
    assert "secret-tempo-token" not in str(bundle)


def test_missing_deployment_timestamp_skips_metric_query(monkeypatch):
    artifacts = _artifacts()
    artifacts.deployment.started_at = ""
    calls = []
    monkeypatch.setattr(observability, "urlopen", lambda *args, **kwargs: calls.append(args))
    bundle = collect_observability_bundle(artifacts, prometheus_url="https://prometheus.example.test")
    assert bundle.metric_samples == []
    assert calls == []


def test_connector_failure_is_audited_not_raised(monkeypatch):
    monkeypatch.setattr(observability, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    bundle = collect_observability_bundle(
        _artifacts(),
        prometheus_url="https://prometheus.example.test",
        tempo_url="https://tempo.example.test",
    )
    assert bundle.metric_samples == []
    assert bundle.trace_spans == []
    assert all(audit.status == "failed" for audit in bundle.audits)
    assert all(audit.error == "bounded query failed" for audit in bundle.audits)


def test_authenticated_observability_queries_disable_redirects():
    assert observability._NoRedirect().redirect_request(
        None, None, 302, "Found", {}, "https://other.example/query"
    ) is None


def test_unsafe_service_and_trace_identifiers_are_not_queried(monkeypatch):
    artifacts = _artifacts()
    artifacts.deployment.service = 'api"} or vector(1)'
    artifacts.events[0].trace_id = "../../admin"
    calls = []
    monkeypatch.setattr(observability, "urlopen", lambda *args, **kwargs: calls.append(args))
    bundle = collect_observability_bundle(
        artifacts,
        prometheus_url="https://prometheus.example.test",
        tempo_url="https://tempo.example.test",
    )
    assert calls == []
    assert bundle.metric_samples == []
    assert bundle.trace_spans == []
