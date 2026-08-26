# Hound Agent

Offline-first investigator for CI/CD failures. Hound analyzes builds, tests,
CI jobs, and deployments; correlates run/release context; triages incidents;
and drafts actionable tickets — without mutating infrastructure.

## Install

```sh
uv sync --extra dev
```

## Quick start

```sh
# Open interactive TUI (requires a TTY)
hound

# Analyze all artifacts in a directory (offline, no API key needed)
hound analyze ./ci-logs --offline

# Capture a command's output and analyze it
hound log --analyze --offline -- pytest -q
```

## End-to-end demo

Run the deterministic offline demo to verify classification, tracing, redaction,
deduplication, and generated reports through the public CLI:

```sh
uv run python demo_project/run_demo.py --profile smoke
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

The scale profile generates its dataset at runtime, so thousands of sample logs
do not need to be committed. See [`demo_project/README.md`](demo_project/README.md).

## Commands

### `hound analyze`

Analyzes every `.log`, `.xml` (JUnit), `.sarif`, and test-report `.json` file
found directly inside a directory, then writes `report.json`, `report.md`, and
`ticket.md` per run.

```sh
hound analyze ./ci-logs
hound analyze ./ci-logs --offline
hound analyze ./ci-logs --repo . --source-context --offline
hound analyze ./artifacts --format json --output result.json
hound analyze ./ci-logs --jobs 4 --out hound-agent-output
```

**Structured artifact support** — JUnit XML, SARIF, and JSON test reports are
parsed directly without relying on log heuristics.

**Source context** — with `--repo` and `--source-context`, ±2 lines are
attached to each recognized stack frame (Python, C/C++, Go, Rust, Java,
TypeScript) and deployment config reference (`.yaml`, `.yml`, `.tf`, `.tpl`).
Disabled by default because log frames are untrusted.

**CD failure analysis** — the local detector recognizes Kubernetes
rollout/readiness, OOM, crash loops, liveness/readiness probes,
scheduling/quota, registry auth, config-missing, network, image-pull, Helm
release/rollback, Terraform apply, migration, and permission failures. When
tool output cites a repo-contained config line, `--source-context` attaches a
bounded snippet. `--enrich` executes bounded read-only `kubectl`/`helm`
inspection when `--context` supplies deployment identity. Hound never deploys,
retries, or rolls back infrastructure.

**Offline parser coverage** — deterministic parsing recognizes failed tests
from pytest, Jest/Vitest, Go test, RSpec, Cargo, and dotnet output; Java
runtime, V8/JavaScript, and C# stack frames; dependency-resolution conflicts,
disk-full errors, TLS certificate failures, and API rate limits. With `--repo`,
the latest commit subjects for up to three changed files matching stack frames
are included as redacted RCA evidence.

**Parallel analysis** — `--jobs N` runs N workers in parallel. Run dirs and
summary ordering stay deterministic by input order.

**Flaky test detection** — a log is labeled `flaky` only with explicit
retry-then-pass evidence: the same pytest nodeid (`RERUN` then `PASSED`), Jest
test (`✕`/`●` then `✓`), Go test run under `-count=N`, or JUnit
`flakyFailure`/`rerunFailure`. Failure-then-pass without a runner retry signal
remains `test_failure`.

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Completed — no recognized CI/CD/build/test failure found |
| `1` | Completed — at least one failure found |
| `2` | Invalid arguments, path, directory contents, or configuration |
| `3` | Internal analysis/output error, or an explicitly requested ticket/alert delivery failed |

Example CI step:

```sh
hound analyze ./artifacts/logs --offline --format json --output hound-agent.json
code=$?
if [ "$code" -eq 1 ]; then
  echo "Hound found a CI failure"
elif [ "$code" -ge 2 ]; then
  exit "$code"
fi
```

### `hound log`

Captures a command's combined stdout/stderr, tees it to the terminal, and
stores a redacted `.log` plus JSON metadata sidecar in `.hound-agent/logs/`.

```sh
# Run a command directly (no shell)
hound log -- npm test
hound log --name unit-tests -- pytest -q

# Capture piped input
kubectl logs deployment/api | hound log --name api
terraform apply -auto-approve 2>&1 | hound log --name tf-apply

# Capture and immediately analyze
hound log --analyze --offline -- npm test

