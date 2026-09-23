# InboundCheck Enterprise — Production Readiness Audit & Architectural Governance Report

**Document Status:** Complete & Verified Baseline  
**Governing Standard:** Multi-Tier Identity-Aware SaaS Governance & Pre-Flight Certification  
**Author Perspective:** Principal SaaS Security Architect, Staff Backend Engineer, SRE, FinOps Engineer, Product Architect, and SaaS Growth Auditor  
**Target Repository:** InboundCheck (Transactional Email Deliverability & DNS Governance for Shopify & DTC)  
**Verification Date:** September 23, 2026  
**Audit Scope:** Full Stack (Next.js 14 App Router, FastAPI 0.111+, Supabase PostgreSQL, Stripe Billing, Shopify OAuth, Background Workers, DNS/RBL Probes)  

---

## 1. Executive Summary

InboundCheck is an institutional B2B Micro-SaaS designed to eliminate silent email revenue loss for Shopify and direct-to-consumer (DTC) brands caused by strict 2024 Google/Yahoo mailbox delivery mandates, misconfigured DNS records (SPF, DKIM, DMARC, BIMI), and RBL blacklists.

This Production Readiness Audit provides an evidence-based, zero-assumption evaluation of the system following the completion of **Phase 1 (P0 Security & Data Integrity)**, **Phase 2 (Reliability, Resilience & Cost Control)**, and **Phase 2.1 (P1 Reliability Remediation)**.

### Live Environment Verification Summary
* **Backend Automated Test Suite:** **169 of 169 tests passing (100% green)** in 93.68 seconds (`tests/test_audit_leases.py`, `tests/test_phase2_1_remediation.py`, `tests/test_phase2_resilience.py`, `tests/test_p0_security_remediation.py`, `tests/test_workers.py`).
* **Frontend Compilation Gate:** **25 of 25 static/dynamic pages compiled cleanly** via Next.js 14.2.4 App Router (`npm run build`) with zero TypeScript compilation errors and zero Webpack packaging defects.
* **Database Migration Ledger:** 18 sequential SQL migrations applied cleanly without schema drift, containing strict Row Level Security (RLS) policies and `SECURITY DEFINER` functions with immutable search paths.
* **Rate Limiting & Proxy Architecture:** Distributed PostgreSQL sliding windows (`public.rate_limit_windows` and `public.consume_rate_limit`) with anti-spoofing reverse proxy IP resolution and differentiated fail-closed fallback for high-cost AI, DNS, and RBL endpoints.
* **Worker & Retry Architecture:** Audit retry storm remediation active via `next_audit_retry_at` with exponential backoff ($120\text{s} \times 2^{\min(N-1, 10)}$ up to 24h) and $+0\text{--}25\%$ jitter, serialized via `FOR UPDATE SKIP LOCKED`.

### Overall Readiness Posture
The platform displays exceptional engineering rigor in cryptographic validation, anti-SSRF defenses, distributed rate limiting, and background worker leasing. However, critical blocking items remain before full general availability (GA), specifically:
1. Symmetric JWT verification in `app/core/security.py` includes `SUPABASE_KEY` (the public anon key) in `secret_candidates`, creating a theoretical token forgery risk if anon keys are treated as HS256 HMAC secrets.
2. The 1-Click DNS Auto-Fix service (`app/services/dns/auto_fixer.py`) retains mock in-memory stores (`_mock_provider_creds` and `_mock_fix_logs`) rather than persisting encrypted credentials into `dns_provider_credentials`.
3. Shopify webhooks utilize in-memory idempotency deduplication (`self._processed_webhooks`) rather than durable database persistence (`processed_webhook_events`), leaving multi-instance deployments vulnerable to replay races during container restarts.
4. Operational alerting (`OpsAlertService`) is implemented and tested with 15-minute anti-flapping suppression, but requires external production channel webhook/bot token provisioning in the deployment environment.

---

## 2. Complete Architecture Inventory

### 2.1 Frontend Architecture
* **Framework & Engine:** Next.js 14.2.4 (React 18.3.1, TypeScript 5.4.5, Tailwind CSS 3.4.4, clsx, tailwind-merge, Lucide React 0.395.0, Framer Motion 13.1.1, Three.js 0.185.1).
* **Routing Architecture:** Next.js App Router (`src/app/`).
  * *Public Routes:* `/` (Landing & interactive audit demo), `/auth/login`, `/auth/signup`, `/auth/forgot-password`, `/auth/reset-password`, `/dpa`, `/privacy`, `/security`, `/terms`, `/login` (redirect), `/signup` (redirect).
  * *Dynamic Route Handlers:* `/auth/callback/route.ts` (OAuth code & cookie exchange).
  * *Protected Dashboard Routes:* `/dashboard` (Executive Overview & Deliverability KPIs), `/dashboard/billing` (Stripe & Shopify Hybrid Billing), `/dashboard/content-lab` (AI Content Lab), `/dashboard/inspector` (DNS Inspector), `/dashboard/radar` (10-RBL Blacklist Radar), `/dashboard/settings` (Tenant API keys, Profile & Alerts), `/dashboard/shopify` (Store Sync & Delivery Failover), `/dashboard/wizard` (Onboarding On-Ramp).
* **Edge Route Guards & Middleware:** `src/middleware.ts` delegating to `src/lib/supabase/middleware.ts`. Intercepts all paths matching `/dashboard/*`. Validates session cookies via `@supabase/ssr` (`supabase.auth.getUser()`). Non-authenticated requests immediately redirect to `/auth/login` (fail-closed).
* **API Client & State Management:** Native browser `fetch` via React Server Components and client-side hooks; session token synchronization managed via `httpOnly` SSR cookies and Bearer token forwarding. Zero external Redux/Zustand bloat; local component state managed via React hooks.
* **Design System:** Obsidian Dark Glassmorphism, custom Canvas micro-visualizations (`Hero3DCanvas`, `RadarPulseCanvas`, `Sparkline3DCanvas`, `InboxWitnessCanvas`), Lucide icons, responsive reflow.
* **SEO Implementation:** Root metadata in `src/app/layout.tsx` (title template, canonical, OpenGraph, Twitter cards, keywords); dynamic XML sitemap in `src/app/sitemap.ts`; crawl directives in `src/app/robots.ts`; comprehensive Schema.org JSON-LD microdata graph (`WebApplication`, `SoftwareApplication`, `FAQPage`) embedded in `src/app/page.tsx`.

### 2.2 Backend Architecture
* **Framework:** FastAPI 0.111.0 on Starlette, Python 3.12+ / 3.14.3, Pydantic v2 (2.8.2), `dnspython` 2.6.1, `cryptography` 42.0.8, `httpx` 0.27.0.
* **Routers (`app/api/v1/`):**
  * `dns.py`: Apex DNS diagnostics, MX, SPF, DKIM selector discovery, DMARC, BIMI SVG verification.
  * `domains.py`: Tenant domain registry (CRUD, active toggles, manual re-audits).
  * `shopify.py`: Shopify OAuth handshake, store syncing, compliance webhooks (GDPR).
  * `billing.py`: Hybrid Stripe Checkout, customer billing portal, invoice retrieval, Stripe webhook ingestion.
  * `settings.py`: User profile governance, dynamic developer API keys, alert rules.
  * `ai.py`: AI Content Lab spam density scoring and polymorphic copy generator.
  * `failover.py`: Delivery failure analytics, failover configs, manual notification dispatches.
  * `failover_webhooks.py`: Ingestion of raw delivery-failure webhooks from Postmark, SendGrid, Mailgun, Amazon SES, Klaviyo.
  * `auto_fix.py`: 1-Click DNS Auto-Remediation and snapshot rollback (Cloudflare/GoDaddy).
  * `analytics.py`: Real-time dispute reduction, protected GMV correlation ($37.3\times$).
  * `seed_testing.py`: Inbox seed mailbox placement verifier.
