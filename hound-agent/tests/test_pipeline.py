import json

import pytest

from hound_agent.analyze.rca import run_analysis
from hound_agent.cli import build_parser, run_analyze
from hound_agent.config import Config
from hound_agent.models import validate
from hound_agent.pipeline import analyze
from tests.conftest import make_artifacts


def test_pipeline_analyze_returns_doc(tmp_path):
    log = tmp_path / "pytest_fail.log"
    log.write_text(
        (__import__("pathlib").Path(__file__).parent / "fixtures" / "pytest_fail.log").read_text(
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


def test_offline_pipeline_deterministic(tmp_path):
    from hound_agent.triage.component import assign
    from hound_agent.triage.dedup import check_duplicate
    from hound_agent.triage.severity import classify
    from hound_agent.output.report import write_json
    from hound_agent.models import build_doc
    from hound_agent.output.tickets import build_ticket

    a = make_artifacts("pytest_fail.log", changed_files=["app/cart.py"])
    rc = run_analysis(a, Config(offline=True))
    sev, pri = classify(a)
    t = check_duplicate(a, rc, str(tmp_path / "state.json"))
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
    from hound_agent.cli import build_parser

    log = tmp_path / "pytest_fail.log"
    log.write_text(
        (__import__("pathlib").Path(__file__).parent / "fixtures" / "pytest_fail.log").read_text(
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
