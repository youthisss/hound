"""Compatibility adapter for bounded deployment connectors."""
from __future__ import annotations

from hound_agent.connectors.deployment import collect_deployment_bundle
from hound_agent.connectors.model import ConnectorAudit
from hound_agent.models import DeploymentContext


class RenderedEvidence(list[str]):
    """Legacy string list carrying structured audit records for new consumers."""

    def __init__(self, values: list[str], audits: list[ConnectorAudit]) -> None:
        super().__init__(values)
        self.audits = audits


def collect_deployment_evidence(context: DeploymentContext) -> list[str]:
    """Return sanitized rendered evidence for the existing analysis pipeline.

    The structured connector contract remains available through
    ``collect_deployment_bundle``; this adapter preserves the established
    ``list[str]`` pipeline interface.
    """
    bundle = collect_deployment_bundle(context)
    return RenderedEvidence(bundle.rendered_evidence(), bundle.audits)
