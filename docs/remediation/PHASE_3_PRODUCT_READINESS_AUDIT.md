# Phase 3 Product Readiness Audit: InboundCheck Enterprise Platform

**Document Version:** 3.0.0-AUDIT
**Date:** September 24, 2026
**Auditor:** Principal Enterprise Security Architect, Cloud Operations & Reliability Commander
**Scope:** Comprehensive Read-Only Audit across 6 Product Readiness Domains
**Target Repository:** InboundCheck (Transactional Email Deliverability & DNS Governance)
**Git HEAD Commit:** `dea5fe6` ("fix: harden failover worker lease recovery")

---

## A. Executive Verdict

### **VERDICT: READY WITH BLOCKERS**

### Executive Summary
The InboundCheck platform demonstrates institutional-grade engineering across core diagnostic algorithms, cryptographic HMAC verification, anti-SSRF defenses, multi-resolver DNS evaluation, and recent operational hardening (OPS-01 rate limiter exemptions, OPS-02 Telegram ops incident dispatch, and OPS-03 lease-based failover recovery with 236/236 passing backend tests).

However, **production launch cannot proceed immediately** due to **two high-severity blockers** and **one major architectural persistence defect**:
1. **[P0 BLOCKER] Direct Client Privilege Escalation via Supabase RLS:** The PostgreSQL RLS update policy on `public.profiles` lacks column-level write restrictions or trigger validation. Any authenticated tenant can issue an arbitrary `UPDATE` query via the browser Supabase client (using the public anon key and their JWT) to change their own `subscription_tier` to `'enterprise'` and `subscription_status` to `'active'`, completely bypassing all Stripe and Shopify paywalls.
2. **[P1 BLOCKER] Missing Shopify Subscription Lifecycle Webhooks:** The platform implements Shopify billing creation and approval callbacks, but fails to implement or subscribe to `app_subscriptions/update` and `app/uninstalled` webhooks. If a merchant cancels or pauses their plan via Shopify Admin, InboundCheck is never notified, resulting in indefinite free access to paid tiers.
3. **[P1 BLOCKER] Volatile In-Memory DNS Auto-Fixer Persistence:** `DNSAutoFixerService` persists tenant DNS credentials and remediation history in module-level in-memory dictionaries (`_mock_provider_creds` and `_mock_auto_fix_logs`) rather than database tables (`dns_provider_credentials` and `dns_auto_fix_logs`), causing credential and log loss across server restarts and cross-container multi-pod deployments.

Once these blockers are remediated, the platform will be fully production-ready.

---

## B. Structured Findings (P0 — P3)

### Summary of Findings by Severity
| Severity | Count | Blockers | Status |
|---|---|---|---|
| **P0 (Critical)** | 1 | Yes | Immediate Remediation Required |
| **P1 (High)** | 2 | Yes | Remediation Required Before Launch |
| **P2 (Medium)** | 3 | No | Warning / Operational Debt |
| **P3 (Low)** | 2 | No | Informational / Best Practice |

---

### Finding P3-AUD-01: Direct Client Privilege Escalation on `public.profiles` (P0 — Critical)
- **ID:** `P3-AUD-01`
- **Severity:** `P0` (Release Blocker)
- **File & Line:**
  - `supabase/migrations/20260909000002_performance_and_idempotency_hardening.sql:38-41`
  - `supabase/migrations/20260903000001_complete_production_schema.sql:370-373`
- **Exact Root Cause:**
  The Row Level Security (RLS) `UPDATE` policy for `public.profiles` is defined as:
  ```sql
  CREATE POLICY "Users can update their own profile"
      ON public.profiles FOR UPDATE
      USING ((SELECT auth.uid()) = id);
  ```
  PostgreSQL RLS `USING` clauses restrict *which rows* can be targeted, but do NOT restrict *which columns* can be updated. Because no column-level privileges (`REVOKE UPDATE ... FROM authenticated`) or `BEFORE UPDATE` trigger guards exist, any authenticated client possessing a valid Supabase JWT can modify all non-generated columns on their profile record.
