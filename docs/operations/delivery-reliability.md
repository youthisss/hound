# Delivery reliability and recovery (M12)

External delivery remains opt-in. Hound maintains a separate SQLite ledger at
`<output>/.hound/deliveries.sqlite3`; it does not rely only on dedup state.

## State model

- `pending`: one worker holds the idempotent reservation
- `confirmed`: an external ticket/message ID or URL was persisted
- `failed`: the request is known not to have created an external object and may retry
- `unknown`: the outcome may have succeeded remotely and must be reconciled before retry

The idempotency key is SHA-256 over incident identity plus destination. Concurrent
workers have one reservation winner. A stale `pending` row becomes `unknown`
rather than being resent.

## Reconciliation

Operators should verify the destination using incident title/dedup metadata. If
the object exists, call `DeliveryLedger.reconcile(incident_key, destination,
external_id)` from an administrative recovery script. If it provably does not
exist, mark the row `failed` before retrying. Tokens and request payloads are not
stored in the ledger.

## Retention

`DeliveryLedger.cleanup(days, dry_run=True)` reports removable confirmed/failed
rows. Run dry-run first, export or back up the SQLite file, then use
`dry_run=False`. Pending and unknown outcomes are never removed by retention.

SQLite uses WAL, busy timeout, schema metadata, atomic `BEGIN IMMEDIATE`
reservations, and short-lived connections. Back up the main database together
with `-wal`/`-shm` files or checkpoint it while Hound is stopped.
