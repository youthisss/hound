# Hound Agent QA/QC and DevOps Improvement Plan

## 1. Objective

Evolve Hound Agent from a CI/CD log analyzer into an evidence-backed quality and
deployment investigation assistant used daily by QA/QC and DevOps teams.

The product remains one modular monolith with one CLI, one core evidence model,
and one security boundary. It must remain read-only by default. Privileged
remediation, telemetry storage, and full test-management workflows remain
separate systems.

## 2. Product Promise

Hound should answer five questions with inspectable evidence:

1. What failed?
2. Is it a new regression, a known failure, a flaky test, or an environment issue?
3. What changed since the last healthy run or release?
4. Which source component and owner are most relevant?
5. What safe diagnostic action should an engineer take next?

## 3. Non-Goals

- Automatically modify source code or open fix PRs.
- Deploy, restart, rollback, apply Terraform, execute migrations, or mutate infrastructure.
- Replace observability platforms, test-management systems, or source-code search platforms.
- Send an entire repository or unrestricted raw logs to an LLM.
- Treat an LLM hypothesis or a static call graph as runtime truth.
- Build a public plugin ecosystem before internal connector contracts stabilize.

## 4. Architectural Direction

Retain the existing `ingest -> analyze -> triage -> output` pipeline and evolve it
incrementally. Do not perform a speculative repository-wide reorganization.
Introduce boundaries only when the first concrete feature requires them.

Target capability boundaries:

```text
hound_agent/
|- core evidence, provenance, confidence, schema, persistence
|- qa test history, regression, flaky analysis, coverage, quality gate
|- devops deployment context, timeline, release diff, operational impact
|- source bounded source resolution, changes, ownership, related tests
|- connectors bounded read-only Kubernetes, Helm, metrics, and trace adapters
|- policy quality-gate and trust-policy evaluation
`- output CLI/TUI/report/ticket adapters
```

All adapters must return sanitized structured evidence. Connectors must not
construct an RCA or deliver tickets directly.

## 5. Global Invariants

These conditions apply to every milestone:

- Existing `hound analyze`, `hound batch`, `hound log`, TUI, server, and report
  behavior remains supported unless a documented schema migration says otherwise.
- Offline analysis remains deterministic and requires no network.
- Repository-local configuration is never auto-loaded from an analyzed repository.
- Untrusted paths must pass repository containment checks; symlinks cannot escape roots.
- Secrets and PII are redacted before persistence, external delivery, or LLM use.
- Every inferred conclusion is distinguishable from observed facts.
- Every evidence item records provenance and observation time when available.
- Insufficient evidence is a valid result; Hound must not force a root-cause claim.
- External collection is bounded by time, item count, byte count, and timeout.
- DevOps collectors use read-only credentials and command/API allowlists.
- Delivery integrations are idempotent before automatic filing is recommended.
- No milestone is complete until docs, tests, lint, typing, and offline smoke checks pass.

## 6. Delivery Strategy

The plan is divided into 12 delivery milestones. Each milestone is an independently
valuable product increment, but larger milestones must be delivered as the listed
PR slices rather than one oversized change. Acceptance criteria apply to the full
milestone and must not be weakened when it is split. Use conventional commits and
follow `docs/workflow.md`.

Recommended PR slicing:

| Milestone | PR slices |
|---|---|
| M1 | Evaluation case contract; evaluator and baseline report; adversarial corpus |
| M2 | Evidence model; schema writer/validator; v1.4 reader compatibility; consumers |
| M3 | Feedback persistence/CLI; confidence calibration; trust policy |
| M4 | Normalized test model; SQLite history/migrations; queries and import/export |
| M5 | Flaky classifier; baseline regression classifier; duration/environment analysis |
| M6 | Coverage contract plus one format; remaining formats; SARIF consolidation; gate policy |
| M7 | Deployment context; causal event model; timeline and rendering |
| M8 | Connector contract/security; Kubernetes collector; Helm collector; sandbox contracts |
| M9 | Release diff; Prometheus connector; trace connector; SLO/runbook integration |
| M10 | Containment and limits; symbol extraction; git/owner/test evidence; LLM boundary |
| M11 | One-language call graph; test ranking; evaluation and UI/report integration |
| M12 | Delivery ledger; telemetry; fault injection; retention/typing; pilot report |

Every slice must leave the repository usable. Incomplete capability surfaces stay
disabled or explicitly experimental until their milestone exit criteria pass.

Dependency overview:

```text
M1 -> M2 -> M3
             |-> M4 -> M5 -> M6 ----|
             |-> M7 -> M8 -> M9 ----|-> M12
             `-> M10 -> M11 --------|
```

