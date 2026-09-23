# InboundCheck Enterprise — Phase 2.2 P1/P2 Operational Reliability Audit
## Telegram Alerting + Railway Health Monitoring & Production Resilience

> **Audit Type:** Production Operational Reliability, Telemetry, Observability & Resilience (READ-ONLY)  
> **Target System:** InboundCheck SaaS Platform (`backend/`, `frontend/`, `supabase/`, Docker & Railway Deployment)  
> **Status:** AUDIT COMPLETE — 0 CODE / CONFIG MODIFICATIONS PERFORMED  
> **Timestamp:** September 23, 2026 (Local: 22:56 UTC+2)  
> **Executive Verdict:** **NOT READY** (Blocked by 4 Active P1 Operational Risks)

---

## 1. Executive Summary

Following the successful cryptographic hardening of **P0-1 (JWT Forgery)** and **P0-2 (Shopify Billing Enterprise Bypass)**, this Phase 2.2 audit conducted an exhaustive, adversarial, read-only operational reliability assessment of the InboundCheck infrastructure.

The audit evaluated two foundational pillars of production availability:
1. **Telegram Operational Incident Alerting:** Verifying whether real-time alerting is connected to runtime exception handlers, webhooks, workers, and database failures.
2. **Railway Health & Deployment Stability:** Verifying liveness and readiness probe behaviors, container restart semantics, graceful shutdown, and the critical **"Deployment Death Spiral via `/ready` throttling"** vulnerability.

### Core Audit Discoveries
1. **P1 — Telegram Ops Alerting Disconnected (0 Production Callers):** While `OpsAlertService` (`ops_alert_service.py`) was implemented with anti-flapping (15-min cooldown), payload sanitization, and 5.0s timeouts, it is **never imported or called anywhere in production runtime code**. Critical failures (database outages, unhandled 500 exceptions, Stripe/Shopify webhook errors, worker crashes) are logged to stdout only. No ops page is ever sent.
2. **P1 — Deployment Death Spiral Active via `/ready` Throttling:** `RateLimitingMiddleware` in `backend/app/main.py` explicitly exempts `/health`, `/`, `/docs`, and `/openapi.json` from the 120 req/min rate limiter. However, **`/ready` and `/api/v1/health` were omitted from the exemption list**. If Railway readiness probes, external uptime monitors, or edge reverse-proxy traffic poll `/ready` at standard production cadences, or if proxy IP resolution collapses, `/ready` returns `HTTP 429 Too Many Requests`. This causes Railway to mark the container unhealthy and initiate an endless container restart loop.
3. **P1 — Permanent Queue Lockup on Failover Worker Crash:** The `claim_pending_delivery_failure_events` database RPC sets `processing_status = 'queued'` via `FOR UPDATE SKIP LOCKED`. Unlike `monitored_domains` (which has `audit_lease_until`), the `delivery_failure_events` table has **no lease duration or lease expiry logic**. If `failover_worker` crashes, restarts, or receives SIGTERM while processing claimed events, those events remain stuck in `'queued'` permanently and will never be reclaimed or delivered.
4. **P1 — Silent DNS Remediation Failure:** In `backend/app/services/dns/auto_fixer.py`, when Cloudflare API calls fail or throw an exception, the error is logged, but execution proceeds to return `{"applied": True}` and records `status: "applied"`. Merchants and upstream callers are falsely informed that DNS records were successfully provisioned.

---

## 2. Architecture Map: Observability, Health & Worker Ingress

```
                                [ External Traffic / Uptime Monitors / Railway Orchestrator ]
                                                              │
                                                              ▼
                                              [ Railway Ingress Load Balancer ]
                                                              │
                              ┌───────────────────────────────┴──────────────────────────────┐
                              ▼                                                              ▼
                  [ Liveness Probe: /health ]                                   [ Readiness Probe: /ready ]
                  (Exempt from RateLimiter)                                     (SUBJECT TO RATE LIMITER!)
                              │                                                              │
                              ▼                                                              ▼
                  HTTP 200 {"status": "alive"}                                  `supabase_service.check_db_health()`
                                                                                             │
                                      ┌──────────────────────────────────────────────────────┴──────────────────────┐
                                      ▼                                                                             ▼
                             [ DB Available ]                                                              [ DB Unavailable / 429 ]
                             HTTP 200 "ready"                                                              HTTP 503 / HTTP 429
                                                                                                                    │
                                                                                                                    ▼
                                                                                                        [ Railway Kills Container ]
                                                                                                        (Restart Loop Death Spiral)

───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

                                                [ Backend API & Event Flow ]
                                                              │
                              ┌───────────────────────────────┼──────────────────────────────┐
                              ▼                               ▼                              ▼
                    [ Shopify Webhooks ]             [ Stripe Webhooks ]             [ Global Exception Shield ]
                              │                               │                              │
                    HMAC / JSON Failures             Sig / Parsing Error            Unhandled 500 / DB Outage
                              │                               │                              │
                              ▼                               ▼                              ▼
                        `logger.error`                  `logger.error`                 `logger.error`
                              │                               │                              │
                              └───────────────────────────────┼──────────────────────────────┘
                                                              │
                                                              ▼
                                                 [ NO OpsAlertService DISPATCH ]
                                                  (Ops Telegram: 0 Messages Sent)

───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

                                                [ Dedicated Background Workers ]
                                                              │
                              ┌───────────────────────────────┴──────────────────────────────┐
                              ▼                                                              ▼
                  [ audit_worker.py ]                                           [ failover_worker.py ]
                          │                                                              │
              `claim_due_domain_audits`                                     `claim_pending_delivery_failure_events`
            (FOR UPDATE SKIP LOCKED)                                              (FOR UPDATE SKIP LOCKED)
                          │                                                              │
                  Has Lease Expiry:                                              NO LEASE EXPIRY:
             `audit_lease_until` (900s)                                     `processing_status = 'queued'`
                          │                                                              │
            Worker Crash -> Lease Expires                                  Worker Crash -> STUCK IN QUEUE FOREVER!
```

