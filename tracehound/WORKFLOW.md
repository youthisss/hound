# WORKFLOW — tracehound

Process rules to keep the project linear. Deviations require updating this file, PRD.md, or TODO.md **first**.

## Repo context

- Works inside monorepo at `/mnt/d/project/tracehound/`.
- Do not touch files outside `tracehound/`.
- Package name `tracehound`, import module `tracehound`.

## Change flow (strict order)

1. Docs → 2. Scaffold → 3. ingest → 4. analyze → 5. triage → 6. output → 7. cli → 8. tests → 9. verify.

Within each stage: **one area at a time**. Never edit two modules in parallel; finish + test one before starting the next.

### Definition of done (per task)
- Code written matching ARCHITECTURE.md contracts.
- Unit tests for the module (or pipeline coverage where noted in TODO.md).
- `uv run pytest` green.
- No "TODO" reference to the module remains in other files.

## Git / commit rules

- Commit at stage boundaries (one commit per milestone in TODO.md).
- Messages: conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), subject ≤ 72 chars.
- Never commit `.env`, API keys, or out-dir artifacts.
- Stage only files under `tracehound/`.

## Verify gate (before any milestone is "done")

```sh
uv run pytest
uv run hound analyze tests/fixtures --offline
uv run hound log -- pytest -q
```

Tests must exit 0. Fixture analysis exits 1 when failures are detected. Log collector preserves child command exit. Same-input offline runs must produce identical `dedup_key`.

Production-readiness milestones (M11+) add:

```sh
uv run hound analyze --log tests/fixtures/pytest_fail.log --offline --out /tmp/th_redact_check
rg "sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]" /tmp/th_redact_check   # must find nothing
```

Redaction default is on; any secret pattern in `--out` artifacts fails the gate.

## Drift rule

If the implementation diverges from PRD/ARCHITECTURE by more than ~20% (new module, changed schema, new CLI flag):

1. Stop.
2. Update PRD.md / ARCHITECTURE.md / TODO.md.
3. Then continue.

Do not ship code that contradicts the docs.

## CI policy

- Tests never call a live LLM API.
- `analyze` exits `0` when no recognized failure is found, `1` when analysis finds a CI/CD/build/test failure, `2` for invalid input/config, and `3` for internal errors. LLM failure may still use local fallback.
- Any test that would need network is written against fixtures only.
