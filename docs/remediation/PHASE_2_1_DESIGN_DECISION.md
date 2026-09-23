# InboundCheck — Phase 2.1 Design Decision Document

**Document Identifier:** `PHASE_2_1_DESIGN_DECISION.md`  
**Governing Phase:** Phase 2.1 — P1 Reliability Remediation  
**Status:** Approved Architectural Specification  
**Date:** 2026-09-23  

---

## Executive Summary

Phase 2 Independent Verification confirmed core baseline health (153/153 tests passing, 25/25 frontend routes compiling, universal 5–10s outbound HTTP timeouts) but identified three critical reliability and operational gaps:
1. **P1 — Audit Retry Storm:** Background workers immediately retry failing domain audits every 30 seconds due to `fail_domain_audit` clearing leases without advancing eligibility timestamps.
2. **P1 — Process-Local Rate Limiting:** Global rate limiting is implemented only as a process-local in-memory middleware tracking `request.client.host` without reverse-proxy evaluation, user identity dimensions, or endpoint-specific limits for expensive AI/DNS operations.
3. **P2 — Alerting Reality Alignment:** Infrastructure alerts (`ALERT-DB-OUTAGE`, `ALERT-WORKER-BACKLOG`) were documented as operational runbooks but lacked practical integration and automated notification paths.

This document establishes the definitive, internally consistent design decisions required before code modifications begin.

---

## A. Retry Backoff Design

### 1. Root Cause Analysis
In `public.claim_due_domain_audits`, domain candidates are selected using:
```sql
WHERE is_active = true
  AND (last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval)
  AND (audit_lease_until IS NULL OR audit_lease_until < NOW())
```
When `fail_domain_audit` executes upon an audit failure, it previously set `audit_lease_owner = NULL` and `audit_lease_until = NULL`, while leaving `last_audited_at` unchanged (either `NULL` or older than 1 hour). Because `audit_lease_until` became `NULL`, the domain immediately satisfied the candidate predicate on the next worker sweep (approx. 30 seconds later), generating 120 redundant failing audits per hour per broken domain.

### 2. Decoupled Retry State (`next_audit_retry_at`)
To eliminate semantic ambiguity, **we decouple the active worker lease from the retry scheduling timestamp**:
* `audit_lease_owner` & `audit_lease_until`: Exclusively govern the active worker execution lease (15-minute lease while actively running).
* `next_audit_retry_at TIMESTAMPTZ`: Exclusively governs the retry scheduling timestamp when a domain has experienced one or more consecutive audit failures.

Candidate selection in `public.claim_due_domain_audits` is updated to:
```sql
WHERE is_active = true
  AND (last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval)
  AND (audit_lease_until IS NULL OR audit_lease_until < NOW())
  AND (next_audit_retry_at IS NULL OR next_audit_retry_at <= NOW())
```

### 3. Backoff Formula & Progression
* **Base Delay ($B$):** 120 seconds (2 minutes).
* **Maximum Delay ($M$):** 86,400 seconds (24 hours).
* **Progression:**
  $$\text{delay}_{\text{base}} = \min\left(M, B \times 2^{\min(\text{failure\_count} - 1, 10)}\right)$$
* **Randomized Jitter:** Add uniform jitter of $+0\%$ to $+25\%$ of the calculated delay:
  $$\text{delay}_{\text{jittered}} = \text{delay}_{\text{base}} \times (1.0 + \text{random}(0.0, 0.25))$$
* **Strict Upper Bound Enforcement:** Jitter is applied before the final ceiling cap so the total delay never exceeds the documented 24-hour maximum:
  $$\text{final\_delay} = \min(M, \lfloor\text{delay}_{\text{jittered}}\rfloor)$$

#### Concrete Progression Table:
| Failure Count | Base Delay | Multiplier | Jitter Range (+0–25%) | Final Retry Window |
|:---:|:---:|:---:|:---:|:---:|
| 1 | 120s | $2^0 = 1$ | 0s – 30s | 120s – 150s (~2m) |
| 2 | 120s | $2^1 = 2$ | 0s – 60s | 240s – 300s (~4m–5m) |
| 3 | 120s | $2^2 = 4$ | 0s – 120s | 480s – 600s (~8m–10m) |
| 4 | 120s | $2^3 = 8$ | 0s – 240s | 960s – 1,200s (~16m–20m) |
| 5 | 120s | $2^4 = 16$ | 0s – 480s | 1,920s – 2,400s (~32m–40m) |
| 6 | 120s | $2^5 = 32$ | 0s – 960s | 3,840s – 4,800s (~64m–80m) |
| 7 | 120s | $2^6 = 64$ | 0s – 1,920s | 7,680s – 9,600s (~2.1h–2.6h) |
| 8 | 120s | $2^7 = 128$ | 0s – 3,840s | 15,360s – 19,200s (~4.2h–5.3h) |
| 9 | 120s | $2^8 = 256$ | 0s – 7,680s | 30,720s – 38,400s (~8.5h–10.6h) |
| 10+ | 120s | $2^9 = 512$ | 0s – 15,360s | 61,440s – 76,800s (~17h–21.3h) |
| Persistent (11+) | Capped | — | Capped | **Strictly 86,400s (24h)** |

