"""Fail-closed safety checks for model-authored diagnostic advice."""
from __future__ import annotations

import re
from collections.abc import Iterable

MAX_RECOMMENDATION_CHARS = 512
MAX_RECOMMENDATIONS = 8

# Recommendations are rendered into reports and tickets and may be followed by
# an operator. They are advice only: reject command-like destructive actions,
# outbound transport, security-control bypasses, and inline credential values.
UNSAFE_RECOMMENDATION = re.compile(
    r"(?:"
    r"\brm\s+(?:-[^\s]*r|--recursive)|\bdel(?:ete)?\s+/[sqf]|\brmdir\s+/s|"
    r"\bformat\s+[a-z]:|\bmkfs(?:\.|\s)|\bdd\s+if=|\bsudo\b|\bdoas\b|"
    r"\bkubectl\s+(?:delete|apply|replace|patch|edit|rollout\s+restart|scale)\b|"
    r"\bhelm\s+(?:install|upgrade|uninstall|rollback)\b|"
    r"\bterraform\s+(?:apply|destroy)\b|"
    r"\bgit\s+(?:push|reset|clean|checkout\s+--|branch\s+-D)\b|"
    r"\bdocker\s+(?:rm|rmi|system\s+prune)\b|"
    r"\b(?:curl|wget|invoke-webrequest|invoke-restmethod|nc|netcat|ssh|scp)\b|"
    r"--no-verify\b|\b(?:verify|verification|tls|ssl)\s*[:=]\s*false\b|"
    r"\b(?:disable|skip|bypass|ignore)\w*\s+(?:tls|ssl|certificate|verification|signature)\b|"
    r"\bhttps?://|"
    r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\s*[:=]\s*\S+"
    r")",
    re.IGNORECASE,
)


def validate_recommendation(value: object, *, field: str = "recommendation") -> None:
    """Raise ``ValueError`` when advice is malformed or operationally unsafe."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > MAX_RECOMMENDATION_CHARS:
        raise ValueError(f"{field} exceeds {MAX_RECOMMENDATION_CHARS} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{field} contains control characters")
    if UNSAFE_RECOMMENDATION.search(value):
        raise ValueError(f"{field} contains an unsafe operational instruction")


def validate_recommendations(values: object, *, field: str = "recommendations") -> None:
    """Validate a bounded collection of advice strings."""
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    if len(values) > MAX_RECOMMENDATIONS:
        raise ValueError(f"{field} contains more than {MAX_RECOMMENDATIONS} items")
    for index, value in enumerate(values):
        validate_recommendation(value, field=f"{field}[{index}]")


def recommendations_are_safe(values: Iterable[object]) -> bool:
    """Predicate form for validators that already handle their own errors."""
    try:
        materialized = list(values)
        validate_recommendations(materialized)
    except (TypeError, ValueError):
        return False
    return True
