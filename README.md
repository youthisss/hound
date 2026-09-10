<div align="center">

<pre>
██╗  ██╗  ██████╗  ██╗   ██╗ ███╗   ██╗ ██████╗         ████████╗ ██████╗   █████╗    ██████╗  ███████╗ ██████╗
██║  ██║ ██╔═══██╗ ██║   ██║ ████╗  ██║ ██╔══██╗        ╚══██╔══╝ ██╔══██╗ ██╔══██╗  ██╔════╝  ██╔════╝ ██╔══██╗
███████║ ██║   ██║ ██║   ██║ ██╔██╗ ██║ ██║  ██║ █████╗    ██║    ██████╔╝ ███████║  ██║       █████╗   ██████╔╝
██╔══██║ ██║   ██║ ██║   ██║ ██║╚██╗██║ ██║  ██║ ╚════╝    ██║    ██╔══██╗ ██╔══██║  ██║       ██╔══╝   ██╔══██╗
██║  ██║ ╚██████╔╝ ╚██████╔╝ ██║ ╚████║ ██████╔╝           ██║    ██║  ██║ ██║  ██║  ╚██████╗  ███████╗ ██║  ██║
╚═╝  ╚═╝  ╚═════╝   ╚═════╝  ╚═╝  ╚═══╝ ╚═════╝            ╚═╝    ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═════╝  ╚══════╝ ╚═╝  ╚═╝
</pre>

<h3>Offline-First Diagnostic Agent for CI/CD, Build, Test, and Deployment Failures</h3>

<p align="center">
  <a href="https://pypi.org/project/hound-tracer/"><img src="https://img.shields.io/pypi/v/hound-tracer.svg" alt="PyPI Version"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/Status-Beta%20v0.4.1-yellow.svg" alt="Status"></a>
  <a href="#testing-and-verification"><img src="https://img.shields.io/badge/Tests-Targeted%20gates-success.svg" alt="Tests"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%20to%203.12-blue.svg" alt="Python Version"></a>
  <a href="#security-and-privacy"><img src="https://img.shields.io/badge/Security-Redaction%20Default-orange.svg" alt="Security"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
</p>

</div>

---

Hound Tracer is an offline-first diagnostic tool and terminal interface (TUI) for investigating CI/CD failures, build errors, test regressions, and container crashes.

Hound Tracer ingests execution logs, JUnit XML reports, SARIF static analysis files, and test runner outputs. It strips sensitive credentials and private data by default, frames stack traces across seven programming languages, correlates failure lines with git commits, categorizes issues, deduplicates recurring incidents, and drafts issue tickets for development teams.

Hound Tracer is strictly advisory and read-only. It inspects artifacts and produces structured findings; it does not deploy code, restart services, or alter infrastructure.

---

## Highlights

- **Offline-first analysis:** Built-in deterministic rules evaluate failures with zero network requests and no external API keys (`--offline`).
- **Multi-provider LLM support:** Connects to OpenAI, Anthropic, Google Gemini, Groq, Ollama, DeepSeek, Azure OpenAI, 9router, and generic OpenAI-compatible gateways.
- **Deterministic fallback:** Automatically switches to local rule evaluation if an LLM provider times out, returns HTTP 429 rate limits, or generates invalid responses.
- **Cost controls:** Caches root-cause findings by failure fingerprint (`dedup.reuse: true`) to avoid repeated model calls, skips specified failure kinds (`skip_kinds`), enforces per-run request caps (`--max-llm-calls`), and limits spend (`--max-cost-usd`).
- **Secret redaction:** Strips private keys, API tokens, passwords, database connection strings, email addresses, and IP addresses before text reaches disk or network requests.
- **Supply chain isolation:** Enforces source profiles (`trusted_branch`, `local_artifact`, `fork_pr`). Pull requests from forks run in a restricted sandbox with offline-only analysis, locked redaction, and disabled external delivery.
- **Container and infrastructure diagnostics:** Identifies Kubernetes `CrashLoopBackOff`, `OOMKilled` (exit code 137), container probe failures, scheduling constraints, Helm release rollbacks, and Terraform run errors.
- **Quality gates and analytics:** Tracks test flakiness and execution duration in SQLite (`hound insights`), and enforces configurable gates on test failures, coverage regressions, and SARIF static analysis findings (`hound gate`).
- **Idempotent ticket delivery:** Dispatches issues to GitHub, Jira, GitLab, and Slack through a persistent SQLite delivery ledger that prevents duplicate ticket creation during network retries.

