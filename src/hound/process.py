"""Bounded subprocess capture for read-only evidence collectors."""
from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class BoundedCompletedProcess:
    """Small ``CompletedProcess``-like result with an output-limit flag."""

    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str = ""
    truncated: bool = False


class _Capture:
    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self.data = bytearray()
        self.truncated = False
        self._lock = threading.Lock()

    def append(self, value: bytes) -> None:
        with self._lock:
            remaining = self.limit - len(self.data)
            if remaining > 0:
                self.data.extend(value[:remaining])
            if len(value) > max(remaining, 0):
                self.truncated = True


def run_bounded(
    args: Sequence[str],
    *,
    timeout: float,
    max_output_bytes: int,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> BoundedCompletedProcess:
    """Run a command without a shell and cap captured combined output.

    The child writes to one pipe, so there is no stdout/stderr pipe deadlock.
    Once the cap is reached, the reader continues draining and discards bytes;
    this keeps the process bounded until its timeout without retaining attacker-
    controlled output in memory.
    """
    if not args:
        raise ValueError("cannot run an empty command")
    if timeout <= 0:
        raise ValueError("subprocess timeout must be positive")
    if max_output_bytes < 0:
        raise ValueError("subprocess output limit must not be negative")

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        start_new_session=os.name != "nt",
        creationflags=creationflags,
    )
    capture = _Capture(max_output_bytes)

    def drain() -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                capture.append(chunk)
        except OSError:
            return

    reader = threading.Thread(target=drain, name="hound_subprocess_reader", daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate(process)
        _wait_after_terminate(process)
        reader.join(timeout=1.0)
        raise exc
    finally:
        reader.join(timeout=1.0)
        if process.poll() is None:
            _terminate(process)
            _wait_after_terminate(process)

    return BoundedCompletedProcess(
        args=args,
        returncode=int(process.returncode or 0),
        stdout=bytes(capture.data).decode("utf-8", errors="replace"),
        truncated=capture.truncated,
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
                shell=False,
            )
        else:
            killpg = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
            if callable(killpg):
                killpg(process.pid, sigkill)
            else:
                process.kill()
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _wait_after_terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass
