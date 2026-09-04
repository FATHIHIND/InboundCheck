-- =====================================================================
-- InboundCheck Enterprise Platform — Unified Schema Setup Script
-- File: supabase/full_schema_setup.sql
-- Consolidated: Migrations 001, 002, 003, and 004
-- Target Database: PostgreSQL 15+ (Supabase)
-- 
-- IDEMPOTENCY GUARANTEE:
-- This script is 100% self-healing and safe to execute repeatedly
-- in the Supabase Dashboard SQL Editor without throwing duplicate
-- relation, duplicate policy, or duplicate trigger errors.
-- =====================================================================

-- =====================================================================
-- SECTION 1: EXTENSIONS & UTILITY FUNCTIONS
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function for automatic user profile provisioning from Supabase Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions, pg_temp
AS $$
DECLARE
  v_full_name TEXT;
  v_avatar_url TEXT;
  v_company_name TEXT;
  v_api_key TEXT;
BEGIN
  -- Extract metadata with graceful fallbacks
  v_full_name := COALESCE(
    NEW.raw_user_meta_data->>'full_name',
    NEW.raw_user_meta_data->>'name',
    split_part(NEW.email, '@', 1)
  );
  v_avatar_url := COALESCE(
    NEW.raw_user_meta_data->>'avatar_url',
    NEW.raw_user_meta_data->>'picture',
    NULL
  );
  v_company_name := COALESCE(
    NEW.raw_user_meta_data->>'company_name',
    NULL
  );

  -- Generate resilient API key
  BEGIN
    v_api_key := 'ic_live_' || encode(extensions.gen_random_bytes(24), 'hex');
  EXCEPTION WHEN OTHERS THEN
    v_api_key := 'ic_live_' || replace(gen_random_uuid()::text, '-', '') || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16);
  END;

  -- Remove any orphan profile with the same email to avoid unique constraint collision
  IF NEW.email IS NOT NULL THEN
    DELETE FROM public.profiles WHERE email = NEW.email AND id <> NEW.id;
  END IF;

  -- Upsert profile record
  INSERT INTO public.profiles (
    id,
    email,
    full_name,
    avatar_url,
    company_name,
    api_key,
    tier
  )
  VALUES (
    NEW.id,
    COALESCE(NEW.email, NEW.id::text || '@inboundcheck.internal'),
    v_full_name,
    v_avatar_url,
    v_company_name,
    v_api_key,
    'starter'
  )
  ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = COALESCE(EXCLUDED.full_name, public.profiles.full_name),
    avatar_url = COALESCE(EXCLUDED.avatar_url, public.profiles.avatar_url),
    company_name = COALESCE(EXCLUDED.company_name, public.profiles.company_name),
    updated_at = NOW();

  RETURN NEW;
EXCEPTION
  WHEN OTHERS THEN
    -- Prevent aborting auth.users insert transaction; log error to Postgres logs
    RAISE WARNING 'handle_new_user trigger encountered an error for user %: % (SQLSTATE %)', NEW.id, SQLERRM, SQLSTATE;
    RETURN NEW;
END;
$$;

ALTER FUNCTION public.handle_new_user() OWNER TO postgres;

-- Provisioning Trigger on auth.users
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- =====================================================================
-- SECTION 2: CORE TABLES (MIGRATION 001)
-- =====================================================================

-- 2.1 User Profiles
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    company_name TEXT,
    api_key TEXT UNIQUE NOT NULL DEFAULT ('ic_live_' || replace(gen_random_uuid()::text, '-', '') || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16)),
    tier TEXT NOT NULL DEFAULT 'starter' CHECK (tier IN ('starter', 'growth', 'enterprise')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.2 Monitored Domains
CREATE TABLE IF NOT EXISTS public.monitored_domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    health_score INTEGER NOT NULL DEFAULT 0 CHECK (health_score >= 0 AND health_score <= 100),
    spf_status TEXT NOT NULL DEFAULT 'missing' CHECK (spf_status IN ('optimal', 'warning', 'critical', 'missing')),
    dkim_status TEXT NOT NULL DEFAULT 'missing' CHECK (dkim_status IN ('optimal', 'warning', 'critical', 'missing')),
    dmarc_status TEXT NOT NULL DEFAULT 'missing' CHECK (dmarc_status IN ('optimal', 'warning', 'critical', 'missing')),
    mx_status TEXT NOT NULL DEFAULT 'missing' CHECK (mx_status IN ('optimal', 'warning', 'critical', 'missing')),
    bimi_status TEXT NOT NULL DEFAULT 'missing' CHECK (bimi_status IN ('optimal', 'warning', 'critical', 'missing')),
    custom_selectors TEXT[] DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_domain UNIQUE (user_id, domain_name)
);

