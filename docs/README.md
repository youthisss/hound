# Hound Agent Documentation

This directory contains the product contract, operator guidance, and the
evidence records used to evolve Hound Agent without hiding release assumptions
in the root README.

## Start Here

- [Product requirements](prd.md) - scope, behavior, and release constraints.
- [Architecture](architecture.md) - pipeline stages, module boundaries, and data flow.
- [Contribution workflow](workflow.md) - development and verification gates.
- [Usage guide](guides/usage.md) - CLI, TUI, server, QA history, and integrations.

## Guides

- [Usage](guides/usage.md)
- [GitHub Action](guides/github-action.md)
- [Server deployment](guides/server-deployment.md)
- [Deployment connectors](guides/deployment-connectors.md)

## Reference

- [Log format](reference/log-format.md)
- [Source intelligence](reference/source-intelligence.md)
- [Test impact](reference/test-impact.md)
- [Timeline schema](reference/timeline-schema.md)
- [Schema migration](reference/schema-migration-v1.4-to-v2.0.md)
- [RCA JSON Schema](schema/rca-v2.0.schema.json)

## Operations

- [Dependency policy](operations/dependency-policy.md)
- [Delivery reliability](operations/delivery-reliability.md)
- [Operational correlation](operations/operational-correlation.md)
- [Operations metrics](operations/operations-metrics.md)
- [Server state recovery](operations/state-recovery.md)
- [Threat model](operations/threat-model.md)
- [Pilot readiness](operations/pilot-readiness.md)
- [Release checklist](operations/release-checklist.md)
- [Pilot evidence template](operations/pilot-evidence-template.md)

## Project Records

- [Milestone audits](audits/milestone-audits.md)
- [Implementation and product plans](plans/)
- [Nginx example](examples/nginx-hound.conf)
- [Scale benchmark](benchmarks/benchmark-2026-08-31.md)
