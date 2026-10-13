-- Telegram-only merchant incident alerts use failover_logs as an operational
-- audit trail. Legacy SMS/WhatsApp values remain readable for historical data.

ALTER TABLE public.failover_logs
  ALTER COLUMN customer_phone DROP NOT NULL;

ALTER TABLE public.failover_logs
  DROP CONSTRAINT IF EXISTS failover_logs_fallback_channel_check;

ALTER TABLE public.failover_logs
  DROP CONSTRAINT IF EXISTS check_failover_logs_channel;

DO $$
DECLARE
  conname text;
BEGIN
  FOR conname IN (
    SELECT con.conname 
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE rel.relname = 'failover_logs' 
      AND con.contype = 'c' 
      AND pg_get_constraintdef(con.oid) LIKE '%fallback_channel%'
  ) LOOP
    EXECUTE 'ALTER TABLE public.failover_logs DROP CONSTRAINT IF EXISTS ' || quote_ident(conname);
  END LOOP;
END $$;

ALTER TABLE public.failover_logs
  ADD CONSTRAINT failover_logs_fallback_channel_check
  CHECK (fallback_channel IN ('telegram', 'sms', 'whatsapp'));

-- Add an idempotency index for Telegram incident records:
CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_incident_per_event
ON public.failover_logs(delivery_failure_event_id)
WHERE delivery_failure_event_id IS NOT NULL
  AND fallback_channel = 'telegram';

-- Add worker-claim RPC:
-- Select only processing_status = 'received', lock using FOR UPDATE SKIP LOCKED,
-- update selected rows to queued, and return the claimed records.
CREATE OR REPLACE FUNCTION public.claim_pending_delivery_failure_events(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20
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
    ORDER BY received_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.delivery_failure_events event
  SET processing_status = 'queued',
      claimed_by = p_worker_id,
      claimed_at = NOW()
  FROM candidates
  WHERE event.id = candidates.id
  RETURNING event.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER) TO authenticated, service_role;
