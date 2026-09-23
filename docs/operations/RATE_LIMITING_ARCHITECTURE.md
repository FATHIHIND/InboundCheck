# InboundCheck — Production Rate Limiting Architecture

**Document Version:** 1.0 (Phase 2.1 Reliability & Abuse Protection)  
**Governing Standard:** Multi-Tier Identity-Aware Ingress & Resource Governance  
**Target Platform:** FastAPI Backend, Background Workers, Ingress Proxies  
**Date:** 2026-09-23  

---

## 1. Executive Summary & Topology

InboundCheck is a high-precision transactional deliverability SaaS engineered for eCommerce and Shopify merchants. The production topology consists of:
* **Edge Ingress / Reverse Proxy:** Cloudflare edge routing and Railway/Docker container orchestration.
* **API Service:** FastAPI (Python 3.12+) running asynchronously.
* **Persistence Layer:** Supabase PostgreSQL with connection pooling (PgBouncer) and Row Level Security (RLS).
* **Multi-Instance Capability:** Production deployments can scale horizontally across multiple container instances.

A process-local in-memory rate limiter cannot protect expensive variable-cost resources across multiple instances. Furthermore, blindly reading client-supplied headers (`X-Forwarded-For`, `CF-Connecting-IP`) allows trivial IP spoofing.

This document establishes the production rate limiting architecture, proxy trust model, storage strategy, and failure policies.

---

## 2. Threat Model & Abuse Vectors

1. **Forwarded Header Spoofing:** Malicious clients inject arbitrary `X-Forwarded-For` or `CF-Connecting-IP` headers to evade IP-based rate limiting or starve quotas of third parties.
2. **Shared Office NAT Collisions:** Multiple legitimate merchants or team members operating behind the same public office IP share an IP quota; an IP-only limiter prematurely throttles legitimate tenants.
3. **Multi-Domain Amplification:** An authenticated user with 20 domains submits concurrent audit requests across all domains, multiplying backend DNS/AI workload 20x.
4. **Variable-Cost Denial of Wallet:** Scripted loops targeting `/api/v1/ai/audit` or `/api/v1/dns/audit` exhaust OpenAI/LLM tokens or cause DNSBL query volume blocks.
5. **Limiter Storage Outage Abuse:** If the shared limiter fails open completely during database degradation, an attacker can launch an amplified resource exhaustion attack.

---

## 3. Trusted Proxy Model & IP Resolution

### 3.1 Trust Verification Hierarchy
Forwarded headers are **never** trusted based solely on their presence in the HTTP request. The immediate network peer (`request.client.host`) must first match the configured trusted proxy list:

```python
TRUSTED_PROXY_SOURCES = {"127.0.0.1", "::1"} | CONFIGURED_TRUSTED_CIDRS
```

### 3.2 Resolution Algorithm
1. **Direct Untrusted Peer:** If `request.client.host` is NOT in `TRUSTED_PROXY_SOURCES`:
   * Discard all `CF-Connecting-IP`, `X-Forwarded-For`, and `X-Real-IP` headers.
   * Return `request.client.host` directly as the client IP.
2. **Trusted Proxy Peer:** If `request.client.host` IS in `TRUSTED_PROXY_SOURCES`:
   * **Step A:** Check `CF-Connecting-IP`. If present and parses as a valid IPv4 or IPv6 address, return it (Cloudflare verified ingress).
   * **Step B:** If `CF-Connecting-IP` is absent, parse `X-Forwarded-For`. Split by comma and traverse the chain from right to left, selecting the rightmost IP that does not belong to the trusted proxy list.
   * **Step C:** If headers are malformed or missing, fall back safely to `request.client.host`.

---

## 4. Rate Limit Dimensions & Resource Tiers

