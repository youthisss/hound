# Hound Tracer Reference Sheet

## 1. Supported Artifact Types
- **Raw Logs:** `.log`, `.txt` (Pytest, Jest, Vitest, Go, Rust, Java/Maven, .NET, Docker, Kubernetes)
- **Test Reports:** `.xml` (JUnit, xUnit, Surefire, NUnit)
- **Security Reports:** `.sarif` (Trivy, CodeQL, Snyk)
- **Structured Evidence:** `.json` (Test runners, trace sidecars)

## 2. Common Failure Kinds (`failure.kind`)
| Kind | Description | Typical Remediation |
|---|---|---|
| `compilation_error` | Syntax or compiler failure | Fix syntax, types, or missing imports |
| `test_failure` | Unit/integration test assertion failed | Update test logic or implementation code |
| `import_error` | Missing module or package | Check dependencies or virtual environment |
| `timeout` | Test or process exceeded deadline | Optimize slow queries or increase timeout |
| `flaky` | Test passed on retry or has low stability | Stabilize async timing, mocks, or state isolation |
| `oom_killed` | Container terminated with exit code 137 | Increase memory limit or fix memory leaks |
| `crash_loop` | Kubernetes pod CrashLoopBackOff | Inspect pod logs and startup probes |
| `image_pull_error` | Container registry auth or missing image | Verify image tag and credentials |
| `migration_failed` | DB migration script error | Inspect SQL syntax and schema rollback |
| `dependency_resolution` | Package version conflict (pip/npm/cargo) | Update lockfile or resolve constraints |

## 3. CLI Subcommands Quick Reference
| Command | Primary Use Case |
|---|---|
| `hound analyze <path> --offline` | Investigate logs/reports without external LLM |
| `hound log -- <command>` | Run and record command output with secret scrubbing |
| `hound gate <results>` | Check quality and security policy gates |
| `hound insights stats --test <id>` | Query flakiness and historical test performance |
| `hound doctor` | Verify local installation and tooling readiness |
| `hound mcp` | Launch the JSON-RPC stdio Model Context Protocol server |
| `hound console` | Launch interactive terminal UI (TUI) |
