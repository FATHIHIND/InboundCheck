-- Migration: 20260926000001_p1_failover_lease_recovery.sql
-- Description: Phase 2.3 P1 Operational Remediation: Failover Worker Lease Expiry, Stale Recovery & Graceful Release (OPS-03)

-- =====================================================================
-- SECTION 1: LEASE EXPIRY COLUMN & QUEUE INDEX
-- =====================================================================

ALTER TABLE public.delivery_failure_events
  ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_lease_queue
  ON public.delivery_failure_events(processing_status, lease_until, received_at)
  WHERE processing_status IN ('received', 'queued');

-- =====================================================================
-- SECTION 2: ATOMIC CLAIM RPC WITH STALE RECOVERY (FOR UPDATE SKIP LOCKED)
-- =====================================================================

-- 2.1 Primary claim RPC preserving existing parameter name p_lease_timeout
-- Eliminates PostgreSQL 42P13 parameter rename error while implementing OPS-03 lease recovery
CREATE OR REPLACE FUNCTION public.claim_received_delivery_failure_events(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '15 minutes'
)
RETURNS SETOF public.delivery_failure_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.delivery_failure_events
    WHERE processing_status = 'received'
       OR (processing_status = 'queued' AND (lease_until IS NULL OR lease_until < NOW()))
    ORDER BY received_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.delivery_failure_events e
  SET processing_status = 'queued',
      claimed_by = p_worker_id,
      claimed_at = NOW(),
      lease_until = NOW() + p_lease_timeout
  FROM candidates
  WHERE e.id = candidates.id
  RETURNING e.*;
END;
$$;

-- 2.2 Drop legacy 2-parameter signature if present to prevent ambiguous overloading
DROP FUNCTION IF EXISTS public.claim_pending_delivery_failure_events(UUID, INTEGER);

-- 2.3 Provide claim_pending_delivery_failure_events with matching p_lease_timeout
CREATE OR REPLACE FUNCTION public.claim_pending_delivery_failure_events(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '15 minutes'
)
RETURNS SETOF public.delivery_failure_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY SELECT * FROM public.claim_received_delivery_failure_events(p_worker_id, p_limit, p_lease_timeout);
END;
$$;

-- =====================================================================
-- SECTION 3: GRACEFUL RELEASE RPC FOR SIGTERM DRAIN
-- =====================================================================

CREATE OR REPLACE FUNCTION public.release_claimed_delivery_failure_event(
  p_event_id UUID,
  p_worker_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  UPDATE public.delivery_failure_events
  SET processing_status = 'received',
      claimed_by = NULL,
      claimed_at = NULL,
      lease_until = NULL
  WHERE id = p_event_id
    AND claimed_by = p_worker_id
    AND processing_status = 'queued';

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- Grant execution to authenticated and service_role
GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.release_claimed_delivery_failure_event(UUID, UUID) TO authenticated, service_role;