-- 2.3 DNS Audit Logs
CREATE TABLE IF NOT EXISTS public.dns_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES public.monitored_domains(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    health_score INTEGER NOT NULL CHECK (health_score >= 0 AND health_score <= 100),
    spf_record TEXT,
    spf_status TEXT NOT NULL,
    dkim_records JSONB DEFAULT '[]'::jsonb,
    dkim_status TEXT NOT NULL,
    dmarc_record TEXT,
    dmarc_status TEXT NOT NULL,
    mx_records JSONB DEFAULT '[]'::jsonb,
    mx_status TEXT NOT NULL,
    bimi_record TEXT,
    bimi_status TEXT NOT NULL,
    fixes JSONB DEFAULT '[]'::jsonb,
    raw_responses JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.4 Shopify Stores
CREATE TABLE IF NOT EXISTS public.shopify_stores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    shop_domain TEXT NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    scope TEXT NOT NULL,
    sender_email TEXT,
    sender_alignment_status TEXT NOT NULL DEFAULT 'pending' CHECK (sender_alignment_status IN ('aligned', 'misaligned', 'pending')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_shop UNIQUE (user_id, shop_domain)
);

-- 2.5 Alert Configurations
CREATE TABLE IF NOT EXISTS public.alert_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    email_notifications BOOLEAN NOT NULL DEFAULT TRUE,
    notification_email TEXT,
    slack_webhook_url TEXT,
    alert_on_health_drop BOOLEAN NOT NULL DEFAULT TRUE,
    health_threshold INTEGER NOT NULL DEFAULT 75 CHECK (health_threshold >= 1 AND health_threshold <= 99),
    alert_on_blacklist BOOLEAN NOT NULL DEFAULT TRUE,
    alert_on_dmarc_change BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_alert_config UNIQUE (user_id)
);


-- =====================================================================
-- SECTION 3: V3 ENTERPRISE TABLES (MIGRATIONS 002 & 003)
-- =====================================================================

-- 3.1 AI Content Template Audits Table (Bloc A)
CREATE TABLE IF NOT EXISTS public.ai_template_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    spam_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    promotional_density NUMERIC(5, 2) DEFAULT 0,
    flagged_triggers JSONB DEFAULT '[]'::jsonb,
    recommendations JSONB DEFAULT '[]'::jsonb,
    polymorphic_variants JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.2 Omnichannel Failover Configuration & Dispatch Logs (Bloc B)
CREATE TABLE IF NOT EXISTS public.failover_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    primary_channel TEXT NOT NULL DEFAULT 'telegram' CHECK (primary_channel IN ('telegram', 'whatsapp', 'sms')),
    provider TEXT NOT NULL DEFAULT 'telegram_bot_api' CHECK (provider IN ('telegram_bot_api', 'twilio', 'interakt')),
    phone_routing_format TEXT NOT NULL DEFAULT 'E.164',
    trigger_events JSONB DEFAULT '["email_spam", "delivery_failure", "hard_bounce", "rbl_listed", "dmarc_broken"]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_failover_config UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS public.failover_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('telegram', 'whatsapp', 'sms')),
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'dispatched' CHECK (status IN ('dispatched', 'delivered', 'failed')),
    dispatch_payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure constraints support Telegram in case tables existed previously (Migration 003)
ALTER TABLE public.failover_configs 
    DROP CONSTRAINT IF EXISTS failover_configs_primary_channel_check;
ALTER TABLE public.failover_configs 
    ADD CONSTRAINT failover_configs_primary_channel_check 
    CHECK (primary_channel IN ('telegram', 'whatsapp', 'sms'));

ALTER TABLE public.failover_configs 
    DROP CONSTRAINT IF EXISTS failover_configs_provider_check;