---

## Architecture

```text
  ┌────────────────────────────────────────────────────────────────────────┐
  │  Failure Artifacts (.log, JUnit .xml, SARIF .sarif, test .json)        │
  │  + Optional Git Checkout & Sidecar Metadata (.hound/logs/*.json)       │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 1. INGESTION & REDACTION                                               │
  │    • Head/Tail windowing (preserves start and failure boundaries)      │
  │    • Secret & PII scrubbing (Keys, Tokens, Passwords, IP addresses)    │
  │    • Stack trace framing (Python, Go, Rust, Java, JS/TS, C#)           │
  │    • Request correlation (trace_id, request_id, user_id)               │
  │    • Git context (diff, blame, CODEOWNERS, recent commits)             │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 2. ROOT CAUSE ANALYSIS (RCA ENGINE)                                    │
  │    ├─► Dedup Cache Reuse (fingerprint match: zero API calls)           │
  │    ├─► LLM Synthesis (OpenAI, Gemini, Claude, Ollama, DeepSeek)        │
  │    └─► Deterministic Fallback Rules (offline baseline and safe backup) │
  │    • Structured evidence citations ([llm-ref ev-001])                  │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 3. TRIAGE & DEDUPLICATION                                              │
  │    • Severity (Critical, High, Medium, Low) and Priority (P1 to P5)    │
  │    • Component mapping through path glob patterns                      │
  │    • Normalized SHA-256 fingerprinting (SQLite WAL or JSON file)       │
  │    • Flakiness detection from retry-then-pass execution records        │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 4. INVESTIGATION, TIMELINE & OUTPUT                                    │
  │    • Timeline reconstruction: chronological ordering & causal tracing  │
  │    • Report artifacts: report.json (Schema v2.0), report.md, ticket.md │
  │    • Idempotent delivery: GitHub Issues, Jira, GitLab, Slack           │
  │    • Execution modes: Interactive TUI, CLI automation, Webhook server  │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Using uv (Recommended)

```sh
# Install globally
uv tool install hound-tracer

# Verify installation
hound --version
hound doctor
```

### Using pipx or pip

```sh
# Install with pipx (isolated application environment)
pipx install hound-tracer

# Or install in a standard Python environment (Python >= 3.10, < 3.13)
pip install hound-tracer
```

### From Source

```sh
git clone https://github.com/youthisss/hound-tracer.git
cd hound-tracer
uv sync --extra dev
uv run hound doctor
```

---

## Quick Start

```sh
# 1. Run environment and diagnostic readiness checks
hound doctor

# 2. Launch the interactive Terminal UI (TUI) pointing to a log directory
hound console --logs ./ci-logs --offline

# 3. Analyze artifacts in a directory using offline rules
hound analyze ./ci-logs --offline

# 4. Intercept a test command; immediately analyze if the command exits non-zero
hound log --analyze --offline -- pytest -q
```

---

## Terminal Interface (TUI)

Hound Tracer includes an interactive terminal user interface built with [Textual](https://textual.textualize.io/) for navigating failure logs, inspecting stack frames, and reviewing diagnostic reports.

```sh
# Launch in offline mode
hound console --logs ./ci-logs --offline

# Launch with online LLM analysis and worker limits
hound console --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

### Keyboard Shortcuts

