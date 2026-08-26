"""Deterministic offline evaluation harness for labeled failure artifacts."""
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hound_agent.ingest.logs import extract_events, parse_log
from hound_agent.ingest.redact import redact_text
from hound_agent.ingest.stacktrace import parse_stacktrace
from hound_agent.ingest.structured import MAX_ARTIFACT_BYTES, parse_structured_artifact
from hound_agent.ingest.tests import parse_failed_tests
from hound_agent.analyze.fallback import build_root_cause
from hound_agent.models import CONFIDENCES, KINDS, SEVERITIES, STAGES, Artifacts, FailedTest, StackFrame, score_confidence
from hound_agent.triage.dedup import fingerprint
from hound_agent.triage.severity import classify

CASE_VERSION = "1.0"
DEFAULT_CORPUS = Path("tests/eval/cases")
BASELINE_PATH = Path("tests/eval/baseline-v1.0.json")
_TOP_LEVEL_FIELDS = {"eval_case_version", "id", "artifact", "expected"}
_EXPECTED_FIELDS = {
    "stage", "kind", "primary_event", "failed_tests", "stack_frames",
    "severity_range", "duplicate_group", "redactions",
}


@dataclass
class EvaluationCase:
    case_id: str
    split: str
    artifact: Path
    expected_stage: str
    expected_kind: str
    primary_event: dict[str, str] | None
    failed_tests: list[str]
    stack_frames: list[dict[str, Any]]
    severity_range: list[str]
    duplicate_group: str | None
    expected_redactions: list[str]


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def load_case(path: Path, corpus: Path) -> EvaluationCase:
    if path.is_symlink():
        raise ValueError(f"{path}: label must be a regular file, not a symlink")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("eval_case_version") != CASE_VERSION:
        raise ValueError(f"{path}: eval_case_version must be {CASE_VERSION}")
    if set(data) != _TOP_LEVEL_FIELDS:
        raise ValueError(f"{path}: fields must be exactly {sorted(_TOP_LEVEL_FIELDS)}")
    split = path.relative_to(corpus).parts[0] if path != corpus else ""
    if split not in {"dev", "held_out"}:
        raise ValueError(f"{path}: case must be under dev or held_out")
    case_id = data.get("id")
    artifact_name = data.get("artifact")
    expected = data.get("expected")
    if not isinstance(case_id, str) or not case_id or not isinstance(artifact_name, str) or not artifact_name:
        raise ValueError(f"{path}: id and artifact must be non-empty strings")
    if not isinstance(expected, dict):
        raise ValueError(f"{path}: expected must be an object")
    if set(expected) != _EXPECTED_FIELDS:
        raise ValueError(f"{path}: expected fields must be exactly {sorted(_EXPECTED_FIELDS)}")
    artifact = (path.parent / artifact_name).resolve()
    if path.parent.resolve() not in artifact.parents or not artifact.is_file() or artifact.is_symlink():
        raise ValueError(f"{path}: artifact must be a contained regular file")
    stage, kind = expected.get("stage"), expected.get("kind")
    if stage not in STAGES or kind not in KINDS:
        raise ValueError(f"{path}: expected stage or kind is invalid")
    primary = expected.get("primary_event")
    if primary is not None and (
        not isinstance(primary, dict)
        or primary.get("stage") not in STAGES
        or primary.get("kind") not in KINDS
    ):
        raise ValueError(f"{path}: primary_event must contain a valid stage and kind")
    frames = expected.get("stack_frames", [])
    if not isinstance(frames, list) or not all(
        isinstance(frame, dict)
        and set(frame).issubset({"file", "line", "function"})
        and isinstance(frame.get("file"), str)
        and isinstance(frame.get("line", 0), int)
        and not isinstance(frame.get("line", 0), bool)
        and frame.get("line", 0) >= 0
        and isinstance(frame.get("function", ""), str)
        for frame in frames
    ):
        raise ValueError(f"{path}: stack_frames must contain valid file/line/function values")
    severity_range = _strings(expected.get("severity_range", []), f"{path}: severity_range")
    if not severity_range or not set(severity_range).issubset(SEVERITIES):
        raise ValueError(f"{path}: severity_range must contain valid severities")
    duplicate_group = expected.get("duplicate_group")
    if duplicate_group is not None and (not isinstance(duplicate_group, str) or not duplicate_group.strip()):
        raise ValueError(f"{path}: duplicate_group must be a non-empty string or null")
    redactions = _strings(expected.get("redactions", []), f"{path}: redactions")
    if any(not secret for secret in redactions):
        raise ValueError(f"{path}: expected redactions cannot be empty")
    return EvaluationCase(
        case_id, split, artifact, stage, kind, primary,
        _strings(expected.get("failed_tests", []), f"{path}: failed_tests"),
        frames, severity_range, duplicate_group, redactions,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _classification_metrics(expected: list[str], predicted: list[str], labels: set[str]) -> dict[str, Any]:
    per_label: dict[str, dict[str, float | int]] = {}
    for label in sorted(labels | set(expected) | set(predicted)):
        tp = sum(e == label and p == label for e, p in zip(expected, predicted))
        fp = sum(e != label and p == label for e, p in zip(expected, predicted))
        fn = sum(e == label and p != label for e, p in zip(expected, predicted))
        per_label[label] = {"support": expected.count(label), "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    active = [item for item in per_label.values() if item["support"]]
    return {
        "accuracy": _ratio(sum(e == p for e, p in zip(expected, predicted)), len(expected)),
        "macro_precision": round(sum(float(item["precision"]) for item in active) / len(active), 6) if active else 0.0,
        "macro_recall": round(sum(float(item["recall"]) for item in active) / len(active), 6) if active else 0.0,
        "per_label": per_label,
    }


def _set_counts(expected: set[Any], predicted: set[Any]) -> tuple[int, int, int]:
    return len(expected & predicted), len(predicted - expected), len(expected - predicted)


def _frame_key(frame: StackFrame | dict[str, Any]) -> tuple[str, int, str]:
    if isinstance(frame, StackFrame):
        return frame.file, frame.line, frame.function or ""
    return str(frame.get("file", "")), int(frame.get("line", 0)), str(frame.get("function", ""))


def _test_key(name: str) -> str:
    """Compare stable test identity without requiring runner-specific path prefixes."""
    normalized = " ".join(name.replace("\\", "/").split())
    return normalized.rsplit("::", 1)[-1]


def _redact_failed_tests(tests: list[FailedTest]) -> list[FailedTest]:
    sanitized: list[FailedTest] = []
    for test in tests:
        name, _ = redact_text(test.name)
        file, _ = redact_text(test.file)
        assertion, _ = redact_text(test.assertion)
        sanitized.append(FailedTest(name=name, file=file, line=test.line, assertion=assertion))
    return sanitized


def _analyze_case(case: EvaluationCase) -> tuple[dict[str, Any], Artifacts]:
    try:
        size = case.artifact.stat().st_size
    except OSError as exc:
        raise ValueError(f"{case.case_id}: artifact cannot be inspected: {exc}") from exc
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"{case.case_id}: artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    raw = case.artifact.read_text(encoding="utf-8", errors="replace")
    for secret in case.expected_redactions:
        if secret not in raw:
            raise ValueError(f"{case.case_id}: expected redaction is absent from artifact")
    text, _ = redact_text(raw)
    leaked = [secret for secret in case.expected_redactions if secret in text]
    structured = parse_structured_artifact(case.artifact)
    if structured:
        stage, kind, summary, message, failed_tests = structured
        summary, _ = redact_text(summary)
        message, _ = redact_text(message)
        failed_tests = _redact_failed_tests(failed_tests)
    else:
        stage, kind, summary, message = parse_log(text)
        failed_tests = parse_failed_tests(text)
    frames = parse_stacktrace(text)
    events = extract_events(text, stage, kind, message)
    artifacts = Artifacts(log_text=text, stage=stage, kind=kind, summary=summary, message=message, frames=frames, failed_tests=failed_tests, events=events)
    severity, _ = classify(artifacts)
    primary = next((event for event in events if event.role == "primary"), None)
    result = {
        "id": case.case_id,
        "split": case.split,
        "expected": {"stage": case.expected_stage, "kind": case.expected_kind},
        "predicted": {"stage": stage, "kind": kind},
        "primary_event_match": (
            primary is None if case.primary_event is None else
            primary is not None and primary.stage == case.primary_event["stage"] and primary.kind == case.primary_event["kind"]
        ),
        "severity_match": severity in case.severity_range,
        "expected_failed_tests": case.failed_tests,
        "predicted_failed_tests": [test.name for test in failed_tests],
        "expected_stack_frames": [_frame_key(frame) for frame in case.stack_frames],
        "predicted_stack_frames": [_frame_key(frame) for frame in frames],
        "redactions_expected": len(case.expected_redactions),
        "redactions_leaked": len(leaked),
        "dedup_fingerprint": fingerprint(artifacts),
    }
    return result, artifacts


def _case_paths(corpus: Path) -> list[Path]:
    """Find case labels while allowing a case to reference a JSON artifact."""
    paths = sorted(corpus.glob("*/*.json"))
    referenced_artifacts: set[Path] = set()
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("artifact"), str):
            referenced_artifacts.add((path.parent / value["artifact"]).resolve())
    return [path for path in paths if path.resolve() not in referenced_artifacts]


def _confidence_calibration(results: list[dict[str, Any]]) -> dict[str, Any]:
    bands: dict[str, dict[str, float | int | None]] = {}
    for band in sorted(CONFIDENCES):
        selected = [result for result in results if result["confidence"]["band"] == band]
        support = len(selected)
        accuracy = _ratio(sum(result["classification_correct"] for result in selected), support) if support else 0.0
        mean_score = round(
            sum(result["confidence"]["score"] for result in selected) / support, 6
        ) if support else 0.0
        bands[band] = {
            "support": support,
            "empirical_accuracy": accuracy if support else None,
            "mean_deterministic_score": mean_score if support else None,
            "absolute_gap": round(abs(accuracy - mean_score), 6) if support else None,
        }
    unsupported = [band for band, values in bands.items() if values["support"] == 0]
    limitations = [
        "The corpus is small; confidence bands with zero support are provisional.",
        "Classification correctness is a proxy until reviewed root-cause outcomes are available.",
    ]
    if unsupported:
        limitations.append(f"No evaluation support for: {', '.join(unsupported)}.")
    return {
        "target": "exact stage-and-kind classification correctness proxy",
        "bands": bands,
        "limitations": limitations,
    }


def evaluate(corpus: Path = DEFAULT_CORPUS, suite: str = "all") -> dict[str, Any]:
    corpus = corpus.resolve()
    if suite not in {"all", "dev", "held_out"}:
        raise ValueError("suite must be all, dev, or held_out")
    paths = _case_paths(corpus)
    cases = [load_case(path, corpus) for path in paths]
    if suite != "all":
        cases = [case for case in cases if case.split == suite]
    if not cases:
        raise ValueError(f"no evaluation cases found in {corpus}")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be unique")

    tracemalloc.start()
    started = time.perf_counter()
    analyzed = [_analyze_case(case) for case in cases]
    results = [result for result, _ in analyzed]
    for result, artifacts in analyzed:
        band = build_root_cause(artifacts).confidence
        score, _ = score_confidence(artifacts)
        result["classification_correct"] = (
            result["expected"]["stage"] == result["predicted"]["stage"]
            and result["expected"]["kind"] == result["predicted"]["kind"]
        )
        result["confidence"] = {"band": band, "score": score}
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    failed_tp = failed_fp = failed_fn = frame_tp = frame_fp = frame_fn = 0
    for result in results:
        tp, fp, fn = _set_counts(
            {_test_key(name) for name in result["expected_failed_tests"]},
            {_test_key(name) for name in result["predicted_failed_tests"]},
        )
        failed_tp += tp
        failed_fp += fp
        failed_fn += fn
        tp, fp, fn = _set_counts(set(map(tuple, result["expected_stack_frames"])), set(map(tuple, result["predicted_stack_frames"])))
        frame_tp += tp
        frame_fp += fp
        frame_fn += fn

    group_by_id = {case.case_id: case.duplicate_group for case in cases}
    fingerprint_by_id = {result["id"]: result["dedup_fingerprint"] for result in results}
    dedup_tp = dedup_fp = dedup_fn = 0
    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            expected_same = group_by_id[left] is not None and group_by_id[left] == group_by_id[right]
            predicted_same = fingerprint_by_id[left] == fingerprint_by_id[right]
            dedup_tp += expected_same and predicted_same
            dedup_fp += not expected_same and predicted_same
            dedup_fn += expected_same and not predicted_same

    expected_stages = [case.expected_stage for case in cases]
    expected_kinds = [case.expected_kind for case in cases]
    predicted_stages = [result["predicted"]["stage"] for result in results]
    predicted_kinds = [result["predicted"]["kind"] for result in results]
    redaction_expected = sum(result["redactions_expected"] for result in results)
    redaction_leaked = sum(result["redactions_leaked"] for result in results)
    report = {
        "evaluation_version": CASE_VERSION,
        "suite": suite,
        "case_count": len(cases),
        "split_counts": dict(sorted(Counter(case.split for case in cases).items())),
        "metrics": {
            "stage": _classification_metrics(expected_stages, predicted_stages, STAGES),
            "kind": _classification_metrics(expected_kinds, predicted_kinds, KINDS),
            "primary_event_accuracy": _ratio(sum(result["primary_event_match"] for result in results), len(results)),
            "severity_range_accuracy": _ratio(sum(result["severity_match"] for result in results), len(results)),
            "failed_tests": {"precision": _ratio(failed_tp, failed_tp + failed_fp), "recall": _ratio(failed_tp, failed_tp + failed_fn)},
            "stack_frames": {"precision": _ratio(frame_tp, frame_tp + frame_fp), "recall": _ratio(frame_tp, frame_tp + frame_fn)},
            "dedup": {"precision": _ratio(dedup_tp, dedup_tp + dedup_fp), "recall": _ratio(dedup_tp, dedup_tp + dedup_fn)},
            "redaction_recall": _ratio(redaction_expected - redaction_leaked, redaction_expected) if redaction_expected else 1.0,
            "unknown_rate": _ratio(predicted_kinds.count("unknown"), len(predicted_kinds)),
            "throughput_cases_per_second": round(len(cases) / elapsed, 3) if elapsed else 0.0,
            "peak_memory_bytes": peak,
        },
        "confidence_calibration": _confidence_calibration(results),
        "cases": results,
    }
    serialized = json.dumps(report, sort_keys=True)
    if any(secret in serialized for case in cases for secret in case.expected_redactions):
        raise RuntimeError("expected secret leaked into evaluation report")
    if redaction_leaked:
        raise RuntimeError(f"{redaction_leaked} expected secret value(s) were not redacted")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="required; evaluation never uses the network")
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--suite", choices=("all", "dev", "held_out"), default="all")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args(argv)
    if not args.offline:
        parser.error("--offline is required")
    try:
        report = evaluate(args.corpus, args.suite)
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"evaluation failed: {exc}\n")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
