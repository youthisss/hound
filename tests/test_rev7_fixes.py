"""Regression tests for the rev-7 fix pass (REVIEW.md rev-6 findings).

Covers: BUG-1 (Windows stale-lock detection), BUG-2 (vacuous stale-lock
test path), G1 (collector sidecar auto-load), G2 (batch artifact shapes),
G3 (unknown-kind logs skip the dedup store), plus minor cleanups
(ANSI suppression on redirect, validate() message accuracy).
"""
from __future__ import annotations

import gc
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

JUNIT_XML = (
    "<testsuite name='suite' tests='1' failures='1'>"
    "<testcase classname='pkg' name='test_total'><failure message='boom'>"
    "assert 2 == 3\nAssertionError: boom</failure></testcase>"
    "</testsuite>"
)


# ---------------------------------------------------------------- BUG-1


def test_pid_alive_reports_dead_process_as_dead():
    """A reaped child's PID must be reported dead on every platform.

    Windows raises plain OSError (winerror 87) instead of
    ProcessLookupError; the pre-fix code treated that as "alive".
    """
    from hound_agent.triage.dedup import _pid_alive

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid
    del proc
    gc.collect()
    time.sleep(0.05)
    assert _pid_alive(dead_pid) is False
    # A PID that cannot exist must also be dead, never "alive".
    assert _pid_alive(99999999) is False


def test_pid_alive_reports_live_process_as_alive():
    from hound_agent.triage.dedup import _pid_alive

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.3)
        assert proc.poll() is None
        assert _pid_alive(proc.pid) is True
    finally:
        proc.kill()
        proc.wait()
    # Release the Popen handle: while any handle stays open, Windows keeps
    # the PID valid and even a reaped process probes as "alive".
    dead_pid = proc.pid
    del proc
    gc.collect()
    time.sleep(0.05)
    assert _pid_alive(dead_pid) is False