| Key | Action | Description |
|:---:|:---|:---|
| `a` | **Analyze** | Analyze or retry the currently selected log artifact |
| `A` | **Analyze All** | Sequentially or in parallel analyze all visible logs |
| `b` | **Browse Folder** | Open interactive filesystem directory picker |
| `r` | **Refresh** | Reload log listing and recent analysis runs |
| `h` | **Home** | Return to the default Home view |
| `f` / `l` | **Artifacts / Results** | Open the artifact or stored-results workspace |
| `y` / `i` | **Quality / Overview** | Open QA workflows or the current run overview |
| `m` | **Sidebar** | Focus the navigation sidebar |
| `s` | **Settings** | Configure LLM providers, models, API keys, base URLs, and offline mode |
| `v` | **Feedback** | Review the currently opened stored run |
| `o` | **Toggle Offline** | Switch between local deterministic rules and online model analysis |
| `space` | **Toggle Selection** | Select or deselect the focused artifact or stored run |
| `z` / `d` | **Select / Deselect All** | Change selection for the active workspace |
| `p` / `n` | **Previous / Next** | Change page or move between opened results, depending on context |
| `x` / `X` | **Clear** | Clear one stored run or all selected runs with confirmation |
| `g` | **Focus Filter** | Focus the filter for the active list workspace |
| `c` | **Copy Report** | Copy generated Markdown report to clipboard |
| `e` | **Copy Ticket** | Copy formatted ticket draft to clipboard |
| `?` | **Help** | Display keyboard shortcut reference |
| `q` | **Quit** | Exit the interface |

---

## Command-Line Reference

Use canonical subcommands for automation scripts and CI pipelines:

| Canonical Command | Description |
|:---|:---|
| `hound analyze` | Analyze single files or directories of artifacts |
| `hound batch` | High-throughput batch processing with spend guardrails |
| `hound console` | Launch interactive Textual terminal UI |
| `hound log` | Intercept, tee-stream, and optionally analyze command execution |
| `hound gate` | Evaluate test results, coverage deltas, and SARIF against a policy |
| `hound insights` | Long-term test history, flakiness, and runtime analytics |
| `hound serve` | HTTP webhook server with persistent SQLite job queue |
| `hound doctor` | Validate environment, storage, and dependency health |
| `hound config` | Inspect, set, or strictly validate configuration (`.hound.yml`) |
| `hound providers` | List available LLM provider presets |
| `hound models` | Query or refresh provider model discovery catalog |
| `hound runs` | List historical analysis runs stored on disk |
| `hound report` | Re-render a stored run report in text, JSON, or Markdown |
| `hound feedback` | Record engineer ratings and export regression test candidates |
| `hound delivery` | Inspect and explicitly recover persisted external-delivery outcomes |
| `hound incidents` | Inspect recurrence and invalidate cached RCA snapshots without deleting history |
| `hound client` | Submit, inspect, poll, or cancel jobs on a bounded Hound server |
| `hound clean` | Safely purge output directories verified by `.hound-owned` markers |

## Capability boundaries

The four supported surfaces share the same read-only analysis pipeline, but they
do not expose the same controls:

| Surface | Primary capabilities | Deliberate limits |
|:---|:---|:---|
| CLI | Headless analysis, batch budgets, log capture, QA gates/history, reports, feedback, providers, and opt-in delivery | No interactive screen; automation must handle exit codes and output files |
| TUI | Interactive artifact selection, local/LLM analysis, stored runs, report/ticket/context/raw-log review, settings, QA history import, and feedback | No infrastructure mutation, connector collection, or automatic external delivery; bounded local history/feedback/preferences writes are allowed |
| Server | Authenticated `POST /analyze`, bounded jobs, polling, health/readiness, and telemetry endpoints | HTTP receiver only; no interactive UI, shell commands, or deploy/rollback operations |
| GitHub Action | One artifact analysis with JSON/Markdown/ticket outputs and Action outputs | Action wrapper only; it does not expose the server, TUI, or long-term QA export workflows |

The tested platform/runtime boundaries are maintained in
[`docs/support-matrix.md`](docs/support-matrix.md).

