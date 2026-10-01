-- =====================================================================
-- Migration: AI Generation Usage & Cost Telemetry Database Foundation
-- File: supabase/migrations/20261001000001_ai_generation_telemetry.sql
-- Step: 17D.1 — Database Telemetry Foundation (Isolated Phase)
-- Description:
-- 1. Creates public.ai_generation_telemetry table for operational observability.
--    NOTE: This is NOT the commercial quota ledger (which is public.ai_generation_usage).
--    Telemetry is best-effort and NEVER disrupts AI generation availability or quota correctness.
-- 2. Strictly enforces schema invariants and data integrity CHECK constraints:
--    - billing_period format YYYY-MM
--    - plan_tier in ('starter', 'growth', 'agency', 'enterprise')
--    - cost_status in ('calculated', 'reported', 'zero_cost', 'unreported')
--    - outcome in ('success', 'success_via_fallback', 'liquid_failed', 'timeout', 'error')
--    - non-negative token counts when non-null
--    - non-negative cost when non-null
--    - non-negative latency (latency_ms >= 0, provider_latency_ms >= 0 when non-null)
--    - logical consistency between cost_status and cost_micro_usd
-- 3. Enables Row Level Security (RLS) with SELECT policy restricted to tenant owner (auth.uid() = user_id).
-- 4. Revokes all direct client DML (INSERT, UPDATE, DELETE) from PUBLIC, anon, and authenticated.
-- 5. Grants SELECT to authenticated, and full read/write management to service_role.
-- 6. Creates focused b-tree indexes on (user_id, billing_period) and (created_at).
-- =====================================================================

BEGIN;

-- 1. Create Telemetry Table
CREATE TABLE IF NOT EXISTS public.ai_generation_telemetry (
    generation_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    plan_tier VARCHAR(20) NOT NULL,
    billing_period VARCHAR(7) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    prompt_tokens INTEGER NULL,
    completion_tokens INTEGER NULL,
    total_tokens INTEGER NULL,
    cost_micro_usd BIGINT NULL,
    cost_status VARCHAR(20) NOT NULL,
    latency_ms INTEGER NOT NULL,
    provider_latency_ms INTEGER NULL,
    outcome VARCHAR(30) NOT NULL,
    fallback_used BOOLEAN NOT NULL DEFAULT false,
    quota_consumed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),

    -- Data Integrity Constraints
    CONSTRAINT check_ai_telemetry_billing_period 
        CHECK (billing_period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    
    CONSTRAINT check_ai_telemetry_plan_tier 
        CHECK (plan_tier IN ('starter', 'growth', 'agency', 'enterprise')),

    CONSTRAINT check_ai_telemetry_cost_status 
        CHECK (cost_status IN ('calculated', 'reported', 'zero_cost', 'unreported')),

    CONSTRAINT check_ai_telemetry_outcome 
        CHECK (outcome IN ('success', 'success_via_fallback', 'liquid_failed', 'timeout', 'error')),

    CONSTRAINT check_ai_telemetry_prompt_tokens 
        CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),

    CONSTRAINT check_ai_telemetry_completion_tokens 
        CHECK (completion_tokens IS NULL OR completion_tokens >= 0),

    CONSTRAINT check_ai_telemetry_total_tokens 
        CHECK (total_tokens IS NULL OR total_tokens >= 0),

    CONSTRAINT check_ai_telemetry_cost_micro_usd 
        CHECK (cost_micro_usd IS NULL OR cost_micro_usd >= 0),

    CONSTRAINT check_ai_telemetry_latency_ms 
        CHECK (latency_ms >= 0),

    CONSTRAINT check_ai_telemetry_provider_latency_ms 
        CHECK (provider_latency_ms IS NULL OR provider_latency_ms >= 0),

    -- Cost Status and Cost Micro USD Logical Consistency:
    -- 'unreported': cost_micro_usd must be NULL
    -- 'zero_cost': cost_micro_usd must be 0
    -- 'calculated' or 'reported': cost_micro_usd must be NOT NULL
    CONSTRAINT check_ai_telemetry_cost_consistency CHECK (
        (cost_status = 'unreported' AND cost_micro_usd IS NULL) OR
        (cost_status = 'zero_cost' AND cost_micro_usd = 0) OR
        (cost_status IN ('calculated', 'reported') AND cost_micro_usd IS NOT NULL)
    )
);

-- 2. Performance & Aggregation Indexes
-- Required: lookup by tenant and billing period for tenant telemetry/reconciliation
CREATE INDEX IF NOT EXISTS idx_ai_telemetry_user_billing 
    ON public.ai_generation_telemetry (user_id, billing_period);

-- Required: time-range pruning and operational telemetry window queries
CREATE INDEX IF NOT EXISTS idx_ai_telemetry_created_at 
    ON public.ai_generation_telemetry (created_at);

-- 3. Row Level Security (RLS)
ALTER TABLE public.ai_generation_telemetry ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own AI generation telemetry" ON public.ai_generation_telemetry;
CREATE POLICY "Users can view their own AI generation telemetry"
    ON public.ai_generation_telemetry
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- 4. Restrict Direct DML Permissions
-- Revoke all table-level access from untrusted client roles
REVOKE ALL ON TABLE public.ai_generation_telemetry FROM PUBLIC, anon, authenticated;

-- Allow authenticated users SELECT only (governed by RLS policy above)
GRANT SELECT ON TABLE public.ai_generation_telemetry TO authenticated;

-- Allow privileged backend service_role full operational access
GRANT ALL ON TABLE public.ai_generation_telemetry TO service_role;

COMMIT;
