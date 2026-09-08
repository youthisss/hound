"""Persistent idempotent delivery ledger with ambiguous-outcome recovery."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from hound.ingest.redact import redact_text
from hound.pathutil import path_has_symlink
from hound.state_recovery import preserve_corrupt_sqlite

SCHEMA_VERSION = 1
PENDING_TTL_SECONDS = 300
STATES = {"pending", "confirmed", "failed", "unknown"}
_INIT_LOCK = threading.Lock()
MAX_EXTERNAL_ID_CHARS = 2048


def delivery_key(incident_key: str, destination: str) -> str:
    return hashlib.sha256(f"{incident_key}\0{destination}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DeliveryRecord:
    key: str
    incident_key: str
    destination: str
    state: str
    external_id: str
    attempts: int
    created_at: float
    updated_at: float
    error: str


class DeliveryLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.is_symlink() or path_has_symlink(self.path.parent):
            raise ValueError("delivery ledger must not contain symlinked path components")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _INIT_LOCK:
            try:
                self._init_schema()
            except sqlite3.DatabaseError as exc:
                recovery = preserve_corrupt_sqlite(self.path)
                raise ValueError(f"delivery ledger is damaged; original preserved at {recovery}") from exc

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink() or path_has_symlink(self.path.parent):
            raise ValueError("delivery ledger must not contain symlinked path components")
        connection = sqlite3.connect(self.path, timeout=10.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA synchronous=NORMAL")
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback and always close the short-lived connection."""
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._session() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS deliveries (
                    key TEXT PRIMARY KEY,
                    incident_key TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    state TEXT NOT NULL,
                    external_id TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_updated ON deliveries(updated_at)")

    def reserve(self, incident_key: str, destination: str) -> bool:
        key = delivery_key(incident_key, destination)
        now = time.time()
        with self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state, updated_at FROM deliveries WHERE key = ?", (key,)).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO deliveries(key, incident_key, destination, state, attempts, created_at, updated_at) "
                    "VALUES(?, ?, ?, 'pending', 1, ?, ?)",
                    (key, incident_key, destination, now, now),
                )
                return True
            state = str(row["state"])
            if state in {"confirmed", "unknown"}:
                return False
            if state == "pending" and now - float(row["updated_at"]) < PENDING_TTL_SECONDS:
                return False
            if state == "pending":
                connection.execute(
                    "UPDATE deliveries SET state='unknown', updated_at=?, error=? WHERE key=?",
                    (now, "stale pending delivery requires reconciliation", key),
                )
                return False
            connection.execute(
                "UPDATE deliveries SET state='pending', attempts=attempts+1, updated_at=?, error='' WHERE key=?",
                (now, key),
            )
            return True

    def confirm(self, incident_key: str, destination: str, external_id: str = "") -> None:
        self._transition(incident_key, destination, "confirmed", external_id=external_id)

    def fail(self, incident_key: str, destination: str, error: str) -> None:
        self._transition(incident_key, destination, "failed", error=error)

    def mark_unknown(self, incident_key: str, destination: str, error: str) -> None:
        self._transition(incident_key, destination, "unknown", error=error)

    def mark_failed(self, incident_key: str, destination: str, error: str) -> None:
        """Mark an unresolved delivery failed after an operator verified absence.

        This is deliberately narrower than ``fail``: the administration path may
        only close a pending or unknown outcome. Confirmed deliveries and already
        failed records cannot be rewritten through this recovery operation.
        """
        key = delivery_key(incident_key, destination)
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE deliveries SET state='failed', external_id='', error=?, updated_at=? "
                "WHERE key=? AND state IN ('pending', 'unknown')",
                (_safe_error(error), time.time(), key),
            )
            if cursor.rowcount != 1:
                raise ValueError("only pending or unknown deliveries can be marked failed")

    def reconcile(self, incident_key: str, destination: str, external_id: str) -> None:
        if not external_id:
            raise ValueError("external_id is required to confirm reconciliation")
        record = self.get(incident_key, destination)
        if record is None:
            raise KeyError("delivery reservation not found")
        if record.state != "unknown":
            raise ValueError("only unknown deliveries can be reconciled")
        self.confirm(incident_key, destination, external_id)

    def retry_failed(self, incident_key: str, destination: str) -> bool:
        """Explicitly retry a known failed delivery.

        Unknown and pending outcomes are intentionally not retryable here. A
        caller must reconcile an unknown outcome first so a remote object is
        never duplicated by an automatic or ambiguous retry.
        """
        key = delivery_key(incident_key, destination)
        now = time.time()
        with self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE deliveries SET state='pending', attempts=attempts+1, updated_at=?, error='' "
                "WHERE key=? AND state='failed'",
                (now, key),
            )
            return cursor.rowcount == 1

    def get(self, incident_key: str, destination: str) -> DeliveryRecord | None:
        key = delivery_key(incident_key, destination)
        with self._session() as connection:
            row = connection.execute("SELECT * FROM deliveries WHERE key = ?", (key,)).fetchone()
        return DeliveryRecord(**dict(row)) if row is not None else None

    def list_records(
        self,
        *,
        state: str | None = None,
        incident_key: str | None = None,
        destination: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryRecord]:
        """List bounded ledger records for operator inspection."""
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")
        if state is not None and state not in STATES:
            raise ValueError(f"state must be one of {sorted(STATES)}")
        clauses: list[str] = []
        values: list[str | int] = []
        if state is not None:
            clauses.append("state = ?")
            values.append(state)
        if incident_key is not None:
            clauses.append("incident_key = ?")
            values.append(incident_key)
        if destination is not None:
            clauses.append("destination = ?")
            values.append(destination)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM deliveries{where} ORDER BY updated_at DESC, key DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [DeliveryRecord(**dict(row)) for row in rows]

    def cleanup(self, retention_days: int, *, dry_run: bool = True) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        cutoff = time.time() - retention_days * 86400
        with self._session() as connection:
            count = int(connection.execute(
                "SELECT COUNT(*) FROM deliveries WHERE updated_at < ? AND state IN ('confirmed','failed')",
                (cutoff,),
            ).fetchone()[0])
            if not dry_run:
                connection.execute(
                    "DELETE FROM deliveries WHERE updated_at < ? AND state IN ('confirmed','failed')",
                    (cutoff,),
                )
        return count

    def counts(self) -> dict[str, int]:
        result = {state: 0 for state in sorted(STATES)}
        with self._session() as connection:
            rows = connection.execute("SELECT state, COUNT(*) AS count FROM deliveries GROUP BY state").fetchall()
        for row in rows:
            result[str(row["state"])] = int(row["count"])
        return result

    def _transition(
        self,
        incident_key: str,
        destination: str,
        state: str,
        *,
        external_id: str = "",
        error: str = "",
    ) -> None:
        if state not in STATES:
            raise ValueError(f"invalid delivery state: {state}")
        key = delivery_key(incident_key, destination)
        external_id = _safe_external_id(external_id)
        error = _safe_error(error)
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE deliveries SET state=?, external_id=?, error=?, updated_at=? WHERE key=?",
                (state, external_id, error, time.time(), key),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"delivery reservation not found: {key}")


def _safe_external_id(value: str) -> str:
    """Bound and redact external IDs/URLs before they reach durable state."""
    text = str(value or "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_EXTERNAL_ID_CHARS:
        raise ValueError(f"external_id exceeds {MAX_EXTERNAL_ID_CHARS} characters")
    redacted, _ = redact_text(text)
    return redacted[:MAX_EXTERNAL_ID_CHARS]


def _safe_error(value: object) -> str:
    """Bound and redact connector diagnostics before durable persistence."""
    text = str(value or "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    redacted, _ = redact_text(text)
    return redacted[:500]
