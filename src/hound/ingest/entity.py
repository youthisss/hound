"""Extract bounded request/entity correlation context from CI/CD log windows."""
from __future__ import annotations

import re

from hound.models import MAX_REQUEST_USERS, RequestContext

MAX_USERS = MAX_REQUEST_USERS
_ID_VALUE = r"[A-Za-z0-9._@-]+"
_PATH_VALUE = r"/[A-Za-z0-9._/{}\[\]:?-]+"
_HTTP_METHODS = "GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS"


def _field_pattern(*names: str) -> re.Pattern[str]:
    joined = "|".join(re.escape(name) for name in names)
    return re.compile(
        rf"(?<![A-Za-z0-9_])(?:[\"'])?(?:{joined})(?:[\"'])?\s*[:=]\s*"
        rf"(?:[\"'])?(?P<value>{_ID_VALUE})",
        re.IGNORECASE,
    )


_REQUEST_ID = _field_pattern("request_id", "requestId", "req_id", "x-request-id", "rid")
_TRACE_ID = _field_pattern("trace_id", "traceId", "traceid")
_SESSION_ID = _field_pattern("session_id", "sessionId", "sid")
_USER_ID = _field_pattern("user_id", "userId", "username", "actor", "user")
_METHOD = re.compile(
    rf"(?<![A-Za-z0-9_])(?:[\"'])?method(?:[\"'])?\s*[:=]\s*(?:[\"'])?(?P<value>{_HTTP_METHODS})\b",
    re.IGNORECASE,
)
_PATH = re.compile(
    rf"(?<![A-Za-z0-9_])(?:[\"'])?path(?:[\"'])?\s*[:=]\s*(?:[\"'])?(?P<value>{_PATH_VALUE})",
    re.IGNORECASE,
)
_METHOD_PATH = re.compile(rf"\b(?P<method>{_HTTP_METHODS})\s+(?P<path>{_PATH_VALUE})", re.IGNORECASE)


def _values(pattern: re.Pattern[str], text: str) -> list[str]:
    return [match.group("value") for match in pattern.finditer(text)]


def _mode(values: list[str]) -> str:
    if not values:
        return ""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best = values[0]
    for value in values:
        if counts[value] > counts[best]:
            best = value
    return best


def extract_entity_context(text: str) -> RequestContext:
    """Extract correlation IDs and the most representative HTTP request.

    Scalar fields use the most frequent value, users retain first-seen order,
    and method/path is selected as a pair so unrelated values are not combined.
    """
    user_values = _values(_USER_ID, text)
    users: list[str] = []
    for user in user_values:
        if user not in users:
            users.append(user)
            if len(users) >= MAX_USERS:
                break

    method_paths: list[tuple[str, str]] = []
    for line in text.splitlines():
        method = _METHOD.search(line)
        path = _PATH.search(line)
        if method and path:
            method_paths.append((method.group("value").upper(), path.group("value")))
        method_paths.extend((match.group("method").upper(), match.group("path")) for match in _METHOD_PATH.finditer(line))
    selected_method, selected_path = _mode([f"{method}\n{path}" for method, path in method_paths]).split("\n", 1) if method_paths else ("", "")

    return RequestContext(
        request_id=_mode(_values(_REQUEST_ID, text)),
        trace_id=_mode(_values(_TRACE_ID, text)),
        session_id=_mode(_values(_SESSION_ID, text)),
        user_id=_mode(user_values),
        users=users,
        method=selected_method,
        path=selected_path,
    )