### 4. Lifecycle Reset
* Upon successful audit (`public.complete_domain_audit`):
  * `next_audit_retry_at = NULL`
  * `audit_failure_count = 0`
  * `last_audit_error = NULL`
  * `last_audited_at = NOW()`
  * `audit_lease_owner = NULL`
  * `audit_lease_until = NULL`

---

## B. Rate Limiting Architecture

### 1. Multi-Tier Hybrid Rate Limiting
To achieve multi-instance safety without introducing Redis, InboundCheck adopts a two-tier hybrid architecture:
1. **Tier 1 (Local In-Memory Sliding Window):** Microsecond-fast path for general ingress protection and unauthenticated endpoints.
2. **Tier 2 (PostgreSQL Atomic Windows):** Distributed token counting for high-cost variable operations across all application instances.

### 2. Endpoint Classification & Quotas

| Endpoint Class | Target Routes | Quota Dimension | Limit & Window | Storage Backend | Failure Policy |
|---|---|---|---|:---:|:---:|
| **General Ingress** | Global catch-all (`/*`) | Verified Client IP | 120 req / 60s | In-Memory (L1) | Fail-Open with warning |
| **High-Cost AI** | `/api/v1/ai/audit`, `/api/v1/ai/variants` | `user_id` + `endpoint` | 10 req / 60s | PostgreSQL (L2) + L1 | **Bounded Local Fallback (Max 3 req/min)** |
| **High-Cost DNS Audits** | `/api/v1/dns/audit`, `/api/v1/domains/*/audit` | `user_id` + `domain_id` + `endpoint` | 15 req / 60s (User) / 2 req / 60s (Domain) | PostgreSQL (L2) + L1 | **Bounded Local Fallback (Max 5 req/min)** |
| **High-Cost RBL Probes** | `/api/v1/rbl/scan`, `/api/v1/rbl/lookup` | `user_id` + `endpoint` | 15 req / 60s | PostgreSQL (L2) + L1 | **Bounded Local Fallback (Max 5 req/min)** |
| **Security Sensitive** | `/api/v1/shopify/webhooks/*`, `/api/v1/billing/webhook` | Verified Source IP / Webhook ID | 60 req / 60s | In-Memory (L1) | Fail-Closed on invalid signatures |

### 3. Identity Dimension Prioritization
* **Authenticated Requests:** Rate limits track `user_id` extracted from cryptographically verified Supabase JWT Bearer tokens. Multiple team members or merchant employees behind a single corporate IP will never exhaust each other's quota.
* **Unauthenticated Requests:** Rate limits track verified client IP resolved through the Trusted Proxy Model.
* **Targeted Resource Dimension:** For manual re-audits (`/api/v1/domains/{domain_id}/audit`), quota tracks `user_id` + `domain_id` to prevent multi-domain amplification attacks.

---

## C. Trusted Proxy Model

### 1. Threat Model & Forwarded Header Spoofing
Untrusted public clients routinely inject spoofed headers:
```http
X-Forwarded-For: 8.8.8.8
CF-Connecting-IP: 1.1.1.1
```
If an application reads these headers directly from untrusted network peers, malicious actors can bypass IP rate limits or frame innocent third parties.

### 2. Network Trust Verification Rules
The application verifies whether `request.client.host` belongs to an explicitly configured trusted proxy list before parsing any proxy headers:

```
[ Inbound Request Received ]
             │
             ▼
Is request.client.host in TRUSTED_PROXY_SOURCES?
             ├─────────────────────────────────────────────────┐
             │ YES                                             │ NO
             ▼                                                 ▼
Check CF-Connecting-IP                                DISCARD ALL FORWARDED HEADERS
    │                                                 Use request.client.host directly
    ├─ Present & Valid IP ──► Return CF-Connecting-IP
    │
    └─ Missing or Invalid ──► Inspect X-Forwarded-For
                                  │
                                  ├─ Parse comma-separated IPs
                                  └─ Select rightmost untrusted hop
```

### 3. Explicit Trusted Sources (`TRUSTED_PROXY_SOURCES`)
* **Loopback:** `127.0.0.1`, `::1` (Local testing, container health checks).
* **Configured CIDRs:** Specified explicitly via environment variable `TRUSTED_PROXY_CIDRS` (e.g., Railway private subnet, Cloudflare edge IP ranges).
* **Default Stance:** If `TRUSTED_PROXY_CIDRS` is unset, ONLY loopback (`127.0.0.1`, `::1`) is trusted. No blind trust of RFC 1918 private ranges unless explicitly declared.

