from copy import deepcopy

import pytest

from hound.models import Artifacts, FailedTest, StackFrame
from hound.triage import dedup


def _named_failure(assertion, *, summary=False, file="tests/test_cart.py"):
    name = f"{file}::test_cart_total"
    return Artifacts(kind="test_failure", stage="test",
                     message=f"FAILED {name} - {assertion}" if summary else f"E {assertion}",
                     failed_tests=[FailedTest(name=name, file=file, assertion=assertion)],
                     frames=[] if summary else [StackFrame(file=file, line=12, function="AssertionError")])


@pytest.mark.parametrize("actual,expected", [
    ("5", "10"), ("2", "4"), ("[1, 2]", "[1, 3]"),
    ("'A'", "'a'"), ("0x12", "0x13"), ("-2", "4"),
    ("{'a': 2}", "{'a': 4}"), ("True", "False"),
    ("'2026-01-01T12:00:00Z'", "'2026-01-02T12:00:00Z'"),
])
def test_named_literal_equality_matches_across_formats(actual, expected):
    original = _named_failure(f"assert {actual} == {expected}")
    repeat = _named_failure(f"AssertionError: expected {expected}, got {actual}", summary=True)
    assert dedup.fingerprint(original) == dedup.fingerprint(repeat)


@pytest.mark.parametrize("different", [
    "AssertionError: expected 4, got 3", "AssertionError: expected 5, got 2",
    "AssertionError: expected 2, got 4", "AssertionError: expected 4, got '2'",
    "assert 2 != 4", "assert inventory == 4",
])
def test_named_literal_differences_do_not_merge(different):
    assert dedup.fingerprint(_named_failure("assert 2 == 4")) != dedup.fingerprint(_named_failure(different, summary=True))


def test_named_assertions_keep_case_paths_and_project_scope():
    original = _named_failure("assert 'A' == 'a'")
    assert dedup.fingerprint(original) != dedup.fingerprint(_named_failure("assert 'a' == 'a'"))
    assert dedup.fingerprint(original) != dedup.fingerprint(_named_failure("assert 'A' == 'a'", file="tests/other.py"))
    assert dedup.fingerprint(original, project_scope="one") != dedup.fingerprint(original, project_scope="two")


def test_timestamp_and_object_address_noise_is_complete_and_narrow():
    assert dedup.normalize("error 2026-01-01T12:00:00.123Z <Thing object at 0x123>") == dedup.normalize("error 2026-02-02T13:00:00.456+05:30 <Thing object at 0x456>")
    assert dedup.normalize("value at 0x12") != dedup.normalize("value at 0x13")
    assert dedup.fingerprint(_named_failure("assert '2026-01-01' == 'x'")) != dedup.fingerprint(_named_failure("assert '2026-01-02' == 'x'"))


def test_identity_separates_projects_paths_and_assertions():
    artifact = Artifacts(kind="test_failure", message="assert [1] == [2]",
                         frames=[StackFrame(file="a.py", function="run")])
    key = dedup.fingerprint(artifact, project_scope="org/one")
    assert key.startswith("incident-v2:")
    assert key != dedup.fingerprint(artifact, project_scope="org/two")
    other = deepcopy(artifact)
    other.frames[0].file = "b.py"
    assert key != dedup.fingerprint(other, project_scope="org/one")
    other = deepcopy(artifact)
    other.message = "assert [1] == [3]"
    assert key != dedup.fingerprint(other, project_scope="org/one")
    artifact.failed_tests = [FailedTest(name="test_x[A]", assertion="assert 'A' == 'a'")]
    other = deepcopy(artifact)
    other.failed_tests[0].assertion = "assert 'B' == 'b'"
    assert dedup.fingerprint(artifact) != dedup.fingerprint(other)