- **Evidence:**
  1. In `frontend/src/lib/supabase/client.ts`, the frontend initializes the standard Supabase browser client with `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
  2. Any tenant can run the following snippet in their browser console:
     ```javascript
     const { data, error } = await supabase
       .from('profiles')
       .update({
         subscription_tier: 'enterprise',
         tier: 'enterprise',
         subscription_status: 'active'
       })
       .eq('id', user.id);
     ```
  3. In `backend/app/core/tier_guards.py:139`, the backend queries `profiles` via `supabase_service.get_user_profile(user_id)` and reads `prof.get("subscription_tier") or prof.get("tier") or "starter"`.
  4. In `backend/app/api/v1/domains.py:70`, domain monitoring limits (`TIER_LIMITS`) evaluate directly against this database column.
- **Production Impact:**
  Complete commercial circumvention. 100% of non-paying users can escalate their account to Enterprise tier with 0 payment, bypassing Stripe and Shopify checkouts and exhausting system resources with unlimited domains and automated scans.
- **Recommended Remediation:**
  Apply a database migration adding a protective `BEFORE UPDATE` PostgreSQL trigger function that forbids modifying billing-related columns unless the database caller holds the `service_role` role:
  ```sql
  CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()
  RETURNS TRIGGER AS $$
  BEGIN
    IF (NEW.subscription_tier IS DISTINCT FROM OLD.subscription_tier OR
        NEW.tier IS DISTINCT FROM OLD.tier OR
        NEW.subscription_status IS DISTINCT FROM OLD.subscription_status OR
        NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id OR
        NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id OR
        NEW.shopify_charge_id IS DISTINCT FROM OLD.shopify_charge_id OR
        NEW.trial_ends_at IS DISTINCT FROM OLD.trial_ends_at) THEN
      IF (current_setting('request.jwt.claim.role', true) != 'service_role' AND
          current_user != 'postgres') THEN
        RAISE EXCEPTION 'Unauthorized: Billing columns can only be modified by backend service role.';
      END IF;
    END IF;
    RETURN NEW;
  END;
  $$ LANGUAGE plpgsql SECURITY DEFINER;

  CREATE TRIGGER trg_protect_profile_billing_columns
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.protect_profile_billing_columns();
  ```

---

### Finding P3-AUD-02: Missing Shopify Subscription Lifecycle Webhooks (`app_subscriptions/update`) (P1 — High)
- **ID:** `P3-AUD-02`
- **Severity:** `P1` (Release Blocker)
- **File & Line:** `backend/app/api/v1/shopify.py:431-613`
- **Exact Root Cause:**
  `backend/app/api/v1/shopify.py` implements handlers for `orders/create`, `customers/data_request`, `customers/redact`, and `shop/redact`. It does **not** implement webhook endpoints for Shopify's `app_subscriptions/update` or `app/uninstalled` topics.
- **Evidence:**
  1. Grepping `backend/app/api/v1/shopify.py` reveals zero routes handling `app_subscriptions/update`.
  2. In contrast, `backend/app/services/billing/stripe_service.py:555-609` explicitly handles `customer.subscription.deleted` and `customer.subscription.updated` to downgrade users to `'starter'` and `'canceled'`.
  3. When a merchant modifies their subscription (cancels, declines payment, or changes plan) directly within Shopify Admin or uninstalls the app, no webhook is ingested by InboundCheck.
- **Production Impact:**
  Revenue leakage and orphan active tiers. Canceled or downgraded Shopify merchants retain paid status indefinitely in `public.profiles.subscription_status = 'active'`, allowing continued consumption of high-tier features without ongoing Shopify billing charges.
- **Recommended Remediation:**
  1. Add route `POST /api/v1/shopify/webhooks/app_subscriptions/update` in `shopify.py`.
  2. Verify HMAC-SHA256 signature and timestamp tolerance via existing `shopify_service.verify_webhook_hmac()`.
  3. Parse the subscription status from the webhook payload: if `status` is `CANCELLED`, `EXPIRED`, `DECLINED`, or `FROZEN`, downgrade the profile via `supabase_service.update_user_profile(user_id, {"subscription_tier": "starter", "tier": "starter", "subscription_status": "canceled"})`.
  4. Subscribe to `app_subscriptions/update` and `app/uninstalled` in the Shopify partner dashboard and during OAuth registration.

---

### Finding P3-AUD-03: DNS Auto-Fixer Credentials & Execution Logs Stored in Volatile In-Memory Dicts (P1 — High)
- **ID:** `P3-AUD-03`
- **Severity:** `P1` (Release Blocker)
- **File & Line:** `backend/app/services/dns/auto_fixer.py:19-48, 56-120, 164, 240-271`
- **Exact Root Cause:**
  `DNSAutoFixerService` stores all provider credentials in `_mock_provider_creds: Dict[str, Dict[str, Any]]` and all remediation execution history in `_mock_auto_fix_logs: Dict[str, List[Dict[str, Any]]]`. It never executes read/write queries to the database tables `dns_provider_credentials` or `dns_auto_fix_logs`.
- **Evidence:**
  1. In `backend/app/services/dns/auto_fixer.py:58-59`:
     ```python
     def get_credentials(self, user_id: str) -> Dict[str, Any]:
         if user_id in _mock_provider_creds:
             return _mock_provider_creds[user_id]
     ```
  2. In `backend/app/services/dns/auto_fixer.py:164`:
     ```python
     headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"}
     ```
     `apply_dns_fix()` uses the server's global fallback environment variable `settings.CLOUDFLARE_API_TOKEN` instead of the merchant's saved credentials.
  3. Migration `20260903000001_complete_production_schema.sql:205-235` created tables `dns_provider_credentials` and `dns_auto_fix_logs`, but the Python service layer completely ignores them.
- **Production Impact:**
  In a multi-worker production environment (e.g. Uvicorn with multiple workers, or multi-container Kubernetes/Docker deployments), tenant credentials configured on Worker A are unavailable on Worker B. Server restarts or deployments instantly wipe all tenant credentials and auto-fix audit logs.
- **Recommended Remediation:**
  1. Integrate `supabase_service` into `DNSAutoFixerService` to persist encrypted credentials into `public.dns_provider_credentials` using `FernetCredentialVault`.
  2. Write all auto-fix execution records and snapshots into `public.dns_auto_fix_logs`.
  3. Update `apply_dns_fix()` to decrypt and use the merchant's tenant-specific Cloudflare API token rather than the server-wide default token.

---

### Finding P3-AUD-04: Overly Permissive CORS Origin Regex in Production (P2 — Medium)
- **ID:** `P3-AUD-04`
- **Severity:** `P2` (Warning)
- **File & Line:** `backend/app/main.py:172-179`
- **Exact Root Cause:**
  FastAPI CORS middleware is configured with:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=cors_origins,
      allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.up\.railway\.app|http://localhost:\d+",
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Evidence:**
  `allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.up\.railway\.app|http://localhost:\d+"` matches *every single domain* hosted on Vercel or Railway (e.g. `https://attacker-domain.vercel.app`). Because `allow_credentials=True`, an attacker deploying a malicious site to Vercel can make credentialed cross-origin requests to the InboundCheck API.
