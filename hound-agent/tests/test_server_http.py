import http.client
import json
import threading
import time
from pathlib import Path

import pytest
import socket

from hound_agent.server import ServerConfig, _Server


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


def test_http_rate_limits_failed_authentication(http_server, monkeypatch):
    monkeypatch.setattr("hound_agent.server.MAX_REQUESTS_PER_WINDOW", 1)
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


def test_http_queue_and_rate_limits(http_server, monkeypatch):
    monkeypatch.setattr("hound_agent.server.MAX_QUEUED_JOBS", 1)
    with http_server.jobs_lock:
        http_server.jobs["busy"] = {"status": "running", "created": time.monotonic()}
    assert _request(http_server, "POST", "/analyze", {"log": "run.log"})[0] == 429

    with http_server.jobs_lock:
        http_server.jobs.clear()
        http_server.request_times.clear()
    monkeypatch.setattr("hound_agent.server.MAX_QUEUED_JOBS", 8)
    monkeypatch.setattr("hound_agent.server.MAX_REQUESTS_PER_WINDOW", 1)
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


def test_http_active_jobs_are_not_expired(http_server, monkeypatch):
    monkeypatch.setattr("hound_agent.server.JOB_TTL_SECONDS", 1)
    with http_server.jobs_lock:
        http_server.jobs["active"] = {
            "status": "running",
            "created": time.monotonic() - 100,
            "updated": time.monotonic() - 100,
        }
    _request(http_server, "GET", "/jobs/" + "0" * 32)
    assert "active" in http_server.jobs


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
