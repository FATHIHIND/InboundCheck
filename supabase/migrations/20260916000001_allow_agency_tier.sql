-- =====================================================================
-- Migration: Add 'agency' to profiles subscription_tier and tier CHECK constraints
-- File: supabase/migrations/20260916000001_allow_agency_tier.sql
-- Description: Updates profiles_subscription_tier_check and profiles_tier_check
-- to support ('starter', 'growth', 'agency', 'enterprise').
-- =====================================================================

DO $$
BEGIN
    -- Update subscription_tier CHECK constraint
    ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_subscription_tier_check;
    ALTER TABLE public.profiles ADD CONSTRAINT profiles_subscription_tier_check 
        CHECK (subscription_tier IN ('starter', 'growth', 'agency', 'enterprise'));

    -- Update legacy tier CHECK constraint if present
    ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_tier_check;
    ALTER TABLE public.profiles ADD CONSTRAINT profiles_tier_check 
        CHECK (tier IN ('starter', 'growth', 'agency', 'enterprise'));
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Agency constraint migration notice: %', SQLERRM;
END $$;
