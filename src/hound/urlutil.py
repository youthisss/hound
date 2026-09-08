"""Small, consistent validation helpers for Hound's HTTP boundaries."""
from __future__ import annotations

from urllib.parse import urlsplit


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_http_url(
    value: object,
    *,
    label: str = "URL",
    require_https: bool = False,
    allow_loopback_http: bool = True,
    allow_query: bool = False,
) -> str:
    """Validate a configured HTTP(S) URL without making a network request.

    Credentials, fragments, malformed ports, and control/whitespace characters
    are rejected before a URL can reach an HTTP client. Plain HTTP is reserved
    for explicit loopback development endpoints; callers that handle secrets or
    delivery should set ``require_https``.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an HTTP(S) URL")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{label} must be an HTTP(S) URL")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port  # Force validation of malformed ports.
    except ValueError as exc:
        raise ValueError(f"{label} must be an HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise ValueError(f"{label} must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not include URL credentials")
    if parsed.fragment or (parsed.query and not allow_query):
        raise ValueError(f"{label} must not include a query or fragment")
    if parsed.scheme != "https" and (
        require_https or not allow_loopback_http or hostname.lower() not in LOOPBACK_HOSTS
    ):
        raise ValueError(f"{label} must use HTTPS")
    return value
