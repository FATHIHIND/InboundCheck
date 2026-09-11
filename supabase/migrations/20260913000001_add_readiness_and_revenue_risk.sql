-- =====================================================================
-- Migration 009: Deliverability Readiness & Revenue-at-Risk Engine
-- File: supabase/migrations/20260913000001_add_readiness_and_revenue_risk.sql
-- Description:
-- 1. Adds deliverability readiness & revenue risk fields to public.monitored_domains.
-- 2. Creates public.revenue_risk_snapshots table for audit logging & trend forecasting.
-- 3. Enables strict Row Level Security (RLS) with cached scalar subqueries.
-- =====================================================================

-- 1. Add fields to public.monitored_domains
ALTER TABLE public.monitored_domains
ADD COLUMN IF NOT EXISTS revenue_at_risk_cents BIGINT DEFAULT 0,
ADD COLUMN IF NOT EXISTS revenue_risk_calculated_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS deliverability_readiness_score INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS deliverability_readiness_updated_at TIMESTAMPTZ;

-- 2. Create public.revenue_risk_snapshots table
CREATE TABLE IF NOT EXISTS public.revenue_risk_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    order_count INTEGER NOT NULL DEFAULT 0,
    average_order_value_cents BIGINT NOT NULL DEFAULT 0,
    monthly_gmv_cents BIGINT NOT NULL DEFAULT 0,
    impairment_probability NUMERIC(5, 4) NOT NULL DEFAULT 0.0000,
    customer_impact_factor NUMERIC(5, 4) NOT NULL DEFAULT 1.0000,
    expected_risk_cents BIGINT NOT NULL DEFAULT 0,
    confidence_band TEXT NOT NULL DEFAULT 'medium' CHECK (confidence_band IN ('high', 'medium', 'low')),
    breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. High-throughput compound index
CREATE INDEX IF NOT EXISTS idx_revenue_risk_snapshots_user_domain_created 
ON public.revenue_risk_snapshots (user_id, domain_id, created_at DESC);

-- 4. Enable Row Level Security (RLS)
ALTER TABLE public.revenue_risk_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own revenue risk snapshots" ON public.revenue_risk_snapshots;
CREATE POLICY "Users can view their own revenue risk snapshots"
    ON public.revenue_risk_snapshots FOR SELECT
    USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can insert their own revenue risk snapshots" ON public.revenue_risk_snapshots;
CREATE POLICY "Users can insert their own revenue risk snapshots"
    ON public.revenue_risk_snapshots FOR INSERT
    WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users can delete their own revenue risk snapshots" ON public.revenue_risk_snapshots;
CREATE POLICY "Users can delete their own revenue risk snapshots"
    ON public.revenue_risk_snapshots FOR DELETE
    USING ((SELECT auth.uid()) = user_id);
