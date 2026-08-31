# Server Deployment and Reverse Proxy Operations

Hound's HTTP receiver (`hound serve` or `hound server`) accepts failure artifacts from trusted pipelines.

## Security Boundary

- Always bind the service to loopback (`127.0.0.1` or `::1`).
- Terminate TLS and authenticate clients through a reverse proxy (nginx or Caddy).
- Require `HOUND_SERVER_TOKEN` (or `--token`) on every non-health request.

## Caddy Configuration Example

```caddy
hound.internal.domain {
    tls internal

    # Request size limit: 1MB body
    request_body {
        max_size 1048576
    }

    # Health probes remain unauthenticated
    handle /health {
        reverse_proxy 127.0.0.1:8123
    }
    handle /ready {
        reverse_proxy 127.0.0.1:8123
    }

    # All analysis endpoints require Bearer auth forwarded to Hound
    handle {
        reverse_proxy 127.0.0.1:8123 {
            header_up Host {host}
            header_up X-Real-IP {remote_host}
        }
    }
}
```

For a rate-limited nginx configuration with explicit bearer forwarding and safe
access logging, use [`docs/examples/nginx-hound.conf`](examples/nginx-hound.conf).

## Backup and Retention

The server writes durable jobs to `<output-dir>/.hound-agent/jobs.sqlite3` and incident deduplication to `<output-dir>/.hound-agent/state.sqlite3`.

1. To back up, flush or copy the SQLite database along with `-wal` and `-shm` sidecars.
2. Expired jobs are cleaned up automatically via `--job-ttl` (default 3600s).
3. Delivery ledger records can be pruned using dry-run verification first:
   `DeliveryLedger.cleanup(retention_days=30, dry_run=True)`.

Use the consistent backup, integrity-check, restore, and corruption procedures in
[`state-recovery.md`](state-recovery.md); do not copy a live main database while
discarding its WAL sidecars.

## Operational Logs

Text logs are written to stderr by default. Use `--log-format json` for structured
logs and `--log-level debug` only during bounded diagnosis. JSON records include
`timestamp`, `level`, `component`, `event`, and request/job IDs where available.
Every HTTP response also carries `X-Request-ID`. Hound never logs bearer tokens,
request bodies, artifact contents, provider responses, or exception details.

The built-in rate limiter is process-local and resets on restart. Internet-facing
or multi-instance deployments must enforce shared rate limits at the proxy.