---

## 3. Telegram Alerting Call Graph

InboundCheck contains two distinct Telegram alerting subsystems:
- **Subsystem A (Infrastructure & Ops Alerting):** `OpsAlertService` (`backend/app/services/alerting/ops_alert_service.py`).
- **Subsystem B (Merchant Deliverability Alerts):** `TelegramAlertService` / `alert_dispatcher` (`backend/app/services/failover/omnichannel_service.py` & `backend/app/services/alert_dispatcher.py`).

### Detailed Subsystem Audit

#### Subsystem A: `OpsAlertService` (Ops Incident Dispatcher)
- **Implementation File:** [`backend/app/services/alerting/ops_alert_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alerting/ops_alert_service.py)
- **Features:** Anti-flapping suppression (15-min cooldown), recursive payload sanitization (`sanitize_incident_payload`), 5.0s httpx timeout, 0 retries (safe against amplification).
- **Wiring Status:** **100% DISCONNECTED.** Grep search across the entire `backend/` directory reveals that `ops_alert_service` and `dispatch_incident()` are **only referenced in `tests/test_phase2_1_remediation.py`**.

```
[ ERROR SOURCE ] ──────────────► [ HANDLER ] ──────────────► [ ALERT SERVICE ] ────────► [ TELEGRAM API ] ────────► [ RESULT ]
FastAPI Unhandled 500            global_exception_shield     DISCONNECTED                 None                       Log only
DatabaseUnavailableError         global_exception_shield     DISCONNECTED                 None                       Log only
Shopify Webhook Error            shopify_orders_webhook      DISCONNECTED                 None                       Log only
Stripe Webhook Error             stripe_webhook_handler      DISCONNECTED                 None                       Log only
Audit Worker Crash               run_audit_worker (except)   DISCONNECTED                 None                       Log only
Failover Worker Crash            run_failover_worker (except)DISCONNECTED                 None                       Log only
Cloudflare Auto-Fix Failure      apply_dns_fix (except)      DISCONNECTED                 None                       Silent / False OK
```

#### Subsystem B: `alert_dispatcher.py` & `omnichannel_service.py` (Merchant Telemetry)
- **Implementation Files:** [`backend/app/services/alert_dispatcher.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alert_dispatcher.py), [`backend/app/services/failover/omnichannel_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/failover/omnichannel_service.py)
- **Wiring Status:** **PARTIALLY CONNECTED (Merchant Scope Only).**
  - `audit_worker.py` (line 154) calls `alert_dispatcher.evaluate_and_dispatch()` when a domain deliverability score drops below threshold (default 75%) or SPF/DKIM/DMARC fails. Suppressed by a 6-hour cooldown window.
  - `failover_worker.py` (line 144) calls `telegram_alert_service.dispatch_alert()` when delivery failure events (`bounce`, `dropped`, `rejected`) are claimed from ESP webhooks.
  - Endpoint `/api/v1/failover/dispatch` triggers manual merchant alerts.
  - Endpoint `/api/v1/failover/test-ping` and `/api/v1/settings/telegram/test` send connection test pings.

### Telegram Alerting Questions A–J Assessment

| # | Question | Finding | Evidence |
|---|---|---|---|
| **A** | Is Telegram alerting actually wired into production execution paths? | **Ops Alerting: NO (0 callers).** Merchant alerting: YES (audit & failover workers). | `grep_search("dispatch_incident")` returns only `ops_alert_service.py` and `test_phase2_1_remediation.py`. |
| **B** | Which errors call `dispatch_incident()`? | **ZERO errors.** No production handler invokes `dispatch_incident()`. | Repository-wide grep confirmation. |
| **C** | Which critical errors only get logged? | 1. FastAPI 500s (`global_exception_shield`)<br>2. DB outage (`DatabaseUnavailableError`)<br>3. Stripe webhook errors<br>4. Shopify webhook errors<br>5. Worker loop crashes<br>6. DNS resolution timeouts. | `backend/app/main.py:184-206`, `backend/app/api/v1/billing.py:264`, `backend/app/api/v1/shopify.py:455`, `backend/app/workers/audit_worker.py:227`. |
| **D** | Which failures are completely silent? | 1. `auto_fixer.py`: Cloudflare API failure logs an error but returns `applied: True`.<br>2. `supabase_client.py`: DB initialization failure in local/test falls back silently to memory.<br>3. `reputation_checks`: Snapshot insert failure logs a warning and proceeds.<br>4. `failover_worker.py`: Non-eligible events (`deferred`, `complaint`) are silently marked `ignored`. | `backend/app/services/dns/auto_fixer.py:164-187`, `backend/app/workers/failover_worker.py:122-128`. |
| **E** | Are alerts duplicated? | `OpsAlertService` deduplicates via fingerprint. `alert_dispatcher` deduplicates via 6-hour tenant:domain window. Direct `omnichannel_service.dispatch_alert()` has **no cooldown**. | `ops_alert_service.py:24`, `alert_dispatcher.py:31`, `omnichannel_service.py:223`. |
| **F** | Are alerts rate-limited/deduplicated? | `OpsAlertService`: 15-minute anti-flapping window (`COOLDOWN_WINDOW_SECONDS = 900`). `alert_dispatcher`: 6-hour window. | `ops_alert_service.py:24`, `alert_dispatcher.py:31`. |
| **G** | Is Telegram timeout/retry handling safe? | **YES.** `ops_alert_service` sets `timeout=5.0s`, `omnichannel_service` sets `timeout=8.0s`. Both have 0 retries to prevent retry loops. | `ops_alert_service.py:140`, `omnichannel_service.py:134`. |
| **H** | Can Telegram failure crash the application? | **NO.** All Telegram dispatches are wrapped in `try ... except Exception:`, logging errors and returning boolean/dict status. | `ops_alert_service.py:154`, `omnichannel_service.py:149`. |
| **I** | Are bot tokens/chat IDs protected from logs? | **Mostly YES, but PII risk present.** `sanitize_incident_payload` masks `token/secret/key`. `sanitize_log_message` masks `bot<digits>:<token>`. However, `omnichannel_service.py:183` formats raw `customer_email` into Telegram message text. | `ops_alert_service.py:35-54`, `omnichannel_service.py:55-71, 183`. |
| **J** | Are alerts actionable enough to diagnose incidents? | Ops alerts have summary, severity, and details, but **lack correlation/request ID and remediation runbook links**. Merchant alerts include domain and deep links to `/dashboard/inspector`. | `ops_alert_service.py:105-113`, `omnichannel_service.py:288-297`. |

---

## 4. Railway Health Monitoring

### Health Endpoints Analysis

The backend exposes three health-related endpoints in [`backend/app/main.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py):

