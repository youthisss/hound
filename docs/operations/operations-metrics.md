# Hound operational metrics

The process-local bounded telemetry registry records numeric operational data
only. It never stores logs, prompts, source snippets, credentials, request bodies,
or provider responses.

Current metrics include analysis count and p50/p95/max latency, unknown and
fallback counts, redacted runs, dedup hits, connector errors, LLM token totals,
delivery attempts/confirmed/unknown/idempotent skips, server queue depth, and last
JSON output size. The authenticated server `/stats` response includes the snapshot
under `hound`.

Observations are bounded to the latest 10,000 values per metric. Metrics reset on
process restart; durable incident, job, history, feedback, and delivery state stay
in their SQLite stores.

Metric behavior is covered by the automated test suite. Runtime values remain
environment-specific observations, not performance guarantees.
