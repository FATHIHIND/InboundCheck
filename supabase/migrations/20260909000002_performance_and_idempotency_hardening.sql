-- =====================================================================
-- Migration 007: Performance Optimization, Trigram Search & Webhook Lock
-- File: supabase/migrations/20260909000002_performance_and_idempotency_hardening.sql
-- Description: Enables pg_trgm, adds GIN trigram index on domain_name,
-- creates distributed webhook idempotency table, and converts all RLS
-- policies to scalar subqueries ((SELECT auth.uid()) = ...) for query caching.
-- =====================================================================

-- 1. Enable pg_trgm extension for sub-millisecond fuzzy domain lookups
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Add GIN Trigram Index on domain_name
CREATE INDEX IF NOT EXISTS idx_monitored_domains_domain_trgm 
ON public.monitored_domains USING gin (domain_name gin_trgm_ops);

-- 3. Persistent Distributed Webhook Idempotency Table
CREATE TABLE IF NOT EXISTS public.processed_webhook_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index with 24h TTL cleanup capability
CREATE INDEX IF NOT EXISTS idx_processed_webhook_events_processed_at 
ON public.processed_webhook_events (processed_at DESC);

-- Enable RLS on processed_webhook_events (service role only)
ALTER TABLE public.processed_webhook_events ENABLE ROW LEVEL SECURITY;

-- 4. Re-optimize all RLS policies using scalar subquery (SELECT auth.uid())

-- public.profiles
DROP POLICY IF EXISTS "Users can view their own profile" ON public.profiles;
CREATE POLICY "Users can view their own profile"
    ON public.profiles FOR SELECT
    USING ((SELECT auth.uid()) = id);

DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING ((SELECT auth.uid()) = id);

-- public.monitored_domains
DROP POLICY IF EXISTS "Users can view their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can view their own monitored domains"
    ON public.monitored_domains FOR SELECT
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can insert their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can insert their own monitored domains"
    ON public.monitored_domains FOR INSERT
    WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can update their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can update their own monitored domains"
    ON public.monitored_domains FOR UPDATE
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can delete their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can delete their own monitored domains"
    ON public.monitored_domains FOR DELETE
    USING ((SELECT auth.uid()) = user_id);

-- public.reputation_checks
DROP POLICY IF EXISTS "Users can view their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can view their own reputation checks"
    ON public.reputation_checks FOR SELECT
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can insert their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can insert their own reputation checks"
    ON public.reputation_checks FOR INSERT
    WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can delete their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can delete their own reputation checks"
    ON public.reputation_checks FOR DELETE
    USING ((SELECT auth.uid()) = user_id);
