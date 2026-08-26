"""Normalized cross-run test-result model.

Stable identity is the ``(suite, test)`` pair, where ``test`` is the runner-
agnostic leaf identity (for example ``test_checkout`` instead of a runner path
prefix). Every runner parser normalizes into ``NormalizedTestResult`` so history
aggregates stay format-agnostic.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from hound_agent.ingest.redact import redact_text

STATUSES = {"passed", "failed", "skipped", "error", "unknown"}
RUNNERS = {"pytest", "junit", "jest", "vitest", "go", "rspec", "cargo", "dotnet", "unknown"}
INSUFFICIENT_HISTORY = "insufficient_history"

MAX_IDENTITY_CHARS = 300
MAX_FIELD_CHARS = 500

_RUNNER_ALIASES = {
    "go_test": "go", "golang": "go", "go_test_json": "go", "go test": "go",
    "jestjs": "jest", "jest": "jest",
    "vitest": "vitest",
    "junit": "junit", "junit5": "junit", "surefire": "junit", "xml": "junit",
    "pytest": "pytest",
    "rspec": "rspec",
    "cargo": "cargo", "cargo_test": "cargo",
    "dotnet": "dotnet", "vstest": "dotnet", "nunit": "dotnet", "xunit": "dotnet",
    "unknown": "unknown", "": "unknown",
}


def normalize_runner(runner: str) -> str:
    """Normalize a free-form runner label into the supported runner set."""
    value = (runner or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _RUNNER_ALIASES.get(value, "unknown")


def stable_test_identity(suite: str, test: str) -> str:
    """Runner-agnostic leaf identity used for cross-run comparison."""
    leaf = str(test or "").strip()
    for separator in ("::", "#", ".", "/", "\\"):
        leaf = leaf.split(separator)[-1].strip()
    leaf = leaf[:MAX_IDENTITY_CHARS] or "unknown"
    return leaf


def failure_signature(message: str) -> str:
    """Deterministic redacted signature of a failure message, or ``""`` for passes."""
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    redacted, _ = redact_text(text[:4000])
    redacted = re.sub(r"\b0x[0-9a-fA-F]{6,}\b", "<addr>", redacted)
    redacted = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", redacted)
    redacted = re.sub(r"\b\d{1,2}:\d{2}:\d{2}\b", "<time>", redacted)
    return hashlib.sha256(redacted.encode("utf-8")).hexdigest()


def _safe(value: object, limit: int = MAX_FIELD_CHARS) -> str:
    redacted, _ = redact_text(str(value or "").strip()[:4000])
    return redacted[:limit]


@dataclass
class NormalizedTestResult:
    suite: str = ""
    test: str = ""
    status: str = "unknown"
    attempt: int = 1
    duration_ms: int | None = None
    runner: str = "unknown"
    commit: str = ""
    branch: str = ""
    environment: str = ""
    failure_signature: str = ""
    run_id: str = ""
    evidence_id: str | None = None
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")
        self.runner = normalize_runner(self.runner)
        self.test = stable_test_identity(self.suite, self.test)
        self.attempt = max(1, int(self.attempt))
        self.suite = _safe(self.suite)
        self.test = _safe(self.test)
        self.commit = _safe(self.commit, 80)
        self.branch = _safe(self.branch, 120)
        self.environment = _safe(self.environment, 200)
        self.run_id = _safe(self.run_id, 160)
        self.evidence_id = _safe(self.evidence_id, 80) if self.evidence_id else None
        if self.duration_ms is not None:
            self.duration_ms = max(0, int(self.duration_ms))

    def identity(self) -> tuple[str, str]:
        """Stable cross-run identity: ``(suite, leaf test)``."""
        return (self.suite, self.test)

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
