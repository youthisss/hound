# Hound Agent Distribution and Installation Plan

## 1. Objective

Make Hound Agent installable as an end-user CLI without cloning the repository,
while retaining a separate contributor setup. The delivery path should mature in
stages:

1. Install directly from GitHub with `uv tool` or `pipx`.
2. Install a released Python package from PyPI.
3. Download verified release artifacts from GitHub Releases.
4. Optionally install through platform scripts or native standalone binaries.

The first stable user experience should be:

```powershell
uv tool install hound-agent
hound --version
hound doctor
```

Until PyPI publishing is ready, the supported command should be:

```powershell
uv tool install "hound-agent @ git+https://github.com/youthisss/hound-agent.git@<reviewed-full-commit-sha>"
```

An unpinned install from `main` is a development channel, not a supported
end-user installation path. Keep using a full commit SHA until both the first
validated tag and the `v*` tag-protection ruleset exist. Only then replace the
SHA in user documentation with an immutable release tag such as `v0.4.0`.

## 2. Current State

- The project is a Python package built with Hatchling.
- `pyproject.toml` declares package version `0.4.0` and the `hound` console script.
- The README currently presents `git clone` plus `uv sync --extra dev` as the
  primary installation method. This is a contributor workflow, not an end-user
  installation workflow.
- The README still contains the placeholder repository URL
  `https://github.com/your-org/hound-agent.git`.
- `.github/workflows/release.yml` builds and smoke-tests wheel artifacts when a
  `v*` tag is pushed, but does not publish to PyPI.
- The release workflow creates checksums and a GitHub Release.
- CI is currently manual through `workflow_dispatch`.
- The local checkout is nested under a Git repository rooted at `D:\Project`,
  whose `origin` points to another project. This must be corrected before normal
  release work to prevent unrelated project history from reaching Hound Agent.

## 3. Scope

### In Scope

- Safe local repository isolation.
- User and contributor installation documentation.
- Package metadata and build validation.
- PyPI Trusted Publishing and release automation.
- GitHub Release artifact verification.
- Upgrade and uninstall documentation.
- Optional shell and PowerShell installers after the package release is stable.
- Evaluation of standalone binaries after package-based distribution is proven.

### Out of Scope

- Automatic installation of API keys or secrets.
- Publishing before ownership of the PyPI package name is confirmed.
- Curl or PowerShell installers that execute unpinned content from `main`.
- Native binaries before dependency compatibility and artifact signing are
  evaluated.
- Homebrew, Winget, Chocolatey, or Scoop manifests before at least one stable
  release exists.

## 4. Invariants

These conditions must hold after every step:

1. `hound analyze --offline` remains usable without API credentials.
2. Secrets are never embedded in packages, installers, workflow files, logs, or
   documentation examples.
3. A release tag and package version identify the same version.
4. Built wheels install into a clean environment and expose the `hound` command.
5. Release artifacts are produced from a reviewed commit, not mutable branch
   content.
6. Existing source-install and Docker use cases remain available.
7. No force-push or history rewrite is part of the normal release process.
8. No work is committed from the `D:\Project` parent repository after preflight.

## 5. Dependency Graph

```text
Preflight: Isolate repository and migrate Hound-only work
  -> Step 2: Correct immediate installation UX
  -> Step 3: Harden package and release validation
      -> Step 4: Prove publishing on TestPyPI
          -> Step 5: Stabilize release operations and enable production PyPI
              -> Step 6A: Installer scripts (optional)
              -> Step 6B: Standalone binaries (optional, parallel with 6A)
```

Steps 2 and 3 may be developed in parallel after preflight, although Step 2 must
be updated again with the final package name from Step 3. Steps 6A and 6B are an
evidence-triggered backlog and may run in parallel only after Step 5 has completed
successfully.

## 6. Implementation Steps

### Preflight - Isolate Hound Agent as Its Own Git Repository

**Purpose:** Remove the current risk that commits or pushes include sibling
projects under `D:\Project`.

**Context brief:** The current `git rev-parse --show-toplevel` resolves to
`D:\Project`, and that repository contains unrelated projects. The Hound Agent
remote is configured as a secondary remote. Release work must use a checkout
whose Git root is exactly the Hound Agent directory.

**Tasks:**

