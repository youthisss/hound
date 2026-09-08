"""Bounded authenticated HTTP receiver for trusted local log roots."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
import contextlib
import hashlib
import hmac
import json
import os
import re
import socket
import sqlite3
import stat
import shutil
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from hound import service
from hound.config import load_config
from hound.operational_logging import configure_server_logging, server_logger
from hound.output.report import ensure_outdir
from hound.pathutil import path_has_symlink
from hound.pipeline import default_state_path
from hound.state_recovery import preserve_corrupt_sqlite
from hound.telemetry import telemetry
from hound.triage.dedup import _pid_alive as _dedup_pid_alive

DEFAULT_PORT = 8123
MAX_BODY_BYTES = 1024 * 1024
MAX_WORKERS = 4
MAX_QUEUED_JOBS = 64
MAX_CLIENT_CONNECTIONS = 16
CLIENT_READ_TIMEOUT_SECONDS = 15
JOB_TTL_SECONDS = 3600
RATE_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 60
MAX_TRACKED_CLIENTS = 1024
MAX_SERVER_LOG_BYTES = 16 * 1024 * 1024
COPY_CHUNK_BYTES = 64 * 1024
MAX_IDEMPOTENCY_KEY_BYTES = 128
MAX_ERROR_TEXT_BYTES = 512
MAX_OUTPUT_BYTES_PER_JOB = 32 * 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 256 * 1024
SERVER_SHUTDOWN_TIMEOUT_SECONDS = 10.0
LOG = server_logger()


def _bounded_text(value: object, limit: int = MAX_ERROR_TEXT_BYTES) -> str:
    """Return a safe, bounded diagnostic value for persistence and responses."""
    text = str(value).replace("\x00", "")
    return text[:limit]


def _job_error(exc: BaseException) -> dict[str, object]:
    """Map internal exceptions to a stable, non-sensitive job error contract."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return {"code": "analysis_timeout", "category": "analysis", "retryable": True}
    if isinstance(exc, (sqlite3.Error,)):
        return {"code": "persistence_unavailable", "category": "persistence", "retryable": True}
    if isinstance(exc, (FileNotFoundError, PermissionError, IsADirectoryError)):
        return {"code": "input_unavailable", "category": "input", "retryable": False}
    if isinstance(exc, ValueError):
        return {"code": "invalid_input", "category": "input", "retryable": False}
    if isinstance(exc, OSError):
        return {"code": "storage_error", "category": "persistence", "retryable": True}
    return {"code": "analysis_failed", "category": "analysis", "retryable": False}


def _consume_rate_token(
    buckets: dict[str, tuple[float, float]],
    client: str,
    capacity: int,
    now: float,
) -> bool:
    """Consume one token using a bounded, O(1)-state per-client bucket."""
    previous = buckets.get(client)
    if previous is None:
        buckets[client] = (now, float(max(capacity - 1, 0)))
        return capacity > 0
    updated_at, tokens = previous
    refill = (now - updated_at) * (capacity / RATE_WINDOW_SECONDS)
    tokens = min(float(capacity), max(0.0, tokens + max(refill, 0.0)))
    if tokens < 1.0:
        buckets[client] = (now, tokens)
        return False
    buckets[client] = (now, tokens - 1.0)
    return True


def _safe_input_message(exc: BaseException) -> str:
    """Keep validation responses useful without echoing arbitrary input."""
    message = _bounded_text(exc, 256)
    # Paths and parser details are not needed by an HTTP caller and can carry
    # local usernames, repository names, or injected terminal text.
    safe = message.replace("\r", " ").replace("\n", " ")
    return safe if safe else "invalid request"


