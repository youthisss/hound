# Hound Agent

Offline-first investigator for CI/CD failures. Hound analyzes builds, tests, CI jobs, and deployments; correlates trusted run/release context, triages incidents, and drafts actionable tickets without mutating infrastructure.

## Install

```sh
uv sync --extra dev
```

## Usage

```sh
# interactive UI; only opens automatically in a TTY
hound

# analyze every .log file directly inside one directory
hound analyze ./ci-logs
hound analyze ./ci-logs --format text
hound analyze ./ci-logs --format json
hound analyze ./ci-logs --format json --output result.json

# JUnit XML, SARIF, and JSON test reports are supported alongside .log files
hound analyze ./artifacts --repo . --offline

# local rule-based analysis; no provider or network integration is used
hound analyze ./ci-logs --offline

# capture command output as .tracehound/logs/<timestamp>-<name>.log
hound log -- npm test
hound log --name unit-tests -- pytest -q

# capture piped logs
kubectl logs deployment/api | hound log --name api

# inspect a failed Kubernetes rollout or Terraform apply (analysis only)
kubectl rollout status deployment/api 2>&1 | hound log --name api-rollout --analyze --offline
terraform apply -auto-approve 2>&1 | hound log --name terraform-apply --analyze --offline

# explicit, bounded, read-only Kubernetes/Helm evidence collection
hound analyze ./deploy-logs --repo . --enrich --context deployment-context.json --offline

# capture, then analyze through the same engine used by CLI and TUI
hound log --analyze --offline -- npm test

# inspect one stored run (copy the opaque ID from list-runs)
hound list-runs --out tracehound_output
hound report run-a1b2c3d4e5f6

# initialize project configuration, list runs, or remove generated output
hound init
hound list-runs --out tracehound_output
hound clean --out tracehound_output --yes

# persist a provider preset or exact model in .tracehound.yml
hound config set model gemini
hound config set model gpt-4o-mini

# with an OpenAI-compatible LLM
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://...          # optional override
export OPENAI_MODEL=gpt-4o-mini             # optional
hound analyze <log-directory> --repo <repo-dir> --out <out-dir>

# with another provider (env-based)
export TH_API_PROVIDER=gemini
export GEMINI_API_KEY=...
export GEMINI_MODEL=gemini-2.0-flash
hound analyze <log-directory> --out <out-dir>

# provider can also be chosen per-run via CLI flags (highest priority)
hound analyze <log-directory> --out <out-dir> \
    --provider groq --model llama-3.3-70b-versatile

# list available provider presets
hound list-providers

# local model via Ollama (no API key needed)
export TH_API_PROVIDER=ollama
export OLLAMA_MODEL=llama3.1
hound analyze <log-directory> --out <out-dir>

# file the ticket as a GitHub issue (optional; needs GH_TOKEN + GH_REPO)
export GH_TOKEN=...
export GH_REPO=owner/name
hound analyze <log-directory> --gh

# ... or Jira / GitLab / Slack
export JIRA_URL=https://jira.example.com JIRA_PROJECT=QA JIRA_TOKEN=...
hound analyze <log-directory> --jira
export GITLAB_URL=https://gitlab.example.com GITLAB_PROJECT=group/repo GITLAB_TOKEN=...
hound analyze <log-directory> --gitlab
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
hound analyze <log-directory> --slack-webhook

# analyze every *.log in a directory (shared dedup state, unique summary file at out/)
uv run hound batch --logs <dir-of-logs> --out <out-dir> --offline

# interactive terminal UI (press b or use Browse folder to select a log directory)
uv run hound tui --logs <dir-of-logs> --out <out-dir> --offline

# HTTP receiver requires an explicit token and trusted filesystem roots
export TH_SERVER_TOKEN=change-me
uv run hound server --host 127.0.0.1 --port 8123 --log-root ./ci-logs --out ./server-runs
```

Secrets and PII (API keys, JWTs, passwords, connection strings, emails, IPs)
are redacted from log text by default before the LLM and before anything is
written to disk. Disable with `--no-redact` (or `redact: false` in YAML).
Oversized logs are sliced head+tail around failure markers instead of a blind
tail read. When trusted logs are analyzed with `--repo` and explicit
`--source-context`, ±2 lines of source are attached to each
stacktrace frame so the LLM sees the failing code.

Outputs into `--out` (default `tracehound_output/`): `report.json`, `report.md`, `ticket.md`, and a dedup state file at `<out>/.tracehound/state.json`. Batch mode writes opaque, unique run directories plus `summary-<batch-id>.json`, so repeated or concurrent batches do not overwrite each other.

Recurring incidents and flaky tests are distinct. A recurring incident is a matching fingerprint seen at least three times (configurable); a flaky test requires a failed test with explicit retry/pass evidence. Deployment fingerprints include environment and release identity so independent releases are not deduplicated together.

If no API key is set, the LLM call fails, or `--offline` is passed, analysis falls back to deterministic rule-based RCA. Explicit tracker delivery failures return exit code `3`; duplicates are never re-filed.

### CD failure analysis

Deployment logs are classified as stage `deploy`. The local detector recognizes Kubernetes rollout/readiness, OOM, crash loops, liveness/readiness probes, scheduling/quota, registry authentication, configuration, network, image pull, Helm release/rollback, Terraform apply, migration, and permission failures. `--enrich` only executes bounded read-only `kubectl`/`helm` inspection commands when an explicit `--context` supplies the deployment identity; Hound never deploys, retries, rolls back, or mutates infrastructure.

### CI/CD context

Hound loads operator-approved run/deployment context only through `--context context.json`. GitHub Actions context is discovered automatically from `GITHUB_*` and its event payload, including run, job, workflow, PR, base/head SHA, and run URL. PR changed files are computed against `base_sha...head_sha`; matching `CODEOWNERS` are included in reports and tickets.

The RCA schema includes a primary failure plus downstream `failure.events`, so cleanup or cancellation errors do not overwrite the root failure. Deployment context records platform, environment, namespace, target, release revision, artifact, outcome, and recovery.

### Automation and exit codes

`hound analyze` writes formatted results to stdout unless `--output` is
provided. JSON mode emits one valid JSON object without progress or debug text.
Warnings and errors go to stderr.

| Code | Meaning |
|------|---------|
| `0` | Analysis completed; no recognized CI/CD/build/test failure found |
| `1` | Analysis completed; at least one CI/CD/build/test failure found |
| `2` | Invalid arguments, path, directory contents, or configuration |
| `3` | Internal analysis/output error, or an explicitly requested ticket/alert delivery failed |

Example CI step:

```sh
hound analyze ./artifacts/logs --offline --format json --output hound-agent.json
code=$?
if [ "$code" -eq 1 ]; then
  echo "Hound Agent found a CI failure"
elif [ "$code" -ge 2 ]; then
  exit "$code"
fi
```

Without arguments, Hound Agent opens TUI only when stdin and stdout are TTYs.
In pipes or CI, use an explicit command such as `hound analyze ./ci-logs`.

### Log collection

`hound log -- <command>` runs the command directly without a shell, tees
combined stdout/stderr to the terminal, and stores a redacted `.log` plus JSON
metadata sidecar under `.tracehound/logs`. Metadata includes source, command,
child exit code, timestamp, duration, working directory, and available Git
context. Child exit code is preserved so wrappers and CI retain command
semantics.

`hound log --name <name>` reads stdin only when stdin is piped. Running it
without a command or pipe returns exit `2` with an actionable message. Use
`--output file.log` for an explicit path, or `--output <existing-directory>` to
keep generated timestamped names. `--analyze` runs the captured file through
the shared analysis service; capture remains the default to avoid implicit LLM
calls.

## Optional config (YAML)

```yaml
llm:
  provider: gemini          # openai | anthropic | gemini | groq | ollama | deepseek | azure | custom
  model: gemini-2.0-flash
  temperature: 0.2
  timeout: 120
  max_tokens: 2048
  max_retries: 3            # LLM retries with exponential backoff (429/5xx)
redact: true                # secret/PII scrubbing (default on)
components:
  "app/cart/*": "cart"
  "src/handlers/*": "payments"
dedup:
  state_file: "/path/to/state.json"   # default: <out>/.tracehound/state.json
  backend: "file"                     # file only; distributed HTTP store disabled pending CAS support
policy:
  recurrence_threshold: 3
  severity_overrides:
    production:
      deployment_failed: critical
github:
  repo: "owner/name"                   # optional; else use GH_REPO env
jira:
  url: "https://jira.example.com"
  project: "QA"
  token: ""                            # else JIRA_TOKEN env
  email: ""                            # JIRA_EMAIL; enables Jira Cloud Basic auth
gitlab:
  url: "https://gitlab.example.com"
  project: "group/repo"
  token: ""                            # else GITLAB_TOKEN env
slack:
  webhook_url: "https://hooks.slack.com/services/..."   # else SLACK_WEBHOOK_URL env
```

Pass with `--config <file>`. Configuration is never auto-loaded from an
analyzed repository because repository contents are untrusted.

## LLM providers

Any OpenAI-compatible endpoint works. Pick a provider preset, or configure
a custom one:

| Provider  | Env vars                                    | Default model        |
|-----------|---------------------------------------------|----------------------|
| openai    | `OPENAI_API_KEY`, `OPENAI_MODEL`            | gpt-4o-mini          |
| anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL` | claude-sonnet-4-20250514 via an OpenAI-compatible proxy |
| gemini    | `GEMINI_API_KEY`, `GEMINI_MODEL`            | gemini-2.0-flash     |
| groq      | `GROQ_API_KEY`, `GROQ_MODEL`                | llama-3.3-70b-versatile |
| ollama    | `OLLAMA_MODEL` (no key)                     | llama3.1             |
| deepseek  | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`        | deepseek-chat        |
| azure     | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_API_VERSION` | required |
| custom    | `CUSTOM_API_KEY`, `CUSTOM_MODEL`            | required            |

Selection order: `--provider/--model/--base-url/--api-key` CLI flags
> YAML `llm:` block > `TH_API_PROVIDER`/`TH_API_KEY`/`TH_BASE_URL`/`TH_MODEL`
> provider-specific env vars > legacy `OPENAI_*` fallback.

Legacy `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL` keep working
unchanged (they map to the `openai` preset). `TH_*` vars exist as a generic
override that works with every provider.

## Deployment

- **Docker**: `docker build -t hound-agent . && docker run --rm -v "$PWD/logs:/logs:ro" hound-agent analyze /logs --offline`
- **GitHub Action**: `action.yml` is a Docker action for deterministic offline analysis. It does not inject GitHub credentials or file tickets.
- **GitHub Action outputs**: `report`, `ticket`, `severity`, `kind`, `stage`, and `dedup_key`. The default output directory is `${{ github.workspace }}/tracehound_output`, so it can be uploaded by a later artifact step.

## Tests

```sh
uv run pytest
```

No live API calls in tests; all fixtures are local.

## Docs

See `PRD.md`, `WORKFLOW.md`, `TODO.md`, `ARCHITECTURE.md`.