- **Production Impact:**
  Cross-Site Request Forgery (CSRF) or cross-origin data exposure risks for any endpoint relying on ambient credentials (cookies or basic auth). While Bearer token headers mitigate some CSRF vectors, permissive regex violates production defense-in-depth principles.
- **Recommended Remediation:**
  Tighten `allow_origin_regex` to match only the organization's specific Vercel deployment slugs:
  ```python
  allow_origin_regex = r"https://inbound-check(-[a-z0-9]+)?\.vercel\.app|http://localhost:\d+"
  ```

---

### Finding P3-AUD-05: Lack of Background Worker Heartbeat / Liveness Socket (P2 — Medium)
- **ID:** `P3-AUD-05`
- **Severity:** `P2` (Warning)
- **File & Line:** `backend/app/workers/runner.py:1-72`
- **Exact Root Cause:**
  Dedicated background worker processes (`python -m app.workers.runner audit|failover|all`) execute an async infinite loop without writing an operational heartbeat timestamp to Supabase or exposing a local liveness port/file.
- **Evidence:**
  In `backend/app/workers/runner.py`, worker execution is bounded only by `stop_event` on SIGINT/SIGTERM. If an unhandled thread starvation, async event loop deadlock, or persistent network timeout occurs, the worker process remains running in OS process tables while failing to process queues.
- **Production Impact:**
  Container orchestrators (Docker Compose `healthcheck`, Kubernetes liveness probes) have no mechanism to distinguish between a healthy idle worker and a deadlocked zombie worker, preventing automated pod restarts.
- **Recommended Remediation:**
  Implement a lightweight worker heartbeat mechanism:
  1. Worker touches a local healthfile `/tmp/worker_heartbeat` or updates a row in `public.worker_status` every iteration.
  2. Add Docker Compose healthcheck verifying heartbeat file mtime `< 60s`.

---

### Finding P3-AUD-06: Incomplete Backend `.env.example` Documentation (P2 — Medium)
- **ID:** `P3-AUD-06`
- **Severity:** `P2` (Warning)
- **File & Line:** `backend/.env.example:1-26` vs `backend/app/core/config.py:1-82`
- **Exact Root Cause:**
  `backend/.env.example` lists only 11 baseline variables and omits all V3 and Phase 4 configuration settings introduced in `config.py`.
- **Evidence:**
  The following active configuration settings defined in `backend/app/core/config.py` are completely absent from `backend/.env.example`:
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (OPS-02 Alerting)
  - `CLOUDFLARE_API_TOKEN`, `GODADDY_API_KEY`, `GODADDY_API_SECRET` (DNS Remediation)
  - `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL_NAME` (AI Content Lab)
  - `POSTMARK_WEBHOOK_SECRET`, `SENDGRID_WEBHOOK_VERIFICATION_KEY`, `MAILGUN_WEBHOOK_SIGNING_KEY`, `SES_WEBHOOK_SECRET`, `KLAVIYO_WEBHOOK_SECRET` (ESP Delivery Failure Ingestion)
  - `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_GROWTH`, `STRIPE_PRICE_AGENCY`, `STRIPE_PRICE_ENTERPRISE`
  - `RUN_IN_PROCESS_SCHEDULER`
- **Production Impact:**
  High risk of deployment failure or misconfiguration during infrastructure provisioning. Missing keys lead to silent fallbacks, broken alerts, or rejected webhooks.
