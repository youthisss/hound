# Milestone Audits

## M1 — Evaluation Harness and Baselines

- Exit status: passed on 2026-08-26.
- Code-review lane: initially `REQUEST CHANGES`; after fixes, `APPROVE` for the
  M1 contract. External review agents were unavailable because their account
  quota was exhausted, so both review lanes were completed locally.
- Architecture lane: `WATCH`. The evaluator boundary is safe and repeatable,
  but the seven-case baseline is intentionally small and reports dedup recall
  `0.0`; corpus growth and classifier improvements remain release work.
- Final synthesis: `COMMENT` because of the architecture watch item. This does
  not weaken the M1 exit criteria; it prevents treating the product as
  production-ready based on the harness alone.

Findings fixed:

1. `HIGH` — structured JSON/XML/SARIF fields could reach evaluation results
   without field-level redaction. Structured summaries, messages, and failed
   tests are now sanitized before evidence and fingerprints are built.
2. `HIGH` — a JSON evaluation artifact was discovered as if it were a label.
   Case discovery now excludes artifacts referenced by case documents.
3. `MEDIUM` — failed-test metrics compared runner-qualified node IDs against
   stable leaf IDs and incorrectly reported zero precision/recall.
4. `MEDIUM` — missing/unknown label fields and malformed frame values were not
   rejected consistently; the v1.0 label contract is now strict.
5. `MEDIUM` — a negative `primary_event` label matched even when an event was
   predicted; negative labels now require no predicted primary event.
6. `MEDIUM` — evaluation artifacts were read without an evaluator-level size
   bound; the structured-artifact byte ceiling is now enforced for all cases.
7. `MEDIUM` — Windows stale-lock liveness used `os.kill(pid, 0)`, which can
   report reaped processes as alive. Windows now probes a waitable process
   handle, preventing abandoned dedup locks from remaining permanent.
8. `LOW` — TUI tests wrote real user preferences and could hang in a restricted
   runner; persistence is isolated in those tests. Unused imports were removed.

Verification evidence:

- `uv run pytest --cov=hound_agent --cov-report=term --cov-fail-under=80 -q`:
  456 passed, 5 skipped, 83.52% coverage.
- `uv run python -m hound_agent.eval --offline --format json`: exit 0; committed
  deterministic snapshot at `tests/eval/baseline-v1.0.json`.
- Held-out-only evaluator: exit 0.
- `uv run ruff check .`: clean.
- `uv run mypy src/hound_agent`: clean across 35 source files.

## M2 - Evidence, Provenance, and Uncertainty Schema

- Exit status: passed on 2026-08-26.
- Code-review lane: initially `REQUEST CHANGES`; after fixes, `APPROVE` for
  the M2 contract. External review agents remained unavailable because their
  account quota was exhausted, so both review lanes were completed locally.
- Architecture lane: `CLEAR`. New writes are v2.0, persisted v1.4 reports stay
  readable, and the legacy `root_cause` projection provides a bounded consumer
  migration path.
- Final synthesis: `APPROVE` for M2. This approval covers the milestone only;
  later QA, DevOps, hardening, and pilot gates remain open.

Findings fixed:

1. `HIGH` - the published JSON Schema constrained only `analysis`, leaving all
   other report sections effectively untyped. The normative schema now covers
   the complete v2.0 document with closed objects and bounded enums/types.
2. `HIGH` - a reused dedup snapshot carried run-scoped evidence IDs into a new
   run, where the same counter could identify different evidence. Reused
   hypotheses now clear old citations and explicitly report unsupported current
   evidence until re-analysis.
3. `MEDIUM` - the v1.4 golden fixture contained the newer `meta.llm` field and
   did not prove compatibility with an older persisted document. The legacy
   reader now requires v2-only telemetry only for v2.0, and the fixture omits it.
4. `MEDIUM` - oversized prompt fitting could truncate evidence IDs after using
   its string budget on duplicated raw artifact text. Evidence is prioritized
   and citation/classification keys are preserved by the fitter.
5. `MEDIUM` - deterministic confidence used exact path equality for diff/frame
   correlation. It now uses the shared normalized suffix-aware path matcher.
6. `LOW` - a collector test mocked the shared analysis service with an invalid
   partial document. It now uses the v2.0 golden contract, preserving strict
   stored-report validation.

