# PRD — Hound Agent

**Version:** 0.4.0 · **Schema:** RCA v2.0 (v1.4 reader compatible)

## 1. Problem Statement

CI/CD, build, and test failures are frequently left uninvestigated:

- No structured record of *why* a build failed.
- Duplicate tickets opened for the same recurring failure.
- Root-cause knowledge lives in heads and chat logs, not in the repo.
- Manual triage (severity, component, priority) is slow and inconsistent.

## 2. Goal

Hound Agent is a Python CLI and core library (`hound_agent`) that
auto-investigates a failure artifact:

```
log + repo context → parse → root cause analysis → triage → report + ticket draft
```

- **Offline-first:** fully functional with rule-based analysis when no LLM is configured.
- **Optional LLM:** any OpenAI-compatible endpoint; configurable base URL, key, and model.
- **CI-safe:** LLM failure silently falls back to rules; exit codes are deterministic.
- **Read-only:** never deploys, retries, rolls back, or mutates infrastructure.

## 3. Users

| User | Context | Core need |
|------|---------|-----------|
| Developer | Locally triaging a failing run | Quick report, ticket draft, dedup vs known issues |
| CI pipeline | Headless, no API key | Deterministic offline analysis and meaningful exit code |
| On-call engineer | Triaging a queue | Severity + component + dedup to prioritize work |

## 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Parse CI/CD/build/test log → stage (`ci`/`build`/`test`/`deploy`/`unknown`), failure kind, summary, message |
| FR-2 | Parse stacktrace into frames (file, line, function); recognize Python, C/C++, Go, Rust, compiler Java/TypeScript locations, Java runtime `at` frames, JavaScript V8 frames, C# `in file.cs:line N` frames, and YAML/TF/TPL deployment config references |
| FR-3 | Parse failed-test list (name, file, line, assertion message) from pytest, Jest/Vitest, Go test verbose, RSpec, Cargo test, and dotnet test output |
| FR-4 | Gather git context: branch, HEAD commit, changed files vs HEAD, and up to three latest commit subjects for changed files matching repository-contained stack frames |
| FR-5 | LLM analysis via any OpenAI-compatible API (base URL, key, and model overridable) |
| FR-6 | Deterministic rule-based fallback analysis (no network, no API key) |
| FR-7 | Triage: severity (`critical`/`high`/`medium`/`low`), component (YAML glob map), priority 1–5 |
| FR-8 | Dedup: normalized fingerprint → SHA-256; persists across runs in output directory; `is_duplicate_of` set on second occurrence; `recurring_incident` set at configurable threshold |
| FR-9 | Output: `report.json` + `report.md` + `ticket.md` into `--out` directory; unique opaque run directories (`run-<hex>`) prevent filename leakage |
| FR-10 | CLI: `hound analyze <LOG_DIRECTORY>` — scans `.log`, JUnit `.xml`, SARIF, and test-report `.json`; `--jobs N` for parallel analysis |
| FR-11 | Optional live issue filing: `--gh` (GitHub), `--jira` (Jira), `--gitlab` (GitLab); filing failures warn to stderr and exit `3`, never suppressing the analysis result |
| FR-12 | Batch: `hound batch --logs DIR [--jobs N] [--max-llm-calls N] [--max-cost-usd X]` — shared dedup state, `summary-<batch-id>.json`, `usage-<batch-id>.json`; deterministic run ordering |
| FR-13 | Recurring-incident detection: dedup state tracks occurrence count; repeated identical fingerprint at ≥ threshold (default 3) flagged `recurring_incident`; flaky detection requires explicit retry-then-pass evidence for the same pytest nodeid, Jest test, Go `-count` test, or JUnit `flakyFailure`/`rerunFailure` element |
| FR-14 | TUI: `hound tui [--logs DIR]` — browse logs, run analysis per-file or all-visible (`A`), view overview/report/ticket/raw-log panes |
| FR-15 | Secret/PII redaction: API keys, JWTs, passwords, connection strings, emails, IPs scrubbed from log text before LLM and before disk write; `meta.redacted` recorded; `--no-redact` / `redact: false` escape hatch |
| FR-16 | Opt-in source context: `--repo --source-context` attaches ±2 lines around recognized frames from repo-contained source and deployment config files; suffix allowlist prevents reading secrets files |
| FR-17 | Smart log windowing: oversized logs sliced as head+tail around failure markers, not a blind tail read |
| FR-18 | LLM resilience: exponential backoff retries on 429/5xx (`--max-retries` / `llm.max_retries`); prompt/completion token usage recorded in `meta.usage` |
| FR-19 | Dedup store: locked atomic file store (JSON, 1000-entry cap) or WAL-mode SQLite (`dedup.backend: sqlite`) with atomic `ON CONFLICT` upserts, `max_entries`, and `retention_days` pruning; evicted entries are upserted on `record_triage` so reuse snapshots are never silently lost |
| FR-20 | Issue-tracker integrations: Jira REST (`--jira`), GitLab Issues (`--gitlab`), Slack webhook (`--slack-webhook`); all warn-not-fail |
| FR-21 | Webhook server: `hound server --port` — stdlib HTTP; `/analyze` (POST, bearer auth), `/health` (GET), `/jobs/<id>` (GET), `/stats` (GET); configurable workers, queue, rate-limit, job-ttl; SQLite job store survives restarts |
| FR-22 | Explicit config only: YAML loaded via `--config`; repository-local config never auto-loaded |
| FR-23 | Distribution: `Dockerfile`, GitHub Action (`action.yml`), PyPI metadata in `pyproject.toml` |
| FR-24 | CD failure detection: Kubernetes rollout/readiness, OOM, crash loops, liveness/readiness probes, scheduling/quota, registry auth, config-missing, network, image-pull, Helm rollback, Terraform apply, migration, and permission failures; analysis is read-only |
| FR-25 | Scale to thousands of logs per day: parallel analysis, SQLite dedup backend, high-throughput server with persistent job store, deterministic run dirs and summaries, `llm.max_concurrency` throttling |
| FR-26 | Cost control: dedup-first LLM reuse (`dedup.reuse`, `dedup.reuse_after_occurrences`; reused runs tagged `meta.reused`/`meta.reused_from_key`), LLM routing by failure kind (`llm.routing: exclude-kinds` + `llm.skip_kinds`), batch budget guardrails (`--max-llm-calls`, `--max-cost-usd`), per-batch usage telemetry |
| FR-27 | Request/entity correlation: extract `request_id`, `trace_id`, `session_id`, `user_id`, distinct users (max 10), and HTTP `method`/`path` from the bounded raw log window; publish as `context.request` in RCA schema v2.0 (and retain v1.4 reader compatibility); redacted before LLM and output; excluded from dedup fingerprints |
| FR-28 | Offline detection accuracy: failed-test parsing for Jest/Vitest, Go, RSpec, Cargo, and dotnet runners; stacktrace recognition for Java/V8/C# formats; chained-traceback message extraction (final exception wins), descriptive npm summaries, Kubernetes `Events:` warning priority; and additional failure kinds `dependency_resolution`, `disk_full`, `tls_certificate_error`, `api_rate_limited`. All deterministic — no network, no LLM |
| FR-29 | Offline evaluation harness: validate versioned sanitized cases, keep development and held-out sets separate, and report machine-readable classification, extraction, dedup, redaction, throughput, and memory baselines without changing production classifiers |
| FR-30 | Structured feedback: rate root-cause usefulness, kind/severity/owner/duplicate correctness, and confirmed actual outcome; store separately from dedup state with audit metadata and redaction; CLI record/export (`hound feedback`); reviewed feedback exports explicit regression-fixture candidate manifests without mutating classifiers |
| FR-31 | Trust policy: source classes `trusted_branch`/`fork_pr`/`local_artifact` gate source context, enrichment, LLM, and delivery (`--source-class`, YAML `trust.source_class`, `TH_SOURCE_CLASS`, CI detection); untrusted fork analysis defaults to offline with no source enrichment and no delivery |
| FR-32 | Confidence calibration: deterministic `high`/`medium`/`low` bands calibrated against the evaluation set; evaluator reports support, empirical accuracy, mean deterministic score, and gap per band with documented meaning |

