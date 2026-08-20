# PRD — Root Cause Analysis Bot for Team Automation (Hound Agent)

## 1. Problem Statement

CI/CD, build, and test failures are frequently left uninvestigated:

- No structured record of *why* a build failed.
- Duplicate tickets opened for the same recurring failure.
- Root-cause knowledge lives in heads / chat logs, not in the repo.
- Manual triage (severity, component, priority) is slow and inconsistent.

## 2. Goal (v1)

Hound Agent is Python CLI + core library (`hound_agent`) that auto-investigates a failure artifact:

```
log + repo context → parse → root cause analysis → triage → report + ticket draft
```

- **Offline-first**: fully functional with rule-based analysis when no LLM is configured.
- **Optional LLM**: OpenAI-compatible endpoint (configurable base URL + key) for richer RCA.
- **CI-safe**: never hard-fails; LLM failure silently falls back to rules.

### Out of scope (v1)
- Live GitHub ticket creation (draft only; API client later). — *superseded by FR-11 (v1.1)*
- Auto-fix / auto-PR.
- Web UI / dashboard.
- Streaming analysis, batch multi-log processing.
- Attachments / artifact zips.

## 3. Users

| User | Context | Needs |
|---|---|---|
| Developer | locally triaging a failing run | quick report, ticket draft, dedup vs known issues |
| CI pipeline | headless, no API key | deterministic offline analysis and meaningful failure exit code |
| On-call | triaging queue | severity + component + dedup to prioritize |

## 4. Requirements

### 4.1 Functional

| ID | Requirement |
|---|---|
| FR-1 | Parse CI/CD/build/test log → stage (`ci`/`build`/`test`/`deploy`), failure kind, summary, message |
| FR-2 | Parse stacktrace into frames (file, line, function) |
| FR-3 | Parse failed-test list (name, file, line, assertion message) |
| FR-4 | Gather git context via GitPython: branch, HEAD commit, changed files vs HEAD |
| FR-5 | LLM analysis via OpenAI-compatible API (base URL + key + model overridable) |
| FR-6 | Deterministic rule-based fallback analysis (no network) |
| FR-7 | Triage: severity (critical/high/medium/low), component (YAML glob map), priority 1–5 |
| FR-8 | Dedup: normalized fingerprint → sha256; persists across runs in out dir |
| FR-9 | Output: `report.json` + `report.md` + `ticket.md` into `--out` dir |
| FR-10 | CLI: `hound analyze LOG_DIRECTORY` or legacy `hound analyze --log FILE`, with repo/output/offline/config options |
| FR-11 | Optional live GitHub issue creation: `--gh` flag; `GH_TOKEN` + `GH_REPO` env; labels from severity/component; failure warns, never exits non-zero |
| FR-12 | Batch: `hound batch --logs DIR` analyzes all logs into unique run dirs + `summary-<batch-id>.json`; shared dedup state |
| FR-13 | Flaky-with-history: dedup state tracks occurrence count; repeated identical failure (≥3) flagged `flaky_suspect` |
| FR-14 | TUI: `hound tui [--logs DIR] [--repo DIR] [--out DIR] [--offline]` — browse logs, run analysis, view overview/report/ticket/raw log interactively |
| FR-15 | Secret/PII redaction: API keys, JWTs, passwords, connection strings, emails, IPs scrubbed from log text before LLM + disk (`meta.redacted`); `--no-redact` / `redact: false` escape hatch |
| FR-16 | Opt-in repo code context: with `--repo --source-context`, ±2 lines around stacktrace frames are surfaced in prompt/report/ticket; disabled by default because log frames are untrusted |
| FR-17 | Smart log windowing: oversized logs sliced as head+tail around failure markers, not a blind 2MB tail |
| FR-18 | LLM resilience: exponential backoff retries on 429/5xx (`--max-retries` / `llm.max_retries`); prompt/completion token usage recorded in `meta.usage` |
| FR-19 | Locked, atomic file dedup store; remote backends remain disabled until conditional writes prevent lost updates |
| FR-20 | Issue-tracker integrations: Jira REST (`--jira`), GitLab Issues (`--gitlab`), Slack webhook alert (`--slack-webhook`); all warn-not-fail, never exit non-zero |
| FR-21 | Webhook server: `hound server --port` stdlib HTTP receiver with `/analyze` + `/health`; accepts JSON payload and runs pipeline in background |
| FR-22 | Explicit config only: load YAML through `--config`; never trust repository-local config automatically |
| FR-23 | Distribution: `Dockerfile` + GitHub Action manifest (`action.yml`); PyPI metadata in `pyproject.toml` |
| FR-24 | Detect deployment failures from Kubernetes, Helm, Docker, Terraform, and deployment-provider logs: failed deployment, rollback, health-check failure, image-pull error, migration failure, permission error, and readiness timeout. Analysis is read-only: it must not deploy, retry, or roll back infrastructure. |

### 4.2 Non-functional

| ID | Requirement |
|---|---|
| NFR-1 | No live API call in CI/tests (fixtures only) |
| NFR-2 | Auto-fallback to rules if LLM missing/errored/malformed; exit `1` only for a recognized failure kind |
| NFR-3 | Deterministic output when `--offline` (same input → same RCA) |
| NFR-4 | Python >= 3.10; deps: openai, gitpython, pyyaml (dev: pytest) |
| NFR-5 | Validate LLM JSON against schema before trusting it |
| NFR-6 | Redaction on by default; secrets/PII never reach LLM prompt, `report.json`, `ticket.md`, or filed tickets |
| NFR-7 | External API calls (GH/Jira/GitLab/Slack) use bounded timeouts; delivery failures warn without changing analysis result |
| NFR-8 | LLM retries bounded (`max_retries`, default 3) with backoff; still falls back to rules on exhaustion |

## 5. Success Metrics

- 100% of fixture-suite tests pass (`uv run pytest`).
- Offline determinism: two identical runs produce identical RCA + dedup_key.
- Dedup catches a repeated failure across runs (is_duplicate_of set on 2nd run).
- `hound analyze` exits `0` for healthy/unknown logs and `1` for recognized failures, with or without an API key.

## 6. Constraints & Assumptions

- Input is a single text log file (path given via `--log`).
- Optional `--repo` is a local git checkout.
- LLM contract: chat completions with `response_format={"type":"json_object"}` returning our RCA schema.
- Component mapping, when not supplied, defaults to path-based heuristic + `unowned`.

## 7. Milestones

| M | Deliverable |
|---|---|
| M1 | Docs (PRD/WORKFLOW/TODO/ARCHITECTURE) + scaffold |
| M2 | ingest parsers + fixtures |
| M3 | analyze (fallback + LLM) |
| M4 | triage (severity/component/dedup) |
| M5 | output + CLI |
| M6 | full test suite + verify gate |
