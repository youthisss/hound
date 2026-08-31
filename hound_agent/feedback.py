"""Auditable feedback storage kept separate from incident deduplication state."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hound_agent.ingest.redact import redact_text
from hound_agent.models import KINDS, SEVERITIES, validate

FEEDBACK_SCHEMA_VERSION = "1.0"
MAX_REPORT_BYTES = 16 * 1024 * 1024
RATINGS = {"correct", "incorrect", "unknown"}
USEFULNESS = {"useful", "partial", "not_useful", "unknown"}
OUTCOMES = {"root_cause_confirmed", "alternative_cause", "false_positive", "resolved", "unresolved", "unknown"}
REVIEW_STATUSES = {"pending", "reviewed", "rejected"}


def default_feedback_store(output_root: str | Path) -> Path:
    """Return the feedback DB path; it intentionally differs from dedup state."""
    return Path(output_root) / ".hound-agent" / "feedback.sqlite3"


def resolve_report(output_root: str | Path, run_id: str) -> Path:
    """Resolve a stored run report without allowing traversal or symlink escape."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run-id must be a single directory name")
    root = Path(output_root).resolve()
    run_dir = root / run_id
    report = run_dir / "report.json"
    if run_dir.is_symlink() or report.is_symlink():
        raise ValueError("feedback source report must not use symlinks")
    resolved = report.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("feedback source report escapes output directory") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"stored report not found: {run_id}")
    return resolved


def _load_report(path: Path) -> tuple[dict, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"could not inspect report: {exc}") from exc
    if size > MAX_REPORT_BYTES:
        raise ValueError(f"report exceeds {MAX_REPORT_BYTES} bytes")
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read report: {exc}") from exc
    validate(document)
    return document, hashlib.sha256(raw).hexdigest()


def _safe_text(value: str, field: str, limit: int = 256) -> str:
    normalized = " ".join(str(value or "").split())
    redacted, _ = redact_text(normalized[:4096])
    redacted = redacted[:limit]
    if value and not redacted:
        raise ValueError(f"{field} must contain visible text")
    return redacted