- **Recommended Remediation:**
  Update `backend/.env.example` with sanitized template entries for every variable defined in `app.core.config.Settings`.

---

### Finding P3-AUD-07: GoDaddy DNS Auto-Remediation Is Pure Simulation (P3 — Low)
- **ID:** `P3-AUD-07`
- **Severity:** `P3` (Informational)
- **File & Line:** `backend/app/services/dns/auto_fixer.py:210-239`
- **Exact Root Cause:**
  While Cloudflare remediation executes real HTTP calls against `api.cloudflare.com/client/v4/zones/...`, the GoDaddy provider branch is hardcoded to simulate success without making outbound HTTP calls to `api.godaddy.com/v1/domains/...`.
- **Evidence:**
  In `backend/app/services/dns/auto_fixer.py:212-218`:
  ```python
  elif clean_provider == "godaddy":
      applied = True
      status = "applied"
      logger.info(f"Simulated GoDaddy DNS record creation for {host} (dev/test mode)")
  ```
- **Production Impact:**
  GoDaddy merchants clicking "Auto-Fix DNS" receive a successful response in the UI, but no real DNS records are inserted into their GoDaddy DNS zone.
- **Recommended Remediation:**
  Implement the real GoDaddy REST API integration (`PUT https://api.godaddy.com/v1/domains/{domain}/records/{type}/{name}`) using credentials stored in `dns_provider_credentials`, or mark GoDaddy in UI as "Manual Step / Guided Setup" until the API adapter is completed.

---

### Finding P3-AUD-08: Complete Absence of Frontend Test Framework (P3 — Low)
- **ID:** `P3-AUD-08`
- **Severity:** `P3` (Informational / Quality Gate)
- **File & Line:** `frontend/package.json:5-10`
- **Exact Root Cause:**
  `frontend/package.json` contains no test runner, test framework (Jest, Vitest, Playwright, Cypress), or test script.
- **Evidence:**
  The `scripts` object only contains `"dev"`, `"build"`, `"start"`, `"lint"`. Zero `.test.tsx` or `.spec.ts` files exist in `frontend/src/`.
- **Production Impact:**
  Frontend quality assurance depends entirely on Next.js compile-time type checking (`next build`). Regressions in client-side state handling, paywall modal display triggers, or auth cookie handling can only be caught via manual browser testing.
- **Recommended Remediation:**
  Install `@testing-library/react` and `vitest`, and configure CI to execute frontend component and hook tests alongside `npm run build`.

---

## C. Exhaustive Audit Breakdown by Area

### 1. BILLING & ENTITLEMENTS

#### 1.1 Shopify Subscription Lifecycle
- **Status:** Partially Implemented / Blocker
- **Findings:**
  - **Plan Creation & Initiation:** `ShopifyBillingService.create_subscription()` (`backend/app/services/shopify/shopify_billing_service.py:43-143`) correctly constructs GraphQL `appSubscriptionCreate` mutations targeting Shopify Admin API (`2024-04`) with verified pricing tiers ($19 Starter, $49 Growth, $149 Agency, $299 Enterprise).
  - **Approval Callback:** `GET /api/v1/shopify/billing/callback` (`backend/app/api/v1/shopify.py:210-368`) enforces a 6-gate validation pipeline:
    - Gate 1: Nonce verification
    - Gate 2: HMAC signature check
    - Gate 3: Live GraphQL subscription node query (`verify_and_activate_subscription`)
    - Gate 4: Active status validation (`sub_status == "ACTIVE"`)
    - Gate 5: Plan tier binding
    - Gate 6: Supabase profile persistence (`subscription_tier`, `subscription_status = 'active'`)
  - **Cancellation & Expiration Handling:** **MISSING (P1 Blocker - Finding P3-AUD-02)**. Shopify's `app_subscriptions/update` webhook is neither registered nor handled. When a merchant cancels a subscription in Shopify Admin, InboundCheck never downgrades the user.

#### 1.2 Stripe Subscription Lifecycle
- **Status:** Verified Safe
- **Findings:**
  - **Checkout Session:** `StripeBillingService.create_checkout_session()` creates Stripe Checkout sessions with `client_reference_id = user_id`, `metadata.user_id`, and `metadata.subscription_tier`.
  - **Customer Portal:** `create_portal_session()` securely generates Stripe billing management portal URLs.
  - **Webhook Processing:** Handled in `backend/app/services/billing/stripe_service.py:455-645`:
    - `checkout.session.completed`: Sets profile `subscription_tier` and `subscription_status = 'active'`.
    - `customer.subscription.deleted`: Downgrades profile `subscription_tier = 'starter'`, `subscription_status = 'canceled'`.
    - `customer.subscription.updated`: Accurately handles `canceled`, `unpaid`, `active`, `past_due`, and `trialing` states, updating `current_period_end` and `subscription_tier`.
  - **Webhook Authorization:** Enforces HMAC signature via `stripe.Webhook.construct_event(body, sig_header, secret)` with 1MB payload ceiling and replay protection via table `stripe_events`.

