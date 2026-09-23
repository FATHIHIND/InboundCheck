# InboundCheck Enterprise — Production Readiness & Adversarial Reliability Audit

> **Document Type:** Independent Principal Security & Reliability Verification Audit Report (Phase 2.2)  
> **Target System:** InboundCheck (Transactional Email Deliverability & DNS Governance Platform)  
> **Audited By:** Principal SaaS Security Architect, Staff Backend Engineer, SRE, FinOps & Production Reliability Auditor  
> **Date of Execution:** September 23, 2026  
> **Audit Status:** **AUDIT ONLY — STRICT ZERO CODE/SCHEMA MODIFICATION MODE**  
> **Scope:** Full-Repository Deep Inspection across 45 Operational & Security Dimensions  

---

## 1. Executive Summary

This independent production readiness audit provides an unvarnished, adversarial evaluation of the InboundCheck SaaS repository. Previous internal completion milestones claimed that Phase 1 (P0 Security & Data Integrity), Phase 2 (Production Reliability, Resilience & Cost Control), and Phase 2.1 (P1 Reliability Remediation) were fully resolved.

Our mandate was to reject all completion documentation as unverified assertions and audit the raw source code, SQL migrations, container topology, and execution pathways directly.

### Executive Verdict
**CURRENT PRODUCTION READINESS STATUS: NOT READY FOR PAYING CUSTOMERS.**

While the engineering team has achieved significant architectural milestones—including a 100% passing backend test suite (169/169 tests in 99.88s), clean Next.js 14 compilation (25/25 pages), state-of-the-art socket-pinned anti-SSRF protections, and a robust `SKIP LOCKED` worker audit queue with jittered exponential backoff—**critical vulnerabilities remain that would result in immediate financial loss, credential theft, and tenant impersonation in a production environment.**

### Most Critical Findings Overview
1. **P0 Cryptographic Tenant Impersonation:** The JWT verification module includes the public browser anon key in its symmetric HMAC validation candidates. Any unauthenticated attacker who reads `NEXT_PUBLIC_SUPABASE_ANON_KEY` can mint valid HS256 tokens for arbitrary `user_id` UUIDs, completely bypassing all tenant isolation.
2. **P0 Free Enterprise Billing Bypass:** The Shopify billing activation callback swallows API errors and unconditionally upgrades the store owner to an `"enterprise"` subscription tier with `$0` payment.
3. **P1 Ephemeral Auto-Fix Credentials:** Cloudflare API keys submitted for automated DNS remediation are stored exclusively in an in-memory process dictionary, vanishing on every server restart and failing completely in multi-container deployments.
4. **P1 Missing RLS on Distributed Rate Limiter:** The newly introduced `rate_limit_windows` table lacks PostgreSQL Row Level Security (RLS) and public RPC restrictions, allowing clients to manipulate rate-limiting counters directly via PostgREST.
5. **P1 Ghost Incident Alerting:** The Telegram and operational alerting service is well-tested in isolation but is never wired into any webhook error handlers, billing failures, or worker crashes.

---

## 2. Scope

The audit covered every file, directory, configuration file, database migration, and test in the InboundCheck repository:

- **Backend Application:** `backend/app/` (FastAPI 0.111+, Pydantic v2, Starlette middleware, routers, services).
- **Persistence Layer:** `supabase/migrations/` (PostgreSQL schemas, RLS policies, triggers, RPC stored procedures).
- **Worker & Job Architecture:** `backend/app/worker.py`, background scheduling, lease claims, retry backoff algorithms.
- **Frontend Application:** `frontend/src/` (Next.js 14 App Router, `@supabase/ssr`, Tailwind CSS, middleware route guards).
- **Deployment & Infrastructure:** `Dockerfile`, `docker-compose.yml`, `railway.json`, environment definitions.
- **Test Infrastructure:** `backend/tests/` (169 unit, integration, and failure-injection test cases).

The audit evaluated 45 distinct operational dimensions with zero code modifications made during the inspection.

---

## 3. Repository Architecture & Component Inventory

### Component Map

| Component | Entry Point | Dependencies | External Services | Data Touched | Operational Importance |
|---|---|---|---|---|---|
| **API Gateway** | `backend/app/main.py` | FastAPI, Starlette | Reverse Proxy / CDN | Inbound HTTP Requests | P0: Single entry point for all API traffic |
| **Edge Auth Middleware** | `frontend/src/middleware.ts` | `@supabase/ssr` | Supabase Auth API | Session Cookies (`sb-*-auth-token`) | P0: Route guards for `/dashboard/*` |
| **JWT Verification** | `backend/app/core/security.py` | PyJWT, Cryptography | Supabase JWKS endpoint | `Authorization: Bearer <token>` | P0: Tenant identity extraction |
| **Rate Limiter** | `backend/app/services/security/rate_limiter.py` | Supabase Client | PostgreSQL RPC | `public.rate_limit_windows` | P1: Abuse, brute-force, and DoS mitigation |
| **SSRF Guard** | `backend/app/services/security/safe_http_fetcher.py` | `socket`, `ipaddress`, `httpx` | External DNS resolvers | Outbound HTTP requests (BIMI/Webhooks) | P0: Prevents SSRF & cloud metadata theft |
| **Worker Engine** | `backend/app/worker.py` | Asyncio, DNS Engine | Authoritative DNS & RBLs | `monitored_domains`, `dns_audit_logs` | P0: Core deliverability auditing pipeline |
| **DNS Diagnostic Engine** | `backend/app/services/dns/diagnostic_engine.py` | `dnspython` | Public Nameservers | DNS records (SPF, DKIM, DMARC, MX) | P0: Primary diagnostic capability |
| **DNS Auto-Fixer** | `backend/app/services/dns/auto_fixer.py` | `httpx` | Cloudflare REST v4 API | DNS zone records & API tokens | P1: Automated DNS record remediation |
| **Stripe Billing Service** | `backend/app/services/billing/stripe_service.py` | `stripe` Python SDK | Stripe API & Webhooks | `profiles`, `processed_webhook_events` | P0: Subscriptions, checkout, and entitlements |
| **Shopify Service** | `backend/app/services/shopify/shopify_service.py` | `httpx`, HMAC-SHA256 | Shopify Admin API & Webhooks | `shopify_stores`, `monitored_domains` | P1: Store connection & receipt monitoring |
| **AI Content Optimizer** | `backend/app/services/ai/content_optimizer.py` | `httpx` | OpenAI-compatible endpoints | Email template copy | P2: Template spam scoring & rewriting |
| **Ops Alert Service** | `backend/app/services/alerting/ops_alert_service.py` | `httpx` | Telegram Bot API | Alert queues & incident telemetry | P2: Real-time incident notifications |

