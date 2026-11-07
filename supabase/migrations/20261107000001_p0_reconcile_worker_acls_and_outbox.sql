-- =====================================================================
-- Migration 20261107000001: P0 reconcile worker ACLs + notification outbox RPCs
-- Target: InboundCheck Supabase Postgres 17
-- =====================================================================
--
-- PURPOSE
--   Production's migration ledger stops at 20261012000001; notification_outbox
--   and an out-of-band outbox function family (claim_pending_notification_outbox,
--   mark_notification_outbox_*, schedule_notification_outbox_retry, ...) were
--   applied by hand. The backend (commit 0a7994c+) calls a DIFFERENT contract:
--     claim_notification_outbox(p_worker_id, p_limit, p_lease_timeout)
--     record_notification_outbox_dispatch_intent(p_outbox_id, p_worker_id)
--     complete_notification_outbox(p_outbox_id, p_worker_id)
--     fail_or_retry_notification_outbox(p_outbox_id, p_worker_id, p_error,
--                                       p_retryable, p_next_attempt_at, p_max_attempts)
--   which are absent in prod (worker logs PGRST202 every ~5s). This migration:
--     1. Adds notification_outbox.dispatch_started_at if missing (the only
--        column the 20261104000003 semantics need that prod lacks). When the
--        column is newly added, in-flight 'dispatching' rows are back-filled
--        as "intent recorded" (conservative: never re-sent automatically).
--     2. Creates/replaces the four outbox RPCs above with the 20261104000003
--        semantics (latest source definition wins): a row whose send intent was
--        recorded is NEVER re-claimed after lease expiry -- it goes to
--        dead_letter with an AMBIGUOUS_EXTERNAL_DISPATCH marker; complete and
--        fail_or_retry are lease-fenced (claimed_by = worker AND lease live).
--        record_notification_outbox_dispatch_intent is replaced as well
--        because prod's out-of-band body only bumps attempt_count and does not
--        persist the one-way intent marker the claim fence depends on.
--     3. Drops any overload of those four names whose identity arguments or
--        result type differ from the contract (CREATE OR REPLACE cannot change
--        a return type, and stray overloads cause PostgREST PGRST203).
--     4. ACL hardening (supersedes 20261031000001 intent): every worker/queue
--        RPC (and every overload of it) that exists gets
--        REVOKE ALL FROM PUBLIC, anon, authenticated; GRANT EXECUTE TO
--        postgres, service_role. Fixes prod findings:
--        record_delivery_failure_dispatch_intent (PUBLIC/anon/authenticated)
--        and quarantine_expired_dispatch_intent_events (authenticated).
--     5. Adds public.schema_contract_missing_functions(text[]) for the app's
--        startup probe (service_role only).
--   Table grants, RLS policies, Stripe and Shopify objects are NOT touched
--   (table-grant hardening is a separate P1 migration).
--
-- PREREQUISITES
--   * public.notification_outbox exists (prod out-of-band shape, or the shape
--     from 20261031000002 + 20261104000003). Columns used: id, status,
--     attempt_count, max_attempts, next_attempt_at, claimed_by, claimed_at,
--     lease_until, last_error, processed_at, created_at (+ dispatch_started_at,
--     added here if missing).
--   * Roles anon, authenticated, service_role exist (standard Supabase).
--   * Run as postgres (migration owner).
--
-- OPERATIONAL REQUIREMENT: STOP ALL FAILOVER/OUTBOX WORKERS BEFORE APPLYING.
--   The dispatch_started_at back-fill classifies every in-flight 'dispatching'
--   row as uncertain; a live worker mid-send would otherwise race the swap of
--   claim semantics. Restart workers (new build) only after verification.
--   Never run old (claim_pending_*) and new (claim_notification_outbox)
--   senders concurrently.
--
-- IDEMPOTENCY
--   Safe to run repeatedly and safe on BOTH (a) production as documented in the
--   2026-11-07 snapshot and (b) a database built from the full repo chain
--   (where 20261031000002 / 20261104000003 already defined these functions).
--
-- POST-APPLY VERIFICATION (run as postgres)
--   -- (1) contract present, expect '{}':
--   SELECT public.schema_contract_missing_functions(ARRAY[
--     'claim_notification_outbox','complete_notification_outbox',
--     'fail_or_retry_notification_outbox','record_notification_outbox_dispatch_intent',
--     'schema_contract_missing_functions']);
--   -- (2) signatures:
--   SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args,
--          pg_get_function_result(p.oid) AS result, p.prosecdef, p.proconfig
--   FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--   WHERE n.nspname = 'public' AND p.proname LIKE '%notification_outbox%'
--   ORDER BY 1, 2;
--   -- (3) privilege matrix, expect zero rows:
--   SELECT p.oid::regprocedure AS fn, r.rolname,
--          has_function_privilege(r.rolname, p.oid, 'EXECUTE') AS can_exec
--   FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--   CROSS JOIN (VALUES ('anon'),('authenticated'),('service_role')) r(rolname)
--   WHERE n.nspname = 'public' AND p.proname IN (<worker list below>)
--     AND has_function_privilege(r.rolname, p.oid, 'EXECUTE')
--         <> (r.rolname = 'service_role');
--   -- (4) ACL text, PUBLIC (=X/) must not appear:
--   SELECT p.oid::regprocedure, p.proacl FROM pg_proc p
--   JOIN pg_namespace n ON n.oid = p.pronamespace
--   WHERE n.nspname = 'public' AND p.proname IN
--     ('record_delivery_failure_dispatch_intent','quarantine_expired_dispatch_intent_events');
--
-- ROLLBACK / UNDO
--   BEGIN;
--   DROP FUNCTION IF EXISTS public.claim_notification_outbox(uuid, integer, interval);
--   DROP FUNCTION IF EXISTS public.complete_notification_outbox(uuid, uuid);
--   DROP FUNCTION IF EXISTS public.fail_or_retry_notification_outbox(uuid, uuid, text, boolean, timestamptz, integer);
--   DROP FUNCTION IF EXISTS public.schema_contract_missing_functions(text[]);
--   -- If the old worker and old intent function are restored, queued rows still
--   -- carrying dispatch_started_at would never be re-claimed; clear the marker:
--   UPDATE public.notification_outbox SET dispatch_started_at = NULL WHERE status = 'queued';
--   COMMIT;
--   NOTIFY pgrst, 'reload schema';
--   Not reverted on purpose:
--   * REVOKEs from PUBLIC/anon/authenticated (re-granting would restore a
--     vulnerability).
--   * record_notification_outbox_dispatch_intent (same signature as prod's
--     out-of-band function; the new body sets dispatch_started_at instead of
--     bumping attempt_count). Restore the prod body from a pre-apply
--     `pg_get_functiondef` capture only if you also roll back to the
--     claim_pending_notification_outbox worker.
--   * notification_outbox.dispatch_started_at (nullable, additive; harmless).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- SECTION 1: additive column required by dispatch-intent semantics
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid = 'public.notification_outbox'::regclass
      AND a.attname = 'dispatch_started_at' AND NOT a.attisdropped
  ) THEN
    ALTER TABLE public.notification_outbox ADD COLUMN dispatch_started_at TIMESTAMPTZ;
    -- Rows claimed under the out-of-band flow have no reliable pre-send
    -- evidence. Treat them as uncertain (never auto re-sent). Runs only when
    -- the column is new, so re-applying never reclassifies fresh claims.
    UPDATE public.notification_outbox
    SET dispatch_started_at = COALESCE(claimed_at, NOW())
    WHERE status = 'dispatching' AND dispatch_started_at IS NULL;
  END IF;
