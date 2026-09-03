"""Safe text and JSON logging for the HTTP server."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import logging
import re
import sys
from typing import TextIO

from hound.ingest.redact import redact_text

LOGGER_NAME = "hound.server"
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|pwd|secret|token|api[_-]?key|credential|authorization|cookie)(?:$|[_-])",
    re.IGNORECASE,
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@/\s]+@", re.IGNORECASE)
_MAX_EXTRA_DEPTH = 8


def _redact_string(value: str) -> str:
    value = _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED:url_credentials]@", value)
    return redact_text(value)[0]


def _redact_value(value: object, *, key: object | None = None, depth: int = 0) -> object:
    if key is not None and _SENSITIVE_KEY.search(str(key)):
        return "[REDACTED:credential]"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, bytes):
        return _redact_string(value.decode("utf-8", errors="replace"))
    if depth >= _MAX_EXTRA_DEPTH:
        return "[REDACTED:truncated]"
    if isinstance(value, Mapping):
        return {
            _redact_string(str(item_key)): _redact_value(item_value, key=item_key, depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_value(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_string(str(value))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "component": record.name,
            "message": _redact_string(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and value is not None:
                payload[key] = _redact_value(value, key=key)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = []
        for key in ("event", "request_id", "job_id", "status", "method", "path"):
            value = getattr(record, key, None)
            if value is not None:
                fields.append(f"{key}={_redact_value(value, key=key)}")
        suffix = f" {' '.join(fields)}" if fields else ""
        message = _redact_string(record.getMessage())
        return f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} {record.levelname} {record.name} {message}{suffix}"


def configure_server_logging(
    level: str = "INFO",
    log_format: str = "text",
    *,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure only Hound's server logger, leaving application logging alone."""
    normalized_level = level.upper()
    if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("log level must be debug, info, warning, error, or critical")
    if log_format not in {"text", "json"}:
        raise ValueError("log format must be text or json")

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_JsonFormatter() if log_format == "json" else _TextFormatter())
    logger.addHandler(handler)
    logger.setLevel(normalized_level)
    logger.propagate = False
    return logger


def server_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