| Capability | CLI | TUI | Server | Action |
|:---|:---:|:---:|:---:|:---:|
| Analyze artifacts | Yes | Yes | Yes | Yes |
| Batch analysis | Yes | Yes | Via queue | Limited |
| QA history import | Yes | Yes | No | No |
| Quality gate | Yes | Yes | No | Optional |
| Feedback record | Yes | Yes | No | No |
| Feedback export | Yes | No | No | No |
| DevOps enrichment | Yes | Read-only report validation/readiness view | Yes | Optional |
| Ticket delivery | Yes | Read-only status | Caller-managed | Optional |
| Log capture | Yes | No | No | No |
| Server lifecycle | Yes | No | N/A | No |

The console opens on Home and provides three data workspaces: Artifacts,
Results, and Quality. Settings is an overlay, Feedback is a modal, and the
Overview, Report, Ticket, Context, and Raw log tabs appear only after a run is
opened. The console can inspect delivery history and connector audits, but never
sends external delivery or constructs an infrastructure mutation command. QA
history export, feedback export, delivery reconciliation, and incident
invalidation are CLI-only administrative operations.

---

### hound analyze: Core Artifact Analysis

Scans `.log`, `.xml` (JUnit), `.sarif`, and `.json` test reports. Generates `report.json` (Schema v2.0), `report.md`, and `ticket.md`.

Directory analysis uses opaque `run-<id>` subdirectories. The legacy
`hound analyze --log <single-file>` form keeps its direct `--output-dir` layout
for compatibility; new automation should pass a directory.

```sh
# Offline analysis (safe, deterministic, zero network requests)
hound analyze ./ci-logs --offline

# Include source code snippets from Git repository around stack frames
hound analyze ./ci-logs --repo-dir . --source-context --offline

# Output structured JSON directly to file
hound analyze ./artifacts --format json --output ./results/hound-report.json

# Parallel multi-worker analysis with prompt preview (dry-run without calling API)
hound analyze ./ci-logs --jobs 4 --llm-preview --output-dir hound-output

# Analyze and automatically file tickets to GitHub Issues and post to Slack
hound analyze ./ci-logs --gh --slack-webhook
```

#### Exit Codes

| Exit Code | Meaning | Condition |
|:---------:|:---|:---|
| `0` | **Clean / Healthy** | Analysis completed successfully; no failure signals detected. |
| `1` | **Failure Detected** | Analysis completed; actionable failure (test failure, crash, OOM) found. |
| `2` | **Usage / Config Error** | Invalid CLI arguments, missing paths, or failed configuration validation. |
| `3` | **Execution Error** | Internal pipeline crash, I/O error, or failed ticket delivery dispatch. |

---

### hound batch: Scaled Processing with Budgets

Processes large directories of build logs with atomic deduplication and budget limits.

```sh
hound batch --logs ./ci-logs \
  --output-dir ./batch-output \
  --jobs 8 \
  --max-llm-calls 50 \
  --max-cost-usd 5.00
```

- Produces `summary-<batch-id>.json` (per-artifact classification and triage) and `usage-<batch-id>.json` (token metrics, cost tracking, and reuse count).
- When `--max-llm-calls` or `--max-cost-usd` thresholds are reached, remaining artifacts fall back to deterministic local rules and receive the `budget_skipped` tag.

---

### hound log: Process Interception and Tee Streaming

Runs build, test, or deployment commands while live-streaming output to stdout/stderr. Simultaneously writes a redacted log file and a JSON metadata sidecar (`cwd`, `git_branch`, `git_commit`, `exit_code`, `timestamp`) under `.hound/logs/`.

```sh
# Capture test output and stream to console
hound log -- npm test
hound log --name unit-tests -- pytest -q

# Intercept piped stdout from CLI tools
kubectl logs deployment/api -n prod | hound log --name api-deploy
terraform apply -auto-approve 2>&1 | hound log --name tf-apply

# Capture and immediately run root-cause analysis on failure
hound log --analyze --offline -- pytest -q
```

---

### hound gate: Deterministic Quality Gate Policy

Evaluates test outcomes, code coverage deltas, and SARIF static analysis findings against a versioned policy file (`quality-gate.yml`).

