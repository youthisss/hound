"""Pure persistence helpers are tested independently of the CLI and TUI."""
from __future__ import annotations

from pathlib import Path

import pytest

from hound.config import Config
from hound.models import Artifacts, GitInfo, RootCause


def test_state_path_and_root_cause_snapshots_fail_closed(tmp_path):
    from hound.pipeline import _root_cause_from_snapshot, _root_cause_snapshot, _snapshot_matches_model, default_state_path

    out = tmp_path / "out"
    out.mkdir()
    assert default_state_path(out, None, True) is None
    assert default_state_path(out, str(tmp_path / "custom.json"), False) == str((tmp_path / "custom.json").resolve())
    snapshot = _root_cause_snapshot(RootCause(hypothesis="cause", confidence="medium", original_run={"run_id": "one"}))
    restored = _root_cause_from_snapshot(snapshot)
    assert restored is not None and restored.llm_status == "reused"
    assert _root_cause_from_snapshot({"original_run": []}) is None
    assert _root_cause_from_snapshot({"missing_information": None, "original_run": {}}) is None
    assert _snapshot_matches_model({"model": ""}, Config(offline=True))


def test_default_state_path_rejects_a_symlinked_state_directory(tmp_path, monkeypatch):
    from hound.pipeline import default_state_path

    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == ".hound")
    with pytest.raises(ValueError, match="symlinked"):
        default_state_path(tmp_path, None, False)


def test_snapshot_model_and_context_resolution_fail_closed(monkeypatch):
    from hound.pipeline import _analysis_context_key, _snapshot_matches_model

    monkeypatch.setattr("hound.pipeline.resolve_model_name", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unknown")))
    assert not _snapshot_matches_model({"model": "provider/model"}, Config(api_key="key", model="auto"))
    monkeypatch.setattr("hound.pipeline.inspect.getsource", lambda _object: (_ for _ in ()).throw(OSError("unreadable")))
    assert _analysis_context_key(Artifacts(), Config(offline=True), "scope", "digest") == ""


def test_context_key_and_reuse_tolerate_unresolved_auto_model_and_bad_occurrence_count(monkeypatch):
    from hound.pipeline import _analysis_context_key, _analyze_with_reuse

    monkeypatch.setattr("hound.pipeline.resolve_model_name", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unknown")))
    config = Config(api_key="key", model="auto")
    assert _analysis_context_key(Artifacts(), config, "scope", "digest")

    artifact = Artifacts(kind="import_error", message="missing")
    monkeypatch.setattr("hound.pipeline.fingerprint", lambda *_args, **_kwargs: "incident")
    monkeypatch.setattr("hound.pipeline.lookup_incident", lambda *_args: {"count": "not-a-number"})
    monkeypatch.setattr("hound.pipeline.reusable_root_cause", lambda *_args: None)
    fresh = RootCause(hypothesis="fresh")
    monkeypatch.setattr("hound.pipeline.run_analysis", lambda *_args: fresh)
    assert _analyze_with_reuse(artifact, config, "state", context_key="context") == (fresh, None)


def test_source_digest_covers_missing_nonfile_large_and_unsafe_paths(tmp_path):
    from hound.pipeline import _source_digest

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "present.py").write_text("x = 1\n", encoding="utf-8")
    artifact = Artifacts(git=GitInfo(head="head", changed_files=["present.py", "missing.py"]))
    assert _source_digest(artifact, repo)

    (repo / "folder").mkdir()
    artifact.git.changed_files = ["folder"]
    assert _source_digest(artifact, repo) == ""

    artifact.git.changed_files = ["../outside.py"]
    assert _source_digest(artifact, repo) == ""

    large = repo / "large.bin"
    large.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    artifact.git.changed_files = ["large.bin"]
    assert _source_digest(artifact, repo) == ""

    artifact.git.changed_files = [f"file-{index}.py" for index in range(257)]
    assert _source_digest(artifact, repo) == ""


def test_source_digest_artifact_only_and_missing_repository_guards():
    from hound.pipeline import _source_digest

    assert _source_digest(Artifacts(), None) == "artifact-only-v1"
    assert _source_digest(Artifacts(source_evidence=[{"file": "x.py"}]), None) == ""
    assert _source_digest(Artifacts(), Path("missing-repository")) == ""


def test_pipeline_rejects_disabled_http_state_backend_before_analysis(tmp_path):
    from hound.pipeline import analyze

    log = tmp_path / "failure.log"
    log.write_text("failure", encoding="utf-8")
    with pytest.raises(ValueError, match="HTTP dedup backend"):
        analyze(log, tmp_path / "out", _config=Config(offline=True, state_backend="http"))
