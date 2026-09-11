---
command: "/hound:analyze"
description: "Diagnose a failure log, JUnit XML, or directory of artifacts using Hound Tracer."
usage: "/hound:analyze [artifact-path]"
---

# Hound Analyze Command

When the user runs `/hound:analyze [artifact-path]`:

1. If `[artifact-path]` is omitted, check the default output directory (`hound-output/`), `.hound/logs/`, or ask the user which log/report file to diagnose.
2. If MCP tools are available:
   - Call `hound_analyze(artifact_path="<path>", offline=True)`.
3. Otherwise, execute via shell:
   ```bash
   hound analyze "<path>" --offline --output-dir .hound-run
   ```
4. Read `.hound-run/report.json` and present the root cause, stacktrace locations, and proposed fix.
