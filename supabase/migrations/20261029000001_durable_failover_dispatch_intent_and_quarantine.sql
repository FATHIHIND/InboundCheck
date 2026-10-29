-- Migration: 20261029000001_durable_failover_dispatch_intent_and_quarantine.sql
-- Description: Group 43D/43F: Durable Telegram Ambiguous-Outcome Recovery, Dispatch Intent Quarantine & Stale-Worker Protection
--
-- Adds durable dispatch-intent state tracking, conservative quarantine for delivery_failure_events,
-- and strict stale-worker lease boundaries.
--
-- Addresses the crash window where Telegram accepts sendMessage but the worker crashes before
-- persisting the incident log. Expired dispatching events without confirmed incident logs are safely
-- quarantined, capped by an atomic concurrency-safe limit. Stale workers cannot override quarantined
-- events or events acquired by newer workers unless an explicit durable incident log confirms dispatch.

-- =====================================================================
-- SECTION 1: EXTEND PROCESSING_STATUS CONSTRAINT & INTENT COLUMNS
-- =====================================================================

ALTER TABLE public.delivery_failure_events
  ADD COLUMN IF NOT EXISTS dispatch_intent_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS dispatch_attempt_count INTEGER DEFAULT 0;

-- Drop and replace processing_status check constraint to include 'dispatching' and 'quarantined'
ALTER TABLE public.delivery_failure_events
  DROP CONSTRAINT IF EXISTS delivery_failure_events_processing_status_check;

ALTER TABLE public.delivery_failure_events
  ADD CONSTRAINT delivery_failure_events_processing_status_check
  CHECK (processing_status IN ('received', 'ignored', 'queued', 'dispatching', 'quarantined', 'processed', 'failed'));

-- Index on dispatching and quarantined events for fast lease monitoring & operational sweeps
CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_dispatching_queue
  ON public.delivery_failure_events(processing_status, lease_until)
  WHERE processing_status IN ('dispatching', 'quarantined');

-- =====================================================================
-- SECTION 2: ATOMIC DISPATCH INTENT REGISTRATION RPC
-- =====================================================================

