# Hound Production Maturity Plan

## 1. Objective

Make Hound reliable enough for a public, installable release and for
bounded production use as a CLI, GitHub Action, and local HTTP service.

This plan covers the work that remains after distribution/install and CLI naming:

- operational observability
- configuration and error contracts
- automated testing and CI gates
- dependency and supply-chain security
- server hardening and operational documentation
- GitHub Action maturity
- release governance and support documentation
- performance, persistence, and recovery evidence

The target is not to add complexity for its own sake. Hound should remain
offline-first, read-only, privacy-preserving, and useful without an LLM key.

## 2. Production Definition

Hound is production-ready for a release only when all of these are true:

1. A clean supported machine can install the package and run `hound --version`,
   `hound doctor`, and an offline analysis.
2. The CLI has stable exit codes, actionable errors, documented output formats,
   and no accidental secret disclosure.
3. Pull requests cannot merge while required quality gates are red.
4. The supported Python and operating-system matrix is tested automatically.
5. The server has bounded input, authentication, queue limits, readiness checks,
   graceful shutdown behavior, safe logs, and deployment guidance.
6. A release is traceable from source commit to package, GitHub Release, Action
   tag, checksums, and provenance.
7. Persistent state has schema versions, migration tests, retention behavior, and
   a documented recovery procedure.
8. The GitHub Action has versioned usage documentation and a tested upgrade path.
9. No telemetry, LLM call, delivery integration, or infrastructure mutation is
   enabled implicitly.

## 3. Evidence-Based Current State

The following gaps are based on the current repository surface:

- `README.md:91` still contains the placeholder `your-org` repository URL.
- The README presents `uv sync --extra dev` as installation even though it is a
  contributor/development workflow.
- There is no `CHANGELOG.md` or equivalent release history.
- `docs/workflow.md:7` exposes the local WSL path `/mnt/d/project/hound/`.
- `pyproject.toml:7` and `src/hound/__init__.py:1` both carry version data.
- Runtime dependencies such as `openai` and `gitpython` have no direct version
  bounds in `pyproject.toml`, although `uv.lock` is locked.
- `pyproject.toml:55` excludes critical modules including server, pipeline,
  collector, TUI, and parts of LLM analysis from mypy.
- The codebase has no logging framework; server diagnostics use stderr writes in
   `src/hound/server.py:322`, `:450`, and `:456`.
- `.github/workflows/ci.yml:3-5` currently uses only `workflow_dispatch`.
- The release workflow does not yet publish through a complete build-once,
  environment-protected package release process.
- `action.yml:7-48` exposes only a small offline input surface.
- `src/hound/server.py:268` keeps rate-limit counters in memory.
- Server TLS is intentionally outside the process, but reverse-proxy guidance is
  not yet documented as a production deployment contract.
- The repository has broad unit/integration coverage, but no formal pytest markers
  for selecting unit, integration, and end-to-end suites.

These findings are not all release blockers. The priority and dependency order
below prevents low-value hardening from delaying the core release path.

## 4. Scope and Non-Goals

### In Scope

- Production contracts and release gates for CLI, Action, and server surfaces.
- Documentation needed by users, contributors, and operators.
- Logging, configuration diagnostics, persistence recovery, and test selection.
- Security boundaries and dependency update policy.
- Reproducible package and Action releases.

### Out of Scope

- Automatic deployment, rollback, or infrastructure mutation by Hound.
- Mandatory external telemetry or hosted SaaS components.
- Turning the local server into a public internet-facing application.
- Adding a database service when SQLite plus documented deployment constraints is
  sufficient.
- Standalone native binaries unless the distribution plan produces evidence that
  Python-based installation is a material adoption barrier.

## 5. Invariants

Every implementation step must preserve these properties:

1. `hound analyze --offline` works without network access or credentials.
2. Redaction remains enabled by default and applies before persistence or delivery.
3. LLM failure falls back safely unless an explicit strict mode is requested.
4. External delivery remains opt-in and source trust policy remains fail-closed.
5. Machine-readable stdout is never polluted by diagnostic logs.
6. Logs, reports, exceptions, and test fixtures contain no real credentials or
   customer data.
7. Existing Docker and GitHub Action workflows remain usable unless a versioned
   breaking change is explicitly documented.
