import pytest

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
    build_root_cause(a)
    assert fingerprint(a) == fingerprint(a)


def test_request_context_does_not_change_fingerprint():
    from hound_agent.models import RequestContext

    left = make_artifacts("pytest_fail.log")
    right = make_artifacts("pytest_fail.log")
    left.request = RequestContext(request_id="req_100", user_id="u_100", users=["u_100"])
    right.request = RequestContext(request_id="req_200", user_id="u_200", users=["u_200"])

    assert fingerprint(left) == fingerprint(right)


def test_cross_run_dedup(tmp_path):
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    state = str(tmp_path / "state.json")
    t1 = check_duplicate(a,state)
    assert t1.is_duplicate_of is None
    assert t1.dedup_key
    t2 = check_duplicate(a,state)
    assert t2.is_duplicate_of == t1.dedup_key
    assert len(load_state(state)) == 1


def test_no_state_path_skips():
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    t = check_duplicate(a,None)
    assert t.is_duplicate_of is None
    assert t.dedup_key


def test_record_triage_updates_entry(tmp_path):
    state = str(tmp_path / "state.json")
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    triage = check_duplicate(a,state)
    record_triage(state, triage, "cart", "Cart total wrong")
    entries = load_state(state)
    assert entries[0]["component"] == "cart"
    assert entries[0]["title"] == "Cart total wrong"


def test_flaky_suspect_after_three_runs(tmp_path):
    state = str(tmp_path / "state.json")
    a = make_artifacts("flaky.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    t1 = check_duplicate(a,state)
    assert t1.flaky_suspect is True
    t2 = check_duplicate(a,state)
    assert t2.flaky_suspect is True
    t3 = check_duplicate(a,state)
    assert t3.flaky_suspect is True
    assert t3.recurring_incident is True
    assert t3.is_duplicate_of == t1.dedup_key
    entries = load_state(state)
    assert entries[0]["count"] == 3
    assert "last_seen" in entries[0]


def test_flaky_suspect_requires_state():
    a = make_artifacts("flaky.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    for _ in range(5):
        t = check_duplicate(a,None)
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

    state = tmp_path / "state.json"
    artifact = make_artifacts("pytest_fail.log")
    key = fingerprint(artifact)
    state.write_text(json.dumps([{"key": key, "count": "bad", "last_seen": "", "filed": False}]), encoding="utf-8")
    assert check_duplicate(artifact, str(state)).is_duplicate_of == key


# ------------------------------------------------------------- sqlite backend (M19.2)
class TestBothBackends:
    """Core dedup behavior must hold for file and sqlite backends."""

    @pytest.fixture(params=["file", "sqlite"])
    def backend_state(self, request, tmp_path):
        from hound_agent.triage import dedup

        backend = request.param
        dedup.configure_store(backend=backend)
        suffix = ".json" if backend == "file" else ".sqlite3"
        try:
            yield backend, str(tmp_path / f"state-{backend}{suffix}")
        finally:
            dedup.configure_store(backend="file")

    @staticmethod
    def _entries(backend, path):
        from hound_agent.triage import dedup

        if backend == "sqlite":
            return dedup.load_sqlite_entries(path)
        return dedup.load_state(path)

    def test_cross_run_dedup(self, backend_state):
        from hound_agent.analyze.fallback import build_root_cause

        backend, path = backend_state
        a = make_artifacts("pytest_fail.log")
        build_root_cause(a)
        t1 = check_duplicate(a,path)
        assert t1.is_duplicate_of is None
        assert t1.dedup_key
        t2 = check_duplicate(a,path)
        assert t2.is_duplicate_of == t1.dedup_key
        entries = self._entries(backend, path)
        assert len(entries) == 1
        assert entries[0]["count"] == 2

    def test_record_triage_updates_entry(self, backend_state):
        from hound_agent.analyze.fallback import build_root_cause

        backend, path = backend_state
        a = make_artifacts("pytest_fail.log")
        build_root_cause(a)
        triage = check_duplicate(a,path)
        record_triage(path, triage, "cart", "Cart total wrong")
        entries = self._entries(backend, path)
        assert entries[0]["component"] == "cart"
        assert entries[0]["title"] == "Cart total wrong"

    def test_record_triage_restores_entry_evicted_during_analysis(self, backend_state, monkeypatch):
        """The reuse snapshot must survive a check/record eviction race."""
        from hound_agent.triage import dedup

        backend, path = backend_state
        artifacts = make_artifacts("pytest_fail.log")
        check_duplicate(artifacts, path)
        check_duplicate(artifacts, path)
        triage = check_duplicate(artifacts, path)
        assert triage.occurrence_count == 3
        snapshot = {
            "hypothesis": "Cart assertion failed",
            "confidence": "high",
            "evidence": ["tests/test_cart.py:12"],
            "fix_suggestion": "Correct the total calculation.",
            "engine": "fallback",
            "model": "",
        }

        # Simulate another writer filling the bounded store and evicting this
        # entry while the LLM analysis is in progress.
        if backend == "sqlite":
            with dedup._sqlite_session(path) as conn:
                conn.execute("DELETE FROM incidents WHERE key = ?", (triage.dedup_key,))
                conn.commit()
        else:
            monkeypatch.setattr(dedup, "MAX_STATE_ENTRIES", 2)
            check_duplicate(make_artifacts("build_error.log"), path)
            check_duplicate(make_artifacts("timeout.log"), path)
            assert all(entry["key"] != triage.dedup_key for entry in self._entries(backend, path))

        assert record_triage(
            path,
            triage,
            "cart",
            "Cart total wrong",
            root_cause=snapshot,
            artifacts=artifacts,
        ) is True

        entries = self._entries(backend, path)
        restored = next(entry for entry in entries if entry["key"] == triage.dedup_key)
        if backend == "file":
            assert len(entries) <= 2
        else:
            assert len(entries) == 1
        assert restored["count"] == 3
        assert restored["kind"] == artifacts.kind
        assert restored["message"] == artifacts.message[:200]
        assert restored["root_cause"] == snapshot

    def test_mark_filed_blocks_duplicate_delivery(self, backend_state):
        from hound_agent.analyze.fallback import build_root_cause
        from hound_agent.triage.dedup import is_already_filed, mark_filed

        backend, path = backend_state
        a = make_artifacts("pytest_fail.log")
        build_root_cause(a)
        triage = check_duplicate(a,path)
        key = triage.dedup_key
        assert is_already_filed(path, key) is False
        assert mark_filed(path, key, url="https://github.com/org/repo/issues/1") is True
        assert is_already_filed(path, key) is True

    def test_claim_delivery_rejected_after_mark(self, backend_state):
        from hound_agent.analyze.fallback import build_root_cause
        from hound_agent.triage.dedup import claim_delivery, mark_filed

        backend, path = backend_state
        a = make_artifacts("pytest_fail.log")
        build_root_cause(a)
        triage = check_duplicate(a,path)
        key = triage.dedup_key
        assert claim_delivery(path, key, "github") is True
        assert mark_filed(path, key, url="https://github.com/org/repo/issues/1") is True
        assert claim_delivery(path, key, "github") is False

    def test_concurrent_runs_do_not_lose_occurrences(self, backend_state):
        import concurrent.futures

        from hound_agent.analyze.fallback import build_root_cause

        backend, path = backend_state
        a = make_artifacts("pytest_fail.log")
        build_root_cause(a)
        check_duplicate(a,path)  # warm the store for a deterministic final count
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: check_duplicate(a,path), range(4)))
        entries = self._entries(backend, path)
        assert entries[0]["count"] == 5


