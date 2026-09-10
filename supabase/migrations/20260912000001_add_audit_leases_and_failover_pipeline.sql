-- File: supabase/migrations/20260912000001_add_audit_leases_and_failover_pipeline.sql
-- Description: Distributed audit synchronization leases and enhanced failover incident logs (Phase 4 Lite)

-- =====================================================================
-- SECTION 1: DISTRIBUTED AUDIT LEASE COLUMNS & INDEXES
-- =====================================================================

ALTER TABLE public.monitored_domains
  ADD COLUMN IF NOT EXISTS last_audited_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS audit_lease_owner UUID,
  ADD COLUMN IF NOT EXISTS audit_lease_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS audit_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS audit_failure_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_audit_error TEXT;

CREATE INDEX IF NOT EXISTS idx_monitored_domains_due_audit
  ON public.monitored_domains (last_audited_at, audit_lease_until)
  WHERE is_active = true;

-- =====================================================================
-- SECTION 2: ATOMIC AUDIT LEASE RPC FUNCTIONS (FOR UPDATE SKIP LOCKED)
-- =====================================================================

-- 2.1 Claim due domain audits atomically across multiple background workers
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

-- 2.2 Complete domain audit upon successful scan (only if lease is still owned by worker)
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
      last_audited_at = NOW(),
      audit_failure_count = 0,
      last_audit_error = NULL
  WHERE id = p_domain_id
    AND audit_lease_owner = p_worker_id;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- 2.3 Record audit failure and release lease (only if lease is still owned by worker)
CREATE OR REPLACE FUNCTION public.fail_domain_audit(
  p_domain_id UUID,
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
  UPDATE public.monitored_domains
  SET audit_lease_owner = NULL,
      audit_lease_until = NULL,
      audit_failure_count = audit_failure_count + 1,
      last_audit_error = p_error
  WHERE id = p_domain_id
    AND audit_lease_owner = p_worker_id;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

-- =====================================================================
-- SECTION 3: ENHANCE FAILOVER_LOGS TABLE WITH TELEGRAM INCIDENT FIELDS
-- =====================================================================

ALTER TABLE public.failover_logs
  ADD COLUMN IF NOT EXISTS domain_name TEXT,
  ADD COLUMN IF NOT EXISTS store_name TEXT,
  ADD COLUMN IF NOT EXISTS triggered_reason TEXT,
  ADD COLUMN IF NOT EXISTS target_chat_id TEXT,
  ADD COLUMN IF NOT EXISTS customer_email TEXT,
  ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_failover_logs_user_created
  ON public.failover_logs (user_id, created_at DESC);
