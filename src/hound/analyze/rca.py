"""Root-cause orchestrator: LLM when enabled, else deterministic fallback."""
from __future__ import annotations

import sys
from dataclasses import replace
import re

from hound.config import Config, resolve_model_name
from hound.models import Artifacts, RootCause, visible_evidence_items
from hound.analyze.fallback import build_root_cause
from hound.analyze.llm import analyze_with_llm
from hound.safety import validate_recommendation, validate_recommendations

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

    usage: dict = {}
    resolved_config = config
    try:
        # Keep ``auto`` as the persisted user preference, but send and report
        # the concrete model selected from the provider catalog.
        try:
            resolved_config = replace(
                config,
                model=resolve_model_name(config.provider, config.model, base_url=config.base_url),
            )
        except ValueError:
            # Keep the unresolved ``auto`` marker until the concrete transport
            # is invoked. This preserves the optional fallback path and lets
            # callers inject an analysis implementation without a local cache.
            # The real request builder still rejects an unresolved catalog.
            resolved_config = config
        data, usage = analyze_with_llm(artifacts, resolved_config)
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
        fallback.usage = getattr(exc, "usage", {}) or {}
        if fallback.usage:
            fallback.model = f"{resolved_config.provider}:{resolved_config.model}"
        return fallback

    try:
        normalized = _normalize_llm_result(data)
        valid = _valid_llm_result(normalized, artifacts)
        if valid and isinstance(normalized, dict):
            return _merge_llm(normalized, fallback, resolved_config, artifacts, usage)
    except Exception:
        pass
    sys.stderr.write("warning: LLM returned an invalid result; using deterministic fallback\n")
    if config.require_llm:
        raise RuntimeError("required LLM returned an invalid result")
    fallback.llm_status = "failed"
    fallback.fallback_reason = "invalid_response"
    fallback.usage = usage
    fallback.model = f"{resolved_config.provider}:{resolved_config.model}"
    return fallback


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
    validate_recommendation(fix, field="fix_suggestion")
    validate_recommendations(data["recommended_checks"], field="recommended_checks")

    # Rule-derived evidence is the deterministic baseline; tag its origin so
    # downstream consumers can tell hard facts from LLM claims.
    evidence = ["[rule] " + e for e in fallback.evidence]
    available = {item["id"]: item for item in visible_evidence_items(artifacts)}
    for ref in data["evidence_refs"]:
        item = available.get(ref)
        if item is not None:
            rendered = f"[llm-ref {ref}] {item['kind']}: {item['value']}"[:1000]
            if rendered not in evidence:
                evidence.append(rendered)

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
    if getattr(exc, "budget_skipped", False):
        return "budget_exhausted"
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
    if not isinstance(data["confidence"], str) or data["confidence"] not in _VALID_CONFIDENCE:
        return False
    if not isinstance(data["fix_suggestion"], str) or not data["fix_suggestion"].strip():
        return False
    for key in ("hypothesis", "fix_suggestion"):
        value = data[key]
        if not isinstance(value, str) or len(value) > 2000 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            return False
    for key in ("evidence_refs", "contradicting_evidence_refs", "missing_information", "recommended_checks"):
        if not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key]):
            return False
        if len(data[key]) > 8:
            return False
    try:
        validate_recommendation(data["fix_suggestion"], field="fix_suggestion")
        validate_recommendations(data["recommended_checks"], field="recommended_checks")
    except ValueError:
        return False
    if any(
        len(item) > 512 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in item)
        for item in data["missing_information"]
    ):
        return False
    if any(not re.fullmatch(r"ev-[0-9]{3,6}", item) for key in ("evidence_refs", "contradicting_evidence_refs") for item in data[key]):
        return False
    available = {item["id"] for item in visible_evidence_items(artifacts)}
    if not set(data["evidence_refs"]).issubset(available):
        return False
    if not set(data["contradicting_evidence_refs"]).issubset(available):
        return False
    if data["confidence"] == "high":
        from hound.models import supporting_evidence_ids

        if artifacts.kind == "unknown" or data["contradicting_evidence_refs"] or not set(data["evidence_refs"]) & supporting_evidence_ids(artifacts):
            return False
    return not (set(data["evidence_refs"]) & set(data["contradicting_evidence_refs"]))


def _normalize_llm_result(data: object) -> object:
    """Normalize harmless model formatting differences before validation.

    Validation remains fail-closed for claims and evidence references. This
    only tolerates extra explanatory keys, confidence casing, and omitted
    optional diagnostic lists that vary across otherwise compatible models.
    """
    if not isinstance(data, dict):
        return data
    required = {"hypothesis", "confidence", "evidence_refs", "fix_suggestion"}
    if not required.issubset(data):
        return data
    normalized = {
        "hypothesis": data["hypothesis"],
        "confidence": data["confidence"].strip().lower() if isinstance(data["confidence"], str) else data["confidence"],
        "evidence_refs": data["evidence_refs"],
        "contradicting_evidence_refs": data.get("contradicting_evidence_refs", []),
        "missing_information": data.get("missing_information", []),
        "recommended_checks": data.get("recommended_checks", []),
        "fix_suggestion": data["fix_suggestion"],
    }
    return normalized
