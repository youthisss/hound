"""Parse CI test and static-analysis artifacts without relying on log heuristics."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tracehound.models import FailedTest

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def _read_artifact(path: Path) -> bytes | None:
    """Read a bounded artifact so reports cannot exhaust the analyzer process."""
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def parse_structured_artifact(path: Path) -> tuple[str, str, str, str, list[FailedTest]] | None:
    if path.suffix.lower() == ".xml":
        return _parse_junit(path)
    if path.suffix.lower() == ".sarif":
        return _parse_sarif(path)
    if path.suffix.lower() == ".json":
        return _parse_test_json(path)
    return None


def _parse_junit(path: Path) -> tuple[str, str, str, str, list[FailedTest]] | None:
    try:
        raw = _read_artifact(path)
        if raw is None or b"<!DOCTYPE" in raw.upper():
            return None
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    tests: list[FailedTest] = []
    for case in root.iter():
        if case.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        failure = next((child for child in case if child.tag.rsplit("}", 1)[-1] in {"failure", "error"}), None)
        if failure is None:
            continue
        file = case.attrib.get("file", case.attrib.get("classname", ""))
        name = case.attrib.get("name", "unknown")
        message = failure.attrib.get("message", "") or (failure.text or "").strip()
        tests.append(FailedTest(name=name, file=file, assertion=message[:500]))
    if not tests:
        return None
    message = tests[0].assertion or f"{tests[0].name} failed"
    return "test", "test_failure", message[:200], message, tests


def _parse_sarif(path: Path) -> tuple[str, str, str, str, list[FailedTest]] | None:
    try:
        raw = _read_artifact(path)
        if raw is None:
            return None
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return None
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        driver = run.get("tool", {}).get("driver", {}) if isinstance(run.get("tool"), dict) else {}
        rules = driver.get("rules", []) if isinstance(driver, dict) else []
        default_levels = {
            str(rule.get("id")): str(rule.get("defaultConfiguration", {}).get("level", "warning"))
            for rule in rules if isinstance(rule, dict) and isinstance(rule.get("defaultConfiguration"), dict)
        }
        results = run.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            level = result.get("level") or default_levels.get(str(result.get("ruleId")), "warning")
            if level != "error":
                continue
            message_data = result.get("message", {})
            message = message_data.get("text", "static analysis error") if isinstance(message_data, dict) else str(message_data)
            return "build", "compilation_error", message[:200], message, []
    return None


def _parse_test_json(path: Path) -> tuple[str, str, str, str, list[FailedTest]] | None:
    """Support pytest-json-report, Playwright/Cypress-style result trees, and Go JSON."""
    try:
        raw_bytes = _read_artifact(path)
        if raw_bytes is None:
            return None
        raw = raw_bytes.decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return _parse_go_json(path)
    tests: list[FailedTest] = []
    _collect_json_failures(payload, tests)
    if not tests:
        return None
    message = tests[0].assertion or f"{tests[0].name} failed"
    return "test", "test_failure", message[:200], message, tests[:100]


def _parse_go_json(path: Path) -> tuple[str, str, str, str, list[FailedTest]] | None:
    """Go's `go test -json` emits newline-delimited JSON rather than one document."""
    try:
        raw = _read_artifact(path)
        if raw is None:
            return None
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, ValueError):
        return None
    failed: list[FailedTest] = []
    output: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        test = row.get("Test")
        if isinstance(test, str) and isinstance(row.get("Output"), str):
            output.setdefault(test, []).append(row["Output"])
        if row.get("Action") == "fail" and isinstance(test, str):
            failed.append(FailedTest(name=test, file=str(row.get("Package", "")), assertion="".join(output.get(test, []))[:500]))
    if not failed:
        return None
    message = failed[0].assertion or f"{failed[0].name} failed"
    return "test", "test_failure", message[:200], message, failed


def _collect_json_failures(value: object, tests: list[FailedTest], depth: int = 0) -> None:
    if depth >= 100 or len(tests) >= 100:
        return
    if isinstance(value, dict):
        outcome = str(value.get("outcome") or value.get("status") or value.get("state") or "").lower()
        failed = outcome in {"failed", "failure", "error", "fail"}
        if failed:
            name = str(value.get("nodeid") or value.get("fullTitle") or value.get("title") or value.get("name") or "unknown")
            file = str(value.get("file") or value.get("location", {}).get("file", "") if isinstance(value.get("location"), dict) else value.get("file", ""))
            detail = value.get("longrepr") or value.get("message") or value.get("error") or ""
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("stack") or ""
            tests.append(FailedTest(name=name, file=file, assertion=str(detail)[:500]))
        for child in value.values():
            _collect_json_failures(child, tests, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _collect_json_failures(child, tests, depth + 1)
