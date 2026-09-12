---
command: "/hound:incidents"
description: "List deduplicated Hound incidents and recurrence counts."
usage: "/hound:incidents [limit]"
---

# Hound Incidents Command

When the user runs `/hound:incidents [limit]`:

1. Use `hound_list_incidents(limit=<limit>)` when MCP tools are available.
2. Otherwise, use the matching Hound CLI incident-listing command if supported by the installed version.
3. Report fingerprints, recurrence counts, severity, and the cached RCA summary.
4. Do not expose raw incident payloads or unredacted logs.