#### 1.3 Privilege-Escalation Paths & Tier Writes
- **Status:** **CRITICAL VULNERABILITY (P0 Blocker - Finding P3-AUD-01)**
- **Findings:**
  - **Backend API Routes:** Safe. `PUT /api/v1/settings/profile` accepts only `full_name`, `email`, and `company_name`. `UpdateProfileRequest` schema does not permit writing `subscription_tier` or `subscription_status`.
  - **Direct Supabase RLS:** **UNSAFE**. `public.profiles` RLS `UPDATE` policy (`USING ((SELECT auth.uid()) = id)`) does not restrict columns. Any authenticated user can execute client-side `supabase.from('profiles').update({ subscription_tier: 'enterprise' })` to self-grant Enterprise status.

---

### 2. ONBOARDING & TENANT INITIALIZATION

#### 2.1 Signup → Login → Dashboard
- **Status:** Verified Safe
- **Findings:**
  - **Authentication Mechanism:** Driven by Supabase SSR Auth (`@supabase/ssr`). Passwords and user records reside in `auth.users`.
  - **Route Protection:** Next.js Edge Middleware (`frontend/src/lib/supabase/middleware.ts:60-93`) intercepts all `/dashboard/*` requests, validating cookies fail-closed and redirecting unauthenticated visitors to `/auth/login`.
  - **Tenant Initialization Trigger:** Migration `20260904000001_fix_handle_new_user_trigger.sql` deploys `public.handle_new_user()` `AFTER INSERT ON auth.users`:
    - Generates secure random API key (`ic_live_...`).
    - Seeds default profile with `tier = 'starter'`, `subscription_tier = 'starter'`, `subscription_status = 'trialing'`, `trial_ends_at = NOW() + INTERVAL '3 days'`.
    - Shielded with `SECURITY DEFINER` and fixed `search_path = public, extensions, pg_temp`.

#### 2.2 Zero-State Behavior & Mock/Demo Data
- **Status:** Verified Safe
- **Findings:**
  - **Clean Zero-State:** In `frontend/src/app/dashboard/page.tsx:915-970`, when a tenant has 0 monitored domains, the UI renders a professional empty-state hero ("No Monitored Stores Connected") offering two explicit actions:
    1. "Simulate Audit with Demo Store"
    2. "Add Your Store Domain"
  - **Demo Data Isolation:** Demo constants (`DEMO_STORE_RECORD`, `DEMO_REVENUE_RISK`) are strictly isolated behind client-side state `isDemoActive: boolean` (`frontend/src/app/dashboard/page.tsx:239`).
  - **Zero Leakage:** No demo records are sent to or stored in backend databases. Exiting demo mode or clicking delete on the demo store immediately restores empty zero-state (`frontend/src/app/dashboard/page.tsx:502-504`).

---

### 3. CORE PRODUCT FLOWS

#### 3.1 Shopify Store Connection
- **Status:** Verified Safe
- **Findings:**
  - **OAuth Workflow:** Implemented in `backend/app/api/v1/shopify.py:65-205`. Validates HMAC signature on query parameters, enforces single-use state nonce (stored in-memory with 10-minute TTL), exchanges temporary authorization code for offline access token, and creates record in `public.shopify_stores`.
  - **Credential Security:** Access tokens are encrypted using `FernetCredentialVault` before persistence.

#### 3.2 Domain Addition & Onboarding
- **Status:** Verified Safe
- **Findings:**
  - Implemented in `POST /api/v1/domains` (`backend/app/api/v1/domains.py:60-120`).
  - Enforces tier domain limits (`starter`: 1, `growth`: 3, `agency`: 10, `enterprise`: unlimited).
  - Validates domain syntax, normalizes casing, and invokes initial multi-resolver DNS audit.
  - Inserts into `public.monitored_domains` with `user_id = current_user_id`.

#### 3.3 DNS Verification & Inspection Engine
- **Status:** Verified Safe
- **Findings:**
  - Multi-resolver asynchronous DNS evaluation in `backend/app/services/dns/diagnostic_engine.py`.
  - Checks SPF syntax, lookup limits (RFC 7208 10-lookup cap), DKIM CNAME/TXT selectors, DMARC alignment (`p=quarantine/reject`), BIMI SVG validation, and MX records.
  - **Anti-SSRF Protection:** Enforced by `_clean_domain()`. Resolves host IP and verifies that it does not collide with loopback (`127.0.0.0/8`), private RFC 1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), or AWS metadata (`169.254.169.254`).

#### 3.4 Blacklist (RBL) Radar Scan
- **Status:** Verified Safe
- **Findings:**
  - Probes 10 authoritative RBLs concurrently via `asyncio.gather()` with timeout shielding in `backend/app/services/dns/rbl_scanner.py`.
  - Rate-limited per tier via `rate_limit_rbl_tier` dependency.
  - Results stored in `public.rbl_scan_results`.

