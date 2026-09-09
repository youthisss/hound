# Dependency Update Policy

Runtime, development, GitHub Action, and container dependencies are reviewed
through Dependabot. Minor and patch updates may be grouped; major updates are
always reviewed separately and are never automatically merged.

## Update Procedure

1. Read upstream release notes and security advisories. Confirm supported Python
   and platform versions before changing bounds in `pyproject.toml`.
2. Update the lock deterministically with `uv lock --upgrade-package <name>`.
3. Run `uv sync --frozen --extra dev`, the full tests, Ruff, mypy, package build,
   Twine metadata validation, and the production dependency audit.
4. For Actions and container images, retain a reviewed immutable commit SHA or
   image digest and update the human-readable version comment.
5. Record behavior changes in `CHANGELOG.md`. Audit exceptions require an owner,
   rationale, tracking issue, and expiry date.

```sh
uv run ruff check .
uv run mypy src/hound
uv run pytest --cov=hound --cov-report=term --cov-fail-under=80 -q
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file audited-requirements.txt
uv run pip-audit --requirement audited-requirements.txt
uv build
uv run twine check dist/*.whl dist/*.tar.gz
```

For an emergency regression or advisory, pin the last known safe supported
version, regenerate `uv.lock`, run the same gates, and fix forward. Never bypass
the audit or silently widen an upper bound to make CI pass.
