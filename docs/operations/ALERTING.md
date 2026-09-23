# INBOUNDCHECK — PRODUCTION ALERTING & INCIDENT THRESHOLDS

**Document Version:** 2.0 (Phase 2.1 Reliability & Reality Alignment)  
**Governing Standard:** Signal-to-Noise Optimized Incident Response & Reality Classification  
**Target Platform:** InboundCheck Production Cluster & Operations  
**Date:** 2026-09-23  

---

## 1. Alerting Philosophy & Classification Taxonomy

InboundCheck follows a **zero-alert-fatigue** policy. Individual transient network glitches (such as a single UDP DNS packet drop or a temporary 502 from an external ESP) must be retried with exponential backoff and bounded jitter, and **must not trigger engineer on-call paging**.

Alerts are reserved strictly for actionable system degradation, sustained component failures, security anomalies, and monetization blockages.

### Reality Classification Standards:
* **`IMPLEMENTED + AUTOMATED`**: An automated detection mechanism, evaluation threshold, and delivery path are fully implemented in active codebase and verified by tests.
* **`IMPLEMENTED + MANUAL`**: Telemetry or health state is captured in code; human investigation or operational script invocation is required to assess impact.
* **`DOCUMENTED ONLY / HEALTH SIGNAL`**: The endpoint or signal (e.g. HTTP 503 on `/ready`) exists in application code, but notification requires an external uptime monitoring platform (e.g. Railway health probe, UptimeRobot, Checkly). No automated paging is baked into the app itself.
* **`DOCUMENTED ONLY`**: Operational runbook query or threshold defined for operations teams without automated code hooks.
* **`NOT AVAILABLE`**: Mechanism is neither implemented nor integrated.

---

## 2. Production Alert Definitions & Status Matrix

| Alert Identifier | Severity | Category | Trigger Condition | Evaluation Window | Operational Path & Target Channel | Implementation Status |
|---|:---:|---|---|---|---|:---:|
| `ALERT-CRITICAL-DELIVERABILITY` | **P2 (Medium)** | Customer Deliverability | Customer monitored domain experiences sudden health score drop below 50 or is newly listed on >= 2 RBLs | Immediate | `alert_dispatcher.py` evaluates score -> formats markdown -> dispatches via merchant Telegram bot | **IMPLEMENTED + AUTOMATED** |
| `ALERT-FAILOVER-INCIDENT` | **P1 (High)** | Omnichannel / Failover | Delivery failure webhook received from ESP (Postmark, SendGrid, Mailgun, SES, Klaviyo) with eligible status | Immediate | Ingestion -> `failure_event_repository` -> `failover_worker` -> `telegram_alert_service` dispatches to store Telegram | **IMPLEMENTED + AUTOMATED** |
| `ALERT-WEBHOOK-FAILURES` | **P1 (High)** | Ingestion / Billing | Sustained HTTP 4xx/5xx on `/api/v1/billing/webhook` or `/api/v1/shopify/webhooks/*` exceeding 5% of traffic | 10 minutes | Webhook exception handler -> `ops_alert_service.py` -> `OPS_ALERT_WEBHOOK_URL` / Ops Telegram | **IMPLEMENTED + AUTOMATED** (When configured) |
| `ALERT-BILLING-FAILURES` | **P1 (High)** | Monetization | Sustained HTTP 500 on `POST /api/v1/billing/create-checkout-session` for >= 3 occurrences in 10 minutes | 10 minutes | Billing router exception handler -> `ops_alert_service.py` -> `OPS_ALERT_WEBHOOK_URL` / Ops Telegram | **IMPLEMENTED + AUTOMATED** (When configured) |
| `ALERT-DB-OUTAGE` | **P0 (Critical)** | Infrastructure | `/ready` probe returns HTTP 503 for >= 3 consecutive health checks (45 seconds) | 1 minute | `/ready` returns 503 `Database connection check failed`. Requires external uptime monitor (e.g. Railway / UptimeRobot) to page on-call. | **DOCUMENTED ONLY / HEALTH SIGNAL** |
| `ALERT-WORKER-BACKLOG` | **P1 (High)** | Queue / Background | Monitored domains due for audit with unexpired leases backlog exceeds 200 items, or lag > 2 hours | 15 minutes | Operational SQL runbook: `SELECT COUNT(*) FROM monitored_domains WHERE is_active=true AND audit_lease_until < NOW() AND last_audited_at < NOW() - INTERVAL '2 hours'` | **DOCUMENTED ONLY** |
| `ALERT-SECURITY-SSRF-SPIKE` | **P2 (Medium)** | Security / Abuse | Rate of Anti-SSRF domain validation rejections (`ValueError: SSRF Protection`) exceeds 30 in 5 minutes from a single IP | 5 minutes | Application logs security event with structured metadata. Edge firewall (Cloudflare WAF) rule configuration required. | **DOCUMENTED ONLY** |
| `ALERT-RATE-LIMIT-BREACH` | **P2 (Medium)** | Traffic / Abuse | Ingress rate-limiting middleware triggers HTTP 429 for > 10 distinct client IPs within 5 minutes | 5 minutes | Application returns HTTP 429 with `Retry-After`. Monitoring edge metrics in Cloudflare / reverse proxy required. | **DOCUMENTED ONLY** |
| `ALERT-DNSBL-THROTTLE` | **P2 (Medium)** | Integration | RBL scanner receives `127.255.255.x` volume rejection codes across > 10% of queries | 30 minutes | Infrastructure runbook: Migrate to direct DNS resolver or configure commercial Spamhaus DQS key. | **DOCUMENTED ONLY** |

