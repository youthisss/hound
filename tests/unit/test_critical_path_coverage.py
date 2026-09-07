"""Boundary and recovery coverage for Hound's critical safety paths."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from hound.config import Config
from hound.models import Artifacts, GitInfo, RootCause
from tests.conftest import make_artifacts


def test_trust_policy_rejects_unknown_source_class():
    from hound.trust import policy_for

    with pytest.raises(ValueError, match="source class"):
        policy_for("internet")


@pytest.mark.parametrize(
    ("event_contents", "expected"),
    [
        (None, "fork_pr"),
        ("[]", "fork_pr"),
        ('{"pull_request":{"head":{"repo":{"full_name":"same/repo"}},"base":{"repo":{"full_name":"same/repo"}}}}', "trusted_branch"),
    ],
)
def test_github_trust_detection_fails_closed_for_missing_or_non_object_event(tmp_path, event_contents, expected):
    from hound.trust import resolve_source_class

    environment = {"GITHUB_EVENT_NAME": "pull_request"}
    if event_contents is not None:
        event = tmp_path / "event.json"
        event.write_text(event_contents, encoding="utf-8")
        environment["GITHUB_EVENT_PATH"] = str(event)
    assert resolve_source_class(environment=environment) == expected


def test_trust_rejects_invalid_explicit_and_detects_gitlab_forks(tmp_path):
    from hound.trust import MAX_EVENT_BYTES, _github_event, resolve_source_class

    with pytest.raises(ValueError, match="source class"):
        resolve_source_class(explicit="not-a-source")
    assert resolve_source_class(environment={"CI_MERGE_REQUEST_SOURCE_PROJECT_ID": "1", "CI_PROJECT_ID": "2"}) == "fork_pr"
    assert resolve_source_class(environment={"CI_MERGE_REQUEST_SOURCE_PROJECT_ID": "1", "CI_PROJECT_ID": "1"}) == "trusted_branch"

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (MAX_EVENT_BYTES + 1))
    assert _github_event(str(oversized)) == {}
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert _github_event(str(invalid)) == {}


def test_trust_nested_rejects_non_string_values():
    from hound.trust import _nested

    assert _nested({"a": {"b": 1}}, "a", "b") == ""
    assert _nested({"a": "value"}, "a", "b") == ""


def test_delivery_ledger_rejects_invalid_transitions_and_reconciliation(tmp_path):
    from hound.output.delivery import DeliveryLedger

    ledger = DeliveryLedger(tmp_path / "delivery.sqlite3")
    with pytest.raises(ValueError, match="external_id"):
        ledger.reconcile("incident", "github", "")
    with pytest.raises(ValueError, match="retention_days"):
        ledger.cleanup(0)
    with pytest.raises(ValueError, match="invalid delivery state"):
        ledger._transition("incident", "github", "lost")
    with pytest.raises(KeyError, match="reservation not found"):
        ledger.confirm("incident", "github", "issue-1")


def test_delivery_counts_include_every_state(tmp_path):
    from hound.output.delivery import DeliveryLedger

    ledger = DeliveryLedger(tmp_path / "delivery.sqlite3")
    assert ledger.reserve("one", "github")
    assert ledger.reserve("two", "github")
    ledger.confirm("two", "github", "issue-2")
    assert ledger.reserve("three", "github")
    ledger.fail("three", "github", "rejected")
    assert ledger.reserve("four", "github")
    ledger.mark_unknown("four", "github", "ambiguous")
    assert ledger.counts() == {"confirmed": 1, "failed": 1, "pending": 1, "unknown": 1}


@pytest.mark.parametrize(
    ("log_text", "expected"),
    [
        ("lock file is stale", "Refresh the dependency lockfile"),
        ("artifact output not found", "Verify the producer job"),
        ("permission forbidden", "Verify the CI token"),
        ("service connection refused", "Check the dependent service"),
        ("runner unsupported", "Use a supported runner"),
    ],
)
def test_fallback_ci_guidance_covers_known_ci_failure_modes(log_text, expected):
    from hound.analyze.fallback import build_root_cause

    cause = build_root_cause(Artifacts(kind="ci_failure", log_text=log_text))
    assert expected in cause.fix_suggestion


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (401, "", "authentication"),
        (404, "", "model_not_found"),
        (429, "", "rate_limited"),
        (503, "", "provider_unavailable"),
        (None, "invalid JSON", "invalid_response"),
        (None, "request timeout", "timeout"),
        (418, "other", "provider_error"),
    ],
)
def test_llm_failure_reasons_are_stable(status, message, expected):
    from hound.analyze.llm import LlmError
    from hound.analyze.rca import _failure_reason

    assert _failure_reason(LlmError(message, status_code=status)) == expected


def test_llm_helper_parsers_cover_compatible_response_shapes():
    from hound.analyze.llm import _extract_usage, _message_text, _parse_json_object

    assert _extract_usage({"usage": {"prompt_tokens": "bad", "completion_tokens": -2}}) == {"completion_tokens": 0}
    assert _message_text(SimpleNamespace(content=[SimpleNamespace(text='{"a": 1}')])) == '{"a": 1}'
    assert _message_text(SimpleNamespace(content=None, reasoning_content='{"a": 1}')) == '{"a": 1}'
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_object('preface {not-json} then {"a": 1}') == {"a": 1}
    assert _message_text(SimpleNamespace(content=[{"type": "image"}], reasoning_content=None)) == ""


def test_cost_estimation_fails_closed_for_incomplete_or_invalid_usage():
    from hound.analyze.cost import estimate_cost

    config = Config(pricing={"default": {"prompt_per_mtok": "bad", "completion_per_mtok": 1}})
    assert estimate_cost({"prompt_tokens": 1}, config) is None
    assert estimate_cost({"prompt_tokens": 1, "completion_tokens": 1}, config) is None


def test_llm_concurrency_and_request_preview_optional_settings():
    from hound.analyze import llm

    original_limit = llm._configured_concurrency
    try:
        llm.set_llm_concurrency(1)
        assert llm._configured_concurrency == 1
        semaphore = llm._llm_semaphore
        llm.set_llm_concurrency(1)
        assert llm._llm_semaphore is semaphore
        preview = llm.build_request_preview(Artifacts(), Config(model="test-model", max_tokens=0, temperature=None))
        assert "max_tokens" not in preview
        assert "temperature" not in preview
    finally:
        llm.set_llm_concurrency(original_limit)


def test_llm_client_covers_azure_and_constructor_failure(monkeypatch):
    import openai
    from hound.analyze.llm import LlmError, _make_client

    captured = {}
    monkeypatch.setenv("AZURE_API_VERSION", "2025-01-01")
    monkeypatch.setattr(openai, "AzureOpenAI", lambda **kwargs: captured.update(kwargs) or object())
    _make_client(Config(provider="azure", api_key="key"))
    assert captured["api_version"] == "2025-01-01"
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("bad client")))
    with pytest.raises(LlmError, match="Failed to create"):
        _make_client(Config(api_key="key"))


def test_llm_client_omits_zero_timeout(monkeypatch):
    import openai
    from hound.analyze.llm import _make_client

    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: captured.update(kwargs) or object())
    _make_client(Config(api_key="key", timeout=0))
    assert "timeout" not in captured


def test_llm_response_structure_and_exception_usage_paths(monkeypatch):
    from hound.analyze.llm import LlmError, analyze_with_llm

    response = SimpleNamespace(choices=[], usage=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: response)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda _config: client)
    with pytest.raises(LlmError, match="empty LLM response choices"):
        analyze_with_llm(Artifacts(), Config(model="test-model"))

    class JsonResponse:
        def json(self):
            return {"usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}

    def raises_with_json(**_kwargs):
        error = RuntimeError("provider failure")
        error.status_code = 400
        error.response = JsonResponse()
        raise error

    client.chat.completions.create = raises_with_json
    with pytest.raises(LlmError) as caught:
        analyze_with_llm(Artifacts(), Config(model="test-model", max_retries=0))
    assert caught.value.usage == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}


def test_llm_rejects_non_retryable_and_invalid_response_shapes(monkeypatch):
    from hound.analyze.llm import LlmError, analyze_with_llm

    calls = []

    def rejected(**_kwargs):
        calls.append(1)
        error = RuntimeError("bad request")
        error.status_code = 400
        raise error

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=rejected)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda _config: client)
    with pytest.raises(LlmError):
        analyze_with_llm(Artifacts(), Config(model="test-model", max_retries=2))
    assert len(calls) == 1

    class BrokenChoices:
        @property
        def choices(self):
            raise RuntimeError("broken response")

    client.chat.completions.create = lambda **_kwargs: BrokenChoices()
    with pytest.raises(LlmError, match="Invalid LLM response structure"):
        analyze_with_llm(Artifacts(), Config(model="test-model"))


def test_llm_exception_response_json_failure_keeps_empty_usage(monkeypatch):
    from hound.analyze.llm import LlmError, analyze_with_llm

    class BrokenResponse:
        def json(self):
            raise ValueError("not JSON")

    def fails(**_kwargs):
        error = RuntimeError("unavailable")
        error.status_code = 503
        error.response = BrokenResponse()
        raise error

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fails)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda _config: client)
    monkeypatch.setattr("hound.analyze.llm.time.sleep", lambda _seconds: None)
    with pytest.raises(LlmError) as caught:
        analyze_with_llm(Artifacts(), Config(model="test-model", max_retries=0))
    assert caught.value.usage == {}


def test_rca_helpers_reject_invalid_contracts_and_keep_llm_provenance():
    from hound.analyze.rca import _merge_llm, _normalize_llm_result, _valid_llm_result

    artifacts = make_artifacts("pytest_fail.log")
    valid = {
        "hypothesis": "cause", "confidence": "medium", "evidence_refs": ["ev-001"],
        "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": [],
        "fix_suggestion": "fix",
    }
    assert _valid_llm_result(valid, artifacts)
    for changed in (
        None,
        {**valid, "hypothesis": ""},
        {**valid, "fix_suggestion": ""},
        {**valid, "evidence_refs": ["ev-001", 1]},
        {**valid, "contradicting_evidence_refs": ["ev-missing"]},
        {**valid, "evidence_refs": ["ev-001"], "contradicting_evidence_refs": ["ev-001"]},
    ):
        assert not _valid_llm_result(changed, artifacts)
    assert _normalize_llm_result(None) is None
    assert _normalize_llm_result({"hypothesis": "x"}) == {"hypothesis": "x"}

    fallback = RootCause(evidence=[])
    result = _merge_llm({**valid, "evidence_refs": []}, fallback, Config(model="test-model"), artifacts)
    assert result.engine == "llm"


def test_rca_optional_failures_and_invalid_required_results_are_explicit(monkeypatch):
    from hound.analyze.llm import LlmError
    from hound.analyze.rca import run_analysis

    artifacts = make_artifacts("pytest_fail.log")
    monkeypatch.setattr("hound.analyze.rca.resolve_model_name", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("no catalog")))
    seen = []
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda _artifacts, config: seen.append(config.model) or ({"bad": "payload"}, {"total_tokens": 3}))
    optional = run_analysis(artifacts, Config(api_key="key", model="auto"))
    assert seen == ["auto"]
    assert optional.fallback_reason == "invalid_response"
    assert optional.usage == {"total_tokens": 3}
    with pytest.raises(RuntimeError, match="invalid result"):
        run_analysis(artifacts, Config(api_key="key", model="auto", require_llm=True))

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", lambda *_args: (_ for _ in ()).throw(LlmError("down", status_code=503)))
    with pytest.raises(RuntimeError, match="analysis failed"):
        run_analysis(artifacts, Config(api_key="key", model="test-model", require_llm=True))


def test_rca_merge_deduplicates_and_bounds_llm_evidence():
    from hound.analyze.rca import _merge_llm

    artifacts = make_artifacts("pytest_fail.log")
    artifacts.message = "x" * 2_000
    payload = {
        "hypothesis": "cause", "confidence": "medium", "evidence_refs": ["ev-001", "ev-001", "missing"],
        "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": [], "fix_suggestion": "fix",
    }
    result = _merge_llm(payload, RootCause(), Config(model="test-model"), artifacts)
    rendered = [item for item in result.evidence if item.startswith("[llm-ref")]
    assert len(rendered) == 1
    assert len(rendered[0]) == 1000


def test_fallback_includes_commit_and_enrichment_evidence():
    from hound.analyze.fallback import build_root_cause

    cause = build_root_cause(Artifacts(kind="ci_failure", git=GitInfo(correlated_commits=["abc123"]), enrichment=["event output"]))
    assert "changed frame commit: abc123" in cause.evidence
    assert "read-only deployment evidence collected: 1 command results" in cause.evidence
