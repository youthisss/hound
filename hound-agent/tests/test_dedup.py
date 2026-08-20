from hound_agent.models import Triage
from hound_agent.triage.dedup import (
    check_duplicate,
    fingerprint,
    load_state,
    normalize,
    record_triage,
)
from tests.conftest import make_artifacts


def test_normalize_strips_noise():
    assert normalize("ERROR at /tmp/x file.py:42 [0x1a2b] 2026-01-01 12:00:00") == "error at file.py"
    assert normalize("MiXeD  CASE") == "mixed case"


def test_fingerprint_deterministic():
    from hound_agent.analyze.fallback import build_root_cause

    a = make_artifacts("pytest_fail.log")
    rc = build_root_cause(a)
    assert fingerprint(a, rc) == fingerprint(a, rc)


def test_cross_run_dedup(tmp_path):
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    rc = build_root_cause(a)
    state = str(tmp_path / "state.json")
    t1 = check_duplicate(a, rc, state)
    assert t1.is_duplicate_of is None
    assert t1.dedup_key
    t2 = check_duplicate(a, rc, state)
    assert t2.is_duplicate_of == t1.dedup_key
    assert len(load_state(state)) == 1


def test_no_state_path_skips():
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    rc = build_root_cause(a)
    t = check_duplicate(a, rc, None)
    assert t.is_duplicate_of is None
    assert t.dedup_key


def test_record_triage_updates_entry(tmp_path):
    state = str(tmp_path / "state.json")
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    rc = build_root_cause(a)
    triage = check_duplicate(a, rc, state)
    record_triage(state, triage, "cart", "Cart total wrong")
    entries = load_state(state)
    assert entries[0]["component"] == "cart"
    assert entries[0]["title"] == "Cart total wrong"


def test_flaky_suspect_after_three_runs(tmp_path):
    state = str(tmp_path / "state.json")
    a = make_artifacts("flaky.log")
    from hound_agent.analyze.fallback import build_root_cause

    rc = build_root_cause(a)
    t1 = check_duplicate(a, rc, state)
    assert t1.flaky_suspect is True
    t2 = check_duplicate(a, rc, state)
    assert t2.flaky_suspect is True
    t3 = check_duplicate(a, rc, state)
    assert t3.flaky_suspect is True
    assert t3.recurring_incident is True
    assert t3.is_duplicate_of == t1.dedup_key
    entries = load_state(state)
    assert entries[0]["count"] == 3
    assert "last_seen" in entries[0]


def test_flaky_suspect_requires_state():
    a = make_artifacts("flaky.log")
    from hound_agent.analyze.fallback import build_root_cause

    rc = build_root_cause(a)
    for _ in range(5):
        t = check_duplicate(a, rc, None)
    assert t.flaky_suspect is True


def test_corrupt_state_is_preserved_for_recovery(tmp_path):
    from hound_agent.triage.dedup import load_state

    state = tmp_path / "state.json"
    state.write_text("{invalid", encoding="utf-8")
    assert load_state(state) == []
    assert not state.exists()
    assert list(tmp_path.glob("state.json.corrupt-*"))


def test_state_cap_retains_filed_entries(tmp_path, monkeypatch):
    from hound_agent.triage import dedup

    monkeypatch.setattr(dedup, "MAX_STATE_ENTRIES", 2)
    state = tmp_path / "state.json"
    dedup.save_state(str(state), [
        {"key": "filed", "filed": True, "last_seen": "2020-01-01"},
        {"key": "new", "filed": False, "last_seen": "2026-01-02"},
        {"key": "old", "filed": False, "last_seen": "2026-01-01"},
    ])
    assert {entry["key"] for entry in dedup.load_state(str(state))} == {"filed", "new"}


def test_malformed_state_count_does_not_abort_analysis(tmp_path):
    import json
    from hound_agent.analyze.fallback import build_root_cause

    state = tmp_path / "state.json"
    artifact = make_artifacts("pytest_fail.log")
    key = fingerprint(artifact, build_root_cause(artifact))
    state.write_text(json.dumps([{"key": key, "count": "bad", "last_seen": "", "filed": False}]), encoding="utf-8")
    assert check_duplicate(artifact, build_root_cause(artifact), str(state)).is_duplicate_of == key
