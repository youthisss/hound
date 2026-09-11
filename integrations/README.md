# Harness Integration

Hound Tracer uses two portable surfaces:

- `skills/hound-tracer/SKILL.md` for agent instructions.
- `python -m hound.mcp` for MCP tools.

The files in this directory are configuration examples, not interchangeable plugin manifests. Copy or merge only the example for the harness you use. Keep existing settings when merging.

## Support matrix

| Harness | Skill | MCP | Hound commands |
|---|---|---|---|
| OpenCode V2 | Native | Native | Configured prompt commands |
| Claude Code | Native | Native | Plugin command files |
| Hermes Agent | Native | Native | Skill slash command |
| Codex | Agent Skills compatible | Native | Invoke skill by name |
| Cursor | Agent Skills compatible where enabled | Native | Invoke skill by name |
| Antigravity | Install skill using its current skill directory | MCP config varies by release | Invoke skill by name |

## Security defaults

All examples restrict Hound to the current workspace with `HOUND_MCP_ROOTS=.`. They do not enable `hound_log_command`. Add `HOUND_MCP_ENABLE_COMMAND_EXECUTION=1` only when the harness permission policy asks before running MCP tools.

## Updating

- Git checkout: update the repository normally. Harnesses that reference `./skills` see the new skill immediately or after reload.
- Hermes registry or URL install: run `/skills update` or `hermes skills update`.
- Published Python package: use the same package manager that installed Hound. Review the target version before upgrading.
- Do not let an agent replace harness configuration or update packages without user confirmation.
