-- =====================================================================
-- Migration 018: Shield Profile Billing & Entitlement Columns (P0 Remediation)
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-09-25
-- Purpose: Permanently prevent client-side privilege escalation on public.profiles
-- Reference: docs/remediation/PHASE_3_P0_PROFILE_BILLING_REMEDIATION_PLAN.md
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. LAYER 1: BEFORE UPDATE Trigger Guard
-- Intercepts any attempted modification of protected entitlement or billing
-- columns and strictly enforces that the caller has service_role or postgres authorization.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    -- Check if any protected billing or entitlement column is being altered
    IF (
        NEW.subscription_tier IS DISTINCT FROM OLD.subscription_tier OR
        NEW.tier IS DISTINCT FROM OLD.tier OR
        NEW.subscription_status IS DISTINCT FROM OLD.subscription_status OR
        NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id OR
        NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id OR
        NEW.shopify_charge_id IS DISTINCT FROM OLD.shopify_charge_id OR
        NEW.trial_ends_at IS DISTINCT FROM OLD.trial_ends_at OR
        NEW.current_period_end IS DISTINCT FROM OLD.current_period_end
    ) THEN
        -- Allow modification ONLY if executed by service_role, postgres, or supabase_admin
        IF (
            COALESCE(auth.role(), '') != 'service_role' AND
            COALESCE(current_setting('request.jwt.claim.role', true), '') != 'service_role' AND
            current_user NOT IN ('postgres', 'supabase_admin')
        ) THEN
            RAISE EXCEPTION 'Privilege escalation rejected: modifying entitlement or billing columns requires service_role authorization.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

ALTER FUNCTION public.protect_profile_billing_columns() OWNER TO postgres;

DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;
CREATE TRIGGER trg_protect_profile_billing_columns
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.protect_profile_billing_columns();

-- ---------------------------------------------------------------------
-- 2. LAYER 2: Column-Level Privilege Restrictions
-- Strips table-wide UPDATE from the authenticated role so that queries
-- attempting to write to ungranted columns fail at the SQL planner level.
-- ---------------------------------------------------------------------

-- Revoke table-wide update privilege from regular authenticated users
REVOKE UPDATE ON TABLE public.profiles FROM authenticated;

-- Grant update privilege strictly for safe user-editable profile columns
GRANT UPDATE (full_name, avatar_url, company_name) ON TABLE public.profiles TO authenticated;

-- Ensure service_role and postgres maintain full table-wide permissions
GRANT ALL ON TABLE public.profiles TO postgres, service_role;

-- ---------------------------------------------------------------------
-- 3. LAYER 3: RLS Policy Hardening with Explicit WITH CHECK
-- Guarantees that tenants cannot reassign the profile row id.
-- ---------------------------------------------------------------------

DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING ((SELECT auth.uid()) = id)
    WITH CHECK ((SELECT auth.uid()) = id);

COMMIT;
