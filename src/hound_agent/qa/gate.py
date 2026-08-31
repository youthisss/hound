"""Deterministic QA quality-gate policy evaluation."""
from __future__ import annotations

import json
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hound_agent.qa.classifier import QAClassification
from hound_agent.qa.coverage import NormalizedCoverage
from hound_agent.qa.sarif import NormalizedSarifReport

OUTCOMES = {"pass", "warn", "block"}
RULE_NAMES = {
    "new_failure",
    "likely_regression",
    "flaky",
    "duration_regression",
    "sarif_error",
    "critical_sarif",
    "sarif_warning",
    "changed_line_coverage",
    "coverage_delta",
    "critical_severity",
    "high_severity",
}
_OUTCOME_RANK = {"pass": 0, "warn": 1, "block": 2}


def _policy_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def _matches_scope(path: str, include: list[str], exclude: list[str]) -> bool:
    normalized_path = _policy_path(path)
    normalized_include = [_policy_path(pattern) for pattern in include]
    normalized_exclude = [_policy_path(pattern) for pattern in exclude]
    return (
        any(fnmatch.fnmatchcase(normalized_path, pattern) for pattern in normalized_include)
        and not any(fnmatch.fnmatchcase(normalized_path, pattern) for pattern in normalized_exclude)
    )


def _coverage_scope(coverage: NormalizedCoverage, rule: dict[str, Any]) -> dict[str, Any]:
    include = rule.get("include", ["*"])
    exclude = rule.get("exclude", [])
    return {
        _policy_path(path): file_coverage
        for path, file_coverage in coverage.files.items()
        if _matches_scope(path, include, exclude)
    }


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"quality-gate policy contains duplicate key: {key}")
        result[key] = value
    return result


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"quality-gate policy contains duplicate key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(frozen=True)
class GateReason:
    evidence_id: str
    rule: str
    outcome: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "rule": self.rule,
            "outcome": self.outcome,
            "message": self.message,
            "evidence": self.evidence,
            "provenance": self.provenance,
        }


@dataclass
class GateResult:
    policy_outcome: str
    reasons: list[GateReason]
    summary: dict[str, Any]
    enforced: bool = True
    analysis_status: str = "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_schema_version": "1.0",
            "analysis_status": self.analysis_status,
            "policy_outcome": self.policy_outcome,
            "enforced": self.enforced,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "summary": self.summary,
            "defect_draft": build_defect_draft(self),
        }


def _validate_outcome(value: object, location: str) -> str:
    if not isinstance(value, str) or value not in OUTCOMES:
        raise ValueError(f"{location} must be one of: {', '.join(sorted(OUTCOMES))}")
    return value


