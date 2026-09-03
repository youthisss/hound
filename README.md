<div align="center">

<pre>
██╗  ██╗ ██████╗ ██╗   ██╗███╗   ██╗██████╗ 
██║  ██║██╔═══██╗██║   ██║████╗  ██║██╔══██╗
███████║██║   ██║██║   ██║██╔██╗ ██║██║  ██║
██╔══██║██║   ██║██║   ██║██║╚██╗██║██║  ██║
██║  ██║╚██████╔╝╚██████╔╝██║ ╚████║██████╔╝
╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═════╝ 
</pre>

<h3>An Offline-First CLI & TUI Tool for Investigating CI/CD, Build, and Test Failures.</h3>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Status-Beta-yellow.svg" alt="Status"></a>
  <a href="#running-tests"><img src="https://img.shields.io/badge/Tests-CI%20Verified-success.svg" alt="Tests"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python Version"></a>
  <a href="#security"><img src="https://img.shields.io/badge/Security-Redaction%20Default-orange.svg" alt="Security"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
</p>

</div>

---

**Hound** is an offline-first diagnostic **developer tool** (CLI & TUI) designed to automatically investigate broken CI/CD pipelines, flaky test runs, build crashes, and deployment failures. It inspects raw execution logs and structured test artifacts, correlates stack traces with repository context, determines root causes, triages issue severity, and generates actionable incident reports and ticket drafts—**in a strictly read-only mode without mutating infrastructure**.

---

## ⚡ Why Hound?

- 🔒 **Offline-First & Deterministic:** 100% functional out of the box with no external services, no API keys, and no network access required.
- 🤖 **Multi-Provider LLM Enhancement:** Seamlessly plug into OpenAI, Anthropic, Gemini, Groq, Ollama, DeepSeek, Azure, or local OpenAI-compatible endpoints when deeper synthesis is desired.
- 🛡️ **Zero-Crash CI Safety:** Automatic fallback to deterministic rule engines if LLM calls time out, hit rate limits, or fail JSON schema validation. Your CI pipeline never fails because of an AI outage.
- 💰 **Built-In Token & Cost Control:** Deduplication-first result caching, failure-kind routing (skip noisy flaky tests), a strict call-attempt cap (`--max-llm-calls`), and an estimated post-call cost threshold (`--max-cost-usd`).
- 🔐 **Privacy by Design:** Automatic regex scrubbing for API keys, passwords, JWTs, connection strings, emails, and IP addresses before anything is analyzed or written to disk.
- 🚫 **Read-Only Guarantee:** Hound analyzes and reports—it **never** deploys, retries, or rolls back infrastructure.

---

## 🔄 How It Works

```text
  ┌────────────────────────────────────────────────────────┐
  │ Failure Artifacts (.log, JUnit .xml, SARIF, JSON)      │
  │ + Optional Git Context & Sidecar Metadata              │
  └──────────────────────────┬─────────────────────────────┘
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 1. Ingest & Scrub (Secret & PII Redaction)             │
  │    - Head/Tail Smart Windowing                         │
  │    - Stack Trace Framing (Python, Go, Rust, Java, etc.)│
  │    - CD Failure Extraction (K8s, Helm, Terraform)      │
  └──────────────────────────┬─────────────────────────────┘
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Root Cause Analysis (RCA Engine)                    │
  │    ├─► LLM Reasoning (OpenAI, Gemini, Claude, Ollama)  │
  │    └─► Deterministic Rule Fallback (Always Safe)       │
  └──────────────────────────┬─────────────────────────────┘
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Triage & Smart Deduplication                        │
  │    - Severity (Critical, High, Medium, Low) & Priority │
  │    - SHA-256 Fingerprinting & Snapshot Reuse (SQLite)  │
  │    - Flaky Test Detection (Explicit Retry Evidence)    │
  └──────────────────────────┬─────────────────────────────┘
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Output & Integrations                               │
  │    - report.json, report.md, ticket.md                 │
  │    - Optional Dispatch: GitHub, Jira, GitLab, Slack    │
  │    - Terminal UI / REST API / SQLite QA History        │
  └────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Installation

#### End-User Installation (No clone required)

Hound supports Python 3.10-3.12 on Windows and Linux. Until the first
`hound-tracer` release is published, install the reviewed commit directly from
GitHub so package managers cannot resolve the unrelated `hound` project on
PyPI:

```sh
# Using uv (recommended)
uv tool install "hound-tracer @ git+https://github.com/youthisss/hound.git@fef7efcb2944336ba621e6f097722ae1bfdcae27"
hound --version
hound doctor

