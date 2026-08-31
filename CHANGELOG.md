# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Standard Open Source documentation: `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.
- Issue and PR templates for GitHub.
- Comprehensive distribution and production maturity roadmap.

### Changed
- Reorganized the package into `src/hound_agent`, grouped tests by runtime boundary,
  and grouped documentation under purpose-specific directories.
- Refreshed README navigation and added a documentation hub plus a runnable demo
  under `examples/demo`.
- Made canonical CLI command and option spellings primary while retaining legacy
  spellings as compatibility aliases.

## [0.4.0] - 2026-08-07

### Added
- **Dynamic Packaging & Canonical CLI Aliases**: Added dynamic Hatch version resolution, canonical CLI subcommands (`insights`, `gate`, `console`, `serve`, `providers`, `runs`), and `--output-dir` / `--repo-dir` options.
- **Strict Configuration Validation**: Added `hound config validate` command with fuzzy key suggestion and `--warn-only` mode.
- **Persistent Delivery Ledger & Bounded Telemetry (M12)**: Added SQLite-backed idempotent delivery ledger with ambiguous-outcome recovery and process-local zero-payload telemetry registry.
- **Known-Issue Matching & LLM Preview (M3 Addendum)**: Added pre-LLM fingerprint resolution against reviewed feedback and `--llm-preview` dry-run export.
- **QA Enrichment & General Severity Policy**: Added CODEOWNERS and related incident feedback correlation to QA classifications and `critical_severity` / `high_severity` policy rules in quality gate.
- **Multi-Provider LLM Engine**: Native support for OpenAI, Anthropic Claude, Google Gemini, Groq, Ollama, DeepSeek, Azure OpenAI, and custom OpenAI-compatible endpoints.
- **Interactive Terminal UI (TUI)**: Built with Textual for interactive log browsing, triage filtering, live log inspection, and configuration settings.
- **Log Stream Capture & Tee (`hound log`)**: Intercept and tee child processes with automatic sidecar metadata and immediate analysis on failure.
- **QA History & Flakiness Tracking (`hound insights`)**: Queryable SQLite database for test runs across branches and commits, tracking duration regressions and intermittent failures.
- **High-Throughput Batch Processing (`hound batch`)**: Parallel log analysis with explicit spending guardrails (`--max-cost-usd`, `--max-llm-calls`) and SQLite WAL deduplication.
- **HTTP Server / Webhook Receiver (`hound serve`)**: Lightweight stdlib-based webhook receiver with Bearer token authentication and persistent SQLite job queue.
- **Smart Privacy & Redaction**: Automated pre-analysis scrubbing for API tokens, passwords, private keys, JWTs, and sensitive connection strings.
- **Structured Test Ingestion**: Native parsing for JUnit XML, SARIF, and JSON test outputs without heuristic regex degradation.
- **Docker & GitHub Action Integration**: Ready-to-use Dockerfile and `action.yml` for automated failure investigation in CI/CD pipelines.