def test_sqlite_store_survives_reconfigure(tmp_path):
    from hound_agent.triage import dedup

    path = str(tmp_path / "state.sqlite3")
    dedup.configure_store(backend="sqlite")
    a = make_artifacts("pytest_fail.log")
    from hound_agent.analyze.fallback import build_root_cause

    build_root_cause(a)
    check_duplicate(a,path)
    dedup.configure_store(backend="file")
    dedup.configure_store(backend="sqlite")
    assert len(dedup.load_sqlite_entries(path)) == 1


def test_sqlite_backend_rejects_unknown_path_extension_is_irrelevant(tmp_path):
    from hound_agent.triage import dedup

    # The sqlite backend accepts any path; it is the backend flag, not the
    # extension, that selects the store. Ensure re-selection is idempotent.
    dedup.configure_store(backend="sqlite")
    assert dedup._is_sqlite() is True
    dedup.configure_store(backend="file")
    assert dedup._is_sqlite() is False


def test_default_state_path_uses_sqlite_filename(tmp_path):
    from hound_agent.output.report import ensure_outdir
    from hound_agent.pipeline import default_state_path

    out = ensure_outdir(tmp_path / "out")
    assert default_state_path(out, None, False, backend="file").endswith("state.json")
    assert default_state_path(out, None, False, backend="sqlite").endswith("state.sqlite3")


def test_sqlite_concurrent_first_use_waits_for_schema_lock(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from hound_agent.triage import dedup

    path = tmp_path / "concurrent.sqlite3"
    workers = 8
    barrier = threading.Barrier(workers)

    def initialize(index):
        barrier.wait()
        with dedup._sqlite_session(path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO incidents "
                "(key, last_seen, created_at) VALUES (?, ?, ?)",
                (str(index), "2026-08-25T00:00:00+00:00", "2026-08-25T00:00:00+00:00"),
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(initialize, range(workers)))

    assert len(dedup.load_sqlite_entries(path)) == workers