8. No release work is performed from the parent Git repository rooted at
   `D:\Project`; use the dedicated Hound checkout from the distribution
   plan.
9. Quality gates are fixed by diagnosing failures, never by weakening assertions
   or marking failures as successful.

## 6. Dependency Graph

```text
P0  Repository and baseline safety
 |\
 | +--> P1  Public documentation and support contract
 | +--> P2  CLI/config/error contract
 |       |
 |       +--> P3  Observability and server operations
 |       +--> P4  Test taxonomy and automatic CI
 |       +--> P5  Security and dependency policy
 |               |
 |               +--> P6  GitHub Action maturity
 |               +--> P7  Release governance and pilot gate
 |                       |
 |                       +--> P8  Performance and scale evidence
 |                       +--> P9  Optional production extensions
```

P1 and P2 can proceed in parallel after P0. P3, P4, and P5 can proceed in
parallel after the contracts are agreed. P6 should follow the CLI/config contract.
P7 must consume the outputs of all required gates. P8 and P9 are not required for
the first stable package unless their acceptance criteria become applicable.

## 7. Milestones

### P0 - Repository and Baseline Safety

**Severity:** Blocking prerequisite

**Purpose:** Prevent unrelated projects, dirty parent-repository state, or
unreproducible local assumptions from contaminating production work.

**Context brief:** `git rev-parse --show-toplevel` previously resolved to
`D:\Project`, while the Hound directory was nested inside it. The Hound
remote was a secondary remote. This caused unrelated sibling paths to enter the
Hound GitHub repository. Distribution work already calls for a dedicated clone.

**Tasks:**

1. Use a fresh dedicated clone of `https://github.com/youthisss/hound.git`
   outside the `D:\Project` parent repository.
2. Confirm the new checkout's Git root and `origin` before staging anything.
3. Inventory and intentionally migrate only Hound changes from the old
   nested checkout.
4. Keep the old checkout and the parent repository untouched until migration is
   reviewed and verified.
5. Add a contributor/release checklist that starts with `git rev-parse
   --show-toplevel` and `git remote -v`.

**Verification:**

```powershell
git rev-parse --show-toplevel
git remote -v
git status --short
```

**Exit criteria:** The top-level path is the dedicated Hound checkout, `origin`
points only to `youthisss/hound`, and no sibling project can be included by
an ordinary `git add .`.

**Rollback:** Remove only the new clone if migration validation fails. Do not use
`git reset --hard`, `git checkout --`, or deletion against the old parent tree.

---

### P1 - Public Documentation and Support Contract

**Severity:** High

**Purpose:** Make the product understandable and supportable before inviting
external users.

**Tasks:**

1. Complete the separate distribution/install plan and replace the placeholder
   repository URL in all public documentation.
2. Separate user installation, contributor setup, Docker usage, GitHub Action
   usage, and server deployment into distinct sections.
3. Add `CHANGELOG.md` using Keep a Changelog conventions. Start with the current
   version history and explicitly mark breaking schema and CLI changes.
4. Add `CONTRIBUTING.md` with prerequisites, setup, test commands, coding rules,
   commit expectations, fixture privacy rules, and pull-request checks.
5. Add `SECURITY.md` with supported versions, vulnerability reporting, secret
   handling, and the fact that Hound is read-only.
6. Remove local machine paths, private workflow assumptions, and internal agent
   instructions from public documentation. Replace them with repository-relative
   examples.
7. Add dedicated docs for `hound insights`, `hound gate`, CLI exit codes, server
   deployment, Action upgrades, and SQLite state recovery.
8. Add a support matrix for Python versions, Windows, Linux, macOS, Docker, and
   the supported Action runner.
9. Keep README examples executable from a clean temporary directory.

**Verification:**

```powershell
rg "your-org|/mnt/d/project|D:\\Project" README.md docs CONTRIBUTING.md SECURITY.md
```

Expected: no private or placeholder path remains in public documentation.

**Exit criteria:** A new user, contributor, and operator each have a documented
first-success path and know where to report security issues or compatibility
problems.

**Rollback:** Documentation-only changes can be reverted independently. Do not
remove old examples until their replacements have been tested.

---

### P2 - CLI, Configuration, and Error Contract

**Severity:** High

**Purpose:** Establish a stable, predictable user-facing contract before package
publication and command renaming.