* **Middleware Pipeline (`app/main.py`):**
  1. `TrustedHostMiddleware`: Allowed hosts (`*.up.railway.app`, `localhost`, `127.0.0.1`, `*`).
  2. `RateLimitingMiddleware`: L1 in-memory sliding window (120 req/min) with opportunistic eviction.
  3. `CORSMiddleware`: Dynamic origin filtering, credentials enabled.
  4. Enterprise Security Headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Strict-Transport-Security`, `Content-Security-Policy`.
  5. Global Exception Handlers: `StarletteHTTPException`, `DatabaseUnavailableError` (503 Service Unavailable with UUID error reference), `Exception` (500 Internal Server Error shielded).
* **Dependencies & Auth:** `get_current_user_id` from `app.core.security` (validates Supabase JWT Bearer token); `require_growth_or_enterprise_tier` from `app.core.tier_guards`.
* **Background Workers & Scheduling:**
  * `BackgroundAuditor` (`app/services/scheduler/background_auditor.py`): Periodic domain audit engine (1-hour cycle default) utilizing PostgreSQL atomic claiming RPC (`claim_due_domain_audits`).
  * `DeliveryFailureWorker` (`app/services/failover/failure_worker.py`): Asynchronous delivery failure queue processor with batch claiming (`claim_pending_delivery_failures`).
* **Operational Services:**
  * `OpsAlertService` (`app/services/alerting/ops_alert_service.py`): Operational incident dispatcher with 15-minute anti-flapping suppression.
  * `SafeHttpFetcher` (`app/services/security/safe_http_fetcher.py`): SSRF-immune, socket-pinned HTTP client.

### 2.3 Database Layer (Supabase PostgreSQL)
* **Migrations Ledger:** 18 SQL migration scripts in `supabase/migrations/`:
  * `20260903000001_complete_production_schema.sql`: Consolidated production tables, RLS, triggers, indexes.
  * `20260904000001_fix_handle_new_user_trigger.sql`: Idempotent profile bootstrap on auth signup.
  * `20260908000001_add_stripe_billing_fields.sql`: Subscriptions, customer IDs, trial windows.
  * `20260909000001_reputation_checks_and_alert_configs.sql`: Time-series reputation snapshots.
  * `20260909000002_performance_and_idempotency_hardening.sql`: Webhook deduplication store.
  * `20260910000001_modernize_rbl_and_secure_rls.sql`: RLS hardening with explicit `WITH CHECK`.
  * `20260911000001_add_rbl_scan_results.sql`: RBL probe history table.
  * `20260912000001_add_audit_leases_and_failover_pipeline.sql`: Distributed worker audit leases.
  * `20260912000002_add_delivery_failure_ingestion_and_idempotency.sql`: ESP failure events.
  * `20260912000003_add_delivery_failure_claim_rpc.sql`: Atomic failure batch claiming RPC.
  * `20260912000003_allow_telegram_fallback_channel.sql`: Telegram failover channel support.
  * `20260913000001_add_readiness_and_revenue_risk.sql`: GMV revenue dispute risk tables.
  * `20260913000002_add_spf_merge_plans.sql`: Conflict-free SPF merge plans.
  * `20260913000003_add_remote_asset_fetch_audit.sql`: BIMI logo and VMC certificate fetch audit logs.
  * `20260913000004_add_stripe_subscriptions.sql`: Multi-subscription tracking table.
  * `20260916000001_allow_agency_tier.sql`: Agency tier support (20 domains).
  * `20260924000001_p0_security_hardening.sql`: Security definer search path hardening.
  * `20260925000001_p1_reliability_remediation.sql`: Decoupled retry backoff & distributed rate limit windows.
* **Core Tables (19 Tables):** `profiles`, `monitored_domains`, `dns_audit_logs`, `reputation_checks`, `rbl_scan_results`, `shopify_stores`, `alert_configs`, `alert_logs`, `failover_configs`, `failover_logs`, `delivery_failure_events`, `dns_provider_credentials`, `dns_auto_fix_logs`, `ai_template_audits`, `revenue_dispute_analytics`, `remote_asset_fetch_audits`, `spf_merge_plans`, `processed_webhook_events`, `rate_limit_windows`.
* **RPC Functions:** `claim_due_domain_audits`, `fail_domain_audit`, `complete_domain_audit`, `claim_pending_delivery_failures`, `consume_rate_limit`, `handle_new_user`.

### 2.4 Architecture Dependency Map

```
[ Client Browser / Mobile / Shopify Admin ]
                  │
                  ▼
[ Cloudflare Ingress Proxy (TLS Termination, DDoS Shield, CF-Connecting-IP) ]
                  │
                  ├───────────────────────────────┐
                  ▼                               ▼
[ Next.js 14 App Router (Port 3000) ]     [ FastAPI API Engine (Port 8000) ]
  ├── Edge Auth Guard (SSR Cookies)         ├── Trusted Host & CORS Guards
  ├── Responsive Obsidian Dark UI           ├── Anti-Spoofing Proxy Client IP Resolver
  └── SVG Real-Time Canvas Engines          ├── L1 In-Memory Rate Limiter (120 req/min)
                  │                         ├── JWT Auth Dependency (get_current_user_id)
                  │                         ├── L2 Distributed Rate Limiter (PostgreSQL RPC)
                  │                         ├── Tier Feature & Quota Guards (Starter/Growth/Enterprise)
                  │                         ├── DNS Diagnostic Engine (dnspython multi-resolver)
                  │                         ├── Anti-SSRF SafeHttpFetcher (Socket-pinned, size-capped)
                  │                         └── Webhook Ingestion Handlers (Stripe, Shopify, ESPs)
                  │                                       │
                  └───────────────────┬───────────────────┘
                                      ▼
                  [ Persistence Layer: Supabase PostgreSQL ]
                    ├── Strict RLS (auth.uid() = user_id)
                    ├── Service Role Fail-Closed Isolation
                    ├── Atomic Workers (claim_due_domain_audits SKIP LOCKED)
                    ├── Decoupled Retry Backoff & Randomized Jitter
                    └── Distributed Rate Limiting Storage (rate_limit_windows)
                                      │
                  ┌───────────────────┼───────────────────┐
                  ▼                   ▼                   ▼
          [ External APIs ]   [ Background Schedulers ] [ Worker Daemons ]
          - Stripe Billing     - BackgroundAuditor       - DeliveryFailureWorker
          - Shopify Admin/HMAC - AlertDispatcher         - SafeDnsResolver
          - Moonshot/OpenAI LLM- OpsAlertService (Telegram)
          - 10 Authoritative RBLs
