import json

import pytest

from hound.analyze import prompts
from hound.config import Config
from hound.models import GitInfo, StackFrame
from hound.pipeline import analyze
from hound.triage.dedup import lookup_incident


@pytest.fixture
def cached_run(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("result = 1\n", encoding="utf-8")
    log = tmp_path / "failure.log"
    log.write_text("ModuleNotFoundError: No module named 'missing'\n", encoding="utf-8")
    monkeypatch.setattr("hound.pipeline.gather", lambda *_: GitInfo(head="same-head", changed_files=["app.py"]))
    monkeypatch.setattr("hound.pipeline.parse_stacktrace", lambda *_: [StackFrame(file="app.py", line=1)])
    monkeypatch.setattr("hound.pipeline.correlated_commit_subjects", lambda *_: [])
    calls = []

    def llm(*_):
        calls.append(1)
        return {
            "hypothesis": "Missing dependency", "confidence": "high", "evidence_refs": ["ev-001"],
            "fix_suggestion": "Inspect install step",
        }, {"total_tokens": 15}

    monkeypatch.setattr("hound.analyze.rca.analyze_with_llm", llm)
    config = Config(api_key="k", model="test-model", reuse_after_occurrences=2)

    def run(backend="file", **kwargs):
        config.state_backend = backend
        return analyze(
            log, tmp_path / "out", repo_dir=kwargs.pop("repo_dir", repo),
            state_path=str(tmp_path / ("state.sqlite3" if backend == "sqlite" else "state.json")),
            _config=config, **kwargs,
        )

    return run, calls, config, source, log, tmp_path


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_exact_context_reuse_keeps_original_run_provenance(cached_run, backend):
    run, calls, _, _, _, tmp_path = cached_run
    run(backend)
    original = run(backend)
    reused = run(backend)
    again = run(backend)
    assert len(calls) == 2
    assert reused["meta"]["reused"] is True
    assert reused["meta"]["usage"] == {}
    assert reused["analysis"]["hypotheses"][0]["supporting_evidence_refs"] == []
    provenance = [item for item in again["analysis"]["missing_information"] if item.startswith("Original analysis run:")]
    assert len(provenance) == 1
    assert original["meta"]["generated_at"] in provenance[0]
    state = tmp_path / ("state.sqlite3" if backend == "sqlite" else "state.json")
    entry = lookup_incident(str(state), reused["triage"]["dedup_key"])
    assert entry["context_fingerprint"]
    assert entry["root_cause"]["original_run"]["generated_at"] == original["meta"]["generated_at"]


@pytest.mark.parametrize("change", ["dirty_source", "log", "model", "prompt", "policy", "project"])
def test_context_changes_force_fresh_analysis(cached_run, monkeypatch, change):
    run, calls, config, source, log, tmp_path = cached_run
    first = run()
    run()
    assert run()["meta"]["reused"] is True
    kwargs = {}
    if change == "dirty_source":
        source.write_text("result = 2\n", encoding="utf-8")
    elif change == "log":
        log.write_text(log.read_text(encoding="utf-8") + "additional diagnostic output\n", encoding="utf-8")
    elif change == "model":
        config.model = "another-model"
    elif change == "prompt":
        monkeypatch.setattr(prompts, "SYSTEM_PROMPT", prompts.SYSTEM_PROMPT + "\nNew investigation policy.")
    elif change == "policy":
        config.source_send_to_llm = True
    elif change == "project":
        repo = tmp_path / "other-repo"
        repo.mkdir()
        (repo / "app.py").write_bytes(source.read_bytes())
        kwargs["repo_dir"] = repo
    changed = run(**kwargs)
    assert changed["meta"]["reused"] is False
    assert len(calls) == 3
    assert (changed["triage"]["dedup_key"] == first["triage"]["dedup_key"]) is (change != "project")


def test_legacy_snapshot_and_reviewed_feedback_cannot_bypass_context(cached_run, monkeypatch):
    run, calls, _, _, _, tmp_path = cached_run
    reviewed = run()
    run()
    state = tmp_path / "state.json"
    entries = json.loads(state.read_text(encoding="utf-8"))
    for entry in entries:
        entry.pop("context_fingerprint", None)
    state.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr("hound.pipeline.find_known_issue", lambda *_: {"report": reviewed})
    assert run()["meta"]["reused"] is False
    assert len(calls) == 3


def test_reviewed_feedback_reuses_only_current_context(cached_run, monkeypatch):
    run, calls, _, source, _, _ = cached_run
    reviewed = run()
    monkeypatch.setattr("hound.pipeline.find_known_issue", lambda *_: {"report": reviewed})
    assert run()["meta"]["reused"] is True
    assert len(calls) == 1
    source.write_text("result = 99\n", encoding="utf-8")
    assert run()["meta"]["reused"] is False
    assert len(calls) == 2


def test_unavailable_source_disables_reuse(cached_run):
    run, calls, _, _, _, tmp_path = cached_run
    for _ in range(3):
        assert run(repo_dir=tmp_path / "missing-repo")["meta"]["reused"] is False
    assert len(calls) == 3


def test_artifact_only_reuse_is_bound_to_exact_evidence(cached_run):
    run, calls, _, _, log, _ = cached_run
    run(repo_dir=None)
    run(repo_dir=None)
    assert run(repo_dir=None)["meta"]["reused"] is True
    log.write_text(log.read_text(encoding="utf-8") + "New diagnostic detail\n", encoding="utf-8")
    assert run(repo_dir=None)["meta"]["reused"] is False
    assert len(calls) == 3
