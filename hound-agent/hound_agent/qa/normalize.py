"""Normalize runner evidence into the QA history model.

Supported evidence sources:

- ``FailedTest`` records from any supported runner text parser (pytest, Jest,
  Vitest, Go, RSpec, Cargo, dotnet) — failures only.
- JUnit/XML test reports — full pass/fail/skip/error plus durations and retry
  attempts (Surefire-style ``flakyFailure``/``rerunFailure`` children).
- pytest-json / generic test JSON reports — full outcome trees when present.

The stable identity is the ``(suite, leaf test)`` pair, so the same logical test
is tracked consistently across runners.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from defusedxml import ElementTree as ET

from hound_agent.ingest.redact import redact_text
from hound_agent.ingest.structured import MAX_ARTIFACT_BYTES, _read_artifact
from hound_agent.models import FailedTest
from hound_agent.qa.model import (
    NormalizedTestResult,
    failure_signature,
    normalize_runner,
    stable_test_identity,
    now_iso,
)


def _safe(value: object, limit: int = 300) -> str:
    redacted, _ = redact_text(str(value or "").strip()[:4000])
    return redacted[:limit]


def _duration_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(float(str(value).strip()) * 1000))
    except (TypeError, ValueError):
        return None


def _record(
    suite: str,
    test: str,
    status: str,
    attempt: int,
    duration_ms: int | None,
    runner: str,
    commit: str,
    branch: str,
    environment: str,
    message: str,
    run_id: str,
    evidence_id: str | None,
    recorded_at: str,
) -> NormalizedTestResult:
    return NormalizedTestResult(
        suite=_safe(suite),
        test=stable_test_identity(suite, test),
        status=status,
        attempt=max(1, int(attempt)),
        duration_ms=duration_ms,
        runner=normalize_runner(runner),
        commit=_safe(commit, 80),
        branch=_safe(branch, 120),
        environment=_safe(environment, 200),
        failure_signature=failure_signature(message),
        run_id=_safe(run_id, 160),
        evidence_id=_safe(evidence_id, 80) if evidence_id else None,
        recorded_at=recorded_at or now_iso(),
    )


def from_failed_tests(
    runner: str,
    run_id: str,
    commit: str,
    branch: str,
    environment: str,
    failed_tests: list[FailedTest],
    suite: str | None = None,
    evidence_id: str | None = None,
    recorded_at: str | None = None,
) -> list[NormalizedTestResult]:
    """Normalize failed-test records into history rows (attempt 1, status failed)."""
    results: list[NormalizedTestResult] = []
    for test in failed_tests:
        name = test.name or ""
        if not name:
            continue
        derived_suite = suite or (test.file or "unknown") or "unknown"
        results.append(
            _record(
                suite=derived_suite,
                test=name,
                status="failed",
                attempt=1,
                duration_ms=None,
                runner=runner,
                commit=commit,
                branch=branch,
                environment=environment,
                message=test.assertion or "",
                run_id=run_id,
                evidence_id=evidence_id,
                recorded_at=recorded_at or "",
            )
        )
    return results


def parse_junit_results(
    path: str | Path,
    run_id: str,
    commit: str,
    branch: str,
    environment: str,
    recorded_at: str | None = None,
) -> list[NormalizedTestResult]:
    """Parse a JUnit XML report into full pass/fail/skip/error history rows.

    Retry metadata (Surefire ``flakyFailure`` / ``rerunFailure`` children and
    repeated failure children) is expanded into attempt-numbered rows.
    """
    raw = _read_artifact(Path(path))
    if raw is None or b"<!DOCTYPE" in raw.upper():
        raise ValueError("JUnit report must be bounded and must not declare a DOCTYPE")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"could not parse JUnit XML: {exc}") from exc

    results: list[NormalizedTestResult] = []
    seen_cases = 0
    for case in root.iter():
        if case.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        seen_cases += 1
        name = case.attrib.get("name") or "unknown"
        suite = case.attrib.get("classname") or case.attrib.get("file") or "unknown"
        duration = _duration_ms(case.attrib.get("time"))

        children = [child for child in case if child.tag.rsplit("}", 1)[-1] in {"failure", "error"}]
        flaky = next(
            (
                child
                for child in case
                if child.tag.rsplit("}", 1)[-1] in {"flakyFailure", "flakyError", "rerunFailure", "rerunError"}
            ),
            None,
        )
        skipped = next((child for child in case if child.tag.rsplit("}", 1)[-1] == "skipped"), None)

        if flaky is not None:
            message = flaky.attrib.get("message", "") or (flaky.text or "")
            results.append(
                _record(suite, name, "failed", 1, duration, "junit", commit, branch, environment, message, run_id, None, recorded_at or "")
            )
            results.append(
                _record(suite, name, "passed", 2, duration, "junit", commit, branch, environment, "", run_id, None, recorded_at or "")
            )
        elif children:
            for index, child in enumerate(children, start=1):
                status = "error" if child.tag.rsplit("}", 1)[-1] == "error" else "failed"
                message = child.attrib.get("message", "") or (child.text or "")
                results.append(
                    _record(suite, name, status, index, duration, "junit", commit, branch, environment, message, run_id, None, recorded_at or "")
                )
        elif skipped is not None:
            results.append(
                _record(suite, name, "skipped", 1, duration, "junit", commit, branch, environment, "", run_id, None, recorded_at or "")
            )
        else:
            results.append(
                _record(suite, name, "passed", 1, duration, "junit", commit, branch, environment, "", run_id, None, recorded_at or "")
            )

    if seen_cases == 0:
        raise ValueError("JUnit report contains no testcase elements")
    return results


def _outcome_of(node: dict) -> str | None:
    outcome = node.get("outcome") or node.get("status") or node.get("result")
    if not isinstance(outcome, str):
        return None
    outcome = outcome.strip().lower()
    mapping = {
        "passed": "passed", "pass": "passed", "success": "passed", "ok": "passed",
        "failed": "failed", "fail": "failed", "failure": "failed", "error": "error",
        "skipped": "skipped", "skip": "skipped", "pending": "skipped", "xfailed": "skipped",
        "rerun": "failed", "unknown": "unknown",
    }
    return mapping.get(outcome, "unknown")


def _walk_json_tests(
    node: object,
    runner: str,
    results: list[NormalizedTestResult],
    commit: str,
    branch: str,
    environment: str,
    run_id: str,
    recorded_at: str,
    suite_hint: str = "unknown",
    depth: int = 0,
) -> None:
    if depth >= 100:
        raise ValueError("test JSON exceeds the maximum nesting depth of 100")
    if isinstance(node, dict):
        outcome = _outcome_of(node)
        name = node.get("name") or node.get("test") or node.get("test_name") or node.get("id")
        if outcome is not None and name:
            if len(results) >= 10000:
                raise ValueError("test JSON exceeds the 10000 result limit")
            suite = str(node.get("classname") or node.get("file") or node.get("suite") or suite_hint)
            duration = _duration_ms(node.get("duration_ms") or node.get("duration") or node.get("time"))
            message = node.get("message") or node.get("error") or node.get("traceback") or ""
            if isinstance(message, dict):
                message = message.get("message", "") if isinstance(message.get("message"), str) else ""
            results.append(
                _record(
                    suite, str(name), outcome, 1, duration, runner, commit, branch,
                    environment, str(message), run_id, None, recorded_at or "",
                )
            )
        for key in ("tests", "testcases", "results", "children", "cases"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    _walk_json_tests(item, runner, results, commit, branch, environment, run_id, recorded_at, suite_hint, depth + 1)
        for key in ("testsuites", "suites"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    _walk_json_tests(item, runner, results, commit, branch, environment, run_id, recorded_at, suite_hint, depth + 1)
        # pytest-json-report "summary" style: nested dicts of outcomes
        summary = node.get("summary")
        if isinstance(summary, dict):
            for section in ("passed", "failed", "errors", "skipped"):
                items = summary.get(section)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            _walk_json_tests(
                                {**item, "outcome": "failed" if section == "errors" else section[:-1]},
                                runner, results, commit, branch, environment, run_id, recorded_at, suite_hint,
                                depth + 1,
                            )
    elif isinstance(node, list):
        for item in node:
            _walk_json_tests(item, runner, results, commit, branch, environment, run_id, recorded_at, suite_hint, depth + 1)


def parse_test_json_results(
    path: str | Path,
    run_id: str,
    commit: str,
    branch: str,
    environment: str,
    recorded_at: str | None = None,
) -> list[NormalizedTestResult]:
    """Parse pytest-json-report / generic test JSON into history rows."""
    source = Path(path)
    if source.is_symlink() or source.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("test JSON must not use symlinks and must be bounded")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"could not parse test JSON: {exc}") from exc

    results: list[NormalizedTestResult] = []
    runner = "pytest"
    meta = payload.get("metadata") if isinstance(payload, dict) else None
    if isinstance(meta, dict):
        collect = meta.get("collect")
        if isinstance(collect, dict) and collect.get("python_version"):
            runner = "pytest"
    _walk_json_tests(payload, runner, results, commit, branch, environment, run_id, recorded_at or "")
    if not results:
        raise ValueError("test JSON contains no test records")
    return results


def detect_runner(text: str, path: str | Path | None = None) -> str:
    """Best-effort runner detection from report content and filename."""
    if path is not None:
        suffix = Path(path).suffix.lower()
        if suffix == ".xml":
            return "junit"
        if suffix == ".sarif":
            return "unknown"
    lowered = (text or "").lower()
    if "pytest" in lowered or "short test summary info" in lowered:
        return "pytest"
    if "vitest" in lowered or re.search(r"^\s*run\s+v\d+\.\d+", lowered):
        return "vitest"
    if "jest" in lowered:
        return "jest"
    if "--- fail:" in lowered:
        return "go"
    if "panicked at" in lowered and "failures:" in lowered:
        return "cargo"
    if "rspec" in lowered or "rspec " in lowered:
        return "rspec"
    if ".cs:line" in lowered or ".cs" in lowered and "failed" in lowered:
        return "dotnet"
    return "unknown"


def import_artifact(
    path: str | Path,
    run_id: str,
    commit: str,
    branch: str,
    environment: str,
    runner: str | None = None,
    recorded_at: str | None = None,
) -> list[NormalizedTestResult]:
    """Normalize a single artifact (XML/JSON/log) into history rows."""
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"artifact not found: {source}")
    suffix = source.suffix.lower()
    if suffix == ".xml":
        return parse_junit_results(source, run_id, commit, branch, environment, recorded_at)
    if suffix == ".json":
        return parse_test_json_results(source, run_id, commit, branch, environment, recorded_at)
    if suffix in {".log", ".txt", ""}:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")[:2_000_000]
        except OSError as exc:
            raise ValueError(f"could not read log: {exc}") from exc
        detected = runner or detect_runner(text, source)
        failed = _parse_failed_tests(text)
        if not failed:
            raise ValueError("no failed tests could be parsed from the log")
        return from_failed_tests(
            detected, run_id, commit, branch, environment, failed,
            evidence_id=None, recorded_at=recorded_at,
        )
    raise ValueError(f"unsupported artifact type: {suffix}")


def _parse_failed_tests(text: str) -> list[FailedTest]:
    from hound_agent.ingest.tests import parse_failed_tests

    return parse_failed_tests(text)