**Context brief:** The CLI already has useful exit codes and redaction defaults,
but several names are implementation-oriented and some errors expose raw
exceptions. Configuration validation is mostly manual and unknown keys are
ignored. The separate naming plan recommends `insights`, `console`, `serve`,
`providers`, and `runs` as public names.

**Tasks:**

1. Finalize canonical command names before the first stable PyPI release:
   - `hound insights` for historical test intelligence
   - `hound gate` for policy enforcement
   - `hound console` for the interactive interface
   - `hound serve` for the HTTP service
   - `hound providers` and `hound runs` for list views
2. Keep `hound` as the default interactive entrypoint when attached to a TTY.
   In non-TTY environments, print an actionable non-interactive error and point
   to the analysis command.
3. Keep `analyze`, `log`, and the GitHub Action's existing `log` input as
   compatibility paths until their external usage is assessed.
4. Use explicit public options such as `--output-dir`, `--repo-dir`,
   `--test-runner`, `--baseline-ref`, `--candidate-ref`, `--history-db`, and
   `--window-days`.
5. Keep precise and familiar options such as `--offline`, `--format`, `--output`,
   `--config`, `--provider`, `--model`, `--policy`, `--coverage`, and `--sarif`.
6. Make dangerous behavior explicit: expose `--allow-unredacted`; retain
   `--no-redact` only as a hidden compatibility alias and emit a warning when it
   is used.
7. Introduce one version source of truth. Prefer Hatch dynamic version metadata
   sourced from `src/hound/__init__.py`, or document and enforce the chosen
   alternative. Add a test that package metadata and `hound --version` agree.
8. Add a formal configuration schema artifact or an equivalent exhaustive schema
   validator. It must document all supported fields, defaults, types, ranges, and
   secret-bearing fields.
9. Detect unknown configuration keys. Default behavior should warn with the exact
   path and suggested key; a strict mode must fail for CI and release validation.
10. Add `hound config validate` or an equivalent validation path that does not call
    an LLM and does not expose secret values.
11. Standardize errors into categories: usage, input, configuration, provider,
    persistence, delivery, and internal failure. Each user-facing error should
    include a next action where safe.
12. Preserve machine-readable JSON contracts and ensure diagnostics go to stderr.
13. Keep `HOUND_*` as the canonical environment-variable namespace and retain
    `TH_*` only as deprecated compatibility aliases without logging secret values.

**Verification:**

```powershell
hound --help
hound insights --help
hound config validate --config .hound.yml
hound doctor --json
```

Add tests for unknown keys, wrong types, invalid ranges, missing files, unsafe
URLs, redaction override warnings, JSON stdout purity, and every documented exit
code.

**Exit criteria:** Every documented command and option has a stable meaning,
invalid configuration fails or warns predictably, and users receive an actionable
message without secrets or traceback noise.

**Rollback:** Retain hidden/deprecated command aliases for one documented release
if existing public users would otherwise break. Do not change persisted schema
keys solely to improve command naming.

---

### P3 - Observability and Server Operations

**Severity:** High for server deployments, medium for offline CLI use

**Purpose:** Make failures diagnosable in production without polluting reports or
leaking sensitive data.

**Tasks:**

1. Introduce Python `logging` with module loggers instead of direct stderr writes.
2. Preserve CLI stdout for human results and machine-readable output; send logs to
   stderr unless an explicit log destination is configured.
3. Support text logs by default and optional JSON structured logs for the server.
4. Include timestamp, level, component, request ID, and job ID where available.
5. Never log API keys, bearer tokens, raw request bodies, full provider responses,
   unredacted artifact content, or secret-bearing paths.
6. Add configurable log level with a safe default and a documented debug mode.
7. Log lifecycle events for request admission, job creation, queue rejection,
   start, completion, failure category, cleanup, and graceful shutdown.
8. Add request/correlation IDs to server responses or headers where useful and
   include the same ID in structured logs.
9. Keep `/health` and `/ready` cheap and deterministic. Keep `/stats` authenticated
   and ensure it does not expose sensitive paths or payloads.
10. Document that the built-in server binds to loopback and that external TLS,
    network access, and rate limiting should be supplied by a reverse proxy or
    controlled internal network.
11. Add a tested nginx or Caddy example with TLS, bearer-token forwarding,
    request-size limits, access logs, and upstream rate limiting.
