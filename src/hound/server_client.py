"""Small authenticated client for the bounded Hound HTTP server."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hound.ingest.redact import redact_text
from hound.urlutil import validate_http_url

MAX_RESPONSE_BYTES = 256 * 1024
MAX_LOG_PATH_CHARS = 1024
MAX_JOB_ID_CHARS = 64
_JOB_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class ServerClientError(RuntimeError):
    """Stable client-side error with an HTTP status and retry hint."""

    def __init__(self, message: str, *, code: str = "server_client_error", status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class ServerClient:
    base_url: str
    token: str
    timeout: float = 15.0

    def __post_init__(self) -> None:
        if not self.token or any(ord(char) < 0x20 for char in self.token):
            raise ValueError("server token is required and must not contain control characters")
        if self.timeout <= 0:
            raise ValueError("client timeout must be positive")
        object.__setattr__(self, "base_url", validate_http_url(self.base_url.rstrip("/"), label="server URL"))

    def submit(self, log: str, *, offline: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
        """Submit one relative log path and return the accepted job payload."""
        _validate_log_path(log)
        if idempotency_key is not None:
            if not idempotency_key or len(idempotency_key.encode("utf-8")) > 128:
                raise ValueError("idempotency key must be between 1 and 128 bytes")
        headers = {"Content-Type": "application/json"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return self._request("POST", "/analyze", {"log": log, "offline": bool(offline)}, headers=headers)

    def inspect(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        result = self._request("GET", f"/jobs/{job_id}")
        if "job_id" not in result and isinstance(result.get("id"), str):
            result["job_id"] = result["id"]
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        return self._request("DELETE", f"/jobs/{job_id}")

    def wait(self, job_id: str, *, poll_seconds: float = 0.2, timeout: float | None = None) -> dict[str, Any]:
        """Poll until a job is terminal, bounded by a monotonic deadline."""
        _validate_job_id(job_id)
        if poll_seconds <= 0:
            raise ValueError("poll interval must be positive")
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        if timeout is not None and timeout <= 0:
            raise ValueError("wait timeout must be positive")
        while True:
            job = self.inspect(job_id)
            if job.get("status") in {"completed", "failed", "canceled"}:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServerClientError("server job polling timed out", code="poll_timeout", retryable=True)
            time.sleep(min(poll_seconds, remaining))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or "?" in path or "#" in path or ".." in path:
            raise ValueError("server client path is invalid")
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        request = Request(f"{self.base_url}{path}", data=body, headers=request_headers, method=method)
        opener = build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            payload_error = _decode_payload(raw)
            message = payload_error.get("error") if isinstance(payload_error, dict) else "server request failed"
            raise ServerClientError(
                _safe_message(message),
                code=str(payload_error.get("code", "http_error")) if isinstance(payload_error, dict) else "http_error",
                status=exc.code,
                retryable=bool(payload_error.get("retryable", exc.code in {429, 500, 503}))
                if isinstance(payload_error, dict)
                else exc.code in {429, 500, 503},
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise ServerClientError("could not reach Hound server", code="network_error", retryable=True) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ServerClientError("server response exceeded the byte limit", code="response_too_large")
        result = _decode_payload(raw)
        if not isinstance(result, dict):
            raise ServerClientError("server returned an invalid JSON object", code="invalid_response", status=status)
        return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise HTTPError(request.full_url, code, "redirects are not allowed", headers, fp)


def _decode_payload(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {}


def _safe_message(value: object) -> str:
    text, _ = redact_text(str(value or "server request failed"))
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())[:512]


def _validate_log_path(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_LOG_PATH_CHARS:
        raise ValueError("log must be a non-empty bounded relative path")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError("log must be a relative path without traversal")


def _validate_job_id(value: str) -> None:
    if len(value) > MAX_JOB_ID_CHARS or not _JOB_ID_RE.fullmatch(value):
        raise ValueError("job-id must be a 32-character hexadecimal ID")
