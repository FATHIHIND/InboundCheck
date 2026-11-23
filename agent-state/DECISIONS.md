# Decisions

Append entries; do not rewrite earlier decisions.

## 2026-11-23 — Shared memory ownership

- Decision: Codex is the single writer for shared `agent-state/` files. Claude Code may send concise proposed checkpoint updates but must not edit these files concurrently.
- Reason: prevent concurrent edits and conflicting project checkpoints.
- Evidence: approved implementation request; startup rule appended to root `AGENTS.md` in this worktree.
- Scope: shared project memory only; this does not alter global CLI configuration.
- Owner: Codex.
- Revisit when: the project explicitly changes shared-state ownership.

## 2026-11-23 — No automatic synchronization

- Decision: keep memory as ordinary repository Markdown with no background service, database, hook, or network sync.
- Reason: keep recovery inspectable, local, and low-risk.
- Evidence: approved implementation scope.
- Scope: files under `agent-state/`.
- Owner: Codex.
- Revisit when: a documented operational requirement cannot be met by reviewed manual updates.