Parallel work:

- M4 (QA history), M7 (deployment context), and M10 (source V1) may start in
  parallel after M3 if they avoid shared core files.
- M5-M6 are serial because regression and quality gates depend on test history.
- M8-M9 are serial because collectors depend on the deployment evidence contract.
- M11 depends on source V1 and benefits from QA history/coverage data.
- M12 is the final cross-capability hardening and pilot gate.

## 7. Milestones

### M1 - Evaluation Harness and Baselines

**Purpose:** Make quality measurable before changing analysis behavior.

**Context:** The current test suite verifies functionality with local fixtures,
but it does not report classification precision/recall, dedup quality, or RCA
usefulness against independently labeled cases.

**Tasks:**

- Define a versioned, sanitized evaluation-case format containing artifact paths,
  expected stage/kind, primary event, failed tests, severity range, duplicate
  group, and expected redactions.
- Separate training/development fixtures from a held-out regression set.
- Implement an offline evaluation command or test utility that emits machine-readable
  per-case results and aggregate metrics.
- Measure stage/kind precision and recall, primary-event accuracy, failed-test
  extraction, stack-frame extraction, dedup precision/recall, redaction recall,
  unknown rate, throughput, and peak memory where practical.
- Add adversarial cases: healthy logs, ambiguous logs, chained failures,
  unsupported formats, misleading downstream errors, and secret-bearing logs.
- Record the current baseline without changing classifiers to improve the score.
- Document how production logs must be anonymized before joining the corpus.
- Register the evaluator as a documented project script or invoke it as a Python
  module; do not leave verification dependent on an undeclared executable.

**Likely areas:** `tests/fixtures/`, new `tests/eval/`, a small evaluation module or
script, `docs/prd.md`, `docs/architecture.md`, `docs/workflow.md`.

**Verification:**

```sh
uv run pytest -q
uv run python -m hound_agent.eval --offline --format json
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** A repeatable offline command reports baseline metrics and fails
on malformed labels or leaked expected secrets. The held-out set is not used to
tune rules in the same change.

**Rollback:** Remove the evaluator entry point and fixtures; production behavior is untouched.

### M2 - Evidence, Provenance, and Uncertainty Schema

**Purpose:** Separate observations from interpretations and make every conclusion auditable.

**Context:** RCA schema v1.4 stores evidence as strings. It cannot reliably show
which parser, source location, artifact, metric, or trace produced a conclusion.

**Tasks:**

- Design the next schema version with typed `observed_facts`, evidence provenance,
  hypotheses, supporting/contradicting evidence references, missing information,
  recommended checks, and confidence reasons.
- Keep deterministic facts from ingest separate from LLM-produced inference.
- Give evidence stable IDs scoped to a run; do not include secrets or raw PII in IDs.
- Add a numeric confidence score only after defining deterministic scoring inputs;
  retain the human-readable high/medium/low band.
- Publish JSON Schema and golden document fixtures.
- Add schema migration or explicit reader compatibility for stored v1.4 reports.
  This is a concrete persisted-data compatibility requirement.
- Add consumer contract tests for Markdown, ticket, TUI, stored-report, and JSON output.
- Ensure malformed LLM evidence references trigger fallback rather than partial trust.

**Likely areas:** `hound_agent/models.py`, `hound_agent/pipeline.py`,
`hound_agent/analyze/`, `hound_agent/output/`, `hound_agent/tui.py`, schema fixtures,
and architecture/PRD documentation.

**Verification:**

```sh
uv run pytest -q
uv run pytest tests/test_models.py tests/test_pipeline.py tests/test_report.py -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Every rendered hypothesis references structured evidence or is
explicitly marked unsupported/insufficient. Existing stored v1.4 reports remain readable.

**Rollback:** Keep the v1.4 writer active behind the schema boundary and remove the
new writer only; never delete existing stored reports.

