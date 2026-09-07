"""Persistence failure-path tests for atomic writes and delivery cleanup."""
from __future__ import annotations

import sqlite3

import pytest


def test_atomic_write_tolerates_permission_mode_failure(tmp_path, monkeypatch):
    from hound.fsio import atomic_write

    target = tmp_path / "state.json"
    monkeypatch.setattr("hound.fsio.os.chmod", lambda *_args: (_ for _ in ()).throw(OSError("chmod denied")))
    atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_removes_temporary_file_when_replace_fails(tmp_path, monkeypatch):
    from hound.fsio import atomic_write

    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr("hound.fsio.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("replace denied")))
    with pytest.raises(OSError, match="replace denied"):
        atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_delivery_connect_closes_connection_when_initialization_fails(tmp_path, monkeypatch):
    from hound.output.delivery import DeliveryLedger

    ledger = DeliveryLedger(tmp_path / "delivery.sqlite3")
    closed = []

    class BrokenConnection:
        row_factory = None

        def execute(self, _statement):
            raise sqlite3.OperationalError("broken connection")

        def close(self):
            closed.append(True)

    monkeypatch.setattr("hound.output.delivery.sqlite3.connect", lambda *_args, **_kwargs: BrokenConnection())
    with pytest.raises(sqlite3.OperationalError, match="broken connection"):
        ledger._connect()
    assert closed == [True]
