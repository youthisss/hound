import json
from pathlib import Path
import sys

import anyio
import pytest

from hound_agent import service
from hound_agent.cli import main
from hound_agent.models import RootCause, Ticket, Triage, build_doc
from tests.conftest import make_artifacts


FIXTURES = Path(__file__).parent / "fixtures"


def _document(*, failure: bool) -> dict:
    artifacts = make_artifacts("pytest_fail.log")
    if not failure:
        artifacts.stage = "unknown"
        artifacts.kind = "unknown"
    root_cause = RootCause(
        hypothesis="Assertion mismatch" if failure else "No supported failure found",
        confidence="high",
        fix_suggestion="Fix expected total" if failure else "No action required",
    )
    return build_doc(
        artifacts,
        root_cause,
        Triage(severity="medium", component="tests", priority=3),
        Ticket(title="test", body_md="body"),
        "2026-08-11T00:00:00+00:00",
    )


def test_no_args_opens_tui_only_on_tty(monkeypatch):
    called = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("hound_agent.cli.run_tui", lambda args: called.append(args) or 0)

    assert main([]) == 0
    assert len(called) == 1


def test_no_args_non_tty_is_actionable(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hound analyze <log-directory>" in captured.err


@pytest.mark.parametrize("path_kind", ["missing", "file", "empty"])
def test_analyze_validates_directory(tmp_path, path_kind, capsys):
    path = tmp_path / path_kind
    if path_kind == "file":
        path.write_text("failure", encoding="utf-8")
    elif path_kind == "empty":
        path.mkdir()

    assert main(["analyze", str(path), "--offline"]) == 2
    assert "error:" in capsys.readouterr().err


def test_json_output_is_valid_and_quiet(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "failure.log").write_text(
        (FIXTURES / "pytest_fail.log").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert main(["analyze", str(logs), "--offline", "--format", "json", "--out", str(tmp_path / "out")]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["count"] == 1
    assert payload["runs"][0]["analysis"]["failure"]["kind"] == "test_failure"


def test_output_file_follows_format(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clean.log").write_text("job complete", encoding="utf-8")
    output = tmp_path / "result.json"

    assert main(["analyze", str(logs), "--offline", "--format", "json", "--output", str(output)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["count"] == 1


def test_init_list_runs_and_clean(tmp_path, capsys):
    config = tmp_path / ".hound-agent.yml"
    assert main(["init", "--config", str(config)]) == 0
    assert config.exists()
    assert main(["init", "--config", str(config)]) == 2
    capsys.readouterr()

    out = tmp_path / "out"
    from hound_agent.output.report import ensure_outdir

    ensure_outdir(out)
    run = out / "sample"
    ensure_outdir(run)
    (run / "report.json").write_text(json.dumps(_document(failure=True)), encoding="utf-8")
    assert main(["list-runs", "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["run_id"] == "sample"
    assert main(["clean", "--out", str(out)]) == 2
    assert main(["clean", "--out", str(out), "--yes"]) == 0
    assert not out.exists()


def test_exit_codes_success_failure_and_internal_error(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("content", encoding="utf-8")

    def fake_runs(failure):
        return [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", _document(failure=failure))]

    monkeypatch.setattr("hound_agent.cli.service.analyze_directory", lambda *args, **kwargs: fake_runs(False))
    assert main(["analyze", str(logs), "--offline"]) == 0
    monkeypatch.setattr("hound_agent.cli.service.analyze_directory", lambda *args, **kwargs: fake_runs(True))
    assert main(["analyze", str(logs), "--offline"]) == 1
    monkeypatch.setattr("hound_agent.cli.service.analyze_directory", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert main(["analyze", str(logs), "--offline"]) == 3


def test_ci_stage_with_unknown_kind_returns_success_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("pipeline failed", encoding="utf-8")
    document = _document(failure=False)
    document["failure"]["stage"] = "ci"
    document["failure"]["kind"] = "unknown"
    monkeypatch.setattr(
        "hound_agent.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )

    assert main(["analyze", str(logs), "--offline"]) == 0


def test_deploy_stage_returns_failure_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("deployment failed", encoding="utf-8")
    document = _document(failure=False)
    document["failure"]["stage"] = "deploy"
    document["failure"]["kind"] = "deployment_failed"
    monkeypatch.setattr(
        "hound_agent.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )

    assert main(["analyze", str(logs), "--offline"]) == 1


def test_deploy_unknown_kind_is_not_a_failure_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    document = _document(failure=False)
    document["failure"]["stage"] = "deploy"
    document["failure"]["kind"] = "unknown"
    monkeypatch.setattr(
        "hound_agent.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )
    assert main(["analyze", str(logs), "--offline"]) == 0


def test_batch_offline_rejects_network_integrations(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("FAILED", encoding="utf-8")
    assert main(["batch", "--logs", str(logs), "--offline", "--gh"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_clean_rejects_current_working_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["clean", "--out", ".", "--yes"]) == 2
    assert "unsafe output path" in capsys.readouterr().err


def test_list_runs_reports_missing_and_malformed_output(tmp_path, capsys):
    assert main(["list-runs", "--out", str(tmp_path / "missing")]) == 2
    root = tmp_path / "out"
    report = root / "run" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text("not-json", encoding="utf-8")
    assert main(["list-runs", "--out", str(root), "--json"]) == 3
    assert "malformed" in capsys.readouterr().err


def test_explicit_cli_does_not_import_tui(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clean.log").write_text("job complete", encoding="utf-8")
    sys.modules.pop("hound_agent.tui", None)

    assert main(["analyze", str(logs), "--offline"]) == 0
    assert "hound_agent.tui" not in sys.modules


def test_directory_run_ids_and_formatted_paths_do_not_leak_log_name(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "person@example.com.log").write_text("12 passed", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["analyze", str(logs), "--offline", "--format", "json", "--out", str(out)]) == 0
    rendered = capsys.readouterr().out
    assert "person@example.com" not in rendered
    run_dirs = [path for path in out.iterdir() if path.is_dir() and path.name.startswith("run-")]
    assert len(run_dirs) == 1


def test_integration_reload_preserves_cli_provider_override(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: anthropic\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("12 passed", encoding="utf-8")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GH_REPO", raising=False)
    assert main([
        "analyze", str(logs), "--out", str(tmp_path / "out"), "--config", str(config),
        "--provider", "openai", "--gh",
    ]) == 3
    assert "requires GH_REPO and GH_TOKEN" in capsys.readouterr().err


def test_offline_rejects_network_integrations(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("failure", encoding="utf-8")

    assert main(["analyze", str(logs), "--offline", "--gh"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_config_set_model_preserves_config(tmp_path, capsys):
    config = tmp_path / ".hound-agent.yml"
    config.write_text("redact: true\ncomponents:\n  src/*: core\n", encoding="utf-8")

    assert main(["config", "set", "model", "gemini", "--config", str(config)]) == 0
    text = config.read_text(encoding="utf-8")
    assert "components:" in text
    assert "provider: gemini" in text
    assert "model: gemini-2.0-flash" in text
    assert "API" not in capsys.readouterr().out


def test_report_reads_run_by_id(tmp_path, capsys):
    run_dir = tmp_path / "runs" / "build"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(json.dumps(_document(failure=True)), encoding="utf-8")

    assert main(["report", "build", "--out", str(tmp_path / "runs"), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["root_cause"]["confidence"] == "high"


def test_tui_and_cli_use_shared_service(tmp_path, monkeypatch):
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView

    log = tmp_path / "run.log"
    log.write_text("failure", encoding="utf-8")
    calls = []

    def fake_analyze(log_path, output_dir, **kwargs):
        calls.append(Path(log_path))
        return _document(failure=True)

    monkeypatch.setattr("hound_agent.service.analyze_log", fake_analyze)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#log-list", ListView).index = 0
            app.action_analyze()
            for _ in range(100):
                if calls:
                    break
                await pilot.pause(0.02)

    anyio.run(exercise)
    assert calls == [log]