---

## 3. Ops Alert Dispatcher Specification (`ops_alert_service.py`)

When operational anomalies occur (repeated webhook signature rejections, billing checkout exceptions), the application invokes:
```python
await ops_alert_service.dispatch_incident(
    OpsIncident(
        alert_id="ALERT-WEBHOOK-FAILURES",
        severity="P1",
        summary="Repeated webhook verification failures detected",
        details={"provider": "stripe", "reason": "signature_mismatch"}
    )
)
```

### Safety & Reliability Guarantees:
1. **Secret Confidentiality:** `OPS_ALERT_WEBHOOK_URL` and `OPS_ALERT_TELEGRAM_BOT_TOKEN` are read strictly from environment secrets; they are never logged or exposed in client responses.
2. **Payload Sanitization:** `sanitize_incident_payload()` recursively scrubs API keys, bearer tokens, customer emails, cookies, and passwords before transmission.
3. **Strict Timeout:** Outbound HTTPS requests to ops webhooks or Telegram have a bounded **5.0s client timeout**.
4. **Zero Retries & No Recursive Loops:** If an ops webhook fails, it logs a warning and does **not** retry, avoiding cascading backpressure or recursive error storms.
5. **Anti-Flapping Suppression:** Repeated alerts with the same fingerprint (`alert_id:severity:summary[:40]`) are throttled by a **15-minute cooldown window**.
6. **Non-Blocking Execution:** Dispatch is non-blocking and fail-safe; failures never bubble up to cause HTTP 500 errors for end users or merchants.

---

## 4. Runbook for External Health Signal Monitoring (`ALERT-DB-OUTAGE`)

Because InboundCheck is a lightweight Micro-SaaS without internal PagerDuty SDK daemons, external uptime monitoring platforms must poll the standardized health endpoints:

```
[ External Uptime Monitor (e.g. Railway / Better Uptime / Checkly) ]
                              │
                              ▼
            GET https://api.inboundcheck.com/ready
                              │
              ┌───────────────┴───────────────┐
              │ HTTP 200 OK                   │ HTTP 503 Service Unavailable
              ▼                               ▼
     Database Healthy                 Page On-Call Engineer (P0)
                                      Verify Supabase status & connection pool
```
