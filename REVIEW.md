# Code Review — Hound Agent

Review date: 2026-08-07 (rev 3)
Scope: full codebase (`hound_agent/`, `tests/`, tooling)
Baseline: 75 tests pass (`pytest -q`), v0.1.0
Prior: rev 2 (2026-08-06) — all rev-2 findings resolved

## Summary

Hound Agent is a Python CLI for auto-investigating CI/build/test failures:
ingest log → parse stacktrace + git context → root-cause analysis (LLM with
deterministic fallback) → triage (severity, component, dedup) → output
`report.json`/`report.md` + draft ticket, optionally file to GitHub issue.
Interactive TUI (`hound tui`) via Textual also available.

Pipeline is solid, modular, well-tested. Rev-2 fixes addressed all prior
HIGH/MEDIUM items. This rev-3 review examines the post-fix codebase for
remaining issues, new code introduced by fixes, and architectural concerns.

**Recommendation: COMMENT** — no blocking bugs. 2 HIGH items should be
addressed before production use; remaining items are design improvements.

**Architectural Status: WATCH** — clean stage boundaries, but LLM-merge
semantics and lock mechanism need attention before scaling.

## What's good

1. **Clean architecture.** `ingest/` → `analyze/` → `triage/` → `output/`
   separation, one responsibility per file, linear flow in `pipeline.py`
   (single entry point shared by CLI and TUI).
2. **Robust fallback.** `analyze/fallback.py` guarantees output when LLM
   is down; `engine` tag (`llm` vs `fallback`) makes provenance transparent.
3. **Persistent dedup.** SHA256 fingerprint + state file cross-run; flaky
   detection (count ≥ 3) works across sessions and in batch. State growth
   capped at 1000 entries. Atomic write via `os.replace`.
4. **Good testing.** 75 tests, realistic fixtures, LLM and GitHub API
   mocked, end-to-end offline tests and TUI headless tests via `run_test()`.
5. **Schema v1.0 + `validate()`.** Schema enforced on every pipeline run
   before output is written.
6. **Security improvements.** `yaml.safe_load`, HTTPS enforcement for
   `GH_API_BASE`, untrusted-data delimiters for log content in LLM prompt,
   code-fence stripping in LLM JSON response, `ensure_ascii=False` consistent.
7. **Provider flexibility.** 8 presets with `default_model` per provider,
   clean precedence ladder (CLI > YAML > TH_* > provider env > OPENAI_*
   fallback > preset default), unknown provider warning.

## Findings (ordered by severity)

### CRITICAL (0)
(none)

### HIGH (2)

#### 1. `triage/dedup.py:43-57` — Lock silent fallthrough on acquisition failure

```python
for _ in range(10):
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.close(fd)
        break
    except OSError:
        import time
        time.sleep(0.05)
yield  # ← executes even if lock was never acquired
```

If all 10 retries fail (0.5s total), `yield` executes without lock. Concurrent
batch processes proceed unprotected → lost-update on `state.json`.

**Risk**: Dedup state corruption, incorrect flaky detection, lost GH filing
state under concurrent CI.

**Fix**: Track acquisition status. Raise `RuntimeError` or fall back to
no-dedup mode with stderr warning:

```python
acquired = False
for _ in range(10):
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.close(fd)
        acquired = True
        break
    except OSError:
        import time
        time.sleep(0.05)
if not acquired:
    sys.stderr.write(f"Warning: could not acquire lock {lock_path}, proceeding unlocked\n")
yield
```

Additionally: stale lockfile from process crash blocks all future runs. Write
PID to lockfile, check liveness on acquisition failure, or remove locks
older than 60s.

#### 2. `analyze/prompts.py:41` — Prompt injection: delimiter is defeatable

```python
lines.append("<untrusted_log_data>")
lines.append(artifacts.log_text[-12000:])
lines.append("</untrusted_log_data>")
```

XML-style delimiters provide weak isolation. Attacker-crafted log content
can include `</untrusted_log_data>` followed by override instructions,
breaking out of the data boundary.

**Risk**: Malicious CI log content could manipulate LLM output — changed
hypothesis, fake confidence, poisoned ticket content via `--gh`.

**Fix**: Use a random nonce boundary (e.g., `BOUNDARY_{uuid4().hex[:16]}`),
strip any occurrences of the boundary from log text before insertion, and
instruct the system prompt to treat everything between boundaries as raw
data. Or encode log content as base64 with explicit decode instruction.

### MEDIUM (7)

#### 3. `config.py:141` — Legacy `OPENAI_BASE_URL` overrides non-openai provider preset

When provider is `gemini` and `OPENAI_BASE_URL` is also set in env (common
in developer environments), `OPENAI_BASE_URL` overrides Gemini's preset
URL because it sits before `preset.get("base_url")` in the precedence chain.
Result: Gemini API key sent to OpenAI URL.