| Tier | Endpoints | Rate Limit Dimension | Quota (Limit / Window) | Backend Storage | Failure Policy |
|---|---|---|---|:---:|:---:|
| **Ingress L1** | All routes (`/*`) | Resolved Client IP | 120 req / 60s | In-Memory Sliding Window | Fail-Open with operational warning |
| **High-Cost AI** | `/api/v1/ai/audit`, `/api/v1/ai/variants` | `user_id` + `endpoint` | 10 req / 60s | PostgreSQL Windows (L2) + L1 | **Conservative Fallback (Max 3 req/min)** |
| **High-Cost DNS** | `/api/v1/dns/audit` | `user_id` + `endpoint` | 15 req / 60s | PostgreSQL Windows (L2) + L1 | **Conservative Fallback (Max 5 req/min)** |
| **Manual Re-Audit**| `/api/v1/domains/{domain_id}/audit` | `user_id` + `domain_id` | 2 req / 60s per domain (Max 10 / user) | PostgreSQL Windows (L2) + L1 | **Conservative Fallback (Max 1 req/min)** |
| **High-Cost RBL** | `/api/v1/rbl/scan`, `/api/v1/rbl/lookup` | `user_id` + `endpoint` | 15 req / 60s | PostgreSQL Windows (L2) + L1 | **Conservative Fallback (Max 5 req/min)** |
| **Security Sensitive**| `/api/v1/shopify/webhooks/*`, `/api/v1/billing/webhook` | Webhook ID / Client IP | 60 req / 60s | In-Memory (L1) | Fail-Closed on invalid signatures |

---

## 5. Storage Mechanism: PostgreSQL Fixed Windows vs Redis

### 5.1 Why Not Redis?
InboundCheck is an institutional Micro-SaaS. Adding Redis introduces:
* Additional external container or managed cloud cluster (Upstash / AWS ElastiCache).
* Network latency, TLS handshake overhead, and Redis connection pool maintenance.
* Increased infrastructure cost and operational failure surface.

### 5.2 PostgreSQL Atomic Window Implementation
PostgreSQL safely and efficiently coordinates multi-instance rate limits for expensive operations using an atomic upsert pattern:

```sql
CREATE TABLE IF NOT EXISTS public.rate_limit_windows (
  bucket_key TEXT NOT NULL,
  window_start BIGINT NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 1,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (bucket_key, window_start)
);
```

An atomic RPC function (`public.consume_rate_limit`) executes:
```sql
INSERT INTO public.rate_limit_windows (bucket_key, window_start, request_count, expires_at)
VALUES (p_bucket_key, v_window_start, 1, v_expires_at)
ON CONFLICT (bucket_key, window_start)
DO UPDATE SET request_count = rate_limit_windows.request_count + 1
RETURNING request_count;
```

* **Zero TOCTOU Races:** Completely serialized at row level.
* **Low Latency:** < 2ms execution time (negligible compared to 800ms DNS/LLM lookups).
* **Automatic Eviction:** Windows expire within 2 periods and are pruned opportunistically.

---

## 6. Differentiated Failure Policy

```
                                  [ Rate Limit Check Initiated ]
                                                │
                                                ▼
                                    Is DB Storage Reachable?
                                ┌───────────────┴───────────────┐
                                │ YES                           │ NO (Error / Timeout)
                                ▼                               ▼
                    Consume Token via RPC           [ Evaluate Endpoint Class ]
                                │                               │
                   ┌────────────┴────────────┐                  ├─────────────────────────────┐
                   │ Count <= Limit          │ Count > Limit    │ General Ingress             │ Expensive (AI/DNS/RBL)
                   ▼                         ▼                  ▼                             ▼
             Allow Request             Reject HTTP 429     Fail-Open (L1 Memory)      [ Conservative Local Budget ]
                                                           Log Warning                      │
                                                                               ┌────────────┴────────────┐
                                                                               │ Within Budget           │ Exceeded Budget
                                                                               ▼                         ▼
                                                                         Allow Request             Fail-Closed HTTP 429
```

1. **General Endpoints:** Fail-open with warning log if both database and in-memory table encounter failure.
2. **Expensive Endpoints (AI, DNS, RBL):**
   * Never fail open into unlimited requests.
   * Switch immediately to a **bounded conservative local budget** (AI: 3 req/min, DNS: 5 req/min).
   * Once local budget is reached while storage is offline, **fail closed** returning `HTTP 429 Too Many Requests`.

---

## 7. Cost & Operational Impact

1. **AI Token Conservation:** Strict 10 req/min user limit guarantees an individual user cannot run up runaway LLM billing.
2. **DNSBL Protection:** DNS diagnostic and RBL probes are bounded, protecting against open resolver rate blocks.
3. **Database Performance:** Rate limiting table row count remains bounded (< 5,000 active keys) via automatic expiration indexing and cleanup.