1. Inventory Hound-only tracked changes and untracked files without staging or
   modifying sibling projects:

   ```powershell
   git -C D:\Project\hound-agent diff --binary --relative `
     --output="$env:TEMP\hound-agent.patch" -- .
   git -C D:\Project status --short -- hound-agent
   Get-ChildItem D:\Project\hound-agent -Recurse -File | ForEach-Object FullName |
     Set-Content $env:TEMP\hound-agent-files.txt
   ```

2. Copy untracked Hound-only files to a temporary archive after reviewing the
   status output. Do not archive secrets, caches, virtual environments, or build
   output.
3. Clone `https://github.com/youthisss/hound-agent.git` into a new dedicated
   directory outside the `D:\Project` repository, or move the parent `.git`
   only after separately auditing all projects. A fresh clone is preferred.
4. Apply the Hound-only patch in the fresh clone and intentionally copy reviewed
   untracked files. First run `git apply --check $env:TEMP\hound-agent.patch`,
   then apply it only if validation succeeds. Paths are relative to the old
   `hound-agent` directory.
5. Compare tracked diffs and file manifests between old and new Hound checkouts.
6. Confirm the dedicated checkout has `origin` set to the Hound Agent URL.
7. Document the canonical local path used for future Hound Agent release work.
8. Do not delete the old nested directory until migrated changes are committed or
   intentionally discarded in the dedicated checkout.

**Verification:**

```powershell
git rev-parse --show-toplevel
git remote -v
git status --short
```

Expected: the top-level path is the dedicated Hound Agent checkout, `origin`
points only to `youthisss/hound-agent`, and `git status` contains only intentionally
migrated Hound changes. Compare `git diff --stat` and the reviewed file manifest
before proceeding.

**Exit criteria:** Future `git add`, `commit`, and `push` operations cannot include
files from sibling projects.

**Rollback:** Keep using the existing checkout read-only and remove only the new
clone if validation fails. Do not alter the parent repository.

---

### Step 2 - Correct the Immediate Installation Experience

**Purpose:** Give users a no-clone installation path before PyPI is configured.

**Context brief:** The package already exposes `hound = "hound_agent.cli:main"`,
so `uv tool` and `pipx` can install it directly from GitHub. Contributor setup
still needs a clone and development dependencies.

**Tasks:**

1. Replace the placeholder README URL with the real repository URL.
2. Split README installation into these explicit paths:
   - Recommended pre-PyPI user install from a reviewed full commit with
     `uv tool install`. Promote a release tag only after `v*` tag protection is
     configured.
   - Alternative user install with `pipx`.
   - Contributor setup with `git clone`, `uv sync --extra dev`, and
     `uv run hound`.
   - Docker usage, linked rather than duplicated.
3. Add verification commands: `hound --version` and `hound doctor`.
4. Add upgrade and uninstall commands for both `uv tool` and `pipx`.
5. State Python and `uv`/`pipx` prerequisites accurately for Windows, macOS, and
   Linux without claiming unsupported package managers.
6. Test README commands in clean temporary environments on Windows and Linux.

**Verification:**

```powershell
uv tool install "hound-agent @ git+https://github.com/youthisss/hound-agent.git@<reviewed-ref>"
hound --version
hound doctor --output-dir hound-doctor-output --json
uv tool uninstall hound-agent
```

On Linux, run the equivalent commands in a clean container or CI runner.

**Exit criteria:** A new user can install and invoke Hound without cloning the
repository, and a contributor can clearly identify the separate development
workflow.

**Rollback:** Revert documentation only. No runtime behavior changes are needed.

---

### Step 3 - Harden Packaging and Release Validation

**Purpose:** Ensure every artifact is complete, reproducible enough to inspect,
and installable before publication.

**Context brief:** Packaging metadata exists, and the release workflow already
builds a wheel and source distribution. Release validation should be reusable
without requiring an actual release tag.

**Tasks:**

1. Audit `pyproject.toml` metadata for project URLs, authors or maintainers,
   classifiers, keywords, supported Python versions, and license expression.
2. Confirm the PyPI distribution name `hound-agent` is available or controlled.
   If not, choose a new distribution name while preserving the `hound` command.
3. Establish one version source of truth. Avoid manual drift between
   `pyproject.toml` and `src/hound_agent/__init__.py`.
4. Add a packaging verification job or script that runs:
   - `uv build`
   - metadata validation with `twine check dist/*` or an equivalent tool
   - clean wheel installation
   - `hound --version`
   - `hound doctor`
   - one offline smoke analysis using a temporary fixture
5. Validate both wheel and source distribution installations.
6. Add tag/version validation: tag `vX.Y.Z` must equal package version `X.Y.Z`.
7. Keep dependency audit and artifact checksum generation.
8. Run artifact smoke tests from a temporary directory outside the repository so
   local source files and `PYTHONPATH` cannot mask incomplete packages.
9. For a fixture containing a detected failure, explicitly assert exit code `1`
   and validate generated reports. Do not treat that expected result as workflow
   failure. Alternatively, use a known clean fixture when asserting exit code `0`.