**Fix**: Apply `OPENAI_BASE_URL`/`OPENAI_MODEL`/`OPENAI_API_KEY` fallbacks
only when `provider == "openai"`:

```python
if provider == "openai":
    api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
    base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    model = model or os.environ.get("OPENAI_MODEL")
```

#### 4. `analyze/rca.py:26-49` — LLM merge hides source attribution

`_merge_llm` uses fallback evidence as base, appends LLM evidence, but
LLM hypothesis/fix replace fallback wholesale. Engine tagged `"llm"` even
though evidence is mixed. Downstream consumers (ticket, report) can't
distinguish deterministic facts from LLM claims.

**Risk**: Hallucinated hypothesis appears authoritative. No way to audit
LLM quality over time or compare LLM vs fallback accuracy.

**Fix**: Tag evidence items with source (`"[rule] ..."` vs `"[llm] ..."`),
or use engine value `"merged"` when both contribute. Consider separate
`llm_hypothesis` / `fallback_hypothesis` fields.

#### 5. `tui.py:346,358` — Double worker nesting in TUI analyze

`action_analyze` calls `run_worker(self._analyze(...))` (line 346). Inside
`_analyze`, another `run_worker(lambda: analyze(...), thread=True)` (line
358). Two worker layers for one operation; exception handling from outer
worker may swallow errors.

**Fix**: Remove outer `run_worker` — `_analyze` is already async, call it
directly or use `self.call_later`. Or remove inner `run_worker` if outer
is sufficient.

#### 6. `tui.py:75` — `_fmt_age` uses naive `datetime.now()` vs UTC `st_mtime`

`datetime.now().timestamp()` uses local time; `st_mtime` is UTC epoch.
Result: file age display off by timezone offset.

**Fix**: Use `time.time()`: `age = time.time() - p.stat().st_mtime`.

#### 7. `analyze/fallback.py:62-68` + `triage/severity.py:14-19` — Duplicate path-matching logic

Same path normalization + matching logic duplicated in `PathLike.in_changed`
and `_frame_hits_changed_file`. Bug fixes in one place missed in the other.

**Fix**: Extract shared `path_matches(file: str, changed: set[str]) -> bool`
utility. Both modules import from it.

#### 8. `config.py:128` — YAML config can contain `api_key` in cleartext

`llm_cfg.get("api_key")` reads API key from YAML. If config is committed
to version control, key leaks.

**Risk**: Credential exposure. YAML files commonly committed.

**Fix**: Log warning when api_key originates from YAML. Document that YAML
should never contain secrets. Better: refuse to read `api_key` from YAML,
accept only via env vars.

#### 9. `config.py` — No validation on YAML numeric config values

`temperature`, `timeout`, `max_tokens` from YAML not validated. Negative
temperature, zero timeout, or string values cause cryptic downstream errors.

**Fix**: Bounds check: `0.0 <= temperature <= 2.0`, `timeout > 0`,
`max_tokens > 0`. Raise `ValueError` with descriptive message.

### LOW (8)

#### 10. `dedup.py:44-61` — Stale lockfile from crash blocks future runs

If process crashes between lock creation and `finally` cleanup, lockfile
persists forever. No PID check or age-based cleanup.

**Fix**: Write PID to lockfile. On failure, check if PID is alive. Or
remove locks older than 60s.

#### 11. `cli.py:24` — `--api-key` CLI arg visible in process list

`--api-key` flag exposes secret in `ps aux` / `/proc/*/cmdline`.

**Fix**: Document risk. Prefer env var or YAML config for secrets.

#### 12. `cli.py:241-244` — Dead code: `_unique_stem` wrapper never called

`_unique_stem` wraps `_unique_stem_fast` but no caller uses it.

**Fix**: Remove.

#### 13. `severity.py:23` — `root_cause` param in `classify()` never used

All callers (and tests) pass it, but function body never reads it. Dead
interface surface.

**Fix**: Remove parameter, or use it (adjust severity based on confidence).

#### 14. `config.py:22-25` — Anthropic preset URL is not OpenAI-compatible

Anthropic preset `base_url: "https://api.anthropic.com/v1"` used with
`openai.OpenAI(...)` client. Anthropic native API != OpenAI-compatible.
Only works with proxy.

**Fix**: Add note that Anthropic preset requires an OpenAI-compatible proxy,
or remove preset.

#### 15. Magic numbers scattered without named constants

`prompts.py:41` (`12000`), `tui.py:43` (`256 * 1024`),
`dedup.py:23` (`1000`). `pipeline.py:20` (`READ_LIMIT`) is properly named.

**Fix**: Define named constants with docstrings for all size limits.

#### 16. `ingest/git.py:30,34,39,43` — Bare `except Exception: pass` hides errors

