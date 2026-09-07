import json

import pytest

from hound.analyze.fallback import build_root_cause
from hound.analyze.rca import run_analysis
from hound.config import Config
from hound.models import Artifacts, GitInfo, RootCause, StackFrame, Ticket, Triage, build_doc, validate
from hound.pipeline import analyze


def payload(confidence="high", refs=None):
    return {
        "hypothesis": "Dependency is missing", "confidence": confidence,
        "evidence_refs": ["ev-001"] if refs is None else refs,
        "fix_suggestion": "Inspect dependency installation",
    }


@pytest.mark.parametrize("confidence", [[], {}, None, 1])
@pytest.mark.parametrize("required", [False, True])
def test_invalid_confidence_preserves_optional_fallback(monkeypatch, confidence, required):
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (payload(confidence), usage))
    config = Config(api_key="k", model="test-model", require_llm=required)
    artifacts = Artifacts(kind="import_error", message="ModuleNotFoundError: missing")
    if required:
        with pytest.raises(RuntimeError, match="required LLM returned an invalid result"):
            run_analysis(artifacts, config)
    else:
        result = run_analysis(artifacts, config)
        assert result.engine == "fallback"
        assert result.fallback_reason == "invalid_response"
        assert result.usage == usage


def test_validator_failure_cannot_break_optional_analysis(monkeypatch):
    usage = {"total_tokens": 15}
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (payload(), usage))

    def broken_validator(*_):
        raise TypeError("unexpected response shape")

    monkeypatch.setattr("hound.analyze.rca._valid_llm_result", broken_validator)
    result = run_analysis(Artifacts(), Config(api_key="k", model="test-model"))
    assert result.fallback_reason == "invalid_response"
    assert result.usage == usage


def test_provider_parse_failure_retains_usage(monkeypatch):
    error = ValueError("invalid JSON")
    error.usage = {"total_tokens": 15}

    def fail(*_):
        raise error

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fail)
    result = run_analysis(Artifacts(), Config(api_key="k", model="test-model"))
    assert result.usage == error.usage
    assert result.fallback_reason == "invalid_response"


@pytest.mark.parametrize("refs", [[], ["ev-001"]])
def test_high_confidence_needs_failure_support(monkeypatch, refs):
    artifacts = Artifacts(kind="import_error", git=GitInfo(owners=["team-platform"]))
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (payload(refs=refs), {}))
    assert run_analysis(artifacts, Config(api_key="k", model="test-model")).engine == "fallback"


def test_unknown_changed_frame_does_not_establish_hypothesis():
    artifacts = Artifacts(frames=[StackFrame(file="app.py")], git=GitInfo(changed_files=["app.py"]))
    result = build_root_cause(artifacts)
    assert result.confidence == "low"
    doc = build_doc(artifacts, result, Triage(), Ticket(), "2026-01-01T00:00:00Z")
    validate(doc)
    hypothesis = doc["analysis"]["hypotheses"][0]
    assert hypothesis["support_status"] == "insufficient_evidence"
    assert "evidence completeness" in hypothesis["confidence"]["reasons"][0]
    assert "not hypothesis probability" in hypothesis["confidence"]["reasons"][0]


@pytest.mark.parametrize("unknown", [False, True])
def test_high_confidence_is_rejected_for_unknown_or_conflicting_evidence(monkeypatch, unknown):
    artifacts = Artifacts(
        kind="unknown" if unknown else "import_error", message="ModuleNotFoundError: missing",
        frames=[StackFrame(file="app.py", line=1)],
    )
    response = payload()
    if not unknown:
        response["contradicting_evidence_refs"] = ["ev-002"]
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (response, {}))
    result = run_analysis(artifacts, Config(api_key="k", model="test-model"))
    assert result.engine == "fallback"
    assert result.confidence != "high"


@pytest.mark.parametrize("backend", ["file", "sqlite"])
@pytest.mark.parametrize("reused", [False, True])
def test_redacts_analysis_before_state_and_report_persistence(tmp_path, monkeypatch, backend, reused):
    from hound.triage.dedup import lookup_incident

    secret = "ghp_" + "A" * 36
    log = tmp_path / "failure.log"
    log.write_text("ModuleNotFoundError: No module named 'missing'\n", encoding="utf-8")
    root = RootCause(
        hypothesis=f"credential {secret}", confidence="low", engine="merged",
        evidence=[secret], fix_suggestion=secret, missing_information=[secret],
        recommended_checks=[secret], llm_status="reused" if reused else "succeeded",
    )
    monkeypatch.setattr("hound.pipeline._analyze_with_reuse", lambda *_: (root, "original" if reused else None))
    monkeypatch.setattr("hound.pipeline.build_ticket", lambda *_: Ticket(title=secret, body_md=secret))
    state = str(tmp_path / ("state.sqlite3" if backend == "sqlite" else "state.json"))
    doc = analyze(log, tmp_path / "out", state_path=state,
                  _config=Config(offline=True, redact=True, state_backend=backend))
    entry = lookup_incident(state, doc["triage"]["dedup_key"])
    assert entry is not None
    assert secret not in json.dumps(entry)
    assert secret not in json.dumps(doc)
    assert doc["meta"]["redacted"] is True
    for path in (tmp_path / "out").glob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8")