#### 3.5 Automated DNS Remediation
- **Status:** **UNSAFE (P1 Blocker - Finding P3-AUD-03 & Finding P3-AUD-07)**
- **Findings:**
  - Cloudflare execution path fails closed on API error (OPS-04 hardened).
  - However, credentials and auto-fix logs are held in volatile in-memory dicts rather than database tables.
  - GoDaddy execution path is simulated rather than executing real DNS changes.

#### 3.6 Continuous Monitoring & Worker Pipeline
- **Status:** Verified Safe
- **Findings:**
  - Audit worker (`backend/app/workers/audit_worker.py`) queries domains due for audit, processes scans, and updates `monitored_domains`.
  - Failover worker (`backend/app/workers/failover_worker.py`) executes transactional fallback dispatch via WhatsApp/SMS with lease-based claim recovery (OPS-03 hardened).

---

### 4. PRODUCTION CONFIGURATION

| Category | Parameter | Source | Production Status |
|---|---|---|---|
| **App Core** | `PROJECT_NAME` | `config.py:6` | `InboundCheck API` |
| | `ENVIRONMENT` | `config.py:8` | Needs `"production"` in deployment |
| | `API_V1_STR` | `config.py:7` | `/api/v1` |
| | `FRONTEND_URL` | `config.py:9` | Must match Vercel production URL |
| **CORS** | `ALLOWED_ORIGINS` | `main.py:155` | Defined; Warning on broad regex (Finding P3-AUD-04) |
| **Supabase** | `SUPABASE_URL` | `config.py:20` | Required |
| | `SUPABASE_KEY` | `config.py:21` | Required (Public anon key) |
| | `SUPABASE_SERVICE_ROLE_KEY` | `config.py:24` | Required (Admin key) |
| | `SUPABASE_JWT_SECRET` | `config.py:25` | Required (HS256 JWT signature verification) |
| **Shopify** | `SHOPIFY_API_KEY` | `config.py:29` | Required |
| | `SHOPIFY_API_SECRET` | `config.py:30` | Required (HMAC signature verification) |
| **Stripe** | `STRIPE_SECRET_KEY` | `config.py:33` | Required |
| | `STRIPE_PUBLISHABLE_KEY` | `config.py:34` | Required |
| | `STRIPE_WEBHOOK_SECRET` | `config.py:35` | Required (HMAC webhook validation) |
| | `STRIPE_PRICE_*` | `config.py:36-39` | Standard tier Price IDs |
| **DNS Provider** | `CLOUDFLARE_API_TOKEN` | `config.py:51` | Required for fallback Cloudflare auto-fix |
| | `GODADDY_API_KEY` / `SECRET` | `config.py:52-53` | Configured |
| **Alerting** | `TELEGRAM_BOT_TOKEN` | `config.py:47` | Required for OPS-02 Incident Alerts |
| | `TELEGRAM_CHAT_ID` | `config.py:48` | Target Ops Incident Channel |
| **ESP Webhooks** | `POSTMARK_WEBHOOK_SECRET` | `config.py:59` | Required for Postmark delivery failures |
| | `SENDGRID_WEBHOOK_VERIFICATION_KEY` | `config.py:60` | Required for SendGrid ECDSA signatures |
| | `MAILGUN_WEBHOOK_SIGNING_KEY` | `config.py:61` | Required for Mailgun HMAC signatures |
| | `SES_WEBHOOK_SECRET` | `config.py:62` | Required for SES delivery failures |
| | `KLAVIYO_WEBHOOK_SECRET` | `config.py:63` | Required for Klaviyo webhook verification |

*(Note: In compliance with instructions, no actual secret values or live credentials are printed.)*

---

### 5. OBSERVABILITY & OPERATIONAL RELIABILITY

#### 5.1 Health & Readiness Endpoints
- **Status:** Verified Safe (OPS-01 Hardened)
- **Findings:**
  - `GET /ready` (`backend/app/main.py:108`): Verifies database connectivity fail-closed (`SELECT 1`). Returns HTTP 200 `{"status": "ready"}` or HTTP 503 `{"status": "unhealthy", "database": "disconnected"}`.
  - `GET /api/v1/health` (`backend/app/main.py:126`): Verifies API engine liveness.
  - **Exemption:** Both endpoints are explicitly excluded from `RateLimitingMiddleware` to prevent false-positive uptime monitor failures.