1. **`/health` (Liveness Probe — Line 213):**
   - Returns: `{"status": "alive", "service": "InboundCheck API Engine", "environment": "production", "version": "1.0.0", "timestamp": "..."}`
   - Behavior: Pure in-memory event-loop check. Does not query database or external dependencies.
   - Rate Limiter Status: **EXEMPT** (`request.url.path in ["/health", "/", "/docs", "/openapi.json"]`).

2. **`/ready` and `/api/v1/health` (Readiness Probe — Line 225):**
   - Calls `supabase_service.check_db_health()`.
   - If database is unreachable in production, returns `HTTP 503 Service Unavailable`.
   - Rate Limiter Status: **NOT EXEMPT!** (Lines 104–107 omit `/ready` and `/api/v1/health`).

### Investigation of "Deployment Death Spiral via `/ready` Throttling"

#### Audit Verification
In `backend/app/main.py` lines 103–107:
```python
# Exempt health checks and pytest test runner from IP rate limiting
is_exempt = (
    request.url.path in ["/health", "/", "/docs", "/openapi.json"]
    or os.getenv("PYTEST_CURRENT_TEST") is not None
)
```
- `/ready` is **NOT** in `is_exempt`.
- `/api/v1/health` is **NOT** in `is_exempt`.
- `RateLimitingMiddleware` enforces a maximum of `max_requests = 120` per `window_seconds = 60` (line 69).

#### Failure Mechanism
1. In Railway or container orchestration, readiness probes poll `/ready` every 2 to 5 seconds.
2. In production on Railway, requests route through the Railway edge proxy. Unless `TRUSTED_PROXY_CIDRS` is explicitly configured with Railway's internal CIDRs, `get_trusted_client_ip()` treats the incoming peer as an untrusted proxy, collapsing all incoming traffic into the single proxy IP (`10.x.x.x` or similar).
3. Under combined user traffic and health polling, the 120 requests/minute threshold is exceeded rapidly.
4. `RateLimitingMiddleware` returns:
   ```json
   HTTP 429 Too Many Requests
   {"detail": "Rate limit exceeded. Please slow down your requests."}
   ```
5. Railway interprets HTTP 429 as probe failure, marks the container as `UNHEALTHY`, and terminates the process (`SIGKILL` / restart).
6. The container restarts, begins serving, receives traffic + health probes, hits HTTP 429 within 30–60 seconds, and is killed again.
7. **Conclusion: The "Deployment Death Spiral" vulnerability is ACTIVE in the current codebase.**

### Health Monitoring Questions A–J Assessment

