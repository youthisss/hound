# Hound operational metrics (M12)

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

The existing demo harness remains the permanent smoke/scale entry point:

```powershell
uv run python demo_project/run_demo.py --profile smoke
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

Benchmark output is runner-dependent evidence, not a hard performance promise.
