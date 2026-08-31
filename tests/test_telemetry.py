from __future__ import annotations

from hound_agent.pipeline import analyze
from hound_agent.telemetry import TelemetryRegistry, telemetry


def test_registry_reports_bounded_percentiles_and_gauges():
    registry = TelemetryRegistry(max_observations=3)
    for value in (1, 2, 3, 100):
        registry.observe("latency", value)
    registry.increment("runs", 2)
    registry.gauge("queue", 4)
    snapshot = registry.snapshot()
    assert snapshot["observations"]["latency"] == {"count": 3, "p50": 3, "p95": 100, "max": 100}
    assert snapshot["counters"]["runs"] == 2
    assert snapshot["gauges"]["queue"] == 4


def test_pipeline_records_metrics_without_payload(tmp_path):
    telemetry.reset()
    log = tmp_path / "failure.log"
    secret = "telemetry-must-not-store-this"
    log.write_text(f"AssertionError: {secret}", encoding="utf-8")
    analyze(log, tmp_path / "out", offline=True, no_dedup=True)
    snapshot = telemetry.snapshot()
    assert snapshot["counters"]["analysis_total"] == 1
    assert snapshot["observations"]["analysis_latency_ms"]["count"] == 1
    assert secret not in str(snapshot)
