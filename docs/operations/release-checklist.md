# Release Checklist

## Repository And Version

- [ ] `git rev-parse --show-toplevel` identifies only the Hound checkout.
- [ ] `git remote -v` points to `youthisss/hound`.
- [ ] The release commit is reviewed, reachable from protected `main`, and clean.
- [ ] The Release workflow is dispatched from protected `main`, not a feature branch.
- [ ] `CHANGELOG.md` covers behavior, schema, CLI, and Action contract changes.
- [ ] `hound --version` equals the intended `vX.Y.Z` tag exactly.
- [ ] The `v*` tag ruleset and `pypi`/`github-release` environment reviewers are active.

## Quality And Security

- [ ] Ruff, mypy, unit, integration, e2e, evaluation, and 80% overall coverage gates pass.
- [ ] `pip-audit`, repository/artifact secret scan, and Trivy image scans pass.
- [ ] Wheel and source distribution pass Twine and clean outside-checkout installs.
- [ ] Windows wheel, runtime Docker image, and GitHub Action output contract pass.
- [ ] Redaction defaults, offline behavior, and least-privilege workflow permissions are unchanged.

## Candidate And Publication

- [ ] The exact candidate is published through the protected TestPyPI OIDC environment by the release workflow.
- [ ] Its direct wheel URL, SHA-256, clean install, `hound doctor`, and offline smoke pass.
- [ ] The release workflow builds distributions once and promotes the same retained bytes from TestPyPI to PyPI.
- [ ] PyPI publication completes and the published hashes match retained artifacts.
- [ ] Provenance and `SHA256SUMS` cover every distribution.
- [ ] GitHub Release is created from the same retained artifacts; no retry rebuild occurs.
- [ ] GitHub Action major/minor tags are created only from validated immutable release bytes.

## Pilot And Recovery

- [ ] `docs/operations/pilot-readiness.md` has reviewed aggregate evidence from at least two repositories and 100-300 sanitized real failures.
- [ ] Zero known redaction escapes and duplicate confirmed deliveries are recorded.
- [ ] Accepted precision, unknown-rate, cost, throughput, and support limitations are explicit.
- [ ] Partial failure recovery is understood: reuse retained artifacts after a GitHub failure; keep a draft unpublished after a PyPI failure; yank only when necessary and fix forward with a new version.
- [ ] Support and rollback status are announced. Published tags are never moved.

## Maintainer Recovery

- Sign annotated release tags with the maintainer's verified signing key and never replace a published tag.
- Use PEP 440 prerelease versions (`aN`, `bN`, or `rcN`) and set the workflow's `prerelease` input for non-final releases.
- Bootstrap the `hound-tracer` TestPyPI/PyPI projects with the maintainer account, then restrict publishing to this repository's `testpypi` and `pypi` GitHub environments through Trusted Publishing.
- If TestPyPI contains the same version with different hashes, increment the version; do not overwrite candidate files.
- If PyPI succeeds but GitHub Release fails, dispatch the same version again with
  `source_run_id` set to the original Release run ID. The recovery path downloads
  that run's distributions, checksums, and identity, verifies the build job and
  hashes, and never rebuilds the package. `skip-existing` is safe only because the
  workflow verifies every retained hash before recreating the release.
- If PyPI fails, leave any GitHub release unpublished and fix forward without rebuilding or moving the tag.
- If a published artifact is harmful, yank it in PyPI, record the reason in the changelog, and issue a new patch version. Never reuse the version number.