```sh
hound gate ./test-results \
  --repo-dir . \
  --baseline-ref origin/main \
  --candidate-ref HEAD \
  --policy ./quality-gate.yml \
  --coverage ./coverage/coverage.json \
  --baseline-coverage ./coverage/baseline-coverage.json \
  --sarif ./reports/semgrep.sarif \
  --output gate-results.json
```

#### Quality Gate Policy Example (`quality-gate.yml`)

```yaml
version: "1.0"
rules:
  # Block on new test failures introduced in candidate ref
  new_failure: block
  # Warn on tests showing flaky behavior
  flaky: warn
  # Block if overall coverage drops by more than 2%
  coverage_delta:
    outcome: block
    threshold_percent: -2.0
  # Block if changed line coverage falls below 80%
  changed_line_coverage:
    outcome: block
    threshold_percent: 80.0
    include: ["src/**"]
    exclude: ["tests/**", "docs/**"]
  # Block on critical SARIF security findings
  critical_sarif: block
  sarif_warning: warn
```

---

### hound insights: Test Run History and Flakiness Analytics

Maintains an SQLite database tracking test durations, success rates, and flakiness across branches, environments, and commit hashes.

```sh
# Import JUnit XML into historical store
hound insights import ./junit.xml \
  --test-runner pytest \
  --branch main \
  --commit abc1234 \
  --environment "os=linux;python=3.11"

# Query aggregate statistics (failure rate, p95 duration)
hound insights stats tests/test_payment.py test_checkout_idempotency

# View recent execution records
hound insights history tests/test_payment.py test_checkout_idempotency --window-days 30

# List tracked tests across all suites
hound insights tests --suite-prefix tests/unit/
```

---

### hound serve: Production Webhook Server

HTTP webhook service with Bearer token authentication and persistent SQLite job management (`jobs.sqlite3`).

```sh
export HOUND_SERVER_TOKEN="your-secure-auth-token"

hound serve \
  --host 127.0.0.1 \
  --port 8123 \
  --log-root ./ci-logs \
  --output-dir ./server-runs \
  --workers 4 \
  --rate-limit 60
```

#### Endpoints

- `POST /analyze`: Submit analysis job `{"log": "relative/path.log", "offline": false}`
- `GET /jobs/<id>`: Poll bounded job status, engine, errors, and the managed report path
- `DELETE /jobs/<id>`: Cancel a queued or running job; a worker that already started is not force-killed
- `GET /health` and `GET /ready`: Health and readiness probes for orchestrators
- `GET /stats`: Telemetry counters (queued, running, completed, engine breakdown)

For production deployment with reverse-proxy TLS termination and systemd service units, refer to [`docs/guides/server-deployment.md`](docs/guides/server-deployment.md).

---

### Operational Commands

```sh
# Generate a commented configuration template (.hound.yml)
hound init

# Validate configuration keys and schema strictly
hound config validate --config .hound.yml

# Inspect current resolved configuration
hound config show

# Discover and cache available models from an LLM provider
hound models --provider ollama --refresh

# Record engineer feedback on analysis accuracy
hound feedback record --run-id run-abc1234 --usefulness useful --actual-kind test_failure

# Export reviewed feedback as candidate regression fixtures
hound feedback export --candidate-fixtures --output candidate-fixtures.json

# Safely purge analysis output directory (checks .hound-owned marker)
hound clean --output-dir hound-output --yes

# Inspect and explicitly recover delivery outcomes
hound delivery list --output-dir hound-output --json
hound delivery inspect --output-dir hound-output --incident-key <key> --destination github --json
hound delivery reconcile --output-dir hound-output --incident-key <key> --destination github --external-id <id>
hound delivery mark-failed --output-dir hound-output --incident-key <key> --destination github --error "verified absent" --confirm-absent
hound delivery retry-failed --output-dir hound-output --incident-key <key> --destination jira

# Inspect recurrence and stale RCA provenance without deleting history
hound incidents list --output-dir hound-output --json
hound incidents inspect --output-dir hound-output --key <dedup-key> --json
hound incidents invalidate --output-dir hound-output --key <dedup-key> --yes

# Use the bounded server client
hound client submit --url http://127.0.0.1:8123 --token "$HOUND_SERVER_TOKEN" --log failure.log --offline --wait
```

