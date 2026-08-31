# Deployment timeline and causal-link schema (M7)

Milestone 7 adds an optional `timeline` section to the RCA document and
extends `context.deployment` and `failure.events` with new optional fields.
Legacy v2.0 documents (produced before M7) remain fully readable — every new
field is additive and never required in existing sections.

## Timeline section (`doc["timeline"]`)

Present only when the pipeline builds the timeline (always in M7+ code).

| Field | Type | Description |
|---|---|---|
| `entries` | `TimelineEvent[]` | Deterministically ordered event list. |
| `grouping` | `enum` | `runtime` / `pipeline` / `mixed` / `none`. |
| `ordering_basis` | `enum` | `timestamp_ns` / `sequence` / `log_order` / `mixed`. |
| `has_cycles` | `bool` | True when a parent link cycle was detected. |
| `cycle_warning` | `str` | Human message when `has_cycles` is true. |
| `primary_event_id` | `str` | ID of the primary failure event. |
| `downstream_event_ids` | `str[]` | IDs of downstream symptom events. |
| `recovery_event_ids` | `str[]` | IDs of recovery-marker events. |
| `customer_impact` | `enum` | `unknown` / `none` / `degraded` / `outage`. |
| `release_changed` | `bool?` | `null` when previous release not supplied; `true` when identity differs; `false` when identical. |
| `release_changed_fields` | `str[]` | Fields that differ between current and previous release. |

### `TimelineEvent` fields

| Field | Required | Description |
|---|---|---|
| `event_id` | yes | Stable run-scoped ID (`ev-001`, `ctx-ci`, etc.). |
| `position` | yes | 0-based index in the sorted timeline. |
| `timestamp_ns` | no | High-precision nanosecond epoch (null if unavailable). |
| `timestamp` | no | ISO 8601 readable timestamp. |
| `sequence` | no | Deterministic ordering fallback when clocks are absent. |
| `stage` | yes | `ci` / `build` / `test` / `deploy` / `unknown`. |
| `kind` | yes | Failure kind (or `unknown` for context markers). |
| `role` | yes | `primary` / `downstream` / `recovery` / `context` / `unknown`. |
| `message` | yes | Bounded human-readable message (≤ 1000 chars). |
| `trace_id` | no | W3C-compatible trace ID (32 hex chars). |
| `span_id` | no | Current span ID (16 hex chars). |
| `parent_span_id` | no | Parent span ID; nullable for root spans. |
| `service` | no | Service target name (if available). |
| `source` | yes | `failure_event` / `deployment` / `ci` / `recovery` / `""`. |
| `ordering_basis` | yes | Per-entry basis: `timestamp_ns` / `sequence` / `log_order`. |
| `uncertainty` | yes | Explains when ordering is approximate. |

## Deterministic ordering

Entries are sorted by a key:

```python
(sort_group, timestamp_ns_or_0, sequence_or_0, original_index)
```

where `sort_group` is 0 for clocked entries, 1 for sequenced, 2 for unclocked.
The inter-group policy (clocked before sequenced before unclocked) is documented
and never reorders entries that lack comparable evidence. Each entry carries
`ordering_basis` and `uncertainty` so consumers can tell a high-confidence clock
from a fallback ordering.

## Causal-link wire format

Extended fields on `failure.events`:

| Field | Description |
|---|---|
| `event_id` | Stable run-scoped ID (e.g. `ev-001`). |
| `trace_id` | Request/invocation-scoped ID. Aligned with W3C Trace Context (32 hex). |
| `span_id` | Current span ID (16 hex). |
| `parent_span_id` | Nullable; links to the causal parent. Supports partial traces. |
| `timestamp` | ISO 8601 timestamp (optional). |
| `timestamp_ns` | High-precision nanosecond epoch (optional; authoritative clock). |
| `sequence` | Deterministic ordering fallback (optional). |

When a log line carries a `traceparent` header (`00-trace-span-flags`), the trace
field maps to `trace_id` and the span field maps to `parent_span_id` (the span that
initiated the current request). Explicit `trace_id=... span_id=... parent_span_id=...`
fields (from OpenTelemetry structured logs) are preferred.

## Runtime vs pipeline grouping

- **Runtime**: events carry `trace_id` and `span_id` with causal parent links.
- **Pipeline**: no trace IDs; ordering follows CI job/step structure via sequence.
- **Mixed**: partial instrumentation — some services are linked, some are not.
- **None**: no failure events.

Partial traces are preserved, not dropped. Un-instrumented services produce
events with empty `trace_id` and appear in the flat deterministic list.

## Cycle detection

Mis-assigned `parent_span_id` values (common from partial instrumentation or
incorrect user instrumentation) can create cycles. The builder performs iterative
DFS with three-color marking. If a cycle is detected:

1. `has_cycles` is set to `true`.
2. `cycle_warning` carries a human-readable diagnostic.
3. The flat deterministic list is returned unchanged (safe fallback).

Cycles are surfaced in the timeline metadata, never propagated to consumers.
This is consistent with the project invariant: *insufficient evidence is a valid
result; the build never fails due to a cycle in user-provided metadata.*

## Deployment context extension

New optional fields on `context.deployment` (backward-compatible):

| Field | Purpose |
|---|---|
| `service` | Service target name. |
| `workload` | Workload identifier. |
| `commit` | Release commit SHA. |
| `image_digest` | Container image digest (e.g. `sha256:...`). |
| `finished_at` | Deployment end timestamp (ISO 8601). |
| `previous_commit` | Commit of the previous healthy release. |
| `previous_image_digest` | Image digest of the previous healthy release. |
| `customer_impact` | Operator-supplied impact status (`unknown` / `none` / `degraded` / `outage`). |

## Backward compatibility

- **v1.4 readers** ignore unknown top-level keys; the `timeline` section is transparent.
- **v2.0 readers** tolerate missing `timeline` (optional for legacy docs).
- **New v2.0 documents** always include `timeline` when built by the pipeline.
- **Golden v2.0 documents** (`tests/golden/`) are unchanged; they do not include
  `timeline` and validate successfully because timeline is not in the required set.
- Sidecar JSON for `context.deployment` may omit all new fields; detection fills
  what it can find in the log; the sidecar always wins for shared fields.

## Customer-impact classification (deterministic)

The timeline derives `customer_impact` from evidence in priority order:

1. Operator-supplied `deployment.customer_impact` (sidecar) wins when present.
2. Log-text markers: `outage` > `degraded` (highest match wins).
3. Recovery confirmed (rollback succeeded) without impact markers → `none`.
4. Default: `unknown` (fail-closed).
