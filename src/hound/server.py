"""Bounded authenticated HTTP receiver for trusted local log roots."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import contextlib
import hmac
import json
import os
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
from uuid import uuid4

from hound import service
from hound.config import load_config
from hound.operational_logging import configure_server_logging, server_logger
from hound.output.report import ensure_outdir
from hound.pipeline import default_state_path
from hound.state_recovery import preserve_corrupt_sqlite
from hound.telemetry import telemetry

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
LOG = server_logger()


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._init_schema()
        except sqlite3.DatabaseError as exc:
            recovery = preserve_corrupt_sqlite(self.path)
            raise ValueError(f"job store is damaged; original preserved at {recovery}") from exc

    def _connect(self) -> sqlite3.Connection:
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
                    error   TEXT NOT NULL DEFAULT ''
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated)")
            conn.commit()

    def create(self, job_id: str, status: str = "queued") -> None:
        now = time.time()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO jobs(id, status, created, updated) VALUES(?, ?, ?, ?)",
                (job_id, status, now, now),
            )
            conn.commit()

    def update(self, job_id: str, **fields) -> None:
        allowed = ("status", "updated", "report", "engine", "error")
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates.setdefault("updated", time.time())
        clause = ", ".join(f"{key} = ?" for key in updates)
        with self._session() as conn:
            conn.execute(f"UPDATE jobs SET {clause} WHERE id = ?", (*updates.values(), job_id))
            conn.commit()

    def get(self, job_id: str) -> dict | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None

    def delete(self, job_id: str) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
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
                     SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) AS failed
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
                "SELECT report FROM jobs WHERE updated < ? AND status IN ('completed','failed')",
                (cutoff,),
            ).fetchall()
            conn.execute(
                "DELETE FROM jobs WHERE updated < ? AND status IN ('completed','failed')",
                (cutoff,),
            )
            conn.commit()
        return [str(row["report"]) for row in rows if row["report"]]

    def mark_interrupted(self) -> None:
        """Jobs left queued/running by a previous process are marked failed."""
        with self._session() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = 'interrupted by server restart', updated = ? "
                "WHERE status IN ('queued','running')",
                (time.time(),),
            )
            conn.commit()

    def clear(self) -> None:
        with self._session() as conn:
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
        self.log_root = Path(log_root).resolve()
        self.output_root = Path(output_root).resolve()
        self.repo_root = Path(repo_root).resolve() if repo_root else None
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
        # Jobs survive restarts; anything a previous process left running is
        # a zombie and must be marked failed before we accept new work.
        self.jobs_store = _JobStore(self.output_root / ".hound" / "jobs.sqlite3")
        self.jobs_store.mark_interrupted()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = MAX_CLIENT_CONNECTIONS

    def __init__(self, address, config: ServerConfig):
        self.executor = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="hound")
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)
        self.config = config
        self.jobs_lock = threading.Lock()
        self.request_times: dict[str, list[float]] = {}
        self.unauthorized_times: dict[str, list[float]] = {}
        self.client_slots = threading.BoundedSemaphore(MAX_CLIENT_CONNECTIONS)
        self.cleanup_stop = threading.Event()
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="hound_cleanup",
            daemon=True,
        )
        self.cleanup_thread.start()

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
        LOG.info("server shutdown started", extra={"event": "shutdown_started"})
        if hasattr(self, "cleanup_stop"):
            self.cleanup_stop.set()
            self.cleanup_thread.join(timeout=5)
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True, cancel_futures=True)
            try:
                self.config.jobs_store.mark_interrupted()
            except sqlite3.Error:
                pass
        super().server_close()
        LOG.info("server shutdown completed", extra={"event": "shutdown_completed"})


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "Hound/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(CLIENT_READ_TIMEOUT_SECONDS)
        self.request_id = uuid4().hex

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", self.request_id)
        self.end_headers()
        self.wfile.write(body)

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
                ip: [value for value in values if now - value < RATE_WINDOW_SECONDS]
                for ip, values in self.server.unauthorized_times.items()
                if any(now - value < RATE_WINDOW_SECONDS for value in values)
            }
            if client not in self.server.unauthorized_times and len(self.server.unauthorized_times) >= MAX_TRACKED_CLIENTS:
                self.server.unauthorized_times.pop(next(iter(self.server.unauthorized_times)))
            times = self.server.unauthorized_times.get(client, [])
            limited = len(times) >= self.server.config.rate_limit
            if not limited:
                times.append(now)
            self.server.unauthorized_times[client] = times
        self._json(429 if limited else 401, {"error": "rate limit exceeded" if limited else "unauthorized"})
        LOG.warning("request rejected", extra={"event": "request_rejected", "request_id": self.request_id,
                    "status": 429 if limited else 401, "failure_category": "authentication"})
        return False

    def _admit_request(self) -> bool:
        now = time.monotonic()
        client = self.client_address[0]
        self.server.cleanup_expired()
        with self.server.jobs_lock:
            self.server.request_times = {
                ip: [value for value in values if now - value < RATE_WINDOW_SECONDS]
                for ip, values in self.server.request_times.items()
                if any(now - value < RATE_WINDOW_SECONDS for value in values)
            }
            if client not in self.server.request_times and len(self.server.request_times) >= MAX_TRACKED_CLIENTS:
                self.server.request_times.pop(next(iter(self.server.request_times)))
            times = self.server.request_times.get(client, [])
            if len(times) >= self.server.config.rate_limit:
                self.server.request_times[client] = times
                self._json(429, {"error": "rate limit exceeded"})
                LOG.warning("request rejected", extra={"event": "request_rejected", "request_id": self.request_id,
                            "status": 429, "failure_category": "rate_limit"})
                return False
            times.append(now)
            self.server.request_times[client] = times
        return True

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path.rstrip("/") == "/ready":
            ready = self.server.config.jobs_store.ready() and os.access(self.server.config.output_root, os.W_OK)
            self._json(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
            return
        if not self._require_auth():
            return
        if not self._admit_request():
            return
        if self.path.rstrip("/") == "/stats":
            counts = self.server.config.jobs_store.counts()
            telemetry.gauge("server_queue_depth", float(counts["queued"] + counts["running"]))
            self._json(200, {
                "jobs": counts,
                "analysis": self.server.config.jobs_store.telemetry(),
                "hound": telemetry.snapshot(),
            })
            return
        prefix = "/jobs/"
        if self.path.startswith(prefix):
            job_id = self.path[len(prefix):]
            if not job_id.isalnum() or len(job_id) != 32:
                self._json(404, {"error": "job not found"})
                return
            job = self.server.config.jobs_store.get(job_id)
            self._json(200, job) if job else self._json(404, {"error": "job not found"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/analyze":
            self._json(404, {"error": "not found"})
            return
        if not self._require_auth():
            return
        if not self._admit_request():
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
            self._json(400, {"error": str(exc)})
            return
        job_id = uuid4().hex
        # Capacity admission and reservation must be one process-local critical
        # section; otherwise parallel handlers can all observe the same free slot.
        with self.server.jobs_lock:
            if self.server.config.jobs_store.active_count() >= self.server.config.max_queue:
                self._json(429, {"error": "server queue full"})
                LOG.warning("request rejected", extra={"event": "queue_rejected", "request_id": self.request_id, "status": 429})
                return
            self.server.config.jobs_store.create(job_id, status="queued")
        LOG.info("job created", extra={"event": "job_created", "request_id": self.request_id, "job_id": job_id})
        try:
            log_path = _snapshot_log(self.server.config.log_root, log_path, self.server.config.output_root, job_id)
        except FileNotFoundError:
            self._drop_job(job_id)
            self._json(404, {"error": "log not found"})
            return
        except ValueError as exc:
            self._drop_job(job_id)
            self._json(400, {"error": str(exc)})
            return
        except OSError:
            self._drop_job(job_id)
            self._json(500, {"error": "could not snapshot log"})
            return
        try:
            self.server.executor.submit(
                self._run_job, job_id, log_path, repo_path,
                bool(payload.get("offline", False)), self.request_id,
            )
        except RuntimeError:
            log_path.unlink(missing_ok=True)
            self._drop_job(job_id)
            self._json(503, {"error": "server is shutting down"})
            return
        self._json(202, {"accepted": True, "job_id": job_id})

    def _drop_job(self, job_id: str) -> None:
        with self.server.jobs_lock:
            self.server.config.jobs_store.delete(job_id)

    def _run_job(self, job_id: str, log_path: Path, repo_path: Path | None, offline: bool, request_id: str) -> None:
        self.server.config.jobs_store.update(job_id, status="running")
        LOG.info("job started", extra={"event": "job_started", "request_id": request_id, "job_id": job_id})
        output = self.server.config.output_root / job_id
        try:
            options = dict(self.server.config.analysis_options)
            options.update(repo_dir=repo_path, offline=offline or bool(options.get("offline", False)))
            options["state_path"] = self.server.config.state_path
            options["_config"] = replace(
                self.server.config.analysis_config,
                offline=bool(options["offline"]),
            )
            doc = service.analyze_log(log_path, output, **options)
            self.server.config.jobs_store.update(
                job_id,
                status="completed",
                report=str(output / "report.json"),
                engine=doc["meta"]["engine"],
                error=(doc["meta"].get("llm") or {}).get("fallback_reason") or "",
            )
            LOG.info("job completed", extra={"event": "job_completed", "request_id": request_id,
                     "job_id": job_id, "status": "completed"})
        except Exception:
            LOG.error("analysis job failed", extra={"event": "job_failed", "request_id": request_id, "job_id": job_id,
                      "status": "failed", "failure_category": "analysis"})
            self.server.config.jobs_store.update(
                job_id,
                status="failed",
                report=str(output / "report.json"),
                error="analysis failed",
            )
        finally:
            log_path.unlink(missing_ok=True)

    def log_message(self, fmt: str, *args) -> None:
        LOG.info("request completed", extra={"event": "request_completed", "request_id": self.request_id,
                 "method": self.command, "path": self.path.split("?", 1)[0]})


def _contained_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
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
            return
        target.write(chunk)
        remaining -= len(chunk)


def _remove_expired_report(output_root: Path, report: str) -> None:
    """Remove only a job-owned output directory below the configured root."""
    try:
        report_path = Path(report).resolve()
        job_dir = report_path.parent
        job_dir.relative_to(output_root)
        if report_path.name != "report.json" or len(job_dir.name) != 32 or not job_dir.name.isalnum():
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