`hound config set` intentionally supports only the non-secret `model` key. Use
YAML for other non-secret settings and environment variables or the keyring for
credentials; the command does not accept arbitrary keys.

---

## Supported Failure Types

Hound Tracer classifies failure signals across the software delivery lifecycle into over 25 distinct failure kinds:

| Stage | Failure Kinds | Typical Indicators & Diagnostic Sources |
|:---|:---|:---|
| **Build & Compile** | `compilation_error`<br>`import_error`<br>`dependency_resolution`<br>`config_missing` | Syntax errors, broken typings, missing modules, package conflict resolution errors, missing lockfile sync. |
| **Testing** | `test_failure`<br>`timeout`<br>`flaky` | Failing assertions, hanging unit/integration tests, verified rerun-then-pass flakiness (pytest-rerunfailures, Jest retry, Go `-count`). |
| **CI System** | `ci_failure`<br>`disk_full`<br>`api_rate_limited`<br>`permission_error` | Pipeline step non-zero exits, missing step artifacts, runner disk space exhaustion, API 429 rate limit rejections, CI token access denied. |
| **Deployment & CD** | `deployment_failed`<br>`rollback`<br>`readiness_timeout`<br>`migration_failed` | Terraform apply rejections, Helm release crashes, database migration locks/failures, deployment deadlines exceeded. |
| **Container & K8s** | `oom_killed`<br>`crash_loop`<br>`image_pull_error`<br>`registry_auth_failure`<br>`scheduling_failed`<br>`quota_exceeded`<br>`liveness_probe_failed`<br>`readiness_probe_failed` | Exit code 137 (OOM), `CrashLoopBackOff`, invalid image tags, Docker registry 401/403, pod scheduling taints/tolerations, memory/CPU quota limits, HTTP probe failures. |
| **Network & Security** | `network_failure`<br>`tls_certificate_error` | DNS lookup failures, connection refused, expired or untrusted TLS certificates on mirrors or registries. |

### Ecosystem Ingestion Support

- **Stack Trace Framing:** Python, Go, Rust, Java, JavaScript/TypeScript (V8 engine format), C/C++, C#, and deployment configurations (`.yaml`, `.tf`, `.tpl`).
- **Test Runner Ingestion:** pytest, Jest, Vitest, Go test (`-v`), RSpec, Cargo test, dotnet test, and JUnit XML.
- **Static Analysis & Security:** SARIF 2.1.0 output (Semgrep, CodeQL, Snyk, ESLint, Trivy).

---

## Supported Providers

Hound Tracer connects to any OpenAI-compatible API endpoint. Select presets with `--provider` or through environment variables:

| Provider Preset | Required Environment Variable(s) | Default Base URL | Model Selection |
|:---|:---|:---|:---|
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `auto` or explicit model ID (e.g. `gpt-4o-mini`) |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | *(OpenAI-compatible proxy required)* | `auto` or explicit model ID (e.g. `claude-3-5-sonnet`) |
| `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` | `auto` or explicit model ID (e.g. `gemini-1.5-pro`) |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | `auto` or explicit model ID (e.g. `llama-3.3-70b-versatile`) |
| `ollama` | None required | `http://localhost:11434/v1` | `auto` or explicit model ID (e.g. `qwen2.5-coder:7b`) |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` | `auto` or explicit model ID (e.g. `deepseek-chat`) |
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_BASE_URL` | *(Resource-specific)* | Explicit deployment name |
| `9router` | `NINE_ROUTER_API_KEY` | `http://127.0.0.1:20128/v1` | `auto` or explicit model ID |
| `custom` | `CUSTOM_API_KEY`, `CUSTOM_BASE_URL` | *(User-specified)* | `auto` or explicit model ID |

Configuration resolution order:
CLI flags > YAML `llm:` block > Generic `HOUND_*` environment variables > Provider-specific environment variables > Offline fallback rules.

