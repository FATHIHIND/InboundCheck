-- INV-15: Telegram has no idempotency key. This is conservative unknown-outcome
-- quarantine, NOT exactly-once delivery. Requires coordinated worker rollout:
-- stop/drain old workers before deployment; never run mixed old/new senders.
-- Source only: do not execute without separately authorized DB rollout.
BEGIN;
ALTER TABLE public.notification_outbox
  ADD COLUMN IF NOT EXISTS dispatch_started_at TIMESTAMPTZ;

-- Pre-upgrade claims have no reliable pre-send evidence. Treat them as uncertain
-- rather than reclassifying possibly accepted messages as safe-to-retry.
UPDATE public.notification_outbox
SET dispatch_started_at = COALESCE(claimed_at, NOW())
WHERE status = 'dispatching' AND dispatch_started_at IS NULL;

CREATE OR REPLACE FUNCTION public.record_notification_outbox_dispatch_intent(
  p_outbox_id UUID, p_worker_id UUID
)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_updated INTEGER;
BEGIN
  UPDATE public.notification_outbox
  SET dispatch_started_at = NOW()
  WHERE id = p_outbox_id AND claimed_by = p_worker_id
    AND status = 'dispatching' AND dispatch_started_at IS NULL
    AND lease_until IS NOT NULL AND lease_until > NOW();
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_notification_outbox(
  p_worker_id UUID, p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '5 minutes'
)
RETURNS SETOF public.notification_outbox
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 0), 0), 500);
BEGIN
  IF p_worker_id IS NULL OR v_limit = 0 OR p_lease_timeout IS NULL
     OR p_lease_timeout <= INTERVAL '0 seconds' THEN RETURN; END IF;

  -- Bounded, concurrency-safe sweep. Unknown outcomes are never claimable again.
  WITH uncertain AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE o.status = 'dispatching' AND o.dispatch_started_at IS NOT NULL
      AND (o.lease_until IS NULL OR o.lease_until <= NOW())
    ORDER BY o.lease_until NULLS FIRST, o.created_at
    FOR UPDATE SKIP LOCKED LIMIT v_limit
  )
  UPDATE public.notification_outbox o
  SET status = 'dead_letter', processed_at = NOW(), claimed_by = NULL,
      lease_until = NULL,
      last_error = 'AMBIGUOUS_EXTERNAL_DISPATCH: lease expired after send intent; manual reconciliation required'
  FROM uncertain WHERE o.id = uncertain.id;

  RETURN QUERY
  WITH candidates AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE o.dispatch_started_at IS NULL AND (
      (o.status = 'queued' AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= NOW()))
      OR (o.status = 'dispatching' AND (o.lease_until IS NULL OR o.lease_until <= NOW()))
    )
    ORDER BY o.created_at FOR UPDATE SKIP LOCKED LIMIT v_limit
  )
  UPDATE public.notification_outbox o
  SET status = 'dispatching', attempt_count = o.attempt_count + 1,
      claimed_by = p_worker_id, claimed_at = NOW(), lease_until = NOW() + p_lease_timeout
  FROM candidates WHERE o.id = candidates.id RETURNING o.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_notification_outbox(p_outbox_id UUID, p_worker_id UUID)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE v_updated INTEGER;
BEGIN
  UPDATE public.notification_outbox
  SET status = 'processed', processed_at = NOW(), claimed_by = NULL,
      lease_until = NULL, last_error = NULL
  WHERE id = p_outbox_id AND claimed_by = p_worker_id AND status = 'dispatching'
    AND lease_until IS NOT NULL AND lease_until > NOW();
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_or_retry_notification_outbox(
  p_outbox_id UUID, p_worker_id UUID, p_error TEXT, p_retryable BOOLEAN,
  p_next_attempt_at TIMESTAMPTZ, p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE(id UUID, new_status TEXT, attempt_count INTEGER, next_attempt_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE v_attempts INTEGER; v_max INTEGER; v_status TEXT;
BEGIN
  SELECT o.attempt_count, LEAST(o.max_attempts, GREATEST(COALESCE(p_max_attempts, o.max_attempts), 1))
  INTO v_attempts, v_max FROM public.notification_outbox o
  WHERE o.id = p_outbox_id AND o.claimed_by = p_worker_id AND o.status = 'dispatching'
    AND o.lease_until IS NOT NULL AND o.lease_until > NOW() FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  -- Caller may retry only a definitive pre-send failure or explicit rejection.
  -- A clearly tagged unknown outcome can NEVER be requeued even if misflagged.
  IF NOT COALESCE(p_retryable, FALSE) OR v_attempts >= v_max
     OR p_error LIKE 'AMBIGUOUS_EXTERNAL_DISPATCH:%' THEN
    v_status := 'dead_letter';
    UPDATE public.notification_outbox o
    SET status = v_status, processed_at = NOW(), last_error = p_error,
        claimed_by = NULL, lease_until = NULL
    WHERE o.id = p_outbox_id;
    RETURN QUERY SELECT p_outbox_id, v_status, v_attempts, NULL::TIMESTAMPTZ;
  ELSE
    v_status := 'queued';
    UPDATE public.notification_outbox o
    SET status = v_status, next_attempt_at = p_next_attempt_at,
        last_error = p_error, claimed_by = NULL, lease_until = NULL,
        dispatch_started_at = NULL
    WHERE o.id = p_outbox_id;
    RETURN QUERY SELECT p_outbox_id, v_status, v_attempts, p_next_attempt_at;
  END IF;
END;
$$;

-- No browser/user execution of worker state transitions. Preserve tenant RLS.
REVOKE ALL ON FUNCTION public.record_notification_outbox_dispatch_intent(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_notification_outbox_dispatch_intent(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.record_notification_outbox_dispatch_intent(UUID, UUID) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) TO postgres, service_role;
ALTER FUNCTION public.claim_notification_outbox(UUID, INTEGER, INTERVAL) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.complete_notification_outbox(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_notification_outbox(UUID, UUID) TO postgres, service_role;
ALTER FUNCTION public.complete_notification_outbox(UUID, UUID) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) TO postgres, service_role;
ALTER FUNCTION public.fail_or_retry_notification_outbox(UUID, UUID, TEXT, BOOLEAN, TIMESTAMPTZ, INTEGER) OWNER TO postgres;
COMMIT;
