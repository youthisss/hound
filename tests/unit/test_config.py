from __future__ import annotations

import json
import re

import pytest

from hound.cli import _safe_config, main
from hound.config import Config, load_config


def _write_config(tmp_path, content: str):
    path = tmp_path / "config.yml"
    path.write_text(content, encoding="utf-8")
    return path


def test_config_validate_rejects_insecure_remote_base_url_offline(tmp_path, capsys):
    path = _write_config(tmp_path, "llm:\n  base_url: http://llm.example.test/v1\n")

    assert main(["config", "validate", "--config", str(path)]) == 2
    assert "must use HTTPS" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content,label",
    [
        ("llm:\n  base_url: https://user:secret@llm.example.test/v1\n", "base_url"),
        ("jira:\n  url: https://user:secret@jira.example.test\n", "jira.url"),
        ("runbooks:\n  api: https://user:secret@example.test/runbook\n", "runbooks.api"),
    ],
)
def test_config_rejects_url_userinfo(tmp_path, content, label):
    path = _write_config(tmp_path, content)

    with pytest.raises(ValueError, match=rf"{label} must not include URL credentials"):
        load_config(config_path=str(path), offline=True)


@pytest.mark.parametrize("value", ["yes", 1, [], {}])
def test_config_rejects_non_boolean_redact(tmp_path, value):
    path = _write_config(tmp_path, f"redact: {json.dumps(value)}\n")

    with pytest.raises(ValueError, match="redact must be a boolean"):
        load_config(config_path=str(path), offline=True)


@pytest.mark.parametrize(
    "content,message",
    [
        ("llm:\n  model: [gpt-4o]\n", "llm.model must be a string"),
        ("github:\n  api_base: 42\n", "github.api_base must be a string"),
        ("slack:\n  webhook_url: ftp://example.test/hook\n", "slack.webhook_url must be an HTTP(S) URL"),
    ],
)
def test_config_rejects_obvious_url_and_type_mismatches(tmp_path, content, message):
    path = _write_config(tmp_path, content)

    with pytest.raises(ValueError, match=re.escape(message)):
        load_config(config_path=str(path), offline=True)


def test_safe_config_never_renders_url_credentials():
    payload = _safe_config(Config(base_url="https://user:secret@llm.example.test/v1"))

    assert payload["base_url"] == "[URL credentials redacted]"
    assert "user" not in json.dumps(payload)
    assert "secret" not in json.dumps(payload)


def test_config_show_does_not_echo_rejected_url_credentials(tmp_path, capsys):
    path = _write_config(tmp_path, "llm:\n  base_url: https://user:secret@llm.example.test/v1\n")

    assert main(["config", "show", "--config", str(path), "--json"]) == 2
    output = capsys.readouterr()
    assert "user" not in output.out + output.err
    assert "secret" not in output.out + output.err
