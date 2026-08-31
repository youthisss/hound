"""Shared connector result contract."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConnectorEvidence:
    """One sanitized external observation with provenance."""

    connector: str
    operation: str
    resource: str
    namespace: str
    command: tuple[str, ...]
    value: str
    observed_at: str
    returncode: int
    truncated: bool = False
    redaction_count: int = 0

    def render(self) -> str:
        command = " ".join(self.command)
        return f"$ {command}\n{self.value}"


@dataclass(frozen=True)
class ConnectorAudit:
    """Credential-free record of one attempted connector operation."""

    connector: str
    operation: str
    resource: str
    namespace: str
    status: str
    observed_at: str
    duration_ms: int
    output_bytes: int
    returncode: int | None = None
    error: str = ""


@dataclass
class ConnectorBundle:
    """Bounded evidence plus audit records, including partial failures."""

    evidence: list[ConnectorEvidence] = field(default_factory=list)
    audits: list[ConnectorAudit] = field(default_factory=list)

    def rendered_evidence(self) -> list[str]:
        return [item.render() for item in self.evidence]
