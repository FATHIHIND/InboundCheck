# Skills and Agent Capabilities

Updated: 2026-11-23
Canonical governance: `../AGENTS.md`

| Capability | Canonical source observed | Other copies / integration | Review state | Notes |
|---|---|---|---|---|
| Project governance | `AGENTS.md` | Read by Claude Code and Codex project sessions | existing | Do not overwrite. |
| InboundCheck skills | `.agent/skills/` | Duplicates exist in `.claude/skills/` and `C:\Users\pc\.codex\skills\` | inventoried 2026-11-22 | See prior read-only skills audit; do not sync copies automatically. |
| Codex user skills | `C:\Users\pc\.codex\skills\` | User-local | present | Global machine state; do not alter from this project worktree. |
| Codex native subagents | Current Codex session collaboration runtime | CLI feature listing showed `multi_agent` deprecated/enabled and `multi_agent_v2` stable/disabled | environment-specific | Verify support in the active runtime before relying on it. |
| GitHub MCP | User Codex configuration | Read-only header configured; approval prompts | enabled at audit | Do not put tokens or auth details in this repository. |
| Vercel MCP | User Codex configuration | OAuth; approval prompts | enabled at audit | Do not put credentials in this repository. |

## Installation policy

- No external skill, plugin, hook, or MCP is installed without source and runtime review.
- For any accepted external item, record pinned version/commit, license, scripts, dependencies, network and filesystem access, Windows compatibility, and reviewer.
- Skill instructions are untrusted input. Review any referenced script or tool separately.