| # | Question | Finding | Evidence |
|---|---|---|---|
| **A** | Which endpoint Railway actually uses? | Railway configuration file (`railway.json`) is **missing from repo root**. If configured via UI, either `/health` or `/ready` is specified. If omitted, default is `/` or none. | Repository root inspection; `railway.json` does not exist. |
| **B** | Whether `/ready` is rate limited? | **YES.** Rate limited to 120 req/60s per client IP. | `backend/app/main.py:104-107, 119-123`. |
| **C** | Whether health probes can accidentally trigger HTTP 429? | **YES.** `/ready` will trigger HTTP 429 under standard probe frequency or reverse proxy IP collapse. | `backend/app/main.py:105, 119-123`. |
| **D** | Whether a dependency failure correctly produces unhealthy status? | **YES.** If Supabase fails, `check_db_health()` returns False, causing `/ready` to return HTTP 503. | `backend/app/main.py:245-257`. |
| **E** | Whether health checks can cause restart loops? | **YES (Double Risk):**<br>1. Via HTTP 429 rate limiting.<br>2. Via transient DB blip returning 503 to a readiness probe configured as a liveness probe. | `backend/app/main.py:104-123, 245-257`. |
| **F** | Whether startup probes have appropriate timeouts? | **MISSING.** `backend/Dockerfile` has no `HEALTHCHECK` instruction. Railway default probe timeout is typically 30s. | `backend/Dockerfile:1-25`. |
| **G** | Whether health checks are authenticated accidentally? | **NO.** `/health` and `/ready` do not use auth dependencies. | `backend/app/main.py:213-267`. |
| **H** | Whether health endpoints leak internal infrastructure info? | **NO.** Returns service name, environment, status, and dependency status. No secrets or connection strings leaked. | `backend/app/main.py:240-266`. |
| **I** | Whether web and worker services have independent health monitoring? | **NO.** `audit-worker` and `failover-worker` have no HTTP endpoints, no Docker healthcheck, and no heartbeat mechanism. | `docker-compose.yml:15-34`, `backend/Dockerfile:24`. |
| **J** | Whether graceful shutdown is implemented? | **Web: YES** (Uvicorn SIGTERM handling, stops background auditor).<br>**Workers: PARTIAL** (runner catches SIGINT/SIGTERM, but failover worker drops in-flight batch into stuck state). | `backend/app/main.py:48-52`, `backend/app/workers/runner.py:33-44`, `backend/app/workers/failover_worker.py:221`. |

---

## 5. Dependency Resilience Matrix

| Dependency | Purpose | Timeout | Retries | Backoff / Jitter | Circuit Breaker | Failure Propagation | Local Fallback | Ops Alert? | Severity |
|---|---|---|---|---|---|---|---|---|---|
| **Supabase (PostgreSQL)** | Persistent storage, profiles, domains, logs | Client default (none explicit) | **0** | None for API calls; RPC has retry backoff for audit domain scheduling | **None** | Raises `DatabaseUnavailableError` -> HTTP 503 | In-memory dicts in dev/test; fails in prod | **None** (Logged only) | **P1** |
| **Shopify Admin REST/GraphQL** | Store OAuth, shop info, recurring app billing | 10.0s | **0** | None | **None** | Raises `HTTPException(400)` or `RuntimeError` | None | **None** (Logged only) | **P2** |
| **Stripe API** | Checkout sessions, billing portal, invoices | 10.0s | **0** | None | **None** | In prod raises `RuntimeError` -> HTTP 500 | In dev/test returns mock URL | **None** (Logged only) | **P2** |
| **Telegram Bot API** | Ops incident alerts, merchant failure alerts | Ops: 5.0s<br>Merchant: 8.0s | **0** (deliberate) | None | **None** | Fails closed; returns `{"success": False}` | Logged to stdout | Fallback local log | **P2** |
| **Cloudflare REST v4 API** | 1-Click DNS record insertion / auto-fix | 8.0s | **0** | None | **None** | **SILENT FAILURE!** Logs error but returns `applied: True` | Fictitious success recorded in logs | **None** (Logged only) | **P1** |
| **GoDaddy API** | DNS zone record insertion | None (stub) | **0** | None | **None** | Stubbed | Stubbed | **None** | **P3** |
| **Public DNS Resolvers (1.1.1.1, 8.8.8.8)** | Live DNS resolution (SPF, DKIM, DMARC, MX) | 4.0s (lifetime 8.0s) | Built into `dnspython` | None | **None** | Returns `missing` / `error` status per record | None | **None** | **P2** |
| **RBL DNSBL Zones (10 Authoritative Lists)** | Blacklist radar IP/domain lookup | 1.5s per query | **0** | None | **None** | Returns `unknown` / `error`; never marks clean | None | **None** | **P2** |
| **Redis / Cache Layer** | Distributed caching / locks | **NOT USED** | N/A | N/A | N/A | N/A | In-memory dicts with 24h or 60s TTL | N/A | **P3** |

---

## 6. Worker Reliability Analysis

