# Operational correlation (M9)

M9 combines explicit release identity, bounded metric samples, runtime trace
spans, SLO context, and trusted runbooks in the optional top-level `devops`
section. It does not claim that correlation proves causality.

## Release comparison

Only explicitly supplied current/previous metadata is compared:

- revision and commit
- image and manifest digest
- resource fingerprint
- migration and runtime version
- dependency fingerprint
- feature-flag metadata version

Secret values are never requested or compared. Missing current values produce
`status: unknown`; absent previous values are omitted rather than inferred.

## Prometheus

When `--enrich`, trust policy, deploy stage, context file, and
`observability.prometheus_url` all permit collection, Hound queries one bounded
range around `deployment.started_at`/`finished_at`. The default window is 15
minutes before and after and is configurable from 1 to 120 minutes.

Samples record metric, numeric value, timestamp, source, query window, and this
uncertainty statement: metric movement is correlation and does not prove that a
deployment caused the change. Responses are limited to 256 KiB and 200 samples.

## Tempo-compatible traces

Hound queries at most five W3C-compatible trace IDs already present in failure
events. It reads at most 200 spans and records service, parent link, timing,
status, and version when available. The estimated critical path follows available
parent links and remains explicitly uncertain because partial traces can omit the
true path. Trace-parent cycles are bounded and reported instead of traversed
indefinitely.

## SLO and severity

`deployment.slo_target` and `deployment.error_budget_remaining` are explicit
operator evidence. The report preserves `static_severity` and separately derives
`effective_severity`:

- outage or exhausted error budget: at least `critical`
- degraded impact or error budget below 10 percent: at least `high`
- otherwise retain static severity

## Trusted configuration

```yaml
observability:
  prometheus_url: https://prometheus.example.test
  tempo_url: https://tempo.example.test
  window_minutes: 15
runbooks:
  api: https://runbooks.example.test/api
```

Tokens should use `PROMETHEUS_TOKEN` and `TEMPO_TOKEN`. URLs require HTTPS except
for loopback development endpoints. Tokens, query URLs, and raw responses are
not written to connector audit records.
