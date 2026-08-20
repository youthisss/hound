# TODO — tracehound

Ordered task list. One in progress at a time. Check off when DoD (WORKFLOW.md) met.

## Milestone 1 — Docs + scaffold
- [x] M1.1 PRD.md
- [x] M1.2 WORKFLOW.md
- [x] M1.3 TODO.md
- [x] M1.4 ARCHITECTURE.md
- [x] M1.5 Scaffold: `pyproject.toml` (uv; deps: openai, gitpython, pyyaml; dev: pytest), `.gitignore`, `tracehound/` package skeleton
- [x] M1.6 `models.py`: dataclasses + RCA schema v1.0 + `validate()`

## Milestone 2 — ingest
- [x] M2.1 `ingest/logs.py`: stage + kind detection, error-line extraction (fixtures: pytest_fail.log, build_error.log, flaky.log)
- [x] M2.2 `ingest/stacktrace.py`: frame parsing (file:line, function)
- [x] M2.3 `ingest/tests.py`: failed-test parsing from pytest summary
- [x] M2.4 `ingest/git.py`: GitPython branch, HEAD, changed files vs HEAD
- [x] M2.5 ingest unit tests

## Milestone 3 — analyze
- [x] M3.1 `analyze/fallback.py`: deterministic rule-based RCA
- [x] M3.2 `analyze/prompts.py`: system + user prompt, schema instruction
- [x] M3.3 `analyze/llm.py`: openai SDK, base_url override, json_object, validation
- [x] M3.4 `analyze/rca.py`: orchestrator, LLM → fallback merge, engine tagging
- [x] M3.5 analyze tests (fallback determinism, merge logic — mocked LLM)

## Milestone 4 — triage
- [x] M4.1 `triage/severity.py`: critical/high/medium/low rules + priority 1–5
- [x] M4.2 `triage/component.py`: YAML glob map + path heuristic + `unowned`
- [x] M4.3 `triage/dedup.py`: normalized fingerprint → sha256; state store in `--out/.tracehound/state.json`; is_duplicate_of
- [x] M4.4 triage tests (incl. cross-run dedup)

## Milestone 5 — output + cli
- [x] M5.1 `output/report.py`: report.json + report.md
- [x] M5.2 `output/tickets.py`: GitHub-style ticket.md draft
- [x] M5.3 `cli.py`: argparse `analyze --log --repo --out --offline --config`
- [x] M5.4 output/cli tests

## Milestone 6 — integration
- [x] M6.1 End-to-end offline pipeline test (fixture → out dir)
- [x] M6.2 Verify gate: `uv run pytest` + analyze on fixtures exit 0
- [x] M6.3 README.md

## Next (post-v1)
- [x] Live GitHub ticket creation via API (--gh; GH_TOKEN/GH_REPO; warn-not-fail)
- [x] Multi-log batch analysis (hound batch; unique summary per invocation; shared dedup state)
- [x] Flaky test detection with historical state (count>=3 → flaky_suspect)

## Milestone 10 — TUI
- [x] M10.1 Docs (PRD FR-14, ARCHITECTURE pipeline/tui)
- [x] M10.2 `pipeline.py` — core analyze() shared by CLI + TUI
- [x] M10.3 CLI refactor to pipeline + `tui` subcommand
- [x] M10.4 `tui.py` — Textual app
- [x] M10.5 Tests + verify gate

## Milestone 11 — Production readiness: security (docs-first)
- [x] M11.1 PRD FR-20/FR-21 (redaction + untrusted-log policy), ARCHITECTURE security model
- [x] M11.2 `ingest/redact.py` — secret/PII redaction (API keys, bearer/JWT, AWS/GH keys, passwords, connection strings, emails, IPs)
- [x] M11.3 Pipeline hooks: redact log text before LLM + output; `meta.redacted` + `--no-redact` escape hatch
- [x] M11.4 Tests + verify gate

## Milestone 12 — Production readiness: intelligence
- [x] M12.1 PRD FR-22 (code context), ARCHITECTURE schema v1.1 note
- [x] M12.2 `StackFrame.code` snippet extraction (`ingest/stacktrace.py:attach_snippets`, ±2 lines)
- [x] M12.3 Snippet into LLM prompt + report/ticket rendering
- [x] M12.4 `ingest/logs.py:read_log_window` — head+tail smart slicing (replaces blind 2MB tail)
- [x] M12.5 Tests + verify gate

## Milestone 13 — Production readiness: reliability
- [x] M13.1 PRD FR-23/FR-24, ARCHITECTURE retry + usage + state-store adapter
- [x] M13.2 `analyze/llm.py` — exponential backoff retries (429/5xx), `usage` (prompt/completion tokens) capture
- [x] M13.3 `meta.usage` in RCA doc + `--max-retries` config
- [x] M13.4 `triage/dedup.py` — locked atomic file store; HTTP disabled until conditional writes are available
- [x] M13.5 Tests + verify gate

## Milestone 14 — Production readiness: integrations
- [x] M14.1 PRD FR-25/FR-26, ARCHITECTURE server + trackers
- [x] M14.2 `output/tickets.py` — Jira + GitLab REST clients; `output/slack.py` webhook
- [x] M14.3 CLI `--jira`/`--gitlab`/`--slack-webhook` + YAML `jira:`/`gitlab:`/`slack:` blocks; shared file-ticket dispatch
- [x] M14.4 `server.py` — stdlib HTTP webhook receiver (`hound server`), `/analyze` + `/health`
- [x] M14.5 `config.py` — require explicit `--config` so analyzed repositories cannot redirect provider traffic
- [x] M14.6 Tests + verify gate

## Milestone 15 — Production readiness: packaging + docs
- [x] M15.1 PRD FR-27/FR-28, ARCHITECTURE deploy, USAGE, WORKFLOW verify gate, HANDOFF, REVIEW, README
- [x] M15.2 `Dockerfile` + `.dockerignore`
- [x] M15.3 `action.yml` (GitHub Action manifest)
- [x] M15.4 `pyproject.toml` — version bump 0.2.0, metadata for PyPI
- [x] M15.5 Verify gate: `uv run pytest` + offline analyze fixtures exit 0

## Milestone 16 — CD failure analysis
- [x] M16.1 Docs: CI/CD scope and read-only deployment-analysis boundary
- [x] M16.2 Detect deploy stage and Kubernetes, Helm, Terraform deployment failures
- [x] M16.3 Deterministic RCA and severity rules for deployment failure kinds
- [x] M16.4 Deployment fixtures and pipeline coverage

## Milestone 17 — CI/CD intelligence
- [x] M17.1 Versioned CI run and deployment context, GitHub Actions environment ingestion, PR base/head diff, CODEOWNERS
- [x] M17.2 JUnit, SARIF, JSON test report, and Go NDJSON artifact parsing
- [x] M17.3 Primary/downstream failure-event graph; recurring incidents separated from flaky tests
- [x] M17.4 Specific Kubernetes failure kinds and explicit bounded read-only enrichment
- [x] M17.5 Environment policy overrides, GitHub Action outputs, regression fixtures, verification
