# Hound requirement matrix

This is the source-of-truth mapping for the master implementation list. A
requirement is not treated as release evidence merely because its code exists:
the evidence column names the local check, while operator-dependent checks are
explicitly marked unavailable until their real evidence is supplied.

Capability-row status values are `Implemented`, `Partial`, `Missing`, and
`Intentionally unavailable`. `Intentionally unavailable` is used only where the
product keeps an unsafe or external capability outside the repository, such as
live pilot data or publication credentials. The master-item snapshot below also
uses `verified` and `blocked` from the roadmap vocabulary; those statuses are
not inferred from code existence alone.

## Master implementation status — 2026-09-09

| Master item | Status | Evidence or open condition |
|---|---|---|
| P0 | `verified` | Compile, root/console help, and dedup baseline checks pass. |
| P1 | `verified` | FR/NFR, surface, schema, security, trust, Docker, and release crosswalk is explicit, with limitations recorded. |
| P2 | `verified` | Parser, schema, RCA, triage, fallback, compatibility, and offline evaluator checks pass. |
| P3 | `verified` | Canonical command help, aliases, exit contracts, delivery administration, and bounded server client are covered. |
| P4 | `verified` | Focused acceptance checks cover Home, four navigation workspaces, result tabs, Settings/Feedback boundaries, Help discoverability, keyboard/button parity, focus/back behavior, responsive layout, lifecycle, and cleanup. |
| P5 | `verified` | Focused QA checks cover TUI import, retention input, normalized history reload/statistics, no raw-log history storage, active policy preview, pre-execution policy validation, gate outcomes, and CLI-only export/administration boundaries. |
| P6 | `verified` | Context validation/readiness checks cover current and legacy schema display, connector audit status, observability correlation, release comparison, evidence gaps, static/effective severity, customer impact, and fork trust fail-closed. The TUI remains read-only; collection stays pipeline/CLI-only. |
| P7 | `verified` | Delivery recovery, incident administration, and server-job lifecycle checks pass. |
| P8 | `verified` | Local redaction, URL/path, symlink, trust, persistence, exception, dependency, and fail-closed Trivy repository checks pass. |
| P9 | `verified` | Persistence corruption, concurrency, retention, restart, cancellation, preference, and duplicate-import checks pass. |
| P10 | `verified` | Restored product docs, command/workflow smoke coverage, relative links, and runnable demo match implemented surfaces; external gates remain unclaimed. |
| P11 | `partial` | Current Windows gates pass through coverage, evaluator/corpus, dependency audit, fail-closed repository Trivy, packaging/Twine, clean installs, CLI smoke, and Python 3.10-3.12. Docker/Action image execution, image Trivy, Linux execution, and release-tag provenance remain unavailable. |
| P12 | `blocked` | Trusted Publisher setup, reviewed two-repository pilot, manual privacy/legal review, and release approval require operator evidence. |

P11 and P12 are release-closure statuses. They must not be marked complete by
counting targeted local tests or synthetic corpus results as publication or
pilot evidence.

## Functional requirements