# Using pipx
pipx install "hound-tracer @ git+https://github.com/youthisss/hound.git@fef7efcb2944336ba621e6f097722ae1bfdcae27"
hound --version
hound doctor
```

After the first verified PyPI release, use `uv tool install hound-tracer` or
`pipx install hound-tracer`. Upgrade with `uv tool upgrade hound-tracer` or
`pipx upgrade hound-tracer`; uninstall with `uv tool uninstall hound-tracer` or
`pipx uninstall hound-tracer`.

#### Contributor Setup

```sh
# Clone and install dependencies
git clone https://github.com/youthisss/hound.git
cd hound
uv sync --extra dev
uv run hound --version
```

### 30-Second Usage

```sh
# 1. Open the interactive Terminal UI (TUI)
hound

# 2. Analyze all logs and test reports in a directory (Offline, 0 API keys required)
hound analyze ./ci-logs --offline

# 3. Capture command output and analyze immediately on failure
hound log --analyze --offline -- pytest -q

# 4. Verify system environment and storage readiness
hound doctor
```

---

## 🧪 Interactive Terminal UI (TUI)

Hound includes a rich, full-featured terminal interface built with Textual for interactive log browsing, triage, and live inspection.

```sh
# Launch TUI pointing to a log directory
hound console --logs ./ci-logs --output-dir hound-output --offline

# Launch TUI with LLM analysis and 4 parallel workers
hound console --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

### Essential TUI Shortcuts

| Key | Action |
|:---:|:---|
| `a` | **Analyze** currently selected log / Retry failed analysis |
| `A` | **Analyze All** visible artifacts sequentially (honors active filters) |
| `b` | **Browse folder** via interactive picker |
| `r` | **Refresh** log list and recent runs |
| `s` | **Settings** (configure providers, models, keys, and base URLs) |
| `o` | **Toggle offline mode** instantly |
| `c` / `e` | **Copy** Report / Ticket to clipboard |
| `?` / `q` | Open **Help overlay** / **Quit** |

---

## 🛠️ CLI Command Reference

### Canonical Command and Flag Names

The names below are the public spellings shown by `hound --help`. Older
spellings remain accepted for compatibility but are hidden from help output.

| Canonical | Compatibility alias |
|:---|:---|
| `console` | `tui` |
| `serve` | `server` |
| `providers` | `list-providers` |
| `runs` | `list-runs` |
| `insights` | `qa` |
| `--output-dir` | `--out` |
| `--repo-dir` | `--repo` |
| `--allow-unredacted` | `--no-redact` |
| `--test-runner` | `--runner` |
| `--baseline-ref` | `--baseline` |
| `--candidate-ref` | `--head` |
| `--history-db` | `--store` |
| `--window-days` | `--days` |

Use the canonical spellings in new scripts and CI configuration.

### 1. `hound analyze` — Batch Artifact Analysis

Scans all `.log`, `.xml` (JUnit), `.sarif`, and `.json` test reports directly inside a folder, generating `report.json`, `report.md`, and `ticket.md` per run.

```sh
# Standard offline analysis
hound analyze ./ci-logs --offline

# Include source context around stack frames from repository
hound analyze ./ci-logs --repo-dir . --source-context --offline

# Output structured JSON report directly to a file
hound analyze ./artifacts --format json --output result.json

# Parallel multi-worker analysis
hound analyze ./ci-logs --jobs 4 --output-dir hound-output
```

