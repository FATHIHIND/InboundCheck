-- Migration 010: Add SPF Merge Plans Table & Policy
-- Milestone B: SPF Conflict Resolution & Merge Engine

CREATE TABLE IF NOT EXISTS public.spf_merge_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    source_records JSONB NOT NULL,
    proposed_record TEXT,
    plan_hash TEXT NOT NULL,
    safe_to_apply BOOLEAN NOT NULL DEFAULT FALSE,
    requires_manual_review BOOLEAN NOT NULL DEFAULT TRUE,
    lookup_budget JSONB NOT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable Row Level Security (RLS)
ALTER TABLE public.spf_merge_plans ENABLE ROW LEVEL SECURITY;

-- Scalar subquery RLS policy for user isolation
DROP POLICY IF EXISTS "spf_merge_plans_user_isolation" ON public.spf_merge_plans;
CREATE POLICY "spf_merge_plans_user_isolation"
    ON public.spf_merge_plans
    FOR ALL
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- Service role bypass policy
DROP POLICY IF EXISTS "spf_merge_plans_service_role" ON public.spf_merge_plans;
CREATE POLICY "spf_merge_plans_service_role"
    ON public.spf_merge_plans
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- Composite B-tree index for fast user domain queries
CREATE INDEX IF NOT EXISTS idx_spf_merge_plans_user_domain_created
    ON public.spf_merge_plans (user_id, domain_name, created_at DESC);
