-- =====================================================================
-- Migration 019: Fix Profile Billing Trigger Schema (Corrective Remediation)
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-09-25
-- Purpose: Remove non-existent unmapped columns from protect_profile_billing_columns()
--          to eliminate SQLSTATE 42703 runtime errors on public.profiles updates.
-- Reference: docs/remediation/PHASE_3_P0_PROFILE_BILLING_REMEDIATION_PLAN.md
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Recreate/Replace public.protect_profile_billing_columns()
-- Guards strictly the 7 billing & entitlement columns that physically exist
-- on public.profiles without referencing unmapped external fields.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    -- Check if any protected billing or entitlement column physically present on public.profiles is being altered
    IF (
        NEW.subscription_tier IS DISTINCT FROM OLD.subscription_tier OR
        NEW.tier IS DISTINCT FROM OLD.tier OR
        NEW.subscription_status IS DISTINCT FROM OLD.subscription_status OR
        NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id OR
        NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id OR
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

-- ---------------------------------------------------------------------
-- 2. Preserve Trigger Attachment
-- Ensure trg_protect_profile_billing_columns is active on public.profiles
-- ---------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;
CREATE TRIGGER trg_protect_profile_billing_columns
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.protect_profile_billing_columns();

COMMIT;
