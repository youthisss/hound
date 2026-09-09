# WORKFLOW — Hound

Process rules to keep the project linear. Deviations require updating this file, `docs/prd.md`, or the relevant record under `docs/plans/` **first**.

## Repo context

- Works inside the Hound repository.
- Do not touch files outside the repository.
- Package name `hound`, import module `hound`.

## Change flow (strict order)

1. Docs → 2. Scaffold → 3. ingest → 4. analyze → 5. triage → 6. output → 7. cli → 8. tests → 9. verify.

Within each stage: **one area at a time**. Never edit two modules in parallel; finish + test one before starting the next.

### Definition of done (per task)
- Code written matching `docs/architecture.md` contracts.
- Unit tests for the module (or pipeline coverage where noted in `docs/plans/`).
- `uv run pytest` green.
- No "TODO" reference to the module remains in other files.

## Git / commit rules

- Commit at stage boundaries (one commit per milestone in `docs/plans/`).
- Messages: conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), subject ≤ 72 chars.
- Never commit `.env`, API keys, or out-dir artifacts.
- Stage only files under this repository.

## Verify gate (before any milestone is "done")

```sh
uv run ruff check .
uv run mypy src/hound
uv run pytest --cov=hound --cov-report=term --cov-fail-under=80 -q
uv run python -m hound.eval --offline --format json
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file audited-requirements.txt
uv run pip-audit --requirement audited-requirements.txt
uv run hound analyze tests/fixtures --offline
uv run hound log -- pytest -q
```

Tests must exit 0. Fixture analysis exits 1 when failures are detected. Log collector preserves child command exit. Same-input offline runs must produce identical `dedup_key`.

Evaluation cases use `eval_case_version: "1.0"`. Artifact paths are relative to
the case file, labels contain synthetic/sanitized data only, and cases live in
separate `dev` and `held_out` directories. Production logs must be anonymized at
source: remove customer/repository identifiers, replace secrets with synthetic
tokens, preserve only failure-relevant structure, then run the redaction corpus
check before committing. Held-out cases must not be inspected to tune a rule in
the same change; baseline reports may aggregate them.

The case contract is strict: unknown or missing fields fail evaluation. Expected
failed-test names may use the stable leaf identity (for example `test_checkout`)
instead of a runner-specific path prefix. The committed
`tests/eval/baseline-v1.0.json` records deterministic baseline metrics; throughput
and peak-memory numbers remain command output because they depend on the runner.

Production-readiness milestones (M11+) add:

```sh
uv run hound analyze tests/fixtures --offline --output-dir .audit-redact-check
rg "sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]" .audit-redact-check   # must find nothing
```

Redaction default is on; any secret pattern in `--output-dir` artifacts fails the gate.

Scaling milestones (M19+) add a smoke check that the new concurrency/store
paths are wired end to end:

```sh
uv run hound batch --logs tests/fixtures --output-dir .audit-scale-check --offline --jobs 2
uv run hound analyze tests/fixtures --output-dir .audit-scale-check2 --offline --jobs 2
rg "is_duplicate_of" .audit-scale-check/summary-*.json   # must exist
```

Cost-control milestones add a smoke check for reuse + budget telemetry:

```sh
uv run hound batch --logs tests/fixtures --output-dir .audit-cost-check --offline \
  --max-llm-calls 1 --jobs 2
rg '"usage"' .audit-cost-check/summary-*.json            # per-row usage present
rg 'llm_calls' .audit-cost-check/usage-*.json            # telemetry present
```

Budget-skipping (`budget_skipped`) only activates when real LLM calls consume
the limit; offline/failing-LLM runs never spend, so the guardrail stays silent.

## Drift rule

If the implementation diverges from PRD/ARCHITECTURE by more than ~20% (new module, changed schema, new CLI flag):

1. Stop.
2. Update `docs/prd.md` / `docs/architecture.md` / the relevant file in `docs/plans/`.
3. Then continue.

Do not ship code that contradicts the docs.

## CI policy

- Tests never call a live LLM API.
- `analyze` exits `0` when no recognized failure is found, `1` when analysis finds a CI/CD/build/test failure, `2` for invalid input/config, and `3` for internal errors. LLM failure may still use local fallback.
- Any test that would need network is written against fixtures only.
