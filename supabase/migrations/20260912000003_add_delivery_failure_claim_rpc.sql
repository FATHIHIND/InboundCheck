-- File: supabase/migrations/20260912000003_add_delivery_failure_claim_rpc.sql
-- Description: Atomic claiming and state transition RPCs for delivery failure events (Phase 4 Step 5)

-- =====================================================================
-- SECTION 1: CLAIM TRACKING COLUMNS & QUEUE INDEX
-- =====================================================================

ALTER TABLE public.delivery_failure_events
  ADD COLUMN IF NOT EXISTS claimed_by UUID,
  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS processing_error TEXT;

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_claim_queue
  ON public.delivery_failure_events(processing_status, claimed_at, received_at)
  WHERE processing_status IN ('received', 'queued');

-- =====================================================================
-- SECTION 2: IDEMPOTENCY INDEX ON FAILOVER_LOGS FOR TELEGRAM ALERTS
-- =====================================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_per_event
  ON public.failover_logs(delivery_failure_event_id)
  WHERE delivery_failure_event_id IS NOT NULL AND channel = 'telegram';

-- =====================================================================
-- SECTION 3: ATOMIC EVENT CLAIMING RPC (FOR UPDATE SKIP LOCKED)
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
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.delivery_failure_events
    WHERE processing_status = 'received'
       OR (processing_status = 'queued' AND claimed_at IS NOT NULL AND claimed_at < NOW() - p_lease_timeout)
    ORDER BY received_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.delivery_failure_events e
  SET processing_status = 'queued',
      claimed_by = p_worker_id,
      claimed_at = NOW()
  FROM candidates
  WHERE e.id = candidates.id
  RETURNING e.*;
END;
$$;

-- =====================================================================
-- SECTION 4: ATOMIC EVENT COMPLETION / IGNORE RPC
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
  UPDATE public.delivery_failure_events
  SET processing_status = p_outcome,
      processed_at = NOW(),
      processing_error = p_reason
  WHERE id = p_event_id
    AND (claimed_by = p_worker_id OR claimed_by IS NULL);

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- =====================================================================
-- SECTION 5: ATOMIC EVENT FAILURE RPC
-- =====================================================================

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
  UPDATE public.delivery_failure_events
  SET processing_status = 'failed',
      processed_at = NOW(),
      processing_error = p_error
  WHERE id = p_event_id
    AND (claimed_by = p_worker_id OR claimed_by IS NULL);

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- =====================================================================
-- SECTION 6: FUNCTION EXECUTION GRANTS
-- =====================================================================

GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) TO authenticated, service_role;