10. Decide whether normal CI remains manual. At minimum, package validation must
   run as a required release gate before publication.

**Verification:**

```powershell
uv build
uvx twine check dist/*
uv venv package-smoke
$wheel = (Get-ChildItem dist\*.whl | Select-Object -First 1).FullName
uv pip install --python package-smoke\Scripts\python.exe $wheel
$smoke = Join-Path $env:TEMP "hound-package-smoke"
New-Item -ItemType Directory -Force $smoke | Out-Null
Set-Content (Join-Path $smoke "failure.log") "AssertionError: expected 1 but got 2"
Push-Location $smoke
& <absolute-path-to-package-smoke\Scripts\hound.exe> --version
& <absolute-path-to-package-smoke\Scripts\hound.exe> analyze . --offline --output-dir output
if ($LASTEXITCODE -ne 1) { throw "expected detected-failure exit code 1" }
if (-not (Test-Path output\failure\report.json)) { throw "expected report.json" }
Pop-Location
```

Resolve absolute paths before changing directory. Use separate clean environments
for the wheel and source distribution, and use `bin/hound` on Linux and macOS.

**Exit criteria:** Both artifact formats pass metadata validation and clean
installation smoke tests; mismatched tags cannot enter the publishing job.

**Rollback:** Disable the new publishing path while retaining build artifacts
for diagnosis. Never publish a package that failed smoke tests.

---

### Step 4 - Prove Publishing on TestPyPI

**Purpose:** Prove package ownership and OIDC publication safely before enabling
immutable production PyPI releases.

**Context brief:** GitHub Actions supports PyPI Trusted Publishing through OIDC.
The existing release workflow already grants `id-token: write`, but publication
must use a GitHub Environment with explicit controls.

**Tasks:**

1. Confirm the final distribution name separately on TestPyPI and PyPI. For a new
   project, configure a pending trusted publisher where supported; for an existing
   project, verify current ownership before changing publisher settings.
2. Configure a TestPyPI trusted publisher bound exactly to the GitHub owner,
   repository, workflow filename, and `testpypi` environment.
3. Add a manually triggered TestPyPI workflow or mode for release candidates.
4. Split workflow jobs by privilege. The build job receives only
   `contents: read`; only the TestPyPI job receives `id-token: write` and the
   protected environment.
5. Require artifact build and validation jobs to complete before TestPyPI publish.
6. Publish with `pypa/gh-action-pypi-publish` pinned to a reviewed full commit SHA.
7. Download the exact TestPyPI wheel URL, verify its hash, and install that direct
   artifact URL so dependencies continue resolving from production PyPI without
   exposing Hound Agent to an unsafe indiscriminate extra-index strategy.
8. Run clean, outside-checkout smoke tests and explicitly assert expected exit
   codes.
9. Do not use a PyPI API token unless Trusted Publishing is unavailable and the
   exception is documented.
10. Record the separate TestPyPI and PyPI publisher identities and bootstrap
    procedure in maintainer documentation without secrets.

**Verification:**

```powershell
uv tool install "<exact-TestPyPI-wheel-URL>"
hound --version
hound analyze <temporary-failure-fixture-directory> --offline --output-dir testpypi-smoke-output
# Assert exit code 1 and validate the generated report.
uv tool uninstall hound-agent
```

Resolve and verify the exact wheel URL from TestPyPI metadata. Do not configure
TestPyPI as an unrestricted extra index.

**Exit criteria:** A clean machine can install the exact TestPyPI artifact, its
hash and version match the candidate, and all smoke checks pass.

**Rollback:** TestPyPI artifacts are disposable validation releases, but versions
still must not be reused as if bytes were mutable. Fix forward with a new release
candidate.

---

### Step 5 - Stabilize Release Operations and Enable Production PyPI

**Purpose:** Make releases repeatable, inspectable, and recoverable.

**Context brief:** The current tag workflow creates a GitHub Release with wheel,
source distribution, checksums, and provenance attestations. It needs explicit
release governance around tags and publication ordering.

**Tasks:**

1. Add a release checklist covering version update, changelog, full tests,
   dependency audit, package smoke tests, and tag signing policy.
2. Use a manual release workflow that accepts a version, verifies that the target
   commit is reachable from the protected release branch, validates it, builds
   once, and promotes the same retained artifacts to PyPI and GitHub Releases.
3. Avoid rebuilding independently for PyPI and GitHub; publish the same validated
   artifacts from a single workflow run.
