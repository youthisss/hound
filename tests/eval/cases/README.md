# Synthetic regression corpus

All artifacts here are hand-authored synthetic examples, not real incidents or
production captures. The original eight labels are preserved. The additional
40 cases broaden regression coverage across every supported failure kind; they
do not establish production accuracy.
`held_out` is a regression split, not an independently collected blind benchmark.

Labels describe the evidence, even when the current parser disagrees. Healthy
artifacts have `is_failure: false`; unsupported evidence omits that optional field
because it proves neither success nor failure. Unknown stage/kind is intentional
for healthy and unsupported artifacts. Failure cases have `is_failure: true`.
Build severity permits medium/high; deployment failures without observed customer
impact require high, never critical. Primary-event labels identify the failure
stage/kind, not incidental success or cleanup output.

The `inventory-count` pair represents the same failing assertion across two runs.
`assertion-distinct` has the same test identity but a different assertion and is
deliberately not a duplicate. Null groups do not assert duplicates, including
unrelated healthy/unsupported inputs. Preserve assertion distinctions rather than
relabelling these examples to match a fingerprint collision.

Structured examples use the implemented JUnit, pytest-json-report, Go NDJSON and
SARIF shapes. JSON artifacts live in `artifacts/` so label discovery cannot mistake
them for labels. Passing JUnit output includes failure-related test names to check
that names are not treated as failing records.

Coverage includes passing pytest/Go/build/rollout output, source-code and quoted
exception text, unsupported output, mixed pass/fail output, import/compiler and
dependency errors, TLS/disk/rate-limit/timeouts, every deployment failure kind,
JUnit, pytest JSON, Go JSON and SARIF. Runner syntax coverage includes pytest,
Jest/Vitest-style results, Go, JUnit/Surefire, Rust, Ruby, Java, TypeScript,
GitHub annotations, and common Kubernetes/CI wrappers. Remaining gaps include
real incident data, large/truncated artifacts, Windows traces, comprehensive
framework coverage, customer-impact metadata, and independently adjudicated
root-cause outcomes.