ALTER TABLE public.failover_configs 
    ADD CONSTRAINT failover_configs_provider_check 
    CHECK (provider IN ('telegram_bot_api', 'twilio', 'interakt'));

ALTER TABLE public.failover_logs 
    DROP CONSTRAINT IF EXISTS failover_logs_channel_check;
ALTER TABLE public.failover_logs 
    ADD CONSTRAINT failover_logs_channel_check 
    CHECK (channel IN ('telegram', 'whatsapp', 'sms'));

-- 3.3 1-Click DNS Provider Credentials & Auto-Fix Logs (Bloc C)
CREATE TABLE IF NOT EXISTS public.dns_provider_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    provider_name TEXT NOT NULL CHECK (provider_name IN ('cloudflare', 'godaddy')),
    zone_id TEXT,
    api_token_encrypted TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_dns_provider UNIQUE (user_id, provider_name)
);

CREATE TABLE IF NOT EXISTS public.dns_auto_fix_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    record_type TEXT NOT NULL,
    host TEXT NOT NULL,
    record_value TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'rolled_back', 'failed')),
    snapshot_before JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.4 Predictive Dispute & Revenue Analytics (Bloc D)
CREATE TABLE IF NOT EXISTS public.revenue_dispute_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    monthly_gmv NUMERIC(12, 2) NOT NULL DEFAULT 50000.00,
    weekly_protected_revenue NUMERIC(12, 2) NOT NULL DEFAULT 11850.00,
    spam_risk_rate NUMERIC(5, 2) NOT NULL DEFAULT 1.6,
    protected_order_count INTEGER NOT NULL DEFAULT 482,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_revenue_analytics UNIQUE (user_id)
);


-- =====================================================================
-- SECTION 4: UPDATED_AT TRIGGERS (IDEMPOTENT)
-- =====================================================================

DROP TRIGGER IF EXISTS update_profiles_updated_at ON public.profiles;
CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_monitored_domains_updated_at ON public.monitored_domains;
CREATE TRIGGER update_monitored_domains_updated_at
    BEFORE UPDATE ON public.monitored_domains
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_shopify_stores_updated_at ON public.shopify_stores;
CREATE TRIGGER update_shopify_stores_updated_at
    BEFORE UPDATE ON public.shopify_stores
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_alert_configs_updated_at ON public.alert_configs;
CREATE TRIGGER update_alert_configs_updated_at
    BEFORE UPDATE ON public.alert_configs
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_failover_configs_updated_at ON public.failover_configs;
CREATE TRIGGER update_failover_configs_updated_at
    BEFORE UPDATE ON public.failover_configs
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_dns_provider_credentials_updated_at ON public.dns_provider_credentials;
CREATE TRIGGER update_dns_provider_credentials_updated_at
    BEFORE UPDATE ON public.dns_provider_credentials
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_revenue_dispute_analytics_updated_at ON public.revenue_dispute_analytics;
CREATE TRIGGER update_revenue_dispute_analytics_updated_at
    BEFORE UPDATE ON public.revenue_dispute_analytics
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


-- =====================================================================
-- SECTION 5: ROW LEVEL SECURITY (RLS) POLICIES (IDEMPOTENT)
-- =====================================================================

-- Enable RLS across all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.monitored_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dns_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shopify_stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_template_audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.failover_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.failover_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dns_provider_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dns_auto_fix_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.revenue_dispute_analytics ENABLE ROW LEVEL SECURITY;

-- 5.1 Profiles Policies
DROP POLICY IF EXISTS "Users can view their own profile" ON public.profiles;
CREATE POLICY "Users can view their own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Service role and trigger full access" ON public.profiles;
CREATE POLICY "Service role and trigger full access"
    ON public.profiles
    FOR ALL
    TO service_role, postgres
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Users can insert their own profile" ON public.profiles;
CREATE POLICY "Users can insert their own profile"
    ON public.profiles FOR INSERT
    WITH CHECK (auth.uid() = id OR auth.uid() IS NULL);

-- 5.2 Monitored Domains Policies
DROP POLICY IF EXISTS "Users can view their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can view their own monitored domains"
    ON public.monitored_domains FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can insert their own monitored domains"
    ON public.monitored_domains FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can update their own monitored domains"
    ON public.monitored_domains FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own monitored domains" ON public.monitored_domains;
