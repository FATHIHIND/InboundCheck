-- =====================================================================
-- Migration 008: Modernize RBL Matrix, Secure Alert Configs RLS & Purge Job
-- File: supabase/migrations/20260910000001_modernize_rbl_and_secure_rls.sql
-- Description:
-- 1. Establishes the modernized 10-RBL reputation set (retiring decommissioned SORBS
--    in favor of Invaluement ivmURI) and updates telemetry metadata.
-- 2. Refactors alert_configs Row Level Security (RLS) policies to strictly use
--    cached scalar subqueries ((SELECT auth.uid()) = user_id) for O(1) query planner evaluation.
-- 3. Implements cleanup_stale_webhook_events() SECURITY DEFINER stored procedure
--    to automatically prune processed_webhook_events older than 48 hours.
-- =====================================================================

-- 1. Modernize RBL metadata on reputation_checks
COMMENT ON TABLE public.reputation_checks IS 
'Authoritative deliverability & RBL telemetry (Spamhaus ZEN, Barracuda BRBL, SpamCop SCBL, Invaluement ivmURI, UCEPROTECT L1, Spamhaus DBL, CBL, Abuse.ro, SURBL, Mailspike. Decommissioned SORBS dnsbl.sorbs.net retired)';

-- 2. Optimize alert_configs Row Level Security (RLS) using scalar subqueries
ALTER TABLE public.alert_configs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can view their own alert configs"
    ON public.alert_configs FOR SELECT
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can insert their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can insert their own alert configs"
    ON public.alert_configs FOR INSERT
    WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can update their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can update their own alert configs"
    ON public.alert_configs FOR UPDATE
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can delete their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can delete their own alert configs"
    ON public.alert_configs FOR DELETE
    USING ((SELECT auth.uid()) = user_id);

-- 3. Stored Procedure: Automated Webhook Idempotency Store Cleanup (48h TTL)
CREATE OR REPLACE FUNCTION public.cleanup_stale_webhook_events()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM public.processed_webhook_events
    WHERE processed_at < (NOW() - INTERVAL '48 hours');

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON FUNCTION public.cleanup_stale_webhook_events() IS 
'Purges processed Stripe and Shopify webhook records older than 48 hours to bound table size and ensure high-throughput idempotency index performance.';