```

---

## 3. Multi-Tenant Security Audit

### 3.1 Tenant Identity Acquisition & Cryptographic Proof
1. **Authentication Mechanism:** Every authenticated endpoint requires an HTTP `Authorization: Bearer <token>` header containing a valid Supabase JWT.
2. **Identity Resolution Code Path:** Injected via FastAPI dependency `get_current_user_id` (`app/core/security.py`, lines 124–154).
   * Extracts token string from header.
   * Cryptographically verifies signature against Supabase JWKS (asymmetric RS256/ES256) or symmetric `SUPABASE_JWT_SECRET`.
   * Enforces expiration timestamp (`verify_exp: True`).
   * Extracts authenticated subject: `user_id = payload.get("sub") or payload.get("user_id")`.
3. **Spoofing Immunity:** The client-supplied body or query parameters cannot override `user_id`. The identity is exclusively derived from the verified cryptographic JWT claims.

### 3.2 Tenant Isolation & Resource Ownership Matrix

| Endpoint Route | HTTP Method | Identity Source | Resource Ownership Check | Code Evidence | Result |
|---|---|---|---|---|---|
| `/api/v1/domains/` | `GET` | `get_current_user_id` | Scoped to authenticated `user_id` | `supabase_service.get_user_domains(user_id)` | **VERIFIED** |
| `/api/v1/domains/` | `POST` | `get_current_user_id` | Quota enforced; created under `user_id` | `enforce_domain_quota(user_id, count+1)` | **VERIFIED** |
| `/api/v1/domains/{domain_id}` | `DELETE` | `get_current_user_id` | Verifies domain belongs to user before deletion | `owned = next((d for d in existing if d["id"] == domain_id), None)` | **VERIFIED** |
| `/api/v1/domains/{domain_id}/toggle-active` | `PATCH` | `get_current_user_id` | Verifies domain ownership before update | `owned = next((d for d in existing if d["id"] == domain_id), None)` | **VERIFIED** |
| `/api/v1/domains/{domain_id}/audit` | `POST` | `get_current_user_id` | Verifies ownership; rate-limited (2 req/min) | `owned = next((d for d in existing if d["id"] == domain_id), None)` | **VERIFIED** |
| `/api/v1/dns/audit` | `POST` | None (Public Diagnostic) | None required (domain diagnostic inspection) | Cleaned via `DNSDiagnosticEngine._clean_domain` | **VERIFIED** |
| `/api/v1/billing/subscription` | `GET` | `get_current_user_id` | Scoped to user's profile | `supabase_service.get_user_profile(user_id)` | **VERIFIED** |
| `/api/v1/billing/checkout-session` | `POST` | `get_current_user_id` | Session created with metadata `user_id` | `stripe_service.create_checkout_session(user_id=user_id...)` | **VERIFIED** |
| `/api/v1/billing/customer-portal` | `POST` | `get_current_user_id` | Customer ID fetched from user profile | `profile.get("stripe_customer_id")` verified | **VERIFIED** |
| `/api/v1/billing/invoices` | `GET` | `get_current_user_id` | Retrieves invoices for user's Stripe customer ID | `stripe_service.get_customer_invoices(user_id=user_id)` | **VERIFIED** |
| `/api/v1/shopify/stores` | `GET` | `get_current_user_id` | Scoped to authenticated user stores | `supabase_service.get_user_stores(user_id)` | **VERIFIED** |
| `/api/v1/shopify/sync` | `POST` | `get_current_user_id` | Store domain matched against user's connected stores | `next((s for s in stores if s["shop_domain"] == domain), None)` | **VERIFIED** |
| `/api/v1/ai/audit` | `POST` | `get_current_user_id` | Scoped to user; rate-limited (10 req/min) | `supabase_service.record_ai_audit(user_id=user_id...)` | **VERIFIED** |
| `/api/v1/ai/variants` | `POST` | `get_current_user_id` | Scoped to user; rate-limited (10 req/min) | Rate limited by `consume_rate_limit(f"ai:{user_id}")` | **VERIFIED** |
| `/api/v1/settings/profile` | `GET` | `get_current_user_id` | Scoped to authenticated user profile | `supabase_service.get_user_profile(user_id)` | **VERIFIED** |
| `/api/v1/settings/api-keys` | `POST` | `get_current_user_id` | Enforces Enterprise tier; persists under user | `require_growth_or_enterprise_tier(user_id)` | **VERIFIED** |
| `/api/v1/dns/auto-fix/apply` | `POST` | `require_growth_or_enterprise_tier` | Verifies tier; fetches credentials for user | `dns_auto_fixer_service.apply_dns_fix(user_id=user_id...)` | **PARTIALLY VERIFIED** |
| `/api/v1/dns/auto-fix/rollback`| `POST` | `require_growth_or_enterprise_tier` | Scoped to user fix log | `dns_auto_fixer_service.rollback_dns_fix(user_id=user_id...)`| **PARTIALLY VERIFIED** |

### 3.3 Multi-Tenant Findings & Gaps
* **IDOR/BOLA Protection:** All primary domain, store, and billing operations check tenant ownership in `app/api/v1/domains.py` and `app/api/v1/shopify.py` before executing updates or expensive audits.
* **Partial Defect in Auto-Fix Router (`auto_fix.py`):** `apply_auto_fix` accepts `domain_name` in the payload and verifies user tier, but does **not** check whether `domain_name` exists in `monitored_domains` owned by `user_id`. Although Cloudflare execution relies on the user's configured `zone_id`, an authorized user could submit auto-fix logs referencing arbitrary domain names.
* **ID Enumerability:** Domain and store identifiers utilize standard UUID v4 formats in production migrations, preventing sequential ID enumeration.

---

## 4. Supabase & Row Level Security (RLS) Audit

### 4.1 Table-by-Table RLS Policy Matrix

| Table Name | RLS Enabled? | SELECT Policy | INSERT Policy | UPDATE Policy | DELETE Policy | Service-Role Bypass? |
|---|:---:|---|---|---|---|:---:|
| `profiles` | **YES** | `auth.uid() = id` | `auth.uid() = id` | `auth.uid() = id` | Denied / Service-role | **YES** (Controlled) |
| `monitored_domains` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | **YES** (Worker Lease) |
| `dns_audit_logs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Worker) |
| `reputation_checks` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Worker) |
| `rbl_scan_results` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Worker) |
| `shopify_stores` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | **YES** (OAuth/Sync) |
| `alert_configs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | **YES** |
| `alert_logs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Dispatcher) |
| `failover_configs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | **YES** |
| `failover_logs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Worker) |
| `delivery_failure_events` | **YES** | `auth.uid() = user_id` | Webhook / Service | Service / Worker | Denied | **YES** (Ingestion/Worker) |
| `dns_provider_credentials`| **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | **YES** |
| `dns_auto_fix_logs` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** |
| `ai_template_audits` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** |
| `revenue_dispute_analytics`| **YES**| `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied | **YES** |
| `remote_asset_fetch_audits`| **YES**| `auth.uid() = user_id` | `auth.uid() = user_id` | Denied (Immutable) | Denied (Immutable) | **YES** (Fetcher) |
| `spf_merge_plans` | **YES** | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | Denied | **YES** |
| `processed_webhook_events` | **YES** | Service-role only | Service-role only | Denied | Denied | **YES** (Stripe) |
| `rate_limit_windows` | **YES** | Service-role only | RPC (`consume_rate_limit`) | RPC (`consume_rate_limit`) | RPC / Service-role | **YES** (Limiter) |

### 4.2 Security Definer & Search Path Audit
* All PostgreSQL stored procedures created in migrations:
  * `public.claim_due_domain_audits`
  * `public.fail_domain_audit`
  * `public.complete_domain_audit`
  * `public.claim_pending_delivery_failures`
  * `public.consume_rate_limit`
  * `public.handle_new_user`
* **Evidence:** Every function explicitly declares `SECURITY DEFINER` and enforces `SET search_path = public, pg_temp` (`20260924000001_p0_security_hardening.sql`, `20260925000001_p1_reliability_remediation.sql`). This completely neutralizes search-path hijacking and privilege escalation vectors.

---

## 5. Authentication & Session Security Audit

### 5.1 JWT Validation & Cryptographic Integrity
* **Asymmetric Verification (Primary):** `verify_supabase_jwt` resolves public keys via Supabase JWKS endpoint (`/auth/v1/.well-known/jwks.json`) with in-memory caching and 1-hour TTL (`PyJWKClient`). Validates algorithms `RS256` and `ES256`.
* **Symmetric Verification (Fallback):** Decodes using `HS256` if symmetric keys are configured.
* **CRITICAL FINDING (P1 — Cryptographic Token Forgery Vector):**
  * In `app/core/security.py` (lines 82–96):
    ```python
    secret_candidates = [
        getattr(settings, "SUPABASE_JWT_SECRET", None),
        settings.SUPABASE_SERVICE_ROLE_KEY,
        settings.SUPABASE_KEY
    ]
    ```
  * `settings.SUPABASE_KEY` represents the Supabase **anon key**, which is public and embedded in frontend client builds (`NEXT_PUBLIC_SUPABASE_ANON_KEY`).
  * If `SUPABASE_KEY` is checked as a symmetric candidate secret, an attacker knowing the public anon key could forge an arbitrary JWT signed with `SUPABASE_KEY` using algorithm `HS256` containing `{"sub": "victim_user_id"}`, and the backend would accept it if JWKS is bypassed.
  * **Required Control:** Remove `settings.SUPABASE_KEY` from `secret_candidates` immediately. Symmetric decoding must strictly validate against `SUPABASE_JWT_SECRET`.

### 5.2 Session Management & CORS
* **Session Storage:** Next.js uses `@supabase/ssr` cookies (`sb-<project>-auth-token`). Cookies are flagged `httpOnly`, `SameSite=Lax`, and `Secure` in production.
* **CORS Origin Validation (`app/main.py` lines 148–172):**
  * `allow_credentials=True`.
  * `cors_origins` enforces explicit domains: `https://inbound-check-theta.vercel.app`, `http://localhost:3000`.
  * **FINDING (P2 — Permissive Origin Regex):** Line 168 sets `allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.up\.railway\.app|http://localhost:\d+"`.
  * Because any Vercel customer can deploy an application to `*.vercel.app`, an attacker hosting an exploit on Vercel could execute authenticated cross-origin requests with credentials against an instance matching this regex.
  * **Required Control:** Restrict `allow_origin_regex` to explicit production domain names (`^https://(inboundcheck\.com|inbound-check-[a-z0-9]+-team\.vercel\.app)$`).

---

## 6. Webhook Security Audit

### 6.1 Stripe Webhook Security
* **Endpoint:** `POST /api/v1/billing/webhook`
* **Payload Ceiling:** Enforces 1 MB maximum payload ceiling (`request.headers.get("content-length")` and `len(payload_bytes) > 1024 * 1024`).
* **Signature Verification:** Timestamped HMAC-SHA256 (`Stripe-Signature` header). Parses `t` and `v1` components. Computes `hmac.new(secret, f"{t}.{payload}", sha256).hexdigest()`. Validates with constant-time `hmac.compare_digest`.
* **Clock Skew Tolerance:** Rejects webhooks with timestamp drift exceeding $\pm 300$ seconds (`tolerance_seconds=300`).
* **Idempotency & Replay Protection:** Reconciled events are checked against the persistent database table `public.processed_webhook_events` (`is_event_processed`). Duplicate deliveries immediately return cached reconciliation status without executing duplicate upgrades.
* **Fail-Closed Policy:** In production (`ENVIRONMENT="production"`), missing signatures or unconfigured secrets strictly fail closed with HTTP 400.

### 6.2 Shopify Webhook Security
* **Endpoints:** `POST /api/v1/shopify/webhooks/customers-data-request`, `customers-redact`, `shop-redact`, `app-uninstalled`.
* **Signature Verification:** Base64 HMAC-SHA256 signature in `X-Shopify-Hmac-Sha256`. Computes HMAC over raw body bytes with `SHOPIFY_API_SECRET`. Validates using `hmac.compare_digest`.
* **Clock Skew:** Checks `X-Shopify-Triggered-At` within $\pm 300$ seconds.
* **FINDING (P1 — In-Memory Shopify Webhook Idempotency):**
  * `shopify_service._processed_webhooks` stores reconciled webhook IDs in an in-memory dictionary.
  * Unlike Stripe, Shopify webhook IDs are **not** persisted to `public.processed_webhook_events`.
  * During multi-container scaling or container recycles, duplicate Shopify webhooks could trigger redundant background workflows.

### 6.3 ESP Delivery Failure Ingestion Webhooks
* **Endpoints:** `POST /webhook/delivery-failure/{provider}` (`postmark`, `sendgrid`, `mailgun`, `ses`, `klaviyo`).
* **Payload Limit:** Enforces 1 MB ceiling via `read_body_with_limit`.
* **Cryptographic Verification:** Validated via provider-specific verifiers in `app/services/failover/esp_webhook_service.py` (Mailgun HMAC, SendGrid ECDSA/HMAC, Postmark token, SES signature).
* **Database Deduplication:** Normalized into `delivery_failure_events` with unique compound index `(esp_provider, provider_event_id)` preventing duplicate processing.

---

## 7. SSRF & Network Security Audit

InboundCheck interacts with remote networks during DNS audits, RBL checks, and remote asset fetching (BIMI SVG logos and VMC certificates).

### 7.1 DNS Diagnostic SSRF Defense (`DNSDiagnosticEngine`)
* **Input Sanitization (`_clean_domain`):** Strips protocols, URL paths, and ports. Validates domain length ($\le 253$ chars) and RFC 1035 format regex (`^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$`).
* **Restricted Target Filtering (`is_ssrf_restricted`):** Blocks `localhost`, `127.0.0.1`, `0.0.0.0`, `169.254.169.254`, `metadata.google.internal`, and internal TLDs (`.local`, `.internal`, `.lan`, `.corp`, etc.).
* **IP Network Rejection:** Blocks all direct IP inputs and checks parsed IPs against `RESTRICTED_SSRF_NETWORKS`:
  * `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10` (Carrier NAT), `127.0.0.0/8` (Loopback), `169.254.0.0/16` (Cloud Metadata), `172.16.0.0/12`, `192.168.0.0/16`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `::1/128`, `fc00::/7` (IPv6 ULA), `fe80::/10` (IPv6 Link-Local), `::ffff:0:0/96` (IPv4-mapped IPv6).
