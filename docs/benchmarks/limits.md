# Bounded operation limits

These are implementation ceilings used to keep untrusted artifacts and server
requests bounded. They are not throughput promises; use the versioned benchmark
note for measurements on a named runner.

| Boundary | Limit | Behavior when exceeded |
|---|---:|---|
| HTTP request body | 1 MiB | Request rejected with `413`/`request_too_large` |
| HTTP response | 256 KiB | Safe bounded error response |
| Server log snapshot | 16 MiB | Job rejected as oversized |
| Structured XML/JSON/SARIF artifact | 2 MiB | Artifact is skipped or fails closed |
| Generic log read | 16 MiB maximum window | Head/tail windowing preserves failure context |
| Server workers | 1–64 | Configuration validation rejects values outside the range |
| Server active queue | 1–100,000 | Admission returns `429 queue_full` |
| Server requests/client/minute | 1–1,000,000 | Process-local token bucket; proxy required for shared limiting |
| Finished job retention | 30–86,400 seconds | Expired completed/failed/canceled jobs are removed |
| Source files per report | 20 | Additional files are not collected |
| Source bytes per file / report | 64 KiB / 256 KiB | Additional content is not collected |
| Static impact depth | 2 | Deeper edges are omitted and never called runtime truth |
| Connector items / item bytes / total bytes | 8 / 32 KiB / 128 KiB | Evidence is truncated or audited as partial |
| Delivery external ID | 2,048 characters | Persistence rejects oversized IDs after redaction |

All limits are local and deterministic. A limit or timeout must produce an
actionable status; it must not silently turn a failed analysis into a successful
claim.