Query provider model catalogs with:
```sh
hound models --provider groq --refresh
```

---

## Configuration

Generate a starter configuration file (`.hound.yml`) with `hound init`. Validate syntax with `hound config validate`.

```yaml
# ==============================================================================
# LLM Provider Configuration
# ==============================================================================
llm:
  provider: gemini                   # openai | anthropic | gemini | groq | ollama | deepseek | azure | custom
  model: auto                        # auto resolves first cached catalog model; or pin model ID
  temperature: 0.2
  timeout: 120.0
  max_retries: 3                     # Exponential backoff on 429 and 5xx responses
  max_concurrency: 4                 # Parallel requests per process
  routing: exclude-kinds             # all | exclude-kinds
  skip_kinds: [flaky, timeout]       # Skip model calls for noisy kinds (100% token savings)
  pricing:
    default:
      prompt_per_mtok: 0.15          # USD per million prompt tokens
      completion_per_mtok: 0.60      # USD per million completion tokens

# ==============================================================================
# Security, Trust & Privacy
# ==============================================================================
redact: true                         # Enable secret and PII scrubbing (default: true)

trust:
  source_class: local_artifact       # trusted_branch | local_artifact | fork_pr

# ==============================================================================
# Component Triage Mapping (Glob Pattern -> Engineering Team)
# ==============================================================================
components:
  "services/billing/**": "team-billing"
  "services/auth/**": "team-security"
  "k8s/**": "platform-infra"
  "frontend/**": "team-ui"

# ==============================================================================
# Incident Deduplication & Snapshot Cache
# ==============================================================================
dedup:
  backend: sqlite                    # sqlite (WAL mode, multi-worker safe) | file (JSON)
  state_file: ".hound/state.sqlite3"
  max_entries: 50000
  retention_days: 90
  reuse: true                        # Enable dedup-first RCA snapshot reuse
  reuse_after_occurrences: 3         # Reuse previous analysis after 3 identical runs

# ==============================================================================
# Incident Policy & Severity Overrides
# ==============================================================================
policy:
  recurrence_threshold: 3
  severity_overrides:
    production:
      deployment_failed: critical
      oom_killed: critical
    staging:
      deployment_failed: high

# ==============================================================================
# Observability & Deployment Runbooks
# ==============================================================================
observability:
  prometheus_url: "https://prometheus.internal"
  tempo_url: "https://tempo.internal"
  window_minutes: 15

runbooks:
  api: "https://runbooks.internal/services/api.md"
  billing: "https://runbooks.internal/services/billing.md"

# ==============================================================================
# Issue Tracker Integrations (Warn-only on network failure)
# ==============================================================================
github:
  repo: "my-org/my-repo"             # or GH_REPO environment variable
jira:
  url: "https://jira.example.com"
  project: "PROJ"
gitlab:
  url: "https://gitlab.com"
  project: "my-org/my-repo"
slack:
  webhook_url: "https://hooks.slack.com/services/..."
```

---

## CI/CD Integration

### Official GitHub Action

Hound Tracer provides a GitHub Action. Until an immutable release tag is
published, pin the reviewed commit shown below:

```yaml
name: CI Suite with Hound Tracer Failure Triage

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run Test Suite
        id: test_run
        continue-on-error: true
        run: |
          mkdir -p artifacts
          pytest --junitxml=artifacts/junit.xml | tee artifacts/pytest.log

      - name: Investigate Failures with Hound Tracer
        if: steps.test_run.outcome == 'failure'
        uses: youthisss/hound-tracer@v0.4.1
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

### Docker Execution

Run Hound Tracer inside an isolated container with mounted artifact volumes:
This is an operator/CI path; Docker and Trivy execution are not available in the
current verification workspace and are not claimed as locally passed gates.

```sh
# Build image locally
docker build -t hound-tracer .

# Run offline analysis mounting local log directory
docker run --rm -v "$PWD/ci-logs:/logs:ro" -v "$PWD/hound-output:/out" \
  hound-tracer analyze /logs --output-dir /out --offline
