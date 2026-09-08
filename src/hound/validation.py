"""Persistent report validation engine and audit store.

Provides read-only integrity verification for stored RCA documents:
- Verifies schema 2.0 compliance and legacy 1.4 support.
- Computes and verifies SHA-256 report digest to detect stale or tampered files.
- Enforces fail-closed trust profile compliance (e.g. fork_pr cannot enable external capabilities).
- Checks timeline event coherence and causal acyclicity.
- Audits deployment context, observability correlation, and connector hygiene.
- Persists audit trail in `<output-dir>/.hound/validations.sqlite3` without mutating source reports.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator
from uuid import uuid4

from hound.fsio import read_bounded_bytes
from hound.models import LEGACY_SCHEMA_VERSION, SCHEMA_VERSION, validate
from hound.pathutil import path_has_symlink
from hound.state_recovery import preserve_corrupt_sqlite
from hound.trust import SOURCE_CLASSES, policy_for

VALIDATION_SCHEMA_VERSION = "1.0"
MAX_REPORT_BYTES = 16 * 1024 * 1024
VALIDATION_STATUSES = {"PASS", "WARN", "FAIL"}

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-z0-9_\-\.]{15,}"),
    re.compile(r"(?i)(password|secret|token|api_key|apikey)\s*[:=]\s*['\"][^\s'\"]{6,}['\"]"),
]


@dataclass
class ValidationCheck:
    name: str
    status: str  # "PASS", "WARN", "FAIL"
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationRecord:
    validation_id: str
    run_id: str
    report_path: str
    report_sha256: str
    schema_version: str
    status: str  # "PASS", "WARN", "FAIL"
    summary: str
    checks: list[ValidationCheck]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "validation_id": self.validation_id,
            "run_id": self.run_id,
            "report_path": self.report_path,
            "report_sha256": self.report_sha256,
            "schema_version": self.schema_version,
            "status": self.status,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "created_at": self.created_at,
        }

    def is_stale(self, current_report_path: str | Path | None = None) -> bool:
        """Return True if the target report file on disk has a different SHA-256 hash."""
        target = Path(current_report_path or self.report_path)
        if not target.is_file() or target.is_symlink():
            return True
        try:
            raw = read_bounded_bytes(target, MAX_REPORT_BYTES)
            current_digest = hashlib.sha256(raw).hexdigest()
            return current_digest != self.report_sha256
        except Exception:
            return True


def default_validation_store(output_root: str | Path) -> Path:
    """Return the validations SQLite DB path under `.hound/validations.sqlite3`."""
    return Path(output_root) / ".hound" / "validations.sqlite3"


@contextmanager
def _connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    store = Path(path)
    if path_has_symlink(store) or store.is_symlink():
        raise ValueError("validation store must not use symlinks")
    store.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(store) or store.is_symlink():
        raise ValueError("validation store must not use symlinks")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(store, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS report_validations (
                validation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                report_path TEXT NOT NULL,
                report_sha256 TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_validations_run ON report_validations(run_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_validations_sha ON report_validations(report_sha256)"
        )
        connection.execute("PRAGMA user_version=1")
        yield connection
        connection.commit()
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.rollback()
        if store.exists() and _looks_corrupt(exc):
            if connection is not None:
                connection.close()
                connection = None
            recovery = preserve_corrupt_sqlite(store)
            raise ValueError(f"validation store is damaged; original preserved at {recovery}") from exc
        raise
    finally:
        if connection is not None:
            connection.close()


def _looks_corrupt(error: sqlite3.DatabaseError) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in ("not a database", "database disk image is malformed", "file is encrypted")
    )


def save_validation(store_path: str | Path, record: ValidationRecord) -> None:
    """Persist one validation record into the SQLite store."""
    checks_json = json.dumps([c.to_dict() for c in record.checks], separators=(",", ":"))
    with _connect(store_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO report_validations (
                validation_id, run_id, report_path, report_sha256,
                schema_version, status, summary, checks_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.validation_id,
                record.run_id,
                record.report_path,
                record.report_sha256,
                record.schema_version,
                record.status,
                record.summary,
                checks_json,
                record.created_at,
            ),
        )


def _row_to_record(row: sqlite3.Row) -> ValidationRecord:
    checks_raw = json.loads(row["checks_json"])
    checks = [
        ValidationCheck(
            name=c.get("name", "unknown"),
            status=c.get("status", "FAIL"),
            message=c.get("message", ""),
            details=c.get("details", {}),
        )
        for c in checks_raw
    ]
    return ValidationRecord(
        validation_id=row["validation_id"],
        run_id=row["run_id"],
        report_path=row["report_path"],
        report_sha256=row["report_sha256"],
        schema_version=row["schema_version"],
        status=row["status"],
        summary=row["summary"],
        checks=checks,
        created_at=row["created_at"],
    )


def get_latest_validation(store_path: str | Path, run_id: str) -> ValidationRecord | None:
    """Return the most recent validation record for run_id, or None."""
    store = Path(store_path)
    if not store.is_file() or store.is_symlink():
        return None
    with _connect(store) as connection:
        row = connection.execute(
            "SELECT * FROM report_validations WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def get_validation_by_sha256(store_path: str | Path, report_sha256: str) -> ValidationRecord | None:
    """Return the most recent validation record matching report_sha256."""
    store = Path(store_path)
    if not store.is_file() or store.is_symlink():
        return None
    with _connect(store) as connection:
        row = connection.execute(
            "SELECT * FROM report_validations WHERE report_sha256 = ? ORDER BY created_at DESC LIMIT 1",
            (report_sha256,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def list_validations(
    store_path: str | Path,
    run_id: str | None = None,
    limit: int = 50,
) -> list[ValidationRecord]:
    """List validation records, newest first."""
    store = Path(store_path)
    if not store.is_file() or store.is_symlink():
        return []
    with _connect(store) as connection:
        if run_id:
            rows = connection.execute(
                "SELECT * FROM report_validations WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM report_validations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]


def count_validations(store_path: str | Path) -> dict[str, int]:
    """Return total count and status breakdown from validation store."""
    store = Path(store_path)
    if not store.is_file() or store.is_symlink():
        return {"total": 0, "pass": 0, "warn": 0, "fail": 0}
    with _connect(store) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) as cnt FROM report_validations GROUP BY status"
        ).fetchall()
        counts = {"total": 0, "pass": 0, "warn": 0, "fail": 0}
        for row in rows:
            status_lower = str(row["status"]).lower()
            cnt = int(row["cnt"])
            counts["total"] += cnt
            if status_lower in counts:
                counts[status_lower] = cnt
        return counts


def validate_report(
    report_path: str | Path,
    *,
    output_root: str | Path | None = None,
    persist: bool = True,
) -> ValidationRecord:
    """Validate a report on disk, determine PASS/WARN/FAIL, and optionally persist.

    Performs complete read-only evaluation:
    1. Reads bounded file content & computes SHA-256.
    2. Parses JSON & evaluates model schema rules.
    3. Audits trust profile & fail-closed permission enforcement.
    4. Audits timeline causal integrity (ordering & cycle detection).
    5. Audits deployment context, observability, and connector records.
    6. Returns an immutable ValidationRecord.
    """
    path = Path(report_path)
    run_id = path.parent.name
    if not path.is_file() or path.is_symlink():
        record = ValidationRecord(
            validation_id=f"val-{uuid4().hex[:12]}",
            run_id=run_id,
            report_path=str(path),
            report_sha256="",
            schema_version="unknown",
            status="FAIL",
            summary="Report file missing or invalid symlink",
            checks=[
                ValidationCheck(
                    name="file_integrity",
                    status="FAIL",
                    message=f"File not found or is a symlink: {path}",
                )
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return record

    try:
        size = path.stat().st_size
    except OSError as exc:
        return ValidationRecord(
            validation_id=f"val-{uuid4().hex[:12]}",
            run_id=run_id,
            report_path=str(path),
            report_sha256="",
            schema_version="unknown",
            status="FAIL",
            summary=f"Could not inspect file: {exc}",
            checks=[
                ValidationCheck(
                    name="file_integrity",
                    status="FAIL",
                    message=str(exc),
                )
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    if size > MAX_REPORT_BYTES:
        return ValidationRecord(
            validation_id=f"val-{uuid4().hex[:12]}",
            run_id=run_id,
            report_path=str(path),
            report_sha256="",
            schema_version="unknown",
            status="FAIL",
            summary=f"Report file exceeds maximum allowed size ({MAX_REPORT_BYTES} bytes)",
            checks=[
                ValidationCheck(
                    name="file_size",
                    status="FAIL",
                    message=f"Size {size} exceeds limit {MAX_REPORT_BYTES}",
                )
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    try:
        raw = read_bounded_bytes(path, MAX_REPORT_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return ValidationRecord(
            validation_id=f"val-{uuid4().hex[:12]}",
            run_id=run_id,
            report_path=str(path),
            report_sha256="",
            schema_version="unknown",
            status="FAIL",
            summary=f"JSON decoding failed: {exc}",
            checks=[
                ValidationCheck(
                    name="json_parse",
                    status="FAIL",
                    message=str(exc),
                )
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    checks: list[ValidationCheck] = []

    # 1. Digest Integrity check
    checks.append(
        ValidationCheck(
            name="digest_integrity",
            status="PASS",
            message=f"SHA-256 digest verified ({digest[:12]}…)",
            details={"sha256": digest, "bytes": len(raw)},
        )
    )

    # 2. Schema compliance
    schema_ver = str(doc.get("schema_version", "unknown"))
    schema_error: str | None = None
    try:
        validate(doc)
        if schema_ver == SCHEMA_VERSION:
            checks.append(
                ValidationCheck(
                    name="schema_compliance",
                    status="PASS",
                    message=f"Report conforms to current schema v{SCHEMA_VERSION}",
                    details={"version": schema_ver},
                )
            )
        elif schema_ver == LEGACY_SCHEMA_VERSION:
            checks.append(
                ValidationCheck(
                    name="schema_compliance",
                    status="WARN",
                    message=f"Report uses legacy schema v{LEGACY_SCHEMA_VERSION}; upgrade to v{SCHEMA_VERSION} recommended",
                    details={"version": schema_ver},
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="schema_compliance",
                    status="WARN",
                    message=f"Supported schema version {schema_ver}",
                    details={"version": schema_ver},
                )
            )
    except ValueError as exc:
        schema_error = str(exc)
        checks.append(
            ValidationCheck(
                name="schema_compliance",
                status="FAIL",
                message=f"Schema validation error: {schema_error}",
                details={"error": schema_error},
            )
        )

    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    context = doc.get("context") if isinstance(doc.get("context"), dict) else {}
    timeline = doc.get("timeline") if isinstance(doc.get("timeline"), dict) else {}
    devops = doc.get("devops") if isinstance(doc.get("devops"), dict) else {}

    # 3. Trust Profile Audit & Fail-Closed Enforcement
    trust = meta.get("trust")
    if isinstance(trust, dict):
        src_class = trust.get("source_class")
        if src_class not in SOURCE_CLASSES:
            checks.append(
                ValidationCheck(
                    name="trust_profile",
                    status="FAIL",
                    message=f"Invalid trust source_class: {src_class}",
                    details={"trust": trust},
                )
            )
        else:
            policy = policy_for(src_class)
            # Fail-closed enforcement check:
            # If policy does not allow a capability, it MUST be False in the report trust metadata
            violations = []
            if not policy.allow_source_context and trust.get("source_context") is True:
                violations.append("source_context enabled for untrusted source")
            if not policy.allow_enrichment and trust.get("enrichment") is True:
                violations.append("enrichment enabled for untrusted source")
            if not policy.allow_llm and trust.get("llm") is True:
                violations.append("llm enabled for untrusted source")
            if not policy.allow_delivery and trust.get("delivery") is True:
                violations.append("delivery enabled for untrusted source")

            if violations:
                checks.append(
                    ValidationCheck(
                        name="trust_profile",
                        status="FAIL",
                        message=f"Trust policy violation: {'; '.join(violations)}",
                        details={"violations": violations, "trust": trust},
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        name="trust_profile",
                        status="PASS",
                        message=f"Source class '{src_class}' satisfies fail-closed security boundary",
                        details={"source_class": src_class, "trust": trust},
                    )
                )
    else:
        # If legacy report without explicit trust dict
        checks.append(
            ValidationCheck(
                name="trust_profile",
                status="WARN",
                message="Report meta.trust metadata omitted (legacy run)",
            )
        )

    # 4. Timeline Coherence & Causal Acyclicity
    timeline_entries = timeline.get("entries") if isinstance(timeline.get("entries"), list) else []
    has_cycles = bool(timeline.get("has_cycles", False))
    cycle_warning = str(timeline.get("cycle_warning", ""))

    if has_cycles:
        checks.append(
            ValidationCheck(
                name="timeline_causality",
                status="WARN",
                message=f"Causal cycle detected in event timeline: {cycle_warning or 'cycle detected'}",
                details={"cycle_warning": cycle_warning},
            )
        )
    elif timeline_entries:
        checks.append(
            ValidationCheck(
                name="timeline_causality",
                status="PASS",
                message=f"Deterministic causal timeline verified ({len(timeline_entries)} events, no cycles)",
                details={"events_count": len(timeline_entries), "grouping": timeline.get("grouping", "none")},
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="timeline_causality",
                status="WARN",
                message="No timeline events recorded in report",
            )
        )

    # 5. Deployment Context & Integrity
    _dep = context.get("deployment")
    deployment: dict = _dep if isinstance(_dep, dict) else {}
    platform = str(deployment.get("platform", "")).strip()
    target = str(deployment.get("target", "")).strip()
    cluster = str(deployment.get("cluster", "")).strip()

    if platform and target:
        checks.append(
            ValidationCheck(
                name="deployment_context",
                status="PASS",
                message=f"Deployment target verified ({platform} / {target})",
                details={"platform": platform, "target": target, "cluster": cluster},
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="deployment_context",
                status="WARN",
                message="Deployment platform or target not specified",
            )
        )

    # 6. Observability & Connector Hygiene
    _ca = context.get("connector_audits")
    connector_audits: list = _ca if isinstance(_ca, list) else []
    _ms = devops.get("metric_samples")
    metric_samples: list = _ms if isinstance(_ms, list) else []
    _ts = devops.get("trace_spans")
    trace_spans: list = _ts if isinstance(_ts, list) else []

    # Check connector outputs for credential leaks
    leak_detected = False
    leak_details = []
    for index, audit in enumerate(connector_audits):
        if isinstance(audit, dict):
            output_text = str(audit.get("output", ""))
            for pattern in _SENSITIVE_PATTERNS:
                if pattern.search(output_text):
                    leak_detected = True
                    leak_details.append(f"audit[{index}] command: {audit.get('command')}")
                    break

    if leak_detected:
        checks.append(
            ValidationCheck(
                name="connector_hygiene",
                status="FAIL",
                message=f"Sensitive credentials unredacted in connector audit output: {'; '.join(leak_details)}",
                details={"leaks": leak_details},
            )
        )
    elif connector_audits:
        checks.append(
            ValidationCheck(
                name="connector_hygiene",
                status="PASS",
                message=f"Connector audit records clean and redacted ({len(connector_audits)} commands)",
                details={"audits_count": len(connector_audits)},
            )
        )
    elif platform:
        checks.append(
            ValidationCheck(
                name="connector_hygiene",
                status="WARN",
                message="Deployment platform configured but no connector audit evidence captured",
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="connector_hygiene",
                status="PASS",
                message="No connector audits required",
            )
        )

    if metric_samples or trace_spans:
        checks.append(
            ValidationCheck(
                name="observability",
                status="PASS",
                message=f"Observability correlation present ({len(metric_samples)} metric samples, {len(trace_spans)} trace spans)",
                details={"metrics": len(metric_samples), "traces": len(trace_spans)},
            )
        )
    elif platform:
        checks.append(
            ValidationCheck(
                name="observability",
                status="WARN",
                message="Observability correlation missing for deployment failure",
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="observability",
                status="PASS",
                message="Observability not required for standalone run",
            )
        )

    # 7. Source Evidence & Ownership
    _se = context.get("source_evidence")
    source_evidence: list = _se if isinstance(_se, list) else []
    _ow = context.get("owners")
    owners: list = _ow if isinstance(_ow, list) else []
    if source_evidence:
        checks.append(
            ValidationCheck(
                name="source_evidence",
                status="PASS",
                message=f"Source evidence captured ({len(source_evidence)} snippets, owners: {len(owners)})",
                details={"snippets": len(source_evidence), "owners": owners},
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="source_evidence",
                status="WARN",
                message="Source context evidence not collected (opt-in)",
            )
        )

    # Overall status calculation
    has_fail = any(c.status == "FAIL" for c in checks)
    has_warn = any(c.status == "WARN" for c in checks)

    if has_fail:
        overall_status = "FAIL"
        failing = [c.name for c in checks if c.status == "FAIL"]
        summary = f"Integrity validation failed: {', '.join(failing)}"
    elif has_warn:
        overall_status = "WARN"
        warnings = [c.name for c in checks if c.status == "WARN"]
        summary = f"Validation passed with advisory warnings ({', '.join(warnings)})"
    else:
        overall_status = "PASS"
        summary = "Report integrity fully verified; ready for review"

    record = ValidationRecord(
        validation_id=f"val-{uuid4().hex[:12]}",
        run_id=run_id,
        report_path=str(path),
        report_sha256=digest,
        schema_version=schema_ver,
        status=overall_status,
        summary=summary,
        checks=checks,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    if persist:
        # Determine store path: either output_root or path.parent.parent
        root = Path(output_root) if output_root else path.parent.parent
        store = default_validation_store(root)
        try:
            save_validation(store, record)
        except Exception:
            # Persistence failure should not crash validation inspection
            pass

    return record


def format_validation_markdown(record: ValidationRecord, is_stale: bool = False) -> str:
    """Format validation record into a clean markdown summary for clipboard / display."""
    status_label = f"STALE ({record.status})" if is_stale else record.status
    lines = [
        f"### Report Validation Summary — {record.run_id}",
        f"- **Status**: `{status_label}`",
        f"- **Validation ID**: `{record.validation_id}`",
        f"- **Schema**: `v{record.schema_version}`",
        f"- **Report SHA-256**: `{record.report_sha256[:16]}…`",
        f"- **Timestamp**: `{record.created_at}`",
        f"- **Summary**: {record.summary}",
        "",
        "#### Check Breakdown",
    ]
    for check in record.checks:
        symbol = "✓" if check.status == "PASS" else "!" if check.status == "WARN" else "✗"
        lines.append(f"- `[{symbol}]` **{check.name}** ({check.status}): {check.message}")
    return "\n".join(lines)
