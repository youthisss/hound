---
command: "/hound:run"
description: "Execute a command under Hound's secret-scrubbing collector, auto-analyzing failures."
usage: "/hound:run <command...>"
---

# Hound Run Command

When the user runs `/hound:run <command...>`:

1. Wrap and run the command with Hound collector:
   ```bash
   hound log --analyze --offline -- <command...>
   ```
   Or invoke the MCP tool `hound_log_command(command=["..."])`.
2. If the command exits with `0`, report success.
3. If the command exits with a non-zero status code:
   - Read the generated `report.json`.
   - Present the primary error event, failing assertions, and recommended fix.
