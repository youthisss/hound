"""Cost-control coverage (M19.4): dedup-first reuse, routing, and batch budget."""
import json

import pytest

from hound.cli import main
from hound.config import Config, load_config
from hound.analyze.cost import TransportBudget
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


def test_transport_budget_accumulates_sub_microcent_request_costs():
    config = Config(pricing={"default": {"prompt_per_mtok": 0.10, "completion_per_mtok": 0.10}})
    budget = TransportBudget(max_calls=None, max_cost=0.000001)
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    for _ in range(5):
        assert budget.reserve_llm() is True
        budget.observe(usage, config)
    snapshot = budget.snapshot()
    assert snapshot["known_cost_usd"] == 0.000001
    assert budget.reserve_llm() is False


def test_routing_exclude_kinds_skips_llm(monkeypatch):
    from hound.analyze.rca import run_analysis

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM must not be called for a skipped kind")

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", boom)
    cfg = Config(api_key="x", routing="exclude-kinds", skip_kinds=["flaky"])
    rc = run_analysis(make_artifacts("flaky.log"), cfg)
    assert rc.engine == "fallback"


def test_routing_all_keeps_llm(monkeypatch):
    from hound.analyze.rca import run_analysis

    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", model="test-model", routing="all")
    rc = run_analysis(make_artifacts("flaky.log"), cfg)
    assert calls["n"] == 1
    assert rc.engine in {"llm", "merged"}


# ------------------------------------------------------------------ reuse


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_reuse_skips_llm_after_threshold(tmp_path, monkeypatch, backend):
    from hound.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return (
            {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"},
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", model="test-model", reuse=True, reuse_after_occurrences=2, state_backend=backend)
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
    from hound.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fake_llm)
    cfg = Config(api_key="x", model="test-model", reuse=False)
    state = str(tmp_path / "state.json")
    for i in range(3):
        analyze(log, tmp_path / "out" / f"r{i}", _config=cfg, state_path=state)
    assert calls["n"] == 3


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_model_change_does_not_reuse_previous_llm_snapshot(tmp_path, monkeypatch, backend):
    from hound.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    calls: list[str] = []

    def fake_llm(_artifacts, config):
        calls.append(config.model)
        return (
            {"hypothesis": config.model, "confidence": "high", "evidence_refs": ["ev-001"],
             "contradicting_evidence_refs": [], "missing_information": [],
             "recommended_checks": ["check"], "fix_suggestion": "f"},
            {},
        )

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fake_llm)
    state = str(tmp_path / f"state.{'sqlite3' if backend == 'sqlite' else 'json'}")
    gemini = Config(
        api_key="x", provider="9router", model="ag/gemini-3.7-flash-low",
        reuse=True, reuse_after_occurrences=2, state_backend=backend,
    )
    gpt = Config(
        api_key="x", provider="9router", model="cx/gpt-5.6-terra",
        reuse=True, reuse_after_occurrences=2, state_backend=backend,
    )

    first = analyze(log, tmp_path / "out" / "r1", _config=gemini, state_path=state)
    second = analyze(log, tmp_path / "out" / "r2", _config=gpt, state_path=state)
    third = analyze(log, tmp_path / "out" / "r3", _config=gpt, state_path=state)

    assert calls == ["ag/gemini-3.7-flash-low", "cx/gpt-5.6-terra"]
    assert first["meta"]["model"] == "9router:ag/gemini-3.7-flash-low"
    assert second["meta"]["model"] == "9router:cx/gpt-5.6-terra"
    assert second["meta"]["reused"] is False
    assert third["meta"]["model"] == "9router:cx/gpt-5.6-terra"
    assert third["meta"]["reused"] is True


