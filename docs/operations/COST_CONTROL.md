# INBOUNDCHECK — VARIABLE COST CONTROL & ABUSE PROTECTION

**Document Version:** 1.0 (Phase 2 Reliability & Cost Control)  
**Governing Standard:** Predictable Infrastructure Unit Economics & Resource Ceiling Bounds  
**Target Platform:** InboundCheck (FastAPI Backend, Background Workers, External Integrations)  
**Date:** 2026-09-23  

---

## 1. Executive Summary

InboundCheck interacts with multiple third-party APIs and consumes computational and network resources on a per-request or per-record basis. Without strict concurrency ceilings, query throttling, and token quotas, variable operational expenses could scale unbounded or suffer abuse from adversarial traffic.

This document identifies every variable-cost driver across the platform, establishes hard resource bounds, documents known provider pricing (or explicitly flags unknown metrics), and maps abuse protection mechanisms.

---

## 2. Variable-Cost Operations Matrix

| Operation | Third-Party Provider | Cost Driver | Current System Usage | Abuse Vector | Enforced System Limit | Plan Impact / Tier Guard | Estimated Unit Cost |
|---|---|---|---|---|---|---|---|
| **DNS Resolution (SPF, DKIM, DMARC, BIMI)** | Public Resolver (Cloudflare `1.1.1.1`, Google `8.8.8.8`, Quad9 `9.9.9.9`) | UDP/TCP DNS queries & bandwidth | ~15 DNS queries per full audit | Rapid repeated audits against hundreds of domains | Per-IP Rate Limiting (120 req/min) + domain audit lease interval (1 hour) | Available on all tiers; minimum 1h interval between automatic sweeps | $0.00 (Public Root Resolvers) |
| **RBL Multi-Zone Probes (10 Lists)** | DNSBL Operators (Spamhaus, Barracuda, SpamCop, etc.) | DNSBL query volume | 10–20 DNS queries per domain scan | High-frequency bulk scanning triggering DNSBL rate-limit blocking codes (`127.255.255.x`) | Bounded concurrency (`Semaphore(10)`) + hard 1.5s per-query timeout + cache TTL | All tiers; scans cached; worker sweeps spaced by tier interval | $0.00 (Free Community Tier) / Commercial volume fees: `UNKNOWN — VERIFY BEFORE PRODUCTION` |
| **AI Content Lab Analysis & Variant Generation** | Neutral OpenAI-Compatible LLM Adapter (`LLM_API_BASE`) | Token consumption (Prompt + Completion tokens) | ~300 prompt tokens + ~250 completion tokens per audit | Submitting massive text blocks or automated loop scripts | In-memory token length limits (capped at 4,000 characters) + sliding window rate limit | Growth & Enterprise tiers only (`BIL-02`) | Depends on underlying LLM model endpoint; `UNKNOWN — VERIFY BEFORE PRODUCTION` |
| **Telegram Incident Alerts** | Telegram Bot API (`api.telegram.org`) | Outbound HTTPS requests | Dispatched only on permanent delivery failures (`bounce`, `dropped`, `rejected`) | Spamming fake webhook events to trigger continuous Telegram messages | Unique DB constraint (`idx_failover_logs_one_telegram_per_event`) + webhook HMAC verification | Included on all active monitoring plans | $0.00 (Telegram Bot API has no per-message fees) |
| **Cloudflare Zone Auto-Remediation** | Cloudflare REST v4 API | API calls per DNS record modification | 1–3 REST requests per remediated record | Repeatedly clicking apply/rollback | Rate-limited + pre-flight conflict check to avoid duplicate calls | Growth & Enterprise tiers only | Included in standard Cloudflare account tier |
| **Shopify Admin REST / GraphQL Queries** | Shopify Admin API | GraphQL API Points (Bucket capacity 1,000 points, restore rate 50 pts/s) | ~10 points per billing charge or store profile check | Fast loops querying store profile or unneeded billing mutations | Explicit 10.0s HTTP client timeout + only called on install / billing change | Mandatory for Shopify store integrations | Included in Shopify App Partner Program |
| **Stripe Checkout & Billing Portal** | Stripe API | API calls per checkout session or invoice query | 1 API call per checkout initiation or invoice fetch | Brute-force checkout session generation | User JWT authenticated + rate-limited via client IP | Billed per successful transaction | Standard Stripe processing fee (2.9% + $0.30 per charge) |

---

## 3. Variable-Cost Abuse Safeguards

### 3.1 Rate Limiting Architecture
* **Global Edge / Ingress IP Limiter:** `RateLimitingMiddleware` in `backend/app/main.py` enforces a sliding window maximum of **120 requests per 60 seconds per IP address**, automatically evicting stale IPs to prevent memory leaks.
* **DNS Audit Lease Interval:** Background workers cannot audit a domain more frequently than once every `interval_seconds` (default: 3600s / 1 hour), preventing audit loops from consuming excessive resolver capacity.
* **Payload Size Ceilings:**
  * All incoming webhook endpoints (Shopify, Stripe, ESPs) strictly reject payloads larger than **1 MB (1,048,576 bytes)** with `HTTP 413 Content Too Large`.
  * Remote BIMI SVG logo and VMC certificate fetchers enforce an early-streaming termination at **500 KB**.

### 3.2 AI Inference Cost Containment
* **Character Truncation:** Input templates for email copy optimization are bounded before passing to the inference client.
* **Stateless Heuristics Pre-Filter:** If the external LLM endpoint is unreachable, timed out, or unconfigured, `ContentOptimizer` falls back to zero-cost local regex heuristics (detecting trigger words, uppercase density, punctuation spam) without failing customer workflows.

### 3.3 Alert Dispatch Storm Suppression
* Delivery failure alerts from ESP webhooks are deduplicated at ingestion on `(esp_provider, provider_event_id)`.
* In addition, the PostgreSQL partial unique index `idx_failover_logs_one_telegram_per_event` guarantees that even if a worker crashes and retries, only one Telegram message is dispatched per incident.

---

## 4. Cost Governance & Monitoring Recommendations

1. **LLM Inference Budget Cap:** If commercial model endpoints (e.g. OpenAI, Anthropic, or DeepSeek API) are configured in production, set monthly spending limits in the provider console to prevent rogue overage charges.
2. **DNSBL Commercial Usage Tracking:** If domain monitoring scales beyond 5,000 active domains, verify whether public open resolvers trigger Spamhaus query volume notices (`127.255.255.x`), which requires a dedicated Spamhaus DQS key (`UNKNOWN — VERIFY BEFORE PRODUCTION`).
3. **Database Storage Growth:** Prune raw DNS audit logs older than 90 days via scheduled pg_cron maintenance or Supabase edge functions to bound table sizes.