---

## 4. Security Findings

```
CRITICAL VULNERABILITY TREE:
[Untrusted Client]
       │
       ▼ (HS256 Signature using NEXT_PUBLIC_SUPABASE_ANON_KEY)
[backend/app/core/security.py] ───► Accepted as valid!
       │
       ▼ (get_current_user_id extracts victim "sub")
[backend/app/api/v1/domains.py] ───► Returns victim domains, audits, credentials!
```

### Finding SEC-01 (P0): Cryptographic Signature Forgery via Public Anon Key
- **File:** [`backend/app/core/security.py:82-96`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/core/security.py#L82-L96)
- **Vulnerability:** In `_decode_supabase_jwt_symmetric()`, the code searches for a valid HMAC key among `secret_candidates`:
  ```python
  secret_candidates = [
      settings.SUPABASE_JWT_SECRET,
      settings.SUPABASE_SERVICE_ROLE_KEY,
      settings.SUPABASE_KEY,  # <--- CRITICAL VULNERABILITY
  ]
  ```
  `settings.SUPABASE_KEY` is the public anonymous client key. This key is intentionally exposed to client web browsers as `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `frontend/.env.local`.
- **Exploitation:** Any external user can inspect their browser DOM or network tab to obtain `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Using this key as an HMAC secret, the attacker crafts a forged JWT with header `{"alg": "HS256"}` and payload `{"sub": "<target_user_uuid>"}`. When sent to the FastAPI backend, the JWT decoder tests `settings.SUPABASE_KEY`, successfully validates the signature, and accepts the forged identity.
- **Impact:** Complete cross-tenant account takeover for any known user ID.

### Finding SEC-02 (P1): Permissive CORS Regular Expression
- **File:** [`backend/app/main.py:168`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L168)
- **Vulnerability:** The CORS configuration utilizes an unanchored regex:
  ```python
  allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.railway\.app",
  allow_credentials=True,
  ```
- **Exploitation:** Any malicious actor hosting a phishing website on any Vercel domain (e.g., `https://evil-attacker.vercel.app`) can initiate credentialed cross-origin requests (`fetch(..., {credentials: 'include'})`) against the backend API.
- **Impact:** Cross-Origin API abuse and session hijacking for browser-authenticated clients.

---

## 5. Tenant Isolation Audit

We inspected all API routers in `backend/app/api/v1/` and compared database queries against `docs/security/TENANT_ISOLATION_MATRIX.md`.

### Evaluation Across Resources

| Resource | Identity Source | Application-Level Check | Database RLS Protection | Verdict |
|---|---|---|---|---|
| **User Profile** | `get_current_user_id` | Strict `WHERE id = user_id` | `auth.uid() = id` | **VERIFIED** |
| **Monitored Domains** | `get_current_user_id` | Explicit `user_id` query filter | `auth.uid() = user_id` | **VERIFIED** |
| **Audit Logs** | `get_current_user_id` | Joins via `domain_id` ownership | Inherited via domain ownership | **VERIFIED** |
| **Domain Re-Audit** | `get_current_user_id` | Checks `domain_id` ownership | Creates unvalidated domain query | **PARTIALLY VERIFIED** (See Finding ISO-01) |
| **DNS Auto-Fix** | `get_current_user_id` | Checks `domain_id` ownership | Credentials stored in memory only | **INCORRECT** |
| **Shopify Stores** | `get_current_user_id` | Strict `user_id` filter | `auth.uid() = user_id` | **VERIFIED** |
| **Failover Logs** | `get_current_user_id` | Strict `user_id` filter | `auth.uid() = user_id` | **VERIFIED** |
| **AI Content Lab** | `get_current_user_id` | Enforces tier & usage caps | User-scoped record logging | **VERIFIED** |
| **Rate Limit Counters**| Client IP / User ID | RPC `consume_rate_limit` | **NO RLS ON TABLE** | **INCORRECT** |

### Finding ISO-01 (P1): Domain Quota Bypass via `re_audit_domain`
- **File:** [`backend/app/api/v1/domains.py:143-162`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/domains.py#L143-L162)
- **Vulnerability:** When a user calls `POST /api/v1/domains/{domain_id}/re-audit?domain_name=attacker-domain.com`, the endpoint verifies that `{domain_id}` belongs to the authenticated user. However, when triggering the audit, it passes `domain_name` (the query parameter) rather than the verified domain name of `{domain_id}`.
- **Exploitation:** `supabase_service.create_or_update_domain(domain_name=clean_domain)` is invoked for `attacker-domain.com` without performing the tenant plan domain quota check. A free-tier user restricted to 1 domain can audit unlimited external domains by repeatedly calling `re-audit` with varying query strings.

---

## 6. Authentication & Authorization

### JWT Life Cycle & Verification
The authentication layer in `backend/app/core/security.py` relies on an asymmetric JWKS fetcher with local symmetric HMAC fallback:
1. **Asymmetric Flow (Supabase RS256/ES256):** `_decode_supabase_jwt_asymmetric` fetches the JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, caching keys for 1 hour. It verifies `alg`, `exp`, and `iss`.
2. **Missing Token & Malformed Token Tests:** Tested and verified. Supplying an empty string, expired token, or invalid header correctly raises HTTP 401 Unauthorized.
3. **Privilege Escalation:** No role-based access control (RBAC) engine is implemented. All authenticated users share the same role (`authenticated`). Administrative endpoints do not exist in the public router.

---

## 7. SSRF (Server-Side Request Forgery) Protection

We audited all endpoints that accept external domains, URLs, or hostnames:
- `DNSDiagnosticEngine._clean_domain()`: [`backend/app/services/dns/diagnostic_engine.py:84-118`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/dns/diagnostic_engine.py#L84-L118)
- `SafeHttpFetcher.get()`: [`backend/app/services/security/safe_http_fetcher.py:108-204`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/security/safe_http_fetcher.py#L108-204)

### Evaluation Against SSRF Vectors

| Vector | Filter Mechanism | Code Location | Status |
|---|---|---|---|
| `127.0.0.1` / `localhost` | `ipaddress.is_loopback` check | `safe_http_fetcher.py:53` | **PROTECTED** |
| `169.254.169.254` (AWS/GCP Metadata) | `ipaddress.is_link_local` check | `safe_http_fetcher.py:56` | **PROTECTED** |
| RFC 1918 Private Ranges (`10.0.0.0/8`, etc.) | `ipaddress.is_private` check | `safe_http_fetcher.py:54` | **PROTECTED** |
| IPv6 Loopback (`::1`) & Link-Local (`fe80::/10`) | `is_loopback` & `is_link_local` | `safe_http_fetcher.py:53` | **PROTECTED** |
| IPv4-Mapped IPv6 (`::ffff:127.0.0.1`) | `is_ipv4_mapped` normalization | `safe_http_fetcher.py:65` | **PROTECTED** |
| Octal / Hex / Decimal IPs (`0177.0.0.1`, `0x7f.1`) | `ipaddress.ip_address` parser | `safe_http_fetcher.py:48` | **PROTECTED** |
| DNS Rebinding (TOCTOU) | Socket connection pinned to validated IP | `safe_http_fetcher.py:165` | **PROTECTED** |
| Open Redirects to Internal IPs | Redirect loop re-resolves and validates IP | `safe_http_fetcher.py:180` | **PROTECTED** |
| Response Bomb / Buffer Exhaustion | Streamed response capped at 500 KB | `safe_http_fetcher.py:192` | **PROTECTED** |

**SSRF Assessment:** **ENTERPRISE GRADE & FULLY VERIFIED.** The `SafeHttpFetcher` implementation is exceptionally robust against all standard and esoteric SSRF attack vectors.

---

## 8. Webhook Security

### 1. Stripe Webhooks
- **File:** [`backend/app/api/v1/billing.py:112-140`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/billing.py#L112-L140)
- **Signature Verification:** Uses `stripe.Webhook.construct_event(payload, sig_header, secret, tolerance=300)`. Enforces 300s timestamp tolerance.
- **Replay Protection:** Deduplication is persisted to the database via `public.processed_webhook_events`. Events are recorded with status `'processing'` under a database unique constraint before business logic executes.
- **Duplicate Delivery:** Tested and confirmed idempotent. Duplicate event IDs return HTTP 200 with `{"received": True, "duplicate": True}`.

### 2. Shopify Webhooks
- **File:** [`backend/app/services/shopify/shopify_service.py:43-59`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/shopify/shopify_service.py#L43-L59)
- **Signature Verification:** Computes `hmac.new(secret, raw_body, hashlib.sha256).digest()` and verifies with `hmac.compare_digest()`.
- **VULNERABILITY (P1): Ephemeral Webhook Deduplication:**
  ```python
  # shopify_service.py:45
  self._processed_webhooks: set = set()
  ```
  Unlike Stripe webhooks, Shopify webhook deduplication is stored in an in-memory Python `set`. When running across multiple containers or after a process restart, re-sent Shopify webhooks (e.g., `orders/create`, `app/uninstalled`) will be processed multiple times, triggering duplicate failover messages and corrupted shop state.

---

## 9. Rate Limiting & Abuse Prevention Audit

In Phase 2.1, the team implemented a dual-layer rate limiting architecture:
1. `RateLimitingMiddleware` (`backend/app/main.py`): In-memory sliding window for fast global DoS throttling (120 req/min).
2. `DistributedRateLimiter` (`backend/app/services/security/rate_limiter.py`): PostgreSQL-backed atomic rate limiter with differentiated failure modes.

### Critical Deficiencies Discovered

#### Finding LIM-01 (P2): Health Probe Throttling via Missing `/ready` Bypass
- **File:** [`backend/app/main.py:103-108`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L103-L108)
- **Vulnerability:** The in-memory middleware explicitly exempts `/health`, `/`, and `/docs`:
  ```python
  if request.url.path in ["/health", "/", "/docs", "/openapi.json"]:
      return await call_next(request)
  ```
  It **omits** `/ready` and `/api/v1/health`.
- **Production Failure:** Railway or Kubernetes readiness probes polling `/ready` every 2–5 seconds will quickly consume the 120-request limit. The middleware will begin returning HTTP 429 to the infrastructure orchestrator, causing the container to be falsely marked unhealthy and killed in an endless restart loop.

#### Finding LIM-02 (P1): Unprotected `rate_limit_windows` Table
- **File:** [`supabase/migrations/20260925000001_p1_reliability_remediation.sql:140-186`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260925000001_p1_reliability_remediation.sql#L140-L186)
- **Vulnerability:** Migration `20260925000001` creates table `public.rate_limit_windows` and function `public.consume_rate_limit`. However, it **fails to enable Row Level Security (RLS)**:
  - `ALTER TABLE public.rate_limit_windows ENABLE ROW LEVEL SECURITY;` was never executed.
  - `REVOKE EXECUTE ON FUNCTION public.consume_rate_limit FROM PUBLIC;` was never executed.
- **Exploitation:** Any client holding `NEXT_PUBLIC_SUPABASE_ANON_KEY` can make direct PostgREST calls to `DELETE FROM rate_limit_windows` or `UPDATE rate_limit_windows SET request_count = 0`, resetting their rate limits at will.

---

## 10. Audit Retry & Background Worker Reliability

We audited the entire lifecycle of background domain audits in `backend/app/worker.py` and migration `20260925000001_p1_reliability_remediation.sql`.

```
LIFECYCLE VERIFICATION FLOW:
[DUE DOMAIN]
     │
     ▼ (claim_due_domain_audits via FOR UPDATE SKIP LOCKED)
[CLAIMED: audit_lease_owner = worker_id, audit_lease_until = NOW() + 120s]
     │
     ├─► [SUCCESS] ──► audit_failure_count = 0, last_audited_at = NOW(), lease cleared
     │
     └─► [EXCEPTION] ──► fail_domain_audit()
                             │
                             ├─► audit_failure_count += 1
                             ├─► next_audit_retry_at = NOW() + (120s * 2^N) + Jitter
                             ├─► audit_lease_until = NULL
                             └─► last_audited_at UNCHANGED (Audit history preserved)
```

### Verification Results
1. **Separation of Retry and Lease Timers (Phase 2.1 Fix):** **VERIFIED.** The database procedure `claim_due_domain_audits` now strictly checks:
   ```sql
   AND (next_audit_retry_at IS NULL OR next_audit_retry_at <= now())
   AND (audit_lease_until IS NULL OR audit_lease_until < now())
   ```
2. **Backoff Mathematics:** **VERIFIED.** Uses `120 * POWER(2, LEAST(v_new_failure_count, 10))` with randomized jitter of `+0%` to `+25%`, capped at 86,400 seconds (24 hours).
3. **Crash Recovery:** **VERIFIED.** Abandoned worker leases automatically expire after 120 seconds, allowing surviving workers to reclaim stuck domains.

---

## 11. Idempotency Audit

| Operation | Idempotency Key | Storage Location | Transaction Boundary | Duplicate Behavior | Status |
|---|---|---|---|---|---|
| **Stripe Webhook** | `event.id` | `processed_webhook_events` | DB Unique Index | Returns HTTP 200 duplicate | **VERIFIED** |
| **Shopify Webhook** | `X-Shopify-Webhook-Id` | In-memory `set` | Process memory only | Multi-instance duplicate execution | **FAILED (P1)** |
| **Domain Creation** | `(user_id, domain_name)` | `monitored_domains` | DB Unique Constraint | Upserts record cleanly | **VERIFIED** |
| **Worker Lease Claim**| `domain.id` | `monitored_domains` | `FOR UPDATE SKIP LOCKED`| Zero duplicate worker claims | **VERIFIED** |
| **Rate Limit Window** | `(key, window_start)` | `rate_limit_windows` | DB Primary Key Upsert | Atomic increment | **VERIFIED** |

---

## 12. Billing & Monetization Lifecycle

### Finding BIL-01 (P0): Free Enterprise Upgrade Vulnerability
- **File:** [`backend/app/api/v1/shopify.py:276-297`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py#L276-L297)
- **Vulnerability:** In `shopify_billing_callback`, the code attempts to activate a Shopify merchant subscription. When an error occurs (such as an invalid charge ID or rejected test token), the exception is logged but ignored, and the user is upgraded anyway:
  ```python
  # shopify.py:284-297
  try:
      # If external verification fails or throws an exception...
      success = await shopify_service.verify_and_activate_subscription(shop, charge_id)
  except Exception as e:
      logger.error(f"Shopify billing activation error: {e}")
      # DOES NOT RETURN! Drops through to:

  supabase_service.update_user_profile(
      resolved_user_id,
      {
          "subscription_tier": "enterprise",
          "subscription_status": "active",
      }
  )
  ```
- **Exploitation:** Any authenticated user can navigate to `/api/v1/shopify/billing/callback?shop=test.myshopify.com&charge_id=fake_charge` and instantly obtain a lifetime Enterprise subscription without paying.

### Finding BIL-02 (P1): Out-of-Order Webhook Subscription Resurrection
- **File:** [`backend/app/services/billing/stripe_service.py:555-638`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/billing/stripe_service.py#L555-L638)
- **Vulnerability:** Stripe webhook events (`customer.subscription.updated` and `customer.subscription.deleted`) update the user's `subscription_status` without checking the event timestamp (`event.created`) against the existing record timestamp (`profile.updated_at`).
- **Production Failure:** If network latency causes a delayed `customer.subscription.updated` event to arrive 10 seconds *after* a `customer.subscription.deleted` event, the canceled user account will be reactivated as a paying subscriber.

---

## 13. AI & Cost Control Audit

- **Implementation:** [`backend/app/services/ai/content_optimizer.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/ai/content_optimizer.py)
- **Model Adapter:** Neutral OpenAI-compatible client. Model name configurable via `LLM_MODEL_NAME`.
- **Timeouts & Token Limits:** Strict 15.0s client timeout. System prompts enforce maximum token generation limits.
- **Untrusted Input Ingestion:** User email copy is passed as content. Mitigated by explicit system separation and heuristic pre-screening for spam markers before invoking LLM inference.
- **Fallback Heuristics:** If the LLM provider fails, times out, or returns a 5xx error, the service falls back to a deterministic, zero-cost Python heuristic rule engine (`_fallback_heuristic_audit`).
- **Denial-of-Wallet Exposure:** Single user requests are constrained by tier quotas (e.g., 5 audits/day for Free, 50/day for Pro) and database rate limits.
- **Provider Pricing:** **UNKNOWN — VERIFY BEFORE PRODUCTION.** (Depends on configured third-party inference provider).

---

## 14. DNS & RBL Infrastructure

- **Implementation:** [`backend/app/services/dns/diagnostic_engine.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/dns/diagnostic_engine.py)
- **Resolver Architecture:** Uses `dnspython` with asynchronous multi-resolver pooling.
- **Timeout Safety:** Lifetime timeout is hard-capped at 4.0 seconds per query, with 1.0 second per attempt.
- **Resolver Exhaustion Prevention:** Async execution utilizes semaphore concurrency limiting (`asyncio.Semaphore(10)`), preventing file descriptor exhaustion during bulk RBL scans.
- **RBL Providers Audited:** 10 authoritative zones (Spamhaus ZEN, Barracuda BRBL, SpamCop, Invaluement, etc.). Queries use non-blocking executor wrappers.

---

## 15. External Integration Audit

| Provider | Purpose | Timeout | Retries | Circuit Protection | Failure Behavior | Stored Credentials |
|---|---|---|---|---|---|---|
| **Supabase PostgREST** | Primary Datastore | 10.0s | None | None | 500 Internal Error | Service Role / Anon Key |
| **Stripe API** | Billing Engine | 8.0s | 2 (SDK default) | None | Blocks checkout flow | Secret Key |
| **Shopify Admin API** | Store Metadata | 10.0s | 1 attempt | None | Disables sync features | Access Token |
| **Cloudflare v4 API** | DNS Auto-Fix | 10.0s | None | None | Fails remediation | **IN-MEMORY ONLY (P1)** |
| **Telegram Bot API** | Ops Alerts | 4.0s | None | Drops alert | Silent log warning | Bot Token / Chat ID |
| **OpenAI / LLM** | Content Lab | 15.0s | None | Heuristic Fallback | Heuristic takes over | API Key |

---

## 16. Database Migrations & PostgreSQL Schema

### Migration History Analysis
We reviewed all files in `supabase/migrations/`:
1. `20260823000001_initial_schema.sql`: Foundational tables (`profiles`, `monitored_domains`, `dns_audit_logs`).
2. `20260824000002_v3_roadmap_schema.sql`: Extended features (`ai_template_audits`, `failover_configs`).
3. `20260903000001_complete_production_schema.sql`: Production consolidation, triggers, and foreign keys.
4. `20260924000001_p0_security_hardening.sql`: RLS hardening and tenant isolation constraints.
5. `20260925000001_p1_reliability_remediation.sql`: `next_audit_retry_at` column, `claim_due_domain_audits` procedure, and `rate_limit_windows` table.

### Security Defect in Functions
All stored procedures (`claim_due_domain_audits`, `fail_domain_audit`, `consume_rate_limit`) declare `SECURITY DEFINER`.
- **Search Path Risk:** They specify `SET search_path = public`. This prevents search path hijacking attacks.
- **Missing Grant Restrictions:** `consume_rate_limit` lacks `REVOKE EXECUTE ON FUNCTION consume_rate_limit FROM PUBLIC;`. Unauthenticated clients can directly call this procedure via PostgREST.

---

## 17. Data Integrity & Invariant Enforcement

| Invariant | Enforcement Point | DB Enforced? | Tested? |
|---|---|---|---|
| Domain belongs to exactly one user | `monitored_domains.user_id` FK | Yes (`ON DELETE CASCADE`) | Yes |
| Unique active domain per user | `monitored_domains (user_id, domain_name)` | Yes (`UNIQUE` Index) | Yes |
| Audit logs link to valid domain | `dns_audit_logs.domain_id` FK | Yes (`ON DELETE CASCADE`) | Yes |
| Webhook idempotency is global | `processed_webhook_events.event_id` | Yes (`PRIMARY KEY`) | Yes |
| Domain lease exclusivity | `claim_due_domain_audits()` | Yes (`FOR UPDATE SKIP LOCKED`) | Yes |
| Rate limit counter atomic window | `consume_rate_limit()` | Yes (`ON CONFLICT DO UPDATE`) | Yes |

---

## 18. Frontend Security

We audited `frontend/src/` for client-side security risks:
- **Authentication Handlers:** `@supabase/ssr` with `httpOnly` secure cookies. Tokens are not accessible via client JavaScript `document.cookie`.
- **Secret Leaks:** Inspected all `NEXT_PUBLIC_*` variables. Only `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are exposed. No secret keys or Stripe private tokens exist in frontend bundles.
- **XSS & Unsafe HTML:** No occurrences of `dangerouslySetInnerHTML` found. All SVG charts and reputation trends render using sanitized React JSX.

---

## 19. API Security

- **Payload Size Limits:** `RateLimitingMiddleware` rejects payloads larger than 2 MB with HTTP 413 Payload Too Large.
- **Error Information Disclosure:** Custom exception handlers intercept uncaught exceptions and return generic JSON errors (`{"detail": "Internal server error"}`), preventing Python stack traces from leaking to clients in production.
- **Security Headers:** The application injects:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`

---

## 20. Logging & Observability

- **Structured Logging:** Configured via standard Python `logging` with structured JSON formatters.
- **Sensitive Data Masking:** Token authorization headers, cookies, and database passwords are sanitized before emitting to `stdout`.
- **Incident Correlators:** Every HTTP request is tagged with a unique `X-Request-ID` header, propagated through logger context.

---

## 21. Monitoring & Operational Alerting

- **Implementation:** [`backend/app/services/alerting/ops_alert_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alerting/ops_alert_service.py)
- **Telegram Dispatch:** Asynchronous HTTP dispatch with 4.0-second timeout.
- **FINDING MON-01 (P2): Alerting Not Wired to Critical Failure Paths:**
  The `OpsAlertService.dispatch_incident()` method is tested in unit tests, but **it is never called anywhere in the actual application code**. Neither the Stripe webhook error handlers, the worker crash loops, nor the database connection failure handlers invoke `ops_alert_service`.

---

## 22. Disaster Recovery

| Component | Status | Evidence / Implementation |
|---|---|---|
| **Database Backups** | **DOCUMENTED ONLY** | Assumed managed by Supabase; no automated pg_dump or replication verified in repo |
| **Point-in-Time Recovery (PITR)** | **NOT AVAILABLE** | Requires paid Supabase plan; not configured via IaC |
| **Migration Rollback** | **PARTIALLY VERIFIED** | Forward-only migrations; no down-migration scripts exist in repository |
| **Worker Crash Recovery** | **VERIFIED** | Lease timeouts expire in 120s; stuck jobs automatically re-enter candidate pool |
| **Disaster Recovery RPO / RTO** | **NOT VERIFIED** | No formal recovery runbook or verified RTO/RPO targets |

---

## 23. Performance & Concurrency

- **Load Testing Status:** **NOT BENCHMARKED.** No automated Locust or k6 load testing scripts exist in the repository.
- **Database Connection Pooling:** Backend uses `httpx` and Supabase PostgREST connection pools. Under 100+ concurrent users, database connection limits on entry-tier Supabase compute will become a primary bottleneck.
- **Event Loop Safety:** Heavy cryptographic operations and DNS UDP queries execute via worker threads and threadpool executors, preventing FastAPI main event loop blocking.

---

## 24. Deployment & Railway Configuration

- **Railway Config:** [`railway.json`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/railway.json) defines container build commands and healthcheck endpoints.
- **Healthcheck Path:** Configured to `/health`. Because `/health` is exempted from the rate limiter, Railway liveness checks will succeed.
- **Worker Process:** Must run as a distinct service (`python -m app.worker`). Running both web and worker in a single container is not supported by the Dockerfile.

---

## 25. Test Quality Audit

We executed the complete backend test suite:
```powershell
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1\backend"
py -m pytest tests/ -v
```
**Results:** **169 passed in 99.88 seconds.** (138 Pydantic V2 deprecation warnings).

### Test Suite Evaluation
- **High Quality:** SSRF tests, worker retry backoff tests, Stripe webhook idempotency, and DNS scanner tests are comprehensive, asserting concrete failure modes.
- **False-Confidence Warning:** The test suite mocks `get_current_user_id` across almost all API test modules (`test_domains_api.py`, `test_shopify_and_settings.py`), completely masking the cryptographic anon-key JWT forgery vulnerability (Finding SEC-01).

---

## 26. Security Test Matrix

| Attack Vector | Expected Defense | Actual Defense in Code | Test Exists? | Result | Severity |
|---|---|---|---|---|---|
| **Cross-Tenant Read** | Blocked by RLS & User ID | Blocked when valid JWT used | Yes | **PASS** | P0 |
| **JWT Forgery (Anon Key)** | Rejected by JWKS/HMAC | **Accepted via `SUPABASE_KEY`** | No | **FAIL** | **P0** |
| **Shopify Free Upgrade** | Rejected without payment | **Upgrades unconditionally** | No | **FAIL** | **P0** |
| **SSRF (AWS 169.254.169.254)**| Blocked before socket connect | Socket-pinned IP rejected | Yes | **PASS** | P0 |
| **SSRF (DNS Rebinding)** | Blocked via pinned connection | IP pinned on socket connect | Yes | **PASS** | P0 |
| **Stripe Webhook Replay** | Rejected as duplicate | Deduplicated via DB table | Yes | **PASS** | P0 |
| **Shopify Webhook Replay** | Rejected as duplicate | In-memory set (fails on restart) | Yes | **FAIL** | P1 |
| **Rate Limit Reset via API** | Blocked by RLS | Table has no RLS enabled | No | **FAIL** | P1 |
| **Domain Quota Bypass** | Blocked by plan limits | Bypassed via `re_audit_domain` | No | **FAIL** | P1 |
| **Readiness Probe Lockout** | Exempt from rate limiter | `/ready` throttled at 120 req/min | No | **FAIL** | P2 |

---

## 27. Failure Mode Matrix

| Component | Failure | Current Behavior | Customer Impact | Recovery | Severity |
|---|---|---|---|---|---|
| **Supabase DB** | Database Offline | Rate limiter fails closed on expensive endpoints, 500 on reads | API unavailable; no silent corruption | Automated once DB recovers | P0 |
| **Stripe API** | Network Timeout | Checkout fails cleanly with error message | Customer cannot subscribe | User retry | P1 |
| **Worker Process** | Process Crash | Leased domains expire after 120s | Domain audit delayed by 2 minutes | Auto-reclaimed by surviving workers | P1 |
| **Cloudflare API** | Bad Credentials | Auto-fix logs error to in-memory dict | User sees failure message | User updates API token | P2 |
| **OpenAI / LLM** | 500 or Timeout | Heuristic optimizer takes over automatically | Content scored with heuristic rules | Seamless fallback | P3 |
| **Telegram API** | Bot Token Blocked | Error logged to console; request proceeds | Ops team misses real-time notification | Requires manual credential fix | P3 |

---

## 28. Comprehensive Findings Classification

### Finding 1: SEC-01 — Cryptographic JWT Forgery via Public Anon Key
- **ID:** FIND-SEC-01
- **Severity:** **P0**
- **Component:** Authentication (`backend/app/core/security.py:89`)
- **Problem:** `settings.SUPABASE_KEY` (the public anon key) is included in symmetric JWT validation candidates.
- **Evidence:** `secret_candidates = [settings.SUPABASE_JWT_SECRET, settings.SUPABASE_SERVICE_ROLE_KEY, settings.SUPABASE_KEY]`.
- **Customer Impact:** Catastrophic. Any user can forge tokens for any store or customer, accessing private audits, credentials, and settings.
- **Priority:** **MUST FIX BEFORE BETA.**

### Finding 2: BIL-01 — Free Lifetime Enterprise Upgrade via Shopify Callback
- **ID:** FIND-BIL-01
- **Severity:** **P0**
- **Component:** Shopify Billing (`backend/app/api/v1/shopify.py:284-297`)
- **Problem:** Subscription activation exceptions are swallowed, and the user profile is unconditionally updated to Enterprise.
- **Evidence:** Exception block logs error and falls through to `supabase_service.update_user_profile(resolved_user_id, {"subscription_tier": "enterprise", ...})`.
- **Customer Impact:** Direct revenue loss. Users obtain paid features without paying.
- **Priority:** **MUST FIX BEFORE BETA.**

### Finding 3: FIX-01 — Ephemeral DNS Auto-Fix Credentials and Logs
- **ID:** FIND-FIX-01
- **Severity:** **P1**
- **Component:** 1-Click DNS Auto-Fixer (`backend/app/services/dns/auto_fixer.py:80-118`)
- **Problem:** Cloudflare API credentials and zone logs are saved in module-level global dicts (`_mock_provider_creds`), not in Supabase.
- **Evidence:** Restarting the container purges all customer Cloudflare tokens and audit histories.
- **Customer Impact:** Customer configurations are wiped out on deployment; multi-container deployments fail.
- **Priority:** **MUST FIX BEFORE PAYING CUSTOMERS.**

### Finding 4: SEC-02 — Missing RLS on `rate_limit_windows` Table
- **ID:** FIND-SEC-02
- **Severity:** **P1**
- **Component:** Database Security (`supabase/migrations/20260925000001_p1_reliability_remediation.sql:140`)
- **Problem:** `rate_limit_windows` table was created without `ENABLE ROW LEVEL SECURITY`.
- **Evidence:** Table has no RLS policies defined; PostgREST exposes table to anon key.
- **Customer Impact:** Malicious users can flush or delete rate-limit counters, bypassing rate limits.
- **Priority:** **MUST FIX BEFORE PAYING CUSTOMERS.**

### Finding 5: REL-01 — In-Memory Shopify Webhook Deduplication
- **ID:** FIND-REL-01
- **Severity:** **P1**
- **Component:** Shopify Service (`backend/app/services/shopify/shopify_service.py:45`)
- **Problem:** Deduplication stores IDs in a Python `set()`.
- **Evidence:** `self._processed_webhooks: set = set()`. Not persisted to database.
- **Customer Impact:** Duplicate Shopify webhook deliveries trigger duplicate notifications or corrupted shop sync state.
- **Priority:** **MUST FIX BEFORE PAYING CUSTOMERS.**

### Finding 6: REL-02 — Readiness Probe Throttling via Ingress
- **ID:** FIND-REL-02
- **Severity:** **P2**
- **Component:** Middleware Gateway (`backend/app/main.py:103`)
- **Problem:** `/ready` is omitted from the rate limiter bypass list.
- **Evidence:** Only `["/health", "/", "/docs", "/openapi.json"]` are exempted.
- **Customer Impact:** Frequent deployment readiness probes hit HTTP 429, triggering false container crash restarts.
- **Priority:** **MUST FIX BEFORE PAYING CUSTOMERS.**

### Finding 7: SEC-03 — Permissive CORS Regular Expression
- **ID:** FIND-SEC-03
- **Severity:** **P2**
- **Component:** Middleware (`backend/app/main.py:168`)
- **Problem:** Origin regex allows any `*.vercel.app` or `*.railway.app` subdomain with credentials.
- **Evidence:** `allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.railway\.app"`.
- **Customer Impact:** Phishing sites hosted on Vercel can access the API on behalf of logged-in users.
- **Priority:** **SHOULD FIX SOON.**

### Finding 8: OBS-01 — Operational Incident Alerting Unwired in Production
- **ID:** FIND-OBS-01
- **Severity:** **P2**
- **Component:** Observability (`backend/app/services/alerting/ops_alert_service.py`)
- **Problem:** `OpsAlertService.dispatch_incident` is never invoked in actual error/exception paths.
- **Evidence:** Zero references to `dispatch_incident` outside `test_ops_alert_service.py`.
- **Customer Impact:** Silent production outages; engineering team receives no alerts during payment or worker failures.
- **Priority:** **SHOULD FIX SOON.**

---

## 29. False Claim Detection

| Documented Claim | Source File | Actual Code Reality | Verdict |
|---|---|---|---|
| *"Multi-instance safe rate limiting"* | `RATE_LIMITING_ARCHITECTURE.md` | `rate_limit_windows` lacks RLS; table open to anon deletion | **FALSE CLAIM** |
| *"Production Ready Billing"* | `PHASE_2_COMPLETION_REPORT.md` | Shopify callback grants Enterprise on error for $0 | **FALSE CLAIM** |
| *"1-Click Auto-Fix Fully Functional"*| `GEMINI.md` | Cloudflare tokens stored in ephemeral Python dict | **FALSE CLAIM** |
| *"Real-time Ops Alerting Active"* | `ALERTING_STRATEGY.md` | `OpsAlertService` is never called in application code | **FALSE CLAIM** |
| *"Zero-Risk Tenant Isolation"* | `TENANT_ISOLATION_MATRIX.md` | Forged HS256 JWT using anon key takes over any account | **FALSE CLAIM** |

---

## 30. Missing Controls Before Real Customers

### Must Fix Before Beta
1. **Remove `settings.SUPABASE_KEY` from `secret_candidates` in `backend/app/core/security.py`** to eliminate cryptographic JWT forgery.
2. **Fix `shopify_billing_callback` in `backend/app/api/v1/shopify.py`** to ensure failed activations return HTTP 400 and do not upgrade user tiers.
3. **Restrict CORS regex in `backend/app/main.py`** to exact, verified frontend production domains.

### Must Fix Before Paying Customers
4. **Persist Cloudflare credentials and DNS auto-fix logs to Supabase** with Fernet envelope encryption and RLS instead of in-memory dictionaries.
5. **Enable RLS on `rate_limit_windows`** and restrict `consume_rate_limit` RPC execution to service role.
6. **Add `/ready` and `/api/v1/health` to `RateLimitingMiddleware` bypass list** to prevent orchestrator probe death spirals.
7. **Migrate Shopify webhook deduplication** from in-memory set to database table `processed_webhook_events`.
8. **Enforce timestamp sequencing on Stripe subscription webhooks** to prevent out-of-order resurrection of canceled accounts.

### Should Fix Soon
9. **Wire `OpsAlertService.dispatch_incident()`** into webhook catch blocks, worker exception handlers, and billing checkout errors.
10. **Fix domain quota bypass** in `backend/app/api/v1/domains.py:re_audit_domain`.

### Can Wait
11. Add automated k6 / Locust concurrency load testing scripts.
12. Configure automated database point-in-time recovery (PITR) policies via Terraform.

---

## 31. Production Readiness Scorecard

| Domain | Status | Concrete Evidence |
|---|---|---|
| **Security** | **NOT READY** | Public anon key in symmetric JWT secret list allows universal tenant spoofing. |
| **Tenant Isolation** | **NOT READY** | Compromised by JWT forgery flaw; domain quota bypass in re-audit. |
| **Data Integrity** | **READY WITH CONDITIONS** | Foreign keys and unique constraints solid; DNS auto-fix credentials lost on restart. |
| **Reliability** | **READY WITH CONDITIONS** | Worker backoff & lease recovery verified; `/ready` probe throttled by limiter. |
| **Billing** | **NOT READY** | Shopify billing callback grants free Enterprise tier on exception. |
| **External Integrations**| **READY WITH CONDITIONS** | SSRF protection excellent; Shopify webhooks lack persistent deduplication. |
| **Cost Control** | **READY** | OpenAI client bounded by 15s timeout, heuristic fallback, and daily quotas. |
| **Observability** | **NOT READY** | Telegram alerting service fully implemented and tested but never wired to handlers. |
| **Disaster Recovery** | **DOCUMENTED ONLY** | No verified database backup/restore runbook or PITR pipeline. |
| **Performance** | **NOT BENCHMARKED** | Fast async execution, but no formal multi-user load testing performed. |
| **Deployment** | **READY WITH CONDITIONS** | Docker & Railway ready, but readiness probe susceptible to rate limiting. |
| **Testing** | **READY WITH CONDITIONS** | 169 tests pass, but unit tests mock auth and fail to detect JWT forgery bug. |

---

## 32. Recommended Next Phase: Phase 2.3 Hardening & Launch Gate

Before opening InboundCheck to any external beta or paying customer, execute a targeted, zero-feature remediation sprint:
- **Sprint 2.3.1:** Security & Auth Patch (Remove anon key from JWT validation, tighten CORS, lock down `rate_limit_windows` RLS).
- **Sprint 2.3.2:** Monetization & State Patch (Fix Shopify free upgrade bypass, persist DNS auto-fix credentials to PostgreSQL).
- **Sprint 2.3.3:** Reliability & SRE Patch (Exempt `/ready` from rate limiting, wire `OpsAlertService` to production handlers, persist Shopify webhooks).

---

## 33. Evidence & Code Citations

1. **JWT Anon Key Flaw:** [`backend/app/core/security.py:89`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/core/security.py#L89)
2. **Shopify Billing Free Upgrade:** [`backend/app/api/v1/shopify.py:284-297`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py#L284-L297)
3. **In-Memory Cloudflare Tokens:** [`backend/app/services/dns/auto_fixer.py:80`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/dns/auto_fixer.py#L80)
4. **Missing Table RLS:** [`supabase/migrations/20260925000001_p1_reliability_remediation.sql:140`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260925000001_p1_reliability_remediation.sql#L140)
5. **Readiness Probe Throttling:** [`backend/app/main.py:103`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L103)
6. **In-Memory Shopify Webhook Set:** [`backend/app/services/shopify/shopify_service.py:45`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/shopify/shopify_service.py#L45)
7. **Unwired Alerting Service:** [`backend/app/services/alerting/ops_alert_service.py:72`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alerting/ops_alert_service.py#L72)

---

## 34. Verification Commands

To reproduce the audit verification independently:

```powershell
# 1. Run Complete Backend Regression Test Suite (169 tests)
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1\backend"
py -m pytest tests/ -v

# 2. Run Complete Next.js Frontend Compilation (25 pages)
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1\frontend"
npm run build

# 3. Verify Clean Git Status (Zero unauthorized changes)
Set-Location "c:\Users\pc\Desktop\inboundcheck VERSION 1"
git status
```

---

## 35. Final Conclusion

InboundCheck demonstrates impressive engineering depth in its core domain: the DNS audit pipeline, RFC deliverability scoring, SSRF defenses, and worker jittered backoff mechanisms are institutional-grade.

However, **it is NOT production ready**. Exposing this codebase to production in its current state would allow malicious actors to trivially forge administrative credentials, upgrade themselves to enterprise subscriptions for free, delete distributed rate-limit counters, and cause deployment death spirals via readiness probe throttling.

Remediation of these exact 10 issues must take precedence before any marketing, beta invitations, or payment collection.

---

## TOP 10 RISKS BEFORE PRODUCTION

1. **Cryptographic JWT Forgery (P0)**  
   - **Responsible File / Function:** [`backend/app/core/security.py::_decode_supabase_jwt_symmetric`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/core/security.py#L82-L96)  
   - **Risk:** Public `NEXT_PUBLIC_SUPABASE_ANON_KEY` is accepted as a valid HMAC signing secret, allowing any user to forge tokens and take over any account.

2. **Shopify Billing Free Enterprise Upgrade (P0)**  
   - **Responsible File / Function:** [`backend/app/api/v1/shopify.py::shopify_billing_callback`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py#L276-L297)  
   - **Risk:** Swallows billing activation exceptions and unconditionally upgrades the merchant to an active Enterprise subscription for $0.

3. **Ephemeral Auto-Fix Cloudflare Credentials (P1)**  
   - **Responsible File / Function:** [`backend/app/services/dns/auto_fixer.py::save_provider_credentials`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/dns/auto_fixer.py#L80-L105)  
   - **Risk:** Credentials stored in process memory dictionary (`_mock_provider_creds`), completely vanishing upon server restart or across multi-container instances.

4. **Missing RLS on Distributed Rate Limiter Table (P1)**  
   - **Responsible File / Function:** [`supabase/migrations/20260925000001_p1_reliability_remediation.sql::rate_limit_windows`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260925000001_p1_reliability_remediation.sql#L140-L186)  
   - **Risk:** `rate_limit_windows` lacks RLS; clients can directly alter or delete counter rows via PostgREST to bypass rate limiting.

5. **Shopify Webhook In-Memory Deduplication (P1)**  
   - **Responsible File / Function:** [`backend/app/services/shopify/shopify_service.py::verify_and_process_webhook`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/shopify/shopify_service.py#L43-L59)  
   - **Risk:** Uses a local in-memory Python `set()`. Retries across replicas or after restarts re-process order receipts and duplicate failovers.

6. **Out-of-Order Stripe Webhook Subscription Resurrection (P1)**  
   - **Responsible File / Function:** [`backend/app/services/billing/stripe_service.py::process_webhook_event`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/billing/stripe_service.py#L555-L638)  
   - **Risk:** Fails to check event creation timestamps against `profile.updated_at`. A delayed `updated` event arriving after a `deleted` event reactivates canceled subscriptions.

7. **Deployment Death Spiral via `/ready` Throttling (P2)**  
   - **Responsible File / Function:** [`backend/app/main.py::RateLimitingMiddleware.dispatch`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L103-L108)  
   - **Risk:** Health probe path `/ready` is omitted from bypass list. High-frequency orchestrator probes trigger HTTP 429 and cause container termination.

8. **Overly Permissive CORS Regex (P2)**  
   - **Responsible File / Function:** [`backend/app/main.py::app.add_middleware(CORSMiddleware)`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py#L168)  
   - **Risk:** Unanchored regex `https://.*\.vercel\.app` allows any attacker-hosted site on Vercel to issue credentialed cross-origin requests.

9. **Unwired Operational Incident Alerting (P2)**  
   - **Responsible File / Function:** [`backend/app/services/alerting/ops_alert_service.py::dispatch_incident`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alerting/ops_alert_service.py#L72-L135)  
   - **Risk:** Alerting service is implemented and tested but never invoked anywhere in actual application error handlers or background worker crash paths.

10. **Domain Quota Bypass via Re-Audit (P2)**  
    - **Responsible File / Function:** [`backend/app/api/v1/domains.py::re_audit_domain`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/domains.py#L128-L162)  
    - **Risk:** Endpoint validates ownership of `domain_id` but audits the unvalidated query parameter `domain_name`, upserting arbitrary domains without enforcing tier quotas.
