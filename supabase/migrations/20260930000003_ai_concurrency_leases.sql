-- =====================================================================
-- Migration: AI Distributed Concurrency Leases & Atomic Enforcement RPC
-- File: supabase/migrations/20260930000003_ai_concurrency_leases.sql
-- Description:
-- 1. Creates public.ai_concurrency_leases table for distributed horizontal scaling.
-- 2. Enforces tenant-isolated atomic acquisition RPC with transaction advisory locking:
--    - Starter: maximum 1 concurrent generation
--    - Growth: maximum 2 concurrent generations
--    - Agency: maximum 5 concurrent generations
--    - Legacy Enterprise: maximum 5 concurrent generations
-- 3. Automatic lease expiration (default 60s TTL) for crash/OOM safety.
-- 4. Fast graceful release RPC for request completion/error handling.
-- 5. Hardened security model: service_role only execution, RLS enabled, search_path fixed.
-- =====================================================================

BEGIN;

-- 1. Create short-lived distributed concurrency lease table
CREATE TABLE IF NOT EXISTS public.ai_concurrency_leases (
    lease_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Index for fast tenant active lease lookup and expiration pruning
CREATE INDEX IF NOT EXISTS idx_ai_concurrency_leases_user_exp 
    ON public.ai_concurrency_leases (user_id, expires_at);

-- 2. Row Level Security (RLS)
ALTER TABLE public.ai_concurrency_leases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own AI concurrency leases" ON public.ai_concurrency_leases;
CREATE POLICY "Users can view their own AI concurrency leases"
    ON public.ai_concurrency_leases
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- 3. Atomic Concurrency Slot Acquisition RPC
CREATE OR REPLACE FUNCTION public.acquire_ai_concurrency_slot(
    p_user_id UUID,
    p_concurrency_limit INTEGER,
    p_lease_id UUID,
    p_ttl_seconds INTEGER DEFAULT 60
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_db_tier TEXT;
    v_allowed_max INTEGER;
    v_lock_key INTEGER;
    v_active_count INTEGER;
    v_effective_ttl INTEGER;
BEGIN
    -- 3.1. Input Validation
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'INVALID_USER: user_id cannot be null.' USING ERRCODE = '22023';
    END IF;

    IF p_lease_id IS NULL THEN
        RAISE EXCEPTION 'INVALID_LEASE: lease_id cannot be null.' USING ERRCODE = '22023';
    END IF;

    IF p_concurrency_limit < 1 THEN
        RAISE EXCEPTION 'INVALID_LIMIT: Concurrency limit must be at least 1.' USING ERRCODE = '22023';
    END IF;

    v_effective_ttl := COALESCE(p_ttl_seconds, 60);
    IF v_effective_ttl < 5 OR v_effective_ttl > 180 THEN
        v_effective_ttl := 60;
    END IF;

    -- 3.2. Tenant Impersonation Defense
    IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot acquire concurrency slot for another tenant.' USING ERRCODE = '42501';
    END IF;

    -- 3.3. Server-side Entitlement Verification (Defense-in-depth against client tampering)
    SELECT COALESCE(subscription_tier, tier, 'starter') INTO v_db_tier
    FROM public.profiles
    WHERE id = p_user_id;

    v_allowed_max := CASE lower(COALESCE(v_db_tier, 'starter'))
        WHEN 'starter' THEN 1
        WHEN 'growth' THEN 2
        WHEN 'agency' THEN 5
        WHEN 'enterprise' THEN 5 -- legacy enterprise safely resolves to agency quota
        ELSE 1
    END;

    IF p_concurrency_limit > v_allowed_max THEN
        p_concurrency_limit := v_allowed_max;
    END IF;

    -- 3.4. Transaction-scoped Advisory Lock (Class: 20260930, Key: deterministic 32-bit tenant hash)
    -- Serializes concurrent acquisition attempts for the same tenant across all Railway nodes.
    v_lock_key := ('x' || substr(md5(p_user_id::text), 1, 8))::bit(32)::integer;
    PERFORM pg_advisory_xact_lock(20260930, v_lock_key);

    -- 3.5. Lazy cleanup of expired leases for this tenant
    DELETE FROM public.ai_concurrency_leases
    WHERE user_id = p_user_id AND expires_at < NOW();

    -- 3.6. Count active non-expired leases for tenant
    SELECT COUNT(*) INTO v_active_count
    FROM public.ai_concurrency_leases
    WHERE user_id = p_user_id AND expires_at >= NOW();

    -- 3.7. Check capacity
    IF v_active_count >= p_concurrency_limit THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'current_active', v_active_count,
            'concurrency_limit', p_concurrency_limit,
            'lease_id', NULL
        );
    END IF;

    -- 3.8. Create new active lease
    INSERT INTO public.ai_concurrency_leases (
        lease_id,
        user_id,
        acquired_at,
        expires_at
    ) VALUES (
        p_lease_id,
        p_user_id,
        NOW(),
        NOW() + (v_effective_ttl || ' seconds')::interval
    );

    RETURN jsonb_build_object(
        'allowed', true,
        'current_active', v_active_count + 1,
        'concurrency_limit', p_concurrency_limit,
        'lease_id', p_lease_id
    );
END;
$$;

-- 4. Graceful Concurrency Slot Release RPC
CREATE OR REPLACE FUNCTION public.release_ai_concurrency_slot(
    p_user_id UUID,
    p_lease_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    -- Tenant Impersonation Defense
    IF (auth.uid() IS NOT NULL AND auth.uid() <> p_user_id) THEN
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot release concurrency slot for another tenant.' USING ERRCODE = '42501';
    END IF;

    DELETE FROM public.ai_concurrency_leases
    WHERE user_id = p_user_id AND lease_id = p_lease_id;

    RETURN FOUND;
END;
$$;

-- 5. Query Function for Telemetry and Diagnostics
CREATE OR REPLACE FUNCTION public.get_ai_active_concurrency(
    p_user_id UUID
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
        RAISE EXCEPTION 'ACCESS_DENIED: Cannot query concurrency for another tenant.' USING ERRCODE = '42501';
    END IF;

    SELECT COUNT(*) INTO v_count
    FROM public.ai_concurrency_leases
    WHERE user_id = p_user_id AND expires_at >= NOW();

    RETURN COALESCE(v_count, 0);
END;
$$;

-- 6. Restrict Execution Permissions (Hardened ACL)
-- Concurrency leases are internal to backend orchestration and must ONLY be callable via service_role.
-- Direct execution by PUBLIC, anon, and authenticated roles is explicitly revoked.
REVOKE ALL ON FUNCTION public.acquire_ai_concurrency_slot(UUID, INTEGER, UUID, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.acquire_ai_concurrency_slot(UUID, INTEGER, UUID, INTEGER) TO service_role;

REVOKE ALL ON FUNCTION public.release_ai_concurrency_slot(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_ai_concurrency_slot(UUID, UUID) TO service_role;

REVOKE ALL ON FUNCTION public.get_ai_active_concurrency(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ai_active_concurrency(UUID) TO service_role;

COMMIT;
