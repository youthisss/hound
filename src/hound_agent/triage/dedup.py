"""Dedup via normalized fingerprint; persists across runs in a state store.

Two backends are supported:

- ``file`` (default): locked JSON array at ``<state_path>``. Bounded by
  ``MAX_STATE_ENTRIES`` (eviction keeps filed entries first).
- ``sqlite``: a WAL-mode SQLite database using atomic upserts (``ON
  CONFLICT ... RETURNING``). No whole-file rewrite, O(1) per incident, safe
  for concurrent workers, and bounded by ``max_entries``/``retention_days``.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from hound_agent.models import Artifacts, Triage

_REMOVE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?|"
    r"\b0x[0-9a-fA-F]+\b|"
    r"/tmp/[A-Za-z0-9_./-]+|"
    r"\[[^\]]*\]|"
    r":\d+[:,]?",
    re.IGNORECASE,
)

MAX_STATE_ENTRIES = 1000
DELIVERY_CLAIM_TTL_SECONDS = 300
_LOCK_RETRIES = 100
_LOCK_RETRY_DELAY = 0.05
_LOCK_STALE_SECONDS = 60.0
_HTTP_TIMEOUT = 15
_SQLITE_BUSY_TIMEOUT_MS = 5000
_SQLITE_PRUNE_EVERY = 64

_BACKEND = "file"
_STORE_URL = ""
_STORE_TOKEN = ""
_SQLITE_MAX_ENTRIES = 50000
_SQLITE_RETENTION_DAYS = 90
_prune_counter = 0


def configure_store(backend: str = "file", url: str = "", token: str = "", max_entries: int = 50000, retention_days: int = 90) -> None:
    """Select the state-store backend. ``file`` (default) or ``sqlite``.

    The ``http`` backend treats ``url`` as an S3-compatible blob: GET returns
    the current JSON list, PUT replaces it. For distributed CI runners with no
    shared filesystem. It stays disabled until conditional writes are
    supported because read-modify-write over HTTP can lose concurrent updates.
    """
    if backend not in {"", "file", "sqlite"}:
        if backend == "http":
            raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")
        raise ValueError(f"unsupported dedup backend: {backend!r}")
    global _BACKEND, _STORE_URL, _STORE_TOKEN, _SQLITE_MAX_ENTRIES, _SQLITE_RETENTION_DAYS
    _BACKEND = backend or "file"
    _STORE_URL = url or ""
    _STORE_TOKEN = token or ""
    if max_entries >= 1:
        _SQLITE_MAX_ENTRIES = int(max_entries)
    if retention_days >= 1:
        _SQLITE_RETENTION_DAYS = int(retention_days)


def _is_sqlite() -> bool:
    return _BACKEND == "sqlite"


def _is_http() -> bool:
    return _BACKEND == "http"


# ---------------------------------------------------------------- HTTP (disabled)


def _http_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _STORE_TOKEN:
        headers["Authorization"] = f"Bearer {_STORE_TOKEN}"
    return headers


def _http_get() -> list[dict]:
    if not _STORE_URL:
        return []
    try:
        from urllib.request import Request, urlopen

        req = Request(_STORE_URL, headers=_http_headers(), method="GET")
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        sys.stderr.write(f"Warning: dedup HTTP store GET failed: {exc}\n")
        return []


def _http_put(entries: list[dict]) -> None:
    if not _STORE_URL:
        return
    try:
        from urllib.request import Request, urlopen

        payload = json.dumps(entries).encode("utf-8")
        req = Request(_STORE_URL, data=payload, headers=_http_headers(), method="PUT")
        with urlopen(req, timeout=_HTTP_TIMEOUT):  # noqa: S310 - user-supplied store URL
            pass
    except Exception as exc:
        sys.stderr.write(f"Warning: dedup HTTP store PUT failed: {exc}\n")


# ---------------------------------------------------------------- shared helpers


def normalize(text: str) -> str:
    t = text.lower()
    t = _REMOVE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fingerprint(artifacts: Artifacts) -> str:
    parts: list[str] = [artifacts.kind]
    if artifacts.message:
        parts.append(normalize(artifacts.message))
    parts.extend(normalize(t.name) for t in artifacts.failed_tests[:5])
    parts.extend(f.function or "" for f in artifacts.frames[:3] if f.function)
    # A release failure in production must not suppress an independent staging
    # incident that happens to have the same tool message.
    if artifacts.stage == "deploy":
        deployment = artifacts.deployment
        parts.extend((deployment.platform, deployment.environment, deployment.namespace,
                      deployment.target, deployment.release, deployment.revision, deployment.artifact))
    key = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------- SQLite backend


def _sqlite_connect(path: str | os.PathLike) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # journal_mode needs a write lock during first-use initialization. Install
    # the busy handler first, then retry because Windows may still return BUSY
    # immediately while another connection is creating the database.
    conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    try:
        for attempt in range(_LOCK_RETRIES):
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                _sqlite_init(conn)
                return conn
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == _LOCK_RETRIES - 1:
                    raise
                time.sleep(_LOCK_RETRY_DELAY)
    except Exception:
        conn.close()
        raise
    raise RuntimeError("unreachable SQLite initialization state")


@contextlib.contextmanager
def _sqlite_session(path: str | os.PathLike):
    """sqlite3 ``with conn`` commits/rolls back but does not close; ensure the
    file handle is always released so Windows never holds a lock."""
    conn = _sqlite_connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _sqlite_init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS incidents (
            key        TEXT PRIMARY KEY,
            kind       TEXT NOT NULL DEFAULT '',
            message    TEXT NOT NULL DEFAULT '',
            component  TEXT NOT NULL DEFAULT '',
            title      TEXT NOT NULL DEFAULT '',
            count      INTEGER NOT NULL DEFAULT 1,
            last_seen  TEXT NOT NULL,
            created_at TEXT NOT NULL,
            filed      INTEGER NOT NULL DEFAULT 0,
            ticket_url TEXT NOT NULL DEFAULT '',
            deliveries TEXT NOT NULL DEFAULT '{}',
            claims     TEXT NOT NULL DEFAULT '{}',
            root_cause TEXT NOT NULL DEFAULT ''
        )"""
    )
    # Migration (schema v1.3): stores a root-cause snapshot for LLM reuse.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)").fetchall()}
    if "root_cause" not in columns:
        conn.execute("ALTER TABLE incidents ADD COLUMN root_cause TEXT NOT NULL DEFAULT ''")
        conn.commit()


