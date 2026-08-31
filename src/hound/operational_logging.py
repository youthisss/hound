"""Safe text and JSON logging for the HTTP server."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import TextIO

LOGGER_NAME = "hound.server"
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "component": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = []
        for key in ("event", "request_id", "job_id", "status", "method", "path"):
            value = getattr(record, key, None)
            if value is not None:
                fields.append(f"{key}={value}")
        suffix = f" {' '.join(fields)}" if fields else ""
        return f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} {record.levelname} {record.name} {record.getMessage()}{suffix}"


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