Verification evidence:

- Focused consumer/schema gate: 93 passed across models, RCA, pipeline, report,
  cost-control, and TUI tests.
- Post-review regression gate: 21 passed.
- Full suite: 462 passed, 5 skipped.
- `uv run ruff check src tests`: clean.
- `uv run mypy src/hound_agent`: clean across 35 source files.
- JSON syntax check for `docs/schema/rca-v2.0.schema.json`: clean.

## M3 - Feedback, Calibration, and Trust Policy

- Exit status: passed on 2026-08-26.
- Code-review lane: `APPROVE`. The feedback store is isolated from dedup state,
  reviewed feedback exports explicit candidate-fixture manifests instead of
  mutating classifiers, and the trust policy fails closed for untrusted forks
  before any optional capability runs.
- Architecture lane: `WATCH`. Confidence calibration is implemented and
  documented, but the seven-case corpus gives zero support for the `high` band;
  band accuracy claims remain provisional until reviewed feedback outcomes join
  the corpus.
- Final synthesis: `COMMENT` because of the architecture watch item. This does
  not weaken the M3 exit criteria; it prevents treating the calibration numbers
  as production claims before the corpus grows.

Findings fixed:

1. `MEDIUM` - the `hound feedback` CLI, trust policy (`--source-class`,
   `trust.source_class`, `TH_SOURCE_CLASS`), and confidence-band calibration
   were implemented but undocumented. `docs/guides/usage.md` now covers feedback and
   trust policy workflows, `docs/architecture.md` documents the trust profiles,
   feedback store, and calibration meaning, and `docs/prd.md` adds FR-30/31/32.
2. `LOW` - the committed baseline snapshot predated confidence calibration and
   did not record band support or empirical accuracy. `tests/eval/baseline-v1.0.json`
   now includes the calibration block with explicit limitations.

Verification evidence:

- `uv run pytest tests/e2e/test_eval.py tests/integration/test_feedback.py tests/unit/test_trust.py -q`:
  20 passed.
- Full suite: 472 passed, 5 skipped.
- `uv run hound feedback --help`: exit 0; `record` and `export` subcommands
  (including `--candidate-fixtures`) available.
- `uv run hound config show --json`: exit 0; includes `trust.source_class`,
  `source_context`, `enrichment`, `llm`, `delivery`.
- `uv run python -m hound_agent.eval --offline --format json`: exit 0; reports
  `confidence_calibration` per band.
- `uv run ruff check .`: clean.
- `uv run mypy src/hound_agent`: clean across 37 source files.

## M4 — Normalized Test Results and Historical Store

- Exit status: passed on 2026-08-26.
- Code-review lane: `APPROVE`. The history store is isolated from dedup and
  feedback state (`<out>/.hound-agent/history.sqlite3`), uses WAL plus atomic
  `ON CONFLICT` upserts keyed by `(suite, test, run_id, attempt)`, and never
  stores raw logs — rows reference `run_id`/`evidence_id` instead. Import is
  bounded and rejects DOCTYPE XML and symlinked sources.
- Architecture lane: `CLEAR`. The `(suite, leaf test)` identity is runner-
  agnostic (pytest `path::test`, JUnit `class.method`, Go package-level tests,
  and JSON reports all reduce to the same leaf), and JUnit flaky/rerun metadata
  expands into attempt-numbered rows so aggregates stay comparable.
- Final synthesis: `APPROVE` for M4. Insufficient-history behavior is explicit
  (`insufficient_history`, `failure_rate=None`); later M5/M6 consumers depend on
  that contract.

Findings fixed:

1. `HIGH` - the history schema used the SQLite reserved keyword `commit` as a
   column name, breaking every write with `near "commit": syntax error`. The
   column is renamed `commit_sha` across schema, upsert, query, export, and
   import paths.