### M3 - Feedback, Calibration, and Trust Policy

**Purpose:** Learn from engineers without silently self-modifying production behavior.

**Tasks:**

- Add structured feedback for root-cause usefulness, kind, severity, owner, and
  duplicate correctness plus the confirmed actual outcome when known.
- Store feedback separately from dedup state with audit metadata and no raw secret content.
- Add CLI support to record and export feedback; TUI support may follow after CLI stabilizes.
- Turn reviewed feedback into candidate regression fixtures through an explicit process,
  never automatic rule mutation.
- Calibrate confidence bands against the evaluation set and document their meaning.
- Add trust policy by source class (trusted branch, fork PR, local artifact) controlling
  source context, enrichment, LLM access, and external delivery.
- Default untrusted fork analysis to offline, no source enrichment, and no delivery.

**Likely areas:** new feedback/policy modules, `hound_agent/config.py`,
`hound_agent/cli.py`, persistence helpers, docs, and tests.

**Verification:**

```sh
uv run pytest -q
uv run hound feedback --help
uv run hound config show --json
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Feedback can be recorded, exported, and traced to a run without
changing future classification. Trust-policy tests prove forbidden capabilities do not run.

**Rollback:** Disable feedback ingestion and trust profiles while retaining stored
feedback as inert data.

### M4 - Normalized Test Results and Historical Store

**Purpose:** Give QA/QC reliable cross-run test history.

**Tasks:**

- Define stable test identity and normalized result fields: suite, test, status,
  attempt, duration, runner, commit, branch, environment dimensions, and failure signature.
- Normalize JUnit, pytest, Jest/Vitest, Go, RSpec, Cargo, and dotnet evidence into this model.
- Add a SQLite history backend with WAL, atomic upserts, retention, and schema migrations.
- Avoid storing duplicate raw logs; reference run/evidence IDs instead.
- Add queries for pass/fail/retry counts, failure rate windows, first/last seen,
  duration median/p95, and environment correlation inputs.
- Define missing-history behavior explicitly as `insufficient_history`.
- Add import/export for sanitized history to support CI cache or shared-volume workflows.

**Likely areas:** `hound_agent/ingest/tests.py`, `hound_agent/ingest/structured.py`,
new `hound_agent/qa/` modules, config, CLI, tests.

**Verification:**

```sh
uv run pytest tests/test_tests.py tests/test_structured.py -q
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** The same logical test is tracked consistently across supported
runners, concurrent writes are safe, and retention does not corrupt aggregates.

**Rollback:** Preserve the history database but stop writing it; core analysis remains functional.

### M5 - Regression and Flaky-Test Intelligence

**Purpose:** Distinguish actionable regressions from known or intermittent noise.

**Tasks:**

- Classify results as `new_failure`, `known_failure`, `retry_recovered`,
  `historically_flaky`, `flaky_suspect`, `environment_specific`,
  `likely_regression`, or `insufficient_history`.
- Use conservative, documented thresholds and minimum sample sizes.
- Compare candidate branch/commit against an explicit baseline; never silently infer a baseline.
- Preserve current retry-then-pass evidence as a strong flaky signal.
- Report supporting and contradicting historical evidence.
- Add duration-regression detection with robust statistics and minimum sample requirements.
- Evaluate false-flaky and false-regression rates; prioritize precision over recall.
- Add owner and related-incident context without auto-quarantining tests.

**Likely areas:** `hound_agent/qa/`, triage integration, output formatters, CLI/TUI reports.

**Verification:**

```sh
uv run pytest tests/qa -q
uv run python -m hound_agent.eval --offline --suite qa-history --format json
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Held-out regression and flaky precision meet an agreed threshold
(initial target 90%) and ambiguous cases return `insufficient_history` rather than guessing.

**Rollback:** Disable historical classification and retain existing single-run flaky detection.

### M6 - Coverage, SARIF Consolidation, and Quality Gate

**Purpose:** Turn QA evidence into an explainable release decision.

**Tasks:**

- Parse common coverage formats: Cobertura, JaCoCo, LCOV, coverage.py XML,
  Istanbul JSON, and dotnet coverage, added incrementally with fixtures.
- Compute total and changed-line coverage using an explicit baseline and repository diff.
- Consolidate test regressions, flaky status, coverage deltas, and SARIF findings.
- Add a deterministic policy engine separate from analysis results.
- Support block/warn/pass rules by new failure, severity, environment, critical SARIF,
  changed-line coverage, and duration regression.
- Reserve distinct machine-readable policy outcome fields; document exit-code behavior
  before changing CLI semantics.
- Generate a QA summary and evidence-backed defect draft.
- Do not skip tests based on impact analysis in this milestone.

**Likely areas:** new QA coverage/gate modules, `hound_agent/cli.py`, formatters,
output, config, tests, docs.

**Verification:**

```sh
uv run pytest tests/qa -q
uv run hound qa gate --help
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** The same evidence and policy always produce the same decision and
every block/warn reason is rendered. Analysis success is distinguishable from gate failure.

