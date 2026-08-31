"""SQLite-backed test-history store.

Guarantees required by the QA-history milestone:

- WAL mode with busy_timeout so concurrent writers never lose updates.
- Atomic upserts keyed by ``(suite, test, run_id, attempt)``.
- Retention deletes whole rows only; aggregates are recomputed over the
  remaining rows and therefore cannot be corrupted by pruning.
- Raw logs are never stored; rows reference ``run_id``/``evidence_id`` instead.
- Import/export round-trips sanitized records for CI cache / shared volumes.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from hound.qa.model import INSUFFICIENT_HISTORY, NormalizedTestResult
from hound.state_recovery import preserve_corrupt_sqlite

HISTORY_SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 90
_LOCK_RETRIES = 10
_LOCK_RETRY_DELAY = 0.05

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suite TEXT NOT NULL,
    test TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    duration_ms INTEGER,
    runner TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    branch TEXT NOT NULL,
    environment TEXT NOT NULL,
    failure_signature TEXT NOT NULL,
    run_id TEXT NOT NULL,
    evidence_id TEXT,
    recorded_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_test_result_run ON test_results (suite, test, run_id, attempt);
CREATE INDEX IF NOT EXISTS ix_test_result_identity ON test_results (suite, test);
CREATE INDEX IF NOT EXISTS ix_test_result_recorded ON test_results (recorded_at);
"""

_UPSERT = """
INSERT INTO test_results (
    suite, test, status, attempt, duration_ms, runner, commit_sha, branch,
    environment, failure_signature, run_id, evidence_id, recorded_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (suite, test, run_id, attempt) DO UPDATE SET
    status = excluded.status,
    duration_ms = excluded.duration_ms,
    runner = excluded.runner,
    commit_sha = excluded.commit_sha,
    branch = excluded.branch,
    environment = excluded.environment,
    failure_signature = excluded.failure_signature,
    evidence_id = excluded.evidence_id,
    recorded_at = excluded.recorded_at
"""

_COLUMNS = (
    "suite", "test", "status", "attempt", "duration_ms", "runner", "commit_sha",
    "branch", "environment", "failure_signature", "run_id", "evidence_id", "recorded_at",
)


def default_history_store(output_root: str | Path) -> Path:
    """History DB path, intentionally distinct from dedup and feedback stores."""
    return Path(output_root) / ".hound" / "history.sqlite3"


def _remaining_timeout(deadline: float | None) -> float:
    if deadline is None:
        return 30.0
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("history query exceeded its deadline")
    return min(30.0, max(0.001, remaining))


