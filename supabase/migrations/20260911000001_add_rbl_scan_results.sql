-- File: supabase/migrations/20260911000001_add_rbl_scan_results.sql
-- Description: Normalized per-provider RBL scan evidence and reputation_checks enhancements

-- 1. Create normalized rbl_scan_results table for granular DNSBL evidence
CREATE TABLE IF NOT EXISTS public.rbl_scan_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    dnsbl_zone TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('ip', 'domain')),
    queried_targets JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('clean', 'listed', 'unknown', 'error')),
    severity TEXT NOT NULL DEFAULT 'none' CHECK (severity IN ('none', 'low', 'medium', 'high', 'critical')),
    response_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms INTEGER,
    error_message TEXT,
    delisting_url TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast domain & provider historical audit lookups
CREATE INDEX IF NOT EXISTS idx_rbl_scan_results_user_domain_checked
  ON public.rbl_scan_results(user_id, domain_name, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_rbl_scan_results_domain_provider_checked
  ON public.rbl_scan_results(domain_id, provider_id, checked_at DESC);

-- Enable RLS
ALTER TABLE public.rbl_scan_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users access own rbl scan results" ON public.rbl_scan_results;
CREATE POLICY "Users access own rbl scan results"
  ON public.rbl_scan_results FOR ALL
  USING ((SELECT auth.uid()) = user_id)
  WITH CHECK ((SELECT auth.uid()) = user_id);

-- 2. Enhance public.reputation_checks with measured aggregate fields
ALTER TABLE public.reputation_checks
  ADD COLUMN IF NOT EXISTS rbl_listed_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS rbl_unknown_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS rbl_overall_status TEXT
    CHECK (rbl_overall_status IN ('clean', 'listed', 'partial', 'unavailable'));
