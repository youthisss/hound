# ARCHITECTURE — tracehound

## Module map

```
tracehound/
├── pyproject.toml            # uv; [project.scripts] tracehound = tracehound.cli:main
├── tracehound/
│   ├── __init__.py           # __version__
│   ├── models.py             # dataclasses: Artifacts, RootCause, Triage, Ticket; RCA doc; validate()
│   ├── config.py             # env vars + optional YAML config (component map, dedup path, trackers)
│   ├── collector.py          # command/stdin capture -> redacted .log + metadata
│   ├── service.py            # shared application service for CLI/TUI/server
│   ├── pipeline.py           # core analyze(log_path, out, ...) -> doc
│   ├── cli.py                # argparse; subcommands: analyze, batch, tui, server, list-providers
│   ├── server.py             # stdlib HTTP webhook receiver: /analyze + /health
│   ├── tui.py                # Textual terminal UI: log browser, analyze, report/ticket/raw panes
│   ├── ingest/
│   │   ├── logs.py           # detect stage/kind, failure-event graph, smart windowing
│   │   ├── context.py        # collector/GitHub Actions run and deployment context
│   │   ├── structured.py     # JUnit, SARIF, JSON and Go NDJSON artifact parsers
│   │   ├── owners.py         # CODEOWNERS resolver for affected files
│   │   ├── enrich.py         # explicit bounded read-only Kubernetes/Helm/Terraform evidence
│   │   ├── stacktrace.py     # parse frames: file, line, function; attach source snippets (±2 lines)
│   │   ├── tests.py          # parse failed-test names from pytest output
│   │   ├── redact.py         # secret/PII redaction (keys, JWT, passwords, conn strings, email/IP)
│   │   └── git.py            # GitPython: branch, HEAD, changed_files vs HEAD
│   ├── analyze/
│   │   ├── llm.py            # openai SDK client; retries w/ backoff; usage capture; json_object; try/except
│   │   ├── prompts.py        # system + user prompt builders (nonce-boundary injection guard)
│   │   ├── rca.py            # orchestrator: run_analysis(artifacts) -> RootCause
│   │   └── fallback.py       # rule-based deterministic RCA
│   ├── triage/
│   │   ├── severity.py       # rules -> severity + priority
│   │   ├── component.py      # glob map + path heuristic -> component
│   │   └── dedup.py          # normalize -> sha256; locked file store; flaky_suspect (count>=3)
│   └── output/
│       ├── report.py         # write report.json + report.md
│       ├── tickets.py        # ticket.md draft; GitHub/Jira/GitLab REST clients
│       └── slack.py          # Slack webhook alert
├── Dockerfile                # containerized runner
├── action.yml                # GitHub Action manifest
├── tests/
│   ├── conftest.py           # fixtures path helpers
│   ├── fixtures/             # pytest_fail.log, build_error.log, stacktrace.txt, flaky.log, fake repo/
│   └── test_*.py
```

## Data flow

```
 log ─┐
 repo ─┼─► ingest ──► Artifacts ──► analyze ──► RootCause ──► triage ──► RCA doc ──► output ──► out/
       │                       │        (LLM │ fallback)      │  (severity/     (report +    report.json
       └───────────────────────┘        auto-fallback,        │   component/     ticket.md)  report.md
                                         engine tagged)        └─ dedup ───────────► state.json
```

1. **ingest** builds `Artifacts`: redact secrets (default on), detect stage/kind, extract summary/message, parse stacktrace, failed tests, and git context. Source snippets require explicit `--source-context` for trusted logs.
2. **analyze** produces `RootCause`: LLM if enabled+ok (with retry/backoff + usage capture), else fallback; LLM output merged over rule facts; `engine` recorded.
3. **triage** decorates: `Triage` (severity, component, priority, dedup_key, is_duplicate_of). State lives in a locked, atomic file store.
4. **output** renders `report.json`, `report.md`, `ticket.md` into `--out` (default `./tracehound_output/`). Optional filing: GitHub/Jira/GitLab ticket, Slack alert.
5. **batch** (`hound batch --logs DIR`) writes opaque unique run directories and `summary-<batch-id>.json`; dedup state is shared at `<out>/.tracehound/state.json`.
6. **tui** (`hound tui`) calls `service.analyze_log()` in a Textual terminal app: pick a log → analyze → browse overview / report.md / ticket.md / raw log.
7. **server** (`hound server --port`) calls the same service from a stdlib HTTP endpoint; GET `/health` returns liveness.
8. **log collector** (`hound log -- COMMAND` or piped stdin) tees raw output to the terminal, persists a redacted `.log` plus JSON metadata, and can explicitly call the shared service with `--analyze`.

