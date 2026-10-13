-- =====================================================================
-- Migration 028: Harden Rate Limit Windows Table & RPC Security
-- File: supabase/migrations/20261012000001_harden_rate_limit_windows_security.sql
-- Reference: PHASE 18A.6B - Remediation of Finding F-02
-- Description:
-- 1. Enables Row-Level Security on public.rate_limit_windows.
-- 2. Revokes direct table access from untrusted client roles (anon, authenticated, PUBLIC).
-- 3. Grants direct table management strictly to trusted server roles (postgres, service_role).
-- 4. Restricts EXECUTE on public.consume_rate_limit RPC to service_role and postgres.
-- 5. Preserves atomic window rate limiting semantics, search_path, and function ownership.
-- =====================================================================

BEGIN;

-- 1. Enable Row-Level Security on public.rate_limit_windows
ALTER TABLE public.rate_limit_windows ENABLE ROW LEVEL SECURITY;

-- 2. Revoke all table privileges from untrusted client-facing roles
REVOKE ALL ON TABLE public.rate_limit_windows FROM PUBLIC;
REVOKE ALL ON TABLE public.rate_limit_windows FROM anon;
REVOKE ALL ON TABLE public.rate_limit_windows FROM authenticated;

-- 3. Grant table privileges strictly to trusted internal database roles
GRANT ALL ON TABLE public.rate_limit_windows TO postgres, service_role;

-- 4. Restrict execution on public.consume_rate_limit RPC
REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM authenticated;

GRANT EXECUTE ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) TO postgres, service_role;

-- 5. Guarantee explicit function ownership and immutable search path
ALTER FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) OWNER TO postgres;
ALTER FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) SET search_path = public, pg_temp;

COMMIT;
