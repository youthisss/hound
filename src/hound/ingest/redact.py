"""Redact secrets and PII from log text before it reaches the LLM or disk.

Logs routinely contain API keys, tokens, connection strings, and addresses.
Without redaction these leak into LLM prompts (third-party data exposure),
report.json, and filed tickets. The default is to redact; disable with
``--allow-unredacted`` or ``redact: false`` in YAML.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from ipaddress import IPv6Address
from typing import Any, cast

_PRIVATE_KEY_HEADER = r"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
_PRIVATE_KEY_FOOTER = r"-----END (?:ENCRYPTED |RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"

#: Ordered (kind, compiled pattern) list. All matching substrings are replaced
#: with ``[REDACTED:<kind>]``. Order matters: token patterns are tried before
#: the generic email/IP fallbacks so a token URL can't mask an embedded key.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            _PRIVATE_KEY_HEADER + r".*?" + _PRIVATE_KEY_FOOTER,
            re.DOTALL,
        ),
    ),
    # A log window can end before a key footer. Redact the rest rather than
    # risk sending an incomplete private key to a provider or report file.
    ("unterminated_private_key", re.compile(_PRIVATE_KEY_HEADER + r"[\s\S]*\Z")),
    # Header-like values also occur in JSON-ish and shell output. Do not
    # require a colon: ``Authorization=Bearer x`` is equally sensitive.
    ("authorization", re.compile(r"\bAuthorization\s*[:=]\s*[^\r\n,}]+", re.IGNORECASE)),
    ("cookie", re.compile(r"\b(?:Set-Cookie|Cookie)\s*[:=]\s*[^\r\n,}]+", re.IGNORECASE)),
    ("url_credentials", re.compile(
        r"\b(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
        r"(?P<userinfo>[^\s/@?#:]+:[^\s/@?#]*@)",
        re.IGNORECASE,
    )),
    ("query_credential", re.compile(
        r"(?P<prefix>[?&](?:access[_-]?token|api[_-]?key|auth|password|secret|"
        r"sig(?:nature)?|token)=)[^&#\s]+",
        re.IGNORECASE,
    )),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")),
    ("bearer", re.compile(r"\bBearer [A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret", re.compile(r"\b(?:aws_)?secret(?:_access)?_?key\s*[:=]\s*(?:\"[A-Za-z0-9/+=]{32,}\"|'[A-Za-z0-9/+=]{32,}'|[A-Za-z0-9/+=]{32,}\b)", re.IGNORECASE)),
    ("azure_sas", re.compile(r"\bsv=\d{4}-\d{2}-\d{2}[&A-Za-z0-9%._~=/+-]*\bsig=[^\s\"']+", re.IGNORECASE)),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9_-]{20,}\b")),
    ("slack_webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+", re.IGNORECASE)),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    ("pypi_token", re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b")),
    ("vault_token", re.compile(r"\bhvs\.[A-Za-z0-9_-]{20,}\b")),
    ("password", re.compile(r"(?<![A-Za-z0-9_])(?:[\"'])?(?:[A-Za-z0-9]+[_-])*(?:(?:client|access|refresh|id)[_-]?(?:secret|token)|password|passwd|pwd|secret|token|api[_-]?key|credential|auth)(?:[\"'])?\s*[:=]\s*(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s\"']+)", re.IGNORECASE)),
    (
        "connection_string",
        re.compile(
            r"\b(?:postgres|postgresql|mysql|mongodb|redis|amqp|smtp|mssql)://"
            r"[^\s\"']+",
            re.IGNORECASE,
        ),
    ),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("ipv6_address", re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f:.]*(?:%[0-9A-Za-z_.-]+)?(?![\w:])")),
    ("ip_address", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
]


def redact_text(text: str) -> tuple[str, int]:
    """Return ``(redacted_text, hit_count)``.

    Applies every pattern once. A single pass per pattern is sufficient for
    the supported secret shapes; nested secrets are caught by the outer
    pattern (e.g. a password inside a connection string).
    """
    hits = 0
    result = text
    for kind, pattern in PATTERNS:
        if kind == "ipv6_address":
            def redact_ipv6(match: re.Match[str]) -> str:
                nonlocal hits
                candidate = match.group().rstrip(".")
                try:
                    IPv6Address(candidate)
                except ValueError:
                    return match.group()
                hits += 1
                return "[REDACTED:ipv6_address]" + match.group()[len(candidate):]

            result = pattern.sub(redact_ipv6, result)
            continue
        result, n = pattern.subn(f"[REDACTED:{kind}]", result)
        hits += n
    return result, hits


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_\W])(?:password|passwd|pwd|secret|token|api[_-]?key|credential|"
    r"authorization|cookie|private[_-]?key|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|webhook|signature|sig)"
    r"(?:$|[_\W])",
    re.IGNORECASE,
)
_MAX_REDACT_DEPTH = 16


def _sensitive_key(key: object) -> bool:
    """Recognize snake, kebab, dotted, and camel-case credential keys."""
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
    return _SENSITIVE_KEY.search(normalized) is not None


def redact_value(
    value: object,
    *,
    key: object | None = None,
    depth: int = 0,
) -> tuple[object, int]:
    """Recursively redact strings and values held by sensitive keys.

    ``redact_text`` catches recognizable token shapes, but structured connector
    data commonly contains short opaque credentials that have no recognizable
    prefix. A key-aware pass replaces those values wholesale and recurses into
    every container before reports, prompts, or state persistence are reached.
    """
    if depth >= _MAX_REDACT_DEPTH:
        return "[REDACTED:depth_limit]", 1
    if key is not None and _sensitive_key(key):
        if value in (None, "", [], {}, ()):  # no secret content to preserve
            return value, 0
        return "[REDACTED:sensitive_field]", 1
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        hits = 0
        mapping_result: dict[object, object] = {}
        for child_key, child_value in value.items():
            redacted, child_hits = redact_value(child_value, key=child_key, depth=depth + 1)
            mapping_result[child_key] = redacted
            hits += child_hits
        return mapping_result, hits
    if isinstance(value, list):
        hits = 0
        list_result: list[object] = []
        for item in value:
            redacted, child_hits = redact_value(item, depth=depth + 1)
            list_result.append(redacted)
            hits += child_hits
        return list_result, hits
    if isinstance(value, tuple):
        redacted, hits = redact_value(list(value), depth=depth + 1)
        return tuple(cast(list[Any], redacted)), hits
    if isinstance(value, set):
        redacted, hits = redact_value(list(value), depth=depth + 1)
        return set(cast(list[Any], redacted)), hits
    return value, 0