#### 5.2 Worker Health & Queue Recovery
- **Status:** Verified Safe (OPS-03 Hardened)
- **Findings:**
  - `FailoverWorker` utilizes Postgres atomic lease claiming via `claim_pending_delivery_failure_events(worker_id, limit, lease_interval)`.
  - If a worker crashes mid-processing, leases expire after 30 seconds (`claim_lease_seconds = 30`), allowing surviving workers to safely reclaim events without duplicate delivery.
  - Graceful shutdown handles `SIGINT`/`SIGTERM` by invoking `release_claimed_delivery_failure_event()` to immediately free in-flight items.
  - **Minor Warning:** Worker lacks a dedicated liveness heartbeat socket (Finding P3-AUD-05).

#### 5.3 Operational Alerting
- **Status:** Verified Safe (OPS-02 Hardened)
- **Findings:**
  - `OpsAlertService` (`backend/app/services/alerting/ops_alert_service.py`) dispatches real-time incident notifications to the internal Telegram operations channel for P0/P1 incidents (database outages, webhook HMAC failures, worker exhaustion).
  - Sanitizes sensitive tokens/keys in incident payloads via regex.
  - Dispatches non-blockingly via `asyncio.create_task()`.
  - Enforces in-memory alert deduplication and rate throttling (60-second cooldown per `alert_id`).

#### 5.4 Error Handling & Information Leakage
- **Status:** Verified Safe
- **Findings:**
  - `backend/app/main.py:182-212` implements global exception shields for `StarletteHTTPException` and generic `Exception`.
  - Database failures emit opaque error responses (`"Database service is temporarily unavailable"`) with a unique `ref_id` UUID for internal log correlation, preventing database error messages or internal schema names from leaking to end users.
  - Sanitization filters scrub `token=`, `key=`, `secret=`, and `bearer` patterns from logs.

---

### 6. TEST COVERAGE AUDIT

The backend contains **29 test suites** with **236 passing automated tests** (verified in test execution log). Below is the exact mapping of existing automated tests across the audited functional domains:

| Audit Functional Domain | Existing Automated Test Suites | Test Count & Status |
|---|---|---|
| **Stripe Billing & Subscriptions** | `test_billing.py`<br>`test_billing_and_security.py` | 15 Tests (All Passing) |
| **Shopify Billing & Verification** | `test_shopify_billing.py`<br>`test_shopify_billing_security.py`<br>`test_shopify_compliance.py` | 28 Tests (All Passing) |
| **Authentication & JWT Security** | `test_jwt_security.py`<br>`test_p0_security_remediation.py` | 24 Tests (All Passing) |
| **Core DNS Diagnostics & Scorer** | `test_dns_diagnostic.py`<br>`test_spf_merge_engine.py` | 18 Tests (All Passing) |
| **Monitored Domains Registry** | `test_domains_api.py` | 6 Tests (All Passing) |
| **Blacklist Radar (RBL)** | `test_rbl_api.py`<br>`test_rbl_scanner.py` | 14 Tests (All Passing) |
| **Predictive Revenue & Dispute Risk**| `test_revenue_risk.py` | 8 Tests (All Passing) |
| **Delivery Failure Ingestion** | `test_delivery_failure_ingestion.py`<br>`test_failover_webhooks.py`<br>`test_step6_schema_and_webhooks.py`| 32 Tests (All Passing) |
| **Failover Worker & Lease Claims** | `test_failover_worker_step5.py`<br>`test_audit_leases.py`<br>`test_p1_operational_remediation.py` | 38 Tests (All Passing) |
| **Operational Health & Rate Limiting**| `test_scheduler_and_alerts.py`<br>`test_workers.py`<br>`test_safe_http_fetcher.py` | 26 Tests (All Passing) |
| **Database Persistence & Seed** | `test_persistence_defects.py`<br>`test_seed_verifier.py` | 16 Tests (All Passing) |
| **V3 Roadmap Endpoints** | `test_v3_roadmap.py` | 11 Tests (All Passing) |
| **Total Automated Tests** | **29 Test Files** | **236 Passed, 0 Failed (100%)** |

---

## D. Categorized Summary Lists

### 1. Verified Safe Areas
- [x] **Supabase JWT Authentication:** Verified asymmetric/HMAC signature parsing, role extraction, and automatic token expiry rejection (`app.core.security`).
- [x] **Edge Middleware Route Guard:** Next.js fail-closed `/dashboard/*` redirection for unauthenticated visitors.
- [x] **Stripe Subscription Webhook Lifecycle:** `checkout.session.completed`, `customer.subscription.deleted`, and `customer.subscription.updated` handlers with replay idempotency and HMAC validation.
- [x] **Shopify OAuth Integration:** State nonce validation, HMAC signature checks, and access token encryption.
- [x] **Shopify Billing Activation Callback:** Multi-gate live GraphQL node query and plan binding.
- [x] **Anti-SSRF Domain Guard:** Strict subnet resolution validation blocking private RFC 1918, loopback, and cloud metadata IPs.
- [x] **DNS Diagnostic Engine:** RFC-compliant evaluation of SPF, DKIM, DMARC, BIMI, and MX records.
- [x] **Blacklist Radar Scanning:** Concurrent, non-blocking RBL query dispatch across 10 authoritative blacklists with tier-based rate limiting.
- [x] **Failover Worker Lease Recovery:** Atomic database leasing (`claim_pending_delivery_failure_events`) with 30-second stale lease recovery and clean shutdown release.
- [x] **Readiness & Health Endpoints:** `/ready` and `/api/v1/health` with rate-limiter exemptions (OPS-01).
- [x] **Ops Incident Alerting:** Telegram dispatch for P0/P1 incidents with credential scrubbing and 60-second cooldown (OPS-02).
- [x] **Information Leakage Shields:** Opaque database 503 error responses with UUID reference correlation IDs.