def _connect(path: str | Path) -> sqlite3.Connection:
    store = Path(path)
    if store.is_symlink() or store.parent.is_symlink():
        raise ValueError("feedback store must not use symlinks")
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(store, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            feedback_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            report_schema_version TEXT NOT NULL,
            report_sha256 TEXT NOT NULL,
            dedup_key TEXT NOT NULL,
            predicted_kind TEXT NOT NULL,
            predicted_severity TEXT NOT NULL,
            predicted_component TEXT NOT NULL,
            usefulness TEXT NOT NULL,
            kind_correct TEXT NOT NULL,
            severity_correct TEXT NOT NULL,
            owner_correct TEXT NOT NULL,
            duplicate_correct TEXT NOT NULL,
            actual_kind TEXT,
            actual_severity TEXT,
            actual_owner TEXT NOT NULL,
            actual_outcome TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("PRAGMA user_version=1")
    return connection


def record_feedback(
    store_path: str | Path,
    report_path: str | Path,
    run_id: str,
    *,
    usefulness: str = "unknown",
    kind_correct: str = "unknown",
    severity_correct: str = "unknown",
    owner_correct: str = "unknown",
    duplicate_correct: str = "unknown",
    actual_kind: str | None = None,
    actual_severity: str | None = None,
    actual_owner: str = "",
    actual_outcome: str = "unknown",
    review_status: str = "pending",
    reviewer: str = "",
) -> dict:
    """Validate and append one structured feedback record."""
    if usefulness not in USEFULNESS:
        raise ValueError(f"usefulness must be one of {sorted(USEFULNESS)}")
    ratings = {
        "kind_correct": kind_correct,
        "severity_correct": severity_correct,
        "owner_correct": owner_correct,
        "duplicate_correct": duplicate_correct,
    }
    for name, value in ratings.items():
        if value not in RATINGS:
            raise ValueError(f"{name} must be one of {sorted(RATINGS)}")
    if actual_kind is not None and actual_kind not in KINDS:
        raise ValueError("actual_kind is invalid")
    if actual_severity is not None and actual_severity not in SEVERITIES:
        raise ValueError("actual_severity is invalid")
    if actual_outcome not in OUTCOMES:
        raise ValueError(f"actual_outcome must be one of {sorted(OUTCOMES)}")
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of {sorted(REVIEW_STATUSES)}")

    report, digest = _load_report(Path(report_path))
    record = {
        "feedback_id": f"fb-{uuid4().hex}",
        "run_id": _safe_text(run_id, "run_id", 160),
        "report_schema_version": report["schema_version"],
        "report_sha256": digest,
        "dedup_key": str(report["triage"]["dedup_key"]),
        "predicted_kind": report["failure"]["kind"],
        "predicted_severity": report["triage"]["severity"],
        "predicted_component": _safe_text(report["triage"]["component"], "predicted_component"),
        "usefulness": usefulness,
        **ratings,
        "actual_kind": actual_kind,
        "actual_severity": actual_severity,
        "actual_owner": _safe_text(actual_owner, "actual_owner"),
        "actual_outcome": actual_outcome,
        "review_status": review_status,
        "reviewer": _safe_text(reviewer, "reviewer"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    columns = tuple(record)
    placeholders = ", ".join("?" for _ in columns)
    with _connect(store_path) as connection:
        connection.execute(
            f"INSERT INTO feedback ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608 - fixed columns
            tuple(record[column] for column in columns),
        )
    return record


def read_feedback(store_path: str | Path, *, reviewed_only: bool = False) -> list[dict]:
    store = Path(store_path)
    if not store.is_file() or store.is_symlink():
        raise FileNotFoundError(f"feedback store not found: {store}")
    with _connect(store) as connection:
        query = "SELECT * FROM feedback"
        params: tuple[str, ...] = ()
        if reviewed_only:
            query += " WHERE review_status = ?"
            params = ("reviewed",)
        query += " ORDER BY created_at, feedback_id"
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def find_known_issue(
    store_path: str | Path,
    output_root: str | Path,
    dedup_key: str,
) -> dict | None:
    """Return a hash-verified report for one reviewed, resolved fingerprint."""
    store = Path(store_path)
    if not store.is_file() or store.is_symlink() or not dedup_key:
        return None
    with _connect(store) as connection:
        row = connection.execute(
            """SELECT * FROM feedback
               WHERE dedup_key = ?
                 AND review_status = 'reviewed'
                 AND usefulness IN ('useful', 'partial')
                 AND actual_outcome IN ('root_cause_confirmed', 'resolved')
               ORDER BY created_at DESC, feedback_id DESC
               LIMIT 1""",
            (dedup_key,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    try:
        report_path = resolve_report(output_root, record["run_id"])
        report, digest = _load_report(report_path)
    except (FileNotFoundError, ValueError):
        return None
    if digest != record["report_sha256"]:
        return None
    if report.get("triage", {}).get("dedup_key") != dedup_key:
        return None
    return {"feedback": record, "report": report}


def export_feedback(store_path: str | Path, *, reviewed_only: bool = False, candidates: bool = False) -> dict:
    """Return sanitized records or explicit candidate-fixture manifests."""
    records = read_feedback(store_path, reviewed_only=reviewed_only or candidates)
    if not candidates:
        return {
            "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
            "count": len(records),
            "records": records,
        }
    candidate_rows = []
    for record in records:
        candidate_rows.append({
            "candidate_version": "1.0",
            "feedback_id": record["feedback_id"],
            "source": {
                "run_id": record["run_id"],
                "report_sha256": record["report_sha256"],
            },
            "expected": {
                "kind": record["actual_kind"] or record["predicted_kind"],
                "severity": record["actual_severity"] or record["predicted_severity"],
                "owner": record["actual_owner"],
                "outcome": record["actual_outcome"],
            },
            "requires_manual_sanitized_artifact": True,
        })
    return {
        "candidate_export_version": "1.0",
        "count": len(candidate_rows),
        "candidates": candidate_rows,
    }
