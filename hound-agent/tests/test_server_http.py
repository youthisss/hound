import http.client
import io
import json
import os
import threading
import time
from pathlib import Path

import pytest
import socket

from hound_agent.cli import main
from hound_agent.server import ServerConfig, _Server, _copy_limited


@pytest.fixture
def http_server(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("FAILED tests/test_app.py::test_one - assert 1 == 2", encoding="utf-8")
    server = _Server(("127.0.0.1", 0), ServerConfig("secret", logs, tmp_path / "out", analysis_options={"offline": True}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(server, method, path, body=None, authorized=True):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = {"Authorization": "Bearer secret"} if authorized else {}
    if isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def _wait_for_job(server, job_id):
    for _ in range(100):
        status, job = _request(server, "GET", f"/jobs/{job_id}")
        if job["status"] in {"completed", "failed"}:
            return status, job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_http_auth_submit_and_completed_lifecycle(http_server):
    assert _request(http_server, "GET", "/health", authorized=False) == (200, {"status": "ok"})
    assert _request(http_server, "GET", "/ready", authorized=False) == (200, {"status": "ready"})
    assert _request(http_server, "GET", "/jobs/" + "0" * 32, authorized=False)[0] == 401

    status, accepted = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    assert status == 202
    status, job = _wait_for_job(http_server, accepted["job_id"])
    assert status == 200
    assert job["status"] == "completed"
    assert job["engine"] == "fallback"


def test_http_malformed_utf8_returns_json_400(http_server):
    status, payload = _request(http_server, "POST", "/analyze", b"\xff")
    assert status == 400
    assert "error" in payload


def test_http_rejects_unknown_fields_and_non_boolean_offline(http_server):
    assert _request(http_server, "POST", "/analyze", {"log": "run.log", "out": "elsewhere"})[0] == 400
    assert _request(http_server, "POST", "/analyze", {"log": "run.log", "offline": "false"})[0] == 400


def test_http_rate_limits_failed_authentication(http_server):
    http_server.config.rate_limit = 1
    assert _request(http_server, "POST", "/analyze", {"log": "run.log"}, authorized=False)[0] == 401
    assert _request(http_server, "POST", "/analyze", {"log": "run.log"}, authorized=False)[0] == 429


def test_http_failed_job_lifecycle(http_server, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("internal detail")

    monkeypatch.setattr("hound_agent.server.service.analyze_log", fail)
    status, accepted = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    assert status == 202
    _, job = _wait_for_job(http_server, accepted["job_id"])
    assert job["status"] == "failed"
    assert job["error"] == "analysis failed"
    assert "internal detail" not in json.dumps(job)


def test_http_queue_and_rate_limits(http_server):
    http_server.config.max_queue = 1
    http_server.config.jobs_store.create("busy", status="running")
    assert _request(http_server, "POST", "/analyze", {"log": "run.log"})[0] == 429

    http_server.config.jobs_store.clear()
    http_server.request_times.clear()
    http_server.config.max_queue = 8
    http_server.config.rate_limit = 1
    assert _request(http_server, "POST", "/analyze", {"log": "missing.log"})[0] == 404
    assert _request(http_server, "POST", "/analyze", {"log": "missing.log"})[0] == 429


def test_http_jobs_share_dedup_state(http_server):
    _, first = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    _, first_job = _wait_for_job(http_server, first["job_id"])
    _, second = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    _, second_job = _wait_for_job(http_server, second["job_id"])
    assert first_job["status"] == second_job["status"] == "completed"
    report = json.loads(Path(second_job["report"]).read_text(encoding="utf-8"))
    assert report["triage"]["is_duplicate_of"] == report["triage"]["dedup_key"]


def test_http_output_is_cleanable_after_completed_job(http_server):
    _, accepted = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    _, job = _wait_for_job(http_server, accepted["job_id"])
    assert job["status"] == "completed"
    assert main(["clean", "--out", str(http_server.config.output_root), "--yes"]) == 0


def test_snapshot_copy_is_bounded_and_private(tmp_path):
    target = io.BytesIO()
    _copy_limited(io.BytesIO(b"accepted-appended"), target, len(b"accepted"))
    assert target.getvalue() == b"accepted"

    from hound_agent.server import _snapshot_log

    logs = tmp_path / "logs"
    logs.mkdir()
    source = logs / "run.log"
    source.write_text("safe", encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    snapshot = _snapshot_log(logs, source, output, "a" * 32)
    try:
        assert snapshot.parent == output
        assert snapshot.read_text(encoding="utf-8") == "safe"
        if os.name != "nt":
            assert snapshot.stat().st_mode & 0o777 == 0o600
    finally:
        snapshot.unlink(missing_ok=True)


def test_http_active_jobs_are_not_expired(http_server):
    http_server.config.job_ttl = 1
    http_server.config.jobs_store.create("active", status="running")
    http_server.config.jobs_store.update("active", status="running", updated=time.time() - 100)
    _request(http_server, "GET", "/jobs/" + "0" * 32)
    assert "active" in http_server.config.jobs_store.all_ids()


def test_job_store_finished_ttl_uses_restart_safe_wall_clock(tmp_path):
    from hound_agent.server import _JobStore

    store = _JobStore(tmp_path / "jobs.sqlite3")
    store.create("expired", status="completed")
    store.update("expired", updated=time.time() - 100)
    store.cleanup(10)
    assert store.get("expired") is None


def test_server_selects_ipv6_address_family(tmp_path):
    logs = tmp_path / "logs-v6"
    logs.mkdir()
    config = ServerConfig("secret", logs, tmp_path / "out-v6", analysis_options={"offline": True})
    try:
        server = _Server(("::1", 0), config)
    except OSError:
        pytest.skip("IPv6 loopback is unavailable")
    try:
        assert server.address_family == socket.AF_INET6
    finally:
        server.server_close()


# ------------------------------------------------------------- scaling (M19.4)
def test_server_stats_reports_job_counts(http_server):
    _, accepted = _request(http_server, "POST", "/analyze", {"log": "run.log"})
    _, job = _wait_for_job(http_server, accepted["job_id"])
    assert job["status"] == "completed"
    status, stats = _request(http_server, "GET", "/stats")
    assert status == 200
    assert stats["jobs"]["completed"] >= 1
    assert stats["analysis"]["engines"]["fallback"] >= 1


def test_server_config_exposes_scalable_limits(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    config = ServerConfig(
        "secret",
        logs,
        tmp_path / "out",
        analysis_options={"offline": True},
        workers=2,
        max_queue=16,
        rate_limit=120,
        job_ttl=7200,
    )
    assert config.workers == 2
    assert config.max_queue == 16
    assert config.rate_limit == 120
    assert config.job_ttl == 7200


def test_server_config_reads_env_limits(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setenv("TH_SERVER_WORKERS", "3")
    monkeypatch.setenv("TH_SERVER_MAX_QUEUE", "20")
    monkeypatch.setenv("TH_SERVER_RATE_LIMIT", "99")
    monkeypatch.setenv("TH_SERVER_JOB_TTL", "600")
    config = ServerConfig("secret", logs, tmp_path / "out", analysis_options={"offline": True})
    assert config.workers == 3
    assert config.max_queue == 20
    assert config.rate_limit == 99
    assert config.job_ttl == 600


def test_server_config_rejects_out_of_range_limits(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    with pytest.raises(ValueError, match="workers"):
        ServerConfig("secret", logs, tmp_path / "out", workers=0)
    with pytest.raises(ValueError, match="job_ttl"):
        ServerConfig("secret", logs, tmp_path / "out", job_ttl=5)


def test_job_store_marks_interrupted_jobs_failed(tmp_path):
    from hound_agent.server import _JobStore

    store = _JobStore(tmp_path / "jobs.sqlite3")
    store.create("zombie", status="running")
    store.create("queued", status="queued")
    store.create("done", status="completed")
    store.mark_interrupted()
    assert store.get("zombie")["status"] == "failed"
    assert store.get("queued")["status"] == "failed"
    assert store.get("done")["status"] == "completed"
    assert "interrupted" in store.get("zombie")["error"]


def test_server_job_store_survives_restart(tmp_path):
    from hound_agent.server import _JobStore

    store = _JobStore(tmp_path / "jobs.sqlite3")
    store.create("persisted", status="completed")
    store.update("persisted", report="r.json")
    reopened = _JobStore(tmp_path / "jobs.sqlite3")
    assert reopened.get("persisted")["status"] == "completed"
    assert reopened.get("persisted")["report"] == "r.json"