---

### 2. Blockers (Must Remediate Before Production Launch)
- [ ] **[P0] Supabase RLS Privilege Escalation on `public.profiles` (`P3-AUD-01`):** Direct client-side `UPDATE` statements can modify `subscription_tier` and `subscription_status` without restriction. Requires a `BEFORE UPDATE` trigger function on `public.profiles` blocking updates to billing columns by non-service-role callers.
- [ ] **[P1] Missing Shopify Subscription Update & Cancellation Webhook (`P3-AUD-02`):** Absence of `app_subscriptions/update` webhook handler permits canceled Shopify merchants to retain active paid entitlements indefinitely.
- [ ] **[P1] Volatile In-Memory DNS Auto-Fixer Persistence (`P3-AUD-03`):** `DNSAutoFixerService` stores tenant provider credentials and auto-fix execution logs in memory instead of persisting them to database tables `dns_provider_credentials` and `dns_auto_fix_logs`.

---

### 3. Warnings (Operational Debt & Hardening)
- [ ] **[P2] Overly Permissive CORS Regex (`P3-AUD-04`):** Regex allows all subdomains on `*.vercel.app` and `*.up.railway.app` with `allow_credentials=True`. Should be restricted to project-specific slugs.
- [ ] **[P2] Worker Liveness & Heartbeat Observability (`P3-AUD-05`):** Dedicated worker CLI processes lack healthfile or database heartbeat updates for container orchestrator liveness checks.
- [ ] **[P2] Incomplete `.env.example` Documentation (`P3-AUD-06`):** Missing V3 and Phase 4 environment variables in `backend/.env.example`.
- [ ] **[P3] GoDaddy DNS Auto-Fix Is Simulated (`P3-AUD-07`):** GoDaddy auto-remediation does not call live provider REST APIs.
- [ ] **[P3] Lack of Frontend Component & Integration Tests (`P3-AUD-08`):** `frontend/` has no Vitest/Jest suite for client-side regression prevention.

---

### 4. Missing Tests
The following specific test cases are missing from the test suite:
1. **RLS Column Security Test:** No test currently asserts that an authenticated client JWT fails when executing an `UPDATE public.profiles SET subscription_tier = 'enterprise'`.
2. **Shopify Subscription Cancellation Webhook Test:** No tests exist for Shopify `app_subscriptions/update` or `app/uninstalled` event ingestion.
3. **Database-Backed DNS Auto-Fixer Persistence Test:** Tests currently pass against in-memory dictionaries; no tests verify encryption and retrieval of Cloudflare credentials from `dns_provider_credentials`.
4. **GoDaddy Real Provider API Test:** GoDaddy tests currently only assert mock simulation results.
5. **Frontend Route & Paywall Modal Tests:** Zero automated UI unit/integration tests exist for paywall display triggers or dashboard state changes.

---

## E. Remediation Plan & Sequence

To achieve an unconditional **READY** verdict for production deployment, execute the following 3-step remediation sequence:

1. **Step 1 (P0): Database RLS Billing Shield Migration**
   - Author migration `20260925000001_shield_profile_billing_columns.sql`.
   - Create `BEFORE UPDATE` trigger function `public.protect_profile_billing_columns()` raising an exception if `subscription_tier`, `tier`, `subscription_status`, `stripe_customer_id`, or `trial_ends_at` are altered by anyone other than `service_role`.
   - Write automated pytest in `test_jwt_security.py` verifying client update rejection.

2. **Step 2 (P1): Implement Shopify Subscription Lifecycle Webhook**
   - Add `POST /api/v1/shopify/webhooks/app_subscriptions/update` in `shopify.py`.
   - Validate HMAC signature, parse cancellation/downgrade status, and execute profile tier updates via `supabase_service`.
   - Add test suite in `test_shopify_billing.py` validating cancellation and downgrade handling.

3. **Step 3 (P1): Wire `DNSAutoFixerService` to PostgreSQL Tables**
   - Refactor `DNSAutoFixerService` in `auto_fixer.py` to persist encrypted credentials to `dns_provider_credentials` via `FernetCredentialVault` and append remediation entries to `dns_auto_fix_logs`.
   - Update `apply_dns_fix()` to decrypt and inject the tenant's own Cloudflare API token.
