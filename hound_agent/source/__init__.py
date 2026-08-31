"""Bounded, local-first source intelligence."""
from hound_agent.source.context import collect_source_evidence
from hound_agent.source.impact import build_test_impact, recommendation_recall

__all__ = ["build_test_impact", "collect_source_evidence", "recommendation_recall"]
