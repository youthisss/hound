"""SARIF 2.1.0 Parser and Consolidator for Quality Gate.

Supported SARIF features:
- Ingest runs, tool drivers, and results
- Filter by level (error, warning, note)
- Suppressed/suppression check
- Normalization into structured QA findings
- Security bounds: reject oversized SARIF, reject DOCTYPE
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hound.ingest.structured import _read_artifact
from hound.ingest.redact import redact_text

MAX_SARIF_FINDINGS = 1000
MAX_SARIF_FIELD_CHARS = 2000


def _safe(value: object, limit: int = MAX_SARIF_FIELD_CHARS) -> str:
    return redact_text(str(value))[0][:limit]


def _finding_priority(finding: SarifFinding) -> int:
    if not finding.is_suppressed and finding.level == "critical":
        return 0
    if finding.is_critical_or_error:
        return 1
    if not finding.is_suppressed and finding.level == "warning":
        return 2
    if not finding.is_suppressed and finding.level == "note":
        return 3
    return 4


@dataclass
class SarifFinding:
    rule_id: str
    level: str  # "error" | "warning" | "note" | "none"
    message: str
    file_path: str = ""
    start_line: int = 0
    start_column: int = 0
    rule_name: str = ""
    tool_name: str = ""
    is_suppressed: bool = False

    @property
    def is_critical_or_error(self) -> bool:
        return self.level.lower() in ("error", "critical") and not self.is_suppressed

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "level": self.level,
            "message": self.message,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "tool_name": self.tool_name,
            "is_suppressed": self.is_suppressed,
        }


@dataclass
class NormalizedSarifReport:
    findings: list[SarifFinding] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    note_count: int = 0
    critical_count: int = 0
    processed_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    source_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "note_count": self.note_count,
            "critical_count": self.critical_count,
            "processed_count": self.processed_count,
            "omitted_count": self.omitted_count,
            "truncated": self.truncated,
            "source_artifacts": self.source_artifacts,
            "total_findings": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
        }


def merge_sarif(reports: list[NormalizedSarifReport]) -> NormalizedSarifReport | None:
    if not reports:
        return None
    merged = NormalizedSarifReport()
    merged.tools = sorted({tool for report in reports for tool in report.tools})
    all_retained = [finding for report in reports for finding in report.findings]
    all_retained.sort(key=_finding_priority)
    merged.findings = all_retained[:MAX_SARIF_FINDINGS]
    merged.error_count = sum(report.error_count for report in reports)
    merged.warning_count = sum(report.warning_count for report in reports)
    merged.note_count = sum(report.note_count for report in reports)
    merged.critical_count = sum(report.critical_count for report in reports)
    merged.processed_count = sum(report.processed_count for report in reports)
    merged.omitted_count = max(0, merged.processed_count - len(merged.findings))
    merged.truncated = merged.omitted_count > 0 or any(report.truncated for report in reports)
    merged.source_artifacts = sorted({item for report in reports for item in report.source_artifacts})
    return merged


def parse_sarif_dict(data: dict[str, Any], *, source: str = "") -> NormalizedSarifReport:
    """Parse a SARIF JSON dictionary into NormalizedSarifReport."""
    report = NormalizedSarifReport()
    if source:
        report.source_artifacts = [_safe(source, 500)]
    runs = data.get("runs")
    if not isinstance(runs, list):
        return report

    tools_seen: set[str] = set()

    for run in runs:
        if not isinstance(run, dict):
            continue
        tool_driver = run.get("tool", {}).get("driver", {}) if isinstance(run.get("tool"), dict) else {}
        tool_name = _safe(tool_driver.get("name", "unknown") if isinstance(tool_driver, dict) else "unknown", 500)
        tools_seen.add(tool_name)

        # Build rule dictionary if available
        rules_map: dict[str, dict[str, Any]] = {}
        if isinstance(tool_driver, dict) and isinstance(tool_driver.get("rules"), list):
            for r in tool_driver["rules"]:
                if isinstance(r, dict) and "id" in r:
                    rules_map[str(r["id"])] = r
        ordered_rules = tool_driver.get("rules", []) if isinstance(tool_driver, dict) else []

        results = run.get("results", [])
        if not isinstance(results, list):
            continue

        for res in results:
            if not isinstance(res, dict):
                continue
            report.processed_count += 1
            indexed_rule: dict[str, Any] = {}
            rule_index = res.get("ruleIndex")
            if isinstance(rule_index, int) and not isinstance(rule_index, bool) and 0 <= rule_index < len(ordered_rules):
                candidate_rule = ordered_rules[rule_index]
                if isinstance(candidate_rule, dict):
                    indexed_rule = candidate_rule
            raw_rule_id = res.get("ruleId")
            if raw_rule_id is None:
                raw_rule_id = indexed_rule.get("id", "unknown")
            raw_rule_id_text = str(raw_rule_id)
            rule_meta = rules_map.get(raw_rule_id_text, {})
            rule_id = _safe(raw_rule_id_text, 500)
            if not rule_meta:
                rule_meta = indexed_rule
            rule_name = _safe(rule_meta.get("name") or res.get("ruleName") or rule_id, 500)

            # Determine level
            level = res.get("level")
            if not level or level not in ("critical", "error", "warning", "note", "none"):
                # Check defaultConfiguration in rule_meta
                def_config = rule_meta.get("defaultConfiguration", {}) if isinstance(rule_meta, dict) else {}
                level = def_config.get("level", "warning") if isinstance(def_config, dict) else "warning"

            level = str(level).lower()
            properties = res.get("properties", {})
            security_severity: float | None = None
            rule_properties = rule_meta.get("properties", {}) if isinstance(rule_meta, dict) else {}
            if isinstance(properties, dict):
                raw_security_severity = properties.get("security-severity")
                raw_problem_severity = properties.get("problem.severity") or properties.get("severity")
                if raw_security_severity is None and isinstance(rule_properties, dict):
                    raw_security_severity = rule_properties.get("security-severity")
                if raw_problem_severity is None and isinstance(rule_properties, dict):
                    raw_problem_severity = rule_properties.get("problem.severity") or rule_properties.get("severity")
                try:
                    security_severity = float(raw_security_severity) if raw_security_severity is not None else None
                except (TypeError, ValueError):
                    security_severity = None
                if str(raw_problem_severity).lower() == "critical":
                    level = "critical"
            if security_severity is not None and security_severity >= 9.0:
                level = "critical"

            # Message
            msg = ""
            msg_obj = res.get("message")
            if isinstance(msg_obj, dict):
                msg = msg_obj.get("text", "")
            elif isinstance(msg_obj, str):
                msg = msg_obj
            msg = _safe(msg)

            # Suppressions
            suppressions = res.get("suppressions")
            is_suppressed = bool(
                isinstance(suppressions, list)
                and any(
                    isinstance(suppression, dict)
                    and suppression.get("status", "accepted") == "accepted"
                    for suppression in suppressions
                )
            )

            # Location
            file_path = ""
            start_line = 0
            start_column = 0
            locations = res.get("locations")
            if isinstance(locations, list) and locations:
                first_loc = locations[0]
                if isinstance(first_loc, dict):
                    phys_loc = first_loc.get("physicalLocation")
                    if isinstance(phys_loc, dict):
                        art_loc = phys_loc.get("artifactLocation")
                        if isinstance(art_loc, dict):
                            file_path = _safe(art_loc.get("uri", ""), 1000)
                        region = phys_loc.get("region")
                        if isinstance(region, dict):
                            start_line = int(region.get("startLine", 0))
                            start_column = int(region.get("startColumn", 0))

            finding = SarifFinding(
                rule_id=rule_id,
                level=level,
                message=msg,
                file_path=file_path,
                start_line=start_line,
                start_column=start_column,
                rule_name=rule_name,
                tool_name=tool_name,
                is_suppressed=is_suppressed,
            )
            if not is_suppressed:
                if level == "critical":
                    report.critical_count += 1
                    report.error_count += 1
                elif level == "error":
                    report.error_count += 1
                elif level == "warning":
                    report.warning_count += 1
                elif level == "note":
                    report.note_count += 1

            if len(report.findings) < MAX_SARIF_FINDINGS:
                report.findings.append(finding)
            else:
                worst_index = max(range(len(report.findings)), key=lambda index: _finding_priority(report.findings[index]))
                if _finding_priority(finding) < _finding_priority(report.findings[worst_index]):
                    report.findings[worst_index] = finding

    report.tools = sorted(tools_seen)
    report.omitted_count = max(0, report.processed_count - len(report.findings))
    report.truncated = report.omitted_count > 0
    return report


def parse_sarif_artifact(path: str | Path) -> NormalizedSarifReport | None:
    """Read and parse a SARIF JSON file safely."""
    p = Path(path)
    if not p.exists() or p.is_symlink():
        return None
    raw_bytes = _read_artifact(p)
    if raw_bytes is None:
        return None
    if b"<!DOCTYPE" in raw_bytes.upper():
        return None  # Security invariant: reject DOCTYPE

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(data, dict) and ("$schema" in data or "version" in data or "runs" in data):
            if "runs" in data:
                return parse_sarif_dict(data, source=str(p))
    except Exception:
        return None
    return None