def test_reviewed_feedback_without_current_context_does_not_skip_llm(tmp_path, monkeypatch):
    from hound.feedback import default_feedback_store, record_feedback
    from hound.pipeline import analyze

    log = tmp_path / "x.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2\n", encoding="utf-8")
    output_root = tmp_path / "out"
    first_dir = output_root / "run-001"
    first = analyze(
        log, first_dir, offline=True, no_dedup=True, feedback_output_root=output_root,
    )
    record_feedback(
        default_feedback_store(output_root),
        first_dir / "report.json",
        "run-001",
        usefulness="useful",
        actual_outcome="root_cause_confirmed",
        review_status="reviewed",
    )

    calls = []

    def fresh_analysis(*_args, **_kwargs):
        calls.append(1)
        return {
            "hypothesis": "Fresh diagnosis", "confidence": "low", "evidence_refs": ["ev-001"],
            "fix_suggestion": "Check the current assertion",
        }, {}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fresh_analysis)
    second = analyze(
        log,
        output_root / "run-002",
        _config=Config(api_key="test-key", model="test-model"),
        no_dedup=True,
        feedback_output_root=output_root,
    )
    assert calls == [1]
    assert second["meta"]["reused"] is False
    assert second["meta"]["reused_from_key"] is None
    assert second["triage"]["dedup_key"] == first["triage"]["dedup_key"]
    assert second["root_cause"]["hypothesis"] == "Fresh diagnosis"


def test_llm_preview_is_redacted_and_never_calls_provider(tmp_path, monkeypatch):
    log = tmp_path / "x.log"
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    log.write_text(f"FAILED tests/test_x.py::test_x - token={secret}\n", encoding="utf-8")
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("preview must not call the provider")

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", boom)
    out = tmp_path / "out"
    assert main(["analyze", "--log", str(log), "--out", str(out), "--model", "test-model", "--llm-preview"]) == 1
    preview = (out / "llm-preview.json").read_text(encoding="utf-8")
    assert calls["n"] == 0
    assert secret not in preview
    assert "[REDACTED:" in preview


# ------------------------------------------------------------------ batch budget


def _write_logs(tmp_path, names):
    d = tmp_path / "logs"
    d.mkdir()
    for name in names:
        (d / name).write_text(
            f"FAILED tests/test_{name[:-4]}.py::test_x - assert 1 == 2\n", encoding="utf-8"
        )
    return d


def _mock_transport(monkeypatch, fake):
    from types import SimpleNamespace

    def create(**kwargs):
        data, usage = fake(None, None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))],
            usage=SimpleNamespace(**usage),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda config: client)


