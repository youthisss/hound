"""Bounded authenticated HTTP receiver for trusted local log roots."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hmac
import json
import os
import socket
import stat
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from tracehound import service
from tracehound.config import load_config
from tracehound.output.report import ensure_outdir
from tracehound.pipeline import default_state_path

DEFAULT_PORT = 8123
MAX_BODY_BYTES = 1024 * 1024
MAX_WORKERS = 2
MAX_QUEUED_JOBS = 8
MAX_CLIENT_CONNECTIONS = 16
CLIENT_READ_TIMEOUT_SECONDS = 15
JOB_TTL_SECONDS = 3600
RATE_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 30
MAX_SERVER_LOG_BYTES = 16 * 1024 * 1024


class ServerConfig:
    def __init__(self, token: str, log_root: str | Path, output_root: str | Path, repo_root: str | Path | None = None, analysis_options: dict | None = None):
        if not token:
            raise ValueError("server token is required")
        self.token = token
        self.log_root = Path(log_root).resolve()
        self.output_root = Path(output_root).resolve()
        self.repo_root = Path(repo_root).resolve() if repo_root else None
        self.analysis_options = analysis_options or {}
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
        )
        self.analysis_config = replace(config, timeout=min(config.timeout, 30.0), max_retries=0)
        self.state_path = default_state_path(
            self.output_root,
            config.state_file,
            bool(self.analysis_options.get("no_dedup", False)),
        )


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = MAX_CLIENT_CONNECTIONS

    def __init__(self, address, config: ServerConfig):
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="tracehound")
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)
        self.config = config
        self.jobs: dict[str, dict] = {}
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
        with self.server.jobs_lock:
            self.server.jobs = {
                job_id: job for job_id, job in self.server.jobs.items()
                if job.get("status") in {"queued", "running"}
                or now - job.get("updated", job.get("created", now)) < JOB_TTL_SECONDS
            }
            self.server.request_times = {
                ip: [value for value in values if now - value < RATE_WINDOW_SECONDS]
                for ip, values in self.server.request_times.items()
                if any(now - value < RATE_WINDOW_SECONDS for value in values)
            }
            times = self.server.request_times.get(client, [])
            if len(times) >= MAX_REQUESTS_PER_WINDOW:
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
        if not self._admit_request():
            return
        if not self._require_auth():
            return
        prefix = "/jobs/"
        if self.path.startswith(prefix):
            job_id = self.path[len(prefix):]
            if not job_id.isalnum() or len(job_id) != 32:
                self._json(404, {"error": "job not found"})
                return
            with self.server.jobs_lock:
                job = self.server.jobs.get(job_id)
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
        job = {"id": job_id, "status": "queued", "created": time.monotonic(), "updated": time.monotonic()}
        with self.server.jobs_lock:
            queued = sum(item["status"] in {"queued", "running"} for item in self.server.jobs.values())
            if queued >= MAX_QUEUED_JOBS:
                self._json(429, {"error": "server queue full"})
                return
            self.server.jobs[job_id] = job
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
            self.server.jobs.pop(job_id, None)

    def _run_job(self, job_id: str, log_path: Path, repo_path: Path | None, offline: bool) -> None:
        with self.server.jobs_lock:
            job = self.server.jobs.get(job_id, {"id": job_id, "created": time.monotonic()})
            job.update(status="running", updated=time.monotonic())
            self.server.jobs[job_id] = job
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
            with self.server.jobs_lock:
                job = self.server.jobs[job_id]
                job.update(status="completed", updated=time.monotonic(), report=str(output / "report.json"), engine=doc["meta"]["engine"])
        except Exception as exc:
            sys.stderr.write(f"server: analysis job {job_id} failed: {exc}\n")
            with self.server.jobs_lock:
                job = self.server.jobs.get(job_id, {"id": job_id, "created": time.monotonic()})
                job.update(status="failed", updated=time.monotonic(), error="analysis failed")
                self.server.jobs[job_id] = job
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
    try:
        source_stat = os.fstat(fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > MAX_SERVER_LOG_BYTES:
            raise ValueError("log must be a regular file within the server size limit")
        snapshot_dir = output_root / ".incoming"
        snapshot_dir.mkdir(mode=0o700, exist_ok=True)
        snapshot = snapshot_dir / f"{job_id}{path.suffix.lower()}"
        with os.fdopen(fd, "rb", closefd=False) as source, snapshot.open("xb") as target:
            shutil.copyfileobj(source, target, length=64 * 1024)
    finally:
        os.close(fd)
    return snapshot


def run_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, *, token: str | None = None, log_root: str | Path = ".", output_root: str | Path = "tracehound_server_output", repo_root: str | Path | None = None, **analysis_options) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("server only supports loopback HTTP; terminate TLS at a reverse proxy")
    config = ServerConfig(token or os.environ.get("TH_SERVER_TOKEN", ""), log_root, output_root, repo_root, analysis_options)
    httpd = _Server((host, port), config)
    print(f"Hound Agent server listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