END
$$;

-- ---------------------------------------------------------------------
-- SECTION 1b: align out-of-band production drift with the source contract
-- ---------------------------------------------------------------------
-- Production's out-of-band notification_outbox carries order_id and
-- trigger_reason as NOT NULL without defaults. The source table
-- (20261031000002) has no such columns; the backend stores these values in
-- payload and its insert never sets them, so every enqueue would fail with
-- 23502 in production. Relax NOT NULL only where these drift columns exist.
-- No effect on databases built from the repository migration chain.
DO $$
DECLARE
  v_col TEXT;
BEGIN
  FOREACH v_col IN ARRAY ARRAY['order_id', 'trigger_reason'] LOOP
    IF EXISTS (
      SELECT 1 FROM pg_attribute a
      WHERE a.attrelid = 'public.notification_outbox'::regclass
        AND a.attname = v_col AND a.attnotnull AND NOT a.attisdropped
    ) THEN
      EXECUTE format('ALTER TABLE public.notification_outbox ALTER COLUMN %I DROP NOT NULL', v_col);
    END IF;
  END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- SECTION 2: remove conflicting overloads of the contract RPCs
-- ---------------------------------------------------------------------
DO $$
DECLARE
  r RECORD;
  v_want_args TEXT;
  v_want_result TEXT;
  v_old_path TEXT := current_setting('search_path');
