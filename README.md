<div align="center" style="text-align: center; width: 100%;">

```text
██╗  ██╗ ██████╗ ██╗   ██╗███╗   ██╗██████╗ 
██║  ██║██╔═══██╗██║   ██║████╗  ██║██╔══██╗
███████║██║   ██║██║   ██║██╔██╗ ██║██║  ██║
██╔══██║██║   ██║██║   ██║██║╚██╗██║██║  ██║
██║  ██║╚██████╔╝╚██████╔╝██║ ╚████║██████╔╝
╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═════╝ 
```

### An Offline-First CLI & TUI Tool for Investigating CI/CD, Build, and Test Failures.

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Status-Production--Ready-brightgreen.svg" alt="Status"></a>
  <a href="#tests"><img src="https://img.shields.io/badge/Tests-493%20Passed-success.svg" alt="Tests"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python Version"></a>
  <a href="#security-and-privacy"><img src="https://img.shields.io/badge/Security-Redaction%20Default-orange.svg" alt="Security"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
</p>

</div>

---

**Hound Agent** is an offline-first diagnostic **developer tool** (CLI & TUI) designed to automatically investigate broken CI/CD pipelines, flaky test runs, build crashes, and deployment failures. It inspects raw execution logs and structured test artifacts, correlates stack traces with repository context, determines root causes, triages issue severity, and generates actionable incident reports and ticket drafts—**in a strictly read-only mode without mutating infrastructure**.

---

## ⚡ Why Hound Agent?

- 🔒 **Offline-First & Deterministic:** 100% functional out of the box with zero external dependencies, no API keys, and no network access required.
- 🤖 **Multi-Provider LLM Enhancement:** Seamlessly plug into OpenAI, Anthropic, Gemini, Groq, Ollama, DeepSeek, Azure, or local OpenAI-compatible endpoints when deeper synthesis is desired.
- 🛡️ **Zero-Crash CI Safety:** Automatic fallback to deterministic rule engines if LLM calls time out, hit rate limits, or fail JSON schema validation. Your CI pipeline never fails because of an AI outage.
- 💰 **Built-In Token & Cost Control:** Deduplication-first result caching, failure-kind routing (skip noisy flaky tests), and hard per-batch spend caps (`--max-cost-usd`, `--max-llm-calls`).
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

