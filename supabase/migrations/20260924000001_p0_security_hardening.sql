-- =====================================================================
-- Migration 017: P0 Security Hardening
-- Target: InboundCheck Production PostgreSQL 15
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-09-24
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Remediate Permissive Profiles Insert Policy (SEC-03)
-- ---------------------------------------------------------------------
-- Problem: Policy contained `WITH CHECK (auth.uid() = id OR auth.uid() IS NULL);`
-- which permitted anonymous unauthenticated clients to insert arbitrary profile records.
-- Fix: Remove `auth.uid() IS NULL` so that only the authenticated user owning the record
-- (or privileged service_role/trigger functions) can insert profiles.
DROP POLICY IF EXISTS "Users can insert their own profile" ON public.profiles;

CREATE POLICY "Users can insert their own profile"
    ON public.profiles FOR INSERT
    WITH CHECK (auth.uid() = id);

-- ---------------------------------------------------------------------
-- 2. Ensure Non-Null Trial Expiration Defaults (SEC-05)
-- ---------------------------------------------------------------------
ALTER TABLE public.profiles 
    ALTER COLUMN trial_ends_at SET DEFAULT (NOW() + INTERVAL '3 days');

UPDATE public.profiles
SET trial_ends_at = created_at + INTERVAL '3 days'
WHERE trial_ends_at IS NULL AND subscription_status = 'trialing';

COMMIT;
