-- =====================================================================
-- Migration 005: Add Stripe Billing & Subscription Fields to Profiles
-- File: supabase/migrations/20260908000001_add_stripe_billing_fields.sql
-- Description: Stores customer & subscription IDs, status, and period end
-- for real-world Stripe checkout and customer portal reconciliation.
-- =====================================================================

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT UNIQUE,
ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT,
ADD COLUMN IF NOT EXISTS subscription_status TEXT DEFAULT 'active',
ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;

-- B-Tree index for high-speed O(1) webhook lookup on customer_id
CREATE INDEX IF NOT EXISTS idx_profiles_stripe_customer_id
ON public.profiles(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_profiles_stripe_subscription_id
ON public.profiles(stripe_subscription_id);
