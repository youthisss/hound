---
command: "/hound:gate"
description: "Evaluate test results, code coverage, and SARIF against the repository quality gate policy."
usage: "/hound:gate [test-results.xml]"
---

# Hound Gate Command

When the user runs `/hound:gate [test-results.xml]`:

1. Locate the test results (defaulting to any JUnit XML in `target/`, `build/`, or test output directories).
2. Check if a gate policy exists at `.hound/gate-policy.yml` or run:
   ```bash
   hound gate "<test-results.xml>" --repo-dir . --baseline-ref origin/main --candidate-ref HEAD
   ```
   Or invoke the MCP tool `hound_check_gate(source_path="<test-results.xml>")`.
3. Report whether the quality gate passed, warned, or blocked, including coverage deltas or introduced defects.
