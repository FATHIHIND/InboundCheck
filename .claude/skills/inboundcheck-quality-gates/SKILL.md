---
name: inboundcheck-quality-gates
description: Exact quality-gate commands, pass criteria and failure handling for InboundCheck (backend pytest groups, frontend, scan, scope, reviews), and how hook-recorded evidence satisfies task completion. Use when running or interpreting gates for an autonomous task.
---

# Quality Gates

Before selecting work or gates, read the project policy at
`.agent/references/engineering-os.md`. Use one builder, retain existing security
review requirements, and never bypass hooks or manufacture approval/evidence.
Runtime registry requirements still govern mechanical DONE; report blockers accurately.

Source of truth: `.claude/orchestration/gates.json` (each gate has trigger, command, pass, on_fail, status). Evidence for DONE comes from the PostToolUse hook, so run the real command in the real directory; a paraphrase or a manual note does not count.

## How to run (verified against this repo)
- Backend: `cd backend && py -m pytest <paths> -q` (`pytest.ini`: `testpaths = tests`, `asyncio_mode = auto`). The `cd backend` is required (the hook downgrades a pytest run outside `backend/` to UNKNOWN). Local Python is 3.14, Docker image is 3.11: a local pass does not prove 3.11.
- Frontend unit: `cd frontend && node --loader ./tests/loader.mjs --test tests/*.test.ts` (from AGENTS.md section 6; run result recorded in the final report).
- Scan: `node .claude/orchestration/scan.mjs --changed`. Scope: `node .claude/orchestration/ledger.mjs scope-check`.

## Gate selection
Always: `G-SCOPE`, `G-SCAN`; LOW adds `G-BE-COLLECT`; MEDIUM/HIGH add `G-BE-FULL`. Add area gates from the `inboundcheck-security-gates` table (`G-AUTH-JWT`, `G-WEBHOOKS`, `G-BILLING`, `G-ABUSE`, `G-WORKER`, `G-MIGRATION-STATIC`). Frontend changes add `G-FE-UNIT`.

## Needs user approval (never autonomous)
`G-FE-TYPES`, `G-FE-LINT`, `G-FE-BUILD` (need `node_modules`; installing dependencies is an approval step), `G-DOCKER` (starts containers). `G-BE-LINT` is NOT CONFIGURED: no ruff/mypy exists; do not invent one. If a task needs a blocked gate, the task cannot reach DONE autonomously: report it as awaiting approval.

## Pass / fail behavior
- Pass criteria are per gate. Exit 0 with failed or error counts is a FAIL. No tests collected is not a pass.
- Fail: `ledger.mjs fail <T> --reason ...` with the failing test names (not full logs). Fix the code, never the assertion, never skip/xfail. Max 2 correction cycles, then BLOCKED.
- Flaky or environment failure (import error from missing local package, network): classify as ENV, re-run once, then report as an environment blocker rather than "fixing" tests.
- Never run workers, servers, `docker compose up`, or anything touching real Supabase/Stripe/Shopify/Railway. There is no `.env` in this checkout and none may be created or read.

## Definition of done
Acceptance criteria met + `.claude/references/definition-of-done.md` + gates (hook-recorded PASS after the last edit) + required reviews (hook-confirmed agent runs after the last edit) + clean scope-check and scan. `ledger.mjs done <T>` verifies all of this mechanically and refuses otherwise.