def test_volatile_locations_but_not_assertion_values_are_normalized():
    assert dedup.normalize("x.py:12 2026-01-01 12:00:00") == dedup.normalize("x.py:99 2026-02-02 13:00:00")
    assert dedup.normalize("assert [1] == [2]") != dedup.normalize("assert [1] == [3]")
    assert dedup.normalize("assert 0x12 == 0x13") != dedup.normalize("assert 0x12 == 0x14")
    assert dedup.normalize("assert [0x12] == [0x13]") != dedup.normalize("assert [0x12] == [0x14]")
    assert dedup.normalize("assert {'x':12}") != dedup.normalize("assert {'x':13}")


def _context(artifact, **overrides):
    options = dict(source_fingerprint="source-digest", model="provider/model", prompt_version="v1")
    options.update(overrides)
    return dedup.context_fingerprint(artifact, **options)


@pytest.mark.parametrize("field", ["source_fingerprint", "model", "prompt_version", "policy_version"])
def test_cache_context_tracks_analysis_versions(field):
    artifact = Artifacts(message="failure")
    assert _context(artifact) != _context(artifact, **{field: "changed"})


def test_context_changes_without_splitting_incident():
    artifact = Artifacts(message="failure")
    other = deepcopy(artifact)
    other.git.head = "new-commit"
    other.source_evidence = [{"file": "a.py", "content": "changed"}]
    assert dedup.fingerprint(artifact) == dedup.fingerprint(other)
    assert _context(artifact) != _context(other)
    assert _context(artifact, source_fingerprint="") == ""
    assert dedup.reusable_root_cause({"root_cause": {"hypothesis": "old"}}, _context(artifact)) is None


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_cache_contract_and_invalidation_preserve_delivery(tmp_path, backend):
    dedup.configure_store(backend)
    try:
        path = str(tmp_path / "state")
        artifact = Artifacts(message="failure")
        triage = dedup.check_duplicate(artifact, path, project_scope="org/repo")
        context = _context(artifact)
        snapshot = {"hypothesis": "cause", "confidence": "high"}
        assert dedup.record_triage(path, triage, "component", "title", snapshot, context_key=context)
        assert dedup.mark_filed(path, triage.dedup_key, "https://ticket")
        entry = dedup.lookup_incident(path, triage.dedup_key)
        assert dedup.reusable_root_cause(entry, context) == snapshot
        assert dedup.reusable_root_cause(entry, "wrong-context") is None
        assert dedup.invalidate_root_cause(path, triage.dedup_key)
        entry = dedup.lookup_incident(path, triage.dedup_key)
        assert dedup.reusable_root_cause(entry, context) is None
        assert entry["count"] == 1
        assert dedup.is_already_filed(path, triage.dedup_key)
        assert dedup.check_duplicate(artifact, path, project_scope="org/repo").occurrence_count == 2
        assert not dedup.invalidate_root_cause(path, "missing")
    finally:
        dedup.configure_store("file")


def test_legacy_file_entries_are_retained_but_not_matched(tmp_path):
    path = str(tmp_path / "state.json")
    old_key = "a" * 64
    dedup.save_state(path, [{"key": old_key, "filed": True, "root_cause": {"hypothesis": "old"}}])
    triage = dedup.check_duplicate(Artifacts(message="failure"), path)
    assert triage.is_duplicate_of is None
    assert dedup.lookup_incident(path, old_key)["filed"]
    assert len(dedup.load_state(path)) == 2


def test_sqlite_migrates_cache_metadata(tmp_path):
    import sqlite3

    path = str(tmp_path / "state.sqlite")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE incidents (key TEXT PRIMARY KEY, root_cause TEXT)")
        conn.execute("INSERT INTO incidents VALUES ('legacy', ?)", ('{"hypothesis":"old"}',))
    dedup.configure_store("sqlite")
    try:
        entry = dedup.lookup_incident(path, "legacy")
        assert entry["context_fingerprint"] == ""
        assert dedup.reusable_root_cause(entry, "context") is None
    finally:
        dedup.configure_store("file")
