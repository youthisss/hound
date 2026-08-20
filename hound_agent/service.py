"""Shared application service used by CLI and TUI adapters."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from uuid import uuid4
from hound_agent.config import load_config
from hound_agent.pipeline import default_state_path

from hound_agent.pipeline import analyze as _analyze_pipeline
from hound_agent.output.report import ensure_outdir


SUPPORTED_LOG_SUFFIXES = {".log", ".xml", ".sarif", ".json"}


class AnalysisInputError(ValueError):
    """Raised when an analysis input path is invalid or unusable."""


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    log_path: Path
    output_dir: Path
    document: dict


def find_logs(log_directory: str | Path) -> list[Path]:
    """Return supported logs from one directory without recursive scanning."""
    directory = Path(log_directory).expanduser()
    if not directory.exists():
        raise AnalysisInputError(f"log directory does not exist: {directory}")
    if not directory.is_dir():
        raise AnalysisInputError(f"expected a log directory, got file: {directory}")
    if not os.access(directory, os.R_OK):
        raise AnalysisInputError(f"log directory is not readable: {directory}")
    root = directory.resolve()
    try:
        logs = sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(root)
                and path.suffix.lower() in SUPPORTED_LOG_SUFFIXES
                and not _is_sidecar(path)
            ),
            key=lambda path: path.name.lower(),
        )
    except OSError as exc:
        raise AnalysisInputError(f"cannot read log directory {directory}: {exc}") from exc
    if not logs:
        raise AnalysisInputError(
                f"no supported artifacts found in {directory}; add a .log, JUnit .xml, or .sarif file"
        )
    return logs


def _is_sidecar(path: Path) -> bool:
    """Collector writes `<log>.json`; it is context, never an input artifact."""
    return path.suffix.lower() == ".json" and path.with_suffix(".log").is_file()


def analyze_log(log_path: str | Path, output_dir: str | Path, **kwargs) -> dict:
    """Run shared analysis pipeline for one log."""
    return _analyze_pipeline(log_path, output_dir, **kwargs)


def analyze_directory(
    log_directory: str | Path,
    output_root: str | Path,
    **kwargs,
) -> list[AnalysisRun]:
    """Analyze supported logs in one directory using isolated run directories."""
    logs = find_logs(log_directory)
    root = ensure_outdir(output_root)
    config = load_config(
        offline=bool(kwargs.get("offline", False)),
        config_path=kwargs.get("config_path"),
        provider=kwargs.get("provider"),
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        api_key=kwargs.get("api_key"),
        redact=kwargs.get("redact"),
        max_retries=kwargs.get("max_retries"),
    )
    state_path = default_state_path(root, config.state_file, bool(kwargs.get("no_dedup", False)))
    runs: list[AnalysisRun] = []
    for log_path in logs:
        run_id = f"run-{uuid4().hex[:12]}"
        run_output = root / run_id
        document = analyze_log(log_path, run_output, state_path=state_path, _config=config, **kwargs)
        runs.append(AnalysisRun(run_id, log_path, run_output, document))
    return runs


def has_ci_failure(runs: list[AnalysisRun]) -> bool:
    """Return whether completed analysis found a CI/CD failure."""
    return any(run.document.get("failure", {}).get("kind") != "unknown" for run in runs)
