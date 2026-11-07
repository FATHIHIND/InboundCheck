-- =====================================================================
-- Migration 20261107000002: Shopify billing columns on public.profiles (BILL-3)
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Date: 2026-11-07
--
-- Purpose:
--   The Shopify billing callback and app_subscriptions/update webhook persist
--   billing_provider and shopify_charge_id, but production public.profiles has
--   neither column, so every Shopify activation raised (HTTP 500) after the
--   merchant was charged. This migration adds both columns, constrains
--   billing_provider, binds each Shopify charge to exactly one profile via a
--   UNIQUE partial index, and extends the client-write shield to the new
--   billing columns. subscription_status is intentionally NOT widened: the
--   application maps Shopify statuses onto the existing CHECK set
--   (see map_shopify_subscription_status in shopify_billing_service.py).
--
--   Client protection: the real control is a dedicated SECURITY INVOKER trigger
--   that rejects any non-trusted role that sets or changes billing_provider /
--   shopify_charge_id, independent of grants. The column-level REVOKE below is
--   defense-in-depth only: a column REVOKE does not remove a table-level UPDATE
--   grant, so clients holding table-level UPDATE on profiles can still reach the
--   columns at the privilege layer and are stopped by the trigger.
--   Idempotent: safe to re-run.
--
-- Verification SQL (run as postgres after apply):
--   SELECT column_name, data_type FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='profiles'
--      AND column_name IN ('billing_provider','shopify_charge_id');          -- expect 2 rows, text
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid='public.profiles'::regclass
--      AND conname='profiles_billing_provider_check';                        -- expect 1 row
--   SELECT indexdef FROM pg_indexes WHERE schemaname='public'
--      AND indexname='profiles_shopify_charge_id_unique';                    -- UNIQUE ... WHERE (shopify_charge_id IS NOT NULL)
--   SELECT grantee, privilege_type, column_name FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='profiles'
--      AND column_name IN ('billing_provider','shopify_charge_id')
--      AND grantee IN ('anon','authenticated','PUBLIC')
--      AND privilege_type IN ('INSERT','UPDATE');
--     -- Rows here are INHERITED from table-level grants on profiles (a column
--     -- REVOKE cannot remove them). In production on 2026-11-07 this returned 6
--     -- rows (anon INSERT+UPDATE, authenticated INSERT). Writes are still blocked
--     -- by RLS (auth.uid() = id) and by the guard trigger below; removing the
--     -- table-level client grants is the separate P1 grant-hardening migration.
--   SELECT tgname FROM pg_trigger WHERE tgrelid='public.profiles'::regclass
--      AND tgname='trg_protect_profile_shopify_billing_columns';             -- expect 1 row
--
-- Rollback SQL (only after reverting the API code that writes these columns):
--   BEGIN;
--   DROP TRIGGER IF EXISTS trg_protect_profile_shopify_billing_columns ON public.profiles;
--   DROP FUNCTION IF EXISTS public.protect_profile_shopify_billing_columns();
--   DROP INDEX IF EXISTS public.profiles_shopify_charge_id_unique;
--   ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_billing_provider_check;
--   ALTER TABLE public.profiles DROP COLUMN IF EXISTS shopify_charge_id;
--   ALTER TABLE public.profiles DROP COLUMN IF EXISTS billing_provider;
--   COMMIT;
-- =====================================================================

BEGIN;

-- 1. Columns
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS billing_provider text;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS shopify_charge_id text;

-- 2. billing_provider domain (added idempotently)
DO $chk$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.profiles'::regclass
       AND conname = 'profiles_billing_provider_check'
  ) THEN
    ALTER TABLE public.profiles
      ADD CONSTRAINT profiles_billing_provider_check
      CHECK (billing_provider IS NULL OR billing_provider IN ('stripe','shopify'));
  END IF;
END;
$chk$;

-- 3. One Shopify charge binds to exactly one user
CREATE UNIQUE INDEX IF NOT EXISTS profiles_shopify_charge_id_unique
  ON public.profiles (shopify_charge_id)
  WHERE shopify_charge_id IS NOT NULL;

-- 4. Defense-in-depth only. A column-level REVOKE does not remove a table-level
--    UPDATE grant on public.profiles, so this alone does NOT stop client writes;
--    the trigger in step 5 is the enforcing control.
REVOKE INSERT (billing_provider, shopify_charge_id), UPDATE (billing_provider, shopify_charge_id)
  ON public.profiles FROM PUBLIC, anon, authenticated;

-- 5. Trigger guard for the new billing columns. Separate from
--    protect_profile_billing_columns() so that function's column list does not
--    reference columns that do not exist when earlier migrations run.
--    SECURITY INVOKER: current_user is the real SQL caller (service_role via
--    PostgREST, postgres for definer RPCs / handle_new_user provisioning).
CREATE OR REPLACE FUNCTION public.protect_profile_shopify_billing_columns()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $guard$
BEGIN
  IF current_user IN ('postgres', 'supabase_admin', 'service_role') THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.billing_provider IS NOT NULL OR NEW.shopify_charge_id IS NOT NULL THEN
      RAISE EXCEPTION 'BILLING_WRITE_REQUIRES_TRUSTED_SQL_ROLE' USING ERRCODE = '42501';
    END IF;
  ELSIF (
    NEW.billing_provider IS DISTINCT FROM OLD.billing_provider OR
    NEW.shopify_charge_id IS DISTINCT FROM OLD.shopify_charge_id
  ) THEN
    RAISE EXCEPTION 'BILLING_WRITE_REQUIRES_TRUSTED_SQL_ROLE' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$guard$;
ALTER FUNCTION public.protect_profile_shopify_billing_columns() OWNER TO postgres;
REVOKE ALL ON FUNCTION public.protect_profile_shopify_billing_columns() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.protect_profile_shopify_billing_columns() TO postgres, service_role;

DROP TRIGGER IF EXISTS trg_protect_profile_shopify_billing_columns ON public.profiles;
CREATE TRIGGER trg_protect_profile_shopify_billing_columns
  BEFORE INSERT OR UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.protect_profile_shopify_billing_columns();

COMMIT;
