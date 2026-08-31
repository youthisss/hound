# Persistent State Backup And Recovery

Hound keeps independent SQLite stores for deduplication, jobs, QA history,
feedback, and delivery. Stop the server and all writers before a manual restore.
Never copy only a live database file while ignoring its WAL state.

## Backup

Use SQLite's online backup API for each database while the source filesystem is
trusted. The example creates a consistent copy without copying `-wal` or `-shm`
sidecars directly.

```powershell
uv run python -c "import sqlite3; s=sqlite3.connect(r'hound-output/.hound/jobs.sqlite3'); d=sqlite3.connect(r'backup/jobs.sqlite3'); s.backup(d); d.close(); s.close()"
uv run python -c "import sqlite3; c=sqlite3.connect(r'backup/jobs.sqlite3'); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"
```

Repeat for existing `state.sqlite3`, `history.sqlite3`, feedback, and delivery
ledger files. Store backups outside the output root, restrict their permissions,
and record a SHA-256 digest. Backups can contain repository identifiers and
sanitized incident metadata even though raw logs are not stored.

## Restore

1. Stop Hound and retain the current database plus `-wal` and `-shm` sidecars.
2. Verify the backup checksum and require `PRAGMA integrity_check` to return `ok`.
3. Copy the verified backup to a temporary file in the target directory.
4. Atomically rename the temporary file to the expected database name while no
   process is using it, then restart Hound and check `hound doctor --json`.
5. Keep the displaced database until application-level records are verified.

When startup detects a damaged jobs, history, or delivery database, Hound moves
the original and its SQLite sidecars into a timestamped `.corrupt-*` recovery
directory and fails with its location. It never overwrites that evidence with a
new empty store. Legacy dedup state follows the same preserve-and-recover rule.

Queued or running server jobs left by a process interruption are marked failed
with an interruption reason on restart. Completed jobs survive until retention
cleanup; external delivery records in `unknown` state require reconciliation and
are never retried automatically.