def test_live_owner_lock_blocks_but_dead_owner_lock_recovered(tmp_path, monkeypatch):
    """Discrimination proof: a live owner keeps blocking; a dead one recovers."""
    import os

    from hound_agent.triage import dedup
    from tests.conftest import make_artifacts

    monkeypatch.setattr(dedup, "_LOCK_RETRIES", 3)
    monkeypatch.setattr(dedup, "_LOCK_RETRY_DELAY", 0.01)

    make_artifacts("pytest_fail.log")
    state = str(tmp_path / "state.json")
    lock = Path(state).with_suffix(".lock")

    lock.write_text(f"{os.getpid()}:live-owner", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dedup lock"):
        with dedup._state_lock(state):
            pass  # pragma: no cover

    lock.write_text("99999999:dead-owner", encoding="utf-8")
    with dedup._state_lock(state):
        assert True  # stale lock was broken and acquired
    assert not lock.exists()


# ---------------------------------------------------------------- G3


def test_unknown_kind_never_touches_dedup_store(tmp_path, capsys):
    from hound_agent import service
    from hound_agent.triage.dedup import load_state

    healthy = tmp_path / "healthy.log"
    healthy.write_text("everything fine\nbuild finished\nexit code 0\n", encoding="utf-8")
    out = tmp_path / "out"

    doc = service.analyze_log(healthy, out, offline=True)

    assert doc["failure"]["kind"] == "unknown"
    assert doc["triage"]["dedup_key"]  # key still reported for traceability
    state_file = out / ".hound-agent" / "state.json"
    assert load_state(str(state_file)) == []
    capsys.readouterr()


def test_unknown_kind_skips_occurrence_counting_across_runs(tmp_path):
    from hound_agent import service
    from hound_agent.triage.dedup import load_state

    healthy = tmp_path / "healthy.log"
    healthy.write_text("still fine\nexit code 0\n", encoding="utf-8")
    state_path = str(tmp_path / "state.json")
    for _ in range(3):
        service.analyze_log(healthy, tmp_path / f"out{_}", offline=True, state_path=state_path)
    assert load_state(state_path) == []


# ---------------------------------------------------------------- G1


def test_collector_sidecar_autoloaded_as_context(tmp_path):
    from hound_agent import service

    log = tmp_path / "app.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    sidecar = tmp_path / "app.json"
    sidecar.write_text(
        json.dumps({"run": {"provider": "custom-ci", "run_id": "R-42"}}),
        encoding="utf-8",
    )

    doc = service.analyze_log(log, tmp_path / "out", offline=True)

    assert doc["context"]["run"]["provider"] == "custom-ci"
    assert doc["context"]["run"]["run_id"] == "R-42"


def test_explicit_context_wins_over_sidecar(tmp_path):
    from hound_agent.ingest.context import load_context

    log = tmp_path / "x.log"
    log.write_text("hello\n", encoding="utf-8")
    (tmp_path / "x.json").write_text(json.dumps({"run": {"provider": "sidecar"}}), encoding="utf-8")
    explicit = tmp_path / "ctx.json"
    explicit.write_text(json.dumps({"run": {"provider": "explicit"}}), encoding="utf-8")

    run, _ = load_context(log, "", str(explicit))
    assert run.provider == "explicit"


# ---------------------------------------------------------------- G2


def test_batch_picks_up_junit_and_log(tmp_path, capsys):
    from hound_agent.cli import main

    logs_dir = tmp_path / "artifacts"
    logs_dir.mkdir()
    (logs_dir / "junit.xml").write_text(JUNIT_XML, encoding="utf-8")
    shutil.copy(FIXTURES / "flaky.log", logs_dir / "flaky.log")

    code = main(["batch", "--logs", str(logs_dir), "--out", str(tmp_path / "out"), "--offline"])

    assert code == 1  # at least one recognized failure
    summaries = list((tmp_path / "out").glob("summary-*.json"))
    assert summaries, "summary file missing"
    rows = json.loads(summaries[0].read_text(encoding="utf-8"))
    # Both artifacts must be analyzed and classified (stage non-empty), without
    # pinning the exact stage labels — detector wording may evolve.
    assert len(rows) == 2
    assert all(row["stage"] for row in rows)
    capsys.readouterr()


def test_batch_ignores_collector_sidecars(tmp_path, capsys):
    from hound_agent.cli import main

    logs_dir = tmp_path / "artifacts"
    logs_dir.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", logs_dir / "job.log")
    (logs_dir / "job.json").write_text(json.dumps({"source": "sidecar"}), encoding="utf-8")

    code = main(["batch", "--logs", str(logs_dir), "--out", str(tmp_path / "out"), "--offline"])

    assert code == 1
    summaries = list((tmp_path / "out").glob("summary-*.json"))
    rows = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert len(rows) == 1  # only job.log analyzed; job.json is a sidecar
    capsys.readouterr()


# ---------------------------------------------------------------- minors


def test_print_result_suppresses_ansi_when_redirected(tmp_path, capsys, monkeypatch):
    from hound_agent.cli import _print_result

    doc = {
        "failure": {"stage": "test", "kind": "test_failure"},
        "triage": {
            "severity": "high",
            "component": "cart",
            "is_duplicate_of": None,
            "flaky_suspect": False,
            "dedup_key": "a" * 64,
        },
        "meta": {"engine": "fallback"},
    }
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    _print_result(doc, tmp_path)

    out = capsys.readouterr().out
    assert "\033[" not in out


def test_validate_names_duration_ms_in_error():
    from hound_agent.models import (
        Artifacts,
        RootCause,
        Ticket,
        Triage,
        build_doc,
        validate,
    )
    from tests.conftest import make_artifacts

    artifacts: Artifacts = make_artifacts("pytest_fail.log")
    doc = build_doc(
        artifacts,
        RootCause(hypothesis="h", confidence="low", fix_suggestion="f"),
        Triage(severity="medium", component="c", priority=3),
        Ticket(title="t", body_md="b"),
        "2026-08-24T00:00:00+00:00",
    )
    doc["context"]["run"]["duration_ms"] = -5
    with pytest.raises(ValueError, match="duration_ms"):
        validate(doc)


# ---------------------------------------------------------------- G8 (TUI)


def _write_app(tmp_path: Path):
    from hound_agent.tui import RcaTui

    return RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)


def test_tui_analyze_all_processes_visible_logs(tmp_path):
    from textual.widgets import Static

    from hound_agent.tui import RcaTui

    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "a.log")
    shutil.copy(FIXTURES / "flaky.log", tmp_path / "b.log")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app._log_files) == 2
            await pilot.press("A")
            for _ in range(600):
                await pilot.pause(0.02)
                if not app._analyzing and len(app._runs) >= 2:
                    break
            assert not app._analyzing
            reports = list((tmp_path / "out").glob("*/report.md"))
            assert len(reports) == 2
            overview = str(app.query_one("#overview", Static).renderable)
            assert "Batch analysis complete" in overview
            assert "Analyzed [b]2/2[/b]" in overview

    anyio.run(main)


def test_tui_analyze_all_empty_selection_is_noop(tmp_path):
    from textual.widgets import Button, Static

    app = _write_app(tmp_path)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_analyze_all()
            await pilot.pause()
            assert not app._analyzing
            assert "No visible logs" in str(app.query_one("#workflow-status", Static).renderable)
            assert app.query_one("#analyze-all", Button).disabled

    anyio.run(main)


def test_tui_lists_structured_artifacts_alongside_logs(tmp_path):
    from textual.widgets import ListView, Static

    app = _write_app(tmp_path)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            (tmp_path / "junit.xml").write_text(JUNIT_XML, encoding="utf-8")
            app.action_refresh()
            await pilot.pause()
            items = app.query_one("#log-list", ListView)
            names = {str(child.query_one(Static).renderable).splitlines()[0].split()[0] for child in items.children}
            assert names == {"junit.xml"}
            assert "TEST" in str(items.children[0].query_one(Static).renderable)

    anyio.run(main)
