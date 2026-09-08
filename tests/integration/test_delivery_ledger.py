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


def test_delivery_admin_listing_and_explicit_retry(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "jira") is True
    ledger.fail("incident", "jira", "rejected before creation")
    rows = ledger.list_records(state="failed", incident_key="incident")
    assert len(rows) == 1
    assert rows[0].destination == "jira"
    assert ledger.retry_failed("incident", "jira") is True
    assert ledger.get("incident", "jira").state == "pending"
    assert ledger.retry_failed("incident", "jira") is False


def test_reconcile_rejects_known_failed_outcome(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "github") is True
    ledger.fail("incident", "github", "not created")
    with pytest.raises(ValueError, match="only unknown"):
        ledger.reconcile("incident", "github", "issue-1")


def test_external_id_is_redacted_before_persistence(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "slack") is True
    ledger.confirm("incident", "slack", "https://example.test/hook?token=ghp_abcdefghijklmnopqrstuvwxyz123456")
    record = ledger.get("incident", "slack")
    assert record is not None
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in record.external_id


def test_operator_mark_failed_requires_verified_absence_and_redacts_reason(tmp_path):
    ledger = DeliveryLedger(tmp_path / "deliveries.sqlite3")
    assert ledger.reserve("incident", "github") is True
    ledger.mark_unknown("incident", "github", "request failed token=ghp_abcdefghijklmnopqrstuvwxyz123456")

    # The low-level transition is intentionally not a confirmation prompt. The
    # CLI owns that human acknowledgement; this call verifies safe persistence.
    ledger.mark_failed("incident", "github", "verified absent token=ghp_abcdefghijklmnopqrstuvwxyz123456")
    record = ledger.get("incident", "github")
    assert record is not None and record.state == "failed"
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in record.error
