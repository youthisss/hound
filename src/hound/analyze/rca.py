"""Root-cause orchestrator: LLM when enabled, else deterministic fallback."""
from __future__ import annotations

import sys

from hound.config import Config
from hound.models import Artifacts, RootCause, build_evidence_items
from hound.analyze.fallback import build_root_cause
from hound.analyze.llm import analyze_with_llm

_VALID_CONFIDENCE = {"high", "medium", "low"}


def run_analysis(artifacts: Artifacts, config: Config) -> RootCause:
    fallback = build_root_cause(artifacts)
    if not config.llm_enabled:
        return fallback
    # Cost-control routing: cheap/noisy kinds can be pinned to the rule-based
    # fallback so repeated noise never spends tokens.
    if getattr(config, "routing", "all") == "exclude-kinds" and artifacts.kind in config.skip_kinds:
        fallback.fallback_reason = "routing_policy"
        return fallback

    try:
        data, usage = analyze_with_llm(artifacts, config)
    # Online analysis is optional. Any provider/client parsing failure must
    # preserve the deterministic, offline-safe result.
    except Exception as exc:
        # Do not expose provider exception details, which can contain request
        # metadata, but make degraded online analysis observable to operators.
        sys.stderr.write("warning: LLM analysis failed; using deterministic fallback\n")
        if config.require_llm:
            raise RuntimeError("required LLM analysis failed") from exc
        fallback.llm_status = "failed"
        fallback.fallback_reason = _failure_reason(exc)
        return fallback

    if not _valid_llm_result(data, artifacts):
        sys.stderr.write("warning: LLM returned an invalid result; using deterministic fallback\n")
        if config.require_llm:
            raise RuntimeError("required LLM returned an invalid result")
        fallback.llm_status = "failed"
        fallback.fallback_reason = "invalid_response"
        return fallback
    merged = _merge_llm(data, fallback, config, artifacts, usage)
    return merged


def _merge_llm(
    data: dict,
    fallback: RootCause,
    config: Config,
    artifacts: Artifacts,
    usage: dict | None = None,
) -> RootCause:
    model = config.model
    hypothesis = data["hypothesis"].strip()
    confidence = data["confidence"]
    fix = data["fix_suggestion"].strip()

    # Rule-derived evidence is the deterministic baseline; tag its origin so
    # downstream consumers can tell hard facts from LLM claims.
    evidence = ["[rule] " + e for e in fallback.evidence]
    available = {item["id"]: item for item in build_evidence_items(artifacts)}
    for ref in data["evidence_refs"]:
        item = available.get(ref)
        if item is not None:
            rendered = f"[llm-ref {ref}] {item['kind']}: {item['value']}"
            if rendered not in evidence:
                evidence.append(rendered[:1000])

    # Engine reflects provenance: "merged" when the LLM contributed anything on
    # top of the rule facts; "llm" only when rules produced nothing to keep.
    engine = "merged" if fallback.evidence else "llm"

    return RootCause(
        hypothesis=hypothesis,
        confidence=confidence,
        evidence=evidence,
        fix_suggestion=fix,
        engine=engine,
        model=f"{config.provider}:{model}",  # e.g. "gemini:gemini-3.7-flash"
        usage=usage or {},
        llm_status="succeeded",
        evidence_refs=list(data["evidence_refs"]),
        contradicting_evidence_refs=list(data["contradicting_evidence_refs"]),
        missing_information=list(data["missing_information"]),
        recommended_checks=list(data["recommended_checks"]),
    )


def _failure_reason(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "rate_limited"
    if status in {500, 502, 503, 504}:
        return "provider_unavailable"
    text = str(exc).lower()
    if "json" in text:
        return "invalid_response"
    if "timeout" in text:
        return "timeout"
    return "provider_error"


def _valid_llm_result(data: object, artifacts: Artifacts) -> bool:
    if not isinstance(data, dict):
        return False
    expected_keys = {
        "hypothesis", "confidence", "evidence_refs", "contradicting_evidence_refs",
        "missing_information", "recommended_checks", "fix_suggestion",
    }
    if set(data) != expected_keys:
        return False
    if not isinstance(data["hypothesis"], str) or not data["hypothesis"].strip():
        return False
    if data["confidence"] not in _VALID_CONFIDENCE:
        return False
    if not isinstance(data["fix_suggestion"], str) or not data["fix_suggestion"].strip():
        return False
    for key in ("evidence_refs", "contradicting_evidence_refs", "missing_information", "recommended_checks"):
        if not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key]):
            return False
    available = {item["id"] for item in build_evidence_items(artifacts)}
    if not set(data["evidence_refs"]).issubset(available):
        return False
    if not set(data["contradicting_evidence_refs"]).issubset(available):
        return False
    return not (set(data["evidence_refs"]) & set(data["contradicting_evidence_refs"]))