Git info silently incomplete when exceptions occur. User gets degraded
results with no indication.

**Fix**: Log warnings via `sys.stderr.write()` for suppressed exceptions.

#### 17. `cli.py:11` — `Ticket` imported from `output.tickets` instead of canonical `models`

`Ticket` dataclass lives in `hound_agent.models` but imported via
`hound_agent.output.tickets` (re-export). Architecturally misleading.

**Fix**: Import from `hound_agent.models` directly.

### INFO (2)

#### 18. `ingest/logs.py:41-48` — `detect_stage`/`detect_kind` priority collision

`TEST_MARKERS` checked before `BUILD_MARKERS`. Mixed logs get `stage="test"`
even if build failed. Not a bug with current fixtures. Noted since rev 2.

#### 19. `pipeline.py:94` + `dedup.py:92-124,159-172` — 3-4 lock-load-save cycles per analysis

One `analyze()` call triggers `check_duplicate` (lock+load+save) then
`record_triage` (lock+load+save), plus optional `mark_filed`. In batch
with 100 logs → 300+ file I/O ops on same file.

**Recommendation**: Consolidate into one lock-load-modify-save cycle.

## Statistics

- Source files: 17 production (incl. `pathutil.py`) + 17 test files
- Fixtures: 10 (`pytest_fail`, `flaky`, `build_error`, `stacktrace`,
  `import_error`, `timeout`, `segfault`, `npm_build_error`, `ci_generic`,
  `mixed_build_test`)
- Tests: **93 passed** (81 prior + 12 fixture coverage)
- Version: 0.1.0, schema RCA v1.0
- Python >= 3.10, deps: openai, gitpython, pyyaml, textual (dev: pytest)

## Priority recommendations

