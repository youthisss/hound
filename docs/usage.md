# Hound Agent Usage Guide

Hound Agent collects and analyzes CI/CD/build/test failures, estimates the
root cause, performs triage, stores reports, and drafts tickets. The main
workflow is available through an interactive TUI and a CLI for automation and
CI.

## 1. Installation

Requires Python >= 3.10 and [uv](https://docs.astral.sh/uv/).

```sh
cd hound-agent
uv sync --extra dev
uv run hound --version
```

The package also provides the `hound` executable after installation.

## 2. Default TUI

Run without arguments from an interactive terminal:

```sh
uv run hound
```

Hound Agent opens the TUI only when stdin and stdout are TTYs. In a pipe,
redirect, or non-interactive CI, a command without arguments exits with code
`2` and suggests:

```sh
hound analyze <log-directory>
```

Hound Agent never auto-analyzes the current working directory when the command
is empty.

The TUI can also be opened explicitly:

```sh
uv run hound tui --logs ./ci-logs --out hound-agent-output --offline
uv run hound tui --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

If `--logs` is not given, the TUI uses `.hound-agent/logs` when that collector
output directory is available; otherwise it opens the current directory.

### TUI Workflow

The TUI opens on the **Home** page with the HOUND wordmark, directory and
provider readiness, quick start, main shortcuts, and setup recommendations.
`Overview` is now the first result tab alongside `Report`, `Ticket`, and
`Raw log`.

1. The `Settings [s]` button is in the sidebar after the Recent Runs list and
   can be opened at any time with `s`.
2. Select a directory with the `Browse folder` button or press `b`; the path
   can also be typed manually.
3. Press `Load directory` after typing a manual path.
4. Use the log-name filter when needed. Type filters (`Deploy`, `Build`,
   `Test`, `CI`, `Unknown`) and sorting by time, type, or name can be combined.
   `Analyze all visible` only processes artifacts that pass the active filters.
5. Select a `.log` file and run `Analyze` or press `a`.

The UI shows the active file count and path. Analyze is disabled when the
directory or log is invalid. While analysis is running, buttons show a
progress estimate and duplicate submissions are blocked.

`Analyze all visible` supports bounded parallelism via `--jobs`. In online
mode, use `--max-llm-calls` as a hard call limit and `--max-cost-usd` as an
estimated-cost guardrail. The TUI batch summary shows call counts,
budget-skipped artifacts, and estimated cost.

Tabs available:

- `Overview`: severity, failed stage, root cause, confidence, duration/
  timestamp, and recommended action.
- `Report`: the Markdown report.
- `Ticket`: the draft ticket.
- `Raw log`: the active log content.
- `Settings`: provider, model, API key override, base URL, and mode.

`Recent runs` shows run name, relative age, severity/status, and a failure
summary. The list has a vertical scrollbar; select a run to update Overview,
Report, Ticket, and Raw log.

The TUI state is explicit: empty, loading, success, and error. Failed analyses
show a retry option.

### TUI Shortcuts

| Key | Action |
|---|---|
| `a` | Analyze or retry |
| `b` | Open folder picker for the log directory |
| `r` | Refresh logs and recent runs |
| `s` | Open Settings and focus the provider |
| `o` | Toggle offline mode |
| `Enter` | Open the selected log |
| `c` | Copy Report in the relevant context |
| `e` | Copy Ticket in the relevant context |
| `?` | Open the help overlay |
| `Esc` | Close overlay or release focus |
| `q` | Quit |

The bottom shortcut bar changes according to the active tab/context.

### Providers and Models

Settings supports local routers on `http://127.0.0.1:20128/v1` and custom
OpenAI-compatible providers. `Connect & discover` tests the `/models`
endpoint, stores the API key in the operating system keyring, and loads the
model catalog. Custom provider definitions are global; the project YAML only
selects a provider and model. HTTP is only accepted for loopback endpoints;
remote endpoints require HTTPS.

## 3. Collecting Logs

`hound log` creates a reusable log file from a command or piped stdin.

### Run a Command

```sh
hound log -- npm test
hound log -- pytest -q
hound log -- docker build .
hound log --name unit-tests -- pytest -q
```

The command runs directly without a shell. stdout and stderr are merged,
streamed live to the terminal, and then saved. The child command's exit code is
preserved.

### Capture Piped Input

```sh
kubectl logs deployment/api | hound log --name api
npm test 2>&1 | hound log --name npm-test
kubectl rollout status deployment/api 2>&1 | hound log --name api-rollout --analyze --offline
```

Without a command and without piped stdin, the collector exits with code `2`.
Empty piped stdin is also rejected.

### Collector Output Location

Default:

```text
.hound-agent/logs/
|- 20260811T143012Z-npm.log
`- 20260811T143012Z-npm.json
```

Set a destination:

```sh
hound log --output captured.log -- npm test
hound log --output ./existing-directory -- npm test
```

`--output` accepts a `.log` file or an existing directory.

The `.log` file, JSON metadata, and the live terminal stream are redacted by
default. Use `--raw-console` only when raw terminal output is truly required.
The metadata contains source, name, command, exit code, timestamp, duration,
cwd, log location, redaction status, branch, commit, and changed files. Values
after common flags such as `--token`, `--password`, `--secret`, and
`--api-key` are redacted in the metadata.

### Capture and Analyze

```sh
hound log --analyze --offline -- npm test
hound log --analyze -- npm test
```

`--analyze` uses the same shared analysis service as the CLI, TUI, and server.
Analysis does not run automatically without this flag, so the collector never
makes hidden LLM calls.

If the child command fails, its exit code is preserved. If the child succeeds
but analysis fails, the command exits with code `3`.

## 4. Directory Analysis

The canonical command accepts a directory containing `.log` files:

```sh
hound analyze ./ci-logs
hound analyze ./ci-logs --offline
hound analyze ./ci-logs --repo ./repo --out hound-agent-output
```

Use `hound doctor` to check Python, configuration, providers, output directory,
Git, and local operational tooling without printing credential values:

```sh
hound doctor
hound doctor --json
hound config show --json
```

`config show` only reports credentials as `configured` or `missing`.

The scan is direct-level only, not recursive. Supported input formats: `.log`,
JUnit `.xml`, SARIF, and test-report `.json`. The directory must exist, be
readable, and contain at least one supported artifact.

Legacy `analyze --log <file>` is still accepted for compatibility but is not
shown in help and is not the recommended syntax.

### CLI Output Formats

```sh
hound analyze ./ci-logs --format text
hound analyze ./ci-logs --format json
hound analyze ./ci-logs --format markdown
hound analyze ./ci-logs --format json --output result.json
```

- `text`: severity, root cause, failed stage/kind, confidence, recommended action.
- `json`: one valid JSON object without progress/debug noise on stdout.
- `markdown`: a Markdown summary per run.
- `--output`: writes formatted output to a file and keeps stdout empty.
- Warnings and errors are always written to stderr.

Each log gets a separate run directory:

```text
hound-agent-output/
|- run-a1b2c3d4e5f6/
|  |- report.json
|  |- report.md
|  `- ticket.md
|- run-f6e5d4c3b2a1/
|  |- report.json
|  |- report.md
|  `- ticket.md
`- .hound-agent/
   `- state.json
```

Run IDs are opaque (`run-<random>`) so file names that may contain PII or
secrets never leak into output paths.

### Analyze Exit Codes

| Code | Meaning |
|---|---|
| `0` | Analysis completed; no recognized CI/CD/build/test failure |
| `1` | Analysis completed; at least one failure found |
| `2` | Invalid arguments, path, directory content, or configuration |
| `3` | Internal analysis or output error |

Exit `1` is a valid analysis result, not an application crash.

CI example:

```sh
hound analyze ./artifacts/logs --offline --format json --output hound-agent.json
code=$?

if [ "$code" -eq 1 ]; then
  echo "Hound Agent found a CI failure"
elif [ "$code" -ge 2 ]; then
  exit "$code"
fi
```

### Offline Mode

`--offline` forces local rule-based analysis and local file dedup. This mode
never contacts an AI provider. To keep the no-network contract explicit,
`--offline` cannot be combined with `--gh`, `--jira`, `--gitlab`, or
`--slack-webhook`.

### CD Analysis

The `deploy` stage recognizes Kubernetes rollout/readiness, image pull, Helm
rollback, Terraform apply, migration, and deployment permission failures. This
feature only analyzes logs and never runs deploys, retries, rollbacks, or
infrastructure changes.

### QA Intelligence & Test History

```sh
# Analyze and classify test artifacts against stored history
hound qa analyze ./artifacts/junit.xml --json

# Compare against a specific commit baseline to detect likely regressions
hound qa analyze ./artifacts/junit.xml --baseline 5a3f2e1

# Import test reports into the history store
hound qa import ./artifacts/junit.xml --run-id run-101 --commit 5a3f2e1 --branch main
```

## 5. Viewing Stored Runs

```sh
hound report <run-id>
hound report build-error --out hound-agent-output
hound report build-error --format json
hound report build-error --format markdown --output report.md
```

The command reads `<out>/<run-id>/report.json`. The run ID must be a single
directory name and must not escape the output root.

### Output Operations

```sh
# create a config template without overwriting an existing config
hound init

# list stored runs
hound list-runs --out hound-agent-output
hound list-runs --out hound-agent-output --json

# delete all analysis output, only with explicit confirmation
hound clean --out hound-agent-output --yes
```

## 6. Model Configuration

Persist a provider preset or model name to YAML:

```sh
hound config set model gemini
hound config set model gpt-4o-mini
hound config set model llama3.1 --config ./config/hound_agent.yml
```

If the value matches a provider preset, Hound Agent stores the provider along
with the provider's default model. Otherwise the value is stored as a model.
YAML updates are atomic and preserve other sections. API keys are never
printed.

## 7. Analysis Engine

| Mode | When used | Network |
|---|---|---|
| LLM | Provider/key/base URL available and not using `--offline` | Yes |
| Rule-based fallback | `--offline`, provider unavailable, or LLM failure | No |

The LLM uses an OpenAI-compatible endpoint. Select the provider via CLI, YAML,
or environment variables:

```sh
hound analyze ./ci-logs --provider groq --model llama-3.3-70b-versatile
hound list-providers
hound list-providers --json
```

If the LLM fails, the pipeline can fall back to deterministic rules and still
produce a report.

## 8. Analyze Options

| Option | Purpose |
|---|---|
| `<log-directory>` | Directory containing `.log` files; required |
| `--repo` | Git checkout for branch, commit, and changed files |
| `--source-context` | Opt-in: attach source around frames only for trusted logs |
| `--out` | Artifact root; default `hound-agent-output` |
| `--format` | `text`, `json`, or `markdown` |
| `--output` | File for formatted CLI output |
| `--offline` | Local rule-based analysis without network |
| `--source-class` | Trust profile: `trusted_branch`, `fork_pr`, or `local_artifact` (fail-closed) |
| `--config` | Optional YAML config |
| `--jobs` | Number of parallel workers (default 1 = sequential) |
| `--no-dedup` | Disable dedup persistence |
| `--no-redact` | Disable secret/PII redaction |
| `--provider` | Provider preset |
| `--model` | Model override |
| `--base-url` | Provider base URL override |
| `--api-key` | API key override; environment is safer |
| `--gh` | Create a GitHub issue |
| `--jira` | Create a Jira issue |
| `--gitlab` | Create a GitLab issue |
| `--slack-webhook` | Send a Slack alert |

## 9. YAML Configuration

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.2
  timeout: 120
  max_tokens: 2048
  max_retries: 3
  max_concurrency: 4
  routing: all             # all | exclude-kinds (skip LLM for kinds in skip_kinds)
  skip_kinds: [flaky]
  pricing:                 # USD per million tokens; used by --max-cost-usd and telemetry
    default:
      prompt_per_mtok: 0.30
      completion_per_mtok: 1.50

redact: true

trust:
  source_class: local_artifact   # trusted_branch | fork_pr | local_artifact

components:
  "app/cart/*": "cart"
  "src/handlers/*": "payments"

dedup:
  state_file: "/path/to/state.json"
  backend: "file"          # file | sqlite
  # backend: "sqlite"      # WAL store, atomic upsert, safe for parallel workers
  max_entries: 50000
  retention_days: 90
  reuse: true              # reuse stored root causes for recurring incidents (default on)
  reuse_after_occurrences: 3

github:
  repo: "owner/name"

jira:
  url: "https://jira.example.com"
  project: "QA"
  token: ""

gitlab:
  url: "https://gitlab.example.com"
  project: "group/repo"
  token: ""

slack:
  webhook_url: "https://hooks.slack.com/services/..."
```

Use `--config <file>` explicitly. Hound Agent never auto-loads config from the
analyzed repository because repository content is treated as untrusted input.
Store secrets in environment variables, not YAML.

## 10. Environment Variables

| Variable | Purpose |
|---|---|
| `TH_API_PROVIDER` | Generic provider |
| `TH_API_KEY` | Generic API key |
| `TH_BASE_URL` | Generic base URL |
| `TH_MODEL` | Generic model |
| `TH_TEMPERATURE` | Temperature |
| `TH_TIMEOUT` | Request timeout |
| `TH_MAX_TOKENS` | Maximum output tokens |
| `TH_MAX_RETRIES` | Maximum retries |
| `TH_NO_REDACT=1` | Disable redaction |
| `TH_SOURCE_CLASS` | Trust profile override (`trusted_branch`/`fork_pr`/`local_artifact`) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | OpenAI preset |
| `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_BASE_URL` | Gemini preset |
| `GROQ_API_KEY` / `GROQ_MODEL` / `GROQ_BASE_URL` | Groq preset |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | Ollama preset |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | DeepSeek preset |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_MODEL` / `AZURE_OPENAI_BASE_URL` | Azure preset |
| `CUSTOM_API_KEY` / `CUSTOM_MODEL` / `CUSTOM_BASE_URL` | Custom preset |
| `GH_TOKEN` / `GH_REPO` / `GH_API_BASE` | GitHub integration |
| `JIRA_URL` / `JIRA_PROJECT` / `JIRA_TOKEN` | Jira integration |
| `GITLAB_URL` / `GITLAB_PROJECT` / `GITLAB_TOKEN` | GitLab integration |
| `SLACK_WEBHOOK_URL` | Slack integration |

## 11. Legacy Batch

The legacy batch command remains available:

```sh
hound batch --logs ./ci-logs --out hound-agent-output --offline
hound batch --logs ./single.log --out hound-agent-output --offline
hound batch --logs ./ci-logs --out out --jobs 4 --max-llm-calls 40 --max-cost-usd 5.0
```

Batch uses shared dedup state and writes `summary-<batch-id>.json` and
`usage-<batch-id>.json` (LLM call counts, reused runs, budget-skipped runs,
total tokens, estimated cost). `--max-llm-calls` strictly limits LLM calls,
including under parallelism. `--max-cost-usd` limits the estimated cost and
may be exceeded slightly by requests already in flight (requires
`llm.pricing`); once the limit is reached, subsequent logs use rule-based
analysis and are marked `budget_skipped`. Old runs and summaries are kept as
history and never overwritten. For new automation, use
`hound analyze <log-directory>` because its output format and exit codes are
clearer.

## 12. Webhook Server

```sh
TH_SERVER_TOKEN='replace-with-a-strong-token' hound server \
  --host 127.0.0.1 --port 8123 --log-root ./trusted-logs
```

- `POST /analyze`: bearer auth required; JSON `{"log": "relative/path.log", "offline": false}`. The `repo` field may only be `"."` if the server was started with `--repo-root`.
- `GET /health`: process liveness.
- `GET /jobs/<id>`: bearer auth required; asynchronous job status.

The server uses a bearer token and only binds to loopback. If forwarded through
a reverse proxy, use TLS and never expose the token through logs.

## 13. Feedback

Engineer feedback for a run is stored in a store separate from dedup state,
recorded with audit metadata, and **never changes automated classification**.
Reviewed feedback can be exported as regression fixture candidates through an
explicit process.

```sh
# Record feedback for a stored run (--run-id required)
hound feedback record --out hound-agent-output --run-id run-a1b2c3d4e5f6 \
  --usefulness useful \
  --kind-correct correct --severity-correct incorrect \
  --owner-correct correct --duplicate-correct correct \
  --actual-kind test_failure --actual-severity high \
  --actual-owner "@qa-team" --actual-outcome root_cause_confirmed \
  --review-status reviewed --reviewer "engineer@example.com"

# Export all sanitized feedback
hound feedback export --out hound-agent-output

# Export only reviewed feedback in JSONL to a file
hound feedback export --out hound-agent-output --reviewed-only \
  --format jsonl --output reviewed.jsonl

# Export regression fixture candidates (manual manifest, not auto-mutating rules)
hound feedback export --out hound-agent-output --candidate-fixtures
```

The feedback store lives at `<out>/.hound-agent/feedback.sqlite3` (separate
from the dedup `state.sqlite3`/`state.json`). Each record stores `run_id`,
`report_sha256`, `dedup_key`, usefulness/kind/severity/owner/duplicate ratings,
`actual_*` outcome, `review_status`, `reviewer`, and `created_at`. Values
recognized as secrets are redacted before storage. Fixture candidate exports
mark `requires_manual_sanitized_artifact: true` — feedback never changes rules
or classifications automatically.

## 14. Trust Policy

Every analysis is assigned a **source class** that determines which
capabilities may run. The goal is fail-closed: untrusted sources must not
trigger source reading, enrichment, LLM, or delivery.

| Source class | Source context | Enrichment | LLM | Delivery |
|---|---|---|---|---|
| `trusted_branch` | Yes | Yes | Yes | Yes |
| `local_artifact` | Yes | Yes | Yes | Yes |
| `fork_pr` | No | No | No | No |

Select it explicitly with `--source-class <name>`, YAML
`trust.source_class: <name>`, or the `TH_SOURCE_CLASS` environment variable.
If not given, Hound detects it from the CI environment: GitHub
`pull_request`/`pull_request_target` events where the head repo differs from
the base repo, and cross-project GitLab merge requests
(`CI_MERGE_REQUEST_SOURCE_PROJECT_ID != CI_PROJECT_ID`) are classified as
`fork_pr`. Missing or incomplete PR events are also considered untrusted.

The `fork_pr` profile forces offline mode (`llm.require` is rejected),
redaction stays always on (`redact: false` is ignored), and forbidden
capabilities are blocked before any connector is invoked. Example:

```sh
# Fork PR: all optional capabilities are automatically disabled
hound analyze ./ci-logs --source-class fork_pr --offline

# Explicitly trusted
hound analyze ./ci-logs --source-class trusted_branch --repo . --source-context
```

The decision is recorded in the report's `meta.trust`: `source_class`,
`source_context`, `enrichment`, `llm`, `delivery`.

## 15. QA History

Hound stores test results across runs in a SQLite **history store** so flaky
and regression patterns are computed from data, not assumptions. The store is
separate from dedup state: `<out>/.hound-agent/history.sqlite3`.

```sh
# Import test evidence (JUnit/XML, JSON report, or runner log) into history
hound qa import ./artifacts --run-id ci-123 --commit <sha> --branch main \
  --environment "os=linux;python=3.11" --out hound-agent-output

# View aggregate statistics for one test
hound qa stats tests/test_checkout.py test_cart_total --out hound-agent-output --json

# Raw history per run/attempt
hound qa history tests/test_checkout.py test_cart_total --out hound-agent-output

# List tracked tests
hound qa tests --suite-prefix tests/ --out hound-agent-output

# Export sanitized history for CI cache / shared volume
hound qa export --out hound-agent-output --output history.json

# Import an exported manifest back into another store
hound qa import history.json --run-id seed --out /tmp/fresh-output
```

Model notes:

- The stable identity is the `(suite, leaf test)` pair; runner prefixes
  (`path::test`, `class.method`, etc.) are stripped to the leaf so the same
  test is tracked consistently across runners (pytest, JUnit, Jest/Vitest, Go,
  RSpec, Cargo, dotnet).
- One row per `(suite, test, run_id, attempt)`; JUnit retries/flaky results
  automatically become `failed(1)` + `passed(2)` rows.
- Raw logs are never stored; rows only reference `run_id` / `evidence_id`.
- Without enough data, `stats` reports `failure_rate: null` and
  `insufficient_history: true` — never guess from a single sample.
- Retention prunes whole old rows; aggregates are recomputed from the
  remaining rows so they are never corrupted:
  `hound qa import <path> --retention-days 90 --out <out>`.

## 16. Brief Architecture

```text
command / piped stdin
        |
        v
collector -> redacted .log + metadata
        |
        v
shared service -> pipeline -> parse -> analyze -> triage -> output
        ^
        |
CLI / TUI / server
```

`service.analyze_log()` is the adapter-facing entry point. The service
delegates to one core `pipeline.analyze()`, so parsing, redaction, AI analysis,
triage, dedup, and report generation are never duplicated.

## 17. End-to-End Example

```sh
# Install
uv sync --extra dev

# Capture a command; exit follows the executed command
uv run hound log --name tests -- pytest -q

# Open the captured logs in the TUI
uv run hound

# Or analyze a directory headlessly
uv run hound analyze .hound-agent/logs --offline --format json \
  --output hound-agent-result.json

# View one of the stored runs
uv run hound report <run-id> --format text
```

## 18. Testing and Build

```sh
uv run pytest
uv run python -m py_compile hound_agent/cli.py hound_agent/tui.py \
  hound_agent/service.py hound_agent/collector.py hound_agent/formatters.py
uv build
```

Baseline when this document was last updated: `421 passed, 5 skipped` on
Windows. The skipped tests verify POSIX permission bits specifically. Tests
never make live API calls.

## 19. Other Documentation

- `README.md`: summary and quick start.
- `docs/prd.md`: product requirements and scope.
- `docs/architecture.md`: module structure and data flow.
- `AGENTS.md`: development workflow, definition of done, and verification gates.