**Rollback:** Run policy in report-only mode; artifact parsing and RCA remain available.

### M7 - Explicit Deployment Context and Timeline

**Purpose:** Create a reliable DevOps investigation contract before querying infrastructure.

**Tasks:**

- Define and validate explicit deployment context: environment, service, cluster,
  namespace, workload, release, commit, image digest, strategy, and timestamps.
- Expand failure events with stable IDs and causal links from primary to downstream events.
- Build a deterministic timeline from CI metadata, logs, deployment context, and existing events.
- Represent clock uncertainty and missing timestamps rather than inventing order.
- Compare current and previous healthy release identity when explicitly supplied.
- Render deployment outcome, recovery, and customer-impact status separately.
- Keep legacy sidecars readable and provide migration documentation.

**Likely areas:** `hound_agent/models.py`, `hound_agent/ingest/context.py`,
`hound_agent/ingest/logs.py`, new DevOps modules, reports, tests.

**Verification:**

```sh
uv run pytest tests/test_cicd_intelligence.py tests/test_context.py -q
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Fixture deployments produce a stable timeline and distinguish
primary failure, downstream symptoms, recovery, and unknown impact.

**Rollback:** Render existing event lists and ignore timeline fields while preserving stored data.

### M8 - Bounded Kubernetes and Helm Evidence Bundle

**Purpose:** Collect actionable deployment evidence safely and read-only.

**Tasks:**

- Formalize a connector contract returning sanitized evidence with provenance.
- Implement Kubernetes/Helm collection using direct process invocation without a shell.
- Allowlist read-only operations such as get, describe, logs, events, status, and history.
- Deny exec, apply, patch, delete, scale, rollout mutation, upgrade, and rollback.
- Enforce namespace/resource restrictions, timeout, byte/item limits, and time windows.
- Collect workload state, ReplicaSet/pod state, termination reason, restart count,
  relevant events, probes, resource requests/limits, image digest, and Helm revision.
- Add audit records that omit credential values.
- Test command construction and malicious context values without requiring a live cluster.
- Add optional sandbox contract tests for a local disposable cluster outside default CI.

**Likely areas:** `hound_agent/ingest/enrich.py`, new connector boundary,
config/trust policy, tests, docs.

**Verification:**

```sh
uv run pytest tests/test_enrich.py tests/devops -q
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Tests prove no mutating command can be constructed, out-of-scope
resources are rejected, and partial collector failure does not lose local analysis.

**Rollback:** Disable external enrichment; log-only deployment analysis continues.

### M9 - Release Diff, Metrics, Traces, and SLO Impact

**Purpose:** Correlate deployment failures with change and runtime impact.

**Tasks:**

- Implement release comparison for commit range, image digest, manifests/Helm values,
  resource limits, migration version, runtime/dependency metadata, and feature-flag metadata.
- Never read secret values; compare approved metadata or versions only.
- Start with one metrics ecosystem and one trace contract, preferably Prometheus plus
  OpenTelemetry/Tempo-compatible data, before adding vendors.
- Query bounded pre/post-deployment windows and trace IDs already present in evidence.
- Record metric samples, query window, source, and uncertainty; do not claim causality
  from correlation alone.
- Resolve error spans, service boundaries, critical path, and service versions where available.
- Add SLO/error-budget evidence when supplied; derive effective severity from observed
  impact without discarding static severity.
- Add runbook mapping and service ownership from explicit trusted configuration.

**Likely areas:** new connectors and DevOps analysis modules, config, triage,
reports, tests.