---

## D. Rate Limiter Failure Policy

### Prohibited Behavior
```
DATABASE DOWN ──► RATE LIMITER BYPASS ──► UNLIMITED EXPENSIVE REQUESTS
```
This behavior is strictly prohibited.

### Differentiated Failure Specifications

#### 1. Low-Cost / General Ingress Endpoints
* If the limiter backend encounters an error:
  * Falls back to local in-memory tracking.
  * Logs an operational warning (`[RATE_LIMIT_DEGRADED]`).
  * Fails open only if memory capacity is exceeded, preserving basic application accessibility.

#### 2. Expensive Endpoints (AI, DNS Diagnostics, RBL Probes)
* If database-backed rate limit storage is unreachable:
  * **Bounded Local Fallback Policy:** The endpoint falls back to a **strict conservative in-memory quota**:
    * AI Endpoints: **Max 3 requests / minute** per instance.
    * DNS Diagnostics: **Max 5 requests / minute** per instance.
    * RBL Probes: **Max 5 requests / minute** per instance.
  * If the local burst budget is exhausted while the database is down, the endpoint **fails closed** returning `HTTP 429 Too Many Requests` with:
    ```json
    {
      "detail": "Rate limit service temporarily degraded. Request rejected under conservative safety budget."
    }
    ```
  * Unlimited expensive operations can **never** occur during an infrastructure outage.

---

## E. Alerting Architecture

### 1. Alert Reality Matrix & Classification Taxonomy

| Alert Identifier | Target Condition | Mechanism | Classification |
|---|---|---|:---:|
| `ALERT-CRITICAL-DELIVERABILITY` | Domain score < 70 or listed on >= 2 RBLs | `alert_dispatcher.py` -> Merchant Telegram | **IMPLEMENTED + AUTOMATED** |
| `ALERT-FAILOVER-INCIDENT` | ESP webhook delivery failure | `telegram_alert_service` -> Merchant Telegram | **IMPLEMENTED + AUTOMATED** |
| `ALERT-DB-OUTAGE` | `/ready` returns HTTP 503 | Endpoint health signal; requires external uptime monitor | **DOCUMENTED ONLY / HEALTH SIGNAL** |
| `ALERT-WORKER-BACKLOG` | Unaudited domains backlog > 200 | Database query runbook | **DOCUMENTED ONLY** |
| `ALERT-WEBHOOK-FAILURES` | Webhook 4xx/5xx rate > 5% | `ops_alert_service.py` -> Ops Webhook/Telegram | **IMPLEMENTED + AUTOMATED** (When configured) |
| `ALERT-BILLING-FAILURES` | Repeated checkout session errors | `ops_alert_service.py` -> Ops Webhook/Telegram | **IMPLEMENTED + AUTOMATED** (When configured) |

### 2. Operational Alert Dispatcher (`ops_alert_service.py`)
* **Transport:** Sends structured JSON payloads via HTTPS to `OPS_ALERT_WEBHOOK_URL` (Slack, Discord, or generic incident webhook) and/or `OPS_ALERT_TELEGRAM_BOT_TOKEN`.
* **Security & Confidentiality:**
  * Webhook URLs and tokens stored strictly in environment secrets; never logged.
  * Payload sanitization: all authentication tokens, cookies, secrets, and customer PII are strictly scrubbed.
* **Zero Alert Fatigue:**
  * **Thresholding:** Sustained failures only (e.g. >= 3 consecutive failures over 5 minutes).
  * **Flapping Cooldown:** Minimum 15-minute suppression window per incident fingerprint.
* **Fail-Safe Dispatch:**
  * 5.0s client timeout.
  * 0 retries on webhook failure.
  * Dispatched asynchronously via FastAPI background tasks; alerting failures **never** block user requests, workers, or webhook handlers.

---

## F. Manual Audit Abuse Protection

### 1. Semantic Separation
* **Automated Worker Sweeps:** Bound by `next_audit_retry_at` and tier-based interval schedules (1 hour to 24 hours).
* **Manual Re-Audits (`POST /domains/{domain_id}/audit`):** Triggered on-demand by authenticated merchants inspecting DNS record updates. They do not block on worker lease schedules.

### 2. Abuse Safeguards
To prevent a malicious or automated client from using manual audits to circumvent backoff:
1. **Per-Domain Manual Audit Limit:** Max **2 requests per 60 seconds** per domain.
2. **Per-User Manual Audit Limit:** Max **10 requests per 60 seconds** across all domains owned by the tenant.
3. **Quota Violation Response:** Returns `HTTP 429 Too Many Requests` with retry-after header.
4. **Successful Audit State Reset:** When an audit executes successfully, it atomically resets `next_audit_retry_at = NULL` and `audit_failure_count = 0`.

