-- =====================================================================
-- Migration: AI Monthly Generation Quota Ledger & Atomic Enforcement RPC
-- File: supabase/migrations/20260930000002_ai_monthly_quota_ledger.sql
-- Description:
-- 1. Creates public.ai_generation_usage ledger table (user_id, billing_period).
-- 2. Enforces non-negative counts and ISO calendar month billing period format (YYYY-MM).
-- 3. Provides atomic consume_ai_monthly_generation RPC with FOR UPDATE row locking,
--    tenant isolation, and defense-in-depth server-side tier capping:
--    - Starter: 20 generations/month
--    - Growth: 100 generations/month
--    - Agency: 500 generations/month
--    - Legacy Enterprise: 500 generations/month
-- 4. Provides compensation/rollback RPC rollback_ai_monthly_generation if generation
--    fails or Liquid tags are corrupted.
-- 5. Hardened RPC Security Model (Step 17B.1):
--    - Execution granted solely to service_role (trusted backend).
--    - Execution strictly revoked from PUBLIC, anon, and authenticated roles.
--    - Eliminates direct client-side RPC invocation, quota burn, or artificial rollbacks.
-- =====================================================================

BEGIN;

-- 1. Create the persistent AI monthly usage ledger table
CREATE TABLE IF NOT EXISTS public.ai_generation_usage (
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    billing_period TEXT NOT NULL,
    generation_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, billing_period),
    CONSTRAINT check_ai_generation_count_non_negative CHECK (generation_count >= 0),
    CONSTRAINT check_billing_period_format CHECK (billing_period ~ '^\d{4}-\d{2}$')
);

-- Note: PRIMARY KEY (user_id, billing_period) implicitly creates the unique B-tree index.
-- Redundant secondary index on identical columns was removed in Step 17B.1.

-- 2. Row Level Security (RLS)
ALTER TABLE public.ai_generation_usage ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own AI generation usage" ON public.ai_generation_usage;
CREATE POLICY "Users can view their own AI generation usage"
    ON public.ai_generation_usage
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- 3. Atomic Quota Consumption RPC
CREATE OR REPLACE FUNCTION public.consume_ai_monthly_generation(
    p_user_id UUID,
    p_billing_period TEXT,
    p_monthly_limit INTEGER
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_clean_period TEXT;
    v_db_tier TEXT;
    v_allowed_max INTEGER;
    v_current_count INTEGER;
    v_new_count INTEGER;
BEGIN
    -- 3.1. Input Validation
    v_clean_period := trim(p_billing_period);
    IF v_clean_period IS NULL OR NOT (v_clean_period ~ '^\d{4}-\d{2}$') THEN
        RAISE EXCEPTION 'INVALID_PERIOD: Billing period format must be YYYY-MM.' USING ERRCODE = '22023';
    END IF;

    IF p_monthly_limit < 1 THEN
        RAISE EXCEPTION 'INVALID_LIMIT: Monthly quota limit must be at least 1.' USING ERRCODE = '22023';
    END IF;

    -- 3.2. Tenant Impersonation Defense
    IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot consume quota for another tenant.' USING ERRCODE = '42501';
    END IF;

    -- 3.3. Server-side Entitlement Verification (Defense-in-depth against client tampering)
    SELECT COALESCE(subscription_tier, tier, 'starter') INTO v_db_tier
    FROM public.profiles
    WHERE id = p_user_id;

    v_allowed_max := CASE lower(COALESCE(v_db_tier, 'starter'))
        WHEN 'starter' THEN 20
        WHEN 'growth' THEN 100
        WHEN 'agency' THEN 500
        WHEN 'enterprise' THEN 500 -- legacy enterprise safely resolves to agency quota
        ELSE 20
    END;

    -- Requested limit cannot exceed authoritative database tier allowance
    IF p_monthly_limit > v_allowed_max THEN
        p_monthly_limit := v_allowed_max;
    END IF;

    -- 3.4. Ensure period row exists atomically (INSERT ... ON CONFLICT DO NOTHING)
    INSERT INTO public.ai_generation_usage (user_id, billing_period, generation_count, created_at, updated_at)
    VALUES (p_user_id, v_clean_period, 0, NOW(), NOW())
    ON CONFLICT (user_id, billing_period) DO NOTHING;

    -- 3.5. Row-level lock on (user_id, billing_period) to eliminate TOCTOU race conditions
    SELECT generation_count
    INTO v_current_count
    FROM public.ai_generation_usage
    WHERE user_id = p_user_id AND billing_period = v_clean_period
    FOR UPDATE;

    -- 3.6. Check current usage against limit
    IF v_current_count >= p_monthly_limit THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'current_usage', v_current_count,
            'limit', p_monthly_limit,
            'remaining', 0
        );
    END IF;

    -- 3.7. Atomically increment usage
    v_new_count := v_current_count + 1;
    UPDATE public.ai_generation_usage
    SET generation_count = v_new_count,
        updated_at = NOW()
    WHERE user_id = p_user_id AND billing_period = v_clean_period;

    RETURN jsonb_build_object(
        'allowed', true,
        'current_usage', v_new_count,
        'limit', p_monthly_limit,
        'remaining', GREATEST(0, p_monthly_limit - v_new_count)
    );
END;
$$;

-- 4. Compensation / Rollback RPC
CREATE OR REPLACE FUNCTION public.rollback_ai_monthly_generation(
    p_user_id UUID,
    p_billing_period TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_clean_period TEXT;
BEGIN
    v_clean_period := trim(p_billing_period);

    -- Tenant Impersonation Defense
    IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot rollback quota for another tenant.' USING ERRCODE = '42501';
    END IF;

    UPDATE public.ai_generation_usage
    SET generation_count = GREATEST(0, generation_count - 1),
        updated_at = NOW()
    WHERE user_id = p_user_id AND billing_period = v_clean_period;
END;
$$;

-- 5. Query Function for Telemetry and Diagnostics
CREATE OR REPLACE FUNCTION public.get_ai_monthly_usage(
    p_user_id UUID,
    p_billing_period TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot query quota for another tenant.' USING ERRCODE = '42501';
    END IF;

    SELECT generation_count INTO v_count
    FROM public.ai_generation_usage
    WHERE user_id = p_user_id AND billing_period = trim(p_billing_period);

    RETURN COALESCE(v_count, 0);
END;
$$;

-- 6. Restrict Execution Permissions (Step 17B.1 Hardened ACL)
-- Quota manipulation RPCs are backend-internal and must ONLY be callable via service_role.
-- Direct execution by PUBLIC, anon, and authenticated roles is explicitly revoked.
REVOKE ALL ON FUNCTION public.consume_ai_monthly_generation(UUID, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_ai_monthly_generation(UUID, TEXT, INTEGER) TO service_role;

REVOKE ALL ON FUNCTION public.rollback_ai_monthly_generation(UUID, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rollback_ai_monthly_generation(UUID, TEXT) TO service_role;

REVOKE ALL ON FUNCTION public.get_ai_monthly_usage(UUID, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ai_monthly_usage(UUID, TEXT) TO service_role;

COMMIT;
