# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting a Vulnerability

We take the security of Hound Agent seriously. If you discover a security vulnerability, please follow responsible disclosure guidelines.

- **Do NOT open a public GitHub issue** for suspected security vulnerabilities or credential leaks.
- Please report vulnerabilities privately via [GitHub Security Advisories](https://github.com/youthisss/hound-agent/security/advisories/new) or by emailing the maintainer.
- Include detailed reproduction steps, logs (with credentials scrubbed), and potential impact.
- You will receive an acknowledgment within 48 hours.

## Privacy and Secret Redaction

Hound Agent is designed with privacy-first principles:
1. **Redaction by Default**: All logs, stacktraces, and test artifacts pass through pattern-based scrubbing before any analysis or storage.
2. **Read-Only**: Hound Agent does not mutate infrastructure, deploy code, or execute arbitrary remote actions.
3. **Offline Mode**: Operates 100% locally with `--offline` without sending telemetry, logs, or metrics to external services.

Dependency updates follow [`docs/operations/dependency-policy.md`](docs/operations/dependency-policy.md),
including lockfile regeneration, release-note review, tests, and `pip-audit`.
