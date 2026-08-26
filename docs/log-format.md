# Correlated Error Log Format

Hound can correlate a CI/CD failure with the request or actor visible in the
log. Put the correlation fields on the same line as an error or use structured
JSON logging. The fields are optional: logs without them remain valid, but
their `context.request` output is empty.

## Canonical Fields

| Field | Use | Example |
|---|---|---|
| `request_id` | Request correlation | `request_id=req_01HABC` |
| `trace_id` | Cross-service tracing | `trace_id=trace_01HABC` |
| `session_id` | Session correlation | `session_id=sess_01HABC` |
| `user_id` | Authenticated actor | `user_id=u_12345` |
| `method` and `path` | HTTP request route | `method=POST path=/api/checkout` |

Use opaque IDs containing letters, digits, `.`, `_`, or `-`. Do not log
passwords, tokens, cookies, or raw personal data as correlation fields. Hound
redacts recognized secrets and PII by default, but safe opaque identifiers are
more useful and more reliable.

## Examples

Key-value logging:

```text
ts=2026-08-24T10:15:30Z level=error request_id=req_01HABC user_id=u_12345 method=POST path=/api/checkout msg="cart persistence failed: deadline exceeded"
```

JSON logging:

```json
{"ts":"2026-08-24T10:15:30Z","level":"error","request_id":"req_01HABC","user_id":"u_12345","method":"POST","path":"/api/checkout","msg":"cart persistence failed"}
```

Python `logging`:

```python
logger.error(
    "cart persistence failed",
    extra={"request_id": request_id, "user_id": user_id, "method": "POST", "path": "/api/checkout"},
)
```

Go `zap`:

```go
logger.Error("cart persistence failed", zap.String("request_id", requestID), zap.String("user_id", userID), zap.String("method", "POST"), zap.String("path", "/api/checkout"))
```

JavaScript `pino`:

```js
logger.error({ request_id, user_id, method: "POST", path: "/api/checkout" }, "cart persistence failed");
```

Java `logback` / structured logger:

```java
logger.atError().addKeyValue("request_id", requestId).addKeyValue("user_id", userId).addKeyValue("method", "POST").addKeyValue("path", "/api/checkout").log("cart persistence failed");
```

## Extraction Behavior

Hound reads the bounded log window and selects the most frequent value for
each scalar ID. It retains up to 10 distinct user IDs in first-seen order and
selects the most frequent method/path pair. This supports a log containing
multiple requests while keeping output bounded.

The extracted fields appear in `context.request` in RCA schema v2.0; persisted
v1.4 reports remain readable. They are
context for investigation, not proof of root cause, and are intentionally not
included in the dedup fingerprint: identical failures from different users
remain one incident.

## Validation

Check that error-producing logs carry a request or trace ID:

```powershell
rg -n -i "(request_id|requestId|req_id|x-request-id|trace_id|traceId)\s*[:=]" path\to\logs
```

For JSON logs, confirm the same keys are emitted as string fields. Test both a
successful request and a failing request; Hound only knows about correlation
IDs that reach the collected log artifact.
