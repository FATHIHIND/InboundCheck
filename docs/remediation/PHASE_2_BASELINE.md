# INBOUNDCHECK — PHASE 2 BASELINE AUDIT & STATUS

**Audit Date:** 2026-09-23  
**Auditor:** Principal Reliability & Production Infrastructure Engineer  
**Phase:** Phase 2 (Production Reliability, Resilience & Cost Control)  
**Branch:** `main`  
**Latest Git Commit:** `1cf9598f3a254105c0fc3a0cc0ee28c96c4fd4f1`  
**Commit Message:** `feat(ux): enforce institutional zero-state onboarding and purge mock data fallbacks across all dashboard routes`  

---

## 1. Baseline Git Status

```text
On branch main
Your branch is up to date with 'origin/main'.

Changes not staged for commit:
  modified:   backend/app/api/v1/domains.py
  modified:   backend/app/api/v1/shopify.py
  modified:   backend/app/core/tier_guards.py
  modified:   backend/app/main.py
  modified:   backend/app/services/dns/auto_fixer.py
  modified:   backend/app/services/supabase_client.py

Untracked files:
  backend/tests/test_p0_security_remediation.py
  docs/
  supabase/migrations/20260924000001_p0_security_hardening.sql
```

All modified files correspond strictly to Phase 1 P0 security hardening measures verified in `docs/remediation/PHASE_1_VERIFICATION.md`. No unrelated working tree modifications exist.

---

## 2. Baseline Backend Test Results

* **Command:** `py -m pytest tests/` in `backend/`
* **Execution Duration:** 84.42s
* **Total Collected:** 144 items
* **Passed:** 144 (100% green)
* **Failed:** 0
* **Skipped:** 0
* **Xfailed:** 0
* **Warnings:** 137

### Detailed Test Distribution
- `tests/test_audit_leases.py`: 6 passed
- `tests/test_billing.py`: 8 passed
- `tests/test_billing_and_security.py`: 13 passed
- `tests/test_delivery_failure_ingestion.py`: 3 passed
- `tests/test_dns_diagnostic.py`: 4 passed
- `tests/test_domains_api.py`: 1 passed
- `tests/test_failover_webhooks.py`: 9 passed
- `tests/test_failover_worker_step5.py`: 5 passed
- `tests/test_p0_security_remediation.py`: 14 passed
- `tests/test_persistence_defects.py`: 5 passed
- `tests/test_rbl_api.py`: 5 passed
- `tests/test_rbl_scanner.py`: 8 passed
- `tests/test_revenue_risk.py`: 3 passed
- `tests/test_safe_http_fetcher.py`: 5 passed
- `tests/test_scheduler_and_alerts.py`: 3 passed
- `tests/test_seed_verifier.py`: 8 passed
- `tests/test_shopify_and_settings.py`: 2 passed
- `tests/test_shopify_billing.py`: 7 passed
- `tests/test_shopify_compliance.py`: 6 passed
- `tests/test_spf_merge_engine.py`: 6 passed
- `tests/test_step6_schema_and_webhooks.py`: 4 passed
- `tests/test_v3_roadmap.py`: 5 passed
- `tests/test_workers.py`: 14 passed

### Known Warnings Analysis
1. **Datetime Deprecation (`datetime.datetime.utcnow()`):** Python 3.12+ deprecation notices in `supabase_client.py`, `alert_dispatcher.py`, `shopify_service.py`, `revenue_risk_service.py`, `auto_fixer.py`.
2. **HTTP 413 Constant Deprecation (`HTTP_413_REQUEST_ENTITY_TOO_LARGE`):** Starlette deprecation in `failover_webhooks.py:86`, replaced by `HTTP_413_CONTENT_TOO_LARGE`.
3. **Supabase PostgREST Client `verify` Deprecation:** Client library deprecation during sync client instantiation.

---

## 3. Baseline Frontend Build Results

* **Command:** `npm run build` in `frontend/`
* **Static Routes Prerendered:** 25/25 clean
* **TypeScript Compilation Errors:** 0
* **Webpack Bundle Errors:** 0
* **ESLint Notices:** 10 non-fatal warnings regarding `react-hooks/exhaustive-deps` on canvas animation refs.

---

## 4. Phase 2 Target Problem Inventory

1. **Background Job Reliability & Concurrency:**
   - Audit worker & Failover worker lease mechanics, lease expiration recovery, worker crash tolerance.
   - Elimination of duplicate execution via atomic RPCs (`claim_due_domain_audits`, `claim_received_delivery_failure_events`).
2. **Idempotency & Replay Protection:**
   - Safe rerun of DNS audits, RBL scans, webhook event processing, and billing state updates.
   - Comprehensive documentation in `docs/operations/IDEMPOTENCY.md`.
3. **Webhook Ingestion Reliability:**
   - Stripe, Shopify, and ESP delivery failure webhooks: signature verification, timestamp skew checks, replay caches, duplicate delivery tolerance.
4. **External Provider Failure & HTTP Timeouts:**
   - Bounded timeouts (Connect, Read, Write, Total) across all `httpx` calls (Stripe, Shopify, Telegram, Cloudflare, OpenAI-compatible AI, DNS multi-resolvers).
   - Exponential backoff with jitter and circuit-breaking guidelines.
5. **Rate Limiting & Cost Protection:**
   - Variable-cost operations (DNS resolution, RBL lookups, LLM token consumption, Telegram API dispatches).
   - Creation of `docs/operations/COST_CONTROL.md`.
6. **Operational Safety & Continuity:**
   - Observability without secret leakage, disaster recovery analysis (`docs/operations/DISASTER_RECOVERY.md`), alerting thresholds (`docs/operations/ALERTING.md`).