| Requirement | Implementation | Surface | Test | Status | Evidence | Contradictions or limits |
|---|---|---|---|---|---|---|
| FR-1 | `hound.ingest.logs.parse_log`, structured artifact adapters | CLI, TUI, server, Action, library | `tests/unit/test_fixtures.py`, `tests/unit/test_offline_accuracy.py` | Implemented | `uv run pytest tests/unit/test_fixtures.py tests/unit/test_offline_accuracy.py -q` | Unknown artifacts remain unknown and exit cleanly. |
| FR-2 | `hound.ingest.stacktrace` | CLI, TUI, server, Action, library | `tests/unit/test_stacktrace.py`, `tests/unit/test_offline_accuracy.py` | Implemented | Focused stacktrace tests | Source snippets remain opt-in and bounded. |
| FR-3 | `hound.ingest.tests.parse_failed_tests` | CLI, TUI, server, Action, library | `tests/unit/test_offline_accuracy.py`, `tests/unit/test_tests.py` | Implemented | Runner corpus tests | Unsupported runner output is not guessed. |
| FR-4 | `hound.ingest.git`, `hound.ingest.owners` | CLI, TUI, server, Action, library | `tests/integration/test_git.py`, `tests/integration/test_source_context.py` | Implemented | Git/source targeted checks | Repository path must be explicitly supplied. |
| FR-5 | `hound.analyze.llm`, provider/config boundary | CLI, TUI, server, library | `tests/unit/test_rca.py`, `tests/unit/test_production.py` | Implemented | LLM contract tests use local fakes | Network is opt-in. |
| FR-6 | `hound.analyze.fallback` | All analysis surfaces | `tests/unit/test_fixtures.py`, offline evaluator | Implemented | `uv run python -m hound.eval --offline --check --format json` | No external model is required. |
| FR-7 | `hound.triage.severity`, `hound.triage.component` | CLI, TUI, server, Action, library | `tests/unit/test_triage.py`, fixture pipeline tests | Implemented | Focused triage checks | Severity is evidence-based, not an incident policy decision. |
| FR-8 | `hound.triage.dedup.check_duplicate` | CLI, TUI, server, Action, library | `tests/integration/test_dedup.py` | Implemented | Dedup integration checks | HTTP backend is rejected because it lacks conditional writes. |
| FR-9 | `hound.output.report`, `hound.output.markdown`, `hound.output.tickets` | CLI, TUI, server, Action, library | `tests/unit/test_output.py`, pipeline tests | Implemented | Report writer checks | Stored report loading validates schema before rendering. |
| FR-10 | `hound analyze`, `hound batch` | CLI, Action, library | `tests/e2e/test_cli.py`, `tests/e2e/test_batch.py` | Implemented | CLI and batch E2E checks | Single-file `--log` layout remains a compatibility alias. |
| FR-11 | `_maybe_file` plus delivery ledger | CLI, server, library | `tests/integration/test_github.py`, delivery tests | Implemented | Delivery failures return exit 3 after analysis persistence | Delivery remains explicit opt-in. |
| FR-12 | `run_batch`, shared `TransportBudget` | CLI, library | `tests/e2e/test_batch.py`, `tests/unit/test_cost_control.py` | Implemented | Batch budget tests | Run IDs and timestamps are the only documented dynamic fields. |
| FR-13 | Dedup occurrence and flaky evidence tracking | CLI, TUI, server, library | `tests/integration/test_dedup.py`, offline accuracy tests | Implemented | Recurrence/flaky targeted checks | A retry-then-pass signal is required for flaky classification. |
| FR-14 | `hound.tui.RcaTui` | TUI | `tests/e2e/test_tui.py` | Implemented | TUI targeted suites | No infrastructure mutation, connector collection, or automatic delivery; bounded local history, feedback, and preferences writes are allowed. |
| FR-15 | `hound.ingest.redact` and bounded persistence writers | All surfaces | `tests/unit/test_production.py`, redaction tests | Implemented | Redaction targeted checks | `--allow-unredacted` is an explicit unsafe escape hatch. |
| FR-16 | `hound.source.context.collect_source_evidence` | CLI, TUI, server, library | `tests/integration/test_source_context.py` | Implemented | Source containment tests | Source evidence defaults to not sent to LLM. |
| FR-17 | `hound.ingest.logs.read_log_window` | All analysis surfaces | log ingestion tests | Implemented | Bounded ingestion checks | Head and tail windows are deterministic. |
| FR-18 | `hound.analyze.llm` retry/accounting | CLI, TUI, server, library | `tests/unit/test_production.py`, cost tests | Implemented | Retry and usage tests | Retry count and timeout are bounded. |
| FR-19 | File lock and SQLite dedup stores | CLI, TUI, server, library | `tests/unit/test_dedup_critical_coverage.py`, `tests/integration/test_dedup.py` | Implemented | Lock, corruption, contention checks | Stale locks require a provably dead PID. |
| FR-20 | GitHub/Jira/GitLab/Slack adapters | CLI, server, library | `tests/integration/test_github.py`, delivery tests | Implemented | Connector and delivery targeted checks | No automatic delivery is exposed in TUI. |
| FR-21 | `hound.server`, `hound.server_client` | Server, CLI client, library | `tests/integration/test_server_http.py` | Implemented | HTTP lifecycle and client checks | Server binds loopback only and has no shell or mutation endpoint. |
| FR-22 | Explicit `--config` loading | CLI, TUI, server, library | `tests/unit/test_config.py`, CLI contract tests | Implemented | Config boundary tests | Repository-local config is never auto-loaded. |
| FR-23 | `Dockerfile`, `Dockerfile.action`, `action.yml`, packaging metadata | Docker, Action, CLI | workflow contracts and packaging checks | Implemented | `uv build`, Twine, workflow definitions | Local Docker execution is unavailable in this environment. |
| FR-24 | Deterministic deployment and connector classifiers | CLI, TUI, server, library | `tests/integration/test_enrich.py`, DevOps tests | Implemented | Connector safety and classification checks | Collection is read-only and bounded. |
| FR-25 | Parallel batch, SQLite dedup, server queue, LLM concurrency | CLI, server, library | batch/server scaling tests | Partial | Targeted concurrency checks | Thousands-per-day production throughput still requires a measured pilot. |
| FR-26 | Dedup reuse, routing, call/cost budgets | CLI, TUI, server, library | `tests/unit/test_cost_control.py`, pipeline tests | Implemented | Budget and reuse checks | Reuse fails closed on context mismatch. |
| FR-27 | `hound.ingest.entity`, `RequestContext` | All analysis surfaces | entity and schema tests | Implemented | Request correlation tests | User identity is bounded and redacted. |
| FR-28 | Expanded offline parser corpus | All analysis surfaces | `tests/unit/test_offline_accuracy.py` | Implemented | Offline corpus checks | New heuristics require local fixtures. |
| FR-29 | `hound.eval` and versioned corpus | CLI, CI, library | `tests/e2e/test_eval.py`, `tests/unit/test_eval_corpus.py` | Implemented | Offline evaluator check | Corpus is sanitized and held-out cases stay separate. |
| FR-30 | `hound.feedback` | CLI, TUI, library | `tests/integration/test_feedback.py`, TUI feedback tests | Implemented | Feedback persistence checks | Feedback never mutates classifiers automatically. |
| FR-31 | `hound.trust` and config gates | CLI, TUI, server, Action, library | `tests/unit/test_trust.py` | Implemented | Fork fail-closed checks | Fork PRs cannot enable source, enrichment, LLM, or delivery. |
| FR-32 | Confidence bands and evaluator calibration output | CLI, report, library | evaluator and RCA tests | Implemented | Evaluation report check | Confidence is a band plus evidence-completeness score, not probability. |
| FR-33 | `hound.qa.history`, normalization, import/export | CLI, TUI, library | `tests/integration/test_qa_history.py`, QA CLI tests | Implemented | QA history targeted checks | Raw logs are never stored in history. |

