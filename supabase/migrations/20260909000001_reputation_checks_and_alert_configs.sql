-- =====================================================================
-- Migration 006: Reputation Checks Table & Alert Configs Expansion
-- File: supabase/migrations/20260909000001_reputation_checks_and_alert_configs.sql
-- Description: Creates reputation_checks table for historical trend telemetry
-- and adds Telegram bot & granular trigger columns to alert_configs.
-- =====================================================================

-- 1. Expand alert_configs with Telegram & granular alert triggers
ALTER TABLE public.alert_configs
ADD COLUMN IF NOT EXISTS telegram_bot_token TEXT,
ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT,
ADD COLUMN IF NOT EXISTS alert_on_score_drop BOOLEAN DEFAULT true,
ADD COLUMN IF NOT EXISTS score_threshold INTEGER DEFAULT 75,
ADD COLUMN IF NOT EXISTS alert_on_spf_error BOOLEAN DEFAULT true,
ADD COLUMN IF NOT EXISTS alert_on_dkim_fail BOOLEAN DEFAULT true;

-- 2. Create reputation_checks table for historical deliverability telemetry
CREATE TABLE IF NOT EXISTS public.reputation_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
    dns_score INTEGER NOT NULL DEFAULT 0,
    rbl_clean_count INTEGER NOT NULL DEFAULT 10,
    rbl_total_count INTEGER NOT NULL DEFAULT 10,
    predicted_risk_48h TEXT DEFAULT 'low' CHECK (predicted_risk_48h IN ('low', 'medium', 'high')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- B-Tree indexes for fast historical trend querying
CREATE INDEX IF NOT EXISTS idx_reputation_checks_user_domain_created
ON public.reputation_checks(user_id, domain_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reputation_checks_created_at
ON public.reputation_checks(created_at DESC);

-- Enable Row Level Security
ALTER TABLE public.reputation_checks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can view their own reputation checks"
    ON public.reputation_checks FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can insert their own reputation checks"
    ON public.reputation_checks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own reputation checks" ON public.reputation_checks;
CREATE POLICY "Users can delete their own reputation checks"
    ON public.reputation_checks FOR DELETE
    USING (auth.uid() = user_id);
