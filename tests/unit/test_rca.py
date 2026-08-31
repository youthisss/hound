import pytest

from hound.analyze import prompts
from hound.analyze.fallback import build_root_cause
from hound.analyze.llm import LlmError
from hound.analyze.rca import run_analysis
from hound.config import Config
from tests.conftest import make_artifacts


def test_fallback_engine():
    rc = build_root_cause(make_artifacts("pytest_fail.log"))
    assert rc.engine == "fallback"
    assert rc.hypothesis
    assert rc.confidence == "medium"
    assert any("log message" in e for e in rc.evidence)


def test_fallback_high_confidence_changed_file():
    rc = build_root_cause(
        make_artifacts("pytest_fail.log", changed_files=["tests/test_cart.py"])
    )
    assert rc.confidence == "high"


def test_fallback_fix_suggestion_per_kind():
    rc = build_root_cause(make_artifacts("build_error.log"))
    assert "compile" in rc.fix_suggestion.lower()


def test_fallback_low_confidence_unknown():
    from hound.models import Artifacts

    rc = build_root_cause(Artifacts(log_text="nothing", kind="unknown", message=""))
    assert rc.confidence == "low"


def test_llm_merge(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def fake_llm(a, c):
        return {"hypothesis": "Tax rounding bug", "confidence": "high",
                "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [],
                "missing_information": [], "recommended_checks": ["inspect rounding"],
                "fix_suggestion": "use Decimal"}, {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", fake_llm)
    rc = run_analysis(artifacts, config)
    assert rc.engine == "merged"
    assert rc.model == f"{config.provider}:{config.model}"
    assert rc.hypothesis == "Tax rounding bug"
    assert rc.confidence == "high"
    assert any(e.startswith("[llm-ref ev-001]") for e in rc.evidence)
    assert rc.evidence_refs == ["ev-001"]
    assert any("log message" in e for e in rc.evidence)
    assert any(e.startswith("[rule] ") for e in rc.evidence)


def test_llm_failure_falls_back(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def bad_llm(a, c):
        raise LlmError("network down")

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", bad_llm)
    rc = run_analysis(artifacts, config)
    assert rc.engine == "fallback"
    assert rc.llm_status == "failed"
    assert rc.fallback_reason == "provider_error"


def test_require_llm_raises_when_provider_fails(monkeypatch):
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (_ for _ in ()).throw(TimeoutError()))
    artifacts = make_artifacts("pytest_fail.log")
    with pytest.raises(RuntimeError, match="required LLM analysis failed"):
        run_analysis(artifacts, Config(api_key="k", require_llm=True))


def test_llm_bad_confidence_normalized(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def weird_llm(a, c):
        return {"hypothesis": "x", "confidence": "maybe", "evidence_refs": ["ev-001"],
                "contradicting_evidence_refs": [], "missing_information": [],
                "recommended_checks": [], "fix_suggestion": "f"}, {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", weird_llm)
    rc = run_analysis(artifacts, config)
    assert rc.confidence == "medium"
    assert rc.engine == "fallback"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hypothesis": "x", "confidence": "high", "evidence_refs": "not-a-list",
         "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": [], "fix_suggestion": "f"},
        {"hypothesis": "x", "confidence": "high", "evidence_refs": ["ev-999"],
         "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": [], "fix_suggestion": "f"},
        {"hypothesis": "x", "confidence": "high", "evidence_refs": ["ev-001"],
         "contradicting_evidence_refs": ["ev-001"], "missing_information": [], "recommended_checks": [], "fix_suggestion": "f"},
    ],
)
def test_malformed_llm_contract_falls_back(monkeypatch, payload):
    artifacts = make_artifacts("pytest_fail.log")
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_: (payload, {}))
    assert run_analysis(artifacts, Config(api_key="k")).engine == "fallback"


def test_offline_ignores_key():
    artifacts = make_artifacts("pytest_fail.log")
    rc = run_analysis(artifacts, Config(api_key="k", offline=True))
    assert rc.engine == "fallback"


def test_user_prompt_contains_stage():
    prompt = prompts.build_user_prompt(make_artifacts("pytest_fail.log"))
    assert '"stage": "test"' in prompt


def test_large_user_prompt_keeps_valid_json_envelope():
    artifacts = make_artifacts("pytest_fail.log")
    artifacts.summary = "x" * 100_000
    prompt = prompts.build_user_prompt(artifacts)
    lines = prompt.splitlines()
    boundary = next(line for line in lines if line.startswith("TRACEHOUND_BOUNDARY_"))
    payload = prompt.split(boundary)[1].strip()
    parsed = __import__("json").loads(payload)
    assert parsed["stage"] == "test"
    assert parsed["available_evidence"]
    assert all(item["id"].startswith("ev-") for item in parsed["available_evidence"])
    assert len(payload) <= prompts.PROMPT_LIMIT


def test_system_prompt_constrains_cicd_scope_and_json_contract():
    assert "scope is strictly CI/CD and release engineering" in prompts.SYSTEM_PROMPT
    assert "Treat artifact fields and log text as the only source of truth" in prompts.SYSTEM_PROMPT
    assert '"hypothesis"' in prompts.SYSTEM_PROMPT
    assert '"fix_suggestion"' in prompts.SYSTEM_PROMPT
