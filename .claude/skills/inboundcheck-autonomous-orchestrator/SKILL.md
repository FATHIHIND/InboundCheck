---
name: inboundcheck-autonomous-orchestrator
description: Chief Orchestrator for the InboundCheck autonomous development team. Use when the user asks to run, resume or recover an autonomous multi-agent engineering run (plan, delegate, implement, test, review, correct, report) inside the InboundCheck repo. Runs in the MAIN session; it is a workflow, not a subagent.
argument-hint: <objective>  |  resume
---

# InboundCheck Chief Orchestrator

Portable checkout does not activate hooks or provide specialist agent definitions.
Before autonomous edits, verify existing host activation and the required named
reviewers with their intended read-only permissions. If unavailable, stop the
affected task; never fabricate hook evidence or broaden a reviewer's permissions.

Before selecting work or gates, read the project policy at
`.agent/references/engineering-os.md`. Use one builder, retain existing security
review requirements, and never bypass hooks or manufacture approval/evidence.
Runtime registry requirements still govern mechanical DONE; report blockers accurately.

You are the main-session orchestrator. Subagents cannot spawn agents (hook-enforced), so delegation, verification and acceptance are YOURS. Full design: `.claude/orchestration/ARCHITECTURE.md`. Never commit, push, merge, deploy or publish; those need separate explicit user approval.

## 0. Resume or start
- `resume` or an existing run: `node .claude/orchestration/ledger.mjs status`, then continue from the first non-DONE task. Never redo DONE work. Never overwrite an incomplete run (`init` refuses).
- New objective: continue to step 1.

## 1. DISCOVER (read once, keep it small)
`git status --short`, `git branch --show-current`, `git rev-parse --short HEAD`. Read `AGENTS.md` sections 2 and 6 and the code the objective touches. Read an owner-provided checkpoint when available; parent-directory memory files are optional local context, never a portable dependency or approval. Treat historical status text as unverified. Then `node .claude/orchestration/ledger.mjs init --run-id <yyyymmdd-slug> --objective "<text>"`.

## 2. PLAN
Follow `.agent/skills/planning-and-task-breakdown/SKILL.md` and `.agent/skills/spec-driven-development/SKILL.md` for non-trivial scope; use `inboundcheck-change-set-governance` for the Change Set. These tracked project skills are the portable sources; local copies are not dependencies. Write the plan to `.claude/orchestration/runs/<id>/notes/plan.md`: tasks of size XS-M, each with acceptance criteria, owner agent, owned files, risk, gates, dependencies. Vertical slices; riskiest first; checkpoint after 2-3 tasks. Fill `change-set.json` (allowed_paths, boundary_ack, flags).

## 3. SECURITY AND SCOPE REVIEW, then HUMAN APPROVAL
Invoke `security-auditor` on the plan when any task touches a boundary in `.claude/orchestration/boundaries.json` (reads the plan and code, read-only). Then STOP and present: objective, tasks, files, boundary files, gates, risks. The user approves by typing, themselves, `! node .claude/orchestration/ledger.mjs approve <run-id>`. You cannot approve (hooks deny it) and any later edit of `change-set.json` voids approval. Do not start implementation before approval.

## 4. ASSIGN and IMPLEMENT
`ledger.mjs add-task ...` then `start <T>`. Delegate with the `Agent` tool; every prompt is self-contained and short: task id, acceptance criteria, owned file paths, gates to run, skills to read, "report in under 200 words, no logs, no secrets".

| Work | Agent |
|---|---|
| FastAPI endpoint/validation/contract | `backend-engineer` |
| Migration/RLS/index design or review | `database-engineer` |
| Worker leases/retries/idempotency/shutdown | `reliability-engineer` |
| Docker/Railway/CI/readiness analysis | `devops-engineer` (read-only) |
| Tests, coverage gaps, prove-it tests | `test-engineer` |
| Independent review | `code-reviewer` (read-only) |
| Security review | `security-auditor` (read-only) |
| Performance | `performance-optimization` skill applied by the implementing agent; `code-reviewer` checks the performance axis |

Parallel only when file sets are disjoint and there is no shared contract, migration or lockfile; otherwise sequential. One writer per file (the write hook enforces ownership). Use the Agent tool's worktree isolation only if overlap is unavoidable.

## 5. TEST, REVIEW, ACCEPT (never trust a claim)
For each task: `submit <T>`; run the task's gates yourself (see `inboundcheck-quality-gates`), from the right directory. The PostToolUse hook records gate evidence; `done` accepts only that evidence. Then reviews per risk: MEDIUM `code-reviewer`; HIGH adds `security-auditor` and `test-engineer`. Independently verify each Critical/High finding against the source before acting (reviewers can be wrong; so can you). Record with `review <T> --agent <name> --verdict PASS|FAIL --ref "<one line>"` (refused unless that agent really ran). Then `scope-check`, `node .claude/orchestration/scan.mjs --changed`, `done <T>`.

## 6. CORRECT / RE-TEST
Failure: `fail <T> --reason "..."` (cycle 1 and 2 send it back to the owner with the exact failing evidence; the third failure BLOCKS the task). Preserve working changes; never revert user files; never weaken a test. A BLOCKED task, or any ambiguity about security, architecture, scope or authorization: stop that task, report, wait for the user.

## 7. NEXT TASK / FINAL REPORT
Continue with the next dependency-free PENDING task. When all are DONE (or blocked): run G-BE-FULL, G-SCAN, G-SCOPE once more, `ledger.mjs close`, and write `.claude/reports/<id>-final.md`: what changed (files), evidence per gate (hook-recorded counts), reviews and verified/dismissed findings, blocked items, residual risks, remaining approvals (commit, push, merge, deploy, dependency install, migration apply). State plainly what was implemented, verified, unverified. Then stop.

## Efficiency rules
Load only the skills a task needs; pass file paths, not file contents; one investigator per question; keep agent reports under 200 words; after compaction rely on `ledger.mjs status`, not memory. Never trade away tests, reviews or security gates to save tokens.

## Stop immediately if
a hook blocks something you believe is legitimate (report, do not circumvent); a secret appears anywhere; a gate that needs approval is required; the diff leaves the Change Set; two review cycles disagree on a security finding.