## 5. Non-functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | No live API calls in tests; all fixtures are local |
| NFR-2 | Auto-fallback to rules if LLM is missing, errored, or returns malformed JSON; exit `1` only for a recognized failure kind |
| NFR-3 | Deterministic output with `--offline` — same input produces the same RCA and `dedup_key` |
| NFR-4 | Python ≥ 3.10; runtime deps: openai, gitpython, pyyaml, textual, defusedxml |
| NFR-5 | LLM JSON validated against schema before trusting; validation failure triggers fallback |
| NFR-6 | Redaction on by default; secrets and PII must not reach the LLM prompt, `report.json`, `ticket.md`, or filed issues |
| NFR-7 | External API calls (GitHub/Jira/GitLab/Slack) use bounded timeouts; delivery failures warn without altering the analysis result |
| NFR-8 | LLM retries bounded by `max_retries` (default 3) with exponential backoff; exhaustion triggers fallback |
| NFR-9 | Dedup `record_triage` must upsert a missing entry (eviction race) rather than silently discard the reuse snapshot; pipeline warns to stderr on persistence failure |

## 6. RCA Document Schema (v2.0; v1.4 reader compatible)

```json
{
  "schema_version": "2.0",
  "meta": {
    "engine": "llm | fallback | merged",
    "model": null,
    "log_file": "...",
    "generated_at": "ISO8601",
    "redacted": false,
    "usage": { "prompt_tokens": 0, "completion_tokens": 0 },
    "reused": false,
    "reused_from_key": null
  },
  "failure": {
    "stage": "ci | build | test | deploy | unknown",
    "kind": "compilation_error | test_failure | import_error | timeout | flaky | deployment_failed | rollback | health_check_failed | image_pull_error | migration_failed | permission_error | readiness_timeout | oom_killed | crash_loop | liveness_probe_failed | readiness_probe_failed | scheduling_failed | quota_exceeded | network_failure | registry_auth_failure | config_missing | ci_failure | dependency_resolution | disk_full | tls_certificate_error | api_rate_limited | unknown",
    "summary": "...",
    "message": "core error line",
    "stacktrace": [{ "file": "...", "line": 0, "function": "...", "code": "±2 source lines" }],
    "failed_tests": [{ "name": "...", "file": "...", "line": 0, "assertion": "..." }],
    "events": [{ "stage": "build", "kind": "compilation_error", "message": "...", "role": "primary | downstream" }]
  },
  "context": {
    "run": { "provider": "github-actions", "run_id": "...", "job_name": "...", "pr_number": "...", "base_sha": "...", "head_sha": "..." },
    "deployment": { "platform": "kubernetes", "environment": "production", "target": "api", "artifact": "...", "outcome": "failed", "recovery": "" },
    "request": { "request_id": "req_123", "trace_id": "trace_123", "session_id": "", "user_id": "u_123", "users": ["u_123"], "method": "POST", "path": "/api/checkout" },
    "owners": ["@platform"]
  },
  "root_cause": {
    "hypothesis": "...",
    "confidence": "high | medium | low",
    "evidence": ["..."],
    "fix_suggestion": "..."
  },
  "analysis": {
    "observed_facts": [{ "id": "fact-001", "kind": "failure_classification", "value": {}, "evidence_refs": ["ev-001"] }],
    "evidence": [{
      "id": "ev-001",
      "kind": "failure_message",
      "value": "...",
      "provenance": { "source_type": "artifact", "artifact": "...", "locator": "failure.message", "collector": "ingest.logs", "observed_at": "ISO8601" }
    }],
    "hypotheses": [{
      "id": "hyp-001",
      "statement": "...",
      "source": "deterministic | llm",
      "support_status": "supported | unsupported | insufficient_evidence",
      "supporting_evidence_refs": ["ev-001"],
      "contradicting_evidence_refs": [],
      "confidence": { "band": "high | medium | low", "score": 0.75, "reasons": ["deterministic observation"] },
      "missing_information": [],
      "recommended_checks": []
    }],
    "missing_information": [],
    "recommended_checks": []
  },
  "triage": {
    "severity": "critical | high | medium | low",
    "component": "...",
    "priority": 1,
    "dedup_key": "sha256hex",
    "is_duplicate_of": null,
    "flaky_suspect": false,
    "recurring_incident": false,
    "occurrence_count": 1
  },
  "ticket": { "title": "...", "body_md": "...", "labels": ["severity:high"] }
}
```