## Non-functional requirements

| Requirement | Implementation | Surface | Test | Status | Evidence | Contradictions or limits |
|---|---|---|---|---|---|---|
| NFR-1 | Offline fixtures and network-free test policy | CI, library | pytest/evaluator suite | Implemented | Network markers and offline evaluator | Live provider tests are opt-in only. |
| NFR-2 | Deterministic fallback and exit mapping | CLI, server, library | RCA and CLI tests | Implemented | Focused fallback checks | Delivery failure is the explicit exit-3 exception. |
| NFR-3 | Stable offline pipeline | CLI, TUI, server, library | offline accuracy/evaluator tests | Implemented | Offline evaluator check | Run metadata is intentionally dynamic. |
| NFR-4 | `requires-python >=3.10,<3.13` | Packaging, CI | compatibility workflow and doctor | Implemented | `hound doctor --json` and CI matrix | Python 3.13 is rejected. |
| NFR-5 | LLM response validation and fallback | CLI, TUI, server, library | `tests/unit/test_rca.py`, model tests | Implemented | Malformed response regressions | Invalid evidence references are not trusted. |
| NFR-6 | Redaction before LLM, persistence, and delivery | All surfaces | redaction/security tests | Implemented | Secret-pattern targeted checks | Unredacted mode is explicit and warned. |
| NFR-7 | Bounded external request adapters | CLI, server, library | connector/delivery tests | Implemented | Timeout and ledger checks | External provider availability is not claimed locally. |
| NFR-8 | Bounded exponential LLM retry | CLI, TUI, server, library | retry/accounting tests | Implemented | LLM resilience checks | Exhaustion falls back unless `require_llm` is set. |
| NFR-9 | Dedup eviction-race upsert and persistence warning | CLI, TUI, server, library | critical dedup tests | Implemented | `record_triage` recovery tests | Persistence failure never suppresses the analysis result. |

