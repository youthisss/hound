"""Dedup via normalized fingerprint; persists across runs in a state file."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import time
import tempfile
from pathlib import Path
from uuid import uuid4

from hound_agent.models import Artifacts, RootCause, Triage

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

_BACKEND = "file"
_STORE_URL = ""
_STORE_TOKEN = ""


def configure_store(backend: str = "file", url: str = "", token: str = "") -> None:
    """Select the state-store backend. ``file`` (default) or ``http``.

    The ``http`` backend treats ``url`` as an S3-compatible blob: GET returns
    the current JSON list, PUT replaces it. For distributed CI runners with no
    shared filesystem.
    """
    if backend not in {"", "file"}:
        raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")
    global _BACKEND, _STORE_URL, _STORE_TOKEN
    _BACKEND = backend or "file"
    _STORE_URL = url or ""
    _STORE_TOKEN = token or ""


def _is_http() -> bool:
    return _BACKEND == "http"


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


def normalize(text: str) -> str:
    t = text.lower()
    t = _REMOVE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fingerprint(artifacts: Artifacts, root_cause: RootCause | None = None) -> str:
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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
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
            except FileExistsError:
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


def save_state(path: str | os.PathLike, entries: list[dict]) -> bool:
    if _is_http():
        _http_put(entries)
        return True
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Prefer filed entries, but keep the state strictly bounded.
        if len(entries) > MAX_STATE_ENTRIES:
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
        fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(entries, stream, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            tmp.unlink(missing_ok=True)
            raise
        return True
    except OSError as exc:
        sys.stderr.write(f"Warning: Failed to save dedup state to '{path}': {exc}\n")
        return False


FLAKY_THRESHOLD = 3


def check_duplicate(artifacts: Artifacts, root_cause: RootCause, state_path: str | None, recurrence_threshold: int = FLAKY_THRESHOLD) -> Triage:
    key = fingerprint(artifacts, root_cause)
    triage = Triage(dedup_key=key, flaky_suspect=artifacts.kind == "flaky")
    if not state_path:
        return triage

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
        save_state(state_path, entries)
    return triage


def is_already_filed(state_path: str | None, key: str, destination: str = "github") -> bool:
    """Return whether this failure was delivered to the selected integration."""
    if not state_path or not key:
        return False
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
    with _state_lock(state_path):
        entries = load_state(state_path)
        for entry in entries:
            if entry.get("key") == key and isinstance(entry.get("delivery_claims"), dict):
                entry["delivery_claims"].pop(destination, None)
                return save_state(state_path, entries)
        return False


def _entry_delivered(entry: dict) -> bool:
    return bool(entry.get("filed")) or bool(entry.get("deliveries"))


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def record_triage(state_path: str | None, triage: Triage, component: str, title: str) -> None:
    """Attach component/title to the persisted entry for this dedup key."""
    if not state_path or not triage.dedup_key:
        return
    with _state_lock(state_path):
        entries = load_state(state_path)
        updated = False
        for entry in entries:
            if entry.get("key") == triage.dedup_key:
                entry["component"] = component
                entry["title"] = title
                updated = True
        if updated:
            save_state(state_path, entries)