12. Define the in-memory rate-limit behavior on restart. For multi-instance or
    internet-facing deployments, require proxy/shared rate limiting instead of
    pretending the process-local counter is distributed.

**Verification:**

```powershell
hound serve --help
```

Run authenticated, unauthorized, queued, failed, full-queue, and shutdown cases
while collecting logs. Assert that structured logs contain IDs and do not contain
test secrets or request payloads.

**Exit criteria:** Operators can identify a request and job from logs, distinguish
configuration/provider/input failures, and deploy the server without exposing it
directly to the public network.

**Rollback:** Keep text logging as the fallback and disable JSON logging if a
consumer cannot parse it. Do not revert to raw payload logging to diagnose a
problem.

---

### P4 - Test Taxonomy and Automatic CI

**Severity:** High

**Purpose:** Restore automatic regression detection without recreating the noisy
failure-notification problem that led to CI being disabled.

**Context brief:** `.github/workflows/ci.yml` currently has only
`workflow_dispatch`. The repository already contains substantial unit,
subprocess, HTTP, SQLite, and evaluation coverage, but the suites are not formally
marked. The workflow also contains checks whose expected failure exit code must be
handled explicitly.

**Tasks:**

1. First reproduce every current CI failure on a dedicated branch or local clean
   checkout. Fix root causes; do not weaken coverage, lint, audit, or security
   assertions.
2. Add pytest markers such as `unit`, `integration`, `e2e`, `slow`, and `network`,
   and register them in pytest configuration.
3. Classify existing tests based on actual behavior:
   - pure parser/model tests as unit
   - HTTP server, SQLite, filesystem, and provider boundary tests as integration
   - subprocess, Docker, TUI pilot, and complete workflow tests as e2e or slow
4. Add a fast required PR job for lint, type checking, unit tests, and essential
   integration tests.
5. Add a broader scheduled or manually triggered job for slow, Docker, evaluation,
   and optional network tests.
6. Re-enable `pull_request` validation after the fast job is green. Add `push` on
   the protected `main` branch only if post-merge verification is needed. Keep
   `workflow_dispatch` for operators.
7. Add concurrency cancellation for stale pull-request runs to reduce duplicate
   notifications and wasted minutes.
8. Publish a single concise failure summary with links to detailed logs rather
   than sending a separate noisy signal for every matrix leg.
9. Use a known clean fixture for success smoke tests. When testing a fixture that
   intentionally contains a failure, assert exit code `1` explicitly and verify
   the report rather than allowing the shell to interpret it as an unexpected
   workflow failure.
10. Add coverage thresholds per meaningful suite and keep the existing overall
    threshold unless an evidence-based change is approved.
11. Add a dedicated packaging smoke job that installs wheel and source distribution
    artifacts outside the checkout.
12. Add Docker build, Action image build, Trivy scan, and Windows wheel smoke
    checks to the release gate.
13. Expand mypy coverage incrementally. Start with `server.py`, `pipeline.py`,
    and configuration boundaries; record any justified exclusions with issue
    references and tests.

**Verification:**

```powershell
uv run pytest -m unit -q
uv run pytest -m integration -q
uv run pytest -m "not network" -q
uv run ruff check .
uv run mypy src/hound
```

On a clean CI runner, verify that an intentionally failing artifact test passes
only when its expected exit code and report assertions pass.

**Exit criteria:** A pull request receives an automatic, actionable, bounded CI
result; required checks are green; stale runs are cancelled; and no expected
fixture behavior is misreported as infrastructure failure.

**Rollback:** Keep `workflow_dispatch` while diagnosing a broken required job,
but create an issue and restore the required trigger as soon as the root cause is
fixed. Do not permanently hide regression detection.

---

### P5 - Security and Dependency Policy

**Severity:** High

**Purpose:** Make security posture explicit for a tool that reads logs, handles
credentials, calls external models, and can optionally deliver tickets or alerts.

**Tasks:**

1. Define runtime dependency bounds in `pyproject.toml` based on tested and
   security-supported versions. Do not rely only on `uv.lock`, because pip-based
   installs resolve from project metadata.
2. Document the dependency update policy: update lockfile, run tests, run
   `pip-audit`, inspect release notes, and record exceptions.
3. Add Dependabot or an equivalent update workflow for runtime and Action
   dependencies with review labels and no automatic merge of major upgrades.