#### Key Capabilities:
- **Structured Artifact Ingestion:** Parses JUnit XML, SARIF, and test JSON natively without lossy regex heuristics.
- **Stack Trace Context:** With `--repo-dir` and `--source-context`, attaches ±2 lines of real code context for Python, Go, Rust, Java, TypeScript, C/C++, and deployment configurations (`.yaml`, `.tf`, `.tpl`).
- **CD & Cloud Infrastructure Detection:** Detects Kubernetes CrashLoopBackOff, OOMKilled, probe failures, quota exhaustion, image pull errors, Helm release/rollback failures, Terraform apply errors, and migration crashes.
- **Accurate Flaky Test Detection:** Labeled as `flaky` *only* when explicit retry-then-pass evidence is present (pytest `RERUN -> PASSED`, Jest `✕ -> ✓`, Go `-count=N`, or JUnit `flakyFailure`).

#### Exit Codes (CI-Ready)

| Exit Code | Meaning |
|:---------:|:--------|
| `0` | **Success:** Run finished, no CI/CD/build/test failures found. |
| `1` | **Failure Detected:** Run finished, at least one failure was identified. |
| `2` | **Usage Error:** Invalid arguments, missing path, or malformed config. |
| `3` | **Internal Error:** Analysis failed or requested ticket/alert delivery failed. |

```sh
# Example CI pipeline gate
hound analyze ./artifacts/logs --offline --format json --output hound-report.json
EXIT_CODE=$?

if [ $EXIT_CODE -eq 1 ]; then
  echo "❌ Hound detected actionable CI/CD failures!"
elif [ $EXIT_CODE -ge 2 ]; then
  echo "⚠️ Hound execution error (Code: $EXIT_CODE)"
  exit $EXIT_CODE
fi
```

---

### 2. `hound log` — Capture & Tee Stream Execution

Executes any build or test command, streams output to the terminal, and saves a redacted log alongside a JSON metadata sidecar in `.hound/logs/`.

```sh
# Run command directly and capture
hound log -- npm test
hound log --name unit-tests -- pytest -q

# Capture piped stdin
kubectl logs deployment/api | hound log --name api-deploy
terraform apply -auto-approve 2>&1 | hound log --name tf-apply

# Capture and immediately run RCA analysis
hound log --analyze --offline -- pytest -q
```

---

### 3. `hound batch` — Scaled Analysis with Cost Guardrails

Executes high-throughput directory analysis with a unified SQLite deduplication store and explicit budget caps.

```sh
hound batch --logs ./ci-logs \
  --output-dir ./out \
  --jobs 8 \
  --max-llm-calls 50 \
  --max-cost-usd 5.00
```

- Produces `summary-<batch-id>.json` (detailed per-log triage) and `usage-<batch-id>.json` (token telemetry, cost tracking, reuse counts).
- When spending limits are reached, remaining logs gracefully fall back to deterministic rule analysis and are marked `budget_skipped`.

---

### 4. `hound serve` — Webhook Receiver for CI/CD & Production

Runs a lightweight, stdlib-based HTTP webhook service with bearer authentication and persistent SQLite job management.

```sh
export HOUND_SERVER_TOKEN="your-secure-token"

hound serve \
  --host 127.0.0.1 \
  --port 8123 \
  --log-root ./ci-logs \
  --output-dir ./server-runs \
  --workers 4 \
  --rate-limit 60
```

Hound intentionally serves plaintext HTTP on loopback only. Terminate TLS and
apply shared rate limiting at a reverse proxy; see `docs/guides/server-deployment.md`.

#### API Endpoints:
- `POST /analyze` — Submit analysis job `{"log": "relative/path.log", "offline": false}`
- `GET /jobs/<id>` — Poll asynchronous job status and results
- `GET /health` & `GET /ready` — Service liveness and readiness probes
- `GET /stats` — Real-time telemetry (queued, running, completed, engine breakdown)

---

### 5. `hound insights` — Long-Term Test History & Flakiness Tracking

Maintains a queryable SQLite database of historical test executions across runs, branches, and environments to track intermittent failures and duration regressions over time.

