# INBOUNDCHECK — SERVICE-ROLE USAGE & PRIVILEGE AUDIT

**Audit Date:** 2026-09-23  
**Auditor:** Principal Cloud Security & Architecture Specialist  
**Governing Standard:** Principle of Least Privilege (PoLP) & Multi-Tenant Data Boundaries  
**Target:** `SUPABASE_SERVICE_ROLE_KEY` and PostgREST Privileged Access

---

## 1. Why Privileged Service-Role Access is Needed

In InboundCheck's architecture, `SUPABASE_SERVICE_ROLE_KEY` is required for three fundamental operational subsystems that execute outside of an interactive user browser session:

1. **Autonomous Background Workers (Async Daemons):**
   * The `audit_worker` continuously polls for domains whose `next_audit_due` timestamp has passed using the atomic database RPC `claim_due_domain_audits` (`FOR UPDATE SKIP LOCKED`).
   * Because workers run in a headless background loop, there is no user session or user JWT. Workers require service-role access to read and update domain audit records across all active tenants.
2. **Asynchronous Ingress Webhooks (Stripe, Shopify, ESPs):**
   * Stripe webhooks (`/api/v1/billing/webhooks`) receive subscription lifecycle events signed with Stripe HMAC signatures.
   * Shopify webhooks (`/api/v1/shopify/webhooks/*`) receive GDPR redact and app uninstalled events signed with Shopify HMAC-SHA256 signatures.
   * ESP delivery failure webhooks (SendGrid, Postmark, Mailgun, Resend, Brevo) receive bounce notifications.
   * Webhook requests contain zero user cookies or Supabase JWTs. They require privileged service-role credentials to look up and mutate the affected tenant records by `stripe_customer_id`, `shop_domain`, or message ID.
3. **Internal Auth Provisioning & Triggers:**
   * PostgreSQL trigger functions (`on_auth_user_created`) and profile self-healing initialization execute under `SECURITY DEFINER` / `service_role` privileges to link `auth.users` with `public.profiles`.

---

## 2. Table-by-Table Service-Role Access Audit

| Table | Operation | Why Service-Role Needed? | Ownership Safeguard in Code | Can User-Scoped Client Replace? | Final Decision |
|---|---|---|---|:---:|---|
| `public.profiles` | SELECT / UPDATE / UPSERT | User profile lookup, tier updates on Stripe webhook, self-healing profile sync | Code explicitly scopes to `user_id` extracted from cryptographically verified JWT (`sub` claim) or Stripe customer ID lookup | NO (Needed for Stripe webhooks and profile self-healing) | **RETAIN with explicit `.eq("id", user_id)` safeguard** |
| `public.monitored_domains` | SELECT / INSERT / DELETE / UPDATE | Domain monitoring and background audits | Backend API explicitly appends `.eq("user_id", user_id)` and `.eq("id", domain_id)`. Background worker uses atomic lease RPC | NO (Needed for background worker batch leases) | **RETAIN with explicit ownership verification in all API handlers** |
| `public.dns_audit_logs` | INSERT / SELECT | Recording multi-resolver DNS audit outcomes | Inserts inject verified `user_id` from JWT | NO (Needed for worker automated recurring audits) | **RETAIN with strict `domain_id` ownership pre-check** |
| `public.shopify_stores` | SELECT / UPSERT / DELETE | Shopify OAuth exchange, store settings, and GDPR redacts | OAuth exchanges associate store with authenticated JWT `user_id`. GDPR uninstalls verify HMAC signature before lookup by `shop_domain` | NO (Needed for Shopify HMAC webhook handling) | **RETAIN with HMAC signature validation and user scoping** |
| `public.alert_configs` | SELECT / UPSERT | Fetching and saving notification rules and bot tokens | All API calls explicitly append `.eq("user_id", user_id)` | NO (Needed for alert dispatcher workers) | **RETAIN with `.eq("user_id", user_id)`** |
| `public.failover_logs` | INSERT / SELECT | Logging incident notifications and GDPR redaction | Scoped to authenticated user and recipient email redaction | NO (Needed for async webhook dispatches) | **RETAIN with store ownership checks** |
| `public.reputation_checks` | SELECT / INSERT | Querying reputation trends and recording RBL checks | Scoped to `user_id` and domain | NO (Needed for scheduled RBL scans) | **RETAIN with `.eq("user_id", user_id)`** |
| `public.worker_heartbeats` | UPSERT / SELECT | Health readiness probes and worker liveness tracking | System-level table for container orchestrator telemetry | NO (No user concept exists for worker liveness) | **RETAIN under exclusive service-role access** |

---

## 3. Explicit Safeguards & Invariant Rules

To ensure service-role access never violates multi-tenant isolation, the application enforces the following four invariant rules:

1. **Invariant 1 — No Client-Supplied Identity:**
   Under no circumstances is a `user_id` parameter accepted from the request body or query parameters to authorize access to user-owned data. Identity is extracted exclusively from the cryptographically verified JWT payload (`app.core.security.get_current_user_id`).
2. **Invariant 2 — Mandatory Dual-Key Queries:**
   Every query for a specific user resource must include both the resource primary key and the tenant identity:
   ```python
   # Correct
   supabase_client.table("monitored_domains").delete().eq("id", domain_id).eq("user_id", user_id).execute()
   ```
3. **Invariant 3 — Hierarchical Resource Ownership Pre-Checks:**
   Before updating or logging against a child resource (such as `domain_id` in `re_audit_domain`), the API layer must query `monitored_domains` to confirm that `(id == domain_id AND user_id == authenticated_user_id)`. If not found, it must immediately abort with `HTTP 404 Not Found`.
4. **Invariant 4 — Webhook Cryptographic Verification:**
   All unauthenticated endpoints that update state via service role (Stripe, Shopify, ESP webhooks) must strictly reject requests that fail HMAC signature verification or payload format constraints.
