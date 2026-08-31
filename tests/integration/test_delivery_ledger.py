from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from hound.output.delivery import DeliveryLedger, delivery_key


def test_idempotency_key_is_incident_and_destination_scoped():
    assert delivery_key("incident", "github") == delivery_key("incident", "github")
    assert delivery_key("incident", "github") != delivery_key("incident", "jira")
    assert delivery_key("incident-a", "github") != delivery_key("incident-b", "github")


def test_concurrent_reservation_has_one_winner(tmp_path):
    path = tmp_path / "deliveries.sqlite3"

    def reserve(_):
        return DeliveryLedger(path).reserve("incident", "github")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reserve, range(16)))
    assert results.count(True) == 1
    assert results.count(False) == 15


def test_confirmed_delivery_cannot_be_reserved_again(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "github") is True
    ledger.confirm("incident", "github", "https://example.test/issues/1")
    assert ledger.reserve("incident", "github") is False
    record = ledger.get("incident", "github")
    assert record is not None
    assert record.state == "confirmed"
    assert record.external_id.endswith("/1")


def test_unknown_requires_reconciliation_and_blocks_retry(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "slack") is True
    ledger.mark_unknown("incident", "slack", "timeout after request body sent")
    assert ledger.reserve("incident", "slack") is False
    ledger.reconcile("incident", "slack", "message-42")
    record = ledger.get("incident", "slack")
    assert record is not None and record.state == "confirmed"


def test_failed_delivery_can_retry(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "jira") is True
    ledger.fail("incident", "jira", "rejected before creation")
    assert ledger.reserve("incident", "jira") is True
    record = ledger.get("incident", "jira")
    assert record is not None and record.attempts == 2


def test_cleanup_dry_run_preserves_rows(tmp_path, monkeypatch):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "github") is True
    ledger.confirm("incident", "github", "issue-1")
    with ledger._connect() as connection:
        connection.execute("UPDATE deliveries SET updated_at = 0")
    assert ledger.cleanup(30, dry_run=True) == 1
    assert ledger.get("incident", "github") is not None
    assert ledger.cleanup(30, dry_run=False) == 1
    assert ledger.get("incident", "github") is None


def test_stale_pending_becomes_unknown_instead_of_resending(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "github") is True
    with ledger._connect() as connection:
        connection.execute("UPDATE deliveries SET updated_at = 0")
    assert ledger.reserve("incident", "github") is False
    record = ledger.get("incident", "github")
    assert record is not None
    assert record.state == "unknown"
    assert "reconciliation" in record.error


def test_delivery_ledger_preserves_corrupt_database(tmp_path):
    path = tmp_path / "deliveries.sqlite3"
    path.write_bytes(b"not a sqlite database")
    with pytest.raises(ValueError, match="original preserved"):
        DeliveryLedger(path)
    recovery = next(tmp_path.glob("deliveries.sqlite3.corrupt-*"))
    assert (recovery / "deliveries.sqlite3").read_bytes() == b"not a sqlite database"