CREATE POLICY "Users can delete their own monitored domains"
    ON public.monitored_domains FOR DELETE
    USING (auth.uid() = user_id);

-- 5.3 DNS Audit Logs Policies
DROP POLICY IF EXISTS "Users can view their own DNS audit logs" ON public.dns_audit_logs;
CREATE POLICY "Users can view their own DNS audit logs"
    ON public.dns_audit_logs FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own DNS audit logs" ON public.dns_audit_logs;
CREATE POLICY "Users can insert their own DNS audit logs"
    ON public.dns_audit_logs FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own DNS audit logs" ON public.dns_audit_logs;
CREATE POLICY "Users can delete their own DNS audit logs"
    ON public.dns_audit_logs FOR DELETE
    USING (auth.uid() = user_id);

-- 5.4 Shopify Stores Policies
DROP POLICY IF EXISTS "Users can view their own shopify stores" ON public.shopify_stores;
CREATE POLICY "Users can view their own shopify stores"
    ON public.shopify_stores FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own shopify stores" ON public.shopify_stores;
CREATE POLICY "Users can insert their own shopify stores"
    ON public.shopify_stores FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own shopify stores" ON public.shopify_stores;
CREATE POLICY "Users can update their own shopify stores"
    ON public.shopify_stores FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own shopify stores" ON public.shopify_stores;
CREATE POLICY "Users can delete their own shopify stores"
    ON public.shopify_stores FOR DELETE
    USING (auth.uid() = user_id);

-- 5.5 Alert Configs Policies
DROP POLICY IF EXISTS "Users can view their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can view their own alert configs"
    ON public.alert_configs FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can insert their own alert configs"
    ON public.alert_configs FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can update their own alert configs"
    ON public.alert_configs FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own alert configs" ON public.alert_configs;
CREATE POLICY "Users can delete their own alert configs"
    ON public.alert_configs FOR DELETE
    USING (auth.uid() = user_id);

-- 5.6 V3 Roadmap Tables Policies (Bloc A, B, C, D)
DROP POLICY IF EXISTS "Users access own ai_template_audits" ON public.ai_template_audits;
CREATE POLICY "Users access own ai_template_audits"
    ON public.ai_template_audits FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own failover_configs" ON public.failover_configs;
CREATE POLICY "Users access own failover_configs"
    ON public.failover_configs FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own failover_logs" ON public.failover_logs;
CREATE POLICY "Users access own failover_logs"
    ON public.failover_logs FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own dns_provider_credentials" ON public.dns_provider_credentials;
CREATE POLICY "Users access own dns_provider_credentials"
    ON public.dns_provider_credentials FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own dns_auto_fix_logs" ON public.dns_auto_fix_logs;
CREATE POLICY "Users access own dns_auto_fix_logs"
    ON public.dns_auto_fix_logs FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own revenue_dispute_analytics" ON public.revenue_dispute_analytics;
CREATE POLICY "Users access own revenue_dispute_analytics"
    ON public.revenue_dispute_analytics FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);


-- =====================================================================
-- SECTION 6: HIGH-PERFORMANCE B-TREE INDEXES (MIGRATIONS 001 & 004)
-- =====================================================================

-- Core domain lookup indexes
CREATE INDEX IF NOT EXISTS idx_monitored_domains_user_id ON public.monitored_domains USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_monitored_domains_name ON public.monitored_domains USING btree (domain_name);

-- Failover telemetry logs
CREATE INDEX IF NOT EXISTS idx_failover_logs_user_id ON public.failover_logs USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_failover_logs_created_at ON public.failover_logs USING btree (created_at DESC);

-- DNS Auto-Fix audit trails
CREATE INDEX IF NOT EXISTS idx_dns_auto_fix_logs_user_id ON public.dns_auto_fix_logs USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_dns_auto_fix_logs_created_at ON public.dns_auto_fix_logs USING btree (created_at DESC);

-- AI Content audit logs
CREATE INDEX IF NOT EXISTS idx_ai_template_audits_user_id ON public.ai_template_audits USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_ai_template_audits_created_at ON public.ai_template_audits USING btree (created_at DESC);
