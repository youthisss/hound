# Hound Master Implementation Roadmap

## 1. Purpose and source of truth

This document is the execution roadmap for closing the Hound hardening backlog
without duplicating work in the current worktree.

- `docs/plans/hound-qa-devops-improvement-plan.md` remains the capability
  roadmap: **M1-M12**.
- The Master List **P0-P12** is the implementation, audit, and release-closure
  overlay for those milestones.
- This execution is single-session. The roadmap and
  `docs/requirements-matrix.md` are the active status records; the historical
  `SESSION_COORDINATION.md` file is not required for current work.

P0-P12 must not be treated as a second, independent product roadmap. A P item
closes gaps in one or more M milestones; it does not authorize reimplementing
capabilities that are already verified.

## 2. Status vocabulary

Every item uses one of these statuses:

| Status | Meaning |
|---|---|
| `missing` | No implementation or acceptable documented alternative exists. |
| `partial` | Some implementation exists, but an acceptance criterion is open. |
| `implemented` | Code and focused tests exist; final evidence is not yet complete. |
| `verified` | Acceptance criteria and applicable targeted checks pass. |
| `blocked` | Requires external infrastructure, operator action, or unavailable data. |
| `intentionally unavailable` | Explicitly outside product scope and documented. |

`implemented` is not equivalent to `complete`. A milestone is complete only
when its acceptance criteria, documentation, targeted evidence, and required
closure items are verified.

## 3. Milestone-to-closure mapping

| Product milestone | Capability | Master List closure |
|---|---|---|
| M1 | Evaluation harness and baselines | P1, P2, P8, P11 |
| M2 | Evidence, provenance, and schema | P1, P2, P8, P10, P11 |
| M3 | Feedback, calibration, and trust | P2, P4, P8, P10, P11 |
| M4 | Normalized QA results and history | P5, P9, P11 |
| M5 | Regression and flaky intelligence | P2, P5, P11 |
| M6 | Coverage, SARIF, and quality gates | P2, P5, P11 |
| M7 | Deployment context and timeline | P2, P6, P10, P11 |
| M8 | Kubernetes and Helm evidence | P6, P8, P11 |
| M9 | Release diff, metrics, traces, and SLO impact | P6, P8, P11 |
| M10 | Bounded source intelligence V1 | P2, P6, P8, P11 |
| M11 | Test impact and source intelligence V2 | P2, P4, P6, P11 |
| M12 | Delivery reliability, operations, scale, and pilot | P7, P8, P9, P11, P12 |

## 4. Execution order

### Phase 0 — Stabilize the current worktree

The current worktree is owned by one session. Keep the same sequencing and
targeted-verification discipline, but do not wait for or create parallel-session
handoffs.

1. Inspect the complete uncommitted diff before changing shared files.
2. Preserve existing work and resolve contradictions in place.
3. Map each change to P0-P12 and the affected M milestone.
4. Run targeted checks for the changed area; do not run the aggregate suite.

Exit condition: no untracked ownership conflict remains and every change has an
owner, milestone mapping, and focused verification result.

### Phase 1 — Baseline and contract matrix

#### P0 — Restore runnable baseline

Verify the application is runnable and preserve existing fixes for dedup locks,
TUI lifecycle, and imports. Do not reimplement completed fixes.

Targeted gate:

```text
python -m compileall -q src/hound
hound --help
hound console --help
pytest tests/unit/test_dedup_critical_coverage.py -q
pytest tests/integration/test_dedup.py -q
```

#### P1 — Requirement and claim matrix

Create one crosswalk for FR-1..FR-33, NFR-1..NFR-9, CLI, TUI, server,
GitHub Action, Docker, schema, security, and trust policy:

```text
requirement → implementation → surface → test → status → evidence → open contradiction
```

Exit condition: every claim has an explicit status and no documentation claim
has no implementation or documented limitation.

### Phase 2 — Core and CLI closure

#### P2 — Core correctness

Close only real gaps in ingestion, structured parsing, classification,
stacktraces, failed tests, Git/source evidence, fallback, LLM validation,
triage, dedup, reports, feedback, timeline, and cost accounting.

Confirm that every claimed format and failure kind has positive, negative, or
explicitly unsupported coverage; healthy/unknown artifacts do not create false
positives or dedup state; offline output is deterministic; malformed LLM output
and invalid evidence references fail closed; and v1.4/v2.0 reports remain
compatible across loader, CLI, TUI, Markdown, and ticket rendering.

#### P3 — CLI closure

Verify the installed executable for `analyze`, `batch`, `console`, `log`, `gate`,
`insights`, `serve`, `doctor`, `init`, `config`, `providers`, `models`, `runs`,
`report`, `feedback`, and `clean`.

