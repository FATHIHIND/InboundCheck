-- =====================================================================
-- Migration 031: Durable Notification Outbox, Worker Retry Scheduling & Crash Recovery
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-10-31
-- Reference: Group 45B.3B Remediation
-- Description:
-- 1. Adds retry scheduling columns and partial index to delivery_failure_events.
-- 2. Creates schedule_delivery_failure_retry RPC for atomic bounded retries.
-- 3. Updates claim_received_delivery_failure_events to respect next_attempt_at.
-- 4. Creates public.notification_outbox table with strict tenant isolation,
--    idempotency constraints, and RLS policies.
-- 5. Implements claim_notification_outbox, complete_notification_outbox,
--    and fail_or_retry_notification_outbox RPCs.
-- 6. Enforces strict worker ACLs: REVOKE ALL from PUBLIC/anon/authenticated,
--    GRANT strictly to postgres and service_role.
-- =====================================================================

BEGIN;

-- =====================================================================
-- SECTION 1: EXTEND DELIVERY_FAILURE_EVENTS FOR RETRY SCHEDULING
-- =====================================================================

ALTER TABLE public.delivery_failure_events
  ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMPTZ;

-- Partial index for high-efficiency queue polling with backoff
CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_retry
  ON public.delivery_failure_events(processing_status, next_attempt_at)
  WHERE processing_status IN ('received', 'queued');


-- =====================================================================
-- SECTION 2: UPDATE DELIVERY FAILURE EVENT CLAIM RPCS
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
    WHERE (
      (processing_status = 'received' AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()))
      OR
      (processing_status = 'queued' AND (lease_until IS NULL OR lease_until < NOW()) AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()))
    )
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

-- Secure ACLs for updated claim RPCs
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER, INTERVAL) SET search_path = public, pg_temp;


-- =====================================================================
-- SECTION 3: ATOMIC RETRY SCHEDULING RPC FOR DELIVERY FAILURE EVENTS
-- =====================================================================

CREATE OR REPLACE FUNCTION public.schedule_delivery_failure_retry(
  p_event_id UUID,
  p_worker_id UUID,
  p_error TEXT,
  p_next_attempt_at TIMESTAMPTZ,
  p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE(
  event_id UUID,
  new_status TEXT,
  attempt_count INTEGER,
  scheduled_for TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_current_attempts INTEGER;
  v_status TEXT;
BEGIN
  -- Lock the target row and verify worker ownership
  SELECT dispatch_attempt_count INTO v_current_attempts
  FROM public.delivery_failure_events
  WHERE id = p_event_id
    AND claimed_by = p_worker_id
    AND processing_status IN ('dispatching', 'queued')
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  v_current_attempts := COALESCE(v_current_attempts, 1);

  IF v_current_attempts >= p_max_attempts THEN
    -- Terminal failure after bounded attempts
    v_status := 'failed';
    UPDATE public.delivery_failure_events
    SET processing_status = 'failed',
        processed_at = NOW(),
        processing_error = 'MAX_RETRIES_EXCEEDED (' || v_current_attempts || '/' || p_max_attempts || '): ' || COALESCE(p_error, 'Transient dispatch failures exhausted'),
        claimed_by = NULL,
        lease_until = NULL
    WHERE id = p_event_id;

    RETURN QUERY SELECT p_event_id, v_status, v_current_attempts, NULL::TIMESTAMPTZ;
  ELSE
    -- Requeue for retry with backoff timestamp
    v_status := 'received';
    UPDATE public.delivery_failure_events
    SET processing_status = 'received',
        claimed_by = NULL,
        lease_until = NULL,
        processing_error = p_error,
        next_attempt_at = p_next_attempt_at,
        last_retry_at = NOW()
    WHERE id = p_event_id;

    RETURN QUERY SELECT p_event_id, v_status, v_current_attempts, p_next_attempt_at;
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) TO postgres, service_role;
ALTER FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) OWNER TO postgres;
ALTER FUNCTION public.schedule_delivery_failure_retry(UUID, UUID, TEXT, TIMESTAMPTZ, INTEGER) SET search_path = public, pg_temp;


-- =====================================================================
-- SECTION 4: DURABLE NOTIFICATION OUTBOX TABLE & INDEXES
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.notification_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  channel TEXT NOT NULL DEFAULT 'telegram' CHECK (channel IN ('telegram', 'slack', 'email', 'webhook')),
  idempotency_key TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'dispatching', 'processed', 'failed', 'dead_letter')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
  claimed_by UUID,
  claimed_at TIMESTAMPTZ,
  lease_until TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  CONSTRAINT uq_notification_outbox_tenant_idempotency UNIQUE (user_id, idempotency_key)
);