# Explicit output path
hound log --output ./captures/build.log -- make build
```

The adjacent `<log>.json` sidecar is auto-loaded during analysis when no
explicit `--context` is supplied. Child exit code is preserved.

### `hound tui`

Interactive terminal UI — browse, filter, and analyze logs; view
overview/report/ticket/raw-log panes side by side.

```sh
hound tui --logs ./ci-logs --out hound-agent-output --offline
```

Press `A` inside the TUI to analyze every visible artifact sequentially.

**Keyboard shortcuts**

| Key | Action |
|-----|--------|
| `a` | Analyze selected / retry |
| `A` | Analyze all visible artifacts |
| `b` | Browse folder |
| `r` | Refresh log list and recent runs |
| `s` | Open Settings |
| `o` | Toggle offline mode |
| `?` | Help overlay |
| `q` | Quit |

### `hound batch`

Batch-analyzes a directory with shared dedup state and per-batch usage telemetry.

```sh
hound batch --logs ./ci-logs --out out --offline
hound batch --logs ./ci-logs --out out --offline --jobs 4
hound batch --logs ./ci-logs --out out --max-llm-calls 40 --max-cost-usd 5.0
```

Writes `summary-<batch-id>.json` (per-log results) and
`usage-<batch-id>.json` (LLM calls, reused runs, budget-skipped runs, token
totals, estimated cost). Repeated batches never overwrite prior results.

### `hound server`

HTTP webhook receiver. All paths require a bearer token.

```sh
export TH_SERVER_TOKEN=change-me
hound server --host 127.0.0.1 --port 8123 --log-root ./ci-logs --out ./server-runs \
  --workers 4 --max-queue 64 --rate-limit 60 --job-ttl 3600
```

- `POST /analyze` — `{"log": "relative/path.log", "offline": false}`
- `GET /health` — liveness check
- `GET /ready` — local storage/readiness check
- `GET /jobs/<id>` — async job status
- `GET /stats` — queued/running/completed/failed counts
- `GET /stats` also includes persisted engine and fallback-reason counts

### Other commands

```sh
# List available LLM provider presets
hound list-providers

# Inspect one stored run
hound list-runs --out hound-agent-output
hound report <run-id>
hound report <run-id> --format json
hound report <run-id> --format markdown --output report.md

# Initialize a project config template
hound init

# Remove generated output (requires --yes)
hound clean --out hound-agent-output --yes

# Persist provider/model to .hound-agent.yml
hound config set model gemini
hound config set model gpt-4o-mini
```

## LLM providers

Any OpenAI-compatible endpoint works. Select a provider preset or configure a
custom one.

| Provider  | Key env var(s)                                        | Default model              |
|-----------|-------------------------------------------------------|----------------------------|
| openai    | `OPENAI_API_KEY`                                      | gpt-4o-mini                |
| anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`             | claude-sonnet-4-20250514   |
| gemini    | `GEMINI_API_KEY`                                      | gemini-3.7-flash           |
| groq      | `GROQ_API_KEY`                                        | llama-3.3-70b-versatile    |
| ollama    | `OLLAMA_MODEL` (no key)                               | llama3.1                   |
| deepseek  | `DEEPSEEK_API_KEY`                                    | deepseek-chat              |
| azure     | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_API_VERSION` | required |
| 9router   | `NINE_ROUTER_API_KEY`, `NINE_ROUTER_MODEL`, `NINE_ROUTER_BASE_URL` | ag/gemini-3.7-flash-low |
| custom    | `CUSTOM_API_KEY`, `CUSTOM_MODEL`, `CUSTOM_BASE_URL`   | required                   |

**Selection order:** `--provider/--model/--base-url/--api-key` CLI flags
> YAML `llm:` block > `TH_API_PROVIDER`/`TH_API_KEY`/`TH_BASE_URL`/`TH_MODEL`
> provider-specific env vars > legacy `OPENAI_*` fallback.

When no API key is set, `--offline` is passed, or the LLM call fails, analysis
falls back to deterministic rule-based RCA automatically.
Reports expose this explicitly in `meta.llm.status` and
`meta.llm.fallback_reason`. Use `--require-llm` (or `TH_REQUIRE_LLM=1`) in
production canaries when fallback must be treated as a failed analysis.

For 9Router, set `NINE_ROUTER_BASE_URL` to the reachable gateway URL. The
built-in loopback default is intended for local use; hosted CI requires a
network-accessible HTTPS endpoint and the `NINE_ROUTER_API_KEY` secret.

## Cost control

Repeated failures should not repeatedly spend tokens.

- **Dedup-first reuse (default on).** A root-cause snapshot is stored with each
  dedup entry. Once an incident has been analyzed `reuse_after_occurrences` times
  (default 3), later occurrences reuse the stored snapshot instead of calling the
  LLM. Reused runs are tagged `meta.reused`/`meta.reused_from_key`, report zero
  token usage, and still count toward recurrence. Disable with `dedup.reuse: false`
  or `--no-dedup`.
- **Kind routing.** `llm.routing: exclude-kinds` with `llm.skip_kinds: [flaky]`
  pins noisy, rule-resolvable kinds to the fallback so they never spend tokens.
- **Batch budget guardrails.** `--max-llm-calls N` strictly caps LLM calls,
  including parallel batches; `--max-cost-usd X` limits estimated spend
  (requires `llm.pricing` and may cross the threshold by calls already in flight). Once a limit
  is hit, remaining logs run rule-only and are marked `budget_skipped`.

```sh
hound batch --logs ci-logs --out out --max-llm-calls 40 --max-cost-usd 5.0
```

## Request correlation

Hound extracts `request_id`, `trace_id`, `session_id`, `user_id`, distinct
users (up to 10), and HTTP method/path from the bounded raw log window into
`context.request` (RCA schema v2.0; persisted v1.4 reports remain readable). These fields are:

- Redacted before the LLM prompt and before anything is written to disk.
- Rendered in reports and tickets only when present.
- Excluded from dedup fingerprints — the same failure from different users or
  requests remains one incident.

See [docs/log-format.md](docs/log-format.md) for the recommended log field
contract.

## Security and privacy

Secrets and PII (API keys, JWTs, passwords, connection strings, emails, IPs)
are redacted from log text by default before the LLM and before anything is
written to disk. Disable with `--no-redact` or `redact: false` in YAML.

GitHub Actions context is discovered automatically from `GITHUB_*` env vars
and their event payload. PR changed files are computed against
`base_sha...head_sha`; matching `CODEOWNERS` are included in reports and
tickets. Repository-local config is never auto-loaded because repository
contents are untrusted input.

## Configuration (YAML)

```yaml
llm:
  provider: gemini          # openai | anthropic | gemini | groq | ollama | deepseek | azure | custom
  model: gemini-3.7-flash
  temperature: 0.2
  timeout: 120
  max_tokens: 2048
  max_retries: 3            # exponential backoff on 429/5xx
  max_concurrency: 4        # max parallel LLM calls per process (env: TH_MAX_CONCURRENCY)
  routing: all              # all | exclude-kinds
  skip_kinds: [flaky]       # analyzed rule-only when routing: exclude-kinds
  pricing:                  # USD per million tokens; used by --max-cost-usd and usage telemetry
    default:
      prompt_per_mtok: 0.30
      completion_per_mtok: 1.50