CREATE OR REPLACE FUNCTION public.record_delivery_failure_dispatch_intent(
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
  SET processing_status = 'dispatching',
      dispatch_intent_at = NOW(),
      dispatch_attempt_count = COALESCE(dispatch_attempt_count, 0) + 1
  WHERE id = p_event_id
    AND claimed_by = p_worker_id
    AND processing_status = 'queued'
    AND lease_until IS NOT NULL
    AND lease_until > NOW();

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- =====================================================================
-- SECTION 3: ATOMIC SWEEP & QUARANTINE RPC WITH HARD LIMIT & SKIP LOCKED
-- =====================================================================

CREATE OR REPLACE FUNCTION public.quarantine_expired_dispatch_intent_events(
  p_limit INTEGER DEFAULT 50
)
RETURNS TABLE(
  event_id UUID,
  user_id UUID,
  esp_provider TEXT,
  resolution TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_limit INTEGER;
BEGIN
  -- Strict limit validation: NULL, 0, or negative limits exit immediately without changes
  IF p_limit IS NULL OR p_limit <= 0 THEN
    RETURN;
  END IF;

  v_limit := LEAST(p_limit, 500);

  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.delivery_failure_events
    WHERE processing_status = 'dispatching'
      AND lease_until IS NOT NULL
      AND lease_until < NOW()
    ORDER BY lease_until ASC
    FOR UPDATE SKIP LOCKED
    LIMIT v_limit
  ),
  classified AS (
    SELECT 
      c.id AS cand_id,
      EXISTS (
        SELECT 1 FROM public.failover_logs fl
        WHERE fl.delivery_failure_event_id = c.id
          AND fl.fallback_channel = 'telegram'
          AND fl.status IN ('delivered', 'dispatched')
      ) AS has_confirmed_log
    FROM candidates c
  ),
  updated AS (
    UPDATE public.delivery_failure_events e
    SET processing_status = CASE 
          WHEN cl.has_confirmed_log THEN 'processed'
          ELSE 'quarantined'
        END,
        processed_at = NOW(),
        processing_error = CASE 
          WHEN cl.has_confirmed_log THEN 'Resolved on lease expiry via existing durable incident log'
          ELSE 'AMBIGUOUS_EXTERNAL_DISPATCH: worker lease expired during dispatch without durable incident confirmation'
        END
    FROM classified cl
    WHERE e.id = cl.cand_id
    RETURNING 
      e.id AS event_id, 
      e.user_id, 
      e.esp_provider, 
      CASE 
        WHEN e.processing_status = 'processed' THEN 'resolved_processed'::TEXT
        ELSE 'quarantined_ambiguous'::TEXT
      END AS resolution
  )
  SELECT u.event_id, u.user_id, u.esp_provider, u.resolution FROM updated u;
END;
$$;

-- =====================================================================
-- SECTION 4: STALE-WORKER FINALIZATION PROTECTION RPCS
-- =====================================================================

CREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_processed(
  p_event_id UUID,
  p_worker_id UUID,
  p_outcome TEXT DEFAULT 'processed',
  p_reason TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  -- Stale worker safety invariants:
  -- 1) Worker must match claimed_by.
  -- 2) Normal execution allows transition from 'dispatching' or 'queued'.
  -- 3) Stale worker CANNOT overwrite 'quarantined' unless a confirmed durable incident
  --    already exists in failover_logs (reconciliation rule).
  -- 4) Worker CANNOT overwrite an event claimed by another worker or already terminal ('processed', 'failed').
  UPDATE public.delivery_failure_events e
  SET processing_status = p_outcome,
      processed_at = NOW(),
      processing_error = p_reason
  WHERE e.id = p_event_id
    AND e.claimed_by = p_worker_id
    AND (
      e.processing_status IN ('dispatching', 'queued')
      OR (
        e.processing_status = 'quarantined'
        AND EXISTS (
          SELECT 1 FROM public.failover_logs fl
          WHERE fl.delivery_failure_event_id = e.id
            AND fl.fallback_channel = 'telegram'
            AND fl.status IN ('delivered', 'dispatched')
        )
      )
    );

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_failed(
  p_event_id UUID,
  p_worker_id UUID,
  p_error TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  -- Stale worker cannot mark failed if event was claimed by another worker,
  -- or if the event has already been quarantined or processed.
  UPDATE public.delivery_failure_events e
  SET processing_status = 'failed',
      processed_at = NOW(),
      processing_error = p_error
  WHERE e.id = p_event_id
    AND e.claimed_by = p_worker_id
    AND e.processing_status IN ('dispatching', 'queued');

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- =====================================================================
-- SECTION 5: INTEGRATE QUARANTINE SWEEP INTO CLAIM RPC
-- =====================================================================

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
  -- Automatically sweep and quarantine any expired dispatching events
  PERFORM public.quarantine_expired_dispatch_intent_events(p_limit);

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
-- SECTION 6: FUNCTION GRANTS
-- =====================================================================

GRANT EXECUTE ON FUNCTION public.record_delivery_failure_dispatch_intent(UUID, UUID) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.quarantine_expired_dispatch_intent_events(INTEGER) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;

-- =====================================================================
-- SECTION 7: ROLLBACK GUIDANCE & OPERATIONAL SAFETY
-- =====================================================================
-- In the event of a rollback, NEVER blindly requeue ambiguous events to 'received'.
-- Rollback steps:
-- 1. Reconcile remaining quarantined/dispatching events:
--    UPDATE public.delivery_failure_events
--    SET processing_status = 'failed',
--        processing_error = 'Rollback reconciliation: unverified dispatch attempt terminated'
--    WHERE processing_status IN ('dispatching', 'quarantined');
-- 2. Drop updated functions:
--    DROP FUNCTION IF EXISTS public.record_delivery_failure_dispatch_intent(UUID, UUID);
--    DROP FUNCTION IF EXISTS public.quarantine_expired_dispatch_intent_events(INTEGER);
-- 3. Restore previous processing_status constraint:
--    ALTER TABLE public.delivery_failure_events DROP CONSTRAINT delivery_failure_events_processing_status_check;
--    ALTER TABLE public.delivery_failure_events ADD CONSTRAINT delivery_failure_events_processing_status_check
--      CHECK (processing_status IN ('received', 'ignored', 'queued', 'processed', 'failed'));
-- 4. Drop queue index and columns (optional):
--    DROP INDEX IF EXISTS public.idx_delivery_failure_events_dispatching_queue;
--    ALTER TABLE public.delivery_failure_events DROP COLUMN IF EXISTS dispatch_intent_at;
--    ALTER TABLE public.delivery_failure_events DROP COLUMN IF EXISTS dispatch_attempt_count;