def _request_hash(payload: dict) -> str:
    """Hash the canonical request body used by durable idempotency records."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_lock_pid(path: Path) -> int | None:
    try:
        with path.open("rb") as stream:
            first = stream.read(256).decode("ascii").splitlines()[0]
        name, value = first.split("=", 1)
        return int(value) if name == "pid" else None
    except (OSError, UnicodeDecodeError, IndexError, ValueError):
        return None


def _pid_is_alive(pid: int) -> bool:
    """Use the tested cross-platform PID probe shared with deduplication."""
    return _dedup_pid_alive(pid)


def _env_int(name: str, explicit: int | None, *, default: int, lo: int, hi: int) -> int:
    """Resolve a numeric server limit: explicit CLI arg wins, then env, then default."""
    candidate: int | str | None = explicit
    if candidate is None:
        candidate = os.environ.get(name)
        if candidate is None:
            legacy_name = name.replace("HOUND_", "TH_", 1)
            candidate = os.environ.get(legacy_name)
            if candidate is not None:
                sys.stderr.write(f"Warning: {legacy_name} is deprecated; use {name}.\n")
        if candidate is None or not str(candidate).strip():
            return default
    label = name.removeprefix("HOUND_SERVER_").lower()
    try:
        value = int(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer, got {candidate!r}") from exc
    if not lo <= value <= hi:
        raise ValueError(f"{label} must be in [{lo}, {hi}], got {value}")
    return value


class _JobStore:
    """SQLite-backed job registry. Safe for concurrent HTTP threads.

    Each operation opens its own short-lived connection (WAL + busy_timeout),
    so no thread state is shared and the store survives server restarts.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if path_has_symlink(self.path) or self.path.is_symlink():
            raise ValueError("server job store must not contain symlinked path components")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if path_has_symlink(self.path.parent) or self.path.is_symlink():
            raise ValueError("server job store must not contain symlinked path components")
        try:
            self._init_schema()
        except sqlite3.DatabaseError as exc:
            recovery = preserve_corrupt_sqlite(self.path)
            raise ValueError(f"job store is damaged; original preserved at {recovery}") from exc

    def _connect(self) -> sqlite3.Connection:
        if path_has_symlink(self.path) or self.path.is_symlink():
            raise ValueError("server job store must not contain symlinked path components")
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except Exception:
            conn.close()
            raise

    @contextlib.contextmanager
    def _session(self):
        """sqlite3 ``with conn`` commits/rolls back but does not close; ensure
        the file handle is always released so Windows never holds a lock."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id      TEXT PRIMARY KEY,
                    status  TEXT NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    report  TEXT NOT NULL DEFAULT '',
                    engine  TEXT NOT NULL DEFAULT '',
                    error   TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_category TEXT NOT NULL DEFAULT '',
                    retryable INTEGER NOT NULL DEFAULT 0,
                    request_id TEXT NOT NULL DEFAULT ''
                )"""
            )
            # Existing installations predate the diagnostic columns. SQLite
            # has no portable ``ADD COLUMN IF NOT EXISTS`` across supported
            # versions, so inspect the table and migrate each additive column.
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name, definition in (
                ("error_code", "TEXT NOT NULL DEFAULT ''"),
                ("error_category", "TEXT NOT NULL DEFAULT ''"),
                ("retryable", "INTEGER NOT NULL DEFAULT 0"),
                ("request_id", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS idempotency (
                    client_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    created REAL NOT NULL,
                    PRIMARY KEY (client_id, idempotency_key)
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_job ON idempotency(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated)")
            conn.commit()

    def create(self, job_id: str, status: str = "queued", *, request_id: str = "") -> None:
        now = time.time()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO jobs(id, status, created, updated, request_id) VALUES(?, ?, ?, ?, ?)",
                (job_id, status, now, now, _bounded_text(request_id, 64)),
            )
            conn.commit()

    def update(self, job_id: str, **fields) -> None:
        allowed = (
            "status", "updated", "report", "engine", "error", "error_code",
            "error_category", "retryable", "request_id",
        )
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        if "error" in updates:
            updates["error"] = _bounded_text(updates["error"])
        if "error_code" in updates:
            updates["error_code"] = _bounded_text(updates["error_code"], 64)
        if "error_category" in updates:
            updates["error_category"] = _bounded_text(updates["error_category"], 64)
        if "report" in updates:
            updates["report"] = _bounded_text(updates["report"], 1024)
        updates.setdefault("updated", time.time())
        clause = ", ".join(f"{key} = ?" for key in updates)
        with self._session() as conn:
            conn.execute(f"UPDATE jobs SET {clause} WHERE id = ?", (*updates.values(), job_id))
            conn.commit()

    def transition(self, job_id: str, expected_status: str, status: str, **fields) -> bool:
        """Atomically move one job through its lifecycle.

        A compare-and-set transition prevents a late worker or shutdown path
        from overwriting a terminal state written by another path.
        """
        fields["status"] = status
        fields["updated"] = time.time()
        allowed = {
            "status", "updated", "report", "engine", "error", "error_code",
            "error_category", "retryable", "request_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "error" in updates:
            updates["error"] = _bounded_text(updates["error"])
        if "error_code" in updates:
            updates["error_code"] = _bounded_text(updates["error_code"], 64)
        if "error_category" in updates:
            updates["error_category"] = _bounded_text(updates["error_category"], 64)
        if "report" in updates:
            updates["report"] = _bounded_text(updates["report"], 1024)
        clause = ", ".join(f"{key} = ?" for key in updates)
        with self._session() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET {clause} WHERE id = ? AND status = ?",
                (*updates.values(), job_id, expected_status),
            )
            conn.commit()
            return cursor.rowcount == 1

    def get(self, job_id: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("id", "status", "engine", "error_code", "error_category", "request_id"):
            result[key] = _bounded_text(result.get(key, ""), 128)
        result["report"] = _bounded_text(result.get("report", ""), 2048)
        result["error"] = _bounded_text(result.get("error", ""))
        return result

    def delete(self, job_id: str) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM idempotency WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()

    def cancel(self, job_id: str) -> bool:
        """Mark a queued/running job canceled using a compare-and-set update."""
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='canceled', error='canceled by client', "
                "error_code='job_canceled', error_category='lifecycle', retryable=0, updated=? "
                "WHERE id=? AND status IN ('queued','running')",
                (time.time(), job_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    def idempotency(self, client_id: str, key: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT client_id, idempotency_key, request_hash, job_id, created "
                "FROM idempotency WHERE client_id = ? AND idempotency_key = ?",
                (client_id, key),
            ).fetchone()
        return dict(row) if row is not None else None

    def reserve_idempotency(
        self,
        client_id: str,
        key: str,
        request_hash: str,
        job_id: str,
    ) -> bool:
        try:
            with self._session() as conn:
                conn.execute(
                    "INSERT INTO idempotency(client_id, idempotency_key, request_hash, job_id, created) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (client_id, key, request_hash, job_id, time.time()),
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_idempotency_for_job(self, job_id: str) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM idempotency WHERE job_id = ?", (job_id,))
            conn.commit()

    def all_ids(self) -> list[str]:
        with self._session() as conn:
            rows = conn.execute("SELECT id FROM jobs").fetchall()
        return [row["id"] for row in rows]

    def active_count(self) -> int:
        with self._session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()
        return int(row[0])

    def ready(self) -> bool:
        try:
            with self._session() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def counts(self) -> dict[str, int]:
        with self._session() as conn:
            row = conn.execute(
                """SELECT
                     SUM(CASE WHEN status='queued'    THEN 1 ELSE 0 END) AS queued,
                     SUM(CASE WHEN status='running'   THEN 1 ELSE 0 END) AS running,
                     SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                     SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) AS failed,
                     SUM(CASE WHEN status='canceled'  THEN 1 ELSE 0 END) AS canceled
                   FROM jobs"""
            ).fetchone()
        return {name: int(row[name] or 0) for name in row.keys()}

    def telemetry(self) -> dict[str, dict[str, int]]:
        with self._session() as conn:
            engines = conn.execute(
                "SELECT engine, COUNT(*) AS count FROM jobs WHERE engine != '' GROUP BY engine"
            ).fetchall()
            fallbacks = conn.execute(
                "SELECT error, COUNT(*) AS count FROM jobs "
                "WHERE status = 'completed' AND error != '' GROUP BY error"
            ).fetchall()
        return {
            "engines": {row["engine"]: int(row["count"]) for row in engines},
            "fallback_reasons": {row["error"]: int(row["count"]) for row in fallbacks},
        }

    def cleanup(self, ttl: float) -> list[str]:
        """Drop expired finished jobs and return their report paths."""
        cutoff = time.time() - ttl
        with self._session() as conn:
            rows = conn.execute(
                "SELECT id, report FROM jobs WHERE updated < ? AND status IN ('completed','failed','canceled') "
                "ORDER BY updated LIMIT 1000",
                (cutoff,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM idempotency WHERE job_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
            conn.commit()
        return [str(row["report"]) for row in rows if row["report"]]

    def mark_interrupted(self) -> None:
        """Jobs left queued/running by a previous process are marked failed."""
        with self._session() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = 'interrupted by server restart', "
                "error_code = 'server_restart', error_category = 'lifecycle', retryable = 1, updated = ? "
                "WHERE status IN ('queued','running')",
                (time.time(),),
            )
            conn.commit()

    def clear(self) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM idempotency")
            conn.execute("DELETE FROM jobs")
            conn.commit()


class ServerConfig:
    def __init__(
        self,
        token: str,
        log_root: str | Path,
        output_root: str | Path,
        repo_root: str | Path | None = None,
        analysis_options: dict | None = None,
        *,
        workers: int | None = None,
        max_queue: int | None = None,
        rate_limit: int | None = None,
        job_ttl: int | None = None,
    ):
        if not token:
            raise ValueError("server token is required")
        self.token = token
        raw_log_root = Path(log_root).expanduser()
        raw_output_root = Path(output_root).expanduser()
        raw_repo_root = Path(repo_root).expanduser() if repo_root else None
        for path, label in (
            (raw_log_root, "log root"),
            (raw_output_root, "output root"),
            (raw_repo_root, "repository root"),
        ):
            if path is not None and path_has_symlink(path):
                raise ValueError(f"server {label} must not contain symlinked path components")
        self.log_root = raw_log_root.resolve()
        self.output_root = raw_output_root.resolve()
        self.repo_root = raw_repo_root.resolve() if raw_repo_root else None
        self.analysis_options = analysis_options or {}
        self.workers = _env_int("HOUND_SERVER_WORKERS", workers, default=MAX_WORKERS, lo=1, hi=64)
        self.max_queue = _env_int("HOUND_SERVER_MAX_QUEUE", max_queue, default=MAX_QUEUED_JOBS, lo=1, hi=100000)
        self.rate_limit = _env_int("HOUND_SERVER_RATE_LIMIT", rate_limit, default=MAX_REQUESTS_PER_WINDOW, lo=1, hi=1000000)
        self.job_ttl = _env_int("HOUND_SERVER_JOB_TTL", job_ttl, default=JOB_TTL_SECONDS, lo=30, hi=86400)
        if not self.log_root.is_dir():
            raise ValueError(f"server log root is not a directory: {self.log_root}")
        ensure_outdir(self.output_root)
        config = load_config(
            offline=bool(self.analysis_options.get("offline", False)),
            config_path=self.analysis_options.get("config_path"),
            provider=self.analysis_options.get("provider"),
            model=self.analysis_options.get("model"),
            base_url=self.analysis_options.get("base_url"),
            api_key=self.analysis_options.get("api_key"),
            redact=self.analysis_options.get("redact"),
            max_retries=self.analysis_options.get("max_retries"),
            require_llm=self.analysis_options.get("require_llm"),
            source_class=self.analysis_options.get("source_class"),
        )
        self.analysis_config = replace(config, timeout=min(config.timeout, 30.0), max_retries=0)
        self.state_path = default_state_path(
            self.output_root,
            config.state_file,
            bool(self.analysis_options.get("no_dedup", False)),
            backend=config.state_backend,
        )
        # Jobs survive restarts. Recovery is performed by _Server only after it
        # owns the output-root lock, so another process cannot terminate work
        # belonging to a live server.
        jobs_path = self.output_root / ".hound" / "jobs.sqlite3"
        if path_has_symlink(jobs_path.parent) or jobs_path.is_symlink():
            raise ValueError("server job store must not be symlinked")
        self.jobs_store = _JobStore(jobs_path)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = MAX_CLIENT_CONNECTIONS

    def __init__(self, address, config: ServerConfig):
        self.config = config
        self.jobs_lock = threading.RLock()
        self.request_times: dict[str, tuple[float, float]] = {}
        self.unauthorized_times: dict[str, tuple[float, float]] = {}
        self.client_slots = threading.BoundedSemaphore(MAX_CLIENT_CONNECTIONS)
        self.cleanup_stop = threading.Event()
        self.accepting = True
        self._closed = False
        self._futures: set[Future[Any]] = set()
        self._running_jobs: set[str] = set()
        self._snapshots: dict[str, Path] = {}
        self._owner_fd: int | None = None
        self._owner_token = uuid4().hex
        self._owner_lock_path = config.output_root / ".hound" / "server.lock"
        self._release_after_shutdown = False
        self._acquire_owner_lock()
        try:
            self.executor = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="hound")
            self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
            super().__init__(address, _Handler)
            # Only the owner of this output root may recover jobs. This avoids
            # one process marking another process's work as interrupted.
            self.config.jobs_store.mark_interrupted()
            self.cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                name="hound_cleanup",
                daemon=True,
            )
            self.cleanup_thread.start()
        except Exception:
            self._release_owner_lock()
            raise

    def _acquire_owner_lock(self) -> None:
        if path_has_symlink(self._owner_lock_path.parent) or self._owner_lock_path.is_symlink():
            raise ValueError("server owner lock path must not be symlinked")
        self._owner_lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(self._owner_lock_path, flags, 0o600)
        except FileExistsError as exc:
            owner_pid = _read_lock_pid(self._owner_lock_path)
            if owner_pid is not None and not _pid_is_alive(owner_pid):
                try:
                    self._owner_lock_path.unlink()
                except OSError:
                    raise ValueError(
                        "server output root is already owned by another Hound server"
                    ) from exc
                return self._acquire_owner_lock()
            raise ValueError(
                "server output root is already owned by another Hound server; "
                "stop it or remove the lock after verifying the owner"
            ) from exc
        marker = (
            f"pid={os.getpid()}\n"
            f"started={time.time():.6f}\n"
            f"token={self._owner_token}\n"
        ).encode("ascii")
        try:
            written = 0
            while written < len(marker):
                written += os.write(fd, marker[written:])
        except OSError:
            os.close(fd)
            try:
                with self._owner_lock_path.open("rb") as stream:
                    current = stream.read(len(marker) + 1)
                if current == marker:
                    self._owner_lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        # The marker is deliberately closed after atomic creation. This keeps
        # ``hound clean`` cross-platform (Windows cannot delete open files)
        # while the PID-bearing marker still prevents a second owner.
        os.close(fd)
        self._owner_fd = None

    def _release_owner_lock(self) -> None:
        fd, self._owner_fd = self._owner_fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if path_has_symlink(self._owner_lock_path):
                return
            with self._owner_lock_path.open("rb") as stream:
                marker = stream.read(512).decode("ascii")
            if f"token={self._owner_token}" not in marker.splitlines():
                LOG.warning(
                    "owner lock changed before release; preserving replacement marker",
                    extra={"event": "owner_lock_replaced", "failure_category": "lifecycle"},
                )
                return
            self._owner_lock_path.unlink(missing_ok=True)
        except (OSError, UnicodeDecodeError):
            pass

    def cleanup_expired(self) -> None:
        try:
            expired_reports = self.config.jobs_store.cleanup(self.config.job_ttl)
            for report in expired_reports:
                _remove_expired_report(self.config.output_root, report)
        except sqlite3.Error:
            LOG.error("job store cleanup failed", extra={"event": "cleanup_failed", "failure_category": "persistence"})

    def _cleanup_loop(self) -> None:
        interval = min(60.0, max(1.0, self.config.job_ttl / 2))
        while not self.cleanup_stop.wait(interval):
            self.cleanup_expired()

    def process_request(self, request, client_address) -> None:
        if not self.accepting:
            request.close()
            return
        if not self.client_slots.acquire(blocking=False):
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.client_slots.release()

    def server_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.accepting = False
        LOG.info("server shutdown started", extra={"event": "shutdown_started"})
        if hasattr(self, "cleanup_stop"):
            self.cleanup_stop.set()
            self.cleanup_thread.join(timeout=5)
        if hasattr(self, "executor"):
            with self.jobs_lock:
                pending = [
                    (job_id, snapshot)
                    for job_id, snapshot in self._snapshots.items()
                    if job_id not in self._running_jobs
                ]
                for job_id, snapshot in pending:
                    snapshot.unlink(missing_ok=True)
                    self._snapshots.pop(job_id, None)
                futures = list(self._futures)
                for future in futures:
                    future.cancel()
            deadline = time.monotonic() + SERVER_SHUTDOWN_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                with self.jobs_lock:
                    if all(future.done() for future in self._futures):
                        break
                time.sleep(0.02)
            self.executor.shutdown(wait=False, cancel_futures=True)
            with self.jobs_lock:
                workers_stopped = all(future.done() for future in self._futures)
            if workers_stopped:
                try:
                    self.config.jobs_store.mark_interrupted()
                except sqlite3.Error:
                    pass
                self._release_owner_lock()
            else:
                # A Python thread cannot be safely killed. Keep the ownership
                # marker until the process exits rather than letting a second
                # server race a still-running worker against the same store.
                LOG.error(
                    "shutdown deadline reached with active analysis workers",
                    extra={"event": "shutdown_timeout", "failure_category": "analysis"},
                )
                self._release_after_shutdown = True
        super().server_close()
        LOG.info("server shutdown completed", extra={"event": "shutdown_completed"})

    def _forget_future(self, future: Future[Any]) -> None:
        release = False
        with self.jobs_lock:
            self._futures.discard(future)
            if self._release_after_shutdown and not self._futures:
                self._release_after_shutdown = False
                release = True
        if release:
            try:
                self.config.jobs_store.mark_interrupted()
            except sqlite3.Error:
                pass
            self._release_owner_lock()


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "Hound-Tracer/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(CLIENT_READ_TIMEOUT_SECONDS)
        self.request_id = uuid4().hex

    def _json(self, code: int, obj: dict) -> None:
        try:
            body = json.dumps(obj, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            body = b'{"error":"internal server error","code":"internal_error","retryable":false}'
            code = 500
        if len(body) > MAX_HTTP_RESPONSE_BYTES:
            body = b'{"error":"response too large","code":"response_too_large","retryable":false}'
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", self.request_id)
        self.end_headers()
        self.wfile.write(body)

    def _error(
        self,
        code: int,
        message: str,
        *,
        error_code: str,
        retryable: bool = False,
        allow: str | None = None,
    ) -> None:
        """Write the stable JSON error contract for every handled failure."""
        if allow:
            self.send_response(code)
            self.send_header("Allow", allow)
            payload = {
                "error": _bounded_text(message),
                "code": error_code,
                "request_id": self.request_id,
                "retryable": retryable,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", self.request_id)
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(code, {
            "error": _bounded_text(message),
            "code": error_code,
            "request_id": self.request_id,
            "retryable": retryable,
        })

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Replace BaseHTTPRequestHandler's HTML errors with safe JSON."""
        del explain
        messages = {
            400: "invalid request",
            401: "unauthorized",
            404: "not found",
            405: "method not allowed",
            413: "request body too large",
            429: "rate limit exceeded",
            500: "internal server error",
            501: "method not implemented",
            503: "service unavailable",
        }
        self._error(
            code,
            message or messages.get(code, "request failed"),
            error_code={
                400: "invalid_request",
                401: "unauthorized",
                404: "not_found",
                405: "method_not_allowed",
                413: "request_too_large",
                429: "rate_limited",
                500: "internal_error",
                501: "method_not_implemented",
                503: "service_unavailable",
            }.get(code, "request_failed"),
            retryable=code in {429, 500, 503},
        )

    def _target(self) -> tuple[str, str]:
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            self._error(400, "invalid request target", error_code="invalid_request")
            return "", ""
        if parsed.scheme or parsed.netloc:
            self._error(400, "absolute request targets are not supported", error_code="invalid_request")
            return "", ""
        return parsed.path or "/", parsed.query

    def _reject_query(self, query: str) -> bool:
        if query:
            self._error(
                400,
                "query parameters are not supported for this endpoint",
                error_code="unsupported_query",
            )
            return True
        return False

    def _method_not_allowed(self, allow: str) -> None:
        self._error(405, "method not allowed", error_code="method_not_allowed", allow=allow)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.config.token}"
        return hmac.compare_digest(supplied, expected)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        now = time.monotonic()
        client = self.client_address[0]
        with self.server.jobs_lock:
            self.server.unauthorized_times = {
                ip: values for ip, values in self.server.unauthorized_times.items()
                if now - values[0] < RATE_WINDOW_SECONDS
            }
            if client not in self.server.unauthorized_times and len(self.server.unauthorized_times) >= MAX_TRACKED_CLIENTS:
                self.server.unauthorized_times.pop(next(iter(self.server.unauthorized_times)))
            limited = not _consume_rate_token(
                self.server.unauthorized_times,
                client,
                self.server.config.rate_limit,
                now,
            )
        self._error(
            429 if limited else 401,
            "rate limit exceeded" if limited else "unauthorized",
            error_code="rate_limited" if limited else "unauthorized",
            retryable=limited,
        )
        LOG.warning("request rejected", extra={"event": "request_rejected", "request_id": self.request_id,
                    "status": 429 if limited else 401, "failure_category": "authentication"})
        return False

    def _admit_request(self) -> bool:
        now = time.monotonic()
        client = self.client_address[0]
        self.server.cleanup_expired()
        with self.server.jobs_lock:
            self.server.request_times = {
                ip: values for ip, values in self.server.request_times.items()
                if now - values[0] < RATE_WINDOW_SECONDS
            }
            if client not in self.server.request_times and len(self.server.request_times) >= MAX_TRACKED_CLIENTS:
                self.server.request_times.pop(next(iter(self.server.request_times)))
            if not _consume_rate_token(
                self.server.request_times,
                client,
                self.server.config.rate_limit,
                now,
            ):
                self._error(429, "rate limit exceeded", error_code="rate_limited", retryable=True)
                LOG.warning("request rejected", extra={"event": "request_rejected", "request_id": self.request_id,
                            "status": 429, "failure_category": "rate_limit"})
                return False
        return True

    def do_GET(self) -> None:
        route, query = self._target()
        if not route:
            return
        if route.rstrip("/") == "/health":
            if self._reject_query(query):
                return
            self._json(200, {"status": "ok"})
            return
        if route.rstrip("/") == "/ready":
            if self._reject_query(query):
                return
            ready = self.server.config.jobs_store.ready() and os.access(self.server.config.output_root, os.W_OK)
            self._json(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
            return
        if not self._require_auth():
            return
        if not self._admit_request():
            return
        if self._reject_query(query):
            return
        if route.rstrip("/") == "/stats":
            try:
                counts = self.server.config.jobs_store.counts()
                analysis = self.server.config.jobs_store.telemetry()
            except sqlite3.Error:
                self._error(
                    503,
                    "job store unavailable",
                    error_code="persistence_unavailable",
                    retryable=True,
                )
                return
            telemetry.gauge("server_queue_depth", float(counts["queued"] + counts["running"]))
            self._json(200, {
                "jobs": counts,
                "analysis": analysis,
                "hound": telemetry.snapshot(),
            })
            return
        prefix = "/jobs/"
        if route.startswith(prefix):
            job_id = route[len(prefix):]
            if not job_id.isalnum() or len(job_id) != 32:
                self._error(404, "job not found", error_code="job_not_found")
                return
            try:
                job = self.server.config.jobs_store.get(job_id)
            except sqlite3.Error:
                self._error(
                    503,
                    "job store unavailable",
                    error_code="persistence_unavailable",
                    retryable=True,
                )
                return
            self._json(200, job) if job else self._error(404, "job not found", error_code="job_not_found")
            return
        self._error(404, "not found", error_code="not_found")

    def do_POST(self) -> None:
        route, query = self._target()
        if not route:
            return
        if route.rstrip("/") in {"/health", "/ready"}:
            self._method_not_allowed("GET")
            return
        if not self._require_auth():
            return
        if route.rstrip("/") != "/analyze":
            self._error(404, "not found", error_code="not_found")
            return
        if not self._admit_request():
            return
        if self._reject_query(query):
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_BODY_BYTES:
                raise ValueError("request body too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("log"), str):
                raise ValueError("'log' must be a relative path string")
            unknown = set(payload) - {"log", "repo", "offline"}
            if unknown:
                raise ValueError(f"unsupported request fields: {', '.join(sorted(unknown))}")
            if "offline" in payload and not isinstance(payload["offline"], bool):
                raise ValueError("'offline' must be a boolean")
            log_path = _contained_path(self.server.config.log_root, payload["log"])
            repo_path = self.server.config.repo_root
            if payload.get("repo") is not None:
                if repo_path is None or payload["repo"] != ".":
                    raise ValueError("repo selection is not allowed")
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            self._error(400, _safe_input_message(exc), error_code="invalid_request")
            return
        except OSError:
            self._error(503, "request body could not be read", error_code="storage_error", retryable=True)
            return

        idempotency_key = self._idempotency_key()
        if getattr(self, "_idempotency_invalid", False):
            return
        request_hash = _request_hash(payload)
        client_id = hashlib.sha256(self.server.config.token.encode("utf-8")).hexdigest()
        job_id = uuid4().hex
        # Capacity admission and reservation must be one process-local critical
        # section; otherwise parallel handlers can all observe the same free slot.
        try:
            with self.server.jobs_lock:
                if idempotency_key:
                    existing = self.server.config.jobs_store.idempotency(client_id, idempotency_key)
                    if existing is not None:
                        if existing["request_hash"] != request_hash:
                            self._error(409, "idempotency key was reused for a different request", error_code="idempotency_key_reused")
                            return
                        existing_job = self.server.config.jobs_store.get(existing["job_id"])
                        if existing_job is not None:
                            self._json(202, {"accepted": True, "job_id": existing["job_id"], "replayed": True})
                            return
                        self.server.config.jobs_store.delete_idempotency_for_job(existing["job_id"])
                if self.server.config.jobs_store.active_count() >= self.server.config.max_queue:
                    self._error(429, "server queue full", error_code="queue_full", retryable=True)
                    LOG.warning("request rejected", extra={"event": "queue_rejected", "request_id": self.request_id, "status": 429})
                    return
                self.server.config.jobs_store.create(job_id, status="queued", request_id=self.request_id)
                if idempotency_key and not self.server.config.jobs_store.reserve_idempotency(
                    client_id, idempotency_key, request_hash, job_id
                ):
                    existing = self.server.config.jobs_store.idempotency(client_id, idempotency_key)
                    self.server.config.jobs_store.delete(job_id)
                    if existing and existing["request_hash"] == request_hash:
                        self._json(202, {"accepted": True, "job_id": existing["job_id"], "replayed": True})
                    else:
                        self._error(409, "idempotency key was reused for a different request", error_code="idempotency_key_reused")
                    return
        except sqlite3.Error:
            try:
                self.server.config.jobs_store.delete(job_id)
            except sqlite3.Error:
                LOG.error(
                    "could not roll back failed job reservation",
                    extra={"event": "job_reservation_cleanup_failed", "request_id": self.request_id},
                )
            self._error(503, "job store unavailable", error_code="persistence_unavailable", retryable=True)
            return
        LOG.info("job created", extra={"event": "job_created", "request_id": self.request_id, "job_id": job_id})
        # Snapshot, submit, and future registration share the lifecycle lock.
        # Without this critical section shutdown could observe no future after
        # the database reservation but before the handler registered work,
        # release the owner lock, and allow a second server to race the job.
        with self.server.jobs_lock:
            if not self.server.accepting:
                self._drop_job(job_id)
                self._error(503, "server is shutting down", error_code="server_shutting_down", retryable=True)
                return
            try:
                log_path = _snapshot_log(self.server.config.log_root, log_path, self.server.config.output_root, job_id)
                self.server._snapshots[job_id] = log_path
            except FileNotFoundError:
                self._drop_job(job_id)
                self._error(404, "log not found", error_code="log_not_found")
                return
            except ValueError as exc:
                self._drop_job(job_id)
                self._error(400, _safe_input_message(exc), error_code="invalid_input")
                return
            except OSError:
                self._drop_job(job_id)
                self._error(503, "could not snapshot log", error_code="storage_error", retryable=True)
                return
            try:
                future = self.server.executor.submit(
                    self._run_job, job_id, log_path, repo_path,
                    bool(payload.get("offline", False)), self.request_id,
                )
            except RuntimeError:
                self._drop_job(job_id)
                self._error(503, "server is shutting down", error_code="server_shutting_down", retryable=True)
                return
            self.server._futures.add(future)
            # Register while holding the same lock used by shutdown. If the
            # work already completed, Future invokes the callback immediately
            # and the RLock makes the discard race-free.
            future.add_done_callback(self.server._forget_future)
        self._json(202, {"accepted": True, "job_id": job_id})

    def _idempotency_key(self) -> str:
        """Validate and return an optional bounded idempotency key.

        An absent header is represented by the empty string. Invalid headers
        write their response here and return ``""`` only to callers that do
        not need to continue; POST checks ``response_sent`` below.
        """
        value = self.headers.get("Idempotency-Key")
        if value is None:
            return ""
        value = value.strip()
        if not value:
            self._error(400, "Idempotency-Key must not be empty", error_code="invalid_idempotency_key")
            self._idempotency_invalid = True
            return ""
        try:
            length = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            length = MAX_IDEMPOTENCY_KEY_BYTES + 1
        if length > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            self._error(
                400,
                "Idempotency-Key is invalid or too long",
                error_code="invalid_idempotency_key",
            )
            self._idempotency_invalid = True
            return ""
        self._idempotency_invalid = False
        return value

    def do_PUT(self) -> None:
        self._unsupported_method()

    def do_PATCH(self) -> None:
        self._unsupported_method()

    def do_DELETE(self) -> None:
        route, query = self._target()
        if not route:
            return
        if not self._require_auth():
            return
        if not self._admit_request():
            return
        if self._reject_query(query):
            return
        prefix = "/jobs/"
        job_id = route[len(prefix):] if route.startswith(prefix) else ""
        if not job_id.isalnum() or len(job_id) != 32:
            self._error(404, "job not found", error_code="job_not_found")
            return
        try:
            job = self.server.config.jobs_store.get(job_id)
            if job is None:
                self._error(404, "job not found", error_code="job_not_found")
                return
            if not self.server.config.jobs_store.cancel(job_id):
                self._error(409, "job is already terminal", error_code="job_not_cancelable")
                return
        except sqlite3.Error:
            self._error(503, "job store unavailable", error_code="persistence_unavailable", retryable=True)
            return
        self._json(200, {"canceled": True, "job_id": job_id})

    def do_OPTIONS(self) -> None:
        self._unsupported_method()

    def _unsupported_method(self) -> None:
        route, _query = self._target()
        if not route:
            return
        if route.rstrip("/") in {"/health", "/ready"}:
            self._method_not_allowed("GET")
            return
        if not self._require_auth():
            return
        if route.rstrip("/") == "/analyze":
            self._method_not_allowed("POST")
        elif route.rstrip("/") == "/stats" or route.startswith("/jobs/"):
            self._method_not_allowed("GET")
        else:
            self._error(404, "not found", error_code="not_found")

    def _drop_job(self, job_id: str) -> None:
        with self.server.jobs_lock:
            snapshot = self.server._snapshots.pop(job_id, None)
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
            self.server.config.jobs_store.delete(job_id)

    def _run_job(self, job_id: str, log_path: Path, repo_path: Path | None, offline: bool, request_id: str) -> None:
        with self.server.jobs_lock:
            self.server._running_jobs.add(job_id)
        output = self.server.config.output_root / job_id
        try:
            if not self.server.config.jobs_store.transition(job_id, "queued", "running"):
                return
            LOG.info("job started", extra={"event": "job_started", "request_id": request_id, "job_id": job_id})
            options = dict(self.server.config.analysis_options)
            options.update(repo_dir=repo_path, offline=offline or bool(options.get("offline", False)))
            options["state_path"] = self.server.config.state_path
            options["_config"] = replace(
                self.server.config.analysis_config,
                offline=bool(options["offline"]),
            )
            doc = service.analyze_log(log_path, output, **options)
            report = output / "report.json"
            if not report.is_file() or report.stat().st_size > MAX_OUTPUT_BYTES_PER_JOB:
                raise ValueError("analysis output exceeds server limit")
            completed = self.server.config.jobs_store.transition(
                job_id,
                "running",
                "completed",
                report=str(output / "report.json"),
                engine=doc["meta"]["engine"],
                error=(doc["meta"].get("llm") or {}).get("fallback_reason") or "",
            )
            if completed:
                LOG.info("job completed", extra={"event": "job_completed", "request_id": request_id,
                         "job_id": job_id, "status": "completed"})
        except Exception as exc:
            details = _job_error(exc)
            LOG.error("analysis job failed", extra={"event": "job_failed", "request_id": request_id, "job_id": job_id,
                       "status": "failed", "failure_category": "analysis"})
            try:
                self.server.config.jobs_store.transition(
                    job_id,
                    "running",
                    "failed",
                    report=str(output / "report.json"),
                    error="analysis failed",
                    error_code=details["code"],
                    error_category=details["category"],
                    retryable=details["retryable"],
                )
            except sqlite3.Error:
                LOG.error(
                    "could not persist failed job state",
                    extra={"event": "job_persistence_failed", "request_id": request_id,
                           "job_id": job_id, "failure_category": "persistence"},
                )
        finally:
            try:
                log_path.unlink(missing_ok=True)
            except OSError:
                LOG.error(
                    "could not remove analysis snapshot",
                    extra={"event": "snapshot_cleanup_failed", "request_id": request_id,
                           "job_id": job_id, "failure_category": "persistence"},
                )
            with self.server.jobs_lock:
                self.server._running_jobs.discard(job_id)
                self.server._snapshots.pop(job_id, None)

    def log_message(self, fmt: str, *args) -> None:
        LOG.info("request completed", extra={"event": "request_completed", "request_id": self.request_id,
                 "method": self.command, "path": self.path.split("?", 1)[0]})


def _contained_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path.replace("\\", "/"))
    if candidate.is_absolute() or candidate.drive or candidate.anchor or any(
        part in {"", ".", ".."} for part in candidate.parts
    ) or re.match(r"^[A-Za-z]:", relative_path):
        raise ValueError("absolute paths are not allowed")
    unresolved = root / candidate
    if path_has_symlink(unresolved):
        raise ValueError("symlinked paths are not allowed")
    trusted_root = root.resolve()
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ValueError("path escapes configured root") from exc
    return resolved


def _snapshot_log(root: Path, path: Path, output_root: Path, job_id: str) -> Path:
    """Copy an admitted regular file before asynchronous analysis can race it."""
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_SERVER_LOG_BYTES:
        raise ValueError("log exceeds server size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    snapshot = output_root / f".incoming-{job_id}{path.suffix.lower()}"
    target_fd: int | None = None
    try:
        source_stat = os.fstat(fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > MAX_SERVER_LOG_BYTES:
            raise ValueError("log must be a regular file within the server size limit")
        with os.fdopen(fd, "rb", closefd=False) as source:
            target_fd = os.open(
                snapshot,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(target_fd, "wb") as target:
                target_fd = None
                _copy_limited(source, target, source_stat.st_size)
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(fd)
    return snapshot


def _copy_limited(source, target, size: int) -> None:
    """Copy only the bytes admitted by the source file descriptor snapshot."""
    remaining = size
    while remaining > 0:
        chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
        if not chunk:
            raise OSError("input changed while creating the analysis snapshot")
        target.write(chunk)
        remaining -= len(chunk)


def _remove_expired_report(output_root: Path, report: str) -> None:
    """Remove only a job-owned output directory below the configured root."""
    try:
        root = output_root.resolve()
        report_path = Path(report)
        if not report_path.is_absolute():
            return
        if path_has_symlink(report_path) or report_path.is_symlink():
            return
        job_dir = report_path.parent
        if job_dir.parent != root or report_path.name != "report.json":
            return
        if not re.fullmatch(r"[0-9a-f]{32}", job_dir.name, re.IGNORECASE):
            return
        if not job_dir.is_dir() or job_dir.is_symlink():
            return
        shutil.rmtree(job_dir)
    except (OSError, ValueError):
        return


def run_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, *, token: str | None = None, log_root: str | Path = ".", output_root: str | Path = "hound-server-output", repo_root: str | Path | None = None, **analysis_options) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("server only supports loopback HTTP; terminate TLS at a reverse proxy")
    log_level = analysis_options.pop("log_level", "info")
    log_format = analysis_options.pop("log_format", "text")
    configure_server_logging(log_level, log_format)
    workers = analysis_options.pop("workers", None)
    max_queue = analysis_options.pop("max_queue", None)
    rate_limit = analysis_options.pop("rate_limit", None)
    job_ttl = analysis_options.pop("job_ttl", None)
    config = ServerConfig(
        token or os.environ.get("HOUND_SERVER_TOKEN") or os.environ.get("TH_SERVER_TOKEN", ""),
        log_root,
        output_root,
        repo_root,
        analysis_options,
        workers=workers,
        max_queue=max_queue,
        rate_limit=rate_limit,
        job_ttl=job_ttl,
    )
    httpd = _Server((host, port), config)
    LOG.info("server listening", extra={"event": "server_started", "host": host, "port": port})
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def stop_server(_signum, _frame) -> None:
        LOG.info("termination signal received", extra={"event": "shutdown_requested"})
        threading.Thread(target=httpd.shutdown, name="hound_shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        httpd.server_close()