Close exit codes 0/1/2/3, clean JSON stdout, categorized actionable errors,
aliases, configuration command scope, delivery-ledger operations, and either a
minimal server client or explicit HTTP-only documentation.

P2 and P3 may proceed separately only when worktrees and file ownership do not
overlap.

### Phase 3 — TUI workflow closure

#### P4 — TUI foundation

Verify all workspaces and shared actions:

- Home (the default view): artifact/output paths, counts, mode, provider/model,
  trust, source, enrichment, readiness, and next action.
- Navigation workspaces: Artifacts and Results provide supported formats,
  filter/sort, pagination, row preview, selection, progress, partial failure,
  and stop-after-current behavior; Quality and Context are the other two
  navigation workspaces.
- Results tabs: stored-run indexing, navigation, report/ticket/raw views, copy,
  confirmation, and corrupt/legacy report handling. Tabs appear after a run is
  opened; Settings is an overlay and Feedback is a modal.
- Quality and Context: usable workflows within their stated bounds, validation,
  explicit uncertainty, and credential-safe display. Context validates the
  selected report and renders read-only readiness, audit, evidence-gap, and
  trust state; connector collection remains a pipeline/CLI concern.

Also verify worker lifecycle, keyboard/button action parity, responsive layout,
visible focus, non-color state cues, and graceful cleanup.

#### P5 — QA TUI

Add or verify history import from TUI with run metadata, retention input,
imported/skipped counts, test-list reload, and no raw-log persistence. Mark
export/retention administration as CLI-only where applicable. Policy selection
must validate before execution and show active rules. The TUI import action is
allowed to write normalized rows; the history label and documentation must not
describe that database as read-only.

#### P6 — DevOps TUI

Verify context validation, legacy migration display, connector readiness/audits,
observability correlation, release comparison, missing evidence, static versus
effective severity, customer impact, and fail-closed fork trust. Keep all
infrastructure operations read-only; never construct mutation commands. The
Context workspace may validate stored readiness and render audits, but connector
collection remains an explicitly bounded pipeline/CLI operation.

P5 and P6 may proceed in parallel only after P4 is stable and their file claims
are disjoint.

### Phase 4 — Reliability and security closure

#### P7 — Delivery and incident lifecycle

Verify reservation before network requests, stale `pending` to `unknown`,
explicit reconciliation, safe external IDs/URLs, read-only TUI delivery history,
and incident list/inspect/reuse/invalidation operations. Draft generation remains
separate from automatic delivery.

#### P8 — Security and privacy closure

Audit redaction at LLM, persistence, delivery, logs, provider responses,
SQLite/GitHub output, and generated artifacts. Cover URL credentials/fragments/
ports/SSRF/redirects, path traversal, symlinks, archives, prompt/command
injection, source allowlists, hidden files, fork trust, keyring failure, and
cleanup markers. Review broad exception handling rather than masking corruption.

#### P9 — Persistence, concurrency, and recovery

Verify dedup JSON/SQLite, QA history, feedback, delivery ledger, server jobs,
model cache, and TUI preferences for concurrent writers, interruption, stale
locks, corruption, disk/permission errors, partial writes, retention,
migrations, backup/restore, restart, symlinks, entry pruning, and Windows.

HTTP dedup remains disabled and clearly rejected until conditional writes and
versioning are implemented.

Exit condition: no P7-P9 item is `missing` or unexplained `partial`.

### Phase 5 — Documentation synchronization

#### P10 — Synchronize product claims

Update README, PRD, architecture, usage, connector, recovery, delivery,
changelog, and milestone audit documentation to match the matrix. Include the
actual CLI/TUI capability matrix, CLI-only features, read-only DevOps limits,
Python 3.10–3.12 support, and the real PyPI status. Add CI smoke checks for
documented commands where practical.

Do not retain fixed historical test counts as permanent claims.

### Phase 6 — Final repository gates

#### P11 — Final verification

Run this phase only after P0-P10 code-level work and all M1-M12 implementation
work are complete, ownership is reconciled, and the source snapshot is frozen.

Run once on that final snapshot:

1. compileall, Ruff, and mypy;
2. unit, integration, and non-network E2E/TUI suites;
3. full-suite coverage with the required 80% threshold;
4. offline evaluator and corpus validator;
5. secret and workflow scans;
6. strict dependency audit without undocumented ignores;
7. wheel/sdist build, Twine, clean installs, and CLI smoke;
8. Python 3.10/3.11/3.12 and Windows/Linux checks;
9. Docker, Action-contract, and Trivy checks when infrastructure is available;
10. version/tag equality, checksums, and provenance.

If a post-gate fix is required, return to targeted verification and freeze a
new final snapshot before repeating the aggregate gate.