```sh
# Import JUnit or test log evidence into history store
hound insights import ./junit.xml --test-runner pytest --branch main --commit abc1234

# Query historical failure rates and p95 durations for a test
hound insights stats tests/test_checkout.py test_payment_failure

# View recent execution history
hound insights history tests/test_checkout.py test_payment_failure --window-days 30
```

---

### 6. Utility Commands

```sh
# Check local storage, dependencies, and environment readiness
hound doctor

# Generate a commented configuration template (.hound.yml)
hound init

# List supported LLM providers and presets
hound providers

# Inspect previously stored analysis runs
hound runs --output-dir hound-output
hound report <run-id> --format markdown --output report.md

# Record human reviewer feedback to validate RCA accuracy
hound feedback record --run-id <run-id> --usefulness useful --actual-kind assertion_error

# Clean up analysis output directories
hound clean --output-dir hound-output --yes
```

---

## 🤖 Supported LLM Providers

Hound connects to any OpenAI-compatible API endpoint. Select a preset via `--provider` or configure via environment variables:

| Provider Preset | Required Environment Variable(s) | Default Model |
|:---|:---|:---|
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | `claude-sonnet-4-20250514` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.7-flash` |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `ollama` | `OLLAMA_MODEL` *(no key required)* | `llama3.1` |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_API_VERSION` | *(configured)* |
| `9router` | `NINE_ROUTER_API_KEY`, `NINE_ROUTER_MODEL`, `NINE_ROUTER_BASE_URL` | `ag/gemini-3.7-flash-low` |
| `custom` | `CUSTOM_API_KEY`, `CUSTOM_MODEL`, `CUSTOM_BASE_URL` | *(configured)* |

> **Selection Priority:** CLI Flags > YAML `llm:` block > Generic `HOUND_API_*` env vars > Provider-specific env vars > Deterministic offline fallback. Legacy `TH_*` aliases remain supported.

---

## ⚙️ Configuration (`.hound.yml`)

Create a local configuration file with `hound init` or pass one via `--config <path>`.

```yaml
llm:
  provider: gemini
  model: gemini-3.7-flash
  temperature: 0.2
  timeout: 120
  max_retries: 3            # Exponential backoff on 429 / 5xx
  max_concurrency: 4        # Parallel LLM calls per process
  routing: exclude-kinds    # all | exclude-kinds
  skip_kinds: [flaky]       # Route noisy kinds strictly to offline rules (saves tokens)
  pricing:                  # Pricing per million tokens (used for cost guardrails)
    default:
      prompt_per_mtok: 0.30
      completion_per_mtok: 1.50

redact: true                # Secret & PII scrubbing (enabled by default)

# Map repository paths to engineering components for ticket triage
components:
  "app/cart/*": "cart-team"
  "src/handlers/*": "payment-platform"

# Intelligent deduplication and snapshot reuse
dedup:
  backend: sqlite           # file | sqlite (WAL mode for concurrent workers)
  max_entries: 50000        # Automatic pruning limit
  retention_days: 90
  reuse: true               # Reuse root-cause analysis for recurring failures
  reuse_after_occurrences: 3

# Incident policy rules
policy:
  recurrence_threshold: 3
  severity_overrides:
    production:
      deployment_failed: critical

# Optional issue tracker integrations (warn-only on failure)
github:
  repo: "owner/repo"        # or GH_REPO env var
jira:
  url: "https://jira.example.com"
  project: "QA"
slack:
  webhook_url: "https://hooks.slack.com/services/..."
```

---

## 📦 CI/CD & Deployment

### GitHub Actions Integration

Use the official Docker-based GitHub Action (`action.yml`) for automated, deterministic pipeline failure triage:

```yaml
name: CI with Hound Triage

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Test Suite
        id: test_run
        continue-on-error: true
        shell: bash
        run: |
          set -o pipefail
          mkdir -p artifacts
          pytest --junitxml=artifacts/junit.xml | tee artifacts/pytest.log

      - name: Triage Failures with Hound
        if: steps.test_run.outcome == 'failure'
        uses: youthisss/hound@fef7efcb2944336ba621e6f097722ae1bfdcae27
        with:
          log: "artifacts/pytest.log"
          repo: "${{ github.workspace }}"
          out: "${{ github.workspace }}/hound-output"
          offline: "true"

      - name: Upload Investigation Report
        if: steps.test_run.outcome == 'failure'
        uses: actions/upload-artifact@v4
        with:
          name: hound-investigation-report
          path: hound-output/
```

