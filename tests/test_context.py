"""Deployment context detection and sidecar merging (M7)."""
from __future__ import annotations

import json

from hound_agent.ingest.context import _detect_deployment, load_context


def test_detect_service_workload_and_image_digest(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text(
        "kubectl rollout status deployment/api\n"
        "workload/api pods are failing\n"
        "service=api-billing\n"
        "image digest sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
        "deployment failed\n",
        encoding="utf-8",
    )
    deployment = _detect_deployment(log.read_text(encoding="utf-8"))
    assert deployment.service == "api-billing"
    assert deployment.target == "api"
    assert deployment.image_digest == "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    assert deployment.platform == "kubernetes"
    assert deployment.outcome == "failed"


def test_detect_commit_and_finished_at(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text(
        "release commit abc1234def5678\n"
        "finished_at=2026-08-28T12:40:00Z\n"
        "helm upgrade release api failed\n",
        encoding="utf-8",
    )
    deployment = _detect_deployment(log.read_text(encoding="utf-8"))
    assert deployment.commit == "abc1234def5678"
    assert deployment.finished_at == "2026-08-28T12:40:00Z"
    assert deployment.platform == "helm"


def test_detect_customer_impact_markers(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text("deployment rollout failed\nservice outage affecting customers\n", encoding="utf-8")
    deployment = _detect_deployment(log.read_text(encoding="utf-8"))
    assert deployment.customer_impact == "outage"


def test_detect_customer_impact_fail_closed_empty(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text("kubectl rollout status deployment/api\nfailed\n", encoding="utf-8")
    deployment = _detect_deployment(log.read_text(encoding="utf-8"))
    assert deployment.customer_impact == ""


def test_sidecar_maps_new_deployment_fields(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("deployment failed", encoding="utf-8")
    sidecar = tmp_path / "run.json"
    sidecar.write_text(
        json.dumps({
            "deployment": {
                "service": "api",
                "workload": "api-workload",
                "commit": "deadbeef1234",
                "image_digest": "sha256:aaaabbbbccccdddd",
                "finished_at": "2026-08-28T12:40:00Z",
                "previous_commit": "cafebabe5678",
                "previous_image_digest": "sha256:1111222233334444",
                "customer_impact": "degraded",
            }
        }),
        encoding="utf-8",
    )
    run, deployment = load_context(log, log.read_text(encoding="utf-8"), str(sidecar))
    assert deployment.service == "api"
    assert deployment.workload == "api-workload"
    assert deployment.commit == "deadbeef1234"
    assert deployment.image_digest == "sha256:aaaabbbbccccdddd"
    assert deployment.finished_at == "2026-08-28T12:40:00Z"
    assert deployment.previous_commit == "cafebabe5678"
    assert deployment.previous_image_digest == "sha256:1111222233334444"
    assert deployment.customer_impact == "degraded"


def test_sidecar_overrides_detected_fields(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("kubectl rollout status deployment/api\nfailed\n", encoding="utf-8")
    sidecar = tmp_path / "run.json"
    sidecar.write_text(json.dumps({"deployment": {"service": "trusted-service"}}), encoding="utf-8")
    _, deployment = load_context(log, log.read_text(encoding="utf-8"), str(sidecar))
    # Sidecar wins over log-derived detection for the same field.
    assert deployment.service == "trusted-service"


def test_malformed_sidecar_is_ignored_not_crash(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("deployment failed", encoding="utf-8")
    sidecar = tmp_path / "run.json"
    sidecar.write_text("not json", encoding="utf-8")
    _, deployment = load_context(log, log.read_text(encoding="utf-8"), str(sidecar))
    assert deployment.service == ""