def load_gate_policy(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate a version 1.0 gate policy."""
    policy_path = Path(path)
    if not policy_path.is_file() or policy_path.is_symlink():
        raise ValueError(f"quality-gate policy is not a readable regular file: {policy_path}")
    if policy_path.stat().st_size > 1024 * 1024:
        raise ValueError("quality-gate policy exceeds the 1 MiB limit")
    try:
        raw = policy_path.read_text(encoding="utf-8")
        data = (
            json.loads(raw, object_pairs_hook=_unique_json_object)
            if policy_path.suffix.lower() == ".json"
            else yaml.load(raw, Loader=_UniqueKeyLoader)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read quality-gate policy: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("quality-gate policy root must be a mapping")
    unknown = set(data) - {"version", "rules", "environments"}
    if unknown:
        raise ValueError(f"quality-gate policy has unknown fields: {', '.join(sorted(unknown))}")
    if data.get("version") != "1.0":
        raise ValueError("quality-gate policy version must be '1.0'")
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("quality-gate policy rules must be a mapping")
    unknown_rules = set(rules) - RULE_NAMES
    if unknown_rules:
        raise ValueError(f"quality-gate policy has unknown rules: {', '.join(sorted(unknown_rules))}")
    normalized_rules = _validate_rules(rules, "rules")

    environments = data.get("environments", {})
    if not isinstance(environments, dict):
        raise ValueError("quality-gate policy environments must be a mapping")
    normalized_environments: dict[str, dict[str, Any]] = {}
    for environment, overrides in environments.items():
        if not isinstance(environment, str) or not environment.strip():
            raise ValueError("quality-gate environment names must be non-empty strings")
        if not isinstance(overrides, dict):
            raise ValueError(f"environments.{environment} must be a mapping")
        unknown_overrides = set(overrides) - RULE_NAMES
        if unknown_overrides:
            raise ValueError(
                f"environments.{environment} has unknown rules: {', '.join(sorted(unknown_overrides))}"
            )
        normalized_environments[environment] = _validate_rules(overrides, f"environments.{environment}")
    return {"version": "1.0", "rules": normalized_rules, "environments": normalized_environments}


def _validate_rules(rules: dict[str, Any], location: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for name, value in rules.items():
        if name not in {"changed_line_coverage", "coverage_delta"}:
            normalized[name] = _validate_outcome(value, f"{location}.{name}")
            continue
        allowed = {"minimum", "outcome"}
        if name in {"changed_line_coverage", "coverage_delta"}:
            allowed.update({"include", "exclude", "max_unmapped_lines"})
        if name == "coverage_delta":
            allowed.remove("max_unmapped_lines")
        if not isinstance(value, dict) or not {"minimum", "outcome"}.issubset(value) or set(value) - allowed:
            raise ValueError(f"{location}.{name} requires minimum and outcome and contains only supported fields")
        minimum = value["minimum"]
        lower_bound = -1 if name == "coverage_delta" else 0
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not lower_bound <= minimum <= 1:
            raise ValueError(f"{location}.{name}.minimum must be between {lower_bound} and 1")
        normalized_rule: dict[str, Any] = {
            "minimum": float(minimum),
            "outcome": _validate_outcome(value["outcome"], f"{location}.{name}.outcome"),
        }
        if name in {"changed_line_coverage", "coverage_delta"}:
            for pattern_key in ("include", "exclude"):
                patterns = value.get(pattern_key, ["*"] if pattern_key == "include" else [])
                if not isinstance(patterns, list) or not all(isinstance(pattern, str) and pattern for pattern in patterns):
                    raise ValueError(f"{location}.{name}.{pattern_key} must be a list of non-empty glob strings")
                normalized_rule[pattern_key] = [_policy_path(pattern) for pattern in patterns]
        if name == "changed_line_coverage":
            max_unmapped = value.get("max_unmapped_lines", 0)
            if isinstance(max_unmapped, bool) or not isinstance(max_unmapped, int) or max_unmapped < 0:
                raise ValueError(f"{location}.{name}.max_unmapped_lines must be a non-negative integer")
            normalized_rule["max_unmapped_lines"] = max_unmapped
        normalized[name] = normalized_rule
    return normalized


def evaluate_gate(
    policy: dict[str, Any],
    classifications: list[QAClassification],
    coverage: NormalizedCoverage | None,
    changed_lines: dict[str, list[int]] | None,
    sarif: NormalizedSarifReport | None,
    baseline_coverage: NormalizedCoverage | None = None,
    *,
    environment: str = "",
    enforced: bool = True,
    provenance: list[dict[str, Any]] | None = None,
) -> GateResult:
    """Evaluate normalized evidence without side effects."""
    rules = dict(policy["rules"])
    environments = policy.get("environments", {})
    if environment and environment not in environments:
        raise ValueError(f"quality-gate policy has no environment named {environment!r}")
    rules.update(environments.get(environment, {}))
    reasons: list[GateReason] = []
    missing_evidence = False
    provenance_by_id = {
        str(item["id"]): item
        for item in provenance or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    def source_provenance_ids(paths: list[str]) -> list[str]:
        path_set = set(paths)
        return [
            evidence_id
            for evidence_id, item in provenance_by_id.items()
            if item.get("artifact") in path_set
        ]

    def add_reason(
        rule: str,
        outcome: str,
        message: str,
        evidence: dict[str, Any],
        provenance_ids: list[str] | None = None,
    ) -> None:
        reasons.append(GateReason(
            f"gate-ev-{len(reasons) + 1:03d}",
            rule,
            outcome,
            message,
            evidence,
            [provenance_by_id[evidence_id] for evidence_id in provenance_ids or [] if evidence_id in provenance_by_id],
        ))

    decisions: dict[str, list[QAClassification]] = {}
    for classification in classifications:
        decisions.setdefault(classification.decision, []).append(classification)

    for decision in ("new_failure", "likely_regression"):
        outcome = rules.get(decision, "pass")
        matches = decisions.get(decision, [])
        if outcome != "pass" and matches:
            add_reason(
                decision,
                outcome,
                f"{len(matches)} test(s) classified as {decision}",
                {
                    "tests": [f"{item.suite}::{item.test}" for item in matches],
                    "evidence_refs": sorted({ref for item in matches for ref in item.evidence_refs}),
                },
                sorted({ref for item in matches for ref in item.evidence_refs} | {"history-snapshot"}),
            )

    history_rules = [name for name in ("new_failure", "likely_regression") if rules.get(name, "pass") != "pass"]
    unresolved_failures = [
        item for item in classifications
        if item.candidate_status in {"failed", "error"} and item.decision == "insufficient_history"
    ]
    if history_rules and (not classifications or unresolved_failures):
        missing_evidence = True
        missing_outcome = max((rules[name] for name in history_rules), key=lambda value: _OUTCOME_RANK[value])
        add_reason(
            "history_evidence",
            missing_outcome,
            "History-dependent policy rules could not be evaluated",
            {
                "required_by": history_rules,
                "status": "insufficient_evidence",
                "tests": [f"{item.suite}::{item.test}" for item in unresolved_failures],
            },
            sorted({ref for item in unresolved_failures for ref in item.evidence_refs} | {"history-snapshot"}),
        )

    flaky_matches = [
        item for item in classifications
        if item.decision in {"retry_recovered", "historically_flaky", "flaky_suspect"}
    ]
    flaky_outcome = rules.get("flaky", "pass")
    if flaky_outcome != "pass" and flaky_matches:
        add_reason(
            "flaky",
            flaky_outcome,
            f"{len(flaky_matches)} test(s) have flaky evidence",
            {"tests": [f"{item.suite}::{item.test}" for item in flaky_matches]},
            sorted({ref for item in flaky_matches for ref in item.evidence_refs} | {"history-snapshot"}),
        )
    if flaky_outcome != "pass" and (
        not classifications or any(item.decision == "insufficient_history" for item in classifications)
    ):
        missing_evidence = True
        add_reason(
            "flaky_evidence",
            flaky_outcome,
            "Flaky-test policy could not be fully evaluated without historical evidence",
            {"status": "insufficient_evidence"},
            ["history-snapshot"],
        )

    duration_matches = [item for item in classifications if item.duration_regression]
    duration_outcome = rules.get("duration_regression", "pass")
    if duration_outcome != "pass" and duration_matches:
        add_reason(
            "duration_regression",
            duration_outcome,
            f"{len(duration_matches)} test(s) exceeded duration regression thresholds",
            {"tests": [f"{item.suite}::{item.test}" for item in duration_matches]},
            sorted({ref for item in duration_matches for ref in item.evidence_refs} | {"history-snapshot"}),
        )
    duration_unready = not classifications or any(
        item.duration_candidate_ms is None or item.duration_baseline_median_ms is None
        for item in classifications
    )
    if duration_outcome != "pass" and duration_unready:
        missing_evidence = True
        add_reason(
            "duration_regression_evidence",
            duration_outcome,
            "Duration-regression policy could not be evaluated without sufficient historical samples",
            {"status": "insufficient_evidence"},
            ["history-snapshot"],
        )

    # General severity rules (critical_severity, high_severity)
    crit_outcome = rules.get("critical_severity", "pass")
    if crit_outcome != "pass":
        crit_reasons = [
            item for item in classifications
            if item.decision in {"new_failure", "likely_regression"}
            and any("critical" in str(inc.get("actual_severity", "")).lower() for inc in item.related_incidents)
        ]
        if crit_reasons:
            add_reason(
                "critical_severity",
                crit_outcome,
                f"{len(crit_reasons)} test failure(s) correlate with critical severity incidents",
                {"tests": [f"{item.suite}::{item.test}" for item in crit_reasons]},
                sorted({ref for item in crit_reasons for ref in item.evidence_refs} | {"history-snapshot"}),
            )

    high_outcome = rules.get("high_severity", "pass")
    if high_outcome != "pass":
        high_reasons = [
            item for item in classifications
            if item.decision in {"new_failure", "likely_regression"}
            and any("high" in str(inc.get("actual_severity", "")).lower() for inc in item.related_incidents)
        ]
        if high_reasons:
            add_reason(
                "high_severity",
                high_outcome,
                f"{len(high_reasons)} test failure(s) correlate with high severity incidents",
                {"tests": [f"{item.suite}::{item.test}" for item in high_reasons]},
                sorted({ref for item in high_reasons for ref in item.evidence_refs} | {"history-snapshot"}),
            )

    sarif_outcome = rules.get("sarif_error", "pass")
    if sarif_outcome != "pass" and sarif and sarif.error_count:
        errors = [finding for finding in sarif.findings if finding.is_critical_or_error]
        add_reason(
            "sarif_error",
            sarif_outcome,
            f"{sarif.error_count} unsuppressed SARIF error(s) found",
            {
                "findings": [finding.to_dict() for finding in errors],
                "sources": sarif.source_artifacts,
                "details_truncated": sarif.truncated,
            },
            source_provenance_ids(sarif.source_artifacts),
        )

    critical_outcome = rules.get("critical_sarif", "pass")
    if critical_outcome != "pass" and sarif and sarif.critical_count:
        critical = [finding for finding in sarif.findings if finding.level == "critical" and not finding.is_suppressed]
        add_reason(
            "critical_sarif",
            critical_outcome,
            f"{sarif.critical_count} critical SARIF finding(s) found",
            {"findings": [finding.to_dict() for finding in critical], "sources": sarif.source_artifacts},
            source_provenance_ids(sarif.source_artifacts),
        )

    warning_outcome = rules.get("sarif_warning", "pass")
    if warning_outcome != "pass" and sarif and sarif.warning_count:
        add_reason(
            "sarif_warning",
            warning_outcome,
            f"{sarif.warning_count} unsuppressed SARIF warning(s) found",
            {"count": sarif.warning_count, "sources": sarif.source_artifacts},
            source_provenance_ids(sarif.source_artifacts),
        )

    configured_sarif_rules = [
        name for name in ("sarif_error", "critical_sarif", "sarif_warning") if rules.get(name, "pass") != "pass"
    ]
    if configured_sarif_rules and sarif is None:
        missing_evidence = True
        missing_outcome = max((rules[name] for name in configured_sarif_rules), key=lambda value: _OUTCOME_RANK[value])
        add_reason(
            "sarif_evidence",
            missing_outcome,
            "SARIF policy rules could not be evaluated because no valid SARIF evidence was supplied",
            {"required_by": configured_sarif_rules, "status": "insufficient_evidence"},
        )

    coverage_rule = rules.get("changed_line_coverage")
    changed_coverage: dict[str, Any] | None = None
    if coverage_rule and coverage is not None and changed_lines is not None:
        scoped_changed_lines = {
            path: lines for path, lines in changed_lines.items()
            if _matches_scope(path, coverage_rule.get("include", ["*"]), coverage_rule.get("exclude", []))
        }
        changed_coverage = coverage.changed_lines_detail(scoped_changed_lines)
        total = changed_coverage["total"]
        rate = changed_coverage["rate"]
        incomplete_mapping = (
            not coverage.line_mapping_available
            or bool(changed_coverage["unavailable_files"])
            or changed_coverage["unmapped_lines"] > coverage_rule.get("max_unmapped_lines", 0)
        )
        if incomplete_mapping:
            missing_evidence = True
            add_reason(
                "changed_line_coverage_evidence",
                coverage_rule["outcome"],
                "Changed-line coverage evidence is incomplete for the configured source scope",
                {**changed_coverage, "status": "insufficient_evidence", "sources": coverage.source_artifacts},
                source_provenance_ids(coverage.source_artifacts),
            )
        if total > 0 and rate < coverage_rule["minimum"] and coverage_rule["outcome"] != "pass":
            add_reason(
                "changed_line_coverage",
                coverage_rule["outcome"],
                f"Changed-line coverage {rate:.1%} is below {coverage_rule['minimum']:.1%}",
                changed_coverage,
                source_provenance_ids(coverage.source_artifacts),
            )
    elif coverage_rule:
        missing_evidence = True
        add_reason(
            "changed_line_coverage_evidence",
            coverage_rule["outcome"],
            "Changed-line coverage policy could not be evaluated",
            {"status": "insufficient_evidence"},
        )

    coverage_delta_rule = rules.get("coverage_delta")
    coverage_delta: float | None = None
    if coverage_delta_rule and coverage is not None and baseline_coverage is not None:
        candidate_scope = _coverage_scope(coverage, coverage_delta_rule)
        baseline_scope = _coverage_scope(baseline_coverage, coverage_delta_rule)
        candidate_paths = set(candidate_scope)
        baseline_paths = set(baseline_scope)
        if candidate_paths != baseline_paths:
            missing_evidence = True
            add_reason(
                "coverage_delta_evidence",
                coverage_delta_rule["outcome"],
                "Coverage delta requires equivalent candidate and baseline file scopes",
                {
                    "status": "insufficient_evidence",
                    "candidate_only_files": sorted(candidate_paths - baseline_paths),
                    "baseline_only_files": sorted(baseline_paths - candidate_paths),
                },
                source_provenance_ids(coverage.source_artifacts + baseline_coverage.source_artifacts),
            )
        elif candidate_scope:
            candidate_total = sum(item.lines_total for item in candidate_scope.values())
            candidate_covered = sum(item.lines_covered for item in candidate_scope.values())
            baseline_total = sum(item.lines_total for item in baseline_scope.values())
            baseline_covered = sum(item.lines_covered for item in baseline_scope.values())
            candidate_rate = round(candidate_covered / candidate_total, 4) if candidate_total else 1.0
            baseline_rate = round(baseline_covered / baseline_total, 4) if baseline_total else 1.0
            coverage_delta = round(candidate_rate - baseline_rate, 4)
            if coverage_delta < coverage_delta_rule["minimum"] and coverage_delta_rule["outcome"] != "pass":
                add_reason(
                    "coverage_delta",
                    coverage_delta_rule["outcome"],
                    f"Coverage delta {coverage_delta:+.1%} is below {coverage_delta_rule['minimum']:+.1%}",
                    {
                        "candidate_rate": candidate_rate,
                        "baseline_rate": baseline_rate,
                        "delta": coverage_delta,
                        "files": sorted(candidate_paths),
                    },
                    source_provenance_ids(coverage.source_artifacts + baseline_coverage.source_artifacts),
                )
        else:
            missing_evidence = True
            add_reason(
                "coverage_delta_evidence",
                coverage_delta_rule["outcome"],
                "Coverage delta requires non-empty baseline and candidate coverage",
                {"status": "insufficient_evidence"},
                source_provenance_ids(coverage.source_artifacts + baseline_coverage.source_artifacts),
            )
    elif coverage_delta_rule:
        missing_evidence = True
        add_reason(
            "coverage_delta_evidence",
            coverage_delta_rule["outcome"],
            "Coverage delta policy requires explicit baseline and candidate coverage",
            {"status": "insufficient_evidence"},
        )

    outcome = max((reason.outcome for reason in reasons), key=lambda value: _OUTCOME_RANK[value], default="pass")
    summary = {
        "environment": environment or None,
        "tests_analyzed": len(classifications),
        "classification_counts": {key: len(value) for key, value in sorted(decisions.items())},
        "coverage": coverage.to_dict() if coverage else None,
        "baseline_coverage": baseline_coverage.to_dict() if baseline_coverage else None,
        "coverage_delta": coverage_delta,
        "changed_line_coverage": changed_coverage,
        "sarif": sarif.to_dict() if sarif else None,
    }
    return GateResult(
        outcome,
        reasons,
        summary,
        enforced=enforced,
        analysis_status="insufficient_evidence" if missing_evidence else "succeeded",
    )


def build_defect_draft(result: GateResult) -> dict[str, Any] | None:
    if result.policy_outcome == "pass":
        return None
    title = f"QA quality gate {result.policy_outcome}: {len(result.reasons)} policy reason(s)"
    body = [f"Policy outcome: **{result.policy_outcome}**", "", "Evidence:"]
    for reason in result.reasons:
        body.append(f"- [{reason.outcome}] {reason.message} (`{reason.evidence_id}`)")
        if reason.evidence:
            body.append(f"  Evidence: `{json.dumps(reason.evidence, sort_keys=True, ensure_ascii=False)[:2000]}`")
    return {"title": title, "body_md": "\n".join(body)}