4. Keep dependency hashes and lockfile verification for CI and release builds.
5. Add secret scanning for committed files and generated artifacts. Redaction
   tests must cover API keys, bearer tokens, private keys, webhooks, passwords,
   connection strings, and PII patterns.
6. Add a test that a failed analysis and failed delivery do not write raw provider
   responses or credentials into reports, SQLite state, or logs.
7. Review all outbound network paths and document their opt-in conditions.
8. Keep `--api-key` available only with a prominent process-list warning; prefer
   environment variables or the credential store.
9. Review GitHub Action permissions. Build/test jobs should have read-only
   contents; release, attestation, and package-publish permissions must be split
   into narrowly scoped jobs and protected environments.
10. Pin third-party Actions to reviewed full commit SHAs and retain human-readable
    version comments.
11. Add a threat model for untrusted fork artifacts, path traversal, malicious
    logs, prompt injection, provider response injection, and optional delivery.
12. Review Dockerfiles for non-root execution, minimal context, writable paths,
    CA certificates, signal handling, and absence of development credentials.

**Verification:**

```powershell
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file audited-requirements.txt
uv run pip-audit --requirement audited-requirements.txt
rg "sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|BEGIN PRIVATE KEY|hooks.slack.com" .
```

The repository scan should find only synthetic fixture patterns in tests designed
to verify redaction, never real credentials.

**Exit criteria:** Dependencies are bounded and auditable, secrets are tested not
to escape, Action permissions are least-privilege, and the threat model covers
all trust-boundary decisions.

**Rollback:** Pin a known-good dependency version or disable a new integration;
never bypass the audit or commit a credential to make a build green.

---

### P6 - GitHub Action Maturity

**Severity:** Medium to high for Marketplace users

**Purpose:** Make the Action a first-class product surface rather than a thin
wrapper around a local Docker image.

**Context brief:** `action.yml` currently supports `log`, `repo`, `out`, and
`offline`, with a Docker-based implementation. Existing Action consumers are an
external compatibility boundary.

**Tasks:**

1. Keep existing input IDs working unless a major version explicitly removes
   them. Add clearer canonical names such as `input` or `output-dir` only with
   documented aliases and precedence.
2. Add safe inputs for provider/model, source context, context file, enrichment,
   redaction mode, and output format only where the trust and secret model is
   unambiguous.
3. Never accept API keys as ordinary Action inputs in examples. Use environment
   variables or GitHub secrets and document permissions.
4. Ensure every declared output is populated consistently, including failure and
   fallback cases.
5. Add a dedicated `docs/guides/github-action.md` with a minimal offline example, an
   optional LLM example, artifact upload guidance, permissions, and version pinning.
6. Add Action integration tests that build `Dockerfile.action`, execute a fixture,
   assert exit behavior, inspect `GITHUB_OUTPUT`, and verify redaction.
7. Test the Action image on the supported runner architecture and document any
   Docker-in-Docker or filesystem constraints.
8. Publish immutable major and minor Action tags only after release artifacts are
   validated. Keep a moving major tag only as a deliberate maintenance policy.
9. Add a release note whenever Action inputs, outputs, exit behavior, or default
   redaction changes.

**Verification:**

```powershell
docker build -f Dockerfile.action -t hound-action:smoke .
```

Run the image against sanitized fixtures and validate output files, exit codes,
and the absence of secrets.

**Exit criteria:** A GitHub user can copy a documented workflow, pin a version,
receive stable outputs, and understand how Action failures differ from detected
CI failures.

**Rollback:** Keep the previous Action major tag available and publish a new
patch/minor tag for fixes. Do not retag an immutable release to different bytes.

---

### P7 - Release Governance and Production Pilot

**Severity:** Blocking for stable public release

**Purpose:** Turn builds into controlled, verifiable releases with a recoverable
operator process.

**Tasks:**

1. Complete the distribution/install plan before enabling production publishing.
2. Create a release checklist covering changelog, version, tests, package metadata,
   Action image, Docker image, security audit, checksums, provenance, and smoke
   tests.
3. Enforce exact package-version to `vX.Y.Z` tag matching.
4. Protect `v*` tags with a GitHub ruleset and restrict who can create them.
5. Build wheel, source distribution, checksums, and optional container artifacts
   once. Promote the same retained bytes instead of rebuilding for each target.