**Verification:**

```sh
uv run pytest tests/devops tests/connectors -q
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** A fixture scenario correlates release diff, bounded metrics, and
trace evidence into one report while clearly labeling correlation and missing data.

**Rollback:** Disable individual connectors independently; timeline and local RCA remain available.

### M10 - Source Intelligence V1: Bounded Context

**Purpose:** Connect failures to trusted repository evidence without broad source disclosure.

**Tasks:**

- Extend existing source context from fixed surrounding lines to bounded function/symbol context.
- Resolve recognized stack frames and config references only after path containment validation.
- Add current-diff intersection, recent commit metadata, blame metadata, CODEOWNERS,
  and direct related-test references.
- Use language-aware parsing initially for languages represented by pilot users; retain
  safe text fallback for recognized files.
- Enforce max files, max total bytes, per-file bytes, suffix allowlist, excludes,
  no symlink escape, and no hidden secret/config files.
- Add `send_to_llm: false` by default for source evidence, independently configurable
  from local source analysis.
- Emit structured evidence and uncertainty rather than deciding root cause in the source layer.
- Add adversarial path, symlink, oversized-file, binary-file, and prompt-injection fixtures.

**Likely areas:** `hound_agent/ingest/stacktrace.py`, `hound_agent/pathutil.py`,
`hound_agent/ingest/git.py`, `hound_agent/ingest/owners.py`, new source modules,
config, tests.

**Verification:**

```sh
uv run pytest tests/test_source_context.py tests/test_stacktrace.py tests/test_git.py -q
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** A stack frame can be linked to a bounded symbol, changed lines,
owner, commit, and related test while prohibited paths never appear in output or prompts.

**Rollback:** Revert to the existing opt-in +/-2 line source context behavior.

### M11 - Source Intelligence V2 and Test Impact Recommendations

**Purpose:** Suggest likely execution relationships and relevant tests without unsafe test skipping.

**Tasks:**

- Add static caller/callee candidates with a strict depth limit for one pilot language first.
- Label every path `static_candidate`, never runtime-confirmed.
- Link changed symbols to historical test results and coverage data.
- Rank recommended tests by direct reference, coverage, dependency relation, and historical correlation.
- Explain why each test is recommended and expose missing coverage data.
- Evaluate recommendation recall against known changed-file/test pairs.
- Keep the feature advisory; do not alter which tests CI executes.
- Define the contract needed for future runtime trace-to-source mapping, but do not build
  organization-wide indexing or persistent language servers yet.

**Likely areas:** source and QA modules, reports/TUI, evaluation fixtures.

**Verification:**

```sh
uv run pytest tests/source tests/qa -q
uv run python -m hound_agent.eval --offline --suite test-impact --format json
uv run pytest -q
uv run ruff check .
uv run mypy hound_agent
```

**Exit criteria:** Recommendations meet a documented recall target on the evaluation
set and never claim an actual runtime path without trace evidence.

**Rollback:** Disable call-graph ranking and retain V1 contextual source evidence.

### M12 - Delivery Reliability, Observability, Scale, and Pilot Release

**Purpose:** Make the combined product safe to operate and prove value with real teams.

**Tasks:**

- Add delivery idempotency keys based on incident identity and destination.
- Persist a delivery ledger with pending, confirmed, failed, and unknown states plus
  external ticket/message IDs.
- Add reconciliation for ambiguous timeout-after-success outcomes.
- Add Hound metrics and structured logs: latency percentiles, queue depth/rejection,
  parser errors, unknown rate, fallback reasons, token/cost, redaction counts,
  dedup hits, connector errors, delivery failures, storage growth, and throughput.
- Add fault-injection tests for process death, disk full, SQLite lock/contention,
  duplicate concurrent incidents, connector timeout, partial output, and restart recovery.
- Add retention, dry-run cleanup, archive/export policy, and secure handling documentation.
- Tighten typing incrementally in critical modules currently excluded from mypy.
- Add permanent smoke/scale benchmarks for parser, redaction, history, SQLite,
  source analysis, and report rendering.
- Run a pilot on at least two repositories and 100-300 sanitized real failures.
- Measure triage time reduction, classification precision, false dedup, unknown rate,
  ticket edit rate, connector reliability, redaction escapes, and LLM cost per incident.
