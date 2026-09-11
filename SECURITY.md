# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting a Vulnerability

We take the security of Hound Tracer seriously. If you discover a security vulnerability, please follow responsible disclosure guidelines.

- **Do NOT open a public GitHub issue** for suspected security vulnerabilities or credential leaks.
- Please report vulnerabilities privately via [GitHub Security Advisories](https://github.com/youthisss/hound-tracer/security/advisories/new) or by emailing the maintainer.
- Include detailed reproduction steps, logs (with credentials scrubbed), and potential impact.
- You will receive an acknowledgment within 48 hours.

## Privacy and Secret Redaction

Hound Tracer is designed with privacy-first principles:
1. **Redaction by Default**: Supported credential and PII patterns are scrubbed from collected artifacts before LLM requests and from generated results before report or dedup-state persistence. Coverage includes IPv4 and IPv6 addresses. This is pattern-based filtering, not a guarantee that arbitrary, encoded, split, or application-specific secrets are detected. Original input files are not rewritten; `--allow-unredacted` explicitly disables this protection outside restricted trust profiles.
2. **Advisory Analysis**: The analysis pipeline does not deploy, retry, or roll back infrastructure. `hound log` executes the operator-supplied command, and opt-in delivery integrations publish tickets or alerts; those actions have their own side effects.
3. **Offline Mode**: Operates 100% locally with `--offline` without sending telemetry, logs, or metrics to external services.

Dependency updates follow [`docs/operations/dependency-policy.md`](docs/operations/dependency-policy.md),
including lockfile regeneration, release-note review, tests, and `pip-audit`.
