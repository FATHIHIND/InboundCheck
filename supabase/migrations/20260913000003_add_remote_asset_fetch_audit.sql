-- Migration 011: Add Remote Asset Fetch Audits Table & RLS Policy
-- Milestone C: Deep Hardening for Remote Asset Fetching

CREATE TABLE IF NOT EXISTS public.remote_asset_fetch_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    pinned_ip INET,
    fetch_status TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    content_length_bytes INTEGER,
    content_sha256 TEXT,
    redirect_count INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable Row Level Security (RLS)
ALTER TABLE public.remote_asset_fetch_audits ENABLE ROW LEVEL SECURITY;

-- User tenant isolation policy with scalar subquery caching
DROP POLICY IF EXISTS "remote_asset_fetch_audits_user_isolation" ON public.remote_asset_fetch_audits;
CREATE POLICY "remote_asset_fetch_audits_user_isolation"
    ON public.remote_asset_fetch_audits
    FOR ALL
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- Service role bypass policy
DROP POLICY IF EXISTS "remote_asset_fetch_audits_service_role" ON public.remote_asset_fetch_audits;
CREATE POLICY "remote_asset_fetch_audits_service_role"
    ON public.remote_asset_fetch_audits
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- Composite B-tree index for fast user domain timeline queries
CREATE INDEX IF NOT EXISTS idx_remote_asset_fetch_audits_user_domain_created
    ON public.remote_asset_fetch_audits (user_id, domain_id, created_at DESC);
