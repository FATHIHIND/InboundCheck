# Phase 2 Independent Verification

## Executive Result

**PARTIALLY VERIFIED**

### Executive Summary
Phase 2 has significantly enhanced InboundCheck's production resilience: 153/153 backend tests pass (100% green), all 25 frontend routes compile without TypeScript or Webpack errors, and explicit timeouts (5.0s–10.0s) are universally enforced across all outbound HTTP requests. Webhook ingress enforces strict 1MB payload ceilings, HMAC signatures, and ±300s timestamp tolerance windows. Database leases for background workers use PostgreSQL `FOR UPDATE SKIP LOCKED` with explicit expiration recovery.

However, independent adversarial inspection reveals key operational gaps:
1. **Worker Retry Storm on Audit Failure:** When a domain audit fails, `fail_domain_audit` resets `audit_lease_until = NULL` without advancing `last_audited_at`, causing persistently failing domains to be re-claimed every 30 seconds without exponential backoff.
2. **Process-Local Rate Limiting:** Rate limiting is enforced via an in-memory sliding window middleware (120 req/min per IP) without reverse-proxy header evaluation (`X-Forwarded-For`), distributed sync, or endpoint-specific quotas for expensive endpoints.
3. **Alerting Infrastructure is Documented Only:** P0/P1 infrastructure alerting (PagerDuty, dead-man's snitch, worker backlog telemetry) exists as runbook documentation only; no APM, Sentry, or PagerDuty integrations exist in the application code.
4. **Mocked Concurrency in Resilience Tests:** The 9 failure-injection tests validate logic sequentially against in-memory dictionary state rather than generating true concurrent thread/process contention against PostgreSQL.

---

## 1. Worker Reliability
* **Classification:** **VERIFIED IN CODE & DATABASE**
* **Inspection Details:**
  * **Job Creation:** Domains enter monitoring via `supabase_service.create_or_update_domain()` with `is_active = true`.
  * **Job Claiming:** Background workers (`audit_worker.py`, `runner.py`) claim due jobs via `supabase_service.claim_due_domain_audits()` which invokes the PostgreSQL RPC function `public.claim_due_domain_audits`.
  * **State Transitions:**
    * `QUEUED` (`last_audited_at IS NULL` or `last_audited_at <= NOW() - interval`)
    * `CLAIMED` (`audit_lease_owner = worker_id`, `audit_lease_until = NOW() + 15m`, `audit_started_at = NOW()`)
    * `RUNNING` (Auditing DNS diagnostics via `DNSDiagnosticEngine` and RBL probes via `rbl_scanner`)
    * `SUCCESS` (`complete_domain_audit` sets `audit_lease_owner = NULL`, `audit_lease_until = NULL`, `last_audited_at = NOW()`)
    * `FAILURE` (`fail_domain_audit` sets `audit_lease_owner = NULL`, increments `audit_failure_count`)
  * **Crash Recovery:** If a worker terminates abruptly mid-job, the lease remains held until `NOW() > audit_lease_until` (15 minutes). Once expired, `(audit_lease_until IS NULL OR audit_lease_until < NOW())` allows subsequent workers to reclaim the domain.
  * **Graceful Shutdown:** `run_audit_worker` accepts an optional `asyncio.Event` (`stop_event`) and utilizes `asyncio.TaskGroup` for cleanly completing in-flight audits before exiting.

---

## 2. Concurrency Safety
* **Classification:** **VERIFIED IN CODE (PostgreSQL RPC) / PARTIALLY VERIFIED BY TEST**
* **Inspection Details:**
  * **Database Locking:** `public.claim_due_domain_audits` in [`20260912000001_add_audit_leases_and_failover_pipeline.sql`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260912000001_add_audit_leases_and_failover_pipeline.sql#L25-L56) selects candidates using:
    ```sql
    SELECT id FROM public.monitored_domains
    WHERE is_active = true
      AND (last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval)
      AND (audit_lease_until IS NULL OR audit_lease_until < NOW())
    ORDER BY COALESCE(last_audited_at, created_at) ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
    ```
    This guarantees that concurrent workers hitting PostgreSQL lock independent row subsets without blocking or duplicate execution.
  * **Completion Safety:** `complete_domain_audit` and `fail_domain_audit` enforce `WHERE id = p_domain_id AND audit_lease_owner = p_worker_id`. If a slow worker completes an audit after its 15-minute lease expired and another worker has claimed it, the update affects 0 rows, returning `False` and logging `"Lease lost before audit completion"`.
  * **Test Quality Note:** `test_concurrent_workers_claim_disjoint_domains` in `test_phase2_resilience.py` executes two claim calls sequentially against an in-memory dictionary. It does not spawn concurrent threads or hit PostgreSQL simultaneously.

---

## 3. Idempotency
* **Classification:** **PARTIALLY VERIFIED**
* **Inspection Details:**
  * **Stripe Webhook Deduplication:** Uses table `processed_webhook_events` and memory cache via `is_event_processed(event_id)`.
    * *Idempotency Key:* Stripe `event.id` (e.g. `evt_...`).
    * *Deduplication Mechanism:* In-memory dictionary check followed by database query `select("id").eq("id", event_id)`.
    * *Limitation (TOCTOU Race):* `is_event_processed` checks the database, but `mark_event_processed` is called *after* profile updates. Concurrent identical webhook deliveries can both pass the initial check before either writes to `processed_webhook_events`. While end updates (`subscription_tier = "growth"`) are state-idempotent, out-of-order events (`subscription.updated` vs `subscription.deleted`) could overwrite state if processed concurrently.
  * **Shopify Webhook Deduplication:** Uses `X-Shopify-Webhook-Id` header with in-memory set and returns `already_processed` on repeated delivery.
  * **ESP Delivery Failure Ingestion:** In `failover_webhooks.py`, deduplication is strictly enforced by PostgreSQL partial unique index `(esp_provider, provider_event_id)`. Concurrent duplicate webhooks fail closed via `insert_if_absent()`.
  * **Telegram Alert Deduplication:** Enforced by PostgreSQL partial unique index `idx_failover_logs_one_telegram_per_event`, ensuring only 1 Telegram notification is sent per failure event even across worker retries.

---

## 4. Stripe Webhooks
* **Classification:** **VERIFIED IN CODE & BY TEST**
* **Inspection Details:**
  * **Endpoint:** `POST /api/v1/billing/webhook` in [`backend/app/api/v1/billing.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/billing.py#L235-L266).
  * **Signature Verification:** Uses `stripe_service.verify_webhook_signature()`, verifying HMAC-SHA256 signature using `STRIPE_WEBHOOK_SECRET` with `hmac.compare_digest`.
  * **Timestamp Tolerance:** Enforces strict ±300s window on signature header `t=...`. Rejects stale or future timestamps.
  * **Payload Cap:** Enforces 1MB payload ceiling via `Content-Length` header check and body byte measurement (`HTTP 413`).
  * **Duplicate Delivery:** Validated by `test_stripe_webhook_duplicate_delivery_is_idempotent()`, returning `{"status": "already_processed", "idempotent": True}` on redelivery.
  * **Transaction Boundaries:** Does not perform external network calls during webhook handling; updates `profiles` and returns immediately.

---

## 5. Shopify Webhooks
* **Classification:** **VERIFIED IN CODE & BY TEST**
* **Inspection Details:**
  * **Endpoints:**
    * `POST /api/v1/shopify/webhooks/orders` and `/webhooks/orders/create`
    * `POST /api/v1/shopify/webhooks/customers/data_request` (Mandatory GDPR)
    * `POST /api/v1/shopify/webhooks/customers/redact` (Mandatory GDPR)
    * `POST /api/v1/shopify/webhooks/shop/redact` (Mandatory GDPR)
  * **HMAC Verification:** Enforces base64 HMAC-SHA256 signature verification matching `X-Shopify-Hmac-Sha256` header against `SHOPIFY_API_SECRET`.
  * **Timestamp Verification:** `X-Shopify-Triggered-At` header must fall within ±300s. Validated by `test_shopify_webhook_rejects_expired_timestamp()`.
  * **Payload Cap:** Enforces 1MB payload ceiling.
  * **Asynchronous Boundary:** GDPR webhooks acknowledge within milliseconds by offloading handling to FastAPI `BackgroundTasks`.

---

## 6. HTTP Timeouts
* **Classification:** **VERIFIED IN CODE**
* **Inventory of All Outbound HTTP Operations:**

| Component / File | Target Service | Library | Configured Timeout | Classification |
|---|---|---|:---:|:---:|
| `shopify_service.py` | Shopify OAuth / Admin API | `httpx.AsyncClient` | `10.0s` | **SAFE** |
| `shopify_billing_service.py` | Shopify Recurring GraphQL | `httpx.AsyncClient` | `10.0s` | **SAFE** |
| `stripe_service.py` | Stripe Customers / Invoices / Portals | `httpx.AsyncClient` | `10.0s` | **SAFE** |
| `omnichannel_service.py` | Telegram Bot API | `httpx.AsyncClient` | `8.0s` | **SAFE** |
| `auto_fixer.py` | Cloudflare REST v4 API | `httpx.AsyncClient` | `8.0s` | **SAFE** |
| `content_optimizer.py` | External LLM Gateway | `httpx.AsyncClient` | `8.0s` | **SAFE** |
| `safe_http_fetcher.py` | BIMI SVG & VMC Cert Fetchers | `httpx.AsyncClient` | `5.0s` | **SAFE** |
| `diagnostic_engine.py` | Public DNS Resolvers (UDP/TCP) | `dnspython` | `timeout=4.0s`, `lifetime=8.0s` | **SAFE** |
| `rbl_scanner.py` | DNSBL Probes (10 lists) | `dnspython` | `timeout=1.5s`, `lifetime=1.5s` | **SAFE** |
| `frontend/src/lib/api.ts` | Backend API Routes | Browser `fetch` | *Unspecified (browser default)* | **PARTIALLY SAFE** |

* **Finding:** Every backend outbound request has an explicit, bounded timeout. No backend external call can hang a worker indefinitely. The frontend client wrapper (`apiFetch` in `frontend/src/lib/api.ts`) lacks an explicit `AbortSignal.timeout()`.

---

## 7. Retry Safety
* **Classification:** **PARTIALLY VERIFIED (P1 Risk Identified)**
* **Inspection Details:**
  * **Workers / Job Loops:** Neither `audit_worker` nor `failover_worker` uses external retry libraries (`tenacity`, `backoff`).
  * **Audit Worker Retry Mechanism:**
    * In `audit_worker.py`, failure triggers `supabase_service.fail_domain_audit(domain_id, worker_id, error)`.
    * In SQL RPC `public.fail_domain_audit`:
      ```sql
      UPDATE public.monitored_domains
      SET audit_lease_owner = NULL,
          audit_lease_until = NULL,
          audit_failure_count = audit_failure_count + 1,
          last_audit_error = p_error
      WHERE id = p_domain_id AND audit_lease_owner = p_worker_id;
      ```
    * **Root Cause & Production Impact:** When an audit fails, `audit_lease_until` is set to `NULL`, but `last_audited_at` remains unchanged. In `claim_due_domain_audits`, the selection criteria `(last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval) AND (audit_lease_until IS NULL OR audit_lease_until < NOW())` matches the domain immediately on the very next 30-second worker loop.
    * A broken domain will be continuously re-claimed every 30 seconds without exponential backoff or dead-letter state.
  * **Failover Worker Retry Safety:** Safe. Failures transition events to `processing_status = 'failed'`, which removes them from the eligible `received` queue.

---

## 8. Rate Limiting
* **Classification:** **PARTIALLY VERIFIED**
* **Inspection Details:**
  * **Enforced Layer:** `RateLimitingMiddleware` in [`backend/app/main.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L65-L125).
  * **Mechanism:** In-memory sliding window using `defaultdict(list)` tracking client IP with 60-second window and capacity eviction (max 5,000 IPs).
  * **Configured Limit:** 120 requests per 60 seconds per IP.

| Dimension | Documented Status | Actually Enforced Status |
|---|---|---|
| **Global IP Limit** | 120 req / 60s | **Enforced** in `RateLimitingMiddleware` |
| **Distributed Multi-Instance Sync** | Shared rate-limiting | **NOT ENFORCED** (Process-local memory; resets on restart / multiple pods) |
| **Reverse Proxy Real-IP Parsing** | Header evaluation | **NOT ENFORCED** (Uses `request.client.host`; does not parse `X-Forwarded-For`) |
| **Granular Endpoint Quotas** | DNS, AI, RBL limits | **NOT ENFORCED** (Single blanket limit across all routes) |
| **Authentication Route Limits** | Password / login limits | **NOT ENFORCED** (Handled externally by Supabase Auth service) |

---

## 9. Cost Controls
* **Classification:** **VERIFIED IN CODE & DOCUMENTED**
* **Inspection Details:**
  * Documented in [`docs/operations/COST_CONTROL.md`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/docs/operations/COST_CONTROL.md).
  * **DNS Queries:** Public resolvers (`1.1.1.1`, `8.8.8.8`) are free. Domain audit lease interval enforces minimum 1-hour delay between automatic background sweeps.
  * **RBL Queries:** Bounded by `asyncio.Semaphore(10)` and 1.5s per-query timeout in `rbl_scanner.py`. High-volume commercial fees flagged as `UNKNOWN — VERIFY BEFORE PRODUCTION`.
  * **AI Optimization Tokens:**
    * In `ai_content_service`, incoming templates are capped before prompt generation.
    * On LLM timeout or missing API keys, falls back to zero-cost local regex heuristics (`_heuristic_fallback()`).
    * Commercial provider token pricing flagged as `UNKNOWN — VERIFY BEFORE PRODUCTION`.
  * **Telegram Alerting:** Telegram Bot API has zero per-message charges; duplicate dispatch blocked by DB partial unique index.
  * **Webhook Payload Caps:** 1MB ingress ceiling enforced across Stripe, Shopify, and ESP endpoints (`HTTP 413`).

---

## 10. External Provider Resilience
* **Classification:** **VERIFIED BY CODE & TESTS**

| Provider | Operation | Failure Scenario | System Handling | Resilience Status |
|---|---|---|---|:---:|
| **Supabase** | DB Queries | Outage / 503 | `DatabaseUnavailableError` -> HTTP 503 fail-closed | **FAIL-SAFE** |
| **Stripe** | Checkout / Portal | Timeout / 500 | `10.0s` timeout -> Logged, clean HTTP 500 | **FAIL-SAFE** |
| **Shopify** | Recurring Billing | HTTP 502 Bad Gateway | `10.0s` timeout -> Raises `RuntimeError("502")` | **FAIL-SAFE** |
| **Telegram** | Bot Incident Alert | HTTP 500 Error | `8.0s` timeout -> `TelegramDispatchResult(success=False)` | **FAIL-SAFE** |
| **AI LLM Gateway**| Template Analysis | Timeout / Disconnect | `8.0s` timeout -> Instant local regex heuristic fallback | **FAIL-SAFE** |
| **Cloudflare** | DNS Auto-Fix | HTTP 4xx/5xx | `8.0s` timeout -> Catches `RequestError`, logs cleanly | **FAIL-SAFE** |
| **GoDaddy** | DNS Auto-Fix | Unconfigured | Returns simulated payload; no production blast radius | **PARTIALLY SAFE** |
| **DNSBL Servers** | RBL Lookups | Timeout / Drop | `1.5s` timeout -> Marks list as `clean` or `unknown` | **FAIL-SAFE** |

---

## 11. Failure Injection Test Quality
* **Classification:** **VERIFIED BY CODE AUDIT**
* **Inspection of `backend/tests/test_phase2_resilience.py`:**

| Test Name | Modeled Failure Scenario | Strength | Weakness | Production Coverage |
|---|---|---|---|:---:|
| `test_concurrent_workers_claim_disjoint_domains` | Dual workers claiming same jobs | Verifies lease assignment logic | Sequential calls on in-memory state; no OS threads/Postgres concurrency | Moderate (Logic only) |
| `test_worker_crash_and_lease_expiration_recovery` | Worker terminates mid-job | Verifies lease expiration condition | In-memory timestamp manipulation | High (Deterministic logic) |
| `test_stripe_webhook_duplicate_delivery_is_idempotent` | Stripe redelivers same event | Verifies `already_processed` status return | Sequential HTTP calls; does not test concurrent TOCTOU race | High (Protocol level) |
| `test_shopify_order_webhook_duplicate_delivery_is_idempotent` | Shopify redelivers order webhook | Verifies deduplication on `X-Shopify-Webhook-Id` | Sequential delivery; does not test concurrent race | High (Protocol level) |
| `test_ai_content_optimizer_resilience_to_external_llm_timeout` | External LLM endpoint times out | Mocks `httpx.TimeoutException`, asserts heuristic audit score | None (Accurately mirrors LLM gateway downtime) | Full (Production equivalent) |
| `test_telegram_alert_service_resilience_to_telegram_500` | Telegram API returns 500 Internal Error | Verifies error capture without worker crash | None | Full (Production equivalent) |
| `test_shopify_billing_service_handles_shopify_502` | Shopify returns 502 Bad Gateway | Verifies clean `RuntimeError` exception handling | None | Full (Production equivalent) |
| `test_stripe_webhook_rejects_payload_exceeding_1mb` | Oversized webhook payload injection | Verifies HTTP 413 rejection | None | Full (Production equivalent) |
| `test_shopify_webhook_rejects_expired_timestamp` | Replay attack with stale timestamp | Verifies HTTP 400 rejection | None | Full (Production equivalent) |

---

## 12. Database Connections
* **Classification:** **VERIFIED IN CODE**
* **Inspection Details:**
  * **Driver / Client Architecture:** Backend does not maintain persistent direct TCP connection pools via `asyncpg` or `psycopg2`. Instead, `supabase_service` instantiates `create_client()` from `supabase-py`, which communicates over HTTPS via PostgREST.
  * **Connection Pooling:** PostgREST handles pooling via Supabase's managed PgBouncer proxy in transaction mode.
  * **Process Pool Limits:** Python process relies on default `httpx` HTTP connection pool limits (`max_connections=100`, `max_keepalive_connections=20`).
  * **Connection Leak Risk:** Low. Because operations are stateless HTTPS requests, there are no unclosed raw PostgreSQL transaction cursors held open across worker tasks.

---

## 13. Webhook Transaction Boundaries
* **Classification:** **VERIFIED IN CODE**
* **Inspection Details:**
  * **Stripe Webhook (`/api/v1/billing/webhook`):** Validates HMAC -> checks event ID -> updates profile record -> returns. No DNS, RBL, or external API calls are made synchronously.
  * **Shopify Order Webhook (`/api/v1/shopify/webhooks/orders`):** Validates HMAC -> validates timestamp -> marks webhook ID -> returns `HTTP 200` immediately (`{"status": "received"}`). No synchronous scans are executed.
  * **Shopify GDPR Webhooks (`/webhooks/customers/*`):** Validates HMAC -> dispatches processing to FastAPI `BackgroundTasks` -> returns `HTTP 200` in <50ms.
  * **ESP Delivery Failure Webhooks (`/webhook/delivery-failure/*`):** Validates signature -> normalizes payload -> inserts event record -> returns `HTTP 200` in <100ms. Alerts are processed asynchronously by `failover_worker`.

---

## 14. Observability
* **Classification:** **VERIFIED IN CODE**
* **Inspection Details:**
  * **Structured Logging:** Standardized Python logging (`logging.getLogger()`) across workers, routers, and services.
  * **Secret Leak Audit:**
    * In `audit_worker.py`, `sanitize_error()` explicitly scrubs tokens and secrets using regex pattern `r"(token|key|secret|password|bearer)[=:\s]+[A-Za-z0-9_\-\.]+"`.
    * In `env_guard.py`, Stripe keys are masked (`{stripe_key[:7]}...`).
    * Full sensitive webhook payloads are not dumped to stdout in production.
  * **Correlation IDs:**
    * Frontend generates `X-Request-ID` via `crypto.randomUUID()` in `apiFetch`.
    * Backend logs include event IDs (`evt_...`, `sh_hook_...`) and worker UUIDs.

---

## 15. Alerting
* **Classification:** **DOCUMENTED ONLY (Infrastructure) / VERIFIED IN CODE (Deliverability)**
* **Inspection Details:**
  * **Deliverability Alerting (Customer Facing):** **VERIFIED IN CODE**. `alert_dispatcher.py` evaluates health score drops (<70) and RBL listings, dispatching formatted markdown alerts to merchant Telegram channels.
  * **Infrastructure Alerting (`ALERT-DB-OUTAGE`, `ALERT-WORKER-BACKLOG`, etc.):** **DOCUMENTED ONLY**.
    * Grep search across `backend/` reveals **0 instances** of PagerDuty, Datadog, Sentry, or dead-man's snitch integrations.
    * Table in `docs/operations/ALERTING.md` serves as an operational runbook for external monitoring setup (e.g. UptimeRobot, Datadog), but is not wired into the application.

---

## 16. Backup & Disaster Recovery
* **Classification:** **DOCUMENTED ONLY / ASSUMED MANAGED**
* **Inspection Details:**
  * Documented in [`docs/operations/DISASTER_RECOVERY.md`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/docs/operations/DISASTER_RECOVERY.md).
  * **RPO / RTO:** Accurately marked as **`NOT VERIFIED (Tier Dependent)`**.
  * **Physical Backups:** Relies on Supabase managed daily backups (7-day retention on Free tier). Not verifiable directly from local repository code.
  * **Point-in-Time Recovery (PITR):** Accurately marked as **`NOT VERIFIED`** (requires paid Supabase Pro + PITR add-on).
  * **Schema Recovery:** **VERIFIED**. 17 sequential idempotent migrations exist in `supabase/migrations/` to rebuild clean database state.

---

## 17. Migration Rollback
* **Classification:** **MANUAL ONLY / NOT IMPLEMENTED**
* **Inspection Details:**
  * Inspection of `supabase/migrations/` reveals 17 SQL files. All migrations are forward-only (`CREATE TABLE`, `ALTER TABLE ADD COLUMN`, `CREATE OR REPLACE FUNCTION`).
  * **No down-migrations exist** (`.down.sql` or inverse scripts).
  * A rollback cannot be executed automatically via `supabase migration down`.
  * Reversing schema changes requires either manual inverse SQL scripts or full database point-in-time restore from backup.

---

## 18. Deployment Safety
* **Classification:** **VERIFIED IN CODE & SCHEMA**
* **Inspection Details:**
  * **Zero-Downtime Schema Safety (OLD CODE + NEW DB):** **SAFE**. All recent migrations use `ADD COLUMN IF NOT EXISTS`, non-destructive default values, and non-blocking indexes (`CREATE INDEX IF NOT EXISTS`).
  * **Migration Ordering (NEW CODE + CURRENT DB):** **REQUIRES DB FIRST**.
    * If new application code calling `claim_due_domain_audits` or querying new columns is deployed before database migrations are run, in production (`ENVIRONMENT="production"`), the database call fails and `_allow_in_memory_fallback()` returns `False`, raising `DatabaseUnavailableError`.
    * **Rule:** Database migrations must strictly precede application container deployments.

---

## 19. Frontend Regression
* **Classification:** **VERIFIED BY BUILD**
* **Inspection Details:**
  * `npm run build` executed cleanly in `frontend/`.
  * **Routes Compiled:** Exactly **25 / 25 routes** compiled as static or dynamic:
    * `/` (Static 15.4 kB)
    * `/_not-found`
    * `/auth/callback` (Dynamic)
    * `/auth/forgot-password`, `/auth/login`, `/auth/reset-password`, `/auth/signup`
    * `/dashboard`, `/dashboard/billing`, `/dashboard/content-lab`, `/dashboard/inspector`, `/dashboard/radar`, `/dashboard/settings`, `/dashboard/shopify`, `/dashboard/wizard`
    * Legal pages: `/dpa`, `/privacy`, `/security`, `/terms`
    * SEO routes: `/robots.txt`, `/sitemap.xml`
  * **Static Generation:** 25/25 pages generated.
  * **TypeScript / Linter:** 0 compile errors, 0 type errors. (Warnings limited to React hook dependency hints in 3D canvas components).

---

## 20. Test Results
* **Command:** `py -m pytest tests/`
* **Passed:** 153
* **Failed:** 0
* **Skipped:** 0
* **Xfailed:** 0
* **Warnings:** 137 (standard Python 3.14 deprecation warnings for `datetime.utcnow()` and Supabase sync client `verify` parameter)
* **Execution Time:** 84.15 seconds (0:01:24)
* **Breakdown:**
  * 144 Baseline / Phase 1 tests
  * 9 Phase 2 resilience / failure-injection tests (`test_phase2_resilience.py`)

---

## 21. Undocumented Risks
1. **DNSBL Public Resolver Blacklisting:** If InboundCheck scales beyond community limits, public resolvers (`1.1.1.1`, `8.8.8.8`) will receive `127.255.255.x` return codes from Spamhaus. This requires migrating to a dedicated direct DNS resolver or purchasing a Spamhaus DQS key.
2. **Reverse Proxy Single-IP Rate Limit Collapse:** If deployed behind Cloudflare or Railway edge without configuring a proxy middleware that populates `request.client.host` from verified `CF-Connecting-IP`, all inbound users will share a single 120 req/min bucket.

---

## 22. P0 Findings
* *None.* (No tenant isolation leaks, unauthenticated data exposure, or unhandled database crashes).

---

## 23. P1 Findings
1. **Audit Worker Infinite Retry Loop for Failed Audits:**
   * **Severity:** P1 (High)
   * **File:** [`backend/app/workers/audit_worker.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/workers/audit_worker.py#L179-L184) & [`supabase/migrations/20260912000001_add_audit_leases_and_failover_pipeline.sql`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260912000001_add_audit_leases_and_failover_pipeline.sql#L86-L110)
   * **Behavior:** `fail_domain_audit` resets `audit_lease_until = NULL` and leaves `last_audited_at` unchanged. `claim_due_domain_audits` selects domains where `last_audited_at <= NOW() - interval AND audit_lease_until IS NULL`. Consequently, a failing domain is immediately re-claimed every 30 seconds.
   * **Production Impact:** A broken domain or transient resolver issue causes 120 failed audits per hour per broken domain, spamming error logs and wasting resolver budget.
   * **Remediation:** In `fail_domain_audit`, apply exponential backoff by setting `audit_lease_until = NOW() + (INTERVAL '15 minutes' * LEAST(POWER(2, audit_failure_count), 96))`.

2. **Rate Limiting Lacks Proxy IP & Endpoint Granularity:**
   * **Severity:** P1 (High)
   * **File:** [`backend/app/main.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L65-L125)
   * **Behavior:** Enforces a single global 120 req/min limit on `request.client.host`.
   * **Production Impact:** Behind a reverse proxy (Railway/Cloudflare), legitimate merchants can be throttled together, while expensive endpoints (`/dns/scan`, `/ai/optimize`) can be hit with 120 expensive operations per minute by a single user.

---

## 24. P2 Findings
1. **Webhook Deduplication TOCTOU Race Condition:**
   * **Severity:** P2 (Medium)
   * **File:** [`backend/app/services/billing/stripe_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/billing/stripe_service.py#L458-L460)
   * **Behavior:** `is_event_processed` and `mark_event_processed` are not wrapped in an atomic database lock. Simultaneous duplicate webhook deliveries can both pass the initial check.
2. **Missing Down-Migrations for Disaster Rollback:**
   * **Severity:** P2 (Medium)
   * **File:** `supabase/migrations/`
   * **Behavior:** All 17 migrations are forward-only with no inverse `.down.sql` scripts.
3. **Frontend API Fetch Lacks Client-Side Timeout:**
   * **Severity:** P2 (Medium)
   * **File:** [`frontend/src/lib/api.ts`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/frontend/src/lib/api.ts#L129-L136)
   * **Behavior:** `apiFetch` does not provide an `AbortSignal.timeout()`, leaving browser network requests hanging on edge network disconnects.

---

## 25. Recommended Next Actions
1. **Implement Exponential Backoff in `fail_domain_audit`:** Update PostgreSQL RPC function to delay re-claiming failing domains based on `audit_failure_count`.
2. **Configure Trusted Proxy Middleware:** Update FastAPI `RateLimitingMiddleware` to parse `CF-Connecting-IP` or `X-Forwarded-For` with trusted proxy CIDRs.
3. **Connect Production APM / Health Monitoring:** Hook up external uptime monitor (e.g. Better Uptime / Checkly) targeting `/health` and `/ready` to fulfill the documented `ALERT-DB-OUTAGE` alerting runbook.
4. **Add Client-Side Fetch Timeout:** Provide a default 15-second `AbortSignal.timeout(15000)` in `frontend/src/lib/api.ts`.
