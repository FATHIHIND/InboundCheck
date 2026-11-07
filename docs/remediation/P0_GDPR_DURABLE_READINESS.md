# GDPR durable workflow — local source readiness

This is a bounded Shopify shop/customer workflow, NOT full tenant/account erasure or a compliance certification.

## HTTP integration (Shopify router owner)

After body-size, HMAC, topic and body/header shop checks, call synchronously:

    app.services.privacy.repository.accept_gdpr_request(kind, shop, payload, delivery_id)

Kinds: customers/data_request, customers/redact, shop/redact. Delivery ID must be the authenticated Shopify delivery header; no process-generated fallback. Translate PrivacyValidationError to HTTP400 and PrivacyAcceptanceError to HTTP503. Only a returned {status: accepted, job_id, state, idempotent} receipt permits HTTP200. Return acceptance, not completed deletion. Never attach this acceptance to BackgroundTasks. Handler function execution must run before response; a threadpool may keep synchronous DB I/O off the event loop but must be awaited.

Legacy SupabaseService GDPR helpers now queue only and require delivery_id. They no longer query the nonexistent failover_logs.recipient_email column, update another tenant's matching email, log raw email, or return success after swallowed exceptions. They are compatibility entry points, not background durability.

## SQL prerequisite (DB owner, not applied)

The repository follows P0_SHARED_CONTRACT.md v1 names: enqueue_privacy_job, claim_privacy_jobs, execute_privacy_job, fail_privacy_job. Apply reviewed corrective migrations 20261106000001 then 20261106000002 only with separate authorization and isolated PostgreSQL integration evidence. customer_id parameter carries lowercase SHA256, NOT raw Shopify ID. subject hash is SHA256(lower(trim(email))) matching existing registry/ESP normalizers. Hashes remain pseudonymous personal data, not anonymity.

Critical contract revision required: export/count-only requests and incomplete redaction coverage MUST persist requires_manual_review, not completed. Customer-ID-only has no authoritative mapping in current schema; queue manual review or reject retryably without false completion. The worker rejects export-completed receipts but cannot undo an already committed bad SQL terminal status; SQL must itself enforce this.

## Scope and remaining data classes

DB selection must require resolved user AND shopify_store_id for registry. Correlate delivery_failure_events and failover_logs via tenant and registry/message/event links before deleting registry rows; purge notification_outbox entries only where authoritative shop/message mapping exists. failover_logs raw identifier is customer_email (not recipient_email), plus customer_phone/dispatch_payload/provider_error_message. Unlinked rows with only user_id/order_id are not safely shop-identifiable when a tenant owns multiple shops; never broaden to entire tenant. Such residual scope requires manual review. Do not silently claim full deletion of telemetry/free text/outbox without tested selectors.

Data export needs verified delivery to the requester, authorization, format and data-class coverage; a count receipt is not an export. Shop redact does not authorize deleting other stores, user account, tenant DNS credentials, billing records, backups or external provider data. Minimal job receipts/hashes also require retention policy and operator ownership.

## Worker rollout (not started)

GDPRWorker(client).run_once() is a bounded service-only batch, no import side effects or CLI. No Docker/main-worker wiring was changed. Requires separate authorized operator wiring/deployment after SQL validation. DB must use SKIP LOCKED leases, bound retry/backoff, reclaim expired leases and fence execute/fail by active worker lease. Crash before execute remains a leased job; crash after transaction commit must not undo or repeat completed effects. Failure code is fixed execution_unconfirmed, never raw exception data. A failed SQL failure receipt propagates and leaves the lease for recovery; no success is synthesized.

## Minimization handoff outside this agent's ownership

New minimize_diagnostics intentionally preserves only numeric smtp_status/http_status and discards arbitrary free text/nested objects. Parent/normalizer owner must wire it into failover/event_normalizers.py before event_payload persistence; retaining reason/Details/Description/diagnosticCode can retain raw identifiers. Existing alert_dispatcher.py send_failover_alert and SupabaseService.persist_failover_log raw customer_email/dispatch_payload pathways remain outside this patch. Replace raw dispatch payloads with allowlists and stop logging/persisting customer identifiers where not necessary. No broad unowned logging edits made.

## Evidence limits

Unit tests use mocked RPC responses and assert minimization, caller-tenant exclusion, receipt validation, retry invocation and no false export completion. They DO NOT prove PostgreSQL syntax, tenant isolation, RLS/ACL, lease race behavior, transactional rollback, actual deletion mapping, HTTP503 integration, deployment or backup deletion. Windows Python environment is not Docker Python3.11 validation. No database, SQL application, external network, deployment or live customer data accessed.