* **DNS Resolution Target:** DNS queries are dispatched to explicit external public nameservers (`1.1.1.1`, `8.8.8.8`, `9.9.9.9`), preventing internal network DNS resolution.

### 7.2 Remote Asset HTTP Fetcher (`SafeHttpFetcher`)
External HTTP requests (e.g. BIMI logo and VMC certificate downloads) are executed through `SafeHttpFetcher`:
* **Zero Ambient Proxy Trust:** `trust_env=False` ensures system environment proxies cannot intercept requests.
* **Socket-Level IP Pinning:** Uses `SafeDnsResolver.resolve_pinned_ip(hostname, port)` to resolve the target IP *before* connecting. Binds the HTTP connection directly to the resolved IP. This **completely eliminates DNS rebinding TOCTOU attacks**.
* **Strict Redirect Governance:** Manual redirect tracking capped at 3 hops (`ASSET_FETCH_MAX_REDIRECTS`). Detects circular loops and enforces anti-downgrade (HTTPS $\to$ HTTP is blocked). Each redirect hop re-validates URL policy and re-pins the destination IP.
* **Payload Stream Capping:** Streams response chunks and terminates connection immediately if body exceeds 500 KB (`ASSET_FETCH_MAX_BYTES`).
* **SHA-256 Digest:** Computes cryptographic hash for cache immutability and auditing.

---

## 8. Rate Limiting & Abuse Prevention Audit

### 8.1 Trusted Proxy Resolution & Anti-Spoofing
* **Resolver:** `get_trusted_client_ip` (`app/core/rate_limiter.py`).
* **Anti-Spoofing Algorithm:**
  1. Inspects the immediate socket peer (`request.client.host`).
  2. If peer is **not** in configured `TRUSTED_PROXY_SOURCES`: **Discards all forwarded headers** (`CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP`) and uses socket peer IP directly.
  3. If peer **is** in `TRUSTED_PROXY_SOURCES`: Parses `CF-Connecting-IP` (validated as IPv4/IPv6). If absent, walks `X-Forwarded-For` from right to left, selecting the rightmost untrusted IP.

### 8.2 Rate Limit Dimensions & Differentiated Failure Policies

| Tier / Route | Rate Limit Dimension | Quota | Storage Engine | Normal Behavior | Database Storage Offline Behavior |
|---|---|---|---|---|---|
| **Ingress L1** (`/*`) | Client IP | 120 req / 60s | In-Memory Sliding Window | Allow / 429 | Fail-Open with operational warning |
| **High-Cost AI** (`/api/v1/ai/*`) | `user_id` + endpoint | 10 req / 60s | PostgreSQL Atomic Window | Allow / 429 | **Conservative Fallback (Max 3 req/min) $\to$ Fail Closed 429** |
| **High-Cost DNS** (`/api/v1/dns/audit`) | `user_id` + endpoint | 15 req / 60s | PostgreSQL Atomic Window | Allow / 429 | **Conservative Fallback (Max 5 req/min) $\to$ Fail Closed 429** |
| **Manual Re-Audit** (`/api/v1/domains/{id}/audit`) | `user_id` + `domain_id` | 2 req / 60s (Max 10/user) | PostgreSQL Atomic Window | Allow / 429 | **Conservative Fallback (Max 1 req/min) $\to$ Fail Closed 429** |
| **High-Cost RBL** (`/api/v1/rbl/*`) | `user_id` + endpoint | 15 req / 60s | PostgreSQL Atomic Window | Allow / 429 | **Conservative Fallback (Max 5 req/min) $\to$ Fail Closed 429** |
| **Webhooks** (`/api/v1/billing/webhook`, etc.) | Client IP | 60 req / 60s | In-Memory (L1) | Allow / 429 | Fail-Closed on invalid signatures |

* **PostgreSQL Storage RPC (`consume_rate_limit`):**
  * Executes atomic upsert on `public.rate_limit_windows` with serialized row locking on `(bucket_key, window_start)`.
  * Computes `current_requests`, `remaining`, and `reset_seconds`.
  * Employs opportunistic pruning of expired windows ($< 1\%$ sample rate) on write.

---

## 9. Background Workers & Job Safety Audit

### 9.1 Domain Audit Scheduler (`BackgroundAuditor`)
* **Atomic Claiming:** Executes stored procedure `public.claim_due_domain_audits(p_worker_id, p_limit=25, p_interval='1 hour', p_lease_duration='15 minutes')`.
* **Locking Strategy:** Uses `FOR UPDATE SKIP LOCKED`. Candidate selection:
  ```sql
  WHERE is_active = true
    AND (last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval)
    AND (audit_lease_until IS NULL OR audit_lease_until < NOW())
    AND (next_audit_retry_at IS NULL OR next_audit_retry_at <= NOW())
  ```
  Guarantees zero duplicate execution across multiple worker container replicas.
* **Lease Expiration & Crash Recovery:** If a worker crashes mid-audit, `audit_lease_until` expires after 15 minutes, allowing surviving workers to re-claim the domain automatically.
* **Decoupled Retry Backoff & Randomized Jitter:**
  * When an audit fails, `fail_domain_audit` calculates delay:
    $$\text{delay} = \min\left(86400, 120 \times 2^{\min(\text{failures}, 10)}\right) + \text{jitter}(0\text{--}25\%)$$
  * Sets `next_audit_retry_at = NOW() + delay`.
  * Increments `audit_failure_count` and records `last_audit_error`.
  * Clears `audit_lease_owner` and `audit_lease_until`.
  * Successfully eliminates the Phase 2 audit retry storm.

### 9.2 Delivery Failure Queue Worker (`DeliveryFailureWorker`)
* **Queue Processing:** Processes pending rows in `public.delivery_failure_events`.
* **Atomic Batch Claiming:** Uses `claim_pending_delivery_failures(p_worker_id, p_limit=50)` with `FOR UPDATE SKIP LOCKED`.
* **Poison Job Defense:** Jobs exceeding maximum retry count ($\ge 5$) transition to `permanent_failure` status and trigger operational incident logging.

---

## 10. Billing, Entitlements & Tier Enforcement Audit

### 10.1 Tier Structure & Limits

| Plan Tier | Monthly Price | Monitored Domains Cap | Features Enforced Server-Side |
|---|:---:|:---:|---|
| **Starter** | $9 / mo | 1 Apex Domain | Basic DNS Diagnostic, 10-RBL Blacklist Radar, Telegram Alerting, 3-Day Free Trial. |
| **Growth** | $29 / mo | 3 Apex Domains | Shopify OAuth Sync, 1-Click DNS Auto-Fix, SPF Merge Engine, Revenue Dispute Analytics ($37.3\times$ ROI), 3-Day Free Trial. |
| **Agency** | $79 / mo | 20 Apex Domains | Up to 20 Domains, Multi-Store Sync, Priority Queue, White-Label Reporting Exports. |
| **Enterprise**| $199 / mo | 999 Apex Domains | Unlimited Domains, Developer API Keys, 15m Sweeps, AI Content Lab Polymorphic Optimizer. |

### 10.2 Server-Side Entitlement & Quota Enforcement
* **Domain Limit Enforcement:** `enforce_domain_quota` in `app/core/tier_guards.py`. Injected on `POST /api/v1/domains/`. Queries active domain count from database; rejects request with HTTP 403 Forbidden if count reaches tier quota.
* **Feature Gating (`require_growth_or_enterprise_tier`):**
  * Injected on 1-Click Auto-Fix (`/api/v1/dns/auto-fix/apply`, `rollback`).
  * Injected on SPF Merge Engine (`/api/v1/dns/merge-spf`).
  * Injected on Shopify Sync and Dispute Risk Analytics.
  * Injected on Developer API Key creation (`/api/v1/settings/api-keys`).
  * **Security Principle:** Frontend button states are strictly cosmetic; all paid features verify tier entitlements server-side via Supabase profile status.

### 10.3 Hybrid Checkout Architecture
* **Shopify Merchants:** In `create_checkout_session` (`app/api/v1/billing.py`), if the user has an active connected Shopify store, checkout automatically routes through `shopify_billing_service.create_recurring_application_charge` via Shopify GraphQL API, maintaining compliance with Shopify App Store Partner terms.
* **Standard Web Users:** Routes to standard Stripe Checkout session with metadata `{"user_id": user_id, "plan_tier": plan_tier}`.

---

## 11. Cost / Denial-of-Wallet Exposure Analysis

### 11.1 Variable-Cost Amplification Vectors
1. **AI Content Lab (`/api/v1/ai/audit`, `/api/v1/ai/variants`):** Calls external LLM provider (`LLM_API_BASE`). Bounded by 10 req/min rate limit and in-memory rule-based fallback heuristic when API key is missing or calls time out.
2. **DNS & RBL Probes (`/api/v1/dns/audit`, `/api/v1/rbl/scan`):** Resolves records across 10 authoritative RBLs. Bounded by 15 req/min user rate limit and concurrency semaphore (`asyncio.Semaphore(10)`).
3. **Telegram Operational Alerting:** Bounded by 15-minute anti-flapping suppression per incident fingerprint and database unique constraint `idx_failover_logs_one_telegram_per_event`.

### 11.2 Maximum Theoretical Abuse Cost Table

