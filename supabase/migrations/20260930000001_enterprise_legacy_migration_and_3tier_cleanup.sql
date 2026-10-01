-- =====================================================================
-- Migration: Enterprise Legacy Migration & 3-Tier Commercial Cleanup
-- File: supabase/migrations/20260930000001_enterprise_legacy_migration_and_3tier_cleanup.sql
-- Description:
-- 1. Migrates any legacy 'enterprise' profile records to 'agency'.
-- 2. Restricts public.profiles subscription_tier and tier CHECK constraints to ('starter', 'growth', 'agency').
-- 3. Updates atomic domain quota RPC provision_monitored_domain to 3-tier matrix:
--    starter = 1, growth = 3, agency = 20 (removing the legacy 999-domain enterprise branch).
-- =====================================================================

BEGIN;

-- 1. Safely migrate any existing profiles on 'enterprise' to 'agency'
UPDATE public.profiles
SET subscription_tier = 'agency',
    tier = 'agency',
    updated_at = NOW()
WHERE lower(subscription_tier) = 'enterprise'
   OR lower(tier) = 'enterprise';

-- 2. Update subscription_tier CHECK constraint to allow ONLY ('starter', 'growth', 'agency')
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_subscription_tier_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_subscription_tier_check 
    CHECK (subscription_tier IN ('starter', 'growth', 'agency'));

-- 3. Update legacy tier CHECK constraint to allow ONLY ('starter', 'growth', 'agency')
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_tier_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_tier_check 
    CHECK (tier IN ('starter', 'growth', 'agency'));

-- 4. Update the atomic domain provisioning RPC with 3-tier entitlement limits
CREATE OR REPLACE FUNCTION public.provision_monitored_domain(
  p_user_id UUID,
  p_domain_name TEXT,
  p_quota_limit INTEGER,
  p_health_score INTEGER DEFAULT 0,
  p_spf_status TEXT DEFAULT 'missing',
  p_dkim_status TEXT DEFAULT 'missing',
  p_dmarc_status TEXT DEFAULT 'missing',
  p_mx_status TEXT DEFAULT 'missing',
  p_bimi_status TEXT DEFAULT 'missing',
  p_custom_selectors TEXT[] DEFAULT '{}'::text[]
)
RETURNS public.monitored_domains
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_clean_domain TEXT;
  v_existing public.monitored_domains%ROWTYPE;
  v_current_count INTEGER;
  v_inserted public.monitored_domains%ROWTYPE;
  v_lock_key INTEGER;
  v_db_tier TEXT;
  v_allowed_max INTEGER;
BEGIN
  -- 1. Input Validation
  v_clean_domain := lower(trim(p_domain_name));
  IF v_clean_domain = '' OR v_clean_domain IS NULL THEN
    RAISE EXCEPTION 'INVALID_DOMAIN: Domain name cannot be empty.' USING ERRCODE = '22023';
  END IF;

  IF p_quota_limit < 1 THEN
    RAISE EXCEPTION 'INVALID_QUOTA: Quota limit must be at least 1.' USING ERRCODE = '22023';
  END IF;

  -- 2. Tenant Impersonation Defense
  IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
    RAISE EXCEPTION 'ACCESS_DENIED: Cannot provision domain for another tenant.' USING ERRCODE = '42501';
  END IF;

  -- 3. Server-side Entitlement Verification (3-tier commercial model)
  SELECT COALESCE(subscription_tier, tier, 'starter') INTO v_db_tier
  FROM public.profiles
  WHERE id = p_user_id;

  v_allowed_max := CASE lower(COALESCE(v_db_tier, 'starter'))
    WHEN 'starter' THEN 1
    WHEN 'growth' THEN 3
    WHEN 'agency' THEN 20
    ELSE 1
  END;

  IF p_quota_limit > v_allowed_max THEN
    RAISE EXCEPTION 'INVALID_QUOTA: Requested limit (%) exceeds plan allowance (%).',
      p_quota_limit, v_allowed_max USING ERRCODE = '22023';
  END IF;

  -- 4. Transaction-scoped Advisory Lock (Class: 20260928, Key: deterministic 32-bit tenant hash)
  v_lock_key := ('x' || substr(md5(p_user_id::text), 1, 8))::bit(32)::integer;
  PERFORM pg_advisory_xact_lock(20260928, v_lock_key);

  -- 5. Idempotent check for already-owned domain
  SELECT * INTO v_existing
  FROM public.monitored_domains
  WHERE user_id = p_user_id AND domain_name = v_clean_domain;

  IF FOUND THEN
    -- Update existing record (Does NOT consume extra quota)
    UPDATE public.monitored_domains
    SET health_score = COALESCE(p_health_score, health_score),
        spf_status = CASE WHEN p_spf_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_spf_status ELSE spf_status END,
        dkim_status = CASE WHEN p_dkim_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_dkim_status ELSE dkim_status END,
        dmarc_status = CASE WHEN p_dmarc_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_dmarc_status ELSE dmarc_status END,
        mx_status = CASE WHEN p_mx_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_mx_status ELSE mx_status END,
        bimi_status = CASE WHEN p_bimi_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_bimi_status ELSE bimi_status END,
        custom_selectors = CASE WHEN array_length(p_custom_selectors, 1) > 0 THEN p_custom_selectors ELSE custom_selectors END,
        audit_failure_count = 0,
        last_audit_error = NULL,
        next_audit_retry_at = NULL,
        audit_lease_until = NULL,
        is_active = true,
        last_checked_at = NOW(),
        updated_at = NOW()
    WHERE id = v_existing.id
    RETURNING * INTO v_inserted;

    RETURN v_inserted;
  END IF;

  -- 6. Quota Enforcement under Lock
  SELECT COUNT(*) INTO v_current_count
  FROM public.monitored_domains
  WHERE user_id = p_user_id;

  IF v_current_count >= p_quota_limit THEN
    RAISE EXCEPTION 'DOMAIN_QUOTA_EXCEEDED: Tenant domain count (%) reached quota limit (%).',
      v_current_count, p_quota_limit
      USING ERRCODE = 'P0002';
  END IF;

  -- 7. Atomic Insert of New Monitored Domain
  INSERT INTO public.monitored_domains (
    user_id,
    domain_name,
    health_score,
    spf_status,
    dkim_status,
    dmarc_status,
    mx_status,
    bimi_status,
    custom_selectors,
    is_active,
    audit_failure_count,
    last_audit_error,
    next_audit_retry_at,
    audit_lease_until,
    last_checked_at,
    created_at,
    updated_at
  )
  VALUES (
    p_user_id,
    v_clean_domain,
    COALESCE(p_health_score, 0),
    CASE WHEN p_spf_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_spf_status ELSE 'missing' END,
    CASE WHEN p_dkim_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_dkim_status ELSE 'missing' END,
    CASE WHEN p_dmarc_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_dmarc_status ELSE 'missing' END,
    CASE WHEN p_mx_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_mx_status ELSE 'missing' END,
    CASE WHEN p_bimi_status IN ('optimal', 'warning', 'critical', 'missing') THEN p_bimi_status ELSE 'missing' END,
    p_custom_selectors,
    true,
    0,
    NULL,
    NULL,
    NULL,
    NOW(),
    NOW(),
    NOW()
  )
  RETURNING * INTO v_inserted;

  RETURN v_inserted;
END;
$$;

-- Restrict execution to service_role only
REVOKE ALL ON FUNCTION public.provision_monitored_domain(UUID, TEXT, INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.provision_monitored_domain(UUID, TEXT, INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[]) TO service_role;

COMMIT;
