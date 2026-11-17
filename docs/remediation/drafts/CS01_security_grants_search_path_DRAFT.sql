-- =====================================================================
-- DRAFT — NOT A MIGRATION. DO NOT APPLY.
--
-- This file lives in docs/remediation/drafts/, outside supabase/migrations/,
-- so that migration tooling cannot execute it. It must not be moved there
-- without owner approval, a staging rehearsal, and a production change window.
--
-- Change Set: CS-01 (security grants and explicit search_path)
-- Target project: tbjcldcoozvuvyipeonh (production, read-only evidence only)
-- Evidence: Supabase security advisors read 2026-11-17 (read-only):
--   * anon_security_definer_function_executable (handle_new_user,
--     increment_upload_count, protect_profile_billing_columns)
--   * authenticated_security_definer_function_executable (same three)
--   * function_search_path_mutable (increment_upload_count, set_updated_at,
--     update_updated_at_column)
-- Definitions present in repo: handle_new_user (20260904000001),
--   protect_profile_billing_columns (20260925000002/000003),
--   update_updated_at_column (20260903000001).
-- Definitions NOT in repo: increment_upload_count, set_updated_at.
--   Their bodies must be reviewed before any grant change to them.
--
-- Production state: NOT VERIFIED for function bodies, grants and ACLs
-- (no read-only SQL path is available). Do not treat this draft as
-- equivalent to production until the owner-approved schema dump confirms it.
-- =====================================================================

BEGIN;

-- A. Trigger-only functions must not be callable as RPC by anon or authenticated.
--    Trigger firing does not require the invoking role to hold EXECUTE, but
--    this must be verified in staging before production use (see verification).
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.protect_profile_billing_columns() FROM PUBLIC, anon, authenticated;

-- B. Explicit, non-mutable search_path (guarded and idempotent: each ALTER runs
--    only if the function exists with no arguments, matching the advisor metadata).
DO $$
DECLARE
  fn TEXT;
BEGIN
  FOREACH fn IN ARRAY ARRAY['update_updated_at_column', 'set_updated_at', 'increment_upload_count']
  LOOP
    IF EXISTS (
      SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE n.nspname = 'public'
         AND p.proname = fn
         AND p.pronargs = 0
    ) THEN
      EXECUTE format('ALTER FUNCTION public.%I() SET search_path = public, pg_temp', fn);
    END IF;
  END LOOP;
END
$$;

-- C. DECISION REQUIRED (not applied here):
--    increment_upload_count is SECURITY DEFINER and executable by anon and
--    authenticated. Whether to REVOKE EXECUTE, or convert it to SECURITY INVOKER,
--    depends on its body and on whether any client calls /rest/v1/rpc/increment_upload_count.
--    The owner must confirm this before a grant change is added.

COMMIT;

-- =====================================================================
-- VERIFICATION (read-only; to be run only after owner approval, in staging first)
-- =====================================================================
-- SELECT p.proname,
--        has_function_privilege('anon',          p.oid, 'EXECUTE') AS anon_exec,
--        has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_exec,
--        p.proconfig
--   FROM pg_proc p
--   JOIN pg_namespace n ON n.oid = p.pronamespace
--  WHERE n.nspname = 'public'
--    AND p.proname IN ('handle_new_user', 'protect_profile_billing_columns',
--                      'update_updated_at_column', 'set_updated_at', 'increment_upload_count');
--
-- Expected after apply (for the two REVOKEd functions):
--   anon_exec = false, authenticated_exec = false
-- Expected for each ALTERed function that exists:
--   proconfig contains 'search_path=public, pg_temp'
--
-- Trigger check (must still return 1 row each):
--   SELECT tgname FROM pg_trigger WHERE tgname IN
--     ('trg_protect_profile_billing_columns', 'trg_protect_profile_shopify_billing_columns');
--
-- Profile billing flow check: run the Stripe and Shopify billing tests against
-- staging after apply; a trigger that cannot execute would break profile writes.

-- =====================================================================
-- ROLLBACK (restores PostgreSQL default function privileges)
-- =====================================================================
-- BEGIN;
--   GRANT EXECUTE ON FUNCTION public.handle_new_user() TO PUBLIC;
--   GRANT EXECUTE ON FUNCTION public.protect_profile_billing_columns() TO PUBLIC;
--   ALTER FUNCTION public.update_updated_at_column() RESET search_path;
--   ALTER FUNCTION public.set_updated_at() RESET search_path;
--   ALTER FUNCTION public.increment_upload_count() RESET search_path;
-- COMMIT;