1. Fix lock silent fallthrough (#1) + stale lockfile (#10) — prevents state
   corruption under concurrent CI.
2. Strengthen prompt injection delimiter (#2) — nonce boundary or base64.
3. Fix OPENAI_* legacy fallback scope (#3) — prevents key/URL mismatch.
4. Tag merged evidence sources (#4) — enables LLM quality auditing.
5. Clean up TUI double worker (#5) + timezone (#6) — minor but easy.
6. Extract shared path-matching (#7) — reduces duplication.

## Resolved (rev 2 → rev 3 carryover)

| # | Finding | Status |
|---|---------|--------|
| R1 | `llm_enabled` only checked `api_key` | Fixed — checks `api_key OR base_url` |
| R2 | Race condition state dedup | Fixed — atomic write + lock mechanism (lock itself has caveats, see #1) |
| R3 | Markdown ticket not escaped in `report.md` | Fixed — blockquote rendering |
| R4 | Dead import `yaml` in `report.py` | Fixed — removed |
| R5 | Priority only 4 of range 1–5 | Fixed — `flaky_suspect` → priority 5 |
| R6 | Log read without limit | Fixed — 2MB tail read via seek |
| R7 | `detect_stage`/`detect_kind` ordering | INFO — unchanged, acceptable |
| R8 | `run_analyze` stdout empty + `run_batch` crash | Fixed — `_print_result` placement correct |
| R9 | LLM client crash not caught as LlmError | Fixed — wrapped in try/except |
| R10 | Prompt injection: raw log in prompt | Fixed — delimiters added (could be stronger, see #2) |
| R11 | Config precedence inconsistent with docs | Fixed — clean ladder |
| R12 | `yaml: null` / non-dict YAML handling | Fixed — safe fallback |
| R13 | Unknown provider silent remap | Fixed — stderr warning |
| R14 | Unused `asdict` import in dedup | Fixed — removed |
| R15 | `ensure_ascii` inconsistency | Fixed — `False` everywhere |
| R16 | GH_API_BASE non-HTTPS token leak | Fixed — HTTPS enforced |
| R17 | Code fence breaks in ticket/report | Fixed — escaped |
| R18 | GitPython `Repo` not closed | Fixed — `finally: repo.close()` |
| R19 | Windows path normalization | Fixed — `\` → `/` in matching |
| R20 | DEFAULT_MODELS duplicated in tui.py | Fixed — derived from config.PROVIDERS |
| R21 | Textual markup escaping in log display | Fixed — `escape()` applied |
| R22 | Large file seek-tail read | Fixed — pipeline + TUI |

## Synthesis

- **Code-reviewer lane**: COMMENT (0 CRITICAL, 2 HIGH, 7 MEDIUM, 8 LOW)
- **Architect lane**: WATCH (clean boundaries, concerns on merge semantics + lock)
- **Final**: COMMENT — no blocking bugs, ship with awareness of #1 and #2

## Resolved (rev 3 → rev 4)

All rev-3 findings fixed 2026-08-07. Test count: **81 passed** (75 + 6 new).

| # | Finding | Fix |
|---|---------|-----|
| 1 | Lock silent fallthrough on acquisition failure | `_state_lock` raises `RuntimeError` if lock not acquired after retries |
| 2 | Prompt injection: weak `<untrusted_log_data>` delimiter | Random `TRACEHOUND_BOUNDARY_<hex16>` nonce; boundary stripped from log text; system prompt treats boundary region as raw data |
| 3 | `OPENAI_BASE_URL` hijacked non-openai provider | Legacy `OPENAI_*` fallbacks applied only when `provider == "openai"` |
| 4 | LLM merge hid source attribution | Evidence tagged `[rule]`/`[llm]`; new `merged` engine when both contribute (`ENGINES` schema updated) |
| 5 | TUI double worker nesting | Single coroutine worker + inner thread worker; `_analyzing` guard prevents concurrent runs |
| 6 | `_fmt_age` timezone bug | `time.time()` replaces `datetime.now().timestamp()` |
| 7 | Duplicate path-matching logic | Extracted shared `hound_agent/pathutil.py:path_matches()`, used by fallback + severity |
| 8 | YAML api_key cleartext risk | Stderr warning when key read from YAML |
| 9 | YAML numeric config unvalidated | Bounds validation: temp `[0,2]`, timeout `>0`, max_tokens `>0` with `ValueError` |
| 10 | Stale lockfile blocks future runs | PID written to lock; stale detection (dead PID or >60s) removes lock on retry |
| 11 | `--api-key` visible in process list | Help text documents risk, recommends env/YAML |
| 12 | Dead `_unique_stem` wrapper | Removed |
| 13 | `classify()` unused `root_cause` param | Removed param; callers + tests updated |
| 14 | Anthropic preset misleading | Comment documents proxy requirement |
| 15 | Magic numbers scattered | Named constants: `LOG_TEXT_LIMIT` (prompts), `RAW_LIMIT` (tui), `MAX_STATE_ENTRIES` (dedup) |
| 16 | Bare `except Exception: pass` in git.py | `_warn()` writes context to stderr |
| 17 | `Ticket` imported via `output.tickets` | Imported from canonical `hound_agent.models` |

### New tests added

- `test_prompt_nonce_delimiter` — forged boundary cannot equal real nonce
- `test_openai_base_url_does_not_hijack_other_provider` — gemini preset immune to `OPENAI_BASE_URL`
- `test_config_numeric_validation` — bad temperature raises `ValueError`
- `test_yaml_api_key_warns` — YAML key triggers stderr warning
- `test_stale_lock_removed` — dead-PID/old lockfile doesn't block dedup
- `test_path_matches_windows_separators` — `path_matches` normalizes `\` vs `/`

## Resolved (rev 4 → rev 5) — v0.2.0 production-readiness pass

Review date: 2026-08-07 (rev 5). Scope: 6-pillar production hardening.
Test count: **118 passed** (93 + 25 in `tests/test_production.py`).

| Area | Change |
|------|--------|
| Security | `ingest/redact.py` — secret/PII redaction, on by default, `meta.redacted`; nonce-boundary injection guard (already rev-4) unchanged |
| Intelligence | opt-in `attach_snippets` (±2 lines/frame) → prompt + report; bounded full-log marker scan with head/tail context |
| Reliability | LLM exponential-backoff retries + `meta.usage`; locked file dedup store (HTTP disabled pending conditional writes) |
| Integrations | Jira + GitLab REST, Slack webhook; `hound server` (stdlib HTTP, /analyze + /health) |
| Config | explicit `--config`; repository-local config is not trusted automatically |
| Packaging | `Dockerfile`, `.dockerignore`, `action.yml`, pyproject v0.2.0 |
| Schema | v1.1 (additive): `StackFrame.code`, `meta.redacted`, `meta.usage` |

### New findings

1. **server.py uses bearer authentication** and only binds loopback HTTP;
   production exposure requires a TLS reverse proxy.
2. **`configure_store` is module-global state** — set per `analyze()` call in
   pipeline; safe for CLI/TUI/server, but concurrent HTTP-backend writers in the
   same process could interleave. Acceptable for the documented single-run model.
3. **HTTP dedup is disabled** until a conditional-write contract prevents
   multi-run lost updates.
4. **Redaction is regex-based, not entropy-based** — non-standard secrets
   (random 64-char hex tokens) may pass through. Heuristic scan left as future
   work; `--no-redact` gives operators an escape hatch.

### Priority recommendations

1. Put the webhook server behind TLS + auth before exposing beyond localhost.
2. Add an etag/conditional-PUT contract for the HTTP dedup store if concurrent
   runners hit the same bucket.
3. Consider entropy-based secret detection if logs routinely contain
   non-patterned tokens.

**Final (rev 5): APPROVE** — no blocking bugs; 118 tests green, verify gate
passes, redaction + server smoke verified.