4. Split jobs and permissions:
   - Build and test: `contents: read` only.
   - Production PyPI: `id-token: write` only, plus `contents: read`, protected by
     the `pypi` environment and manual approval.
   - Attestation: `id-token: write` and `attestations: write` only where needed.
   - GitHub Release: `contents: write` only in the release creation job.
5. Configure the production PyPI pending/existing Trusted Publisher independently
   from TestPyPI, matching the exact `pypi` environment and workflow identity.
6. Retain SHA-256 checksums, workflow artifacts, and provenance attestations.
7. Add release concurrency so the same version cannot publish twice.
8. Add a GitHub tag ruleset restricting `v*` creation. Require the released commit
   to be reachable from the protected release branch and enforce exact PEP 440 to
   tag-version equality.
9. Define prerelease handling for versions such as `0.5.0rc1`.
10. Implement this publication state machine:
    - Build once and retain immutable workflow artifacts.
    - Validate and approve those artifacts.
    - Publish to PyPI and verify the exact version and hashes.
    - Create or publish the GitHub Release from the same retained bytes.
    - Never rebuild on a publication retry.
11. Define idempotent reruns: skip already verified PyPI publication, reuse retained
    artifacts, and complete a missing GitHub Release without moving or recreating
    the tag.
12. Use a draft GitHub Release before external publication if operator visibility
    is needed, then publish it only after PyPI verification.
13. Document partial failure recovery for PyPI success/GitHub failure and GitHub
    draft success/PyPI failure. Never delete or repoint a released tag.
14. Document the patch-release procedure for a failed or yanked release.
15. Verify the GitHub release contains only intended artifacts and generated
    release notes.

**Verification:**

```powershell
git fetch --tags origin
git tag --list "v*"
uvx gh-release-downloader --help
```

Use GitHub's API or CLI to download the release into a temporary directory,
verify checksums, install the wheel, and compare `hound --version` with the tag.
The exact downloader may differ; use an authenticated, maintained tool available
in the release environment.

**Exit criteria:** One reviewed action produces one immutable version across the
Git tag, GitHub Release, and PyPI, with matching checksums and smoke-tested
artifacts.

**Rollback:** Cancel before publication whenever possible. After PyPI publication,
yank only when necessary and fix forward with a new patch version. If only GitHub
Release creation failed, reuse retained bytes to complete it; never rebuild,
delete the published package, or repoint the tag.

---

### Step 6A - Add Convenience Installer Scripts (Optional)

**Purpose:** Offer Hermes/OpenCode-like onboarding without making scripts the
source of package truth.

**Context brief:** Installer scripts should select and install a specific
released package. They must not execute arbitrary content from `main` or hide
the package manager used underneath.

**Tasks:**

1. Start this step only if user evidence shows that requiring `uv` or `pipx` is a
   material adoption barrier. Create `install.sh` and `install.ps1` only after
   PyPI installation is stable.
2. Default to the latest stable version but support an explicit version option.
3. Verify downloaded installer content and release artifacts using pinned URLs
   and checksums where applicable.
4. Detect prerequisites and provide actionable errors; do not silently install
   unrelated system dependencies with elevated privileges.
5. Install into a user-owned location and explain PATH changes.
6. Provide `--dry-run`, `--version`, and non-interactive behavior where practical.
7. Add automated tests for Windows PowerShell and Linux shell execution.
8. Document the trust model of `curl | sh` and provide a download-inspect-run
   alternative.

**Verification:**

```powershell
Invoke-WebRequest <versioned-install-ps1-url> -OutFile install.ps1
Get-FileHash .\install.ps1 -Algorithm SHA256
.\install.ps1 -Version <version>
hound --version
```

```sh
curl -fL -o install.sh <versioned-install-sh-url>
sha256sum install.sh
sh install.sh --version <version>
hound --version
```

**Exit criteria:** Both installers work on clean supported runners, install a
requested immutable version, and fail safely when prerequisites are missing.

**Rollback:** Remove installer links from documentation while leaving PyPI and
GitHub Release installation available.

---

### Step 6B - Evaluate Standalone Native Binaries (Optional)

**Purpose:** Determine whether users without Python can receive a reliable
single-command installation experience.

**Context brief:** Hound uses Python packages including Textual, GitPython,
keyring, YAML, XML parsing, and OpenAI integration. Freezing these dependencies
can increase artifact size and introduce platform-specific behavior. A binary
must be justified by measured user value, not visual parity with another CLI.

**Tasks:**

1. Start this step only if measured demand justifies no-Python installation.
2. Prototype PyInstaller and Nuitka builds on Windows, Linux, and macOS.
3. Measure artifact size, startup time, build duration, antivirus false positives,
   keyring behavior, certificate handling, and TUI behavior.
