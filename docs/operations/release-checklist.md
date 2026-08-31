# Release Checklist

## Repository And Version

- [ ] `git rev-parse --show-toplevel` identifies only the Hound checkout.
- [ ] `git remote -v` points to `youthisss/hound-agent`.
- [ ] The release commit is reviewed, reachable from protected `main`, and clean.
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

- [ ] The exact candidate is published through the protected TestPyPI OIDC environment.
- [ ] Its direct wheel URL, SHA-256, clean install, `hound doctor`, and offline smoke pass.
- [ ] The release workflow builds distributions once and retains those bytes.
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