| Operational Vector | Unit Cost | Raw Unmitigated Exposure | InboundCheck Governance Control | Maximum Theoretical Abuse Exposure |
|---|:---:|:---:|---|:---:|
| **Moonshot/OpenAI LLM** | ~$0.002 / call | Unlimited loop ($120/hr) | Tier gate + 10 req/min limiter + fallback regex | **$1.20 / hour / user** |
| **DNS Resolution (dnspython)** | Zero (Bandwidth only) | Resolver socket exhaustion | 15 req/min limiter + 4s timeout | **Negligible ($0.00)** |
| **RBL Probes (10 Lists)** | DNS query block risk | Global IP ban by Spamhaus | 15 req/min limiter + 10-concurrency semaphore | **Zero financial cost** |
| **Shopify Admin API** | 40 req/bucket leak | API rate throttling (429) | Token encryption + 1 sync / 5m per store | **Zero financial cost** |
| **Stripe Checkout API** | Free (per-transaction fee) | Session creation flood | Authenticated user required + 120 req/min L1 | **Zero financial cost** |
| **Twilio WhatsApp/SMS** | $0.05 / msg | Scripted dispatch storm | Disabled/Deprecated; Telegram fallback used | **$0.00 (Zero financial cost)** |
| **PostgreSQL Rate Limit Windows**| Storage IOPS | Table unbounded growth | Expiration TTL (2 windows) + opportunistic pruning | **Negligible ($0.00)** |

---

## 12. Database Reliability & Query Performance Audit

### 12.1 Indexing & Query Plan Safety
* **Foreign Key Indexes:** All tables link `user_id` to `profiles(id)` or `auth.users(id)` with explicit foreign key constraints and B-tree indexes (`idx_monitored_domains_user_id`, `idx_dns_audit_logs_user_id`, `idx_shopify_stores_user_id`).
* **Worker Lease & Retry Indexes:**
  * `idx_monitored_domains_retry_schedule` on `monitored_domains (next_audit_retry_at)` WHERE `is_active = true AND next_audit_retry_at IS NOT NULL`.
  * `idx_monitored_domains_audit_lease` on `monitored_domains (audit_lease_until, is_active)`.
* **Rate Limiting Windows Index:**
  * Primary key `(bucket_key, window_start)` provides clustered $O(1)$ point lookups and atomic updates.
  * Index `idx_rate_limit_windows_expires` on `rate_limit_windows (expires_at)` accelerates opportunistic pruning.

### 12.2 Scale Projections (10x, 100x, 1000x)
* **At 10x Scale (5,000 domains):** Single worker loop finishes 5,000 domains in ~20 minutes with 25-concurrency claiming. Database IOPS negligible.
* **At 100x Scale (50,000 domains):** In-process scheduler cannot complete 50,000 domains within 1 hour. Requires distributed worker containers using `claim_due_domain_audits`.
* **At 1000x Scale (500,000 domains):** Table `reputation_checks` and `dns_audit_logs` will accumulate ~12M rows/day. Requires monthly table partitioning (`PARTITION BY RANGE (created_at)`) and cold storage data archival.

---

## 13. Observability & Operational Incident Logging Audit

### 13.1 Health & Readiness Probes (`app/main.py`)
* **Liveness Probe (`GET /health`):** Lightweight probe returning `{"status": "alive"}`. Does not query external dependencies; verifies process and event loop responsiveness.
* **Readiness Probe (`GET /ready` and `GET /api/v1/health`):**
  * Actively probes database connectivity via `supabase_service.check_db_health()`.
  * Inspects scheduler status.
  * **Fail-Closed Readiness:** If the database probe fails and in-memory fallback is disallowed (`ENVIRONMENT="production"`), returns `HTTP 503 Service Unavailable` with structured diagnostic details.

### 13.2 Operational Alerting Implementation Posture

| Component | Status | Code Evidence | Verification Posture |
|---|:---:|---|:---:|
| **OpsAlertService Engine** | **IMPLEMENTED** | `app/services/alerting/ops_alert_service.py` | Unit tested (mock webhook & Telegram) |
| **Payload Sanitization (Secrets Redaction)** | **IMPLEMENTED** | `sanitize_incident_payload()` | Tested with regex credential masking |
| **Anti-Flapping Suppression (15m Cooldown)** | **IMPLEMENTED** | `_INCIDENT_COOLDOWNS` dictionary | Tested with repeated incident dispatches |
| **External Channel Integration** | **PARTIALLY IMPLEMENTED** | Relies on `OPS_ALERT_WEBHOOK_URL` / `OPS_ALERT_TELEGRAM_BOT_TOKEN` | Requires production environment variable provisioning |
| **Distributed Tracing (OpenTelemetry)** | **MISSING** | Standard Python `logging` with reference UUIDs | Architecture decision: deferred to Phase 3 |

---

## 14. Disaster Recovery & Continuity Audit

| Failure Scenario | Recovery Mechanism | RPO (Data Loss) | RTO (Downtime) | Verification Status |
|---|---|:---:|:---:|:---:|
| **Supabase Outage** | Application enters shielded degraded mode; API returns 503 with reference ID; DNS diagnostics continue in-memory. | 0 seconds (managed WAL) | Dependent on Supabase SLA | **PARTIALLY VERIFIED** |
| **Stripe Outage** | Webhook events buffered at Stripe edge; automatic exponential retries for up to 72 hours. | 0 seconds | < 5 minutes after Stripe recovery | **VERIFIED** |
| **Shopify API Outage** | OAuth and store sync fail closed with friendly error; existing domain audits unaffected. | 0 seconds | Immediate upon Shopify recovery | **VERIFIED** |
| **LLM Provider Outage** | AI Content Lab falls back immediately to deterministic regex rule-based engine. | 0 seconds | 0 seconds (zero downtime fallback) | **VERIFIED** |
| **Worker Container Crash** | Leases expire automatically after 15 minutes; surviving workers re-claim orphan domains via `SKIP LOCKED`. | 0 seconds | < 15 minutes | **VERIFIED** |
| **Database Restore Procedure** | Point-in-time recovery via Supabase PostgreSQL physical backups. | < 5 minutes | < 30 minutes | **UNVERIFIED** (Requires live dry-run drill) |

---

## 15. Frontend Security Audit

* **Cross-Site Scripting (XSS):** React 18 automatically escapes dynamic expressions in JSX.
* **Dangerous HTML Rendering:**
  * `dangerouslySetInnerHTML` is used in exactly one place: `src/app/page.tsx` (line 306) to embed the static JSON-LD `structuredData` script. The content is strictly generated from static objects and safe configuration values.
* **Environment Variable Hygiene:**
  * Public variables (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`) are verified safe for browser exposure.
  * Zero private secrets (`SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `SHOPIFY_API_SECRET`) exist in the frontend repository or bundle traces.
* **Source Maps in Production:** Next.js production builds disable source map emission by default, preventing client-side proprietary code exposure.

---

## 16. API Security & Injection Defense Audit

* **SQL Injection:** Supabase client utilizes PostgREST parameter binding. Raw string concatenation is prohibited in application code. All database RPCs use typed PL/pgSQL parameters with immutable search paths.
* **Command Injection:** The codebase contains zero calls to `os.system()`, `subprocess.Popen()`, or shell evaluation functions.
* **Template Injection:** The AI Content Lab processes templates using standard regex pattern matching and string replace routines without passing text to template evaluators (`eval()`, `exec()`, or Jinja2 unescaped contexts).
* **Mass Assignment:** All endpoint payloads are bound to strict Pydantic v2 schemas (`extra="forbid"` default in core models).

---

## 17. Data Privacy & GDPR/CCPA Governance

* **Data Collected:** Merchant email, store apex domain, Shopify shop domain, encrypted OAuth access tokens (Fernet AES-128-CBC), masked API keys, DNS health audit logs.
* **Personal Customer Data (Shopify End Users):**
  * InboundCheck does **not** store customer names, physical addresses, or credit card numbers.
  * In delivery failure events, email addresses are scrubbed or normalized into SHA-256 hashes (`customer_identifier_hash`).
* **Shopify GDPR Mandatory Webhooks:**
  * `POST /api/v1/shopify/webhooks/customers-data-request`: Returns 200 OK (no customer PII retained).
  * `POST /api/v1/shopify/webhooks/customers-redact`: Returns 200 OK.
  * `POST /api/v1/shopify/webhooks/shop-redact`: Asynchronously initiates store data purge.
* **Compliance Documents:** Public legally-binding documents present and statically compiled: `/privacy`, `/terms`, `/security`, `/dpa`.

---

## 18. Technical SEO Audit

* **Title Tags & Meta Descriptions:**
  * Root Title: `"InboundCheck — Shopify Email Deliverability & DNS Governance Platform"`.
  * Meta Description: `"Stop Shopify order receipts from vanishing into spam. Continuous SPF, DKIM, DMARC governance & instant Telegram incident alerts."`
* **Canonical URL:** Statically configured to `"https://inboundcheck.com"` in root layout metadata.
* **XML Sitemap (`/sitemap.xml`):** Valid Next.js route handler (`src/app/sitemap.ts`) indexing public routes with priority and change frequencies.
* **Robots Directives (`/robots.txt`):** Allows public landing and legal routes; disallows `/dashboard/*`, `/api/*`, and `/auth/callback`.
* **Structured Data:** Schema.org `@graph` with `WebApplication`, `SoftwareApplication`, and `FAQPage` embedded cleanly in landing HTML.
* **Core Web Vitals:** Canvas 3D micro-visualizations use lazy intersection observers (`isVisibleRef`) and respect `prefers-reduced-motion` to preserve 60fps frame rates and low First Input Delay (FID).

