---
name: inboundcheck-security-gates
description: Risk-based security verification matrix for InboundCheck (auth/JWT, tenant isolation, Supabase RLS and migrations, Stripe/Shopify webhooks, billing entitlements, abuse protection, workers). Use when classifying task risk, choosing security gates and reviewers, or deciding whether a security question must stop the run.
---

# Security Gates

Before selecting work or gates, read the project policy at
`.agent/references/engineering-os.md`. Use one builder, retain existing security
review requirements, and never bypass hooks or manufacture approval/evidence.
Runtime registry requirements still govern mechanical DONE; report blockers accurately.

Read `.agent/skills/fastapi-cloud-security/SKILL.md` (the tracked project contract) and `.agent/skills/security-and-hardening/SKILL.md` for method. Gate ids and exact commands live in `.claude/orchestration/gates.json`; this file says WHEN each applies and what review must check beyond tests.

| Area | Trigger | Automated gate | Reviewer must verify (by reading code/tests) | Limits |
|---|---|---|---|---|
| Authentication / authorization | `core/security.py`, any route dependency, tenant scoping | `G-AUTH-JWT` | signature, `exp`, `aud`/issuer handling, identity only from the verified JWT (never client `user_id`), no fail-open branch, no privilege escalation path | no live Supabase JWKS test |
| Tenant isolation / RLS | any query, `supabase/**`, `supabase_client.py` | `G-MIGRATION-STATIC`, `G-AUTH-JWT` | every query filtered by verified user id, every table RLS-enabled with `auth.uid() = user_id`, no `USING (true)`, no `anon`/`PUBLIC` grants, service role not used on user paths | **No live-Postgres harness on main:** cross-tenant RLS behavior is reviewed statically only; say so in the report |
| Migrations | `supabase/migrations/**` | `G-MIGRATION-STATIC`, `G-SCAN` | expand/contract, rollback or compensating plan, locks/transactions, no destructive DDL, ledger naming | never applied by the team |
| Billing / entitlements | `billing*`, `tier_guards`, plan/quota code | `G-BILLING` | server-side plan checks, no client-trusted entitlement, no free/enterprise bypass, idempotent state changes | Stripe/Shopify not contacted |
| Webhooks | `failover_webhooks`, billing webhooks, Shopify lifecycle | `G-WEBHOOKS` | HMAC over the raw body with constant-time compare, timestamp/replay window, event-id idempotency, fail-closed on missing secret, safe logging | |
| API / abuse | routes, `rate_limiter`, fetchers, `main.py` | `G-ABUSE` | body size limits, Pydantic validation, rate limits, trusted-proxy IP handling, SSRF guard (`_clean_domain` + restricted subnets), outbound timeouts, generic errors | |
| Background workers | `workers/**`, outbox, leases | `G-WORKER` | lease ownership/expiry, retry cap, idempotency, duplicate claim, graceful shutdown, dead-letter, no unbounded loops | no real broker/DB |
| Secrets / logging | every task | `G-SCAN` | no secrets, tokens, PII or env values in code, tests, logs, reports | scan is pattern-based |

## Risk classification
HIGH if any file matches `security_boundaries` (automatic in `add-task` and `done`), or the change alters auth, RLS, billing enforcement, webhook verification, rate limiting, encryption or lease semantics. MEDIUM: other `backend/app` logic. LOW: tests-only, docs, comments with no behavior change.

## Review protocol for HIGH
1. `security-auditor` (read-only) on the exact diff and trust boundaries (STRIDE per boundary).
2. The orchestrator independently re-derives each Critical/High finding from source before accepting or dismissing it, and records the reasoning in `notes/`.
3. `test-engineer` confirms new behavior has a test that fails without the change.
4. Fixes go back through the same loop (max 2 correction cycles).

## STOP and ask the user (never decide autonomously)
Changing how identity/tokens are validated; adding or relaxing any authorization rule, RLS policy, entitlement or rate limit; touching webhook secrets/verification semantics; adding an external integration, CORS origin or file upload; any finding the reviewers disagree on; anything requiring a real credential or a live service.
