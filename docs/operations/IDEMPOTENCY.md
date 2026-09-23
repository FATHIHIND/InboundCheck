# INBOUNDCHECK — IDEMPOTENCY & REPLAY GOVERNANCE MATRIX

**Document Version:** 1.0 (Phase 2 Production Reliability)  
**Governing Standard:** At-Least-Once Delivery Resilience & Zero Duplicate Side-Effects  
**Target Platform:** InboundCheck (FastAPI Backend, Background Workers, Webhook Ingestion, Supabase PostgreSQL)  
**Date:** 2026-09-23  

---

## 1. Executive Overview

In a distributed cloud architecture with asynchronous background workers, recurring automated audits, and external webhook retries (Shopify, Stripe, ESPs), **network packets and events are delivered at least once**. Systems that assume exactly-once delivery suffer from:
1. Multiple billing activations or duplicate subscription cancellations.
2. Alert storms spamming merchant Telegram channels with repeated notifications for the same delivery failure.
3. Wasteful redundant DNS and RBL query amplification.
4. Data corruption caused by concurrent mutations on the same database record.

InboundCheck classifies all operations into three strict categories:
* **Fully Idempotent:** Safe to execute multiple times with identical arguments; produces the identical system state.
* **Partially Idempotent:** Repeated executions produce consistent state but require intermediate gating or unique constraints to avoid redundant compute or partial state mutations.
* **Non-Idempotent:** Operations with external financial, communication, or state-changing side-effects that **must never run twice** for the same event identifier.

---

## 2. Master Idempotency Classification Matrix

| Subsystem / Operation | Classification | Re-execution Risk | Safeguard / Mechanism | State Transition & Evidence |
|---|:---:|---|---|---|
| **DNS On-Demand Audit** (`/api/v1/dns/audit`) | **Fully Idempotent** | Ephemeral compute load | Stateless read query against public DNS root resolvers | Pure functional resolver; does not mutate tenant state or billing credits. |
| **RBL Multi-Zone Scan** (`/api/v1/dns/rbl-scan`) | **Partially Idempotent** | Redundant DNSBL queries to public zones | In-memory cache + `rbl_scan_results` timestamp tracking | Latest scan is recorded with timestamp; subsequent queries within TTL read from cache. |
| **Scheduled Domain Audit Worker** (`audit_worker.py`) | **Partially Idempotent** | Duplicate worker processing same domain simultaneously | Database lease via atomic RPC `claim_due_domain_audits` (`FOR UPDATE SKIP LOCKED`) | Only the active lease holder can complete (`complete_domain_audit`) or fail (`fail_domain_audit`). Expired leases are safely reclaimed. |
| **SPF Merge Plan Generation** (`/api/v1/dns/spf-merge-plan`) | **Fully Idempotent** | Minimal CPU | Deterministic token parser and deduplicator | Identical inputs produce identical merged SPF strings without side-effects. |
| **Stripe Checkout Webhook** (`checkout.session.completed`) | **Non-Idempotent** | Duplicate subscription activation | `processed_webhook_events` DB table + in-memory LRU cache (`is_event_processed`) | Second arrival returns `{"status": "already_processed", "idempotent": True}` without updating profile twice. |
| **Stripe Cancellation Webhook** (`customer.subscription.deleted`) | **Fully Idempotent** | Re-asserting canceled state | State setter `subscription_status="canceled"` | Calling downgrade multiple times converges on the same `canceled` status. |
| **Shopify Order Created Webhook** (`/api/v1/shopify/webhooks/orders`) | **Non-Idempotent** | Duplicate delivery simulation and log inflation | `X-Shopify-Webhook-Id` tracking (`is_webhook_processed` with 24h memory eviction) | Repeated delivery with identical header returns `{"status": "already_processed"}` immediately. |
| **Shopify GDPR Redact Webhooks** (`customers/redact`, `shop/redact`) | **Fully Idempotent** | Redundant UPDATE/DELETE statements | SQL `UPDATE failover_logs SET recipient_email='[REDACTED_GDPR]' WHERE recipient_email=...` | Running redaction multiple times is a no-op once rows are anonymized. |
| **ESP Delivery Failure Ingestion** (`/api/v1/webhook/delivery-failure/{provider}`) | **Non-Idempotent** | Duplicate incident buffering | Unique DB constraint on `(esp_provider, provider_event_id)` via `insert_if_absent` | Replayed webhooks are acknowledged (`{"accepted": True}`) but existing record is reused; no second event row is inserted. |
| **Telegram Incident Alert Worker** (`failover_worker.py`) | **Non-Idempotent** | Merchant spam / alert storm | PostgreSQL Unique Index `idx_failover_logs_one_telegram_per_event` on `failover_logs(delivery_failure_event_id)` | Worker claims via atomic `claim_received_delivery_failure_events`. Unique index physically prevents duplicate Telegram dispatch logs. |
| **1-Click Cloudflare DNS Fix** (`/api/v1/dns/auto-fix/apply`) | **Partially Idempotent** | Duplicate DNS records in Cloudflare zone | Pre-flight DNS conflict query before POST / PUT | If record already exists with matching value, returns existing state without creating duplicate zone entries. |
| **1-Click DNS Rollback** (`/api/v1/dns/auto-fix/rollback`) | **Partially Idempotent** | Rollback of already deleted record | Inspects snapshot state; Cloudflare DELETE is idempotent (404 treated as success) | Restoring prior snapshot converges on original DNS configuration. |

