import json

import pytest

from hound.analyze.rca import run_analysis
from hound.cli import build_parser, run_analyze
from hound.config import Config
from hound.models import validate
from hound.pipeline import analyze
from tests.conftest import make_artifacts


def test_pipeline_analyze_returns_doc(tmp_path):
    log = tmp_path / "pytest_fail.log"
    log.write_text(
        (__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "pytest_fail.log").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    doc = analyze(log, out, offline=True)
    validate(doc)
    assert (out / "report.json").exists()
    assert (out / "report.md").exists()
    assert (out / "ticket.md").exists()
    assert doc["meta"]["engine"] == "fallback"


def test_pipeline_analyze_missing_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        analyze(tmp_path / "nope.log", tmp_path / "out")


def test_pipeline_warns_when_reuse_snapshot_is_not_persisted(tmp_path, monkeypatch, capsys):
    log = tmp_path / "pytest_fail.log"
    log.write_text(
        (__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "pytest_fail.log").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("hound.pipeline.record_triage", lambda *_args, **_kwargs: False)

    analyze(log, tmp_path / "out", offline=True)

    assert "reuse snapshot was not persisted" in capsys.readouterr().err


def test_pipeline_extracts_and_redacts_request_context(tmp_path):
    log = tmp_path / "request.log"
    log.write_text(
        "pytest\n"
        "request_id=req_checkout user_id=alice@example.test method=POST path=/api/checkout\n"
        "FAILED tests/test_cart.py::test_total - AssertionError\n",
        encoding="utf-8",
    )

    doc = analyze(log, tmp_path / "out", offline=True, no_dedup=True)

    request = doc["context"]["request"]
    assert request["request_id"] == "req_checkout"
    assert request["user_id"] == "[REDACTED:email]"
    assert request["users"] == ["[REDACTED:email]"]
    assert (request["method"], request["path"]) == ("POST", "/api/checkout")
    assert doc["meta"]["redacted"] is True
    assert "alice@example.test" not in json.dumps(doc)


def test_pipeline_legacy_log_has_empty_request_context(tmp_path):
    log = tmp_path / "plain_fail.log"
    log.write_text((__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "plain_fail.log").read_text(encoding="utf-8"), encoding="utf-8")

    doc = analyze(log, tmp_path / "out", offline=True, no_dedup=True)

    assert doc["context"]["request"] == {
        "request_id": "",
        "trace_id": "",
        "session_id": "",
        "user_id": "",
        "users": [],
        "method": "",
        "path": "",
    }
    validate(doc)
def test_offline_pipeline_deterministic(tmp_path):
    from hound.triage.component import assign
    from hound.triage.dedup import check_duplicate
    from hound.triage.severity import classify
    from hound.output.report import write_json
    from hound.models import build_doc
    from hound.output.tickets import build_ticket

    a = make_artifacts("pytest_fail.log", changed_files=["app/cart.py"])
    rc = run_analysis(a, Config(offline=True))
    sev, pri = classify(a)
    t = check_duplicate(a, str(tmp_path / "state.json"))
    t.severity = sev
    t.priority = pri
    t.component = assign(a, {})
    doc = build_doc(a, rc, t, build_ticket(a, rc, t), "2026-01-01T00:00:00Z")
    validate(doc)
    p = write_json(doc, tmp_path / "out")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["meta"]["engine"] == "fallback"
    assert data["triage"]["severity"] in {"critical", "high", "medium", "low"}
    assert data["triage"]["component"] == "tests"


def test_cli_run_analyze_namespace(tmp_path, fake_repo):
    repo, path = fake_repo

    log = tmp_path / "pytest_fail.log"
    log.write_text(
        (__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "pytest_fail.log").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        [
            "analyze",
            "--log",
            str(log),
            "--repo",
            str(path),
            "--out",
            str(tmp_path / "out"),
            "--offline",
        ]
    )
    code = run_analyze(args)
    assert code == 1
    report = (tmp_path / "out" / "report.json").read_text(encoding="utf-8")
    doc = json.loads(report)
    validate(doc)