---

## 19. Generative Engine Optimization (GEO) & AEO Audit

* **Entity Clarity:** Explicitly defines InboundCheck as an institutional email deliverability governance platform for Shopify and DTC brands.
* **RFC Authoritative Citations:** Content references official email standards: RFC 7208 (SPF), RFC 6376 (DKIM), RFC 7489 (DMARC), and Google/Yahoo February 2024 Sender Guidelines.
* **Answer Engine Extractability:**
  * 5 Core High-Intent FAQ question/answer pairs formatted concisely for AI citation in ChatGPT Search, Perplexity AI, and Google AI Overviews.
  * Explicit definition blocks contrasting InboundCheck against marketing ESPs (Klaviyo, Omnisend) to prevent hallucinated category classification.

---

## 20. Competitive Landscape & Market Positioning

*Note: Per governing audit instructions, competitors are documented factually without subjective ranking or declaring a winner.*

### 20.1 Direct Deliverability Testing & Monitoring Competitors
* **GlockApps:**
  * *Target Customer:* High-volume email marketers, cold outbound agencies, enterprise deliverability consultants.
  * *Pricing:* $59/mo (Essential) to $129+/mo (Enterprise); credit-based placement tests.
  * *Features:* Seed list inbox placement tests, spam filter diagnostics, DMARC analyzer, blacklist monitoring.
  * *Claimed Strengths:* Granular breakdown of tab placement (Primary vs Promotions vs Spam) across Gmail and Outlook.
  * *User-Reported Limitations:* Manual seed-list sending required; does not automate DNS zone remediation; high cost for automated continuous polling.
* **MailerCheck:**
  * *Target Customer:* SMB senders and MailerLite users.
  * *Pricing:* Pay-as-you-go credits ($10/tier) or subscription ($25/mo).
  * *Features:* Email list verification, pre-send spam content analysis, basic DNS check.
  * *Claimed Strengths:* Affordable list hygiene combined with basic deliverability audits.
  * *User-Reported Limitations:* Focuses primarily on list validation rather than continuous DNS governance or eCommerce transactional flows.

### 20.2 Enterprise DMARC & DNS Governance Platforms
* **Red Sift (OnDMARC):**
  * *Target Customer:* Enterprise IT and cybersecurity infrastructure teams.
  * *Pricing:* Custom annual contracts ($3,000 to $50,000+/year).
  * *Features:* Automated DMARC policy enforcement, dynamic SPF record flattening, BIMI VMC management.
  * *Claimed Strengths:* Enterprise-grade compliance, security incident auditing, zero manual DNS limit friction.
  * *User-Reported Limitations:* Prohibitive cost for SMB/DTC brands; lacks Shopify OAuth store integration and transactional copy intelligence.
* **Valimail / DMARCian:**
  * *Target Customer:* Corporate domain administrators and enterprise security officers.
  * *Pricing:* Freemium to $500+/mo.
  * *Features:* DMARC aggregate report parsing, authorized sender inventory, automated SPF management.
  * *User-Reported Limitations:* Steep learning curve; reports take weeks to accumulate actionable intelligence; no direct Shopify store alignment.

### 20.3 Shopify Native & Marketing Platforms
* **Klaviyo / Omnisend Built-In Health:**
  * *Target Customer:* Shopify merchants running marketing campaigns.
  * *Pricing:* Bundled into marketing tier based on contact volume.
  * *Features:* Campaign bounce rates, unsubscribe tracking, basic dedicated sending domain setup instructions.
  * *Claimed Strengths:* Direct native integration with Shopify order and cart triggers.
  * *User-Reported Limitations:* Monitors only marketing emails sent through their platform; blind to Shopify native transactional receipts (order confirmations, shipping notifications sent via Shopify Mailer or third-party apps); cannot merge multi-app SPF records.

### 20.4 Free & DIY Alternatives
* **Mail-Tester.com / MXToolbox:**
  * *Target Customer:* Developers and freelance technicians.
  * *Pricing:* Free for basic manual queries; paid API subscriptions.
  * *Features:* Single-shot manual SPF/DKIM validation; blacklist lookup tool.
  * *Limitations:* Requires manual user action for every check; no continuous surveillance; no 1-click zone auto-fixing; no incident alerting.

---

## 21. Product & Micro-SaaS Value Architecture

* **Ideal Customer Profile (ICP):** Shopify DTC brands doing \$15k–\$500k monthly GMV using multi-app stacks (Shopify + Klaviyo + Gorgias/Zendesk + Postmark) who suffer from transactional order confirmation emails landing in spam.
* **Jobs-to-be-Done (JTBD):** "Ensure 100% of my customers receive their order confirmation and shipping receipts immediately, without hiring an expensive DNS consultant or getting trapped in Google/Yahoo 10-lookup SPF limit violations."
* **Core Activation Event (< 60s Time-to-Value):** Merchant inputs store domain $\to$ instant multi-resolver audit reveals Google/Yahoo 2024 compliance failure and SPF lookup count $\to$ displays estimated monthly at-risk GMV.
* **Retention Loop:** Continuous background radar scanning apex domains and 10 RBLs hourly $\to$ dispatches instant Telegram alert when a blacklist or DNS regression occurs $\to$ provides 1-click auto-remediation.
* **Expansion Revenue Vectors:** Multi-store domain add-ons, Agency tier upgrade (20 domains), Developer API key provisioning.

---

## 22. Marketing Acquisition & Growth Map

| Channel | Target Audience | Acquisition Mechanism | Required Assets | Operational Effort |
|---|---|---|---|:---:|
| **Shopify App Store** | Active Shopify merchants | Search terms: "email spam fix", "order confirmation not received", "DMARC compliance" | App listing, icon, demo video, OAuth app submission | **High** (App review process) |
| **Programmatic SEO (pSEO)** | Technical founders & store devs | Long-tail search pages: "How to fix SPF 10 lookup limit for Shopify + Klaviyo + Gorgias" | Dynamic comparison templates, RFC guides | **Medium** |
| **Shopify Community & Reddit** | Frustrated store owners | Factual answers to merchant questions regarding 2024 Gmail/Yahoo spam updates | Technical case studies, deliverability cheat-sheet | **Medium** (Community engagement) |
| **Agency Partner Channel** | Shopify Plus design & dev agencies | Referral revenue share (20%) or Agency Tier dashboard for managing 20 client stores | White-label PDF export engine, partner portal | **High** |
| **Free DNS Diagnostic Magnet** | Cold organic search visitors | Free on-demand apex domain audit tool on landing page converting to 3-day trial | Existing `/api/v1/dns/audit` public endpoint | **Low** (Already live) |

---

## 23. Production Deployment & Platform Infrastructure

### 23.1 Container Architecture & Multi-Service Deployment
* **Backend Container (`backend/Dockerfile`):**
  * Base image: `python:3.11-slim` (compatible with 3.12+ features).
  * Runs Uvicorn: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
  * Multi-container composition defined in `docker-compose.yml` (`web` service).
* **Frontend Container (`frontend/Dockerfile`):**
  * Multi-stage Node.js 18/20 alpine build producing optimized `.next/standalone`.
  * Exposed on port 3000.
* **Reverse Proxy Ingress:** Cloudflare edge proxy forwarding to Railway container infrastructure.