def _sqlite_row_to_entry(row: sqlite3.Row) -> dict:
    entry = dict(row)
    entry["filed"] = bool(entry.get("filed"))
    entry["deliveries"] = _json_loads(entry.get("deliveries") or "{}")
    entry["claims"] = _json_loads(entry.get("claims") or "{}")
    entry["root_cause"] = _json_loads(entry.get("root_cause") or "") or None
    return entry


def load_sqlite_entries(state_path: str | os.PathLike) -> list[dict]:
    """Read all persisted incidents from a SQLite store (for tests/admin)."""
    with _sqlite_session(state_path) as conn:
        rows = conn.execute("SELECT * FROM incidents").fetchall()
    return [_sqlite_row_to_entry(row) for row in rows]


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _sqlite_prune(state_path: str | os.PathLike) -> None:
    """Opportunistic retention: drop delivered entries past retention_days,
    then keep the table under max_entries (delivered entries evicted first).
    """
    global _prune_counter
    _prune_counter += 1
    try:
        with _sqlite_session(state_path) as conn:
            if _prune_counter % _SQLITE_PRUNE_EVERY == 0:
                conn.execute(
                    "DELETE FROM incidents WHERE filed = 1 AND last_seen < ?",
                    (_iso_days_ago(_SQLITE_RETENTION_DAYS),),
                )
            total = int(conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])
            if total > _SQLITE_MAX_ENTRIES:
                excess = total - _SQLITE_MAX_ENTRIES
                conn.execute(
                    """DELETE FROM incidents WHERE key IN (
                           SELECT key FROM incidents
                           ORDER BY filed DESC, last_seen ASC
                           LIMIT ?
                       )""",
                    (excess,),
                )
            conn.commit()
    except sqlite3.Error as exc:
        sys.stderr.write(f"Warning: dedup SQLite prune failed: {exc}\n")