def test_batch_max_llm_calls_forces_fallback(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, ["a.log", "b.log"])
    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    _mock_transport(monkeypatch, fake_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--model", "test-model", "--max-llm-calls", "1"]) == 1

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

    _mock_transport(monkeypatch, fake_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--model", "test-model", "--max-llm-calls", "1", "--jobs", "6"]) == 1

    assert calls["n"] == 1
    summary = json.loads(next(out.glob("summary-*.json")).read_text(encoding="utf-8"))
    assert sum(not row["budget_skipped"] for row in summary) == 1


def test_failed_provider_attempt_still_consumes_batch_call_cap(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, ["a.log", "b.log"])
    calls = {"n": 0}

    def failing_llm(_artifacts, _config):
        calls["n"] += 1
        raise RuntimeError("provider unavailable")

    _mock_transport(monkeypatch, failing_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    assert main(["batch", "--logs", str(d), "--out", str(tmp_path / "out"), "--model", "test-model", "--max-llm-calls", "1"]) == 1
    assert calls["n"] == 1


def test_failed_batch_attempt_consumes_call_slot():
    from hound.cli import _BatchBudget

    budget = _BatchBudget(max_calls=1, max_cost=None)
    assert budget.reserve_llm() is True
    budget.record(False, 0.0, True, False, {})
    assert budget.reserve_llm() is False


def test_cached_batch_result_needs_no_call_slot():
    from hound.cli import _BatchBudget

    budget = _BatchBudget(max_calls=1, max_cost=None)
    budget.record(reused=True)
    assert budget.reserve_llm() is True


def test_zero_batch_budget_allows_no_provider_attempts():
    from hound.cli import _BatchBudget

    assert _BatchBudget(max_calls=0, max_cost=None).reserve_llm() is False
    assert _BatchBudget(max_calls=None, max_cost=0.0).reserve_llm() is False


def test_batch_writes_usage_telemetry(tmp_path, monkeypatch):
    d = _write_logs(tmp_path, ["a.log", "b.log"])
    monkeypatch.setenv("TH_API_KEY", "test-key")

    def fake_llm(_artifacts, _config):
        return (
            {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"},
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    _mock_transport(monkeypatch, fake_llm)
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--model", "test-model", "--max-llm-calls", "1"]) == 1

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
    from hound.analyze.cost import estimate_cost

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

    # Unconfigured prices do not imply free provider usage.
    assert estimate_cost(usage, Config()) is None


# ------------------------------------------------------------------ schema v2.0 + v1.4 reader compatibility


@pytest.mark.parametrize("compatibility", [False, True])
def test_transport_cap_blocks_retry_and_compatibility_fallback(monkeypatch, compatibility):
    from types import SimpleNamespace
    from hound.analyze.llm import analyze_with_llm, LlmError
    from hound.analyze.cost import TransportBudget, RequestAccount

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        error = RuntimeError("unsupported response_format" if compatibility else "unavailable")
        error.status_code = 400 if compatibility else 503
        error.body = {"usage": {"prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20}}
        raise error

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda config: client)
    monkeypatch.setattr("hound.analyze.llm.time.sleep", lambda _: None)
    budget = TransportBudget(1, None)
    account = RequestAccount(budget)
    with pytest.raises(LlmError) as caught:
        analyze_with_llm(make_artifacts("pytest_fail.log"), Config(model="test-model", request_account=account))
    assert len(calls) == 1
    assert caught.value.budget_skipped
    assert caught.value.usage["total_tokens"] == 20
    assert budget.snapshot()["total_tokens"]["total_tokens"] == 20
    assert budget.snapshot()["estimated_cost_usd"] is None


@pytest.mark.parametrize("content", ["not JSON", "", "[]"])
def test_invalid_response_retains_usage(monkeypatch, content):
    from types import SimpleNamespace
    from hound.analyze.llm import analyze_with_llm, LlmError
    from hound.analyze.cost import TransportBudget, RequestAccount

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda config: client)
    budget = TransportBudget(None, 0.0001)
    cfg = Config(model="test-model", request_account=RequestAccount(budget), pricing={"default": {"prompt_per_mtok": 1, "completion_per_mtok": 1}})
    with pytest.raises(LlmError) as caught:
        analyze_with_llm(make_artifacts("pytest_fail.log"), cfg)
    assert caught.value.usage == response.usage
    assert budget.snapshot()["estimated_cost_usd"] == 0.00012
    assert not budget.reserve_llm()


def test_offline_batch_consumes_no_transport_slots(tmp_path):
    logs = _write_logs(tmp_path, ["a.log", "b.log"])
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(logs), "--out", str(out), "--offline", "--max-llm-calls", "1"]) == 1
    usage = json.loads(next(out.glob("usage-*.json")).read_text())
    assert usage["llm_calls"] == 0
    assert usage["budget_skipped_runs"] == 0
    assert usage["estimated_cost_usd"] == 0


@pytest.mark.parametrize("compatibility", [False, True])
def test_each_transport_attempt_is_accounted(monkeypatch, compatibility):
    from types import SimpleNamespace
    from hound.analyze.llm import analyze_with_llm
    from hound.analyze.cost import TransportBudget, RequestAccount

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            error = RuntimeError("unsupported response_format" if compatibility else "unavailable")
            error.status_code = 400 if compatibility else 503
            error.body = {"usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
            raise error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"hypothesis":"h"}'))],
            usage={"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda config: client)
    monkeypatch.setattr("hound.analyze.llm.time.sleep", lambda _: None)
    budget = TransportBudget(2, None)
    cfg = Config(model="test-model", request_account=RequestAccount(budget))
    _, usage = analyze_with_llm(make_artifacts("pytest_fail.log"), cfg)
    assert len(calls) == budget.snapshot()["llm_calls"] == 2
    assert usage == {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36}
    assert usage == budget.snapshot()["total_tokens"]
    assert ("response_format" not in calls[1]) == compatibility


def _doc(reused: bool = False):
    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.tickets import build_ticket

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
    from hound.models import validate

    doc = _doc(reused=True)
    assert doc["schema_version"] == "2.0"
    validate(doc)
    assert doc["meta"]["reused"] is True
    assert doc["meta"]["reused_from_key"] == "k" + "0" * 63


def test_validate_rejects_missing_reused_field():
    from hound.models import validate

    doc = _doc()
    del doc["meta"]["reused"]
    with pytest.raises(ValueError, match="meta.reused missing"):
        validate(doc)