Hound requires **Python ≥ 3.10** and is managed via [`uv`](https://github.com/astral-sh/uv):

```sh
# Clone and install dependencies
git clone https://github.com/your-org/hound-agent.git
cd hound-agent
uv sync --extra dev
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
hound tui --logs ./ci-logs --out hound-agent-output --offline

# Launch TUI with LLM analysis and 4 parallel workers
hound tui --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
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

### 1. `hound analyze` — Batch Artifact Analysis

Scans all `.log`, `.xml` (JUnit), `.sarif`, and `.json` test reports directly inside a folder, generating `report.json`, `report.md`, and `ticket.md` per run.

```sh
# Standard offline analysis
hound analyze ./ci-logs --offline

# Include source context around stack frames from repository
hound analyze ./ci-logs --repo . --source-context --offline

# Output structured JSON report directly to a file
hound analyze ./artifacts --format json --output result.json

# Parallel multi-worker analysis
hound analyze ./ci-logs --jobs 4 --out hound-agent-output
```

#### Key Capabilities:
- **Structured Artifact Ingestion:** Parses JUnit XML, SARIF, and test JSON natively without lossy regex heuristics.
- **Stack Trace Context:** With `--repo` and `--source-context`, attaches ±2 lines of real code context for Python, Go, Rust, Java, TypeScript, C/C++, and deployment configurations (`.yaml`, `.tf`, `.tpl`).
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

Executes any build or test command, streams output to the terminal, and saves a redacted log alongside a JSON metadata sidecar in `.hound-agent/logs/`.

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
  --out ./out \
  --jobs 8 \
  --max-llm-calls 50 \
  --max-cost-usd 5.00
```

- Produces `summary-<batch-id>.json` (detailed per-log triage) and `usage-<batch-id>.json` (token telemetry, cost tracking, reuse counts).
- When spending limits are reached, remaining logs gracefully fall back to deterministic rule analysis and are marked `budget_skipped`.

---

### 4. `hound server` — Webhook Receiver for CI/CD & Production

Runs a lightweight, stdlib-based HTTP webhook service with bearer authentication and persistent SQLite job management.

```sh
export TH_SERVER_TOKEN="your-secure-token"

hound server \
  --host 0.0.0.0 \
  --port 8123 \
  --log-root ./ci-logs \
  --out ./server-runs \
  --workers 4 \
  --rate-limit 60
```

#### API Endpoints:
- `POST /analyze` — Submit analysis job `{"log": "relative/path.log", "offline": false}`
- `GET /jobs/<id>` — Poll asynchronous job status and results
- `GET /health` & `GET /ready` — Service liveness and readiness probes
- `GET /stats` — Real-time telemetry (queued, running, completed, engine breakdown)

---

### 5. `hound qa` — Long-Term Test History & Flakiness Tracking

Maintains a queryable SQLite database of historical test executions across runs, branches, and environments to track intermittent failures and duration regressions over time.

```sh
# Import JUnit or test log evidence into history store
hound qa import ./junit.xml --runner pytest --branch main --commit abc1234

# Query historical failure rates and p95 durations for a test
hound qa stats tests/test_checkout.py test_payment_failure

# View recent execution history
hound qa history tests/test_checkout.py test_payment_failure --days 30
```

---

### 6. Utility Commands

```sh
# Check local storage, dependencies, and environment readiness
hound doctor

# Generate a commented configuration template (.hound-agent.yml)
hound init

# List supported LLM providers and presets
hound list-providers

# Inspect previously stored analysis runs
hound list-runs --out hound-agent-output
hound report <run-id> --format markdown --output report.md

# Record human reviewer feedback to validate RCA accuracy
hound feedback record --run-id <run-id> --usefulness useful --actual-kind assertion_error

# Clean up analysis output directories
hound clean --out hound-agent-output --yes
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

> **Selection Priority:** CLI Flags > YAML `llm:` block > Generic `TH_API_*` env vars > Provider-specific env vars > Deterministic offline fallback.

---

## ⚙️ Configuration (`.hound-agent.yml`)

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
        run: |
          mkdir -p artifacts
          pytest --junitxml=artifacts/junit.xml | tee artifacts/pytest.log

      - name: Triage Failures with Hound
        if: steps.test_run.outcome == 'failure'
        uses: ./
        with:
          log: "artifacts/pytest.log"
          repo: "${{ github.workspace }}"
          out: "${{ github.workspace }}/hound-agent-output"
          offline: "true"

      - name: Upload Investigation Report
        if: steps.test_run.outcome == 'failure'
        uses: actions/upload-artifact@v4
        with:
          name: hound-investigation-report
          path: hound-agent-output/
```

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
uv run python demo_project/run_demo.py --profile smoke

# 2. Run high-volume scale benchmark (5,000 synthetic artifacts across 8 parallel workers)
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

---

## 🧪 Running Tests

```sh
# Run full unit & integration test suite
uv run pytest
```

> **Test Guarantee:** All tests run strictly with local fixtures—no network access or live API credentials needed (**493 passed, 5 skipped**).

---

## 📚 Documentation Index

| Document | Description |
|:---|:---|
| 📖 [**PRD & Specifications**](docs/prd.md) | Complete functional requirements, non-functional constraints, and scope. |
| 🏗️ [**Architecture Guide**](docs/architecture.md) | Pipeline mechanics, module map, data schemas, and contracts. |
| 📘 [**User & Integration Manual**](docs/usage.md) | Comprehensive usage guide (TUI, CLI, Integrations, Bahasa Indonesia). |
| 📋 [**Correlated Log Format**](docs/log-format.md) | Standard schema and field contracts for structured error logging. |
| 🔀 [**Schema Migration (v1.4 ➔ v2.0)**](docs/schema-migration-v1.4-to-v2.0.md) | Backward compatibility and RCA JSON schema upgrades. |
| 🔄 [**Contribution Workflow**](docs/workflow.md) | Development guidelines, code standards, and verification gates. |

---

## 📄 License

Hound Agent is licensed under the [MIT License](LICENSE).