`models.validate(doc)` accepts persisted v1.4 reports and current v2.0 reports,
and raises `ValueError` on missing or malformed fields. All new reports use v2.0.
Malformed or unresolved LLM evidence references trigger the deterministic fallback
instead of crashing. Every hypothesis is either linked to structured evidence or
explicitly marked `unsupported`/`insufficient_evidence`.

## 7. Success Metrics

- 100 % of test suite passes (`uv run pytest`).
- Offline determinism: two identical runs produce identical RCA and `dedup_key`.
- Dedup catches a repeated failure across runs (`is_duplicate_of` set on second run).
- `hound analyze` exits `0` for healthy/unknown logs and `1` for recognized failures,
  with or without an API key.
- No secret or PII pattern found in `--out` artifacts after analysis.
- Evaluation labels are valid and every synthetic expected secret is redacted;
  baseline accuracy is measured before classifier changes.

## 8. Constraints and Assumptions

- Input is a directory of supported artifact files, or a single file via `--log`.
- Optional `--repo` is a local git checkout; analyzed repos are untrusted input.
- LLM contract: chat completions with `response_format={"type": "json_object"}` returning the RCA schema JSON.
- Component mapping defaults to path-based heuristic + `unowned` when not supplied.
- HTTP dedup backend is disabled until conditional writes prevent lost updates.

## 9. Out of Scope

- Auto-fix or auto-PR generation.
- Web UI or dashboard.
- Attachments or artifact zip upload.
- Streaming analysis (results are written once complete).
- Mapping request context from `--context` sidecars (log-window extraction only).
- G7 reverse manifest lookup (resource → manifest matching requires a bounded search contract).
- Generic GitHub annotation and JUnit retry dialect detection (needs representative samples to avoid false positives).
- Validation Stages 2–3 (schema backwards-compat matrix and consumer contract tests).
