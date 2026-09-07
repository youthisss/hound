# Pilot readiness report (M12)

## Status

Code-level M12 reliability controls are implemented, but the required external
pilot on two repositories and 100-300 sanitized real failures has **not been
executed in this workspace**. This is an explicitly recorded release-readiness
miss, not a synthetic success claim.

Automatic external filing therefore remains opt-in. A stable production release
must not claim pilot targets are met until reviewed pilot data is attached.

## Required pilot measurements

- median triage-time reduction
- healthy-log false-positive rate, with an explicit healthy-run denominator
- reviewed root-cause correctness and abstention rate, separate from failure-kind accuracy
- supported-kind and regression/flaky precision
- false deduplication and unknown rate
- ticket edit rate
- connector success/timeout/partial-failure rate
- redaction escapes (target: zero)
- LLM token and cost per incident
- delivery confirmed/unknown/duplicate outcomes
- storage growth and analysis throughput

## Dataset contract

Use at least two repositories and 100-300 failures, sanitized before ingestion.
Keep raw production logs outside this repository. Record only aggregate metrics,
fixture-safe examples, runner assumptions, Hound commit, configuration profile,
and accepted misses.

Record the reviewed aggregates using
[`pilot-evidence-template.md`](pilot-evidence-template.md). Do not replace real
pilot evidence with generated fixtures or the synthetic scale benchmark.

For triage-time comparisons, use matched tasks and record the baseline and
Hound-assisted time to the same reviewer-confirmed diagnosis. Report sample
counts and medians; do not infer time savings from processing latency. Review
cause hypotheses against the eventual fix or other independently collected
evidence. Count unsupported hypotheses separately from incorrect ones, and
break correctness down by confidence band and failure category. Include healthy
and unsupported artifacts so failure-only sampling cannot hide false alarms.

## Go/no-go

Go requires zero known redaction escapes, no duplicate confirmed delivery in
retry tests, documented precision/unknown results, and explicit acceptance of any
missed product targets. Until then, offline analysis and ticket drafts are the
recommended production surface.