### 23.2 Secrets & Runtime Configuration
* All sensitive credentials are decoupled into environment variables (`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `STRIPE_SECRET_KEY`, `SHOPIFY_API_SECRET`, `CLOUDFLARE_API_TOKEN`).
* Verified fail-fast runtime environment guard (`app/core/env_guard.py`) validates configuration integrity on startup before serving traffic.

---

## 24. Failure Mode & Resilience Matrix

| Component | Failure Mode | User Impact | Data Impact | Cost Impact | System Recovery Mechanism | Current Protection Status |
|---|---|---|---|---|---|:---:|
| **Supabase PostgreSQL** | Unreachable / Connection Pool Exhausted | Dashboard enters degraded state; displays friendly notice | 0 data corruption; writes buffered or rejected safely | Zero runaway billing | Global exception shield catches `DatabaseUnavailableError`, returns HTTP 503 with tracking UUID | **VERIFIED** |
| **Stripe API** | Webhook delivery timeout or network drop | Temporary subscription upgrade delay | Zero data loss; Stripe retries up to 72h | Zero | Idempotent reconciliation via `public.processed_webhook_events` ensures safe retry | **VERIFIED** |
| **Shopify OAuth** | Access token revocation by merchant | Store sync pauses; alert dispatched | Encrypted token marked inactive | Zero | Fails gracefully; logs error; prompts re-authorization in `/dashboard/shopify` | **VERIFIED** |
| **OpenAI / Moonshot LLM** | API rate limit (429) or endpoint outage | AI Content Lab audit delayed | Zero data loss | Zero | Automatic fallback to deterministic regex rule-based scoring engine | **VERIFIED** |
| **Authoritative RBL Server** | Resolver timeout or DNSBL UDP dropped | Single RBL marked "unavailable" | Zero; other 9 RBLs complete normally | Zero | 4.0s timeout per resolver; concurrency semaphore limits blast radius | **VERIFIED** |
| **Worker Container Crash** | Host OOM or instance restart mid-audit | Domain audit interrupted | Zero data loss; uncommitted transaction rolled back | Zero | `audit_lease_until` expires in 15m; surviving workers re-claim via `SKIP LOCKED` | **VERIFIED** |
| **Rate Limiter Storage Outage** | PostgreSQL unreachable during rate limit check | Temporary degradation | Zero data loss | Bounded local fallback | Conservative local in-memory budget kicks in (Max 3 AI, 5 DNS) then fails closed (429) | **VERIFIED** |

---

## 25. Security Red Team Findings

### Attack Scenario 1: JWT Signature Forgery via Anon Key
* **Attack:** Adversary creates an HS256 JWT containing `{"sub": "victim_uuid"}` and signs it using the public Supabase anon key (`NEXT_PUBLIC_SUPABASE_ANON_KEY`).
* **Preconditions:** Backend enables symmetric secret candidate list containing `SUPABASE_KEY` (`app/core/security.py`, line 85).
* **Attack Path:** Attacker transmits forged token to `/api/v1/domains/`. Backend cycles through `secret_candidates` and matches `SUPABASE_KEY`.
* **Expected Defense:** Token signature rejected with HTTP 401.
* **Actual Defense:** Token would decode successfully if `SUPABASE_KEY` is tested and verified.
* **Result:** **CRITICAL VULNERABILITY (P1)**.
* **Remediation:** Remove `settings.SUPABASE_KEY` from `secret_candidates` immediately.

### Attack Scenario 2: Reverse Proxy Forwarded Header Spoofing
* **Attack:** Malicious client sends `X-Forwarded-For: 8.8.8.8` or `CF-Connecting-IP: 1.1.1.1` to bypass rate limits.
* **Preconditions:** Untrusted direct connection to API.
* **Attack Path:** Client sends repeated requests with randomized spoofed IPs.
* **Expected Defense:** Backend ignores client-supplied headers.
* **Actual Defense:** `is_ip_trusted_proxy(direct_peer)` evaluates to False. Forwarded headers are discarded; direct socket peer IP is enforced.
* **Result:** **ATTACK DEFEATED (VERIFIED)**.

### Attack Scenario 3: Server-Side Request Forgery (SSRF) via AWS Metadata
* **Attack:** User submits `http://169.254.169.254/latest/meta-data/` to DNS diagnostic or BIMI asset fetcher.
* **Preconditions:** Attacker has an active account.
* **Attack Path:** Submits cloud metadata IP as a target.
* **Expected Defense:** Request blocked immediately before socket connection.
* **Actual Defense:** `DNSDiagnosticEngine._clean_domain` rejects direct IPs and RFC 3927 link-local addresses. `SafeHttpFetcher` pins IP and blocks `169.254.0.0/16` via `SafeDnsResolver`.
* **Result:** **ATTACK DEFEATED (VERIFIED)**.

### Attack Scenario 4: Denial of Wallet via AI Audit Loop
* **Attack:** Automated script calls `/api/v1/ai/audit` 1,000 times per minute.
* **Preconditions:** Attacker creates an authenticated account.
* **Attack Path:** Infinite HTTP POST loop.
* **Expected Defense:** Endpoint throttles attacker.
* **Actual Defense:** `consume_rate_limit(f"ai:{user_id}")` allows exactly 10 requests within 60 seconds. Request #11 returns HTTP 429 Too Many Requests.
* **Result:** **ATTACK DEFEATED (VERIFIED)**.

---

## 26. Master Risk Register

| Risk ID | Domain | Finding & Vulnerability | Severity | Likelihood | Impact | Exploitability | Current Mitigation | Required Missing Control | Priority | Verification Method |
|:---:|---|---|:---:|:---:|:---:|:---:|---|---|:---:|---|
| **SEC-01** | Auth Security | `SUPABASE_KEY` (public anon key) included in JWT symmetric secret candidate list | **P1** | Low | High | Medium | JWKS asymmetric check runs first | Remove `SUPABASE_KEY` from `secret_candidates` in `app/core/security.py` | **HIGH** | Unit test verifying anon-signed JWT is rejected with 401 |
| **SEC-02** | Data Persistence | 1-Click DNS Auto-Fix stores credentials in-memory (`_mock_provider_creds`) rather than DB | **P1** | High | Med | Low | Feature restricted to Growth/Enterprise tiers | Persist encrypted credentials into `dns_provider_credentials` via Fernet cipher | **HIGH** | Integration test asserting persistence across process restarts |
| **SEC-03** | Webhooks | Shopify webhooks deduplicate in-memory only (`_processed_webhooks`) | **P1** | Med | Med | Low | HMAC and 300s timestamp drift checks | Persist Shopify webhook IDs to `public.processed_webhook_events` | **HIGH** | Test asserting duplicate Shopify webhook ID is ignored after restart |
| **SEC-04** | API Security | Permissive CORS regex (`r"https://.*\.vercel\.app"`) allows cross-origin requests from any Vercel domain | **P2** | Low | Med | Medium | Host header checks and auth cookies | Restrict regex strictly to official deployment domains | **MED** | Automated curl test verifying untrusted Vercel origin is denied |
| **SEC-05** | API Security | `TrustedHostMiddleware` includes wildcard `"*"` in `allowed_hosts` | **P2** | Low | Low | Low | Cloudflare edge proxy enforces Host header | Remove `"*"` from `allowed_hosts` in production | **MED** | Test asserting arbitrary Host header returns HTTP 400 |
| **SEC-06** | Observability | Production alerting channels (Webhook / Telegram bot) unprovisioned in default env | **P2** | High | Low | Low | `OpsAlertService` fails safe without raising exceptions | Provision production secrets in deployment environment variables | **MED** | Trigger test alert and verify receipt in operations channel |
| **FIN-01** | Billing / CRO | Pricing discrepancy: `billing.py` docstrings quote $29/$79/$199; code and UI quote $9/$29/$79/$199 | **P3** | Low | Low | Low | Code and Stripe products execute at $9/$29/$79/$199 | Align docstrings and API documentation with official pricing tiers | **LOW** | Code inspection |
| **DAT-01** | Database | Time-series tables (`dns_audit_logs`, `reputation_checks`) lack automated range partitioning | **P3** | Low | Med | Low | Clustered indexes and bounded queries | Implement monthly range partitioning in Phase 3 | **LOW** | Query plan inspection at scale |

---

## 27. Objective Production Go/No-Go Gates

```
========================================================================================
                         INBOUNDCHECK PRODUCTION GATE STATUS
========================================================================================
[ PASS ]             SECURITY GATE: Anti-SSRF, Rate Limiting, RLS Search Paths Verified
[ PASS ]             DATA INTEGRITY GATE: 18 Migrations Applied, Strict RLS Verified
[ PASS ]             RELIABILITY GATE: 169/169 Pytest Passing, 25/25 Next.js Pages Compiled
[ PARTIAL VERIFIED ] AUTHENTICATION GATE: JWKS active; P1 Anon Key candidate secret open
[ PARTIAL VERIFIED ] BILLING GATE: Stripe & Shopify hybrid active; docstring pricing drift
[ PARTIAL VERIFIED ] OBSERVABILITY GATE: OpsAlertService tested; production tokens required
[ NOT VERIFIED ]     DISASTER RECOVERY GATE: Point-in-time restore drill unexecuted
[ PASS ]             SEO / AEO / GEO GATE: Metadata, Sitemap, Schema.org Graph Verified
[ PASS ]             PRIVACY & LEGAL GATE: DPA, Terms, Privacy, GDPR Webhooks Verified
[ PARTIAL VERIFIED ] PRODUCT READINESS GATE: Core active; Auto-Fix requires DB credential store
========================================================================================
OVERALL STATUS: PROVISIONAL PRODUCTION READINESS (Pass with 3 Required P1 Remediations)
========================================================================================
```

### Detailed Gate Audit Specifications

1. **SECURITY GATE: [PASS]**
   * *Required Evidence:* Anti-SSRF enforcement verified via `test_safe_http_fetcher.py`; distributed rate limiting verified via `test_phase2_1_remediation.py`; RLS policies contain `auth.uid() = user_id`.
   * *Verification Command:* `py -m pytest tests/test_safe_http_fetcher.py tests/test_phase2_1_remediation.py` $\to$ **100% Pass**.

2. **DATA INTEGRITY GATE: [PASS]**
   * *Required Evidence:* Schema migrations 001 through `20260925000001_p1_reliability_remediation.sql` present; functions declare immutable search paths; foreign key cascades configured safely.
   * *Verification Command:* Schema validation of `supabase/migrations/*.sql`.

3. **RELIABILITY GATE: [PASS]**
   * *Required Evidence:* 169 backend pytest tests pass; Next.js 14 frontend build succeeds with 25/25 static pages and zero compiler errors; worker retry storms resolved with backoff and jitter.
   * *Verification Commands:*
     * Backend: `py -m pytest tests/` $\to$ **169 passed in 93.68s**.
     * Frontend: `npm run build` $\to$ **25/25 pages compiled successfully**.

4. **AUTHENTICATION GATE: [PARTIALLY VERIFIED]**
   * *Required Evidence:* Asymmetric JWKS caching active; Bearer token extraction verified; blocking P1 finding SEC-01 (`SUPABASE_KEY` in symmetric secret candidate list) must be resolved before general availability.

5. **BILLING GATE: [PARTIALLY VERIFIED]**
   * *Required Evidence:* Hybrid checkout routes Shopify stores to GraphQL and web users to Stripe; webhook HMAC and idempotency verified; docstring pricing discrepancy noted.

6. **OBSERVABILITY GATE: [PARTIALLY VERIFIED]**
   * *Required Evidence:* `/health` (liveness) and `/ready` (readiness) probes separated and functional; `OpsAlertService` tested; production webhook/bot secrets must be injected into Railway/Cloudflare environment.

7. **DISASTER RECOVERY GATE: [NOT VERIFIED]**
   * *Required Evidence:* Failover logic tested; database point-in-time restore requires live operational execution drill on staging.

8. **SEO / AEO / GEO GATE: [PASS]**
   * *Required Evidence:* `src/app/sitemap.ts` and `src/app/robots.ts` active; Schema.org `@graph` validated with `WebApplication`, `SoftwareApplication`, and `FAQPage`.

9. **PRIVACY & LEGAL GATE: [PASS]**
   * *Required Evidence:* GDPR redaction webhooks implemented; PII hashing active; public `/dpa`, `/privacy`, `/security`, `/terms` compiled.

10. **PRODUCT READINESS GATE: [PARTIALLY VERIFIED]**
    * *Required Evidence:* All core diagnostic views operational; Auto-Fix credential persistence (SEC-02) must migrate from in-memory to PostgreSQL before GA.

---

## 28. Phase 3 Strategic Roadmap

*Notice: In strict adherence to audit rules, no Phase 3 tasks have been implemented during this audit.*

### Phase 3A — Security & Cryptographic Hardening
* **Problem:** `SUPABASE_KEY` in symmetric candidate list; permissive Vercel CORS regex; wildcard in `TrustedHostMiddleware`.
* **Why it Matters:** Eliminates potential token forgery vectors and cross-origin exploitation.
* **Affected Files:** `backend/app/core/security.py`, `backend/app/main.py`.
* **Approach:** Remove `SUPABASE_KEY` from candidate secrets; restrict CORS regex to explicit production domains; remove `"*"` from `allowed_hosts`.
* **Required Tests:** Unit test with anon-key signed JWT expecting HTTP 401; test with unauthorized Vercel origin expecting CORS rejection.

### Phase 3B — Billing & Credential Persistence
* **Problem:** Auto-Fix credentials stored in memory (`_mock_provider_creds`); Shopify webhooks deduplicate in memory; pricing docstring mismatch.
* **Why it Matters:** Prevents credential loss on container recycles and protects against duplicate Shopify webhook replays.
* **Affected Files:** `backend/app/services/dns/auto_fixer.py`, `backend/app/services/shopify/shopify_service.py`, `backend/app/api/v1/billing.py`.
* **Approach:** Wire `auto_fixer.py` to persist encrypted credentials to `dns_provider_credentials` via Fernet encryption; record Shopify webhooks in `processed_webhook_events`.
* **Required Tests:** Test asserting Cloudflare credentials persist and reload across service instantiation; test asserting duplicate Shopify webhook ID is ignored.

### Phase 3C — Reliability & Operational Alerting Provisioning
* **Problem:** `OpsAlertService` operational channels unprovisioned in production environment.
* **Why it Matters:** Ensures SRE and operations receive real-time alerts on P0/P1 incidents without alert fatigue.
* **Affected Files:** Deployment environment variables (`OPS_ALERT_WEBHOOK_URL`, `OPS_ALERT_TELEGRAM_BOT_TOKEN`, `OPS_ALERT_TELEGRAM_CHAT_ID`).
* **Approach:** Provision secrets in Railway/Cloudflare deployment settings; trigger validation alert during deployment pipeline.
* **Required Tests:** Live integration alert test in pre-production staging.

### Phase 3D — Observability & Tracing Expansion
* **Problem:** Absence of distributed trace correlation IDs across Next.js frontend and FastAPI backend.
* **Why it Matters:** Reduces incident Mean Time to Resolution (MTTR) by linking frontend client errors directly to backend database queries.
* **Affected Files:** `frontend/src/lib/api.ts`, `backend/app/main.py`.
* **Approach:** Generate `X-Request-ID` in Next.js middleware; propagate header through FastAPI request state and logger context.

### Phase 3E — Cost Governance & Table Partitioning
* **Problem:** Unbounded growth of time-series audit tables (`dns_audit_logs`, `reputation_checks`) at scale.
* **Why it Matters:** Protects database performance and prevents storage bloat.
* **Affected Files:** Supabase database migration scripts.
* **Approach:** Introduce monthly range partitioning and automated 90-day cold storage archival policies.

### Phase 3F — SEO / AEO / GEO Content Expansion
* **Problem:** Static comparison pages against competitors (GlockApps, Red Sift, Klaviyo) currently absent.
* **Why it Matters:** Captures high-intent organic search queries and strengthens AI citation visibility in Perplexity and ChatGPT Search.
* **Affected Files:** `frontend/src/app/vs/`.
* **Approach:** Build programmatic comparison pages highlighting InboundCheck's 1-click DNS remediation and Shopify store integration.

### Phase 3G — Marketing & Shopify App Store Distribution
* **Problem:** App currently distributed via standalone web onboarding; Shopify App Store listing pending.
* **Why it Matters:** Unlocks the primary organic distribution channel for Shopify merchants.
* **Affected Files:** Shopify Partner Dashboard configuration.
* **Approach:** Submit InboundCheck for Shopify App Store review under "Marketing & Deliverability" category.

### Phase 3H — Competitive Moat Strengthening
* **Problem:** Competitors lack native Shopify store alignment and automated SPF merge engines.
* **Why it Matters:** Solidifies InboundCheck's position as the institutional deliverability standard for eCommerce.
* **Approach:** Double down on zero-lookup-limit SPF merging and predictive GMV dispute forecasting ($37.3\times$ ROI messaging).

---

## Top 10 Blocking or High-Risk Findings

1. **[P1 Security] Cryptographic JWT Forgery Vector (`app/core/security.py`):** `SUPABASE_KEY` (public anon key) is included in symmetric secret candidates, which would allow anyone possessing the public anon key to forge HS256 tokens if symmetric decoding is engaged.
2. **[P1 Persistence] Auto-Fix Credentials In-Memory Only (`app/services/dns/auto_fixer.py`):** Provider credentials and fix logs reside in `_mock_provider_creds` and `_mock_fix_logs` rather than the `dns_provider_credentials` database table, causing credential loss across container restarts.
3. **[P1 Reliability] Shopify Webhook Replay Vulnerability (`app/services/shopify/shopify_service.py`):** Shopify webhook deduplication is tracked in an in-memory dictionary rather than `public.processed_webhook_events`, risking duplicate webhook executions across scaled worker containers.
4. **[P2 Security] Permissive CORS Regex (`app/main.py`):** `allow_origin_regex` permits requests from any arbitrary `*.vercel.app` subdomain with credentials, exposing the API to cross-origin exploitation from other Vercel tenants.
5. **[P2 Security] Wildcard Host Header Acceptance (`app/main.py`):** `TrustedHostMiddleware` includes `"*"` in `allowed_hosts`, defeating Host header validation.
6. **[P2 Observability] Unprovisioned Operational Alerting:** `OpsAlertService` requires deployment environment variables (`OPS_ALERT_WEBHOOK_URL` / Telegram bot tokens) to deliver real-time incident notifications.
7. **[P2 Multi-Tenant] Auto-Fix Domain Ownership Check (`app/api/v1/auto_fix.py`):** `apply_auto_fix` verifies user tier but does not validate that `domain_name` exists in `monitored_domains` owned by the user.
8. **[P3 Billing] Documentation & Pricing Tier Discrepancy:** `billing.py` docstrings quote $29/$79/$199 while codebase and landing page execute $9/$29/$79/$199.
9. **[P3 Database] Time-Series Table Archival Strategy:** `reputation_checks` and `dns_audit_logs` lack monthly range partitioning, posing a query latency risk at $100\times$ scale.
10. **[P3 Disaster Recovery] Unverified Physical Database Restore Drill:** Point-in-time recovery and database failover drills remain theoretical and unverified by live operational tests.

---

## Top 10 Next Actions (Ordered by Risk & Dependency)

1. **Action 1 (Fix SEC-01):** Remove `settings.SUPABASE_KEY` from `secret_candidates` in `backend/app/core/security.py` so only `SUPABASE_JWT_SECRET` is used for symmetric decoding.
2. **Action 2 (Fix SEC-02):** Connect `backend/app/services/dns/auto_fixer.py` to `public.dns_provider_credentials` using Fernet symmetric encryption for durable database storage.
3. **Action 3 (Fix SEC-03):** Update `backend/app/services/shopify/shopify_service.py` to persist processed webhook IDs in `public.processed_webhook_events`.
4. **Action 4 (Fix SEC-04 & SEC-05):** Tighten CORS regex in `backend/app/main.py` to explicit production domain names and remove `"*"` from `allowed_hosts`.
5. **Action 5 (Fix SEC-07):** Add domain ownership verification in `backend/app/api/v1/auto_fix.py` ensuring `domain_name` belongs to `user_id` before dispatching remediation.
6. **Action 6 (Provision Alerting):** Inject production Slack/Discord webhook URL and Telegram bot credentials into deployment environment variables (`OPS_ALERT_WEBHOOK_URL`, `OPS_ALERT_TELEGRAM_BOT_TOKEN`).
7. **Action 7 (Harmonize Pricing Docs):** Align docstring references in `backend/app/api/v1/billing.py` with official $9/$29/$79/$199 pricing.
8. **Action 8 (Execute DR Drill):** Execute a staged point-in-time recovery drill on a Supabase database branch to verify RTO/RPO metrics.
9. **Action 9 (Implement Partitioning):** Author a database migration establishing range partitioning for `reputation_checks` and `dns_audit_logs` ahead of high-volume customer onboarding.
10. **Action 10 (Submit Shopify App):** Complete Shopify Partner Dashboard listing configuration and initiate Shopify App Store technical review.
