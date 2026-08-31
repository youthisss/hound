import io
import json

import pytest

from hound_agent.operational_logging import configure_server_logging


def test_json_server_log_has_operational_fields_without_secrets():
    output = io.StringIO()
    logger = configure_server_logging("info", "json", stream=output)
    logger.info("job completed", extra={"event": "job_completed", "request_id": "req-1", "job_id": "job-1"})

    record = json.loads(output.getvalue())
    assert record["level"] == "info"
    assert record["component"] == "hound_agent.server"
    assert record["event"] == "job_completed"
    assert record["request_id"] == "req-1"
    assert record["job_id"] == "job-1"
    assert "timestamp" in record
    assert "token" not in record


@pytest.mark.parametrize("level", ["trace", "verbose"])
def test_server_log_rejects_unknown_level(level):
    with pytest.raises(ValueError, match="log level"):
        configure_server_logging(level)


def test_text_server_log_includes_correlation_fields():
    output = io.StringIO()
    logger = configure_server_logging("warning", "text", stream=output)
    logger.warning("request rejected", extra={"event": "request_rejected", "request_id": "req-1", "status": 401})
    assert "event=request_rejected request_id=req-1 status=401" in output.getvalue()