@contextmanager
def connect(
    store_path: str | Path,
    *,
    deadline: float | None = None,
    read_only: bool = False,
) -> Iterator[sqlite3.Connection]:
    store = Path(store_path)
    if store.is_symlink() or store.parent.is_symlink():
        raise ValueError("history store must not use symlinks")
    timeout = _remaining_timeout(deadline)
    if read_only:
        if not store.is_file():
            raise ValueError("history store is not a readable regular file")
        connection = sqlite3.connect(f"file:{store.resolve().as_posix()}?mode=ro", uri=True, timeout=timeout)
    else:
        store.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(store, timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    if deadline is not None:
        connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
    try:
        if read_only:
            connection.execute("PRAGMA query_only=ON")
            yield connection
            return
        for attempt in range(_LOCK_RETRIES):
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                _migrate(connection)
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == _LOCK_RETRIES - 1:
                    raise
                time.sleep(_LOCK_RETRY_DELAY)
        yield connection
        connection.commit()
    except sqlite3.DatabaseError as exc:
        connection.close()
        if read_only:
            raise ValueError("history store is damaged; restore it from a verified backup") from exc
        recovery = preserve_corrupt_sqlite(store)
        raise ValueError(f"history store is damaged; original preserved at {recovery}") from exc
    finally:
        connection.close()


def _migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        connection.executescript(_SCHEMA_V1)
        connection.execute(f"PRAGMA user_version={HISTORY_SCHEMA_VERSION}")
    elif version > HISTORY_SCHEMA_VERSION:
        raise ValueError(
            f"history store schema {version} is newer than supported {HISTORY_SCHEMA_VERSION}"
        )


def _row_values(result: NormalizedTestResult) -> tuple:
    return (
        result.suite, result.test, result.status, result.attempt, result.duration_ms,
        result.runner, result.commit, result.branch, result.environment,
        result.failure_signature, result.run_id, result.evidence_id, result.recorded_at,
    )


def _result_from_row(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in _COLUMNS if key in row.keys()}


def upsert_results(store_path: str | Path, results: list[NormalizedTestResult]) -> int:
    """Insert or update rows; returns the number of writes applied."""
    if not results:
        return 0
    with connect(store_path) as connection:
        connection.executemany(_UPSERT, [_row_values(r) for r in results])
    return len(results)


def retain(store_path: str | Path, days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete rows older than ``days``; returns the number of deleted rows."""
    if days < 1:
        raise ValueError("retention days must be >= 1")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect(store_path) as connection:
        cursor = connection.execute(
            "DELETE FROM test_results WHERE recorded_at < ?", (cutoff,)
        )
        return int(cursor.rowcount)


def _window(days: int | None) -> str | None:
    if days is None:
        return None
    if days < 1:
        raise ValueError("window days must be >= 1")
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def count_by_status(
    store_path: str | Path, suite: str, test: str, days: int | None = None, *, deadline: float | None = None
) -> dict[str, int]:
    counts = {status: 0 for status in ("passed", "failed", "skipped", "error", "unknown")}
    with connect(store_path, deadline=deadline, read_only=deadline is not None) as connection:
        cutoff = _window(days)
        query = "SELECT status, COUNT(*) AS n FROM test_results WHERE suite = ? AND test = ?"
        params: list = [suite, test]
        if cutoff is not None:
            query += " AND recorded_at >= ?"
            params.append(cutoff)
        query += " GROUP BY status"
        for row in connection.execute(query, params).fetchall():
            counts[str(row["status"])] = int(row["n"])
    return counts


def failure_rate(
    store_path: str | Path, suite: str, test: str, days: int | None = None, *, deadline: float | None = None
) -> float | None:
    """Failed / (passed + failed) over the window, or None for insufficient data."""
    counts = count_by_status(store_path, suite, test, days, deadline=deadline)
    failed = counts["failed"] + counts["error"]
    total = failed + counts["passed"]
    if total == 0:
        return None
    return round(failed / total, 6)


def first_last_seen(
    store_path: str | Path, suite: str, test: str, *, deadline: float | None = None
) -> tuple[str | None, str | None]:
    with connect(store_path, deadline=deadline, read_only=deadline is not None) as connection:
        row = connection.execute(
            "SELECT MIN(recorded_at) AS first_seen, MAX(recorded_at) AS last_seen "
            "FROM test_results WHERE suite = ? AND test = ?",
            (suite, test),
        ).fetchone()
    return (row["first_seen"], row["last_seen"]) if row else (None, None)


def duration_stats(
    store_path: str | Path, suite: str, test: str, days: int | None = None, *, deadline: float | None = None
) -> dict:
    """Median/p95/mean over non-null durations; empty dict when there is no data."""
    with connect(store_path, deadline=deadline, read_only=deadline is not None) as connection:
        cutoff = _window(days)
        query = (
            "SELECT duration_ms FROM test_results "
            "WHERE suite = ? AND test = ? AND duration_ms IS NOT NULL"
        )
        params: list = [suite, test]
        if cutoff is not None:
            query += " AND recorded_at >= ?"
            params.append(cutoff)
        durations = [int(row["duration_ms"]) for row in connection.execute(query, params).fetchall()]
    if not durations:
        return {}
    durations = sorted(durations)
    return {
        "count": len(durations),
        "median_ms": int(statistics.median(durations)),
        "mean_ms": int(sum(durations) / len(durations)),
        "p95_ms": int(durations[max(0, round(0.95 * len(durations)) - 1)]),
        "min_ms": durations[0],
        "max_ms": durations[-1],
    }


def environment_breakdown(
    store_path: str | Path, suite: str, test: str, *, deadline: float | None = None
) -> dict[str, int]:
    with connect(store_path, deadline=deadline, read_only=deadline is not None) as connection:
        rows = connection.execute(
            "SELECT environment, COUNT(*) AS n FROM test_results "
            "WHERE suite = ? AND test = ? GROUP BY environment ORDER BY n DESC",
            (suite, test),
        ).fetchall()
    return {str(row["environment"]): int(row["n"]) for row in rows}


def history_for_test(
    store_path: str | Path,
    suite: str,
    test: str,
    limit: int = 200,
    days: int | None = None,
    *,
    deadline: float | None = None,
) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    with connect(store_path, deadline=deadline, read_only=deadline is not None) as connection:
        cutoff = _window(days)
        query = (
            "SELECT suite, test, status, attempt, duration_ms, runner, commit_sha, branch, "
            "environment, failure_signature, run_id, evidence_id, recorded_at "
            "FROM test_results WHERE suite = ? AND test = ?"
        )
        params: list = [suite, test]
        if cutoff is not None:
            query += " AND recorded_at >= ?"
            params.append(cutoff)
        query += " ORDER BY recorded_at DESC, attempt DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, params).fetchall()
    return [_result_from_row(row) for row in rows]


def list_tests(
    store_path: str | Path, suite_prefix: str = "", limit: int = 100
) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    with connect(store_path, read_only=True) as connection:
        query = (
            "SELECT suite, test, runner, COUNT(*) AS samples, "
            "SUM(CASE WHEN status IN ('failed','error') THEN 1 ELSE 0 END) AS failures "
            "FROM test_results WHERE test != 'unknown'"
        )
        params: list = []
        if suite_prefix:
            query += " AND suite LIKE ?"
            params.append(f"{suite_prefix}%")
        query += " GROUP BY suite, test ORDER BY suite, test LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "suite": row["suite"], "test": row["test"], "runner": row["runner"],
            "samples": int(row["samples"]), "failures": int(row["failures"]),
        }
        for row in rows
    ]


def record_doc_results(doc: dict, store_path: str | Path) -> int:
    """Record normalized results from a built v2.0 RCA document."""
    results: list[NormalizedTestResult] = []
    failure = doc.get("failure", {})
    failed_tests = failure.get("failed_tests", []) if isinstance(failure, dict) else []
    commit = doc.get("context", {}).get("run", {}).get("commit_sha", "")
    branch = doc.get("context", {}).get("run", {}).get("branch", "")
    run_id = doc.get("meta", {}).get("run_id", "")
    recorded_at = doc.get("meta", {}).get("generated_at", "")
    for test in failed_tests:
        if not isinstance(test, dict) or not test.get("name"):
            continue
        results.append(NormalizedTestResult(
            suite=str(test.get("file") or "unknown")[:300],
            test=str(test["name"]),
            status="failed",
            runner="unknown",
            commit=str(commit),
            branch=str(branch),
            environment="",
            failure_signature=str(test.get("assertion") or ""),
            run_id=str(run_id),
            recorded_at=str(recorded_at or ""),
        ))
    return upsert_results(store_path, results)


def export_history(store_path: str | Path, output_path: str | Path) -> dict:
    """Write sanitized history to a JSON file; returns the manifest."""
    with connect(store_path, read_only=True) as connection:
        rows = connection.execute(
            "SELECT suite, test, status, attempt, duration_ms, runner, commit_sha, branch, "
            "environment, failure_signature, run_id, evidence_id, recorded_at "
            "FROM test_results ORDER BY recorded_at, suite, test"
        ).fetchall()
    records = [{key: row[key] for key in row.keys()} for row in rows]
    manifest = {
        "export_version": "1.0",
        "schema_version": HISTORY_SCHEMA_VERSION,
        "count": len(records),
        "records": records,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def import_history(store_path: str | Path, input_path: str | Path) -> int:
    """Upsert records from an exported manifest; returns the number imported."""
    source = Path(input_path)
    if source.is_symlink() or source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("history import must not use symlinks and must be bounded")
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read history import: {exc}") from exc
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("history import must contain a 'records' list")
    results: list[NormalizedTestResult] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"history import record {index} must be an object")
        results.append(NormalizedTestResult(
            suite=str(record.get("suite", "")),
            test=str(record.get("test", "unknown")),
            status=str(record.get("status", "unknown")),
            attempt=int(record.get("attempt", 1) or 1),
            duration_ms=record.get("duration_ms"),
            runner=str(record.get("runner", "unknown")),
            commit=str(record.get("commit_sha", "") or ""),
            branch=str(record.get("branch", "")),
            environment=str(record.get("environment", "")),
            failure_signature=str(record.get("failure_signature", "")),
            run_id=str(record.get("run_id", "")),
            evidence_id=record.get("evidence_id"),
            recorded_at=str(record.get("recorded_at", "")),
        ))
    return upsert_results(store_path, results)


def summarize_insufficient(store_path: str | Path, suite: str, test: str, days: int | None = None) -> dict:
    """Describe why a decision is ``insufficient_history``, or the history signal."""
    counts = count_by_status(store_path, suite, test, days)
    if sum(counts.values()) == 0:
        return {
            "decision": INSUFFICIENT_HISTORY,
            "reason": "no history rows for this test in the window",
            "counts": counts,
        }
    rate = failure_rate(store_path, suite, test, days)
    return {"decision": "analyzed", "reason": "", "counts": counts, "failure_rate": rate}
