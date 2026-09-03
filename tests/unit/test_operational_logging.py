import io
import json

import pytest

from hound.operational_logging import configure_server_logging


def test_json_server_log_has_operational_fields_without_secrets():
    output = io.StringIO()
    logger = configure_server_logging("info", "json", stream=output)
    logger.info("job completed", extra={"event": "job_completed", "request_id": "req-1", "job_id": "job-1"})

    record = json.loads(output.getvalue())
    assert record["level"] == "info"
    assert record["component"] == "hound.server"
    assert record["event"] == "job_completed"
    assert record["request_id"] == "req-1"
    assert record["job_id"] == "job-1"
    assert "timestamp" in record
    assert "token" not in record


def test_json_server_log_redacts_messages_and_nested_extra_values():
    output = io.StringIO()
    logger = configure_server_logging("info", "json", stream=output)
    token = "sk-abcdefghijklmnopqrstuvwxyz123456"
    password = "correct-horse-battery-staple"
    url = "https://deploy-user:url-password@example.test/private"

    logger.info(
        "provider failed token=%s at %s",
        token,
        url,
        extra={
            "event": "provider_failed",
            "request_id": "req-credential-check",
            "job_id": "job-credential-check",
            "details": {"password": password, "endpoint": url, "values": [f"api_token={token}"]},
        },
    )

    serialized = output.getvalue()
    record = json.loads(serialized)
    assert token not in serialized
    assert password not in serialized
    assert "deploy-user" not in serialized
    assert "url-password" not in serialized
    assert record["request_id"] == "req-credential-check"
    assert record["job_id"] == "job-credential-check"
    assert record["details"]["password"] == "[REDACTED:credential]"


@pytest.mark.parametrize("level", ["trace", "verbose"])
def test_server_log_rejects_unknown_level(level):
    with pytest.raises(ValueError, match="log level"):
        configure_server_logging(level)


def test_text_server_log_includes_correlation_fields():
    output = io.StringIO()
    logger = configure_server_logging("warning", "text", stream=output)
    logger.warning("request rejected", extra={"event": "request_rejected", "request_id": "req-1", "status": 401})
    assert "event=request_rejected request_id=req-1 status=401" in output.getvalue()


def test_text_server_log_redacts_message_url_credentials():
    output = io.StringIO()
    logger = configure_server_logging("warning", "text", stream=output)
    logger.warning("upstream rejected https://deploy-user:swordfish-value@example.test/private token=plain-secret-token")

    serialized = output.getvalue()
    assert "deploy-user" not in serialized
    assert "swordfish-value" not in serialized
    assert "plain-secret-token" not in serialized