redact: true                # secret/PII scrubbing (default on)

components:
  "app/cart/*": "cart"
  "src/handlers/*": "payments"

dedup:
  state_file: "/path/to/state.json"   # default: <out>/.hound-agent/state.json
  backend: "file"                     # file | sqlite
  # backend: "sqlite"                 # WAL store, atomic upserts, safe for concurrent workers
  # path: "/path/to/state.sqlite3"    # explicit sqlite path
  max_entries: 50000                  # prune old filed entries beyond this count
  retention_days: 90                  # drop filed entries older than this (sqlite only)
  reuse: true
  reuse_after_occurrences: 3

policy:
  recurrence_threshold: 3
  severity_overrides:
    production:
      deployment_failed: critical

github:
  repo: "owner/name"                  # or use GH_REPO env
jira:
  url: "https://jira.example.com"
  project: "QA"
  token: ""                           # or JIRA_TOKEN env
gitlab:
  url: "https://gitlab.example.com"
  project: "group/repo"
  token: ""                           # or GITLAB_TOKEN env
slack:
  webhook_url: "https://hooks.slack.com/services/..."  # or SLACK_WEBHOOK_URL env
```

Pass with `--config <file>`. Configuration is never auto-loaded from an
analyzed repository.

## Deployment

- **Docker:** `docker build -t hound . && docker run --rm -v "$PWD/logs:/logs:ro" hound analyze /logs --offline`
- **GitHub Action:** `action.yml` is a Docker action for deterministic offline
  analysis. Does not inject credentials or file tickets. Inputs `log`, `repo`,
  and `out` must resolve inside `${{ github.workspace }}`.
  **Outputs:** `report`, `ticket`, `severity`, `kind`, `stage`, `dedup_key`.
  Default output dir: `${{ github.workspace }}/hound-agent-output`.

## Tests

```sh
uv run pytest
```

No live API calls — all fixtures are local. Current baseline: **421 passed, 5 skipped**.

## Docs

| File | Content |
|------|---------|
| [docs/architecture.md](docs/architecture.md) | Module map, data flow, RCA schema, contracts |
| [docs/prd.md](docs/prd.md) | Functional and non-functional requirements |
| [docs/usage.md](docs/usage.md) | Full CLI, TUI, and integration manual (Bahasa Indonesia) |
| [docs/workflow.md](docs/workflow.md) | Contribution workflow and verification gate |
| [docs/log-format.md](docs/log-format.md) | Correlated error log field specification |