-- Fast polling and claim index
CREATE INDEX IF NOT EXISTS idx_notification_outbox_claim
  ON public.notification_outbox(status, next_attempt_at)
  WHERE status IN ('queued', 'dispatching');

-- Tenant audit and status inquiry index
CREATE INDEX IF NOT EXISTS idx_notification_outbox_tenant
  ON public.notification_outbox(user_id, created_at DESC);

-- Enable Row Level Security
ALTER TABLE public.notification_outbox ENABLE ROW LEVEL SECURITY;

-- Tenant isolation RLS policies
DROP POLICY IF EXISTS "Users can read own notification outbox" ON public.notification_outbox;
CREATE POLICY "Users can read own notification outbox"
  ON public.notification_outbox
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own notification outbox" ON public.notification_outbox;
CREATE POLICY "Users can insert own notification outbox"
  ON public.notification_outbox
  FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

GRANT SELECT, INSERT ON public.notification_outbox TO authenticated;
GRANT ALL ON public.notification_outbox TO service_role;


-- =====================================================================
-- SECTION 5: NOTIFICATION OUTBOX WORKER RPCS
-- =====================================================================

-- 5.1 Claim Notification Outbox items with lease expiration & recovery
CREATE OR REPLACE FUNCTION public.claim_notification_outbox(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '5 minutes'
)
RETURNS SETOF public.notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.notification_outbox
    WHERE (
      (status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()))
      OR
      (status = 'dispatching' AND lease_until IS NOT NULL AND lease_until < NOW())
    )
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.notification_outbox o
  SET status = 'dispatching',
      attempt_count = o.attempt_count + 1,
      claimed_by = p_worker_id,
      claimed_at = NOW(),
      lease_until = NOW() + p_lease_timeout
  FROM candidates
  WHERE o.id = candidates.id
  RETURNING o.*;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) FROM anon;
REVOKE ALL ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) OWNER TO postgres;
ALTER FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) SET search_path = public, pg_temp;


-- 5.2 Complete Notification Outbox item upon verified delivery
CREATE OR REPLACE FUNCTION public.complete_notification_outbox(
  p_outbox_id UUID,
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
  UPDATE public.notification_outbox
  SET status = 'processed',
      processed_at = NOW(),
      claimed_by = NULL,
      lease_until = NULL,
      last_error = NULL
  WHERE id = p_outbox_id
    AND claimed_by = p_worker_id
    AND status = 'dispatching';

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

REVOKE ALL ON FUNCTION public.complete_notification_outbox(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_notification_outbox(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.complete_notification_outbox(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.complete_notification_outbox(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.complete_notification_outbox(UUID, UUID) OWNER TO postgres;
ALTER FUNCTION public.complete_notification_outbox(UUID, UUID) SET search_path = public, pg_temp;


-- 5.3 Fail or retry Notification Outbox item
CREATE OR REPLACE FUNCTION public.fail_or_retry_notification_outbox(
  p_outbox_id UUID,
  p_worker_id UUID,
  p_error TEXT,
  p_retryable BOOLEAN,
  p_next_attempt_at TIMESTAMPTZ,
  p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE(
  id UUID,
  new_status TEXT,
  attempt_count INTEGER,
  next_attempt_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_current_attempts INTEGER;
  v_max_attempts INTEGER;
  v_status TEXT;
BEGIN
  SELECT o.attempt_count, o.max_attempts INTO v_current_attempts, v_max_attempts
  FROM public.notification_outbox o
  WHERE o.id = p_outbox_id
    AND o.claimed_by = p_worker_id
    AND o.status = 'dispatching'
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  v_current_attempts := COALESCE(v_current_attempts, 1);
  v_max_attempts := COALESCE(p_max_attempts, v_max_attempts, 5);

  IF (NOT p_retryable) OR (v_current_attempts >= v_max_attempts) THEN
    -- Dead letter terminal failure
    v_status := 'dead_letter';
    UPDATE public.notification_outbox
    SET status = 'dead_letter',
        processed_at = NOW(),
        last_error = p_error,
        claimed_by = NULL,
        lease_until = NULL
    WHERE public.notification_outbox.id = p_outbox_id;

    RETURN QUERY SELECT p_outbox_id, v_status, v_current_attempts, NULL::TIMESTAMPTZ;
  ELSE
    -- Retryable: return to queued with scheduled delay
    v_status := 'queued';
    UPDATE public.notification_outbox
    SET status = 'queued',
        next_attempt_at = p_next_attempt_at,
        last_error = p_error,
        claimed_by = NULL,
        lease_until = NULL
    WHERE public.notification_outbox.id = p_outbox_id;

    RETURN QUERY SELECT p_outbox_id, v_status, v_current_attempts, p_next_attempt_at;
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) TO postgres, service_role;
ALTER FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) OWNER TO postgres;
ALTER FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) SET search_path = public, pg_temp;

COMMIT;
