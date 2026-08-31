# Production Pilot Evidence

Do not mark this document accepted until every placeholder is replaced with
reviewed aggregate evidence. Raw production logs remain outside the repository.

## Provenance

| Field | Value |
|---|---|
| Hound commit | `<full SHA>` |
| Configuration profile | `<sanitized profile>` |
| Pilot dates | `<UTC range>` |
| Repository count | `<at least 2>` |
| Sanitized real failures | `<100-300>` |
| Reviewers | `<names or handles>` |

## Measurements

| Metric | Result | Accepted limitation |
|---|---:|---|
| Median triage-time reduction | `<value>` | `<none or rationale>` |
| Supported-kind precision | `<value>` | `<none or rationale>` |
| Regression/flaky precision | `<value>` | `<none or rationale>` |
| False deduplication rate | `<value>` | `<none or rationale>` |
| Unknown rate | `<value>` | `<none or rationale>` |
| Ticket edit rate | `<value>` | `<none or rationale>` |
| Connector success/timeout/partial failure | `<values>` | `<none or rationale>` |
| Redaction escapes | `<must be 0>` | `none` |
| Median/p95 LLM tokens and cost per incident | `<values>` | `<none or rationale>` |
| Delivery confirmed/unknown/duplicate | `<values; duplicates must be 0>` | `<none or rationale>` |
| Storage growth and throughput | `<values>` | `<none or rationale>` |

## Go/No-Go

- [ ] Zero known redaction escapes.
- [ ] Zero duplicate confirmed deliveries in retry tests.
- [ ] Precision and unknown-rate results are documented.
- [ ] Every missed product target has explicit reviewer acceptance.
- [ ] Final decision and date: `<GO or NO-GO, UTC date>`.
