-- Migration: 20260925000001_p1_reliability_remediation.sql
-- Description: Phase 2.1 P1 Reliability Remediation: Decoupled Audit Retry Backoff and Distributed Rate Limiting

-- =====================================================================
-- SECTION 1: DECOUPLED AUDIT RETRY BACKOFF (P1)
-- =====================================================================

-- 1.1 Add explicit next_audit_retry_at column to monitored_domains
ALTER TABLE public.monitored_domains
  ADD COLUMN IF NOT EXISTS next_audit_retry_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_monitored_domains_retry_schedule
  ON public.monitored_domains (next_audit_retry_at)
  WHERE is_active = true AND next_audit_retry_at IS NOT NULL;

-- 1.2 Update candidate selection in claim_due_domain_audits
CREATE OR REPLACE FUNCTION public.claim_due_domain_audits(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 25,
  p_interval INTERVAL DEFAULT INTERVAL '1 hour',
  p_lease_duration INTERVAL DEFAULT INTERVAL '15 minutes'
)
RETURNS SETOF public.monitored_domains
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.monitored_domains
    WHERE is_active = true
      AND (last_audited_at IS NULL OR last_audited_at <= NOW() - p_interval)
      AND (audit_lease_until IS NULL OR audit_lease_until < NOW())
      AND (next_audit_retry_at IS NULL OR next_audit_retry_at <= NOW())
    ORDER BY COALESCE(last_audited_at, created_at) ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.monitored_domains d
  SET audit_lease_owner = p_worker_id,
      audit_lease_until = NOW() + p_lease_duration,
      audit_started_at = NOW()
  FROM candidates
  WHERE d.id = candidates.id
  RETURNING d.*;
END;
$$;

-- 1.3 Update fail_domain_audit with bounded exponential backoff & randomized jitter
CREATE OR REPLACE FUNCTION public.fail_domain_audit(
  p_domain_id UUID,
  p_worker_id UUID,
  p_error TEXT,
  p_base_delay_seconds INTEGER DEFAULT 120,
  p_max_delay_seconds INTEGER DEFAULT 86400
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
  v_current_failures INTEGER;
  v_backoff_seconds DOUBLE PRECISION;
  v_jitter DOUBLE PRECISION;
  v_total_delay_seconds INTEGER;
BEGIN
  -- Obtain current failure count for domain held under active lease
  SELECT COALESCE(audit_failure_count, 0) INTO v_current_failures
  FROM public.monitored_domains
  WHERE id = p_domain_id AND audit_lease_owner = p_worker_id;

  IF NOT FOUND THEN
    RETURN FALSE;
  END IF;

  -- Exponential backoff: base * 2^(failures), capped at max_delay
  -- failures = 0 before first failure -> multiplier 2^0 = 1 (120s)
  v_backoff_seconds := LEAST(
    p_max_delay_seconds::DOUBLE PRECISION,
    p_base_delay_seconds::DOUBLE PRECISION * POWER(2::DOUBLE PRECISION, LEAST(v_current_failures, 10))
  );

  -- Uniform jitter: +0% to +25% of calculated delay
  v_jitter := random() * 0.25 * v_backoff_seconds;

  -- Ensure total delay strictly respects the maximum upper bound
  v_total_delay_seconds := LEAST(p_max_delay_seconds, (v_backoff_seconds + v_jitter)::INTEGER);

  UPDATE public.monitored_domains
  SET audit_lease_owner = NULL,
      audit_lease_until = NULL,
      next_audit_retry_at = NOW() + (v_total_delay_seconds || ' seconds')::INTERVAL,
      audit_failure_count = audit_failure_count + 1,
      last_audit_error = p_error
  WHERE id = p_domain_id
    AND audit_lease_owner = p_worker_id;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- 1.4 Update complete_domain_audit to clear retry backoff and failure state
CREATE OR REPLACE FUNCTION public.complete_domain_audit(
  p_domain_id UUID,
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
  UPDATE public.monitored_domains
  SET audit_lease_owner = NULL,
      audit_lease_until = NULL,
      next_audit_retry_at = NULL,
      last_audited_at = NOW(),
      audit_failure_count = 0,
      last_audit_error = NULL
  WHERE id = p_domain_id
    AND audit_lease_owner = p_worker_id;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;


-- =====================================================================
-- SECTION 2: DISTRIBUTED RATE LIMITING STORAGE (P1)
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.rate_limit_windows (
  bucket_key TEXT NOT NULL,
  window_start BIGINT NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 1,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (bucket_key, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_windows_expires
  ON public.rate_limit_windows (expires_at);

-- 2.1 Atomic token consumption RPC function
CREATE OR REPLACE FUNCTION public.consume_rate_limit(
  p_bucket_key TEXT,
  p_max_requests INTEGER,
  p_window_seconds INTEGER
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_now_epoch BIGINT := EXTRACT(EPOCH FROM NOW())::BIGINT;
  v_window_start BIGINT := (v_now_epoch / p_window_seconds) * p_window_seconds;
  v_expires_at TIMESTAMPTZ := TO_TIMESTAMP(v_window_start + (p_window_seconds * 2));
  v_count INTEGER;
BEGIN
  INSERT INTO public.rate_limit_windows (bucket_key, window_start, request_count, expires_at)
  VALUES (p_bucket_key, v_window_start, 1, v_expires_at)
  ON CONFLICT (bucket_key, window_start)
  DO UPDATE SET request_count = rate_limit_windows.request_count + 1
  RETURNING request_count INTO v_count;

  -- Opportunistic pruning of expired windows (< 1% sample rate)
  IF random() < 0.01 THEN
    DELETE FROM public.rate_limit_windows WHERE expires_at < NOW();
  END IF;

  RETURN jsonb_build_object(
    'allowed', (v_count <= p_max_requests),
    'current_requests', v_count,
    'remaining', GREATEST(0, p_max_requests - v_count),
    'reset_seconds', (v_window_start + p_window_seconds) - v_now_epoch
  );
END;
$$;