## Surface contracts

| Contract | CLI | TUI | Server | Action | Status | Evidence |
|---|---|---|---|---|---|---|
| Analyze artifacts | Yes | Yes | Yes | Yes | Implemented | CLI/TUI/server/Action tests |
| Batch analysis | Yes | Yes | Via queue | Limited | Implemented | Batch and server lifecycle tests |
| QA history import | Yes | Yes | No | No | Implemented | QA import tests and TUI import tests |
| Quality gate | Yes | Yes | No | Optional | Implemented | QA gate tests |
| Feedback record | Yes | Yes | No | No | Implemented | Feedback and TUI tests |
| Feedback export | Yes | CLI only | No | No | Implemented | Feedback CLI tests |
| DevOps enrichment | Yes | Read-only report validation/readiness view | Yes | Optional | Implemented | Connector and DevOps tests cover bounded pipeline/CLI collection; TUI Context validates and renders stored evidence/audits without running connectors. |
| Ticket delivery | Yes | Status only | Yes through caller | Optional | Implemented | Delivery ledger and connector tests |
| Log capture | Yes | No | No | No | Implemented | Collector tests |
| Server lifecycle | Yes | No | N/A | No | Implemented | Server HTTP tests |
| Delivery administration | Yes, `delivery` (`list`, `inspect`, `reconcile`, `mark-failed`, `retry-failed`) | Read-only history | No | No | Implemented | Delivery admin tests; `mark-failed` requires an operator-confirmed absent remote object. |
| Incident administration | Yes, `incidents` | Read-only provenance | No | No | Implemented | Dedup admin tests |

## Release and pilot gates

| Gate | Implementation | Surface | Test | Status | Evidence | Operator dependency |
|---|---|---|---|---|---|---|
| RCA v2.0 plus v1.4 reader | `hound.models.validate` and JSON schema | All report consumers | model/schema compatibility tests | Implemented | Targeted schema checks | None for local code. |
| Docker runtime and Action image | Pinned Dockerfiles and workflow | Docker, Action | CI/release workflow | Partial | Workflow definitions and Dockerfile review | Docker daemon and Trivy are unavailable locally. |
| Clean wheel/sdist installation | CI package smoke jobs | CLI | package workflow | Partial | Build metadata and workflow | Requires clean CI environments. |
| Trusted Publisher publication | Release workflow OIDC jobs | PyPI/TestPyPI | workflow contract | Intentionally unavailable | No publication is claimed | Maintainer must configure PyPI projects and environments. |
| Two-repository pilot, 100-300 sanitized failures | Pilot evidence contract | Operations | template and readiness checklist | Intentionally unavailable | `docs/operations/pilot-readiness.md` | Requires reviewed real production data and humans. |
| Release-readiness report | Pilot template and checklist | Operations | operator review | Intentionally unavailable | Template remains unaccepted | Must be completed after the pilot; synthetic data cannot replace it. |