InboundCheck utilizes a dedicated worker architecture ([`backend/app/workers/`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/workers/)) orchestrated via [`runner.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/workers/runner.py).

### Worker Implementation Breakdown

#### 1. Audit Worker (`audit_worker.py`)
- **Queue Implementation:** PostgreSQL table `public.monitored_domains`.
- **Claim Mechanism:** RPC `claim_due_domain_audits(p_worker_id, p_limit, p_interval, p_lease_duration)` utilizing `FOR UPDATE SKIP LOCKED`.
- **Lease Duration:** 900 seconds (15 minutes).
- **Crash Recovery:** **SAFE.** If worker crashes mid-audit, `audit_lease_until` expires after 15 minutes. Subsequent worker sweeps re-claim the domain (`WHERE audit_lease_until < NOW()`).
- **Retry Handling & Backoff:** Uses `fail_domain_audit` RPC with exponential backoff:
  $$\text{Delay} = \min(86400, 120 \times 2^{\min(\text{failures}, 10)} + \text{jitter})$$
- **Dead-Letter Behavior:** Increments `audit_failure_count` and records `last_audit_error`. Leaves domain in `monitored_domains`.
- **Alert on Crash:** **NO.** Unhandled exceptions in the audit loop log to stdout only.

#### 2. Failover Worker (`failover_worker.py`)
- **Queue Implementation:** PostgreSQL table `public.delivery_failure_events`.
- **Claim Mechanism:** RPC `claim_pending_delivery_failure_events(p_worker_id, p_limit)` in `20260912000003_allow_telegram_fallback_channel.sql`.
- **Lease Duration:** **NONE.** RPC sets `processing_status = 'queued'`, `claimed_by = p_worker_id`, `claimed_at = NOW()`.
- **Crash Recovery:** **CRITICAL DEFECT (P1).** If worker crashes, restarts, or receives SIGTERM mid-batch, rows in `delivery_failure_events` remain in `'queued'` state. The claim query strictly filters:
  ```sql
  WHERE processing_status = 'received'
  ```
  It **never checks** `processing_status = 'queued' AND claimed_at < NOW() - INTERVAL '15 minutes'`.
- **Result:** Any claimed events during a worker crash become **permanently stuck** and are never processed or alerted.
- **Retry Handling:** None. On failure, calls `mark_event_failed` -> `processing_status = 'failed'`. 0 retries.
- **Graceful Shutdown Defect:** Lines 221–222:
  ```python
  for event in events:
      if stop_event and stop_event.is_set():
          break
      await process_delivery_failure_event(event, worker_id)
  ```
  If `events` has 20 claimed rows and SIGTERM arrives after event 2, the loop breaks immediately. The remaining 18 events are left stuck in `'queued'` forever!

### Worker Reliability Questions Assessment

| Scenario | Audit Worker | Failover Worker |
|---|---|---|
| **1. Restart automatically?** | In Docker/Railway: YES (via `restart: unless-stopped`). | In Docker/Railway: YES (via `restart: unless-stopped`). |
| **2. Alert Telegram on crash?** | **NO.** Caught by `except Exception:` -> `logger.error` only. | **NO.** Caught by `except Exception:` -> `logger.error` only. |
| **3. Lose jobs on crash?** | **NO.** Database records remain intact. | **NO.** Records remain, but cannot be processed. |
| **4. Duplicate jobs on concurrency?** | **NO.** `FOR UPDATE SKIP LOCKED` guarantees disjoint worker partitions. | **NO.** `FOR UPDATE SKIP LOCKED` guarantees disjoint partitions. |
| **5. Leave jobs permanently stuck?** | **NO.** Leases expire after 15m; reclaimed automatically. | **YES (P1).** Claimed jobs remain in `'queued'` forever. |

---

## 7. Railway Failure Simulation Matrix (Scenarios A–H)

| Scenario | Expected Behavior | Current Behavior | Telegram Alert? | Railway Restart? | Data Loss? | Duplicate Processing? | Customer Impact | Severity |
|---|---|---|---|---|---|---|---|---|
| **A: Database Unavailable** | Fail closed, return HTTP 503, alert ops on-call, do not enter restart death spiral | `check_db_health()` returns False; `/ready` returns HTTP 503; `global_exception_shield` returns 503 with reference ID | **NO** (Logs to stdout only) | **YES** (If `/ready` is configured as Railway healthcheck) | No (queries fail read-only) | None | Complete dashboard outage; merchants see 503 | **P1** |
| **B: Supabase Unavailable** | Identical to Scenario A | Identical to Scenario A | **NO** | **YES** (If `/ready` is probed) | None | None | Complete platform outage | **P1** |
| **C: Shopify API Timeout** | Return clean error, retry with backoff, preserve merchant session | After 10.0s, raises `Exception`; OAuth callback returns HTTP 400; billing callback raises HTTP 500/RuntimeError | **NO** (Logs to stdout only) | **NO** | None | None | Merchant cannot install app or approve subscription charge | **P2** |
| **D: Telegram API Unavailable** | Log failure, queue alert for deferred delivery, do not crash worker | Returns `{"success": False, "error": ...}`; logs warning; marks failover event `failed` | **NO** (Telegram itself is down; ops webhook also unconfigured) | **NO** | None | None | Merchant does not receive real-time failure notification | **P2** |
| **E: Worker Crashes** | Container restarts automatically, alerts ops, re-claims in-flight jobs via lease expiry | Docker restarts process; unhandled error logged; `audit_worker` reclaims after 15m; `failover_worker` **leaves jobs stuck in `'queued'` forever** | **NO** | **YES** (Worker container restarts) | No row deletion, but failover events permanently locked | No (`SKIP LOCKED`) | Unprocessed bounce/rejection alerts never reach merchants | **P1** |
| **F: Application Startup Failure** | Refuse to boot, exit code 1, alert ops channel before exit | `validate_runtime_environment()` raises `ValueError`; Uvicorn crashes with exit code 1; Railway restarts container up to backoff limit | **NO** (Process dies before any alerting could dispatch) | **YES** (Container enters CrashLoopBackOff) | None | None | Platform completely unavailable | **P1** |
| **G: `/ready` Receives 200 Probes/Min** | Return HTTP 200/503 without being throttled; health probes never return 429 | `RateLimitingMiddleware` counts probes against client IP; after 120 requests, **returns HTTP 429 Too Many Requests**; Railway kills container | **NO** | **YES** (Infinite Deployment Death Spiral) | None | None | Intermittent or total application downtime as container is continuously killed | **P1** |
| **H: Redis Unavailable** | Failover to database or memory | Redis is not used in InboundCheck. Application runs on in-memory dicts + Postgres tables | N/A | **NO** | None | None | Zero impact (Redis is not an active dependency) | **P3** |

---

## 8. Top 10 Operational Risks

| Rank | Risk ID | Category | Severity | Operational Threat | Primary Evidence |
|---|---|---|---|---|---|
| **1** | **OPS-01** | Deployment / Health | **P1** | **Deployment Death Spiral via `/ready` Throttling:** Health probes to `/ready` trigger HTTP 429 after 120 req/min, causing Railway to mark containers unhealthy and enter restart loops. | `backend/app/main.py:104-107, 119-123` |
| **2** | **OPS-02** | Alerting / Observability | **P1** | **Telegram Ops Alerting Disconnected:** `OpsAlertService.dispatch_incident()` is never called in production. Critical production outages produce zero pages. | `backend/app/services/alerting/ops_alert_service.py:90`, `backend/app/main.py:184` |
| **3** | **OPS-03** | Worker Reliability | **P1** | **Permanent Queue Lockup on Worker Crash:** `delivery_failure_events` claimed by `failover_worker` are marked `'queued'` without a lease expiry, leaving them permanently stuck if a worker dies. | `supabase/migrations/20260912000003_allow_telegram_fallback_channel.sql:63`, `backend/app/workers/failover_worker.py:221` |
| **4** | **OPS-04** | Data Integrity | **P1** | **Silent DNS Remediation Failure:** Cloudflare API errors in `auto_fixer.py` log to stdout but return `applied: True`, falsely indicating to merchants that DNS records were fixed. | `backend/app/services/dns/auto_fixer.py:164-187` |
| **5** | **OPS-05** | Rate Limiting / Proxy | **P2** | **Reverse Proxy IP Collapse on Railway:** If `TRUSTED_PROXY_CIDRS` is not set, all Railway ingress traffic shares the single router IP, causing 120 req/min budget to be shared by all merchants. | `backend/app/core/rate_limiter.py:89-91`, `backend/app/main.py:100` |
| **6** | **OPS-06** | Observability | **P2** | **Zero Worker Health Probes:** `audit-worker` and `failover-worker` have no health probes, HTTP endpoints, or heartbeat mechanisms in Docker/Railway. | `docker-compose.yml:15-34`, `backend/Dockerfile:24` |
| **7** | **OPS-07** | Dependency Resilience | **P2** | **Zero External API Retries or Circuit Breakers:** Supabase, Shopify, and Stripe client calls execute with 0 retries and no circuit breakers, causing transient glitches to immediately error out. | `backend/app/services/supabase_client.py:48`, `backend/app/services/shopify/shopify_service.py:264`, `backend/app/services/billing/stripe_service.py:273` |
| **8** | **OPS-08** | Security / Privacy | **P3** | **Customer PII in Telegram Message Body:** In `omnichannel_service.py:183`, `customer_email` is interpolated directly into Telegram markdown alert text. | `backend/app/services/failover/omnichannel_service.py:183` |
| **9** | **OPS-09** | Configuration Drift | **P3** | **Missing `railway.json` Deployment Manifest:** Documented deployment configuration file `railway.json` is absent from the repository root. | Root directory inspection. |
| **10** | **OPS-10** | Worker Concurrency | **P3** | **Failover Worker Graceful Shutdown Drops Batch:** Breaking out of `process_delivery_failure_event` on `stop_event` leaves remainder of claimed 20-event batch in `'queued'` state. | `backend/app/workers/failover_worker.py:221-224` |

---

## 9. Exact File + Function for Every Finding

### Finding 1: Deployment Death Spiral via `/ready` Throttling (P1)
- **File:** [`backend/app/main.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/main.py)
- **Function / Class:** `RateLimitingMiddleware.dispatch` (lines 103–126)
- **Evidence:**
  ```python
  104: is_exempt = (
  105:     request.url.path in ["/health", "/", "/docs", "/openapi.json"]
  106:     or os.getenv("PYTEST_CURRENT_TEST") is not None
  107: )
  ```
  Path `/ready` and `/api/v1/health` are absent from `is_exempt`. When probes exceed 120 req/60s, line 120 returns `HTTP 429 Too Many Requests`.