---

## 3. Worker Concurrency & Atomic Lease Mechanics

### 3.1 Domain Audit Lifecycle
```
[ Due Domain: last_audited_at <= NOW() - 1h ]
                     │
                     ▼ (claim_due_domain_audits: FOR UPDATE SKIP LOCKED)
[ Worker A acquires lease for 15m (audit_lease_owner = Worker_A_UUID) ]
         │                                       │
         ▼ (Audit succeeds)                      ▼ (Worker crashes or unhandled failure)
[ complete_domain_audit() ]             [ Lease expires: audit_lease_until < NOW() ]
  ├── Releases lease (owner = NULL)              │
  ├── Sets last_audited_at = NOW()               ▼ (Next worker poll)
  └── Resets failure count to 0         [ Worker B re-claims domain cleanly ]
```

### 3.2 Concurrency Guarantees
* **Disjoint Worker Partitions:** When Worker A and Worker B invoke `claim_due_domain_audits` at the exact same millisecond, PostgreSQL locks candidate rows with `FOR UPDATE SKIP LOCKED`. Worker A receives rows 1..25, Worker B receives rows 26..50. Zero overlap is mathematically guaranteed.
* **Lease Loss Protection:** If Worker A takes 16 minutes to audit a domain with a 15-minute lease, Worker B may re-claim it. When Worker A eventually calls `complete_domain_audit(domain_id, worker_a_id)`, the SQL condition `WHERE audit_lease_owner = p_worker_id` evaluates to zero rows modified. Worker A's stale update is discarded safely.

---

## 4. Webhook Deduplication Protocols

### 4.1 Stripe Idempotency Protocol
1. Read incoming webhook header `Stripe-Signature`.
2. Compute HMAC-SHA256 signature and verify clock skew is within `±300s`.
3. Extract `event.id` (e.g. `evt_1O...`).
4. Execute `is_event_processed(event_id)`:
   - Check local in-memory LRU cache (`now - ts < 86400`).
   - Query `public.processed_webhook_events` where `id = event_id`.
   - If present, return `{"status": "already_processed", "idempotent": True}` immediately.
5. If absent: execute business logic (upgrade/downgrade), then call `mark_event_processed(event_id)`.

### 4.2 Shopify Idempotency Protocol
1. Extract `X-Shopify-Webhook-Id` header.
2. Verify timestamp `X-Shopify-Triggered-At` within `±300s`.
3. Verify `X-Shopify-Hmac-Sha256` signature.
4. Check in-memory store `_processed_webhooks[webhook_id]`. If present, return HTTP 200 with `status: already_processed`.
5. Mark `_processed_webhooks[webhook_id] = time.time()`.

### 4.3 ESP Delivery Failure Protocol
1. Extract `(provider, provider_event_id)` from webhook envelope.
2. Execute `insert_if_absent(event)`:
   - Evaluates PostgreSQL unique constraint `ON CONFLICT (esp_provider, provider_event_id) DO NOTHING`.
   - Returns existing row if replayed, preventing duplicate state.
3. Queue status remains `received` or `queued`. Replayed payloads return HTTP 200 without creating secondary worker tasks.

---

## 5. Non-Idempotent Safeguard Checklist for Engineers

1. **Never perform external API dispatches (Telegram, SMS, Stripe charges) inside synchronous webhook handlers.** Always buffer events first and delegate dispatches to worker daemons.
2. **Never execute an UPDATE without scoping to both resource ID and tenant ID.**
3. **Always wrap external webhook event IDs in deduplication checks prior to executing profile mutations.**
4. **Always ensure database unique constraints back up memory-level deduplication caches.**