def _sqlite_check_duplicate(artifacts: Artifacts, state_path: str, recurrence_threshold: int) -> Triage:
    key = fingerprint(artifacts)
    triage = Triage(dedup_key=key, flaky_suspect=artifacts.kind == "flaky")
    now = _now()
    try:
        with _sqlite_session(state_path) as conn:
            row = conn.execute(
                """INSERT INTO incidents(key, kind, message, count, last_seen, created_at)
                   VALUES(?, ?, ?, 1, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       count = count + 1,
                       last_seen = excluded.last_seen
                   RETURNING count""",
                (key, artifacts.kind, (artifacts.message or "")[:200], now, now),
            ).fetchone()
            count = int(row[0])
            conn.commit()
    except sqlite3.Error as exc:
        sys.stderr.write(f"Warning: dedup SQLite update failed: {exc}\n")
        count = 1
    if count > 1:
        triage.is_duplicate_of = key
        triage.occurrence_count = count
        triage.recurring_incident = count >= recurrence_threshold
    _sqlite_prune(state_path)
    return triage


def _sqlite_is_already_filed(state_path: str, key: str, destination: str) -> bool:
    with _sqlite_session(state_path) as conn:
        row = conn.execute("SELECT filed, deliveries FROM incidents WHERE key = ?", (key,)).fetchone()
    if row is None:
        return False
    deliveries = _json_loads(row["deliveries"])
    if isinstance(deliveries, dict) and destination in deliveries:
        return True
    return destination == "github" and bool(row["filed"])


