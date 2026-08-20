"""Root-cause orchestrator: LLM when enabled, else deterministic fallback."""
from __future__ import annotations

import sys

from tracehound.config import Config
from tracehound.models import Artifacts, RootCause
from tracehound.analyze.fallback import build_root_cause
from tracehound.analyze.llm import analyze_with_llm

_VALID_CONFIDENCE = {"high", "medium", "low"}


def run_analysis(artifacts: Artifacts, config: Config) -> RootCause:
    fallback = build_root_cause(artifacts)
    if not config.llm_enabled:
        return fallback

    try:
        data, usage = analyze_with_llm(artifacts, config)
    # Online analysis is optional. Any provider/client parsing failure must
    # preserve the deterministic, offline-safe result.
    except Exception:
        # Do not expose provider exception details, which can contain request
        # metadata, but make degraded online analysis observable to operators.
        sys.stderr.write("warning: LLM analysis failed; using deterministic fallback\n")
        return fallback

    if not _valid_llm_result(data):
        sys.stderr.write("warning: LLM returned an invalid result; using deterministic fallback\n")
        return fallback
    merged = _merge_llm(data, fallback, config, usage)
    return merged


def _merge_llm(data: dict, fallback: RootCause, config: Config, usage: dict | None = None) -> RootCause:
    model = config.model
    hypothesis = data["hypothesis"].strip()
    confidence = data["confidence"]
    fix = data["fix_suggestion"].strip()

    # Rule-derived evidence is the deterministic baseline; tag its origin so
    # downstream consumers can tell hard facts from LLM claims.
    evidence = ["[rule] " + e for e in fallback.evidence]
    llm_evidence = data.get("evidence")
    for item in llm_evidence:
        s = item.strip()
        if s and "[llm] " + s not in evidence:
            evidence.append("[llm] " + s)

    # Engine reflects provenance: "merged" when the LLM contributed anything on
    # top of the rule facts; "llm" only when rules produced nothing to keep.
    engine = "merged" if fallback.evidence else "llm"

    return RootCause(
        hypothesis=hypothesis,
        confidence=confidence,
        evidence=evidence,
        fix_suggestion=fix,
        engine=engine,
        model=f"{config.provider}:{model}",  # e.g. "gemini:gemini-2.0-flash"
        usage=usage or {},
    )


def _valid_llm_result(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if set(data) != {"hypothesis", "confidence", "evidence", "fix_suggestion"}:
        return False
    if not isinstance(data["hypothesis"], str) or not data["hypothesis"].strip():
        return False
    if data["confidence"] not in _VALID_CONFIDENCE:
        return False
    if not isinstance(data["fix_suggestion"], str) or not data["fix_suggestion"].strip():
        return False
    return isinstance(data["evidence"], list) and all(isinstance(item, str) for item in data["evidence"])
