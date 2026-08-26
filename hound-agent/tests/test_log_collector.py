import io
import json
from pathlib import Path
import sys

from hound_agent.cli import main
from hound_agent.collector import collect_command


class Pipe(io.StringIO):
    def isatty(self):
        return False


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_log_command_tees_redacts_and_preserves_exit(tmp_path, capsys):
    script = (
        "import sys; "
        "print('test failed token=supersecretvalue'); "
        "print('stderr line', file=sys.stderr); "
        "raise SystemExit(7)"
    )
    output = tmp_path / "captured.log"

    code = main(["log", "--output", str(output), "--", sys.executable, "-c", script])

    assert code == 7
    captured = capsys.readouterr()
    assert "supersecretvalue" not in captured.out
    assert "[REDACTED:password]" in captured.out
    assert "stderr line" in captured.out
    persisted = output.read_text(encoding="utf-8")
    assert "supersecretvalue" not in persisted
    assert "[REDACTED:password]" in persisted
    metadata = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["source"] == "command"
    assert metadata["exit_code"] == 7
    assert metadata["command"][0] == sys.executable
    assert metadata["duration_ms"] >= 0


def test_log_reads_piped_stdin(tmp_path, monkeypatch, capsys):
    output = tmp_path / "pipe.log"
    monkeypatch.setattr(sys, "stdin", Pipe("pytest FAILED\npassword=hunter2\n"))

    assert main(["log", "--name", "pytest", "--output", str(output)]) == 0
    assert "pytest FAILED" in capsys.readouterr().out
    persisted = output.read_text(encoding="utf-8")
    assert "hunter2" not in persisted
    metadata = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["source"] == "stdin"
    assert metadata["name"] == "pytest"


def test_log_rejects_missing_or_empty_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", Tty())
    assert main(["log", "--output", str(tmp_path / "none.log")]) == 2
    assert "hound log -- <command>" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", Pipe())
    assert main(["log", "--output", str(tmp_path / "empty.log")]) == 2
    assert "piped stdin was empty" in capsys.readouterr().err


def test_log_rejects_missing_command(tmp_path, capsys):
    assert main(["log", "--output", str(tmp_path / "x.log"), "--", "missing-hound_agent-command"]) == 2
    assert "command not found" in capsys.readouterr().err


def test_log_metadata_redacts_sensitive_arguments(tmp_path):
    output = tmp_path / "args.log"
    result = collect_command(
        [sys.executable, "-c", "print('ok')", "--token", "plain-secret", "--api-key=other-secret"],
        output=output,
        stream=io.StringIO(),
    )
    metadata = json.loads(result.metadata_file.read_text(encoding="utf-8"))
    serialized = json.dumps(metadata)
    assert "plain-secret" not in serialized
    assert "other-secret" not in serialized
    assert "[REDACTED:argument]" in serialized


def test_log_analyze_uses_shared_service(tmp_path, monkeypatch, capsys):
    output = tmp_path / "analyze.log"
    calls = []
    document = json.loads(
        (Path(__file__).parent / "golden" / "rca-v2.0.json").read_text(encoding="utf-8")
    )
    document["failure"].update(stage="test", kind="test_failure")
    document["root_cause"].update(hypothesis="failure", confidence="high", fix_suggestion="fix it")
    document["triage"]["severity"] = "high"

    def fake_analyze(log_path, output_dir, **kwargs):
        calls.append((Path(log_path), Path(output_dir), kwargs))
        return document

    monkeypatch.setattr("hound_agent.cli.service.analyze_log", fake_analyze)
    code = main([
        "log", "--analyze", "--offline", "--output", str(output), "--",
        sys.executable, "-c", "print('FAILED')",
    ])

    assert code == 0
    assert calls[0][0] == output
    assert calls[0][2]["offline"] is True
    assert calls[0][2]["state_path"].endswith("hound-agent-output\\.hound-agent\\state.json") or calls[0][2]["state_path"].endswith("hound-agent-output/.hound-agent/state.json")
    assert "severity: high" in capsys.readouterr().err


def test_log_analysis_error_maps_to_internal_error(tmp_path, monkeypatch, capsys):
    output = tmp_path / "analyze-error.log"
    monkeypatch.setattr(
        "hound_agent.cli.service.analyze_log",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("analysis boom")),
    )

    code = main([
        "log", "--analyze", "--output", str(output), "--",
        sys.executable, "-c", "print('ok')",
    ])

    assert code == 3
    assert output.exists()
    assert "captured log analysis failed" in capsys.readouterr().err


def test_log_refuses_to_overwrite_existing_output(tmp_path):
    output = tmp_path / "existing.log"
    output.write_text("important", encoding="utf-8")
    assert main(["log", "--output", str(output), "--", "ignored"]) == 2
    assert output.read_text(encoding="utf-8") == "important"