BEGIN
  -- Render types schema-qualified so the comparison is search_path independent.
  PERFORM set_config('search_path', 'pg_catalog', true);
  FOR r IN
    SELECT p.oid, p.proname,
           pg_get_function_identity_arguments(p.oid) AS args,
           pg_get_function_result(p.oid) AS result
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname IN ('claim_notification_outbox', 'complete_notification_outbox',
                        'fail_or_retry_notification_outbox',
                        'record_notification_outbox_dispatch_intent')
  LOOP
    v_want_args := CASE r.proname
      WHEN 'claim_notification_outbox' THEN
        'p_worker_id uuid, p_limit integer, p_lease_timeout interval'
      WHEN 'complete_notification_outbox' THEN
        'p_outbox_id uuid, p_worker_id uuid'
      WHEN 'record_notification_outbox_dispatch_intent' THEN
        'p_outbox_id uuid, p_worker_id uuid'
      WHEN 'fail_or_retry_notification_outbox' THEN
        'p_outbox_id uuid, p_worker_id uuid, p_error text, p_retryable boolean, p_next_attempt_at timestamp with time zone, p_max_attempts integer'
    END;
    v_want_result := CASE r.proname
      WHEN 'claim_notification_outbox' THEN 'SETOF public.notification_outbox'
      WHEN 'complete_notification_outbox' THEN 'boolean'
      WHEN 'record_notification_outbox_dispatch_intent' THEN 'boolean'
      WHEN 'fail_or_retry_notification_outbox' THEN
        'TABLE(id uuid, new_status text, attempt_count integer, next_attempt_at timestamp with time zone)'
    END;
    IF r.args IS DISTINCT FROM v_want_args OR r.result IS DISTINCT FROM v_want_result THEN
      RAISE NOTICE 'Dropping non-contract overload %(%) -> %', r.proname, r.args, r.result;
      EXECUTE format('DROP FUNCTION public.%I(%s)', r.proname,
                     pg_get_function_identity_arguments(r.oid));
    END IF;
  END LOOP;
  PERFORM set_config('search_path', v_old_path, true);
END
$$;

-- ---------------------------------------------------------------------
-- SECTION 3: outbox worker RPCs (20261104000003 semantics, prod table shape)
-- ---------------------------------------------------------------------

