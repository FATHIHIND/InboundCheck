# Session Handoff

Read `AGENTS.md` first, then this file, then `agent-state/CURRENT.md`. Check `agent-state/OWNERSHIP.md` before editing.

## Resume procedure

1. Confirm repository root, branch, HEAD, dirty status, and registered worktrees.
2. Confirm the current owner still owns the intended files; Codex alone writes shared memory files.
3. Compare recorded SHAs and CI state with current GitHub state. Mark evidence stale if the code, environment, or checks changed.
4. Continue the `Next action` in `CURRENT.md`; do not repeat completed evidence without a concrete reason.
5. Record only verified outcomes and concise blockers. Link to a bounded report when necessary.

Never store secrets, credentials, customer data, access tokens, or full session/command logs here. Do not run candidate installers or modify global CLI configuration as part of memory recovery.