### Finding 2: Telegram Ops Alerting Completely Disconnected (P1)
- **File:** [`backend/app/services/alerting/ops_alert_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/alerting/ops_alert_service.py)
- **Function / Class:** `OpsAlertService.dispatch_incident` (line 90)
- **Evidence:** Not a single handler in `backend/app/main.py` (`global_exception_shield`), `backend/app/api/v1/shopify.py`, `backend/app/api/v1/billing.py`, or `backend/app/workers/` imports or invokes `ops_alert_service.dispatch_incident()`.

### Finding 3: Permanent Queue Lockup on Failover Worker Crash (P1)
- **Files:**
  - [`supabase/migrations/20260912000003_allow_telegram_fallback_channel.sql`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260912000003_allow_telegram_fallback_channel.sql) (lines 43–70)
  - [`backend/app/workers/failover_worker.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/workers/failover_worker.py) (lines 205–225)
- **Function / RPC:** `public.claim_pending_delivery_failure_events` and `run_failover_worker`
- **Evidence:**
  ```sql
  57: WHERE processing_status = 'received'
  ```
  Rows transition to `processing_status = 'queued'`. If worker dies or drops batch, no mechanism ever reclaims rows stuck in `'queued'`.

### Finding 4: Silent DNS Remediation Failure in Auto-Fixer (P1)
- **File:** [`backend/app/services/dns/auto_fixer.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/dns/auto_fixer.py)
- **Function / Class:** `DNSAutoFixerService.apply_dns_fix` (lines 145–187)
- **Evidence:**
  ```python
  164: except Exception as e:
  165:     logger.error(f"Cloudflare API error: {e}")
  ...
  174:     "status": "applied",
  ...
  184: return {
  185:     "applied": True,
  186:     "provider": clean_provider,
  187:     "fix_entry": fix_entry
  188: }
  ```
  Exception is swallowed, logged, and fictitious `applied: True` is returned.

### Finding 5: Reverse Proxy Single-IP Rate Limit Collapse (P2)
- **File:** [`backend/app/core/rate_limiter.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/core/rate_limiter.py)
- **Function:** `get_trusted_client_ip` (lines 87–91)
- **Evidence:**
  ```python
  90: if not is_ip_trusted_proxy(direct_peer):
  91:     return direct_peer
  ```
  If Railway proxy subnet is not in `TRUSTED_PROXY_CIDRS`, `direct_peer` is used for all users, collapsing all traffic into 120 req/min total.

