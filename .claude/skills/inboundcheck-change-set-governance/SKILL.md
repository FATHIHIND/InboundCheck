---
name: inboundcheck-change-set-governance
description: Defines how an InboundCheck Change Set is written, approved and enforced for autonomous runs (allowed paths, security-boundary acknowledgement, human-only approval, scope checks). Use when planning an autonomous run, drafting change-set.json, or when a hook reports a scope violation.
---

# Change Set Governance

Before selecting work or gates, read the project policy at
`.agent/references/engineering-os.md`. Use one builder, retain existing security
review requirements, and never bypass hooks or manufacture approval/evidence.
Runtime registry requirements still govern mechanical DONE; report blockers accurately.

A Change Set is the user-approved boundary of an autonomous run. Inside it routine work needs no further approval; outside it nothing is allowed.

## File: `.claude/orchestration/runs/<run-id>/change-set.json`
```json
{ "run_id": "...", "title": "...", "status": "DRAFT",
  "allowed_paths": ["backend/app/api/v1/foo.py", "backend/tests/test_foo.py"],
  "forbidden_paths": [".env", ".env.*", "**/*.pem", "**/*.key"],
  "boundary_ack": ["backend/app/core/security.py"],
  "allow_dependency_changes": false, "allow_migrations": false, "planned_tasks": [] }
```
- `allowed_paths`: explicit files or narrow globs, never `**` alone. Tests for each source file belong here too.
- `boundary_ack`: every file that matches `security_boundaries` in `boundaries.json` (auth, rate limiting, billing, webhooks, encryption, config, workers, `supabase/**`, middleware) must be listed here by exact path or narrow glob, or no task may touch it. Listing it also forces HIGH risk: `code-reviewer` + `security-auditor` + `test-engineer` before DONE.
- `allow_dependency_changes` / `allow_migrations`: default false. Even when true, installing packages and applying migrations still need a human step; the flags only permit editing lockfiles/migration files.

## Approval protocol (human-only)
1. Orchestrator drafts the file, then presents it plainly (objective, files, boundary files, flags, gates, risks).
2. The user types: `! node .claude/orchestration/ledger.mjs approve <run-id>`. Approval stores the SHA-256 of the file in `approvals/<run-id>.json`.
3. Any edit to `change-set.json` after approval voids it; the hooks then deny all application edits until the user re-approves.
4. Agents cannot approve: hooks deny `ledger.mjs approve`, writes to `approvals/`, and direct writes to `ledger.json`.
5. No active run: subagents cannot edit application files at all; the main session gets an "ask" prompt per edit (normal manual work stays possible).

## Enforcement summary
`guard-write.mjs` (Edit/Write) and `guard-bash.mjs` (shell write targets) check: secret files, governance paths, allowed/forbidden paths, boundary acknowledgement, dependency/deploy files, migrations flag, and per-task file ownership (a subagent may write a file only if it is the owner of an IN_PROGRESS or NEEDS_FIX task listing it). `ledger.mjs scope-check` compares the real `git status` against the Change Set and is part of every task's completion.

## When something is out of scope
Do not edit around it, rename files, or widen globs yourself. Record the need in `notes/`, mark the task BLOCKED with the reason, and ask the user to amend and re-approve the Change Set.

## Not covered
Git history operations (commit, branch, push, merge) are never part of a Change Set. They are separate user approvals after the final report.