`service.analyze_log()` is the adapter-facing entry point for CLI, TUI, server, and collector. It delegates to the single `pipeline.analyze()` core.

## RCA document schema (v1.2)

```json
{
  "schema_version": "1.2",
  "meta": { "engine": "llm|fallback|merged", "model": null, "log_file": "...", "generated_at": "ISO8601",
            "redacted": false, "usage": { "prompt_tokens": 0, "completion_tokens": 0 } },
  "failure": {
     "stage": "ci|build|test|deploy|unknown",
     "kind": "ci_failure|compilation_error|test_failure|import_error|timeout|flaky|deployment_failed|rollback|health_check_failed|image_pull_error|migration_failed|permission_error|readiness_timeout|unknown",
    "summary": "...",
    "message": "core error line",
    "stacktrace": [{ "file": "...", "line": 0, "function": "...", "code": "2 | total = 5.0" }],
     "failed_tests": [{ "name": "...", "file": "...", "line": 0, "assertion": "..." }],
     "events": [{ "stage": "build", "kind": "compilation_error", "message": "...", "role": "primary|downstream" }]
   },
   "context": {
     "run": { "provider": "github-actions", "run_id": "...", "job_name": "...", "pr_number": "...", "base_sha": "...", "head_sha": "..." },
     "deployment": { "platform": "kubernetes", "environment": "production", "target": "api", "artifact": "...", "outcome": "failed", "recovery": "" },
     "owners": ["@platform"]
   },
  "root_cause": {
    "hypothesis": "...",
    "confidence": "high|medium|low",
    "evidence": ["..."],
    "fix_suggestion": "..."
  },
   "triage": {
    "severity": "critical|high|medium|low",
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

`models.validate(doc) -> None` raises on missing fields/types; malformed LLM output triggers fallback.

## Contracts between stages

| Stage | In | Out |
|---|---|---|
| ingest | raw log text, optional repo dir | `Artifacts` |
| analyze | `Artifacts` | `RootCause` |
| triage | `Artifacts` + `RootCause` | `Triage` |
| output | full RCA doc | files in out dir |

## Config

- Env: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (default `gpt-4o-mini`); generic overrides `TH_*`.
- Env (GitHub, used with `--gh`): `GH_TOKEN`, `GH_REPO` (owner/name), `GH_API_BASE` (default `https://api.github.com`).
- Env (trackers): `JIRA_URL`/`JIRA_PROJECT`/`JIRA_TOKEN`, `GITLAB_URL`/`GITLAB_PROJECT`/`GITLAB_TOKEN`, `SLACK_WEBHOOK_URL`.
- Optional YAML supplied explicitly with `--config`: `llm` (incl. `max_retries`), `components`, `redact`, file-based `dedup`, `github`, `jira`, `gitlab`, `slack`.
- Repository-local config is not auto-discovered because analyzed repositories are untrusted input.
- Redaction: on by default; `--no-redact` or `redact: false` disables.
- Dedup store: `file` only (locked JSON at `<out>/.tracehound/state.json`, atomic `os.replace`). HTTP state is disabled until conditional writes are supported.
- LLM resilience: `max_retries` (default 3) with exponential backoff on 429/5xx; token usage captured into `meta.usage`.

## Failure policy

- No key / `--offline` / LLM error / malformed JSON → run fallback, tag `engine:"fallback"`, note in report.
- LLM retry exhaustion after `max_retries` → fallback.
- `analyze` exits `0` for a completed clean result, `1` for a completed result containing a CI/CD/build/test failure, `2` for invalid input/config, and `3` for internal errors.
- GitHub/Jira/GitLab ticket creation or Slack delivery failure (missing creds, HTTP error, network) → warn to stderr and return exit 3 when explicitly requested.
- Unsupported dedup backend -> configuration error before analysis.

## Fallback rules (deterministic)

- Severity: import/compile/image-pull/migration failure → critical; deployment, rollback, permission, health-check, or readiness failure → high; crash/segfault → high; assertion/timeout → medium; flaky → low.
- Priority: critical=1, high=2, medium=3, low=4; `flaky_suspect` (recurring ≥3) = 5.
- Component: match stack paths + git changed files against glob map; else `unowned`.
- Confidence: high if frame hits changed file; medium if generic match; low if unknown.

## Test strategy

- Fixtures only; no live API.
- Git tests use a fake repo fixture (committed, no network).
- LLM tested with mocked client (deterministic JSON response).
- Determinism assert: same input → same dedup_key.
- CI: `uv run pytest` (WORKFLOW verify gate).
