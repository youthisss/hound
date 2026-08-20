"""Log collectors for subprocess output and piped stdin."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import TextIO
from uuid import uuid4

from tracehound.ingest.git import gather
from tracehound.ingest.redact import redact_text
from tracehound.output.report import _atomic_write


DEFAULT_LOG_DIR = Path(".tracehound") / "logs"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")
_PRIVATE_KEY_END = re.compile(r"-----END (?:ENCRYPTED |RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")
_SECRET_FLAGS = {"--api-key", "--password", "--passwd", "--secret", "--token"}
_INTERRUPT_GRACE_SECONDS = 3
MAX_LINE_BYTES = 1024 * 1024


class CollectionInputError(ValueError):
    """Raised when no valid log source was supplied."""


@dataclass(frozen=True)
class CollectedLog:
    log_file: Path
    metadata_file: Path
    exit_code: int
    metadata: dict


def collect_command(
    command: list[str],
    output: str | Path | None = None,
    name: str | None = None,
    cwd: str | Path | None = None,
    stream: TextIO | None = None,
    raw_console: bool = False,
) -> CollectedLog:
    """Run command without a shell, tee output, and persist a redacted log."""
    if not command:
        raise CollectionInputError("no command supplied")
    stream = stream or sys.stdout
    log_file, metadata_file = _output_paths(output, name or command[0])
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    process: subprocess.Popen[str] | None = None
    exit_code = 3
    redactor = _StreamingRedactor()
    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        with _open_log(log_file) as saved:
            if process.stdout is None:
                raise OSError("failed to capture command output")
            for line in _bounded_lines(process.stdout):
                redacted_line = redactor.redact(line)
                stream.write(line if raw_console else redacted_line)
                stream.flush()
                saved.write(redacted_line)
            saved.write(redactor.finish())
        exit_code = _normalize_exit_code(process.wait())
    except KeyboardInterrupt:
        if process is not None:
            _stop_process(process, interrupt=True)
        exit_code = 130
    except FileNotFoundError:
        _remove_if_exists(log_file)
        raise CollectionInputError(f"command not found: {command[0]}") from None
    except Exception:
        if process is not None:
            _stop_process(process)
        _remove_if_exists(log_file)
        raise
    metadata = _metadata(
        source="command",
        name=name or Path(command[0]).name,
        command=command,
        exit_code=exit_code,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started) * 1000),
        cwd=Path(cwd).resolve() if cwd else Path.cwd().resolve(),
        log_file=log_file,
    )
    _write_metadata(metadata_file, metadata)
    return CollectedLog(log_file, metadata_file, exit_code, metadata)


def collect_stdin(
    source: TextIO,
    output: str | Path | None = None,
    name: str | None = None,
    stream: TextIO | None = None,
    raw_console: bool = False,
) -> CollectedLog:
    """Tee piped text to a redacted log file."""
    stream = stream or sys.stdout
    log_file, metadata_file = _output_paths(output, name or "stdin")
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    redactor = _StreamingRedactor()
    received = False
    with _open_log(log_file) as saved:
        for line in _bounded_lines(source):
            received = True
            redacted_line = redactor.redact(line)
            stream.write(line if raw_console else redacted_line)
            stream.flush()
            saved.write(redacted_line)
        saved.write(redactor.finish())
    if not received:
        _remove_if_exists(log_file)
        raise CollectionInputError("piped stdin was empty; provide log text or run 'hound log -- <command>'")
    metadata = _metadata(
        source="stdin",
        name=name or "stdin",
        command=[],
        exit_code=0,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started) * 1000),
        cwd=Path.cwd().resolve(),
        log_file=log_file,
    )
    _write_metadata(metadata_file, metadata)
    return CollectedLog(log_file, metadata_file, 0, metadata)


class _StreamingRedactor:
    def __init__(self) -> None:
        self._inside_private_key = False

    def redact(self, line: str) -> str:
        if self._inside_private_key:
            if _PRIVATE_KEY_END.search(line):
                self._inside_private_key = False
            return ""
        if _PRIVATE_KEY_BEGIN.search(line):
            self._inside_private_key = not bool(_PRIVATE_KEY_END.search(line))
            return "[REDACTED:private_key]\n"
        return redact_text(line)[0]

    def finish(self) -> str:
        self._inside_private_key = False
        return ""


def _output_paths(output: str | Path | None, name: str) -> tuple[Path, Path]:
    if output:
        log_file = Path(output).expanduser()
        if log_file.exists() and log_file.is_dir():
            log_file = _unique_path(log_file, name)
        elif log_file.suffix.lower() != ".log":
            raise CollectionInputError("--output must be a .log file or existing directory")
        elif log_file.exists() or log_file.with_suffix(".json").exists():
            raise CollectionInputError(f"output already exists: {log_file}")
        log_file.parent.mkdir(parents=True, exist_ok=True)
    else:
        log_file = _unique_path(DEFAULT_LOG_DIR, name)
    return log_file, log_file.with_suffix(".json")


def _unique_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    clean_name = _SAFE_NAME.sub("-", redact_text(name)[0]).strip("-._") or "log"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = directory / f"{timestamp}-{clean_name}.log"
    index = 2
    while index <= 1000 and (candidate.exists() or candidate.with_suffix(".json").exists()):
        candidate = directory / f"{timestamp}-{clean_name}-{index}.log"
        index += 1
    if candidate.exists() or candidate.with_suffix(".json").exists():
        candidate = directory / f"{timestamp}-{clean_name}-{uuid4().hex}.log"
    return candidate


def _bounded_lines(source: TextIO):
    """Yield normal lines while replacing oversized lines without buffering them."""
    while True:
        chunk = source.readline(MAX_LINE_BYTES + 1)
        if not chunk:
            return
        if len(chunk) <= MAX_LINE_BYTES:
            yield chunk
            continue
        while chunk and not chunk.endswith("\n"):
            chunk = source.readline(MAX_LINE_BYTES + 1)
        yield "[REDACTED:oversized_line]\n"


def _metadata(
    *,
    source: str,
    name: str,
    command: list[str],
    exit_code: int,
    started_at: datetime,
    duration_ms: int,
    cwd: Path,
    log_file: Path,
) -> dict:
    git = gather(str(cwd))
    safe_command = _redact_command(command)
    metadata = {
        "schema_version": "1.0",
        "source": source,
        "name": name,
        "command": safe_command,
        "exit_code": exit_code,
        "started_at": started_at.isoformat(),
        "duration_ms": duration_ms,
        "cwd": str(cwd),
        "log_file": str(log_file.resolve()),
        "redacted": True,
        "git": asdict(git),
    }
    return _redact_metadata(metadata)


def _write_metadata(path: Path, metadata: dict) -> None:
    _atomic_write(path, json.dumps(metadata, indent=2, ensure_ascii=False))


def _open_log(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


def _redact_command(command: list[str]) -> list[str]:
    safe: list[str] = []
    hide_next = False
    for value in command:
        if hide_next:
            safe.append("[REDACTED:argument]")
            hide_next = False
            continue
        lowered = value.lower()
        if lowered in {"-p", "-u"}:
            safe.append(value)
            hide_next = True
            continue
        if re.match(r"^-[pu].+", lowered):
            safe.append(value[:2] + "[REDACTED:argument]")
            continue
        key = value.split("=", 1)[0].lower()
        if _is_secret_flag(key):
            if "=" in value:
                safe.append(f"{value.split('=', 1)[0]}=[REDACTED:argument]")
            else:
                safe.append(value)
                hide_next = True
            continue
        safe.append(redact_text(value)[0])
    return safe


def _is_secret_flag(value: str) -> bool:
    normalized = value.lstrip("-").replace("_", "-")
    return value in _SECRET_FLAGS or any(
        marker in normalized
        for marker in ("password", "passwd", "secret", "token", "credential", "api-key", "access-key")
    )


def _interrupt_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
    except OSError:
        process.terminate()


def _stop_process(process: subprocess.Popen[str], interrupt: bool = False) -> None:
    if process.poll() is not None:
        process.wait()
        return
    try:
        if interrupt:
            _interrupt_process(process)
        elif os.name == "nt":
            _kill_windows_tree(process.pid)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=_INTERRUPT_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                _kill_windows_tree(process.pid)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=_INTERRUPT_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _kill_windows_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_INTERRUPT_GRACE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _normalize_exit_code(return_code: int) -> int:
    return 128 + abs(return_code) if return_code < 0 else return_code


def _redact_metadata(value):
    if isinstance(value, str):
        return redact_text(value)[0]
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_metadata(item) for key, item in value.items()}
    return value


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