---

## G. Database Impact & Concurrency Model

### 1. Schema Migration: `20260925000001_p1_reliability_remediation.sql`
1. Add column to `public.monitored_domains`:
   ```sql
   ALTER TABLE public.monitored_domains
     ADD COLUMN IF NOT EXISTS next_audit_retry_at TIMESTAMPTZ;

   CREATE INDEX IF NOT EXISTS idx_monitored_domains_retry_schedule
     ON public.monitored_domains (next_audit_retry_at)
     WHERE is_active = true AND next_audit_retry_at IS NOT NULL;
   ```

2. Atomic Distributed Rate Limiting Table:
   ```sql
   CREATE TABLE IF NOT EXISTS public.rate_limit_windows (
     bucket_key TEXT NOT NULL,
     window_start BIGINT NOT NULL,
     request_count INTEGER NOT NULL DEFAULT 1,
     expires_at TIMESTAMPTZ NOT NULL,
     PRIMARY KEY (bucket_key, window_start)
   );

   CREATE INDEX IF NOT EXISTS idx_rate_limit_windows_expires
     ON public.rate_limit_windows (expires_at);
   ```

3. Atomic Token Consumption RPC (`public.consume_rate_limit`):
   ```sql
   CREATE OR REPLACE FUNCTION public.consume_rate_limit(
     p_bucket_key TEXT,
     p_max_requests INTEGER,
     p_window_seconds INTEGER
   )
   RETURNS JSONB
   LANGUAGE plpgsql
   SECURITY DEFINER
   SET search_path = public, pg_temp
   AS $$
   DECLARE
     v_now_epoch BIGINT := EXTRACT(EPOCH FROM NOW())::BIGINT;
     v_window_start BIGINT := (v_now_epoch / p_window_seconds) * p_window_seconds;
     v_expires_at TIMESTAMPTZ := TO_TIMESTAMP(v_window_start + (p_window_seconds * 2));
     v_count INTEGER;
   BEGIN
     INSERT INTO public.rate_limit_windows (bucket_key, window_start, request_count, expires_at)
     VALUES (p_bucket_key, v_window_start, 1, v_expires_at)
     ON CONFLICT (bucket_key, window_start)
     DO UPDATE SET request_count = rate_limit_windows.request_count + 1
     RETURNING request_count INTO v_count;

     -- Opportunistic cleanup of stale rows (< 1% of calls)
     IF random() < 0.01 THEN
       DELETE FROM public.rate_limit_windows WHERE expires_at < NOW();
     END IF;

     RETURN jsonb_build_object(
       'allowed', (v_count <= p_max_requests),
       'current_requests', v_count,
       'remaining', GREATEST(0, p_max_requests - v_count),
       'reset_seconds', (v_window_start + p_window_seconds) - v_now_epoch
     );
   END;
   $$;
   ```

### 2. Concurrency & Performance Analysis
* **Atomicity:** `INSERT ... ON CONFLICT DO UPDATE` guarantees that increments are completely serialized per `(bucket_key, window_start)` without application-level TOCTOU races.
* **Row Growth:** Expired windows have a 2-window TTL and are pruned opportunistically (1% sampling) and via scheduled background cleanup.
* **Contention:** Different keys and different windows do not lock each other; row-level locks are held for <1ms.

---

## H. Security Considerations

1. **Anti-Spoofing Verification:** Forwarded headers (`CF-Connecting-IP`, `X-Forwarded-For`) are discarded unless the direct socket connection originates from a verified trusted proxy source.
2. **BOLA / IDOR Verification:** Manual audits continue to enforce ownership validation: `owned_domain = next((d for d in existing_domains if str(d.get("id")) == str(domain_id)), None)`.
3. **No Credential Exposure:** Error sanitization regex masks tokens before writing to `last_audit_error`.

---

## I. Cost Considerations

1. **DNSBL Protection:** Exponential backoff ensures unresolvable domains do not generate query floods against Spamhaus/Barracuda.
2. **LLM Expense Bound:** Enforcing 10 req/min user quota + 3 req/min fallback quota strictly caps maximum variable token expense.
3. **Database Overhead:** Fixed-window upserts take ~1–2ms and execute only on high-cost endpoints.

---

## J. Rollback Plan

1. **Database Rollback:**
   * Drop column `next_audit_retry_at` if necessary (backward-compatible, ignored by older code).
   * Drop table `rate_limit_windows` and RPC `consume_rate_limit`.
   * Revert `fail_domain_audit` to previous version.
2. **Application Rollback:**
   * Git revert cleanly restores in-memory limiter and previous audit loop behavior.
   * Zero data loss: `monitored_domains` and `profiles` records remain completely intact.
