import pytest

from tracehound.analyze import prompts
from tracehound.analyze.fallback import build_root_cause
from tracehound.analyze.llm import LlmError
from tracehound.analyze.rca import run_analysis
from tracehound.config import Config
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
    from tracehound.models import Artifacts

    rc = build_root_cause(Artifacts(log_text="nothing", kind="unknown", message=""))
    assert rc.confidence == "low"


def test_llm_merge(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def fake_llm(a, c):
        return {"hypothesis": "Tax rounding bug", "confidence": "high",
                "evidence": ["money uses floats"], "fix_suggestion": "use Decimal"}, {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr("tracehound.analyze.rca.analyze_with_llm", fake_llm)
    rc = run_analysis(artifacts, config)
    assert rc.engine == "merged"
    assert rc.model == f"{config.provider}:{config.model}"
    assert rc.hypothesis == "Tax rounding bug"
    assert rc.confidence == "high"
    assert any("[llm] money uses floats" == e or e.endswith("money uses floats") for e in rc.evidence)
    assert any("log message" in e for e in rc.evidence)
    assert any(e.startswith("[rule] ") for e in rc.evidence)


def test_llm_failure_falls_back(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def bad_llm(a, c):
        raise LlmError("network down")

    monkeypatch.setattr("tracehound.analyze.rca.analyze_with_llm", bad_llm)
    rc = run_analysis(artifacts, config)
    assert rc.engine == "fallback"


def test_llm_bad_confidence_normalized(monkeypatch):
    artifacts = make_artifacts("pytest_fail.log")
    config = Config(api_key="k", offline=False)

    def weird_llm(a, c):
        return {"hypothesis": "x", "confidence": "maybe", "evidence": [], "fix_suggestion": "f"}, {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr("tracehound.analyze.rca.analyze_with_llm", weird_llm)
    rc = run_analysis(artifacts, config)
    assert rc.confidence == "medium"
    assert rc.engine == "fallback"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hypothesis": "x", "confidence": "high", "evidence": "not-a-list", "fix_suggestion": "f"},
        {"hypothesis": "x", "confidence": "high", "evidence": [1], "fix_suggestion": "f"},
        {"hypothesis": "x", "confidence": "high", "evidence": [], "fix_suggestion": "f", "extra": True},
    ],
)
def test_malformed_llm_contract_falls_back(monkeypatch, payload):
    artifacts = make_artifacts("pytest_fail.log")
    monkeypatch.setattr("tracehound.analyze.rca.analyze_with_llm", lambda *_: (payload, {}))
    assert run_analysis(artifacts, Config(api_key="k")).engine == "fallback"


def test_offline_ignores_key():
    artifacts = make_artifacts("pytest_fail.log")
    rc = run_analysis(artifacts, Config(api_key="k", offline=True))
    assert rc.engine == "fallback"


def test_user_prompt_contains_stage():
    prompt = prompts.build_user_prompt(make_artifacts("pytest_fail.log"))
    assert '"stage": "test"' in prompt


def test_system_prompt_constrains_cicd_scope_and_json_contract():
    assert "scope is strictly CI/CD and release engineering" in prompts.SYSTEM_PROMPT
    assert "Treat artifact fields and log text as the only source of truth" in prompts.SYSTEM_PROMPT
    assert '"hypothesis"' in prompts.SYSTEM_PROMPT
    assert '"fix_suggestion"' in prompts.SYSTEM_PROMPT