```

---

## Security and Privacy

1. **Redaction by Default:**
   Log text is scrubbed before being passed to model prompts, saved to JSON reports, or dispatched to ticketing systems. Target patterns include private keys, bearer tokens, JWTs, AWS and Azure credentials, passwords, database URLs, emails, and IP addresses.
2. **Untrusted Repositories:**
   Hound Tracer treats analyzed Git checkouts as untrusted input. Hound Tracer never automatically loads configuration from analyzed repositories; `--config` must be explicitly specified by operators.
3. **Fork PR Sandboxing (`fork_pr`):**
   When analyzing pull requests from forks, Hound Tracer isolates execution: offline mode is mandatory, redaction cannot be disabled, and external ticket delivery and source extraction are suppressed.
4. **Symlink and Path Traversal Defenses:**
   Hound Tracer validates all target output directories and generated file paths, preventing symlink traversal or unintended file overwrites. Output cleanup (`hound clean`) verifies `.hound-owned` integrity markers before removing files.

---

## Testing and Verification

Hound Tracer maintains an automated test suite with local isolation guarantees:

```sh
# Run complete test suite (unit, integration, and end-to-end)
uv run pytest

# Run with test coverage measurement
uv run pytest --cov=hound --cov-report=term-missing

# Run code linter and static type checker
uv run ruff check .
uv run mypy src/hound

# Run offline accuracy and evaluation threshold check
uv run python -m hound.eval --offline --check --format json
```

---

## Repository Structure

```text
src/hound/
├── __init__.py          # Package metadata and __version__
├── cli.py               # Command-line interface definition and dispatch
├── service.py           # Shared service layer for CLI, TUI, server, and Action
├── pipeline.py          # Core investigation pipeline orchestrator
├── models.py            # Dataclasses and RCA Document Schema v2.0
├── config.py            # Configuration loader, validation, and provider presets
├── tui.py               # Interactive Textual terminal application
├── server.py            # HTTP webhook service and SQLite job queue
├── collector.py         # Subprocess capture, tee-streaming, and metadata sidecar
├── trust.py             # Security trust profiles (trusted_branch, fork_pr, local)
├── feedback.py          # Structured review feedback store and candidate export
├── eval.py              # Offline accuracy evaluation harness and gate
├── analyze/             # RCA reasoning: LLM client, rule fallback, cost accounting
├── ingest/              # Artifact parsers, windowing, stack trace framing, redaction
├── triage/              # Severity classifier, component mapper, SHA-256 deduplication
├── qa/                  # Test history SQLite store, coverage, SARIF, and quality gate
├── devops/              # Timeline reconstruction, causal tracing, incident correlation
├── connectors/          # Read-only deployment audits (K8s, Helm) and observability (Prometheus/Tempo)
├── source/              # Repository source context extraction and impact analysis
└── output/              # Markdown/JSON report rendering, tickets, Slack, delivery ledger
```

---

## Documentation

Comprehensive specifications, operational manuals, and architecture guides:

| Document | Topic |
|:---|:---|
| [**Architecture Deep Dive**](docs/architecture.md) | Pipeline mechanics, data contracts, and module boundaries |
| [**Security & Threat Model**](docs/operations/threat-model.md) | Redaction mechanics, untrusted inputs, and supply chain isolation |
| [**Server Deployment Guide**](docs/guides/server-deployment.md) | Reverse-proxy setup, rate limiting, and systemd units |
| [**GitHub Action Guide**](docs/guides/github-action.md) | Action inputs, outputs, trust profiles, and upgrade guidance |
| [**Reference Contracts**](docs/reference/log-format.md) | Log formats, timeline schemas, and test impact contracts |
| [**Support Matrix**](docs/support-matrix.md) | Tested runtimes, operating systems, and external boundaries |
| [**Release Checklist**](docs/operations/release-checklist.md) | Maintainer release, publication, and recovery gates |
| [**Changelog**](CHANGELOG.md) | Release history, migration notes, and version changes |

---

## License

Hound Tracer is open-source software distributed under the [MIT License](LICENSE).
