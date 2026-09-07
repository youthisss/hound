# RCA schema migration: v1.4 to v2.0

Hound writes RCA schema v2.0 and continues to read persisted v1.4
reports. Existing report files do not need an in-place migration.

## Reader and writer contract

- Writers always emit `schema_version: "2.0"`.
- `models.validate`, stored-report formatting, and Markdown rendering accept
  both v1.4 and v2.0.
- The v1.4 `root_cause` object remains in v2.0 as a compatibility projection.
- New consumers should use `analysis`; old consumers may keep reading
  `root_cause` during their migration window.

## New v2.0 fields

`analysis.observed_facts` contains deterministic extracted facts.
`analysis.evidence` assigns run-scoped counter IDs and records source type,
artifact, locator, collector, and observation time. `analysis.hypotheses`
references that evidence and records contradicting evidence, missing
information, recommended checks, a human confidence band, and a numeric score
derived only from deterministic observations. That score describes evidence
completeness, not the probability that a cause hypothesis is correct. Consumers
must also inspect support status, contradictions, and missing information.

Every hypothesis must either cite a resolvable evidence ID or declare
`unsupported`/`insufficient_evidence`. An LLM response containing unknown or
overlapping evidence references is discarded and deterministic fallback is
used.

## Incident identity and cached analysis

New incident keys use the `incident-v2:` prefix. Their identity includes project
scope and meaningful failure details, including named-test assertions or frame
paths. Old unscoped hashes remain readable in history but are not automatically
matched to new incidents. The first v2 occurrence therefore starts fresh rather
than inheriting a potentially unrelated diagnosis or delivery suppression.

An incident match alone does not authorize RCA reuse. State records also store
an independent analysis-context fingerprint covering evidence and analysis
inputs. A missing or mismatched fingerprint makes a snapshot ineligible. SQLite
adds this field on opening an older store; file entries without it are treated
the same way. Existing delivery history is retained. Changed or incomplete
context can increase provider calls, deliberately preferring fresh analysis to
reusing an unverified hypothesis.

## Compatibility verification

The normative v2.0 JSON Schema is `docs/schema/rca-v2.0.schema.json`. Golden
v1.4 and v2.0 documents under `tests/golden/` are exercised through validation,
stored-report formatting, and Markdown report rendering in `tests/unit/test_models.py`.
