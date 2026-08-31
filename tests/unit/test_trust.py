from __future__ import annotations

import argparse
import json

from hound.cli import _maybe_file
from hound.config import Config, load_config
from hound.pipeline import analyze
from hound.trust import resolve_source_class


def test_fork_profile_forces_offline_and_forbids_optional_capabilities(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = load_config(source_class="fork_pr")
    assert config.offline is True
    assert config.llm_enabled is False
    assert config.allow_source_context is False
    assert config.allow_enrichment is False
    assert config.allow_delivery is False


def test_yaml_fork_profile_cannot_disable_redaction(tmp_path):
    config_path = tmp_path / "hound.yml"
    config_path.write_text("trust:\n  source_class: fork_pr\nredact: false\n", encoding="utf-8")
    config = load_config(config_path=str(config_path), redact=False)
    assert config.source_class == "fork_pr"
    assert config.offline is True
    assert config.redact is True


def test_github_fork_is_detected_from_event(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "pull_request": {
            "head": {"repo": {"full_name": "contributor/fork"}},
            "base": {"repo": {"full_name": "owner/repository"}},
        }
    }), encoding="utf-8")
    source = resolve_source_class(environment={
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
    })
    assert source == "fork_pr"


def test_canonical_source_class_env_precedes_legacy_alias(capsys):
    assert resolve_source_class(environment={"HOUND_SOURCE_CLASS": "fork_pr", "TH_SOURCE_CLASS": "local_artifact"}) == "fork_pr"
    assert resolve_source_class(environment={"TH_SOURCE_CLASS": "local_artifact"}) == "local_artifact"
    assert "TH_SOURCE_CLASS is deprecated" in capsys.readouterr().err


def test_fork_pipeline_does_not_call_source_enrichment_or_llm(tmp_path, monkeypatch):
    log = tmp_path / "failure.log"
    log.write_text("FAILED tests/test_x.py::test_x - assert 1 == 2", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden capability was called")

    monkeypatch.setattr("hound.pipeline.gather", forbidden)
    monkeypatch.setattr("hound.pipeline.attach_snippets", forbidden)
    monkeypatch.setattr("hound.pipeline.collect_deployment_evidence", forbidden)
    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", forbidden)
    config = Config(
        api_key="test-key",
        offline=True,
        source_class="fork_pr",
        allow_source_context=False,
        allow_enrichment=False,
        allow_llm=False,
        allow_delivery=False,
    )

    document = analyze(
        log,
        tmp_path / "out",
        repo_dir=repo,
        source_context=True,
        enrich=True,
        no_dedup=True,
        _config=config,
    )
    assert document["meta"]["engine"] == "fallback"
    assert document["context"]["owners"] == []
    assert document["meta"]["trust"] == {
        "source_class": "fork_pr",
        "source_context": False,
        "enrichment": False,
        "llm": False,
        "delivery": False,
    }


def test_fork_policy_blocks_delivery_before_connector_call(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr("hound.cli._file_github_ticket", lambda *_args, **_kwargs: called.append(True))
    args = argparse.Namespace(
        gh=True, jira=False, gitlab=False, slack_webhook=False,
        provider=None, model=None, base_url=None, api_key=None, max_retries=None,
        source_class="fork_pr", out=str(tmp_path), no_dedup=True,
    )
    document = {"triage": {"dedup_key": "a" * 64}, "ticket": {"title": "x", "body_md": "x", "labels": []}}
    assert _maybe_file(args, document, None) is False
    assert called == []