2. `MEDIUM` - JUnit tests with dotted full names (for example
   `tests.test_checkout.test_cart_total`) did not reduce to the same leaf as
   pytest text output. `stable_test_identity` now strips `.`, `::`, `#`, `/`,
   and `\` separators, keeping cross-runner identity consistent.
3. `MEDIUM` - Vitest reports were not detected because the runner marker is a
   `RUN vX.Y.Z` header rather than the literal string "vitest". Detection now
   matches the header pattern.

Verification evidence:

- `uv run pytest tests/unit/test_tests.py tests/integration/test_qa_history.py -q`: passed.
- Full suite: 493 passed, 5 skipped.
- `uv run hound insights --help`: exit 0; `import`, `history`, `tests`, `stats`,
  `export` subcommands available.
- `uv run hound insights import tests/fixtures/junit_flaky.xml --output-dir <tmp>`: exit 0;
  flaky test recorded as failed(1) + passed(2); `stats` reports `failure_rate`
  0.5 with attempt metadata.
- Concurrent-write test: 4 threads upsert 200 rows into one WAL store with no
  lost updates (verified in `tests/integration/test_qa_history.py`).
- Retention test: deleting rows older than the window leaves recomputed
  aggregates intact (0.75 before, 0.50 after pruning).
- `uv run ruff check .`: clean.
- `uv run mypy src/hound_agent`: clean across 41 source files.

## M5 — Regression and Flaky-Test Intelligence

- Exit status: passed on 2026-08-27.
- Code-review lane: `APPROVE`. The classifier cleanly distinguishes `new_failure`, `known_failure`,
  `retry_recovered`, `historically_flaky`, `flaky_suspect`, `environment_specific`,
  `likely_regression`, and `insufficient_history`. Minimum sample sizes (`MIN_HISTORY_SAMPLES=5`)
  and conservative thresholds ensure precision over speculative recall.
- Architecture lane: `CLEAR`. Integrates with the M4 historical SQLite store without modifying existing
  analysis pipelines. Evaluation suite `qa-history` achieves 100% precision and recall on held-out cases.
- Final synthesis: `APPROVE` for M5. CLI `hound insights analyze` provides inspectable QA decision output.

Findings fixed:
1. `MEDIUM` - SQLite write locking contention under concurrent multi-threaded writes on Windows was resolved
   with busy timeouts and retry loops.
2. `LOW` - Reused identifier variable in CLI import command was cleaned up for strict type checking.

Verification evidence:
- `uv run pytest tests/integration/test_qa_history.py tests/integration/test_qa_classifier.py -v`: 33 passed.
- `uv run python -m hound_agent.eval --offline --suite qa-history --format json`: 100% precision/recall across 7 cases.
- `uv run hound insights analyze --help`: command available and documented.
- `uv run ruff check .`: clean.
- `uv run mypy src/hound_agent`: clean across 43 source files.

## Production Maturity Repository Gate — 2026-08-31

- Repository implementation status: passed. External publication and pilot
  evidence remain separate release approvals and are not claimed here.
- Server operations now provide safe text/JSON logs, configurable levels,
  request/job correlation, response `X-Request-ID`, bounded client tracking,
  SIGTERM shutdown, and tested loopback proxy guidance.
- Unit, integration, e2e, slow, and network taxonomy is active. CI separates
  fast required checks from scheduled/manual extended gates and aggregates the
  result. The Action failure smoke explicitly requires exit code 1.
- Dependabot, dependency policy, expanded threat model, repository/artifact/image
  scans, TestPyPI OIDC workflow, clean wheel/sdist smoke, Windows, Docker, Action,
  provenance, and protected release jobs are defined.
- Damaged jobs, history, and delivery SQLite stores preserve original files in
  timestamped recovery directories. Backup/restore and release checklists are
  documented.
- Scale evidence: 5,000 inputs produced 5,000 reports in 196.412 seconds on the
  documented Windows runner (`docs/benchmarks/benchmark-2026-08-31.md`).

Local verification:

- Full suite: 654 passed, 6 skipped, 85.84% coverage.
- `uv run ruff check .`: clean.
- `uv run mypy src/hound_agent`: clean across 64 source files.
- Dependency audit: no known vulnerabilities.
- Wheel and source distribution: build, Twine metadata, outside-checkout clean
  installation, import, version, and doctor checks passed.

External release gates still requiring operator infrastructure:

- Docker/Action/Trivy jobs must run on the configured GitHub runner because this
  workstation has no Docker runtime.
- TestPyPI and PyPI environments, Trusted Publisher identities, tag ruleset, and
  branch/environment reviewers must be configured in GitHub/PyPI.
- The mandatory two-repository, 100-300-real-failure pilot must be completed and
reviewed using `docs/operations/pilot-evidence-template.md`.
