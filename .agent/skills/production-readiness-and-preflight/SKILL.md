---
name: production-readiness-and-preflight
description: Executes comprehensive pre-flight build verification, backend pytest suites, frontend TypeScript compilation, Docker health checks, and security audits before shipping or handoff. Use before merging code, deploying to staging/production, or closing any development task.
---

# Production Readiness, Pre-Flight Builds, and Deployment Verification

## Overview

InboundCheck is mission-critical infrastructure for enterprise Shopify merchants. A production regression, broken TypeScript build, silent test failure, or unhandled exception during payment/DNS operations can result in financial loss, domain downtime, or security incidents.

This skill establishes an uncompromising **4-Tier Pre-Flight Verification Gate**. No feature or bug fix may be marked complete or handed off to production without passing all four gates.

---

## When to Use

- Prior to opening or merging any pull request
- Before deploying updates to Vercel, Railway, Render, or Docker hosts
- After making changes across frontend (`frontend/`), backend (`backend/`), or database migrations (`supabase/`)
- During release readiness audits and final QA cycles

---

## The 4-Tier Pre-Flight Verification System

```
[ Gate 1: Frontend Build & Typecheck ]
              ↓ PASS
[ Gate 2: Backend Pytest Test Suite ]
              ↓ PASS
[ Gate 3: Security, Secrets & SSRF Audit ]
              ↓ PASS
[ Gate 4: Docker & Multi-Container Health ]
              ↓ PASS
       🚀 READY TO SHIP
```

---

### Tier 1: Frontend Build & Strict TypeScript Compilation

Every page, component, and server action must compile with zero errors and zero unused variable warnings under Next.js App Router strict mode.

**Execution Command:**
```bash
# MUST be executed inside frontend/ directory
cd "frontend"
npm run build
```

**Passing Criteria:**
- Exit code `0`.
- All static and dynamic routes compile successfully (e.g. `/`, `/dashboard`, `/dashboard/inspector`, `/dashboard/radar`, `/dashboard/shopify`, `/dashboard/content-lab`, `/dashboard/settings`, `/auth/login`, `/auth/signup`).
- 0 TypeScript compilation errors.
- 0 Next.js Webpack module resolution errors.

---

### Tier 2: Backend Integration & Unit Test Suite

The FastAPI backend contains automated test suites covering DNS resolution, SSRF guardrails, BOLA/IDOR protection, Stripe billing, and Shopify OAuth.

**Execution Command:**
```bash
# MUST be executed inside backend/ directory
cd "backend"
py -m pytest tests/ -v
```

**Passing Criteria:**
- Exit code `0`.
- **100% of tests passing** across:
  - `test_dns_diagnostic.py` (Multi-resolver, SPF/DKIM/DMARC/BIMI parsing)
  - `test_domains_api.py` (Tenant domain registration, CRUD, RLS isolation)
  - `test_shopify_and_settings.py` (Shopify HMAC signature verification, tenant settings)
  - `test_billing_and_security.py` (JWT auth dependency, SSRF blocked ranges, Stripe webhooks)
  - `test_v3_roadmap.py` (Bloc A content lab, Bloc B failover, Bloc C auto-fix, Bloc D analytics)

---

### Tier 3: Security, Secrets & Configuration Audit

Verify that no sensitive secrets or keys are hardcoded in the codebase, and all runtime variables are strictly configured.

**Audit Checklist:**
- [ ] **No Hardcoded Secrets:** Run ripgrep to ensure no real API keys, Supabase service keys, or Stripe secrets exist in tracked source code:
  ```bash
  # Check for accidental secret leakage
  git grep -i "sk_live_"
  git grep -i "whsec_"
  git grep -i "SUPABASE_SERVICE_KEY"
  ```
- [ ] **Fernet Encryption Key:** Verify `ENCRYPTION_KEY` is present and at least 32 bytes URL-safe base64.
- [ ] **JWT Bearer Enforcement:** Verify all router endpoints in `backend/app/api/v1/` require `Depends(get_current_user_id)` unless explicitly designed as public webhooks or health checks.
- [ ] **SSRF Guardrail Active:** Verify `RESTRICTED_SSRF_NETWORKS` blocks all private RFC 1918 subnets, loopback `127.0.0.1`, and AWS metadata `169.254.169.254`.
- [ ] **CORS Origins Restricted:** Verify `ALLOW_ORIGINS` does not use wildcard `*` in production mode.
- [ ] **RLS Policies Enabled:** Every table in `supabase/migrations/` has `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` and explicit `WITH CHECK (auth.uid() = user_id)`.

---

### Tier 4: Multi-Container Docker & Runtime Health Checks

Verify that the multi-container Docker Compose setup builds and starts cleanly.

**Execution Command:**
```bash
# Executed from repository root
docker-compose up --build -d
```

**Health Verification:**
- Backend API Health: `GET http://localhost:8000/health` returns `{"status": "healthy"}`.
- Backend OpenAPI Docs: `GET http://localhost:8000/docs` responds HTTP 200.
- Frontend App: `GET http://localhost:3000/` responds HTTP 200.
- Containers: `docker-compose ps` shows both `web` and `frontend` in `Up` state.

---

## Rollback & Recovery Procedures

If a deployment failure or unexpected exception occurs post-launch:
1. **Frontend Fast Rollback:** Revert Vercel/CDN deployment to the previous immutable deployment SHA.
2. **Backend Fast Rollback:** Re-tag and deploy the previous Docker image SHA or restart with the prior Git commit.
3. **Database Migration Safety:** All migrations in `supabase/migrations/` must be additive (expand-and-contract pattern); never drop columns or alter types destructively without a two-phase rollout.
4. **DNS 1-Click Rollbacks:** If an automated DNS record change causes mail routing issues, invoke `DNSAutoFixerService.rollback_dns_snapshot()` to restore the provider's exact prior zone state.

---

## Anti-Rationalization Guardrails

The following justifications are strictly prohibited:
- ❌ *"It's just a minor copy change, so I don't need to run `npm run build`."* (Copy changes frequently break JSX syntax or unescaped quotes).
- ❌ *"The test suite takes too long, I'll test it manually."* (Pytest runs in < 5 seconds; skipping tests hides regressions).
- ❌ *"The TypeScript error is trivial, I'll add `@ts-ignore` to ship faster."* (Never suppress TypeScript errors without explicit architectural justification).

---

## Final Verification Command Reference

```bash
# 1. Verify Backend
cd "c:\Users\pc\Desktop\inboundcheck VERSION 1\backend"
py -m pytest tests/

# 2. Verify Frontend
cd "c:\Users\pc\Desktop\inboundcheck VERSION 1\frontend"
npm run build
```