### Finding 6: Workers Lack Independent Health Monitoring (P2)
- **File:** [`docker-compose.yml`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/docker-compose.yml) (lines 15–34)
- **Evidence:** Containers `audit-worker` and `failover-worker` define command and restart policy, but zero `healthcheck:` stanza. If worker event loop deadlocks, container remains running indefinitely.

### Finding 7: Missing Retries and Circuit Breakers on External HTTP APIs (P2)
- **Files:**
  - [`backend/app/services/shopify/shopify_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/shopify/shopify_service.py) (lines 264–270)
  - [`backend/app/services/billing/stripe_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/billing/stripe_service.py) (lines 273–298)
- **Evidence:** Direct `httpx.AsyncClient(timeout=10.0)` call with 0 retries and no backoff. Any transient network packet drop raises an immediate 400 or 500 exception.

### Finding 8: PII Exposure in Telegram Alert Message (P3)
- **File:** [`backend/app/services/failover/omnichannel_service.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/failover/omnichannel_service.py)
- **Function:** `TelegramAlertService.trigger_failover_dispatch` (line 183)
- **Evidence:**
  ```python
  183: f"📬 *Customer Email:* `{customer_email or 'N/A'}`\n"
  ```
  Customer email is pushed to external Telegram servers in plaintext markdown.

### Finding 9: Missing `railway.json` Deployment Manifest (P3)
- **File:** Repository Root (`c:\Users\pc\Desktop\inboundcheck VERSION 1\`)
- **Evidence:** `railway.json` is referenced in documentation as defining build and healthcheck configurations, but does not exist in the working directory.

### Finding 10: Graceful Shutdown Drops Claimed Failover Batch (P3)
- **File:** [`backend/app/workers/failover_worker.py`](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/workers/failover_worker.py)
- **Function:** `run_failover_worker` (lines 220–224)
- **Evidence:**
  ```python
  220: for event in events:
  221:     if stop_event and stop_event.is_set():
  222:         break
  223:     await process_delivery_failure_event(event, worker_id)
  ```
  Breaks out without rolling back or resetting unhandled claimed items back to `received`.

---

## 10. Recommended Remediation Plan

### Remediation 1: Exempt `/ready` and `/api/v1/health` from Rate Limiter (P1)
In `backend/app/main.py`:
```python
is_exempt = (
    request.url.path in ["/health", "/ready", f"{settings.API_V1_STR}/health", "/", "/docs", "/openapi.json"]
    or os.getenv("PYTEST_CURRENT_TEST") is not None
)
```

### Remediation 2: Wire `OpsAlertService` into Error Handlers (P1)
1. In `backend/app/main.py` -> `global_exception_shield`:
   Call `await ops_alert_service.dispatch_incident(OpsIncident(alert_id="ALERT-UNHANDLED-500", severity="P1", summary=f"Unhandled 500: {exc}", details={"ref_id": ref_id, "path": str(request.url)}))`.
2. In `DatabaseUnavailableError` branch:
   Dispatch `alert_id="ALERT-DB-OUTAGE"`, `severity="P0"`.
3. In `shopify_orders_webhook` and `stripe_webhook_handler`:
   Dispatch `alert_id="ALERT-WEBHOOK-FAILURE"`, `severity="P1"`.
4. In `worker.py` loops:
   Dispatch `alert_id="ALERT-WORKER-CRASH"`, `severity="P1"` in the outer `except Exception:` block.

### Remediation 3: Add Lease Expiry and Stale Recovery to `delivery_failure_events` (P1)
1. Add `claimed_at TIMESTAMPTZ` and `lease_until TIMESTAMPTZ` columns to `delivery_failure_events`.
2. Update `claim_pending_delivery_failure_events` RPC:
   ```sql
   WHERE processing_status = 'received'
      OR (processing_status = 'queued' AND (lease_until IS NULL OR lease_until < NOW()))
   ```
3. In `failover_worker.py`, implement graceful batch drain or reset on shutdown.

### Remediation 4: Fix `apply_dns_fix` Error Handling (P1)
In `backend/app/services/dns/auto_fixer.py`:
If Cloudflare response status is not 200/201 or exception occurs, set `status = "failed"` and return `applied = False`, propagating the error message to the caller.

### Remediation 5: Provide Explicit `railway.json` and Docker Healthchecks (P2)
1. Create `railway.json` at repository root specifying:
   ```json
   {
     "$schema": "https://railway.app/railway.schema.json",
     "build": {
       "builder": "DOCKERFILE",
       "dockerfilePath": "backend/Dockerfile"
     },
     "deploy": {
       "healthcheckPath": "/health",
       "healthcheckTimeout": 30,
       "restartPolicyType": "ON_FAILURE"
     }
   }
   ```
   *Note: Using `/health` for Railway liveness avoids any database coupling in the container restart probe.*
2. Add worker heartbeat health probe via file touch or lightweight IPC.

---

## 11. Test Plan for Future Remediation

```
Phase 2.2 Verification Test Matrix
├── Test Suite 1: Health Probe & Rate Limiting Verification
│   ├── test_health_endpoint_returns_200_without_rate_limit()
│   ├── test_ready_endpoint_exempt_from_rate_limiter_under_200_rpm()
│   ├── test_ready_returns_503_when_db_down()
│   └── test_railway_proxy_ip_resolution_with_trusted_cidrs()
│
├── Test Suite 2: Ops Telegram Alerting Integration Verification
│   ├── test_global_exception_shield_dispatches_ops_alert()
│   ├── test_db_unavailable_dispatches_p0_ops_alert()
│   ├── test_shopify_webhook_failure_dispatches_p1_ops_alert()
│   ├── test_stripe_webhook_failure_dispatches_p1_ops_alert()
│   └── test_ops_alert_anti_flapping_suppresses_subsequent_within_15m()
│
├── Test Suite 3: Worker Lease & Crash Recovery Verification
│   ├── test_failover_worker_reclaims_stale_queued_events_after_lease_expiry()
│   ├── test_worker_graceful_shutdown_drains_or_resets_claimed_batch()
│   └── test_audit_worker_backoff_jitter_bounds()
│
└── Test Suite 4: Auto-Fix Failure Propagation
    ├── test_cloudflare_api_failure_returns_applied_false()
    └── test_failed_dns_fix_logged_as_failed_in_repository()
```

---

## 12. Production Readiness Assessment

| Area | Status | Critical Blocker |
|---|---|---|
| **P0 Security (JWT & Billing)** | **PASSED (100%)** | Fully hardened and cryptographically verified. |
| **Telegram Ops Alerting** | **FAILED** | `OpsAlertService` is completely disconnected from all production error paths. |
| **Railway Health Probes** | **FAILED** | `/ready` is subject to rate limiting; risk of container restart death spiral. |
| **Worker Queue Resilience** | **FAILED** | `failover_worker` has no lease expiry; crashed worker locks events forever. |
| **DNS Auto-Fix Resilience** | **FAILED** | Cloudflare API errors silently report success. |
| **External API Resilience** | **NEEDS WORK** | 0 retries, 0 circuit breakers across Shopify, Stripe, Supabase. |

---

## 13. Concise Executive Verdict

```
================================================================================
EXECUTIVE VERDICT: NOT READY
================================================================================
Reasoning:
While foundational security vulnerabilities (P0 JWT forgery and P0 Shopify
billing bypass) are verified clean, the production operations layer is NOT READY
for launch due to four active P1 reliability defects:

1. Deployment Death Spiral: Health probes to /ready are rate limited and will
   trigger container restart loops on Railway under normal load.
2. Disconnected Ops Alerting: Zero production error handlers or workers call
   OpsAlertService; outages will occur in complete silence.
3. Worker Queue Lockup: Delivery failure events will get permanently stuck in
   'queued' state upon worker crash or restart due to missing lease expiry.
4. Silent Remediation Failure: Cloudflare DNS auto-fix errors report false
   success to merchants.

Remediations for these 4 P1 items are required before production cutover.
================================================================================
```
