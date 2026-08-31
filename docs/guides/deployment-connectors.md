# Bounded deployment connectors (M8)

Hound can optionally collect Kubernetes or Helm evidence for an explicit
deployment context. Collection remains read-only, bounded, and disabled unless
the operator passes `--enrich`. Trust policy, a supplied context file, and a
detected deploy stage must also permit the call.

## Connector contract

`collect_deployment_bundle()` returns a `ConnectorBundle` containing:

- `evidence`: sanitized `ConnectorEvidence` observations with connector,
  operation, resource, namespace, exact argument vector, observation time,
  return code, truncation state, and redaction count.
- `audits`: credential-free `ConnectorAudit` records for every attempt,
  including unavailable executables, timeouts, command failures, and denials.

The existing `collect_deployment_evidence()` function remains a compatibility
adapter returning rendered strings. It carries the structured audit records to
the pipeline, which persists them as `context.connector_audits`.

## Kubernetes allowlist

Generated commands are limited to:

- `kubectl get` for one workload plus label-scoped ReplicaSets and active pods
- `kubectl describe` for one workload
- `kubectl get events` scoped to the workload name
- `kubectl rollout history`
- `kubectl logs` for the workload with `--previous`, `--tail=200`, and `--since=30m`

Supported workload kinds are `deployment`, `statefulset`, and `daemonset`.
Resource, service, release, and namespace values must be bounded ASCII
identifiers. Collection never uses all namespaces.

## Helm allowlist

Generated commands are limited to:

- `helm status <release> -o json`
- `helm history <release> -o json --max 20`

`install`, `upgrade`, and `rollback` are not constructible.

## Explicit denials

Mutation tokens include `apply`, `create`, `delete`, `edit`, `exec`, `install`,
`patch`, `replace`, `restart`, `rollback`, `scale`, `set`, and `upgrade`.
Commands are invoked with `shell=False`; no command string is passed to a shell.

## Bounds and failure behavior

- Per-operation timeout: 10 seconds
- Maximum operations: 8
- Maximum evidence per operation: 32 KiB
- Maximum aggregate evidence: 128 KiB
- Logs: 200 lines and a 30-minute window
- Helm history: 20 revisions

Every output is redacted before it reaches analysis, persistence, reports, or an
LLM. One operation timing out or failing does not discard evidence from the
other operations and never prevents local log analysis.
