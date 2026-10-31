-- =====================================================================
-- Migration 030: Harden Internal Worker RPC ACLs & Overload Resolution (P0-03)
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-10-31
-- Reference: PHASE 2 & 3 AUDIT — P0-03 Remediation
-- Description:
-- 1. Drops obsolete and ambiguous function overloads:
--    - public.claim_pending_delivery_failure_events(UUID, INTEGER) [obsolete 2-arg signature]
--    - public.fail_domain_audit(UUID, UUID, TEXT) [obsolete 3-arg signature causing SQLSTATE 42725 ambiguity]
-- 2. Revokes public/anon/authenticated EXECUTE privileges on all 12 internal worker
--    and maintenance SECURITY DEFINER functions.
-- 3. Restricts EXECUTE strictly to trusted service roles (postgres, service_role).
-- 4. Enforces postgres ownership and immutable search_path (public, pg_temp).
-- =====================================================================

BEGIN;

-- =====================================================================
-- SECTION 1: DROP OBSOLETE & AMBIGUOUS FUNCTION OVERLOADS
-- =====================================================================

-- 1.1 Drop legacy 2-argument claim_pending_delivery_failure_events if lingering
DROP FUNCTION IF EXISTS public.claim_pending_delivery_failure_events(UUID, INTEGER);

-- 1.2 Drop obsolete 3-argument fail_domain_audit to eliminate SQLSTATE 42725 ambiguity
-- (Superseded by 5-argument exponential backoff & jitter version in migration 20260925000001)
DROP FUNCTION IF EXISTS public.fail_domain_audit(UUID, UUID, TEXT);


-- =====================================================================
-- SECTION 2: HARDEN DELIVERY FAILURE & FAILOVER WORKER RPCS
-- =====================================================================

-- 2.1 record_delivery_failure_dispatch_intent(UUID, UUID)
REVOKE ALL ON FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) OWNER TO postgres;
ALTER FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) SET search_path = public, pg_temp;

-- 2.2 quarantine_expired_dispatch_intent_events(INTEGER)
REVOKE ALL ON FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) TO postgres, service_role;
ALTER FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) OWNER TO postgres;
ALTER FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) SET search_path = public, pg_temp;

-- 2.3 mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT)
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) TO postgres, service_role;
ALTER FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) OWNER TO postgres;
ALTER FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) SET search_path = public, pg_temp;

-- 2.4 mark_delivery_failure_event_failed(UUID, UUID, TEXT)
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) TO postgres, service_role;
ALTER FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) OWNER TO postgres;
ALTER FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) SET search_path = public, pg_temp;

-- 2.5 claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL)
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) SET search_path = public, pg_temp;

-- 2.6 claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL)
REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) SET search_path = public, pg_temp;

-- 2.7 release_claimed_delivery_failure_event(UUID, UUID)
REVOKE ALL ON FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) OWNER TO postgres;
ALTER FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) SET search_path = public, pg_temp;


-- =====================================================================
-- SECTION 3: HARDEN DOMAIN AUDIT & SCHEDULER WORKER RPCS
-- =====================================================================

-- 3.1 claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL)
REVOKE ALL ON FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_due_domain_audits(UUID, INTEGER, INTERVAL, INTERVAL) SET search_path = public, pg_temp;

-- 3.2 complete_domain_audit(UUID, UUID)
REVOKE ALL ON FUNCTION public.complete_domain_audit(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_domain_audit(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.complete_domain_audit(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.complete_domain_audit(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.complete_domain_audit(UUID, UUID) OWNER TO postgres;
ALTER FUNCTION public.complete_domain_audit(UUID, UUID) SET search_path = public, pg_temp;

-- 3.3 fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER)
REVOKE ALL ON FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) TO postgres, service_role;
ALTER FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) OWNER TO postgres;
ALTER FUNCTION public.fail_domain_audit(UUID, UUID, TEXT, INTEGER, INTEGER) SET search_path = public, pg_temp;

-- 3.4 extend_domain_audit_lease(UUID, UUID, INTERVAL)
REVOKE ALL ON FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.extend_domain_audit_lease(UUID, UUID, INTERVAL) SET search_path = public, pg_temp;


-- =====================================================================
-- SECTION 4: HARDEN MAINTENANCE STORED PROCEDURES
-- =====================================================================

-- 4.1 cleanup_stale_webhook_events()
REVOKE ALL ON FUNCTION public.cleanup_stale_webhook_events() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cleanup_stale_webhook_events() FROM anon;
REVOKE ALL ON FUNCTION public.cleanup_stale_webhook_events() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.cleanup_stale_webhook_events() TO postgres, service_role;
ALTER FUNCTION public.cleanup_stale_webhook_events() OWNER TO postgres;
ALTER FUNCTION public.cleanup_stale_webhook_events() SET search_path = public, pg_temp;

COMMIT;
