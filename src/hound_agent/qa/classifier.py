"""QA intelligence: classification of test outcomes against historical evidence.

Classifications:
- ``new_failure``: failed in the candidate run, but was 100% passing in baseline / history (no historical failures).
- ``known_failure``: failed in candidate and consistently failed (100% or very high failure rate >= 0.8) historically.
- ``retry_recovered``: failed in attempt 1, passed in attempt >= 2 in the same run (flaky pass).
- ``historically_flaky``: historical failure rate is between (0.05, 0.80) with multiple passes and failures, or previous retry recoveries.
- ``flaky_suspect``: candidate failure has intermittent failure pattern or dedup recurrence pattern across consecutive runs.
- ``environment_specific``: failures strongly correlate with a single environment dimension (>= 90% of failures in one environment while passing in others).
- ``likely_regression``: passed on baseline ref / historical baseline, but fails on candidate commit/branch.
- ``insufficient_history``: sample size is too small (< MIN_HISTORY_SAMPLES) to make a confident statistical claim.

Duration regression:
- Identifies tests whose candidate duration exceeds baseline median + 3 * IQR or p95 threshold with at least MIN_DURATION_SAMPLES.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from hound_agent.ingest.owners import resolve_owners
from hound_agent.qa.history import count_by_status, duration_stats, environment_breakdown, history_for_test
from hound_agent.qa.model import INSUFFICIENT_HISTORY, NormalizedTestResult

# Conservative minimum thresholds
MIN_HISTORY_SAMPLES = 5
MIN_DURATION_SAMPLES = 5
FLAKY_RATE_LOWER = 0.05
FLAKY_RATE_UPPER = 0.80
KNOWN_FAILURE_RATE_THRESHOLD = 0.80
DURATION_REGRESSION_RATIO = 2.0  # at least 2x baseline median duration
DURATION_REGRESSION_MIN_MS = 100  # avoid flagging sub-second microsecond noise

QA_CLASSIFICATIONS = {
    "passed",
    "new_failure",
    "known_failure",
    "retry_recovered",
    "historically_flaky",
    "flaky_suspect",
    "environment_specific",
    "likely_regression",
    "insufficient_history",
}


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ValueError("QA classification exceeded the gate deadline")


@dataclass
class EvidenceItem:
    description: str
    kind: str  # "supporting" | "contradicting"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class QAClassification:
    suite: str
    test: str
    decision: str  # One of QA_CLASSIFICATIONS
    confidence: str  # "high" | "medium" | "low"
    reason: str
    candidate_status: str
    sample_count: int
    historical_failure_rate: float | None
    duration_regression: bool = False
    duration_delta_ms: int | None = None
    duration_baseline_median_ms: int | None = None
    duration_candidate_ms: int | None = None
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradicting_evidence: list[dict[str, Any]] = field(default_factory=list)
    environment_correlation: dict[str, int] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    related_incidents: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "test": self.test,
            "decision": self.decision,
            "confidence": self.confidence,
            "reason": self.reason,
            "candidate_status": self.candidate_status,
            "sample_count": self.sample_count,
            "historical_failure_rate": self.historical_failure_rate,
            "duration_regression": self.duration_regression,
            "duration_delta_ms": self.duration_delta_ms,
            "duration_baseline_median_ms": self.duration_baseline_median_ms,
            "duration_candidate_ms": self.duration_candidate_ms,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "environment_correlation": self.environment_correlation,
            "evidence_refs": self.evidence_refs,
            "owners": self.owners,
            "related_incidents": self.related_incidents,
        }


def check_duration_regression(
    candidate_duration_ms: int | None,
    history_durations: dict[str, Any],
) -> tuple[bool, int | None, int | None]:
    """Check if candidate test duration represents a significant regression.

    Returns:
        (is_regression, delta_ms, baseline_median_ms)
    """
    if candidate_duration_ms is None or not history_durations:
        return False, None, None
    sample_count = history_durations.get("count", 0)
    if sample_count < MIN_DURATION_SAMPLES:
        return False, None, None
    median_ms = history_durations.get("median_ms", 0)
    p95_ms = history_durations.get("p95_ms", 0)

    # Significant regression: candidate is much larger than both median and p95
    # and greater than minimum absolute threshold
    delta_ms = candidate_duration_ms - median_ms
    if (
        candidate_duration_ms > median_ms * DURATION_REGRESSION_RATIO
        and candidate_duration_ms > p95_ms
        and delta_ms >= DURATION_REGRESSION_MIN_MS
    ):
        return True, delta_ms, median_ms
    return False, delta_ms if delta_ms > 0 else 0, median_ms


def classify_test_result(
    store_path: str | Path | None,
    candidate: NormalizedTestResult,
    attempts_in_run: list[NormalizedTestResult] | None = None,
    baseline_commit: str | None = None,
    days: int | None = None,
    deadline: float | None = None,
    repo_dir: str | Path | None = None,
    feedback_store_path: str | Path | None = None,
) -> QAClassification:
    """Classify a single test result against historical evidence and baseline.

    Args:
        store_path: Path to the SQLite history store (None if store unavailable)
        candidate: The test result from current run being evaluated
        attempts_in_run: Other attempts of this test in the same run (for retry detection)
        baseline_commit: Specific commit SHA to compare as baseline (e.g. main branch HEAD)
        days: Analysis window in days
        deadline: Monotonic deadline timestamp
        repo_dir: Repository path for CODEOWNERS resolution
        feedback_store_path: Optional path to feedback SQLite store for related incidents
    """
    suite = candidate.suite
    test = candidate.test
    status = candidate.status
    _check_deadline(deadline)

    owners: list[str] = []
    if repo_dir:
        owners = resolve_owners(repo_dir, [suite, f"{suite}/{test}"])

    related_incidents: list[dict[str, Any]] = []
    if feedback_store_path and Path(feedback_store_path).is_file():
        try:
            from hound_agent.feedback import read_feedback
            # Find reviewed feedback entries that match this suite/test or failure signature
            feedbacks = read_feedback(feedback_store_path, reviewed_only=True)
            for fb in feedbacks:
                pred_comp = fb.get("predicted_component", "")
                if suite in pred_comp or fb.get("dedup_key") == candidate.failure_signature:
                    related_incidents.append({
                        "feedback_id": fb.get("feedback_id"),
                        "run_id": fb.get("run_id"),
                        "actual_outcome": fb.get("actual_outcome"),
                        "actual_owner": fb.get("actual_owner"),
                        "actual_kind": fb.get("actual_kind"),
                        "actual_severity": fb.get("actual_severity") or fb.get("predicted_severity"),
                    })
        except Exception:
            pass

    # 1. Single-run retry recovery check (strongest flaky signal)
    if attempts_in_run:
        sorted_attempts = sorted(attempts_in_run, key=lambda a: a.attempt)
        has_earlier_failure = any(a.attempt < candidate.attempt and a.status in ("failed", "error") for a in sorted_attempts)
        if candidate.status == "passed" and has_earlier_failure:
            return QAClassification(
                suite=suite,
                test=test,
                decision="retry_recovered",
                confidence="high",
                reason=f"Test failed on attempt 1 and passed on attempt {candidate.attempt} within the same run",
                candidate_status=status,
                sample_count=len(attempts_in_run),
                historical_failure_rate=None,
                supporting_evidence=[
                    {
                        "type": "retry_pass",
                        "description": f"Failed attempt followed by pass attempt {candidate.attempt}",
                        "attempts": [a.to_dict() for a in sorted_attempts],
                    }
                ],
                owners=owners,
                related_incidents=related_incidents,
            )
        # If candidate is a failure but there is a later pass in the same run
        has_later_pass = any(a.attempt > candidate.attempt and a.status == "passed" for a in sorted_attempts)
        if candidate.status in ("failed", "error") and has_later_pass:
            return QAClassification(
                suite=suite,
                test=test,
                decision="retry_recovered",
                confidence="high",
                reason="Test failed on this attempt but recovered and passed on a subsequent attempt in the same run",
                candidate_status=status,
                sample_count=len(attempts_in_run),
                historical_failure_rate=None,
                supporting_evidence=[
                    {
                        "type": "retry_pass",
                        "description": "Subsequent attempt succeeded in the same run",
                        "attempts": [a.to_dict() for a in sorted_attempts],
                    }
                ],
                owners=owners,
                related_incidents=related_incidents,
            )

    # If no store is provided or test passed with no retry anomaly
    if store_path is None or not Path(store_path).exists():
        return QAClassification(
            suite=suite,
            test=test,
            decision=INSUFFICIENT_HISTORY,
            confidence="low",
            reason="No historical store available for QA classification",
            candidate_status=status,
            sample_count=0,
            historical_failure_rate=None,
            owners=owners,
            related_incidents=related_incidents,
        )

    # 2. Query history store
    counts = count_by_status(store_path, suite, test, days=days, deadline=deadline)
    _check_deadline(deadline)
    total_samples = sum(counts.values())
    failed_samples = counts["failed"] + counts["error"]
    denominator = failed_samples + counts["passed"]
    fail_rate = round(failed_samples / denominator, 6) if denominator > 0 else None
    history_rows = history_for_test(store_path, suite, test, limit=100, days=days, deadline=deadline)
    _check_deadline(deadline)
    dur_stats = duration_stats(store_path, suite, test, days=days, deadline=deadline)
    _check_deadline(deadline)
    env_breakdown = environment_breakdown(store_path, suite, test, deadline=deadline)
    _check_deadline(deadline)

    # Duration regression check
    is_dur_regr, dur_delta, dur_baseline_median = check_duration_regression(
        candidate.duration_ms, dur_stats
    )

    supporting: list[dict[str, Any]] = []

    # If test passed cleanly
    if status == "passed":
        if is_dur_regr:
            return QAClassification(
                suite=suite,
                test=test,
                decision="passed" if total_samples >= MIN_HISTORY_SAMPLES else INSUFFICIENT_HISTORY,
                confidence="high" if total_samples >= MIN_HISTORY_SAMPLES else "medium",
                reason="Test passed but exhibited a significant duration regression",
                candidate_status=status,
                sample_count=total_samples,
                historical_failure_rate=fail_rate,
                duration_regression=True,
                duration_delta_ms=dur_delta,
                duration_baseline_median_ms=dur_baseline_median,
                duration_candidate_ms=candidate.duration_ms,
                supporting_evidence=[{
                    "type": "duration_regression",
                    "description": f"Duration {candidate.duration_ms}ms is >2x baseline median {dur_baseline_median}ms",
                }],
                owners=owners,
                related_incidents=related_incidents,
            )
        return QAClassification(
            suite=suite,
            test=test,
            decision="passed" if total_samples >= MIN_HISTORY_SAMPLES else INSUFFICIENT_HISTORY,
            confidence="high" if total_samples >= MIN_HISTORY_SAMPLES else "low",
            reason="Test passed cleanly",
            candidate_status=status,
            sample_count=total_samples,
            historical_failure_rate=fail_rate,
            duration_regression=False,
            duration_delta_ms=dur_delta,
            duration_baseline_median_ms=dur_baseline_median,
            duration_candidate_ms=candidate.duration_ms,
            owners=owners,
            related_incidents=related_incidents,
        )

    # 3. Failure analysis: sample count threshold check
    if total_samples < MIN_HISTORY_SAMPLES:
        return QAClassification(
            suite=suite,
            test=test,
            decision=INSUFFICIENT_HISTORY,
            confidence="low",
            reason=f"Insufficient history samples ({total_samples} < {MIN_HISTORY_SAMPLES}) to classify failure reliably",
            candidate_status=status,
            sample_count=total_samples,
            historical_failure_rate=fail_rate,
            duration_regression=is_dur_regr,
            duration_delta_ms=dur_delta,
            duration_baseline_median_ms=dur_baseline_median,
            duration_candidate_ms=candidate.duration_ms,
            contradicting_evidence=[{
                "type": "insufficient_samples",
                "description": f"Only {total_samples} historical runs recorded",
                "counts": counts,
            }],
            owners=owners,
            related_incidents=related_incidents,
        )

    failed_count = counts["failed"] + counts["error"]
    passed_count = counts["passed"]

    # 4. Check Environment Specificity
    # If test failed and environment is known, check if failures only happen in this environment
    if candidate.environment and env_breakdown:
        env_failures = [
            r for r in history_rows
            if r.get("status") in ("failed", "error") and r.get("environment") == candidate.environment
        ]
        other_env_failures = [
            r for r in history_rows
            if r.get("status") in ("failed", "error") and r.get("environment") != candidate.environment
        ]
        other_env_passes = [
            r for r in history_rows
            if r.get("status") == "passed" and r.get("environment") != candidate.environment
        ]
        if len(env_failures) >= 3 and len(other_env_failures) == 0 and len(other_env_passes) >= 3:
            supporting.append({
                "type": "environment_clustering",
                "description": f"All {len(env_failures)} recorded failures occurred in environment '{candidate.environment}'",
                "env_breakdown": env_breakdown,
            })
            return QAClassification(
                suite=suite,
                test=test,
                decision="environment_specific",
                confidence="high",
                reason=f"Failures strictly isolate to environment '{candidate.environment}' with 0 failures in other environments",
                candidate_status=status,
                sample_count=total_samples,
                historical_failure_rate=fail_rate,
                duration_regression=is_dur_regr,
                duration_delta_ms=dur_delta,
                duration_baseline_median_ms=dur_baseline_median,
                duration_candidate_ms=candidate.duration_ms,
                supporting_evidence=supporting,
                environment_correlation=env_breakdown,
                owners=owners,
                related_incidents=related_incidents,
            )

    # 5. Baseline Comparison (Likely Regression vs Known Failure)
    if baseline_commit:
        baseline_rows = [r for r in history_rows if r.get("commit_sha") == baseline_commit]
        if baseline_rows:
            baseline_passed = any(r.get("status") == "passed" for r in baseline_rows)
            baseline_failed = any(r.get("status") in ("failed", "error") for r in baseline_rows)
            if baseline_passed and not baseline_failed:
                supporting.append({
                    "type": "baseline_passed",
                    "description": f"Test passed on baseline commit {baseline_commit}",
                    "baseline_rows": baseline_rows,
                })
                return QAClassification(
                    suite=suite,
                    test=test,
                    decision="likely_regression",
                    confidence="high",
                    reason=f"Test passed on baseline commit '{baseline_commit}' but fails on candidate commit",
                    candidate_status=status,
                    sample_count=total_samples,
                    historical_failure_rate=fail_rate,
                    duration_regression=is_dur_regr,
                    duration_delta_ms=dur_delta,
                    duration_baseline_median_ms=dur_baseline_median,
                    duration_candidate_ms=candidate.duration_ms,
                    supporting_evidence=supporting,
                    owners=owners,
                    related_incidents=related_incidents,
                )
            elif baseline_failed and not baseline_passed:
                supporting.append({
                    "type": "baseline_failed",
                    "description": f"Test already failed on baseline commit {baseline_commit}",
                    "baseline_rows": baseline_rows,
                })
                return QAClassification(
                    suite=suite,
                    test=test,
                    decision="known_failure",
                    confidence="high",
                    reason=f"Test was already failing on baseline commit '{baseline_commit}'",
                    candidate_status=status,
                    sample_count=total_samples,
                    historical_failure_rate=fail_rate,
                    duration_regression=is_dur_regr,
                    duration_delta_ms=dur_delta,
                    duration_baseline_median_ms=dur_baseline_median,
                    duration_candidate_ms=candidate.duration_ms,
                    supporting_evidence=supporting,
                    owners=owners,
                    related_incidents=related_incidents,
                )

    # 6. Statistical Classification (new_failure, known_failure, historically_flaky, flaky_suspect)
    # Check if historically 100% passed (New Failure)
    if failed_count == 0 or (fail_rate is not None and fail_rate == 0.0):
        supporting.append({
            "type": "pure_passing_history",
            "description": f"Zero failures observed across {total_samples} historical runs",
            "counts": counts,
        })
        return QAClassification(
            suite=suite,
            test=test,
            decision="new_failure",
            confidence="high" if total_samples >= 10 else "medium",
            reason=f"First failure observed; test passed in all {total_samples} prior recorded runs",
            candidate_status=status,
            sample_count=total_samples,
            historical_failure_rate=fail_rate,
            duration_regression=is_dur_regr,
            duration_delta_ms=dur_delta,
            duration_baseline_median_ms=dur_baseline_median,
            duration_candidate_ms=candidate.duration_ms,
            supporting_evidence=supporting,
            owners=owners,
            related_incidents=related_incidents,
        )

    # Known Failure (High consistent failure rate)
    if fail_rate is not None and fail_rate >= KNOWN_FAILURE_RATE_THRESHOLD:
        supporting.append({
            "type": "high_failure_rate",
            "description": f"Historical failure rate is {fail_rate:.1%} ({failed_count}/{total_samples})",
            "counts": counts,
        })
        return QAClassification(
            suite=suite,
            test=test,
            decision="known_failure",
            confidence="high" if total_samples >= 10 else "medium",
            reason=f"Known persistent failure with {fail_rate:.1%} historical failure rate across {total_samples} runs",
            candidate_status=status,
            sample_count=total_samples,
            historical_failure_rate=fail_rate,
            duration_regression=is_dur_regr,
            duration_delta_ms=dur_delta,
            duration_baseline_median_ms=dur_baseline_median,
            duration_candidate_ms=candidate.duration_ms,
            supporting_evidence=supporting,
            owners=owners,
            related_incidents=related_incidents,
        )

    # Historically Flaky (Intermittent pass and fail in history)
    if fail_rate is not None and FLAKY_RATE_LOWER <= fail_rate < FLAKY_RATE_UPPER:
        # Check if there are both passes and failures
        if passed_count >= 2 and failed_count >= 2:
            supporting.append({
                "type": "intermittent_history",
                "description": f"Observed {passed_count} passes and {failed_count} failures (rate: {fail_rate:.1%})",
                "counts": counts,
            })
            return QAClassification(
                suite=suite,
                test=test,
                decision="historically_flaky",
                confidence="high" if total_samples >= 10 else "medium",
                reason=f"Historically flaky with {fail_rate:.1%} failure rate ({failed_count} fails, {passed_count} passes)",
                candidate_status=status,
                sample_count=total_samples,
                historical_failure_rate=fail_rate,
                duration_regression=is_dur_regr,
                duration_delta_ms=dur_delta,
                duration_baseline_median_ms=dur_baseline_median,
                duration_candidate_ms=candidate.duration_ms,
                supporting_evidence=supporting,
                owners=owners,
                related_incidents=related_incidents,
            )

    # Flaky Suspect (Occasional failure < 5%, but not pure new failure)
    if fail_rate is not None and 0.0 < fail_rate < FLAKY_RATE_LOWER:
        supporting.append({
            "type": "rare_intermittent_failure",
            "description": f"Rare failure observed ({failed_count}/{total_samples}, rate: {fail_rate:.1%})",
            "counts": counts,
        })
        return QAClassification(
            suite=suite,
            test=test,
            decision="flaky_suspect",
            confidence="medium",
            reason=f"Infrequently failing test ({fail_rate:.1%} failure rate); suspect intermittent flake",
            candidate_status=status,
            sample_count=total_samples,
            historical_failure_rate=fail_rate,
            duration_regression=is_dur_regr,
            duration_delta_ms=dur_delta,
            duration_baseline_median_ms=dur_baseline_median,
            duration_candidate_ms=candidate.duration_ms,
            supporting_evidence=supporting,
            owners=owners,
            related_incidents=related_incidents,
        )

    # Fallback to likely regression if mostly passing (fail_rate low) or insufficient clarity
    if fail_rate is None:
        fail_rate_str = "unknown"
    else:
        fail_rate_str = f"{fail_rate:.1%}"

    return QAClassification(
        suite=suite,
        test=test,
        decision="likely_regression",
        confidence="medium",
        reason=f"Test failed with {fail_rate_str} historical failure rate",
        candidate_status=status,
        sample_count=total_samples,
        historical_failure_rate=fail_rate,
        duration_regression=is_dur_regr,
        duration_delta_ms=dur_delta,
        duration_baseline_median_ms=dur_baseline_median,
        duration_candidate_ms=candidate.duration_ms,
        supporting_evidence=[{"type": "failure_observed", "counts": counts}],
        owners=owners,
        related_incidents=related_incidents,
    )


def classify_run_results(
    store_path: str | Path | None,
    results: list[NormalizedTestResult],
    baseline_commit: str | None = None,
    days: int | None = None,
    deadline: float | None = None,
    repo_dir: str | Path | None = None,
    feedback_store_path: str | Path | None = None,
) -> list[QAClassification]:
    """Classify all test results from a run, grouping attempts by test identity."""
    # Group results by (suite, leaf test)
    attempts_by_identity: dict[tuple[str, str], list[NormalizedTestResult]] = {}
    for res in results:
        _check_deadline(deadline)
        key = (res.suite, res.test)
        attempts_by_identity.setdefault(key, []).append(res)

    classifications: list[QAClassification] = []
    # Classify each unique test using its latest attempt as candidate
    for (suite, test), attempts in attempts_by_identity.items():
        _check_deadline(deadline)
        latest = max(attempts, key=lambda a: a.attempt)
        classification = classify_test_result(
            store_path=store_path,
            candidate=latest,
            attempts_in_run=attempts if len(attempts) > 1 else None,
            baseline_commit=baseline_commit,
            days=days,
            deadline=deadline,
            repo_dir=repo_dir,
            feedback_store_path=feedback_store_path,
        )
        classification.evidence_refs = sorted({attempt.evidence_id for attempt in attempts if attempt.evidence_id})
        classifications.append(classification)

    return classifications