### Phase 7 — Pilot and release readiness

#### P12 — External evidence

Stable release is blocked until:

1. TestPyPI/PyPI Trusted Publisher is configured.
2. At least two repositories supply 100–300 sanitized real failures.
3. Manual privacy/legal review is recorded.
4. Healthy controls and independently reviewed RCA outcomes are included.
5. Classification precision/recall, healthy false positives, false dedup,
   unknown rate, ticket edit rate, connector reliability, redaction escapes,
   latency, memory, and LLM cost are measured.
6. A release-readiness report records accepted risks, limitations, and GO/NO-GO.
7. Automatic delivery remains opt-in.

## 5. Single-session and Git rules

- One writer per file.
- Keep one worktree/branch for this implementation session.
- The active session is the only writer in the current worktree.
- Claim exact files and milestone scope before editing.
- Never reset, revert, or delete broad paths to resolve conflicts.
- Preserve uncommitted work from other sessions.
- Keep devil’s-advocate review read-only.
- Record files, behavior, tests, unrun tests, risks, blockers, and next action
  in the roadmap and requirements matrix; no handoff document is required.

## 6. Verification cadence

Before P11, run only targeted tests and applicable non-aggregate checks for the
changed area. Do not run full-suite or full-coverage for every patch or
intermediate milestone slice. The final aggregate gate is reserved for the
frozen post-M12 implementation snapshot.

Do not weaken test, coverage, lint, typing, audit, packaging, security, or
release thresholds to make a milestone appear complete.

## 7. Current single-session status

Status below reflects the current worktree on 2026-09-09. `verified` means the
roadmap acceptance criteria have passing targeted evidence; it does not replace
the final P11 aggregate gate.

| Master item | Status | Current evidence or open work |
|---|---|---|
| P0 | `verified` | `compileall`, root/console help, dedup critical coverage, and dedup integration checks pass. |
| P1 | `verified` | `docs/requirements-matrix.md` explicitly maps FR/NFR, surfaces, schema, security, trust, Docker, and release gates, including limitations. |
| P2 | `verified` | Parser, adversarial corpus, schema, RCA, triage, fallback, and compatibility targeted suites pass; offline evaluator check passes. |
| P3 | `verified` | All canonical command help checks pass, aliases and exit contracts are covered, and the bounded server client is tested. |
| P4 | `verified` | Focused acceptance checks cover Home, four navigation workspaces, result tabs, Settings/Feedback boundaries, Help discoverability, keyboard/button parity, focus/back behavior, responsive layout, lifecycle, and cleanup. |
| P5 | `verified` | Focused QA checks cover TUI import, retention input, normalized history reload/statistics, no raw-log history storage, active policy preview, pre-execution policy validation, gate outcomes, and CLI-only export/administration boundaries. |
| P6 | `verified` | Context validation/readiness checks cover current and legacy schema display, connector audit status, observability correlation, release comparison, evidence gaps, static/effective severity, customer impact, and fork trust fail-closed. The TUI remains read-only; collection stays pipeline/CLI-only. |
| P7 | `verified` | Delivery reservation, unknown reconciliation, verified-absence `mark-failed`, retry, incident administration, and server-job lifecycle checks pass. |
| P8 | `verified` | Redaction, URL/path/SSRF, exception, dependency, workflow, persistence, and fork-trust checks pass; the repository Trivy scan is fail-closed and a local HIGH/CRITICAL vulnerability-and-secret scan passes. |
| P9 | `verified` | Dedup, QA history, feedback, delivery, server restart/cancel, model cache, preferences, Windows, and concurrency targeted checks pass. |
| P10 | `verified` | Removed documentation was restored; README, usage, Action, recovery, delivery, support, limits, changelog, roadmap, matrix, milestone audit, and runnable demo claims match the implemented surfaces. Relative-link and command smoke checks pass. |
| P11 | `partial` | The current Windows snapshot passes compile, Ruff, mypy, full coverage, evaluator/corpus, dependency, repository Trivy, package/Twine, clean-install, CLI smoke, and Python 3.10/3.11/3.12 checks. Docker/Action image execution, image Trivy, Linux execution, and release-tag provenance remain unavailable. |
| P12 | `blocked` | Trusted Publisher setup, two-repository real-failure pilot, manual privacy/legal review, and release-readiness approval require operator evidence. |

P0-P10 have current local evidence. P11 remains `partial`: the repository scan
now passes with Trivy, but this host has no usable Docker daemon or Linux runner,
and the development snapshot has no release tag from which release provenance
could be verified. Those checks are not represented as synthetic successes.
Trusted Publisher setup, manual privacy/legal review, and the real two-repository
pilot remain `blocked`, never synthetic local success.
