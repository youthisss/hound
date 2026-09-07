"""Failure, recovery, and lifecycle coverage for critical dedup persistence."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from hound.models import Artifacts
from hound.triage import dedup


@pytest.fixture(autouse=True)
def reset_dedup_store():
    dedup.configure_store("file", max_entries=50000, retention_days=90)
    yield
    dedup.configure_store("file", max_entries=50000, retention_days=90)


def _triage(path: str):
    artifact = Artifacts(kind="test_failure", stage="test", message="assert 1 == 2")
    return artifact, dedup.check_duplicate(artifact, path, project_scope="test/project")


def test_dedup_store_configuration_and_http_headers(monkeypatch):
    with pytest.raises(ValueError, match="unsupported"):
        dedup.configure_store("redis")
    with pytest.raises(ValueError, match="conditional writes"):
        dedup.configure_store("http")

    monkeypatch.setattr(dedup, "_STORE_TOKEN", "secret")
    assert dedup._http_headers() == {"Content-Type": "application/json", "Authorization": "Bearer secret"}
    monkeypatch.setattr(dedup, "_STORE_URL", "")
    assert dedup._http_get() == []
    assert dedup._http_put([]) is None


def test_http_helpers_fail_closed_and_round_trip(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return Response(b'[{"key":"one"}]')

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(dedup, "_STORE_URL", "https://store.example/state")
    assert dedup._http_get() == [{"key": "one"}]
    dedup._http_put([{"key": "two"}])
    assert [request.get_method() for request, _timeout in requests] == ["GET", "PUT"]

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert dedup._http_get() == []
    dedup._http_put([{"key": "three"}])


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_delivery_claim_lifecycle_is_destination_scoped(tmp_path, backend):
    dedup.configure_store(backend)
    path = str(tmp_path / "state")
    _artifact, triage = _triage(path)
    key = triage.dedup_key

    assert dedup.claim_delivery(path, key, "jira")
    assert not dedup.claim_delivery(path, key, "jira")
    assert dedup.release_delivery_claim(path, key, "jira")
    assert not dedup.release_delivery_claim(path, key, "jira")
    assert dedup.claim_delivery(path, key, "jira")
    assert dedup.mark_filed(path, key, "JIRA-1", destination="jira")
    assert dedup.is_already_filed(path, key, "jira")
    assert not dedup.is_already_filed(path, key, "github")
    assert not dedup.claim_delivery(path, key, "jira")


@pytest.mark.parametrize("backend", ["file", "sqlite"])
@pytest.mark.parametrize("claimed_at", [0, "not-a-number"])
def test_expired_or_malformed_delivery_claim_can_be_reclaimed(tmp_path, backend, claimed_at):
    dedup.configure_store(backend)
    path = str(tmp_path / "state")
    _artifact, triage = _triage(path)
    key = triage.dedup_key
    if backend == "file":
        entries = dedup.load_state(path)
        entries[0]["delivery_claims"] = {"github": {"claimed_at": claimed_at}}
        assert dedup.save_state(path, entries)
    else:
        with dedup._sqlite_session(path) as connection:
            connection.execute("UPDATE incidents SET claims = ? WHERE key = ?", (json.dumps({"github": {"claimed_at": claimed_at}}), key))
    assert dedup.claim_delivery(path, key, "github")


def test_file_state_recovers_from_corruption_and_ignores_non_list_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{", encoding="utf-8")
    _artifact, triage = _triage(str(path))
    assert triage.dedup_key
    assert len(dedup.load_state(path)) == 1
    assert list(tmp_path.glob("state.json.corrupt-*"))

    path.write_text("{}", encoding="utf-8")
    assert dedup.load_state(path) == []
    assert path.exists()


def test_file_state_cap_protects_just_updated_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(dedup, "MAX_STATE_ENTRIES", 2)
    path = str(tmp_path / "state.json")
    entries = [
        {"key": "filed", "filed": True, "last_seen": "2026-01-03"},
        {"key": "old", "filed": False, "last_seen": "2026-01-01"},
        {"key": "new", "filed": False, "last_seen": "2026-01-02"},
    ]
    assert dedup.save_state(path, entries, keep_key="old")
    assert {entry["key"] for entry in dedup.load_state(path)} == {"filed", "old"}


def test_file_lock_never_removes_a_replaced_owner_lock(tmp_path):
    state = str(tmp_path / "state.json")
    lock = Path(state).with_suffix(".lock")
    with dedup._state_lock(state):
        lock.write_text("replacement-owner", encoding="utf-8")
    assert lock.read_text(encoding="utf-8") == "replacement-owner"


def test_file_lock_retries_permission_error_before_acquiring(tmp_path, monkeypatch):
    original_open = dedup.os.open
    calls = 0

    def open_after_transient_error(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("transient lock contention")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(dedup.os, "open", open_after_transient_error)
    monkeypatch.setattr(dedup, "_LOCK_RETRY_DELAY", 0)
    with dedup._state_lock(tmp_path / "state.json"):
        assert calls == 2


def test_sqlite_pruning_removes_old_delivered_and_prefers_delivered_for_capacity(tmp_path, monkeypatch):
    dedup.configure_store("sqlite", max_entries=2, retention_days=1)
    path = str(tmp_path / "state.sqlite3")
    old_artifact, old = _triage(path)
    assert dedup.mark_filed(path, old.dedup_key)
    with dedup._sqlite_session(path) as connection:
        connection.execute("UPDATE incidents SET last_seen = ? WHERE key = ?", ("2000-01-01T00:00:00+00:00", old.dedup_key))
    monkeypatch.setattr(dedup, "_prune_counter", dedup._SQLITE_PRUNE_EVERY - 1)
    dedup.check_duplicate(Artifacts(message="new", kind="import_error"), path, project_scope="test/project")
    assert dedup.lookup_incident(path, old.dedup_key) is None

    delivered = dedup.check_duplicate(Artifacts(message="delivered", kind="ci_failure"), path, project_scope="test/project")
    assert dedup.mark_filed(path, delivered.dedup_key)
    dedup.check_duplicate(Artifacts(message="one", kind="timeout"), path, project_scope="test/project")
    dedup.check_duplicate(Artifacts(message="two", kind="config_missing"), path, project_scope="test/project")
    assert dedup.lookup_incident(path, delivered.dedup_key) is None
    assert len(dedup.load_sqlite_entries(path)) == 2


def test_sqlite_corruption_fails_open_without_losing_analysis(tmp_path, capsys):
    dedup.configure_store("sqlite")
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not sqlite")
    triage = dedup.check_duplicate(Artifacts(message="failure"), str(path))
    assert triage.is_duplicate_of is None
    assert triage.occurrence_count == 1
    assert "dedup SQLite update failed" in capsys.readouterr().err


def test_dedup_empty_inputs_and_invalid_cached_snapshots_fail_closed(tmp_path):
    assert dedup.context_fingerprint(Artifacts(), source_fingerprint="source", model="", prompt_version="v1") == ""
    assert dedup.context_fingerprint(Artifacts(), source_fingerprint="source", model="model", prompt_version="") == ""
    for snapshot in ({}, [], "bad"):
        assert dedup.reusable_root_cause({"context_fingerprint": "context", "root_cause": snapshot}, "context") is None
    assert not dedup.mark_filed(None, "key")
    assert dedup.claim_delivery(None, "key", "github")
    assert not dedup.release_delivery_claim(None, "key", "github")
    assert dedup.lookup_incident(None, "key") is None
    assert not dedup.invalidate_root_cause(None, "key")


def test_sqlite_and_http_locks_defer_to_their_native_consistency(monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "_BACKEND", "sqlite")
    with dedup._state_lock(tmp_path / "state"):
        pass
    monkeypatch.setattr(dedup, "_BACKEND", "http")
    with dedup._state_lock(tmp_path / "state"):
        pass


def test_pid_liveness_rejects_non_positive_values():
    assert not dedup._pid_alive(0)
    assert not dedup._pid_alive(-1)
    assert dedup._is_stale_lock(Path("does-not-exist.lock")) is False


def test_fingerprint_keeps_deployment_scope_and_file_backend_miss_paths(tmp_path):
    artifact = Artifacts(kind="deployment_failed", stage="deploy", message="failure")
    other = Artifacts(kind="deployment_failed", stage="deploy", message="failure")
    other.deployment.environment = "production"
    assert dedup.fingerprint(artifact, project_scope="project") != dedup.fingerprint(other, project_scope="project")

    path = str(tmp_path / "state.json")
    assert not dedup.is_already_filed(path, "missing")
    assert not dedup.is_already_filed(None, "key")
    assert not dedup.mark_filed(path, "missing")
    assert not dedup.claim_delivery(path, "missing", "github")
    assert not dedup.release_delivery_claim(path, "missing", "github")


def test_file_delivery_claims_recover_malformed_entries(tmp_path):
    path = str(tmp_path / "state.json")
    _artifact, triage = _triage(path)
    entries = dedup.load_state(path)
    entries.insert(0, {"key": "other"})
    entries[-1]["deliveries"] = "corrupt"
    entries[-1]["delivery_claims"] = "corrupt"
    assert dedup.save_state(path, entries)
    assert dedup.mark_filed(path, triage.dedup_key, destination="jira")
    assert dedup.claim_delivery(path, triage.dedup_key, "github")
    entries = dedup.load_state(path)
    entries[-1]["filed"] = True
    assert dedup.save_state(path, entries)
    assert not dedup.claim_delivery(path, triage.dedup_key, "github")


def test_file_lock_cleans_missing_lock_file_without_error(tmp_path):
    state = str(tmp_path / "state.json")
    lock = Path(state).with_suffix(".lock")
    with dedup._state_lock(state):
        lock.unlink()
    assert not lock.exists()


def test_file_lock_rejects_live_owner_with_bounded_retry(tmp_path, monkeypatch):
    state = str(tmp_path / "state.json")
    Path(state).with_suffix(".lock").write_text(f"{os.getpid()}:owner", encoding="utf-8")
    monkeypatch.setattr(dedup, "_LOCK_RETRIES", 1)
    monkeypatch.setattr(dedup, "_LOCK_RETRY_DELAY", 0)
    with pytest.raises(RuntimeError, match="dedup lock"):
        with dedup._state_lock(state):
            pass


def test_save_and_load_dispatch_to_backend_specific_operations(tmp_path, monkeypatch):
    path = str(tmp_path / "state")
    monkeypatch.setattr(dedup, "_BACKEND", "sqlite")
    monkeypatch.setattr(dedup, "load_sqlite_entries", lambda _path: [{"key": "sqlite"}])
    assert dedup.load_state(path) == [{"key": "sqlite"}]
    assert not dedup.save_state(path, [])

    monkeypatch.setattr(dedup, "_BACKEND", "http")
    calls = []
    monkeypatch.setattr(dedup, "_http_get", lambda: [{"key": "http"}])
    monkeypatch.setattr(dedup, "_http_put", lambda entries: calls.append(entries))
    assert dedup.load_state(path) == [{"key": "http"}]
    assert dedup.save_state(path, [{"key": "saved"}])
    assert calls == [[{"key": "saved"}]]


def test_file_save_failure_and_load_io_failure_are_fail_closed(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    monkeypatch.setattr(dedup.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace denied")))
    assert not dedup.save_state(path, [{"key": "one"}])

    state = Path(path)
    state.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read denied")))
    assert dedup.load_state(path) == []


def test_sqlite_delivery_operations_fail_closed_for_missing_rows(tmp_path):
    dedup.configure_store("sqlite")
    path = str(tmp_path / "state.sqlite3")
    assert not dedup._sqlite_is_already_filed(path, "missing", "github")
    assert not dedup._sqlite_mark_filed(path, "missing")
    assert not dedup._sqlite_claim_delivery(path, "missing", "github")
    assert not dedup._sqlite_release_delivery_claim(path, "missing", "github")
    assert not dedup._sqlite_record_triage(path, type("Triage", (), {"dedup_key": ""})(), "", "")


def test_sqlite_filed_github_blocks_claim_and_releases_missing_claim(tmp_path):
    dedup.configure_store("sqlite")
    path = str(tmp_path / "state.sqlite3")
    _artifact, triage = _triage(path)
    assert dedup._sqlite_mark_filed(path, triage.dedup_key)
    assert not dedup._sqlite_claim_delivery(path, triage.dedup_key, "github")
    assert not dedup._sqlite_release_delivery_claim(path, triage.dedup_key, "github")


def test_sqlite_initialization_retries_locks_migrates_and_handles_zero_retry(monkeypatch, tmp_path):
    class Connection:
        def __init__(self):
            self.calls = 0
            self.closed = False
            self.row_factory = None

        def execute(self, _query):
            self.calls += 1
            if self.calls == 2:
                raise dedup.sqlite3.OperationalError("database is locked")
            return self

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(dedup.sqlite3, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(dedup, "_sqlite_init", lambda _connection: None)
    monkeypatch.setattr(dedup, "_LOCK_RETRY_DELAY", 0)
    assert dedup._sqlite_connect(tmp_path / "state.sqlite") is connection
    assert connection.calls >= 4

    monkeypatch.setattr(dedup, "_LOCK_RETRIES", 0)
    with pytest.raises(RuntimeError, match="unreachable SQLite"):
        dedup._sqlite_connect(tmp_path / "other.sqlite")


def test_sqlite_initialization_raises_after_final_lock_retry(monkeypatch, tmp_path):
    class Connection:
        row_factory = None

        def execute(self, query):
            if "busy_timeout" in query:
                return None
            raise dedup.sqlite3.OperationalError("database is locked")

        def close(self):
            pass

    monkeypatch.setattr(dedup.sqlite3, "connect", lambda *_args, **_kwargs: Connection())
    monkeypatch.setattr(dedup, "_LOCK_RETRIES", 1)
    with pytest.raises(dedup.sqlite3.OperationalError, match="locked"):
        dedup._sqlite_connect(tmp_path / "locked.sqlite")


def test_sqlite_migrates_missing_root_cause_column(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE incidents (key TEXT PRIMARY KEY)")
    with dedup._sqlite_session(path) as connection:
        names = {row["name"] for row in connection.execute("PRAGMA table_info(incidents)")}
    assert {"root_cause", "context_fingerprint"}.issubset(names)


def test_sqlite_filed_flag_blocks_github_claim_without_delivery_record(tmp_path):
    dedup.configure_store("sqlite")
    path = str(tmp_path / "state.sqlite3")
    _artifact, triage = _triage(path)
    with dedup._sqlite_session(path) as connection:
        connection.execute("UPDATE incidents SET filed = 1, deliveries = '{}' WHERE key = ?", (triage.dedup_key,))
    assert not dedup._sqlite_claim_delivery(path, triage.dedup_key, "github")


def test_pid_liveness_handles_portable_error_outcomes(monkeypatch):
    monkeypatch.setattr(dedup.os, "name", "posix")
    monkeypatch.setattr(dedup.os, "kill", lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    assert not dedup._pid_alive(1)
    monkeypatch.setattr(dedup.os, "kill", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    assert dedup._pid_alive(1)

    def os_error(*_args):
        error = OSError("missing")
        error.errno = dedup.errno.ESRCH
        raise error

    monkeypatch.setattr(dedup.os, "kill", os_error)
    assert not dedup._pid_alive(1)

    def windows_os_error(*_args):
        error = OSError("invalid process")
        error.winerror = 87
        raise error

    monkeypatch.setattr(dedup.os, "kill", windows_os_error)
    assert not dedup._pid_alive(1)


@pytest.mark.parametrize("wait_result, expected", [(0, False), (0x102, True), (0xFFFFFFFF, True)])
def test_pid_liveness_handles_windows_process_handles(monkeypatch, wait_result, expected):
    class Function:
        def __init__(self, result):
            self.result = result

        def __call__(self, *_args):
            return self.result

    kernel32 = type("Kernel", (), {
        "OpenProcess": Function(123),
        "WaitForSingleObject": Function(wait_result),
        "CloseHandle": Function(1),
    })()
    ctypes = type("Ctypes", (), {
        "WinDLL": staticmethod(lambda *_args, **_kwargs: kernel32),
        "get_last_error": staticmethod(lambda: 5),
        "c_uint32": int,
        "c_int": int,
        "c_void_p": int,
    })()
    monkeypatch.setitem(sys.modules, "ctypes", ctypes)
    monkeypatch.setattr(dedup.os, "name", "nt")
    assert dedup._pid_alive(1) is expected


def test_pid_liveness_windows_falls_back_when_ctypes_is_unavailable(monkeypatch):
    monkeypatch.setattr(dedup.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "ctypes", object())
    monkeypatch.setattr(dedup.os, "kill", lambda *_args: None)
    assert dedup._pid_alive(1)


def test_file_lock_retries_cleanup_io_error(tmp_path, monkeypatch):
    state = str(tmp_path / "state.json")
    lock = Path(state).with_suffix(".lock")
    original_read = Path.read_text
    reads = 0

    def transient_read(path, *args, **kwargs):
        nonlocal reads
        if path == lock and reads == 0:
            reads += 1
            raise OSError("temporary read error")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read)
    monkeypatch.setattr(dedup, "_LOCK_RETRY_DELAY", 0)
    with dedup._state_lock(state):
        pass
    assert not lock.exists()


def test_record_triage_rejects_empty_persistence_key():
    from hound.models import Triage

    assert not dedup.record_triage("state.json", Triage(), "component", "title")