4. Run the same CLI, doctor, offline analysis, and TUI smoke suite against each
   binary.
5. Choose one builder only if it passes the compatibility matrix.
6. Produce per-platform archives, checksums, provenance, and optionally signatures.
7. Upload binaries to the same versioned GitHub Release without replacing Python
   package artifacts.
8. Add platform selection to installer scripts only after binaries are stable.

**Verification:**

```text
Windows x86_64: hound.exe --version, doctor, offline analysis, TUI launch
Linux x86_64:   hound --version, doctor, offline analysis, TUI launch
macOS arm64:    hound --version, doctor, offline analysis, TUI launch
```

Record cold startup time and compressed artifact size for each target.

**Exit criteria:** Supported binaries pass functional and security checks on clean
runners and provide a documented advantage over `uv tool install`.

**Rollback:** Do not publish binaries, or mark affected artifacts unsupported;
retain the Python package as the canonical distribution.

## 7. Pull Request Breakdown

| PR | Scope | Depends On | Model Tier | Parallelizable |
|---|---|---|---|---|
| Preflight | Dedicated repository setup and Hound-only change migration; no PR | None | Strongest | No |
| PR 1 | README installation, upgrade, uninstall, URL corrections | Preflight | Default | Yes |
| PR 2 | Metadata, version consistency, artifact validation tests | Preflight | Strongest | Yes |
| PR 3 | TestPyPI Trusted Publishing and candidate verification | PR 2 | Strongest | No |
| PR 4 | Release governance, production PyPI, promotion and recovery | PR 1, PR 3 | Strongest | No |
| Backlog A | Versioned shell and PowerShell installers, if demand exists | PR 4 | Strongest | Yes |
| Backlog B | Native binary feasibility, if demand exists | PR 4 | Strongest | Yes |

Each PR should be independently reviewable and should not combine application
features with distribution changes.

## 8. Release Gates

A production release must not proceed unless all applicable gates pass:

- Repository root and remote are correct.
- Worktree is clean.
- Unit tests, lint, and type checks pass.
- Dependency audit has no unaccepted blocking findings.
- Wheel and source distribution metadata validate.
- Both artifact formats install in clean environments.
- `hound --version` equals the tag version.
- `hound doctor` passes required checks.
- Offline fixture analysis produces the expected exit code and validated report.
- Checksums and provenance are generated.
- TestPyPI smoke testing has passed for the release process.
- GitHub Environment approval is satisfied for production PyPI.
- No credentials appear in artifacts or workflow logs.

## 9. Success Metrics

Track these after the first PyPI release:

- A new user reaches `hound --version` in under five minutes.
- The documented installation succeeds on clean Windows and Linux runners.
- Package smoke tests have a 100% pass rate across supported Python versions.
- Tag, package, and CLI versions have zero mismatches.
- Releases require no manually copied long-lived publishing token.
- No unrelated repository files appear in Hound Agent commits or releases.
- Installer support requests can be distinguished from application defects.

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `hound-agent` PyPI name unavailable | Check ownership before workflow work; rename distribution only, preserve CLI name |
| Parent Git repository leaks unrelated files | Complete preflight before any implementation or release commit |
| Manual CI allows broken tags | Make release validation mandatory inside the release workflow |
| Version drift | Use one version source and enforce tag/version equality |
| Trusted Publisher misconfiguration | Prove flow on TestPyPI before production PyPI |
| Immutable bad PyPI release | Yank and fix forward with a new patch version |
| Installer executes mutable code | Use versioned release URLs, checksums, and inspect-before-run instructions |
| Frozen binary behaves differently | Maintain package install as canonical and gate binaries per platform |
| Dependency confusion during TestPyPI testing | Document and verify an index strategy that pins Hound to TestPyPI safely |

## 11. Plan Mutation Protocol

If implementation evidence invalidates a step:

1. Record the discovery and affected assumptions in this file.
2. Do not weaken release gates to preserve schedule.
3. Split a step when it can no longer fit in one reviewable PR.
4. Insert a prerequisite before dependent work rather than hiding it inside a
   later PR.
5. Mark optional installer or binary work as skipped if package-based install
   already meets user needs.
6. Update the dependency graph and PR table whenever ordering changes.
7. Preserve rollback instructions for every changed step.

## 12. Recommended First Milestone

Complete preflight and Steps 2 through 4 before attempting production publication.
This delivers an immediate no-clone installation command, corrects unsafe local
Git structure, proves package artifacts, and validates OIDC publishing on
TestPyPI. Proceed to Step 5 only after the package name and Trusted Publishing
ownership are confirmed.
                                                                                                                                                                                                                                                                                        