6. Use separate least-privilege jobs for build/test, attestation, package publish,
   and GitHub Release creation.
7. Use TestPyPI before production PyPI and configure Trusted Publishing with OIDC,
   protected environments, and no long-lived token where supported.
8. Publish to PyPI only after artifact validation and approval. Verify the exact
   version and hashes after publication.
9. Create the GitHub Release from the same validated artifacts. Do not repoint a
   released tag or rebuild during a retry.
10. Define partial failure recovery:
    - PyPI succeeded and GitHub Release failed: reuse retained artifacts.
    - GitHub draft exists and PyPI failed: keep it unpublished and fix forward.
    - A bad PyPI version: yank only when necessary and issue a new patch version.
11. Add a canary or pilot release using sanitized offline fixtures before live LLM
    provider validation. Keep live provider canaries manual or scheduled and do
    not include credentials in output.
12. Define support and rollback status for the first stable release.

**Verification:**

```powershell
uv build
uvx twine check dist/*
git tag --list "v*"
hound --version
```

Install the exact wheel into a clean environment outside the checkout, run
`hound doctor`, perform offline analysis, verify checksums, and compare the CLI
version with the Git tag.

**Exit criteria:** One reviewed commit produces one immutable, traceable release
across GitHub, PyPI, and the Action surface, with a documented recovery path.

**Rollback:** Cancel before external publication. After publication, yank only
when necessary and fix forward. Never force-push a release branch or move a
published tag.

---

### P8 - Performance, Persistence, and Recovery Evidence

**Severity:** Medium; required before high-volume adoption

**Purpose:** Establish measured limits so production users know what Hound can
 safely handle.

**Tasks:**

1. Define supported artifact size, batch size, concurrency, queue depth, and job
   retention limits.
2. Add tests for empty files, malformed encodings, very large logs, many artifacts,
   concurrent workers, interrupted jobs, disk-full behavior, and permission errors.
3. Measure cold startup, single-artifact latency, batch throughput, peak memory,
   SQLite contention, and server queue behavior.
4. Record benchmark commands and runner assumptions without making unstable
   hardware numbers hard release gates.
5. Verify deduplication, retention, and state migration under concurrent access.
6. Document backup and restore of `.hound` state, including jobs, feedback,
   and history databases.
7. Add corruption handling tests: detect a damaged store, preserve the original,
   create a clearly named recovery path, and fail with an actionable message.
8. Test graceful shutdown with queued and running jobs and document what survives
   restart.
9. Add a Textual Pilot or equivalent headless test for critical TUI paths: browse,
   analyze, retry, filter, settings, and quit.

**Verification:**

```powershell
uv run pytest -m "slow or integration" -q
uv run python examples/demo/run_demo.py --profile smoke
uv run python examples/demo/run_demo.py --profile scale --count 5000 --jobs 8
```

Record results in a versioned benchmark note; do not commit generated output or
real logs.

**Exit criteria:** Documented limits are backed by tests, state recovery is
understood, and concurrency does not silently corrupt reports or databases.

**Rollback:** Keep scale features behind existing bounded options. If a new
concurrency path is unstable, disable it and retain the sequential path.

---

### P9 - Optional Extensions After the First Stable Release

These are deliberately deferred until the core release is reliable:

- signed standalone binaries for platforms where Python installation is a proven
  adoption barrier
- shell and PowerShell convenience installers
- shared persistent rate limiting for multi-instance server deployments
- OpenTelemetry integration for operators who explicitly opt in
- hosted dashboard or remote history storage
- package-manager manifests for Homebrew, Winget, Scoop, or Chocolatey

Each extension requires its own threat model, compatibility matrix, rollback plan,
and user-demand evidence. None should weaken the offline-first or privacy-first
defaults.

## 8. Pull Request Breakdown