def _sqlite_mark_filed(state_path: str, key: str, url: str = "", destination: str = "github") -> bool:
    now = _now()
    with _sqlite_session(state_path) as conn:
        row = conn.execute(
            "SELECT filed, ticket_url, deliveries, claims FROM incidents WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return False
        deliveries = _json_loads(row["deliveries"])
        claims = _json_loads(row["claims"])
        deliveries[destination] = {"url": url, "delivered_at": now}
        claims.pop(destination, None)
        filed = 1 if destination == "github" else int(bool(row["filed"]))
        ticket_url = url if destination == "github" else row["ticket_url"]
        conn.execute(
            "UPDATE incidents SET deliveries = ?, claims = ?, filed = ?, ticket_url = ? WHERE key = ?",
            (_json_dumps(deliveries), _json_dumps(claims), filed, ticket_url, key),
        )
        conn.commit()
    return True


def _sqlite_claim_delivery(state_path: str, key: str, destination: str) -> bool:
    now = time.time()
    with _sqlite_session(state_path) as conn:
        row = conn.execute(
            "SELECT filed, deliveries, claims FROM incidents WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return False
        deliveries = _json_loads(row["deliveries"])
        if isinstance(deliveries, dict) and destination in deliveries:
            return False
        if destination == "github" and bool(row["filed"]):
            return False
        claims = _json_loads(row["claims"])
        claim = claims.get(destination)
        if isinstance(claim, dict):
            try:
                claimed_at = float(claim.get("claimed_at", 0))
            except (TypeError, ValueError):
                claimed_at = 0
            if now - claimed_at < DELIVERY_CLAIM_TTL_SECONDS:
                return False
        claims[destination] = {"claimed_at": now, "pid": os.getpid()}
        conn.execute(
            "UPDATE incidents SET claims = ? WHERE key = ?",
            (_json_dumps(claims), key),
        )
        conn.commit()
    return True


def _sqlite_release_delivery_claim(state_path: str, key: str, destination: str) -> bool:
    with _sqlite_session(state_path) as conn:
        row = conn.execute("SELECT claims FROM incidents WHERE key = ?", (key,)).fetchone()
        if row is None:
            return False
        claims = _json_loads(row["claims"])
        if destination not in claims:
            return False
        claims.pop(destination, None)
        conn.execute(
            "UPDATE incidents SET claims = ? WHERE key = ?",
            (_json_dumps(claims), key),
        )
        conn.commit()
    return True


def _sqlite_record_triage(
    state_path: str,
    triage: Triage,
    component: str,
    title: str,
    root_cause: str = "",
    artifacts: Artifacts | None = None,
) -> bool:
    if not triage.dedup_key:
        return False
    with _sqlite_session(state_path) as conn:
        conn.execute(
            """INSERT INTO incidents(
                   key, kind, message, component, title, count, last_seen, created_at, root_cause
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   component = excluded.component,
                   title = excluded.title,
                   root_cause = excluded.root_cause""",
            (
                triage.dedup_key,
                artifacts.kind if artifacts is not None else "",
                artifacts.message[:200] if artifacts is not None else "",
                component,
                title,
                max(triage.occurrence_count, 1),
                _now(),
                _now(),
                root_cause,
            ),
        )
        conn.commit()
    return True


def _sqlite_lookup_incident(state_path: str, key: str) -> dict | None:
    """Read one incident without incrementing its count (read-only lookup)."""
    with _sqlite_session(state_path) as conn:
        row = conn.execute("SELECT * FROM incidents WHERE key = ?", (key,)).fetchone()
    return _sqlite_row_to_entry(row) if row is not None else None


# ---------------------------------------------------------------- file backend


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness probe for a lock-owner PID.

    POSIX: ``kill(0)`` raises ``ProcessLookupError`` for a dead PID and
    ``PermissionError`` (EPERM) for a live one owned by another user.
    Windows: dead PIDs raise plain ``OSError`` (winerror 87 / EINVAL)
    instead of ``ProcessLookupError``, so those must map to "dead" too —
    otherwise a crashed process's lock can never be recovered.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a reliable liveness query on Windows: it
        # can succeed for an already reaped process. A waitable process handle
        # gives an explicit signaled (exited) versus timeout (running) result.
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            open_process.restype = ctypes.c_void_p
            wait_for_single_object = kernel32.WaitForSingleObject
            wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            wait_for_single_object.restype = ctypes.c_uint32
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_int

            handle = open_process(0x00100000, 0, pid)  # SYNCHRONIZE
            if not handle:
                # Access denied proves that a protected process exists. Other
                # failures (notably ERROR_INVALID_PARAMETER) mean no process.
                return ctypes.get_last_error() == 5
            try:
                result = wait_for_single_object(handle, 0)
                if result == 0:  # WAIT_OBJECT_0: process has exited
                    return False
                if result == 0x102:  # WAIT_TIMEOUT: process is still running
                    return True
                # Fail closed for lock recovery only when death is proven.
                return True
            finally:
                close_handle(handle)
        except (AttributeError, OSError):
            # Unexpected ctypes/platform failure falls back to the portable
            # best-effort probe below.
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror is not None:
            # ERROR_INVALID_PARAMETER: no such process on Windows.
            return winerror != 87
        return exc.errno not in {errno.ESRCH, errno.EINVAL}
    return True


def _is_stale_lock(lock_path: Path) -> bool:
    """True only when a lock owner is provably dead.

    Wall-clock age is not proof of death: a paused process can legitimately
    hold a lock longer than the old timeout.
    """
    try:
        pid_str = lock_path.read_text(encoding="utf-8", errors="ignore").strip().split(":", 1)[0]
        if pid_str.isdigit() and not _pid_alive(int(pid_str)):
            return True
    except OSError:
        return False
    return False


@contextlib.contextmanager
def _state_lock(state_path: str | os.PathLike):
    if _is_sqlite():
        # SQLite provides its own locking (WAL + busy_timeout); no local lock.
        yield
        return
    if _is_http():
        # Server-side store is responsible for its own consistency; no local lock.
        yield
        return
    lock_path = Path(state_path).with_suffix(".lock")
    acquired = False
    owner = f"{os.getpid()}:{uuid4().hex}"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(_LOCK_RETRIES):
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                try:
                    os.write(fd, owner.encode("utf-8"))
                finally:
                    os.close(fd)
                acquired = True
                break
            except (FileExistsError, PermissionError):
                # Windows can report ERROR_ACCESS_DENIED (PermissionError)
                # instead of EEXIST while another thread is mid-create/delete
                # of the lock file. Both mean "held", so retry.
                if _is_stale_lock(lock_path):
                    with contextlib.suppress(OSError):
                        lock_path.unlink()
                    continue
                time.sleep(_LOCK_RETRY_DELAY)
        if not acquired:
            raise RuntimeError(
                f"Could not acquire dedup lock {lock_path}; another process holds it"
            )
        yield
    finally:
        if acquired:
            for _ in range(_LOCK_RETRIES):
                try:
                    if lock_path.read_text(encoding="utf-8", errors="ignore").strip() == owner:
                        lock_path.unlink()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(_LOCK_RETRY_DELAY)


def load_state(path: str | os.PathLike) -> list[dict]:
    if _is_sqlite():
        return load_sqlite_entries(path)
    if _is_http():
        return _http_get()
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        backup = p.with_name(p.name + f".corrupt-{int(time.time())}")
        with contextlib.suppress(OSError):
            os.replace(p, backup)
            sys.stderr.write(f"Warning: corrupt dedup state moved to '{backup}': {exc}\n")
        return []
    except OSError:
        return []
    return data if isinstance(data, list) else []


def save_state(path: str | os.PathLike, entries: list[dict], keep_key: str | None = None) -> bool:
    if _is_sqlite():
        # SQLite writes flow through the atomic upsert operations; a bulk
        # save here is only used by tests/admin for file-shaped stores.
        return False
    if _is_http():
        _http_put(entries)
        return True
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Prefer filed entries, but keep the state strictly bounded.
        if len(entries) > MAX_STATE_ENTRIES:
            unbounded_entries = entries
            filed = sorted(
                (entry for entry in entries if _entry_delivered(entry)),
                key=lambda e: e.get("last_seen", ""),
                reverse=True,
            )
            unfiled = sorted(
                (entry for entry in entries if not _entry_delivered(entry)),
                key=lambda e: e.get("last_seen", ""),
                reverse=True,
            )
            # Reserve one slot for the newest undelivered failure so a full
            # archive of delivered entries cannot disable duplicate tracking.
            filed_limit = MAX_STATE_ENTRIES - 1 if unfiled else MAX_STATE_ENTRIES
            filed = filed[:max(filed_limit, 0)]
            entries = filed + unfiled[:MAX_STATE_ENTRIES - len(filed)]
            if keep_key and not any(entry.get("key") == keep_key for entry in entries):
                protected = next((entry for entry in unbounded_entries if entry.get("key") == keep_key), None)
                if protected is not None and entries:
                    # Preserve the just-updated key while evicting the oldest
                    # entry of the same delivery class where possible.
                    same_class = [
                        entry
                        for entry in entries
                        if _entry_delivered(entry) == _entry_delivered(protected)
                    ]
                    evicted = min(same_class or entries, key=lambda entry: entry.get("last_seen", ""))
                    entries.remove(evicted)
                    entries.append(protected)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(entries, stream, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            # os.fdopen owns the fd; the with-block already closed it on error.
            tmp.unlink(missing_ok=True)
            raise
        return True
    except OSError as exc:
        sys.stderr.write(f"Warning: Failed to save dedup state to '{path}': {exc}\n")
        return False


FLAKY_THRESHOLD = 3


def check_duplicate(artifacts: Artifacts, state_path: str | None, recurrence_threshold: int = FLAKY_THRESHOLD) -> Triage:
    key = fingerprint(artifacts)
    triage = Triage(dedup_key=key, flaky_suspect=artifacts.kind == "flaky")
    if not state_path:
        return triage
    if _is_sqlite():
        return _sqlite_check_duplicate(artifacts, state_path, recurrence_threshold)

    with _state_lock(state_path):
        entries = load_state(state_path)
        found = False
        for entry in entries:
            if entry.get("key") == key:
                found = True
                try:
                    count = int(entry.get("count", 1))
                except (TypeError, ValueError):
                    count = 1
                entry["count"] = max(count, 1) + 1
                entry["last_seen"] = _now()
                triage.is_duplicate_of = key
                triage.occurrence_count = entry["count"]
                triage.recurring_incident = entry["count"] >= recurrence_threshold
                break
        if not found:
            entries.append(
                {
                    "key": key,
                    "component": "",
                    "title": "",
                    "kind": artifacts.kind,
                    "message": artifacts.message[:200],
                    "count": 1,
                    "last_seen": _now(),
                    "filed": False,
                }
            )
        save_state(state_path, entries, keep_key=key)
    return triage


def is_already_filed(state_path: str | None, key: str, destination: str = "github") -> bool:
    """Return whether this failure was delivered to the selected integration."""
    if not state_path or not key:
        return False
    if _is_sqlite():
        return _sqlite_is_already_filed(state_path, key, destination)
    with _state_lock(state_path):
        entries = load_state(state_path)
        for entry in entries:
            if entry.get("key") == key:
                deliveries = entry.get("deliveries")
                if isinstance(deliveries, dict) and destination in deliveries:
                    return True
                return destination == "github" and bool(entry.get("filed"))
    return False


def mark_filed(state_path: str | None, key: str, url: str = "", destination: str = "github") -> bool:
    """Mark a dedup key as successfully delivered to one integration."""
    if not state_path or not key:
        return False
    if _is_sqlite():
        return _sqlite_mark_filed(state_path, key, url, destination)
    with _state_lock(state_path):
        entries = load_state(state_path)
        for entry in entries:
            if entry.get("key") == key:
                deliveries = entry.setdefault("deliveries", {})
                if not isinstance(deliveries, dict):
                    deliveries = {}
                    entry["deliveries"] = deliveries
                deliveries[destination] = {"url": url, "delivered_at": _now()}
                claims = entry.get("delivery_claims")
                if isinstance(claims, dict):
                    claims.pop(destination, None)
                if destination == "github":
                    entry["filed"] = True
                    if url:
                        entry["ticket_url"] = url
                return save_state(state_path, entries)
        return False


def claim_delivery(state_path: str | None, key: str, destination: str) -> bool:
    """Atomically reserve one integration delivery across local processes."""
    if not state_path or not key:
        return True
    if _is_sqlite():
        return _sqlite_claim_delivery(state_path, key, destination)
    now = time.time()
    with _state_lock(state_path):
        entries = load_state(state_path)
        for entry in entries:
            if entry.get("key") != key:
                continue
            deliveries = entry.get("deliveries")
            if isinstance(deliveries, dict) and destination in deliveries:
                return False
            if destination == "github" and entry.get("filed"):
                return False
            claims = entry.setdefault("delivery_claims", {})
            if not isinstance(claims, dict):
                claims = {}
                entry["delivery_claims"] = claims
            claim = claims.get(destination)
            if isinstance(claim, dict):
                try:
                    claimed_at = float(claim.get("claimed_at", 0))
                except (TypeError, ValueError):
                    claimed_at = 0
                if now - claimed_at < DELIVERY_CLAIM_TTL_SECONDS:
                    return False
            claims[destination] = {"claimed_at": now, "pid": os.getpid()}
            return save_state(state_path, entries)
    return False


def release_delivery_claim(state_path: str | None, key: str, destination: str) -> bool:
    if not state_path or not key:
        return False
    if _is_sqlite():
        return _sqlite_release_delivery_claim(state_path, key, destination)
    with _state_lock(state_path):
        entries = load_state(state_path)
        for entry in entries:
            if entry.get("key") == key and isinstance(entry.get("delivery_claims"), dict):
                entry["delivery_claims"].pop(destination, None)
                return save_state(state_path, entries)
        return False


def _entry_delivered(entry: dict) -> bool:
    return bool(entry.get("filed")) or bool(entry.get("deliveries"))


def record_triage(
    state_path: str | None,
    triage: Triage,
    component: str,
    title: str,
    root_cause: dict | None = None,
    artifacts: Artifacts | None = None,
) -> bool:
    """Persist triage metadata and its optional root-cause snapshot.

    A bounded store can evict an entry between ``check_duplicate`` and this
    call while analysis is running. Recreate that entry instead of silently
    losing the snapshot and spending another LLM call on the next occurrence.
    """
    if not state_path or not triage.dedup_key:
        return False
    snapshot = _json_dumps(root_cause) if root_cause else ""
    if _is_sqlite():
        return _sqlite_record_triage(state_path, triage, component, title, snapshot, artifacts)
    with _state_lock(state_path):
        entries = load_state(state_path)
        updated = False
        for entry in entries:
            if entry.get("key") == triage.dedup_key:
                entry["component"] = component
                entry["title"] = title
                if root_cause is not None:
                    entry["root_cause"] = root_cause
                updated = True
        if not updated:
            entries.append(
                {
                    "key": triage.dedup_key,
                    "component": component,
                    "title": title,
                    "kind": artifacts.kind if artifacts is not None else "",
                    "message": artifacts.message[:200] if artifacts is not None else "",
                    "count": max(triage.occurrence_count, 1),
                    "last_seen": _now(),
                    "filed": False,
                    **({"root_cause": root_cause} if root_cause is not None else {}),
                }
            )
        saved = save_state(state_path, entries, keep_key=triage.dedup_key)
        return saved and any(entry.get("key") == triage.dedup_key for entry in load_state(state_path))


def lookup_incident(state_path: str | None, key: str) -> dict | None:
    """Return the persisted incident entry for ``key`` without incrementing its
    count. ``None`` when the store has no such incident. Used by the reuse
    decision before the LLM is called."""
    if not state_path or not key:
        return None
    if _is_sqlite():
        return _sqlite_lookup_incident(state_path, key)
    with _state_lock(state_path):
        for entry in load_state(state_path):
            if entry.get("key") == key:
                return entry
    return None