-- One-way send fence: only the lease owner, while the lease is live, and only
-- once per claim. Called immediately before the external Telegram request.
CREATE OR REPLACE FUNCTION public.record_notification_outbox_dispatch_intent(
  p_outbox_id UUID,
  p_worker_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  UPDATE public.notification_outbox
  SET dispatch_started_at = NOW()
  WHERE id = p_outbox_id
    AND claimed_by = p_worker_id
    AND status = 'dispatching'
    AND dispatch_started_at IS NULL
    AND lease_until IS NOT NULL
    AND lease_until > NOW();
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_notification_outbox(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '5 minutes'
)
RETURNS SETOF public.notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 0), 0), 500);
BEGIN
  IF p_worker_id IS NULL OR v_limit = 0 OR p_lease_timeout IS NULL
     OR p_lease_timeout <= INTERVAL '0 seconds' THEN
    RETURN;
  END IF;

  -- Bounded, concurrency-safe sweep: an expired lease AFTER send intent is an
  -- unknown external outcome. It is dead-lettered for manual reconciliation
  -- and is never claimable again.
  WITH uncertain AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE o.status = 'dispatching'
      AND o.dispatch_started_at IS NOT NULL
      AND (o.lease_until IS NULL OR o.lease_until <= NOW())
    ORDER BY o.lease_until NULLS FIRST, o.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT v_limit
  )
  UPDATE public.notification_outbox o
  SET status = 'dead_letter',
      processed_at = NOW(),
      claimed_by = NULL,
      lease_until = NULL,
      last_error = 'AMBIGUOUS_EXTERNAL_DISPATCH: lease expired after send intent; manual reconciliation required'
  FROM uncertain
  WHERE o.id = uncertain.id;

  RETURN QUERY
  WITH candidates AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE o.dispatch_started_at IS NULL
      AND (
        (o.status = 'queued' AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= NOW()))
        OR (o.status = 'dispatching' AND (o.lease_until IS NULL OR o.lease_until <= NOW()))
      )
    ORDER BY o.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT v_limit
  )
  UPDATE public.notification_outbox o
  SET status = 'dispatching',
      attempt_count = o.attempt_count + 1,
      claimed_by = p_worker_id,
      claimed_at = NOW(),
      lease_until = NOW() + p_lease_timeout
  FROM candidates
  WHERE o.id = candidates.id
  RETURNING o.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_notification_outbox(
  p_outbox_id UUID,
  p_worker_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  UPDATE public.notification_outbox
  SET status = 'processed',
      processed_at = NOW(),
      claimed_by = NULL,
      lease_until = NULL,
      last_error = NULL
  WHERE id = p_outbox_id
    AND claimed_by = p_worker_id
    AND status = 'dispatching'
    AND lease_until IS NOT NULL
    AND lease_until > NOW();
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_or_retry_notification_outbox(
  p_outbox_id UUID,
  p_worker_id UUID,
  p_error TEXT,
  p_retryable BOOLEAN,
  p_next_attempt_at TIMESTAMPTZ,
  p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE(id UUID, new_status TEXT, attempt_count INTEGER, next_attempt_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_attempts INTEGER;
  v_max INTEGER;
  v_status TEXT;
BEGIN
  SELECT o.attempt_count,
         LEAST(o.max_attempts, GREATEST(COALESCE(p_max_attempts, o.max_attempts), 1))
  INTO v_attempts, v_max
  FROM public.notification_outbox o
  WHERE o.id = p_outbox_id
    AND o.claimed_by = p_worker_id
    AND o.status = 'dispatching'
    AND o.lease_until IS NOT NULL
    AND o.lease_until > NOW()
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  -- Retry only a definitive pre-send failure or explicit rejection. A tagged
  -- unknown outcome can never be requeued even if misflagged retryable.
  IF NOT COALESCE(p_retryable, FALSE)
     OR v_attempts >= v_max
     OR p_error LIKE 'AMBIGUOUS_EXTERNAL_DISPATCH:%' THEN
    v_status := 'dead_letter';
    UPDATE public.notification_outbox o
    SET status = v_status,
        processed_at = NOW(),
        last_error = p_error,
        claimed_by = NULL,
        lease_until = NULL
    WHERE o.id = p_outbox_id;
    RETURN QUERY SELECT p_outbox_id, v_status, v_attempts, NULL::TIMESTAMPTZ;
  ELSE
    v_status := 'queued';
    UPDATE public.notification_outbox o
    SET status = v_status,
        next_attempt_at = COALESCE(p_next_attempt_at, NOW()),
        last_error = p_error,
        claimed_by = NULL,
        lease_until = NULL,
        dispatch_started_at = NULL
    WHERE o.id = p_outbox_id;
    RETURN QUERY SELECT p_outbox_id, v_status, v_attempts, COALESCE(p_next_attempt_at, NOW());
  END IF;
END;
$$;

-- ---------------------------------------------------------------------
-- SECTION 4: schema contract helper for the application startup probe
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.schema_contract_missing_functions(p_required TEXT[])
RETURNS TEXT[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(array_agg(req.name ORDER BY req.ord), ARRAY[]::TEXT[])
  FROM unnest(COALESCE(p_required, ARRAY[]::TEXT[])) WITH ORDINALITY AS req(name, ord)
  WHERE NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = req.name
  );
$$;

-- ---------------------------------------------------------------------
-- SECTION 5: ACL hardening for every worker / queue RPC that exists
-- ---------------------------------------------------------------------
DO $$
DECLARE
  r RECORD;
  v_names TEXT[] := ARRAY[
    -- 20261031000001 list
    'record_delivery_failure_dispatch_intent',
    'quarantine_expired_dispatch_intent_events',
    'mark_delivery_failure_event_processed',
    'mark_delivery_failure_event_failed',
    'claim_received_delivery_failure_events',
    'claim_pending_delivery_failure_events',
    'release_claimed_delivery_failure_event',
    'claim_due_domain_audits',
    'complete_domain_audit',
    'fail_domain_audit',
    'extend_domain_audit_lease',
    'cleanup_stale_webhook_events',
    -- other delivery-failure worker RPCs present in prod / source
    'mark_delivery_failure_event_dead_letter',
    'schedule_delivery_failure_retry',
    -- outbox family: prod out-of-band names
    'claim_pending_notification_outbox',
    'quarantine_expired_notification_outbox',
    'record_notification_outbox_dispatch_intent',
    'mark_notification_outbox_processed',
    'mark_notification_outbox_failed',
    'mark_notification_outbox_dead_letter',
    'schedule_notification_outbox_retry',
    'enqueue_notification_outbox',
    -- outbox family: source contract names
    'claim_notification_outbox',
    'complete_notification_outbox',
    'fail_or_retry_notification_outbox',
    -- contract helper
    'schema_contract_missing_functions'
  ];
BEGIN
  FOR r IN
    SELECT p.oid, p.proname, p.prosecdef, p.proconfig,
           pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = ANY (v_names) AND p.prokind = 'f'
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%I(%s) FROM PUBLIC, anon, authenticated',
                   r.proname, r.args);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%I(%s) TO postgres, service_role',
                   r.proname, r.args);
    -- Pin search_path only where none is set; never override an existing pin.
    -- proconfig may hold other settings (e.g. statement_timeout) without a search_path.
    IF r.prosecdef AND NOT EXISTS (
         SELECT 1 FROM unnest(coalesce(r.proconfig, '{}'::text[])) c
         WHERE c LIKE 'search_path=%'
       ) THEN
      EXECUTE format('ALTER FUNCTION public.%I(%s) SET search_path = public, pg_temp',
                     r.proname, r.args);
    END IF;
  END LOOP;
END
$$;

COMMIT;

-- Ask PostgREST to pick up the new RPCs (no-op if nothing is listening).
NOTIFY pgrst, 'reload schema';
