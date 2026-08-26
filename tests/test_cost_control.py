"""Cost-control coverage (M19.4): dedup-first reuse, routing, and batch budget."""
import json

import pytest

from hound_agent.cli import main
from hound_agent.config import Config, load_config
from tests.conftest import make_artifacts


# ------------------------------------------------------------------ config


def test_config_parses_cost_control_settings(tmp_path):
    config = tmp_path / "cc.yml"
    config.write_text(
        "dedup:\n"
        "  reuse: false\n"
        "  reuse_after_occurrences: 5\n"
        "llm:\n"
        "  routing: exclude-kinds\n"
        "  skip_kinds: [flaky, timeout]\n"
        "  pricing:\n"
        "    default:\n"
        "      prompt_per_mtok: 0.10\n"
        "      completion_per_mtok: 0.40\n",
        encoding="utf-8",
    )
    cfg = load_config(config_path=str(config), offline=True)
    assert cfg.reuse is False
    assert cfg.reuse_after_occurrences == 5
    assert cfg.routing == "exclude-kinds"
    assert cfg.skip_kinds == ["flaky", "timeout"]
    assert cfg.pricing["default"]["prompt_per_mtok"] == 0.10
    assert cfg.pricing["default"]["completion_per_mtok"] == 0.40


def test_config_rejects_invalid_cost_control(tmp_path):
    cases = [
        ("llm:\n  routing: sometimes\n", "routing"),
        ("llm:\n  skip_kinds: [flaky, madeup]\n", "unknown kinds"),
        ("dedup:\n  reuse: 1\n", "boolean"),
        ("dedup:\n  reuse_after_occurrences: 1\n", "reuse_after_occurrences"),
        ("llm:\n  pricing:\n    default:\n      prompt_per_mtok: -1\n", ">= 0"),
    ]
    for index, (yaml_text, match) in enumerate(cases):
        path = tmp_path / f"bad-{index}.yml"
        path.write_text(yaml_text, encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            load_config(config_path=str(path), offline=True)


# ------------------------------------------------------------------ routing


def test_routing_exclude_kinds_skips_llm(monkeypatch):
    from hound_agent.analyze.rca import run_analysis

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM must not be called for a skipped kind")

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", boom)
    cfg = Config(api_key="x", routing="exclude-kinds", skip_kinds=["flaky"])
    rc = run_analysis(make_artifacts("flaky.log"), cfg)
    assert rc.engine == "fallback"


def test_routing_all_keeps_llm(monkeypatch):
    from hound_agent.analyze.rca import run_analysis

    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", routing="all")
    rc = run_analysis(make_artifacts("flaky.log"), cfg)
    assert calls["n"] == 1
    assert rc.engine in {"llm", "merged"}


# ------------------------------------------------------------------ reuse


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_reuse_skips_llm_after_threshold(tmp_path, monkeypatch, backend):
    from hound_agent.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return (
            {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"},
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", reuse=True, reuse_after_occurrences=2, state_backend=backend)
    state = str(tmp_path / f"state.{'sqlite3' if backend == 'sqlite' else 'json'}")
    docs = [analyze(log, tmp_path / "out" / f"r{i}", _config=cfg, state_path=state) for i in range(3)]

    assert calls["n"] == 2  # runs 1 and 2; run 3 reused the stored snapshot
    assert docs[0]["meta"]["reused"] is False
    assert docs[1]["meta"]["reused"] is False
    assert docs[2]["meta"]["reused"] is True
    assert docs[2]["meta"]["reused_from_key"] == docs[0]["triage"]["dedup_key"]
    assert docs[2]["meta"]["engine"] == "merged"
    assert docs[2]["meta"]["usage"] == {}  # a reused run spends zero tokens now
    assert docs[2]["analysis"]["hypotheses"][0]["support_status"] == "unsupported"
    assert docs[2]["analysis"]["hypotheses"][0]["supporting_evidence_refs"] == []
    assert docs[2]["triage"]["occurrence_count"] == 3  # count still tracked


def test_reuse_disabled_always_calls_llm(tmp_path, monkeypatch):
    from hound_agent.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", reuse=False)
    state = str(tmp_path / "state.json")
    for i in range(3):
        analyze(log, tmp_path / "out" / f"r{i}", _config=cfg, state_path=state)
    assert calls["n"] == 3


# ------------------------------------------------------------------ batch budget


def _write_logs(tmp_path, names):
    d = tmp_path / "logs"
    d.mkdir()
    for name in names:
        (d / name).write_text(
            f"FAILED tests/test_{name[:-4]}.py::test_x - assert 1 == 2\n", encoding="utf-8"
        )
    return d


def test_batch_max_llm_calls_forces_fallback(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, ["a.log", "b.log"])
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--max-llm-calls", "1"]) == 1

    assert calls["n"] == 1
    summary = json.loads(next(out.glob("summary-*.json")).read_text(encoding="utf-8"))
    assert len(summary) == 2
    assert summary[0]["budget_skipped"] is False
    assert summary[0]["engine"] in {"llm", "merged"}
    assert summary[1]["budget_skipped"] is True
    assert summary[1]["engine"] == "fallback"


def test_parallel_batch_does_not_overshoot_max_llm_calls(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, [f"{name}.log" for name in "abcdef"])
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--max-llm-calls", "1", "--jobs", "6"]) == 1

    assert calls["n"] == 1
    summary = json.loads(next(out.glob("summary-*.json")).read_text(encoding="utf-8"))
    assert sum(not row["budget_skipped"] for row in summary) == 1


def test_failed_batch_attempt_releases_reserved_call_slot():
    from hound_agent.cli import _BatchBudget

    budget = _BatchBudget(max_calls=1, max_cost=None)
    assert budget.reserve_llm() is True
    budget.record(False, 0.0, False, False, {})
    assert budget.reserve_llm() is True


def test_batch_writes_usage_telemetry(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, ["a.log", "b.log"])
    monkeypatch.setenv("TH_API_KEY", "test-key")

    def fake_llm(_artifacts, _config):
        return (
            {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"},
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--max-llm-calls", "1"]) == 1

    usage_path = next(out.glob("usage-*.json"))
    block = json.loads(usage_path.read_text(encoding="utf-8"))
    assert block["schema_version"] == "2.0"
    assert block["llm_calls"] == 1
    assert block["budget_skipped_runs"] == 1
    assert block["reused_runs"] == 0
    assert block["limits"] == {"max_llm_calls": 1, "max_cost_usd": None}
    assert block["total_tokens"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


# ------------------------------------------------------------------ cost helper


def test_estimate_cost():
    from hound_agent.analyze.cost import estimate_cost

    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000}
    cfg = Config(
        provider="gemini",
        model="gemini-3.7-flash",
        pricing={"gemini:gemini-3.7-flash": {"prompt_per_mtok": 1.0, "completion_per_mtok": 2.0}},
    )
    assert estimate_cost(usage, cfg) == 2.0
    assert estimate_cost({}, cfg) == 0.0

    # provider-level fallback
    cfg2 = Config(
        provider="gemini", model="x", pricing={"gemini": {"prompt_per_mtok": 0.5, "completion_per_mtok": 0.5}}
    )
    assert estimate_cost({"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}, cfg2) == 1.0

    # no pricing configured -> free
    assert estimate_cost(usage, Config()) == 0.0


# ------------------------------------------------------------------ schema v2.0 + v1.4 reader compatibility


def _doc(reused: bool = False):
    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage, build_doc
    from hound_agent.output.tickets import build_ticket

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    triage = Triage(component="cart", dedup_key="k" + "0" * 63)
    ticket = build_ticket(artifacts, rc, triage)
    return build_doc(
        artifacts,
        rc,
        triage,
        ticket,
        "2026-01-01T00:00:00Z",
        reused=reused,
        reused_from_key="k" + "0" * 63 if reused else None,
    )


def test_schema_v2_reused_fields():
    from hound_agent.models import validate

    doc = _doc(reused=True)
    assert doc["schema_version"] == "2.0"
    validate(doc)
    assert doc["meta"]["reused"] is True
    assert doc["meta"]["reused_from_key"] == "k" + "0" * 63


def test_validate_rejects_missing_reused_field():
    from hound_agent.models import validate

    doc = _doc()
    del doc["meta"]["reused"]
    with pytest.raises(ValueError, match="meta.reused missing"):
        validate(doc)
