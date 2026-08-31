"""Application service for bounded QA gate execution."""
from __future__ import annotations

import os
import hashlib
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Any

from hound.ingest.redact import redact_text
from hound.qa.classifier import classify_run_results
from hound.qa.coverage import get_git_changed_lines, merge_coverage, parse_coverage_artifact
from hound.qa.gate import GateResult, evaluate_gate, load_gate_policy
from hound.qa.normalize import import_artifact
from hound.qa.sarif import merge_sarif, parse_sarif_artifact
from hound.executables import trusted_executable

MAX_ARTIFACT_FILES = 1000
MAX_TOTAL_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_COLLECTION_SECONDS = 10.0
MAX_GATE_SECONDS = 30.0
MAX_NORMALIZED_TEST_RESULTS = 10000
MAX_HISTORY_BYTES = 256 * 1024 * 1024
_TEST_SUFFIXES = {".xml", ".json", ".log", ".txt"}
_COVERAGE_SUFFIXES = {".xml", ".json", ".info", ".lcov"}


def _safe_path(path: Path) -> str:
    return redact_text(str(path))[0][:1000]


def _observed_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _history_snapshot(source: Path, destination: Path, deadline: float) -> dict[str, object]:
    try:
        source_size = source.stat().st_size
    except OSError as exc:
        raise ValueError(f"could not inspect history store: {exc}") from exc
    if source_size > MAX_HISTORY_BYTES:
        raise ValueError("history store exceeds the 256 MiB limit")

    def check_progress(status: int, remaining: int, total: int) -> None:
        del status, remaining, total
        if time.monotonic() > deadline:
            raise ValueError("history snapshot exceeded the QA gate deadline")
        try:
            if destination.exists() and destination.stat().st_size > MAX_HISTORY_BYTES:
                raise ValueError("history snapshot exceeds the 256 MiB limit")
        except OSError as exc:
            raise ValueError(f"could not inspect history snapshot: {exc}") from exc

    try:
        source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as source_connection:
            with closing(sqlite3.connect(destination)) as destination_connection:
                with destination_connection:
                    source_connection.backup(destination_connection, pages=256, progress=check_progress, sleep=0.01)
        digest = hashlib.sha256()
        snapshot_bytes = 0
        with destination.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                if time.monotonic() > deadline:
                    raise ValueError("history hashing exceeded the QA gate deadline")
                snapshot_bytes += len(chunk)
                digest.update(chunk)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise ValueError(f"could not snapshot history store: {exc}") from exc
    return {
        "source": _safe_path(source),
        "sha256": digest.hexdigest(),
        "bytes": snapshot_bytes,
        "observed_at": _observed_at(source),
    }


def _discover_artifacts(source: Path, deadline: float) -> list[Path]:
    if not source.exists() or source.is_symlink():
        raise ValueError(f"artifact path is not a readable regular file or directory: {source}")
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise ValueError(f"artifact path is not a directory: {source}")

    discovery_deadline = min(deadline, time.monotonic() + MAX_COLLECTION_SECONDS)
    discovered: list[Path] = []
    total_bytes = 0
    for root, directories, files in os.walk(source, followlinks=False):
        if time.monotonic() > discovery_deadline:
            raise ValueError("artifact discovery exceeded the allowed time limit")
        directories[:] = sorted(
            name for name in directories if not (Path(root) / name).is_symlink()
        )
        for name in sorted(files):
            if time.monotonic() > discovery_deadline:
                raise ValueError("artifact discovery exceeded the allowed time limit")
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise ValueError(f"could not inspect artifact {path}: {exc}") from exc
            discovered.append(path)
            total_bytes += size
            if len(discovered) > MAX_ARTIFACT_FILES:
                raise ValueError(f"artifact collection exceeds {MAX_ARTIFACT_FILES} files")
            if total_bytes > MAX_TOTAL_ARTIFACT_BYTES:
                raise ValueError("artifact collection exceeds the 128 MiB aggregate limit")
    return discovered


def _validate_collection_limits(paths: list[Path], deadline: float) -> None:
    unique = list(dict.fromkeys(paths))
    if len(unique) > MAX_ARTIFACT_FILES:
        raise ValueError(f"artifact collection exceeds {MAX_ARTIFACT_FILES} files")
    total_bytes = 0
    for path in unique:
        if time.monotonic() > deadline:
            raise ValueError("artifact collection exceeded the QA gate deadline")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"explicit artifact is not a readable regular file: {path}")
        try:
            total_bytes += path.stat().st_size
        except OSError as exc:
            raise ValueError(f"could not inspect artifact {path}: {exc}") from exc
    if total_bytes > MAX_TOTAL_ARTIFACT_BYTES:
        raise ValueError("artifact collection exceeds the 128 MiB aggregate limit")


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_") and key != "SSH_ASKPASS"
    }
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return environment


