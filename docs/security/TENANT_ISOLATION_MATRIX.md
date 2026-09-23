# INBOUNDCHECK — TENANT ISOLATION MATRIX

**Audit Date:** 2026-09-23  
**Auditor:** Principal Security & Cloud Architecture Specialist  
**Governing Standard:** Multi-Tenant Isolation & Zero Trust Data Scoping  
**Core Technology:** FastAPI 0.111+, Supabase PostgreSQL 15, PostgREST with Service-Role Key

---

## 1. Executive Summary

Because the backend communicates with Supabase PostgREST via `SUPABASE_SERVICE_ROLE_KEY`, PostgreSQL Row-Level Security (RLS) is **bypassed on all database queries executed by FastAPI**. All tenant isolation relies 100% on:
1. Validating user identity cryptographically from the Supabase JWT (`get_current_user_id` / `verify_active_subscription_or_trial`).
2. Explicitly scoping every database query with `.eq("user_id", user_id)` (or `.eq("id", user_id)` for `profiles`).
3. Verifying that sub-resources (`domain_id`, `store_id`, `fix_id`) belong to the authenticated user before executing mutations or reading granular records.

This matrix audits every authenticated endpoint interacting with user-owned resources to identify potential cross-tenant leakage or authorization bypass vectors.

---

## 2. Complete Tenant Isolation Matrix

| Endpoint | Method | Resource | Owner Field | User Identity Source | Ownership Check | Database Query | Service Role Used? | Potential Cross-Tenant Path | Current Status |
|---|:---:|---|---|---|---|---|:---:|---|:---:|
| `/api/v1/domains` | GET | `monitored_domains` | `user_id` | JWT `sub` | Verified by dependency | `.eq("user_id", user_id)` | YES | None | **SAFE** |
| `/api/v1/domains` | POST | `monitored_domains` | `user_id` | JWT `sub` (via tier guard) | Injects validated `user_id` | `.upsert(record)` with `user_id` | YES | None | **SAFE** |
| `/api/v1/domains/{domain_id}/audit` | POST | `dns_audit_logs`, `monitored_domains` | `user_id` | JWT `sub` | Injects validated `user_id` | Saves log with `domain_id` and `user_id` | YES | Merchant could submit arbitrary `domain_id` owned by another tenant; audit log would attach to victim domain | **RISK (SEC-T1)** |
| `/api/v1/domains/{domain_id}` | DELETE | `monitored_domains` | `user_id` | JWT `sub` | Verified by dependency | `.eq("id", domain_id).eq("user_id", user_id)` | YES | None (scoped to both keys) | **SAFE** |
| `/api/v1/dns/audit` | POST | In-memory / DNS | `user_id` | JWT `sub` | None (on-demand query) | None (stateless DNS scan + degradation alert) | NO | None | **SAFE** |
| `/api/v1/dns/rbl-scan` | POST | `rbl_scans` / cache | `user_id` | JWT `sub` | Scoped on save | `persist_rbl_scan(user_id=...)` | YES | None | **SAFE** |
| `/api/v1/dns/rbl-status` | GET | `rbl_scans` | `user_id` | JWT `sub` | Scoped query | `get_latest_rbl_scan(user_id=..., domain=...)` | YES | None | **SAFE** |
| `/api/v1/dns/spf-merge-plan` | POST | `spf_merge_plans` | `user_id` | JWT `sub` (via tier guard) | Matches domain in user's list | Scoped to `user_id` | YES | None | **SAFE** |
| `/api/v1/dns/verify-remote-asset` | POST | `remote_asset_audits` | `user_id` | JWT `sub` | Injects validated `user_id` | Saves audit with `user_id` | YES | None | **SAFE** |
| `/api/v1/dns/auto-fix/credentials` | GET | `dns_provider_credentials` | `user_id` | JWT `sub` | Queries by `user_id` | In-memory / DB scoped to `user_id` | NO (Mock) | None | **SAFE** |
| `/api/v1/dns/auto-fix/credentials` | POST | `dns_provider_credentials` | `user_id` | JWT `sub` | Saves with `user_id` | In-memory / DB scoped to `user_id` | NO (Mock) | None | **SAFE** |
| `/api/v1/dns/auto-fix/apply` | POST | `dns_auto_fix_logs` | `user_id` | JWT `sub` (via tier guard) | Scoped to `user_id` | Appends fix log to `user_id` list | NO (Mock) | Uses server env token for Cloudflare instead of tenant credential | **SAFE Tenancy / RISK Config** |
| `/api/v1/dns/auto-fix/rollback` | POST | `dns_auto_fix_logs` | `user_id` | JWT `sub` (via tier guard) | Scoped to `user_id` | Filters `user_logs` by `fix_id` | NO (Mock) | None | **SAFE** |
| `/api/v1/dns/auto-fix/logs` | GET | `dns_auto_fix_logs` | `user_id` | JWT `sub` | Scoped to `user_id` | `_mock_auto_fix_logs.get(user_id, _mock_auto_fix_logs["demo-user-123"])` | NO (Mock) | Fallback leaks `demo-user-123` fix logs to new tenants | **RISK (SEC-T2)** |
| `/api/v1/shopify/stores` | GET | `shopify_stores` | `user_id` | JWT `sub` | Scoped query | `.eq("user_id", user_id)` | YES | None | **SAFE** |
| `/api/v1/shopify/store-settings` | POST | `shopify_stores` | `user_id` | JWT `sub` | Scoped update | Updates store matching `user_id` | YES | None | **SAFE** |
| `/api/v1/shopify/billing/callback` | GET | `profiles` | `id` | Query param `user_id` | None | `update_user_profile(resolved_user_id, ...)` | YES | If `shop` not provided, an unauthenticated user could update victim `user_id` profile tier | **RISK (SEC-T3)** |
| `/api/v1/shopify/deliverability-readiness` | POST | `shopify_readiness` | `user_id` | JWT `sub` | Scoped to `user_id` | Queries domains for `user_id` | YES | None | **SAFE** |
| `/api/v1/settings/profile` | GET | `profiles` | `id` (UUID) | JWT `sub` | Scoped query | `.eq("id", user_id)` | YES | None | **SAFE** |
| `/api/v1/settings/profile` | PUT | `profiles` | `id` (UUID) | JWT `sub` | Scoped update | `.eq("id", user_id)` | YES | None | **SAFE** |
| `/api/v1/settings/api-key/regenerate` | POST | `profiles` | `id` (UUID) | JWT `sub` | Scoped update | `.eq("id", user_id)` | YES | None | **SAFE** |
| `/api/v1/settings/alerts` | GET | `alert_configs` | `user_id` | JWT `sub` | Scoped query | `.eq("user_id", user_id)` | YES | None | **SAFE** |
| `/api/v1/settings/alerts` | POST | `alert_configs` | `user_id` | JWT `sub` | Scoped upsert | `.upsert(data, on_conflict="user_id")` | YES | None | **SAFE** |
| `/api/v1/settings/telegram/test` | POST | External Telegram | `user_id` | JWT `sub` | Dispatches for user | Dispatches message to user-supplied chat | NO | None | **SAFE** |
| `/api/v1/failover/config` | GET | `failover_configs` | `user_id` | JWT `sub` | Scoped query | Queries `user_id` | NO | None | **SAFE** |
| `/api/v1/failover/config` | POST | `failover_configs` | `user_id` | JWT `sub` | Scoped update | Upserts `user_id` | NO | None | **SAFE** |
| `/api/v1/failover/dispatch` | POST | `failover_logs` | `user_id` | JWT `sub` | Scoped insert | Saves log with `user_id` | YES | None | **SAFE** |
| `/api/v1/failover/logs` | GET | `failover_logs` | `user_id` | JWT `sub` | Scoped query | Queries `user_id` | YES | None | **SAFE** |
| `/api/v1/billing/subscription` | GET | `profiles` | `id` (UUID) | JWT `sub` | Scoped query | `.eq("id", user_id)` | YES | None | **SAFE** |
| `/api/v1/billing/create-checkout-session` | POST | Stripe Checkout | `user_id` | JWT `sub` | Scoped lookup | Queries stores for `user_id` | YES | None | **SAFE** |
| `/api/v1/analytics/protected-revenue` | GET / POST | Analytics Engine | `user_id` | JWT `sub` | Scoped calculation | Computes from user domain count | NO | None | **SAFE** |
| `/api/v1/analytics/reputation-trend` | GET | `reputation_checks` | `user_id` | JWT `sub` | Scoped query | `.eq("user_id", user_id)` | YES | None | **SAFE** |
| `/api/v1/analytics/reputation-events`| GET | `reputation_checks` | `user_id` | JWT `sub` | Scoped query | Queries `user_id` | YES | None | **SAFE** |
| `/api/v1/analytics/revenue-at-risk` | GET / POST | `revenue_risk_records` | `user_id` | JWT `sub` | Scoped insert/query | Scoped to `user_id` | YES | None | **SAFE** |
| `/api/v1/ai/audit-template` | POST | Content Optimizer | `user_id` | JWT `sub` | Stateless NLP audit | None | NO | None | **SAFE** |
| `/api/v1/ai/generate-variants` | POST | Content Optimizer | `user_id` | JWT `sub` | Stateless copy generation | None | NO | None | **SAFE** |

