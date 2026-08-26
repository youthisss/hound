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
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from hound_agent import service
from hound_agent.config import load_config
from hound_agent.output.report import ensure_outdir
from hound_agent.pipeline import default_state_path

DEFAULT_PORT = 8123
MAX_BODY_BYTES = 1024 * 1024
MAX_WORKERS = 4
MAX_QUEUED_JOBS = 64
MAX_CLIENT_CONNECTIONS = 16
CLIENT_READ_TIMEOUT_SECONDS = 15
JOB_TTL_SECONDS = 3600
RATE_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 60
MAX_SERVER_LOG_BYTES = 16 * 1024 * 1024
COPY_CHUNK_BYTES = 64 * 1024


def _env_int(name: str, explicit: int | None, *, default: int, lo: int, hi: int) -> int:
    """Resolve a numeric server limit: explicit CLI arg wins, then env, then default."""
    if explicit is None:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return default
        explicit = str(raw)
    label = name.removeprefix("TH_SERVER_").lower()
    try:
        value = int(explicit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer, got {explicit!r}") from exc
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
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

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

    def cleanup(self, ttl: float) -> None:
        """Drop finished jobs older than ``ttl`` seconds. Active jobs are kept."""
        cutoff = time.time() - ttl
        with self._session() as conn:
            conn.execute(
                "DELETE FROM jobs WHERE updated < ? AND status IN ('completed','failed')",
                (cutoff,),
            )
            conn.commit()

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
        self.workers = _env_int("TH_SERVER_WORKERS", workers, default=MAX_WORKERS, lo=1, hi=64)
        self.max_queue = _env_int("TH_SERVER_MAX_QUEUE", max_queue, default=MAX_QUEUED_JOBS, lo=1, hi=100000)
        self.rate_limit = _env_int("TH_SERVER_RATE_LIMIT", rate_limit, default=MAX_REQUESTS_PER_WINDOW, lo=1, hi=1000000)
        self.job_ttl = _env_int("TH_SERVER_JOB_TTL", job_ttl, default=JOB_TTL_SECONDS, lo=30, hi=86400)
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
        self.jobs_store = _JobStore(self.output_root / ".hound-agent" / "jobs.sqlite3")
        self.jobs_store.mark_interrupted()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = MAX_CLIENT_CONNECTIONS

    def __init__(self, address, config: ServerConfig):
        self.executor = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="hound_agent")
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)
        self.config = config
        self.jobs_lock = threading.Lock()
        self.request_times: dict[str, list[float]] = {}
        self.client_slots = threading.BoundedSemaphore(MAX_CLIENT_CONNECTIONS)

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
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True, cancel_futures=True)
        super().server_close()


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "Hound-Agent/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(CLIENT_READ_TIMEOUT_SECONDS)

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.config.token}"
        return hmac.compare_digest(supplied, expected)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json(401, {"error": "unauthorized"})
        return False

    def _admit_request(self) -> bool:
        now = time.monotonic()
        client = self.client_address[0]
        try:
            self.server.config.jobs_store.cleanup(self.server.config.job_ttl)
        except sqlite3.Error as exc:
            sys.stderr.write(f"server: job store cleanup failed: {exc}\n")
        with self.server.jobs_lock:
            self.server.request_times = {
                ip: [value for value in values if now - value < RATE_WINDOW_SECONDS]
                for ip, values in self.server.request_times.items()
                if any(now - value < RATE_WINDOW_SECONDS for value in values)
            }
            times = self.server.request_times.get(client, [])
            if len(times) >= self.server.config.rate_limit:
                self.server.request_times[client] = times
                self._json(429, {"error": "rate limit exceeded"})
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
        if not self._admit_request():
            return
        if not self._require_auth():
            return
        if self.path.rstrip("/") == "/stats":
            self._json(200, {
                "jobs": self.server.config.jobs_store.counts(),
                "analysis": self.server.config.jobs_store.telemetry(),
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
        if not self._admit_request():
            return
        if self.path.rstrip("/") != "/analyze":
            self._json(404, {"error": "not found"})
            return
        if not self._require_auth():
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
                return
            self.server.config.jobs_store.create(job_id, status="queued")
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
            self.server.executor.submit(self._run_job, job_id, log_path, repo_path, bool(payload.get("offline", False)))
        except RuntimeError:
            log_path.unlink(missing_ok=True)
            self._drop_job(job_id)
            self._json(503, {"error": "server is shutting down"})
            return
        self._json(202, {"accepted": True, "job_id": job_id})

    def _drop_job(self, job_id: str) -> None:
        with self.server.jobs_lock:
            self.server.config.jobs_store.delete(job_id)

    def _run_job(self, job_id: str, log_path: Path, repo_path: Path | None, offline: bool) -> None:
        self.server.config.jobs_store.update(job_id, status="running")
        try:
            output = self.server.config.output_root / job_id
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
        except Exception as exc:
            sys.stderr.write(f"server: analysis job {job_id} failed: {exc}\n")
            self.server.config.jobs_store.update(job_id, status="failed", error="analysis failed")
        finally:
            log_path.unlink(missing_ok=True)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"server: {fmt % args!r}\n")


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


def run_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, *, token: str | None = None, log_root: str | Path = ".", output_root: str | Path = "hound-agent-server-output", repo_root: str | Path | None = None, **analysis_options) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("server only supports loopback HTTP; terminate TLS at a reverse proxy")
    workers = analysis_options.pop("workers", None)
    max_queue = analysis_options.pop("max_queue", None)
    rate_limit = analysis_options.pop("rate_limit", None)
    job_ttl = analysis_options.pop("job_ttl", None)
    config = ServerConfig(
        token or os.environ.get("TH_SERVER_TOKEN", ""),
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
    print(f"Hound Agent server listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