- Publish a release-readiness report and keep automatic issue filing opt-in until
  pilot targets are met.

**Likely areas:** output delivery adapters, server/service/pipeline telemetry,
persistence, cleanup CLI, test harnesses, docs.

**Verification:**

```sh
uv run ruff check .
uv run mypy hound_agent
uv run pytest --cov=hound_agent --cov-report=term --cov-fail-under=80 -q
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file audited-requirements.txt
uv run pip-audit --requirement audited-requirements.txt
uv run python demo_project/run_demo.py --profile smoke
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

**Exit criteria:** Pilot quality targets are documented and met or misses are explicitly
accepted. Delivery is idempotent, fault tests pass, no redaction escape is found, and
operators can diagnose Hound itself.

**Rollback:** Disable automatic delivery and external connectors independently;
retain offline analysis, QA history, and generated reports.

## 8. Recommended Product Surface

Preserve existing commands. Introduce capability commands only after their core
contracts stabilize:

```sh
hound qa analyze ./artifacts --baseline <ref> --repo .
hound qa gate ./artifacts --baseline <ref> --repo . --policy quality.yml
hound deploy investigate --context deployment.json
hound source inspect --run <run-id> --repo .
hound feedback <run-id> --root-cause correct
```

Subcommands must delegate to the same application service and pipeline. They must
not create independent RCA, redaction, dedup, or delivery implementations.

## 9. Security Requirements

- Source analysis is opt-in, local-first, and bounded.
- Remote endpoints require HTTPS except explicitly allowed loopback endpoints.
- Connector credentials are least-privilege and never rendered.
- Commands are invoked without a shell and validated against an argument allowlist.
- Fork PRs cannot trigger source reading, enrichment, LLM calls, or delivery by default.
- Evidence passed to an LLM is minimized and schema constrained.
- LLM output cannot create frames, facts, metric samples, or source references that do
  not resolve to collected evidence.
- Redaction tests cover multiline keys, encoded credentials, nested JSON, authorization
  headers, connection strings, split-line secrets, Unicode obfuscation, and custom patterns.
- Every external collection and delivery has an audit record without secret values.

## 10. Success Metrics

Initial release targets should be confirmed after M1 baseline measurement:

- At least 90% precision for supported failure kinds.
- At least 90% precision for `likely_regression` and `historically_flaky` decisions.
- False deduplication below 1% on the labeled corpus.
- Zero known secret escapes in the adversarial redaction corpus.
- 100% of hypotheses reference evidence or state insufficient support.
- Deterministic quality-gate decisions for identical inputs and policy.
- No mutating operation constructible through DevOps connectors.
- Automatic delivery produces no duplicate external ticket in retry tests.
- Offline p95 and scale targets are set from M1/M12 measured baselines, not guessed.
- Pilot teams show measurable median triage-time reduction.
- Ticket drafts require materially less editing than the pre-Hound baseline.

## 11. Release Gates

Each milestone must pass the repository verify gate in `docs/workflow.md`. In
addition:

- Schema changes require golden files, migration tests, and consumer contracts.
- Classifier changes require held-out evaluation deltas and false-positive review.
- New source access requires path/symlink/adversarial tests.
- New connectors require denylist/allowlist tests and bounded-output tests.
- New delivery behavior requires idempotency and timeout reconciliation tests.
- New persistence requires migration, contention, corruption, and retention tests.

## 12. Plan Mutation Protocol

When implementation evidence invalidates this plan:

1. Record the discovery and affected milestone in this document.
2. Do not weaken global invariants or release gates to preserve schedule.
3. Split a milestone when it spans multiple independently reviewable contracts.
4. Insert a prerequisite milestone when data contracts or security boundaries are missing.
5. Skip a milestone only with a documented reason and impact on dependent milestones.
6. Reorder only when the dependency graph remains valid.
7. Extract a separate service only after evidence of a different security boundary,
   scale profile, release cadence, ownership, or deployment lifecycle.

## 13. Immediate Next Step

Start with M1 only. Do not implement QA history, DevOps connectors, or advanced
source tracing until the current baseline and held-out evaluation process exist.
The first product decision after M1 is to choose pilot repositories and agree on
accuracy, privacy, latency, and operational targets with actual QA/QC and DevOps users.