The Action input IDs `repo` and `out` remain stable for existing workflows; the
container forwards them to the canonical CLI options `--repo-dir` and
`--output-dir`.

### Docker Execution

```sh
# Build the container
docker build -t hound .

# Run offline analysis mounting your local log directory
docker run --rm -v "$PWD/ci-logs:/logs:ro" hound analyze /logs --offline
```

---

## 🔬 Deterministic E2E Verification & Benchmarks

Hound includes an offline synthetic benchmark suite to verify classification, stack extraction, redaction, and deduplication at scale without external API calls:

```sh
# 1. Run quick smoke test gate
uv run python examples/demo/run_demo.py --profile smoke

# 2. Run high-volume scale benchmark (5,000 synthetic artifacts across 8 parallel workers)
uv run python examples/demo/run_demo.py --profile scale --count 5000 --jobs 8
```

---

## 🧪 Running Tests

```sh
# Run full unit & integration test suite
uv run pytest
```

> **Test Guarantee:** All tests run strictly with local fixtures, with no live API credentials required. The current count is reported by CI.

## Repository Layout

```text
src/hound/        Core package and CLI implementation
examples/demo/          Offline smoke test and scale benchmark harness
docs/                   Guides, reference contracts, operations, and plans
tests/unit/              Fast in-process tests
tests/integration/       Store, connector, source, and DevOps tests
tests/e2e/               CLI, TUI, Action, evaluator, and demo tests
tests/fixtures/          Local logs and structured artifacts
```

The package uses a standard `src` layout so the development checkout and built
wheel exercise the same import boundary. The repository does not contain a
second application or a hidden runtime service.

## Project Status

Hound `0.4.0` is currently Beta. The offline CLI, TUI, GitHub Action
contract, SQLite state stores, and deterministic fallback are covered by the
local quality gates. Production sign-off still requires the documented
two-repository pilot and external Docker, image-scan, TestPyPI, and PyPI
release controls; see [`docs/operations/pilot-readiness.md`](docs/operations/pilot-readiness.md).

## Contributing

1. Create a branch and keep changes focused.
2. Add or update tests in the matching `tests/unit`, `tests/integration`, or
   `tests/e2e` directory.
3. Run `uv run ruff check .`, `uv run mypy src/hound`, and
   `uv run pytest --cov=hound --cov-fail-under=80 -q`.
4. Update the relevant documentation and `CHANGELOG.md` entry.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`docs/workflow.md`](docs/workflow.md)
for the complete contribution and verification rules.

## Security

Redaction is enabled by default, external integrations are opt-in, and Hound
does not mutate infrastructure. Report suspected vulnerabilities privately
according to [`SECURITY.md`](SECURITY.md).

---

## 📚 Documentation Index

| Document | Description |
|:---|:---|
| 📚 [**Documentation Hub**](docs/README.md) | Map of guides, reference contracts, operations, schema, audits, and plans. |
| 📖 [**PRD & Specifications**](docs/prd.md) | Complete functional requirements, non-functional constraints, and scope. |
| 🏗️ [**Architecture Guide**](docs/architecture.md) | Pipeline mechanics, module map, data schemas, and contracts. |
| 📘 [**User & Integration Manual**](docs/guides/usage.md) | Comprehensive CLI, TUI, server, and integration usage. |
| 📋 [**Reference Contracts**](docs/reference/log-format.md) | Log, source, test-impact, timeline, and migration contracts. |
| 🛡️ [**Operations and Security**](docs/operations/threat-model.md) | Deployment, recovery, release, pilot, and security procedures. |
| 🔄 [**Contribution Workflow**](docs/workflow.md) | Development guidelines, code standards, and verification gates. |

---

## 📄 License

Hound is licensed under the [MIT License](LICENSE).
