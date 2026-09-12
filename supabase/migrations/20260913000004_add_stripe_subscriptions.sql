-- =====================================================================
-- Migration: Add Stripe Subscriptions, 3-Day Free Trial, and Tier Enforcement
-- File: supabase/migrations/20260913000004_add_stripe_subscriptions.sql
-- Description: Establishes 3-day free trial lifecycle, Stripe customer/subscription
-- IDs, subscription tiers ('starter', 'growth', 'enterprise'), statuses,
-- and high-speed composite index on (id, subscription_status).
-- =====================================================================

-- Add subscription and trial tracking columns to public.profiles
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT UNIQUE,
ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT,
ADD COLUMN IF NOT EXISTS subscription_tier TEXT NOT NULL DEFAULT 'starter',
ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'trialing',
ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '3 days'),
ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;

-- Synchronize defaults
ALTER TABLE public.profiles ALTER COLUMN subscription_tier SET DEFAULT 'starter';
ALTER TABLE public.profiles ALTER COLUMN subscription_status SET DEFAULT 'trialing';
ALTER TABLE public.profiles ALTER COLUMN trial_ends_at SET DEFAULT (NOW() + INTERVAL '3 days');

-- Synchronize legacy 'tier' column with 'subscription_tier' if legacy column exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'tier'
    ) THEN
        UPDATE public.profiles 
        SET subscription_tier = CASE 
            WHEN tier IN ('starter', 'growth', 'enterprise') THEN tier 
            ELSE 'starter' 
        END
        WHERE subscription_tier IS NULL;
    END IF;
END $$;

-- Enforce strict CHECK constraints on tier and status
DO $$
BEGIN
    ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_subscription_tier_check;
    ALTER TABLE public.profiles ADD CONSTRAINT profiles_subscription_tier_check 
        CHECK (subscription_tier IN ('starter', 'growth', 'enterprise'));

    ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_subscription_status_check;
    ALTER TABLE public.profiles ADD CONSTRAINT profiles_subscription_status_check 
        CHECK (subscription_status IN ('trialing', 'active', 'past_due', 'canceled', 'expired'));
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Constraint update notice: %', SQLERRM;
END $$;

-- High-speed composite index on (id, subscription_status)
CREATE INDEX IF NOT EXISTS idx_profiles_id_subscription_status
ON public.profiles(id, subscription_status);

-- High-speed lookup index for Stripe webhook customer resolution
CREATE INDEX IF NOT EXISTS idx_profiles_stripe_customer_id
ON public.profiles(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_profiles_stripe_subscription_id
ON public.profiles(stripe_subscription_id);