---

## 3. Specific Cross-Tenant Risks Identified for Remediation

### Risk 1 (`SEC-T1`): Domain Ownership Validation in `re_audit_domain` (`domains.py:126`)
* **Vulnerability:** Endpoint accepts arbitrary `domain_id` in path. If User A triggers `POST /api/v1/domains/{domain_id_of_user_b}/audit?domain_name=user_b_domain.com`, the backend creates/updates the domain for User A, but persists the audit log with User B's `domain_id`.
* **Fix Required:** Validate server-side that `domain_id` belongs to `user_id` before auditing. If not owned by `user_id`, return `HTTP 404 Not Found`.

### Risk 2 (`SEC-T2`): Auto-Fix Logs Default Fallback Leaks Demo Logs (`auto_fixer.py:206`)
* **Vulnerability:** `get_logs()` executes:
  ```python
  return _mock_auto_fix_logs.get(user_id, _mock_auto_fix_logs["demo-user-123"])
  ```
  Any newly authenticated user without previous logs is returned the private DNS fix logs of `demo-user-123`.
* **Fix Required:** Return empty list `_mock_auto_fix_logs.get(user_id, [])`.

### Risk 3 (`SEC-T3`): Shopify Billing Callback Unvalidated `user_id` (`shopify.py:208-255`)
* **Vulnerability:** `/api/v1/shopify/billing/callback` accepts `user_id` as an untrusted query parameter without HMAC signature or JWT authentication. If `shop` is missing or spoofed, it calls `update_user_profile(user_id, ...)` modifying another user's profile.
* **Fix Required:** Verify that `clean_shop` exists, verify that the shop belongs to the `resolved_user_id` in `shopify_stores`, and require Shopify verification before activating any subscription. If shop or store ownership check fails, reject immediately with HTTP 400/403.