def _validate_git_context(repo: Path, baseline: str, head: str, timeout: float) -> tuple[str, str]:
    if not repo.is_dir() or repo.is_symlink():
        raise ValueError(f"repository is not a readable directory: {repo}")
    executable = trusted_executable("git", repo)
    if not executable:
        raise ValueError("trusted Git executable not found")
    resolved: list[str] = []
    for label, revision in (("baseline", baseline), ("head", head)):
        if not revision or revision.startswith("-") or "\x00" in revision:
            raise ValueError(f"{label} Git ref is invalid")
        try:
            process = subprocess.run(
                [
                    executable, "-C", str(repo),
                    "-c", "core.fsmonitor=false",
                    "-c", f"core.hooksPath={os.devnull}",
                    "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}",
                ],
                capture_output=True,
                text=True,
                timeout=max(0.1, min(15.0, timeout)),
                check=False,
                shell=False,
                env=_git_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f"could not validate {label} Git ref: {exc}") from exc
        if process.returncode != 0:
            raise ValueError(f"{label} Git ref does not resolve to a commit: {revision}")
        resolved.append(process.stdout.strip())
    return resolved[0], resolved[1]


def run_quality_gate(
    source_path: str | Path,
    *,
    baseline: str,
    head: str,
    repo_path: str | Path,
    policy_path: str | Path,
    coverage_paths: list[str | Path] | None = None,
    baseline_coverage_paths: list[str | Path] | None = None,
    sarif_paths: list[str | Path] | None = None,
    environment: str = "",
    runner: str | None = None,
    history_store: str | Path | None = None,
    enforced: bool = True,
    output_dir: str | Path | None = None,
) -> GateResult:
    """Normalize bounded evidence and evaluate one deterministic policy."""
    deadline = time.monotonic() + MAX_GATE_SECONDS

    def check_deadline() -> None:
        if time.monotonic() > deadline:
            raise ValueError("QA gate evidence processing exceeded the 30 second limit")

    source = Path(source_path)
    repo = Path(repo_path).resolve()
    baseline_sha, head_sha = _validate_git_context(repo, baseline, head, deadline - time.monotonic())
    check_deadline()
    candidates = _discover_artifacts(source, deadline)
    explicit_coverage = [Path(value) for value in coverage_paths or []]
    explicit_baseline_coverage = [Path(value) for value in baseline_coverage_paths or []]
    explicit_sarif = [Path(value) for value in sarif_paths or []]
    _validate_collection_limits(candidates + explicit_coverage + explicit_baseline_coverage + explicit_sarif, deadline)

    store: Path | None = None
    if history_store is not None:
        store = Path(history_store)
        if not store.is_file() or store.is_symlink():
            raise ValueError(f"history store is not a readable regular file: {store}")

    evidence_paths = list(dict.fromkeys(
        candidates + explicit_coverage + explicit_baseline_coverage + explicit_sarif
    ))
    provenance: list[dict[str, Any]] = [
        {
            "id": f"artifact-{index:04d}",
            "source_type": "artifact",
            "artifact": _safe_path(path),
            "collector": "hound.qa.service",
            "observed_at": _observed_at(path),
        }
        for index, path in enumerate(evidence_paths, 1)
    ]
    provenance_by_path = {path: item for path, item in zip(evidence_paths, provenance)}

    test_results = []
    rejected_structured_tests: dict[Path, str] = {}
    for item in candidates:
        check_deadline()
        if item.suffix.lower() not in _TEST_SUFFIXES:
            continue
        try:
            imported = import_artifact(item, "", "", "", environment, runner=runner)
        except ValueError as exc:
            if item.suffix.lower() in {".json", ".xml"}:
                rejected_structured_tests[item] = str(exc)
            continue
        artifact_record = provenance_by_path[item]
        artifact_id = str(artifact_record["id"])
        for index, test_result in enumerate(imported, 1):
            test_result.evidence_id = f"{artifact_id}-test-{index:04d}"
            provenance.append({
                "id": test_result.evidence_id,
                "source_type": "normalized_test_result",
                "artifact": artifact_record["artifact"],
                "parent_evidence_id": artifact_id,
                "collector": "hound.qa.normalize",
                "observed_at": artifact_record["observed_at"],
            })
        test_results.extend(imported)
    if len(test_results) > MAX_NORMALIZED_TEST_RESULTS:
        raise ValueError(f"normalized test evidence exceeds {MAX_NORMALIZED_TEST_RESULTS} results")
    unique_results = []
    seen_results: dict[tuple[str, str, int], tuple[object, ...]] = {}
    for test_result in test_results:
        key = (test_result.suite, test_result.test, test_result.attempt)
        signature = (
            test_result.status,
            test_result.duration_ms,
            test_result.failure_signature,
            test_result.environment,
        )
        previous = seen_results.get(key)
        if previous is not None and previous != signature:
            raise ValueError(
                f"conflicting test evidence for {test_result.suite}::{test_result.test} attempt {test_result.attempt}"
            )
        if previous is None:
            seen_results[key] = signature
            unique_results.append(test_result)
    test_results = unique_results
    history_provenance: dict[str, object] | None = None
    if store is not None:
        with tempfile.TemporaryDirectory(prefix="hound-gate-history-") as temp_directory:
            snapshot = Path(temp_directory) / "history.sqlite3"
            history_provenance = _history_snapshot(store, snapshot, deadline)
            provenance.append({
                "id": "history-snapshot",
                "source_type": "history_snapshot",
                "artifact": history_provenance["source"],
                "collector": "hound.qa.service",
                "observed_at": history_provenance["observed_at"],
                "sha256": history_provenance["sha256"],
            })
            classifications = classify_run_results(
                store_path=snapshot,
                results=test_results,
                baseline_commit=baseline_sha,
                days=None,
                deadline=deadline,
                repo_dir=repo,
                feedback_store_path=Path(output_dir) / ".hound" / "feedback.sqlite3" if output_dir else None,
            )
    else:
        classifications = classify_run_results(
            store_path=None,
            results=test_results,
            baseline_commit=baseline_sha,
            days=None,
            deadline=deadline,
            repo_dir=repo,
            feedback_store_path=Path(output_dir) / ".hound" / "feedback.sqlite3" if output_dir else None,
        )
    check_deadline()

    coverage_candidates = explicit_coverage + [
        item for item in candidates
        if item.suffix.lower() in _COVERAGE_SUFFIXES and item not in explicit_baseline_coverage
    ]
    coverage_reports = []
    parsed_coverage_paths: set[Path] = set()
    for item in dict.fromkeys(coverage_candidates):
        check_deadline()
        parsed_coverage = parse_coverage_artifact(item)
        if parsed_coverage is None:
            if item in explicit_coverage:
                raise ValueError(f"explicit coverage artifact is invalid or unsupported: {item}")
            continue
        coverage_reports.append(parsed_coverage)
        parsed_coverage_paths.add(item)
        check_deadline()
    coverage = merge_coverage(coverage_reports)

    baseline_coverage_reports = []
    parsed_baseline_coverage_paths: set[Path] = set()
    for item in dict.fromkeys(explicit_baseline_coverage):
        check_deadline()
        parsed_baseline_coverage = parse_coverage_artifact(item)
        if parsed_baseline_coverage is None:
            raise ValueError(f"explicit baseline coverage artifact is invalid or unsupported: {item}")
        baseline_coverage_reports.append(parsed_baseline_coverage)
        parsed_baseline_coverage_paths.add(item)
        check_deadline()
    baseline_coverage = merge_coverage(baseline_coverage_reports)

    sarif_candidates = explicit_sarif + [item for item in candidates if item.suffix.lower() == ".sarif"]
    sarif_reports = []
    parsed_sarif_paths: set[Path] = set()
    for item in dict.fromkeys(sarif_candidates):
        check_deadline()
        parsed_sarif = parse_sarif_artifact(item)
        if parsed_sarif is None:
            if item in explicit_sarif:
                raise ValueError(f"explicit SARIF artifact is invalid or unsupported: {item}")
            continue
        sarif_reports.append(parsed_sarif)
        parsed_sarif_paths.add(item)
        check_deadline()
    sarif = merge_sarif(sarif_reports)

    invalid_structured = [
        item for item in rejected_structured_tests
        if item not in parsed_coverage_paths
        and item not in parsed_baseline_coverage_paths
        and item not in parsed_sarif_paths
    ]
    if invalid_structured:
        item = invalid_structured[0]
        raise ValueError(f"structured QA artifact is invalid or unsupported: {item}: {rejected_structured_tests[item]}")

    if not classifications and coverage is None and sarif is None:
        raise ValueError(f"no supported QA evidence found in {source}")
    changed_lines = get_git_changed_lines(
        repo, baseline_sha, head_sha, deadline - time.monotonic()
    ) if coverage is not None else None
    check_deadline()
    if coverage is not None and changed_lines is None:
        raise ValueError(f"could not diff explicit range {baseline!r}...{head!r} in {repo}")

    result = evaluate_gate(
        load_gate_policy(policy_path),
        classifications,
        coverage,
        changed_lines,
        sarif,
        baseline_coverage,
        environment=environment,
        enforced=enforced,
        provenance=provenance,
    )
    check_deadline()
    result.summary.update({
        "baseline": {"requested": baseline, "commit": baseline_sha},
        "head": {"requested": head, "commit": head_sha},
        "repository": _safe_path(repo),
        "history_store": history_provenance,
        "source_artifacts": provenance,
    })
    return result