| PR | Scope | Depends On | Priority | Parallel |
|---|---|---|---|---|
| Preflight | Dedicated checkout and migration safety; no repository feature diff | None | Blocker | No |
| PR 1 | Changelog, contributing, security, path and support documentation | Preflight | High | Yes |
| PR 2 | Canonical CLI names, aliases, config schema, version source, errors | Preflight | High | Yes |
| PR 3 | Logging framework, structured server logs, operations docs | PR 2 | High | No |
| PR 4 | Test markers, CI recovery, packaging and Docker gates | PR 2 | High | Yes |
| PR 5 | Dependency bounds, secret scans, Action permission review | PR 2 | High | Yes |
| PR 6 | GitHub Action inputs, outputs, docs, and integration tests | PR 2, PR 4 | Medium | No |
| PR 7 | Release workflow, Trusted Publishing, tag protection, recovery | PR 1-6 | Blocker | No |
| PR 8 | Load, persistence recovery, TUI Pilot, benchmark evidence | PR 3, PR 4 | Medium | Yes |
| Backlog | Installers, binaries, shared rate limit, telemetry, package managers | PR 7 | Optional | Yes |

Each PR must be independently reviewable, use conventional commits, and avoid
mixing application features with release hardening.

## 9. Release Gates

The first stable release must pass all applicable gates:

- Dedicated Git root and correct remote verified.
- No placeholder URLs or private filesystem paths in public docs.
- `CHANGELOG.md`, `CONTRIBUTING.md`, and `SECURITY.md` present.
- Canonical commands and deprecated aliases documented.
- Version source is singular and tag equality is tested.
- Config schema, unknown-key behavior, and error categories are tested.
- Unit, integration, and required e2e tests are green.
- Pull-request CI is active and required checks are configured.
- Lint, type checking, coverage, dependency audit, secret scan, and Trivy pass.
- Wheel, source distribution, Docker image, and Action image smoke tests pass.
- Server logs are structured or consistently formatted, correlation IDs work, and
  no sensitive values appear.
- Server deployment does not expose the loopback-only process directly to the
  public internet.
- Persistent state migration, retention, interruption, and recovery are tested.
- TestPyPI publication and clean installation pass.
- Release artifacts have matching versions, hashes, and provenance.
- GitHub Action usage is version-pinned and documented.
- Offline-first behavior and redaction defaults remain intact.

## 10. Success Metrics

Measure the first 30 days after release:

- A new user reaches `hound --version` in under five minutes.
- Clean Windows and Linux installation success is at least 95% in the documented
  test matrix.
- Required PR checks have no unexplained red runs.
- Mean time to diagnose a CI failure is reduced by actionable logs and reports.
- Zero known secret disclosures in committed fixtures, reports, or logs.
- Zero tag/package/CLI version mismatches.
- Release recovery can complete without rebuilding or moving immutable artifacts.
- Support requests can be classified as installation, configuration, provider,
  analysis, Action, or server issues.

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Re-enabling CI recreates notification noise | Use required PR checks, concurrency cancellation, concise summaries, and fix failures before enabling |
| Naming changes break external users | Preserve documented aliases and Action input IDs through a planned deprecation window |
| Logging leaks sensitive data | Redact before logging, prohibit payload logging, add negative tests, and review sample logs |
| Config strictness breaks existing files | Warn by default, provide strict CI mode, and document unknown keys before making strict default |
| Runtime dependency resolution differs from uv | Add metadata bounds, test pip/pipx/uv installs, and audit both lock and package metadata |
| PyPI publication is only partially successful | Build once, retain artifacts, publish in ordered jobs, and define idempotent recovery |
| Server is exposed without TLS | Bind to loopback and require documented reverse-proxy deployment for external access |
| In-memory rate limiting is mistaken for distributed protection | Document the boundary and require proxy/shared limiting for multi-instance deployments |
| Mypy expansion causes scope explosion | Type-check boundaries first, track justified exclusions, and retain runtime tests |
| Production hardening becomes over-engineered | Gate optional extensions on measured demand and keep SQLite/offline defaults |

## 12. Plan Mutation Protocol

If implementation evidence changes an assumption:

1. Record the finding and affected files in this plan.
2. Do not weaken a release gate to preserve schedule.
3. Split a milestone when it exceeds one reviewable PR.
4. Add a prerequisite before dependent work rather than hiding it in a later PR.
5. Mark optional work as deferred when package-based distribution and local
   operations already meet user needs.
6. Update the dependency graph and PR table whenever ordering changes.
7. Preserve a rollback and recovery path for every workflow or persistence change.

## 13. Recommended First Release Scope

For the first stable public release, complete P0 through P7. Treat P8 as a
targeted gate for users who process large batches or operate the HTTP server at
scale. Defer P9 until real adoption data shows that it solves a material problem.
