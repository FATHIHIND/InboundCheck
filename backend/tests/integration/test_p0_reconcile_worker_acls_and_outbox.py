"""Live-Postgres proof for migration 20261107000001 (P0 reconcile worker ACLs + outbox).

SKIPPED unless INBOUNDCHECK_PG_TEST_DSN points at a THROWAWAY local Postgres, e.g.

    docker run --rm -d --name ic-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17
    $env:INBOUNDCHECK_PG_TEST_DSN = "postgresql://postgres:test@localhost:55432/postgres"
    py -m pytest tests/integration/test_p0_reconcile_worker_acls_and_outbox.py -v

The test CREATEs/DROPs its own scratch databases, so it refuses any non-local host.

Scenarios
  * prod_state   : reproduces the 2026-11-07 production snapshot (out-of-band outbox
                   family, missing contract RPCs, PUBLIC/anon/authenticated EXECUTE on
                   record_delivery_failure_dispatch_intent, authenticated EXECUTE on
                   quarantine_expired_dispatch_intent_events).
  * source_state : runs the repo's own 20261031000002 + 20261104000003 on a base schema.
  * conflict     : prod_state plus a wrong-return-type / stray overload of contract RPCs.
Each scenario applies the migration, asserts existence, ACL matrix and behaviour, then
re-applies it to prove idempotency.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import errors as pg_errors  # noqa: E402
from psycopg2.extensions import make_dsn, parse_dsn  # noqa: E402

DSN = os.environ.get("INBOUNDCHECK_PG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INBOUNDCHECK_PG_TEST_DSN not set (live Postgres harness)")

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"
MIGRATION = MIGRATIONS / "20261107000001_p0_reconcile_worker_acls_and_outbox.sql"

CONTRACT = [
    "claim_notification_outbox",
    "complete_notification_outbox",
    "fail_or_retry_notification_outbox",
    "record_notification_outbox_dispatch_intent",
    "schema_contract_missing_functions",
]

WORKER_FUNCTIONS = [
    "record_delivery_failure_dispatch_intent",
    "quarantine_expired_dispatch_intent_events",
    "mark_delivery_failure_event_processed",
    "mark_delivery_failure_event_failed",
    "claim_received_delivery_failure_events",
    "claim_pending_delivery_failure_events",
    "release_claimed_delivery_failure_event",
    "claim_due_domain_audits",
    "complete_domain_audit",
    "fail_domain_audit",
    "extend_domain_audit_lease",
    "cleanup_stale_webhook_events",
    "mark_delivery_failure_event_dead_letter",
    "schedule_delivery_failure_retry",
    "claim_pending_notification_outbox",
    "quarantine_expired_notification_outbox",
    "record_notification_outbox_dispatch_intent",
    "mark_notification_outbox_processed",
    "mark_notification_outbox_failed",
    "mark_notification_outbox_dead_letter",
    "schedule_notification_outbox_retry",
    "enqueue_notification_outbox",
    "claim_notification_outbox",
    "complete_notification_outbox",
    "fail_or_retry_notification_outbox",
    "schema_contract_missing_functions",
]

# ---------------------------------------------------------------------------
# Fixture SQL
# ---------------------------------------------------------------------------

BASE_SQL = r"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
-- Mirror Supabase: new functions in public get explicit EXECUTE for API roles.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;

CREATE SCHEMA IF NOT EXISTS auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $f$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $f$;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS
  $f$ SELECT nullif(current_setting('request.jwt.claim.role', true), '')::text $f$;

CREATE TABLE public.profiles (id uuid PRIMARY KEY);

CREATE TABLE public.delivery_failure_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  esp_provider text NOT NULL DEFAULT 'postmark',
  provider_event_id text NOT NULL DEFAULT gen_random_uuid()::text,
  event_type text NOT NULL DEFAULT 'bounce',
  processing_status text NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received','ignored','queued','dispatching','quarantined','processed','failed')),
  event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  claimed_by uuid, claimed_at timestamptz, processing_error text, lease_until timestamptz,
  dispatch_intent_at timestamptz, dispatch_attempt_count integer DEFAULT 0
);

CREATE TABLE public.failover_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  order_id text, customer_phone text, channel text, provider text,
  status text NOT NULL DEFAULT 'dispatched',
  dispatch_payload jsonb DEFAULT '{}'::jsonb,
  delivery_failure_event_id uuid, fallback_channel text, outbox_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Delivery-failure RPCs shared by both states (bodies per 20261029000001).
CREATE FUNCTION public.record_delivery_failure_dispatch_intent(p_event_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
DECLARE v int; BEGIN
  UPDATE public.delivery_failure_events SET processing_status='dispatching', dispatch_intent_at=now(),
         dispatch_attempt_count=COALESCE(dispatch_attempt_count,0)+1
  WHERE id=p_event_id AND claimed_by=p_worker_id AND processing_status='queued'
    AND lease_until IS NOT NULL AND lease_until>now();
  GET DIAGNOSTICS v = ROW_COUNT; RETURN v>0; END $f$;

CREATE FUNCTION public.quarantine_expired_dispatch_intent_events(p_limit integer DEFAULT 50)
RETURNS TABLE(event_id uuid, user_id uuid, esp_provider text, resolution text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
BEGIN RETURN; END $f$;

CREATE FUNCTION public.claim_pending_delivery_failure_events(p_worker_id uuid, p_limit integer DEFAULT 20,
  p_lease_timeout interval DEFAULT '15 minutes')
RETURNS SETOF public.delivery_failure_events LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $f$ BEGIN RETURN; END $f$;
CREATE FUNCTION public.claim_received_delivery_failure_events(p_worker_id uuid, p_limit integer DEFAULT 20,
  p_lease_timeout interval DEFAULT '15 minutes')
RETURNS SETOF public.delivery_failure_events LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $f$ BEGIN RETURN; END $f$;
CREATE FUNCTION public.release_claimed_delivery_failure_event(p_event_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.mark_delivery_failure_event_processed(p_event_id uuid, p_worker_id uuid,
  p_outcome text DEFAULT 'processed', p_reason text DEFAULT NULL)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.mark_delivery_failure_event_failed(p_event_id uuid, p_worker_id uuid, p_error text)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.cleanup_stale_webhook_events()
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT 0 $f$;
-- Deliberately NO search_path pin: the migration must pin it.
CREATE FUNCTION public.complete_domain_audit(p_domain_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER AS $f$ SELECT false $f$;

-- Mirror the documented prod ACL baseline: service_role/postgres only ...
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', r.sig);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', r.sig);
  END LOOP; END $$;
-- ... except the two documented findings (MUST be fixed by the migration).
GRANT EXECUTE ON FUNCTION public.record_delivery_failure_dispatch_intent(uuid, uuid) TO PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.quarantine_expired_dispatch_intent_events(integer) TO authenticated;
"""

PROD_OUTBOX_SQL = r"""
CREATE TABLE public.notification_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  channel text NOT NULL DEFAULT 'telegram' CHECK (channel IN ('telegram','sms','whatsapp')),
  notification_type text NOT NULL DEFAULT 'incident_alert' CHECK (notification_type IN ('incident_alert','test_ping','digest')),
  idempotency_key text,
  order_id text NOT NULL,
  domain_name text, store_name text,
  trigger_reason text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','dispatching','processed','failed','dead_letter','quarantined')),
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 5,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  claimed_by uuid, claimed_at timestamptz, lease_until timestamptz, last_error text, processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  destination_chat_id text
);
CREATE UNIQUE INDEX idx_notification_outbox_user_idempotency ON public.notification_outbox (user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_notification_outbox_claim_queue ON public.notification_outbox (status, next_attempt_at, lease_until)
  WHERE status IN ('queued','dispatching');
CREATE INDEX idx_notification_outbox_user_created ON public.notification_outbox (user_id, created_at DESC);
ALTER TABLE public.notification_outbox ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own notification outbox" ON public.notification_outbox FOR ALL TO public
  USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
GRANT INSERT, UPDATE, DELETE ON public.notification_outbox TO authenticated;

-- Out-of-band prod outbox family (semantics per snapshot).
CREATE FUNCTION public.quarantine_expired_notification_outbox(p_limit integer DEFAULT 50)
RETURNS TABLE(outbox_id uuid, user_id uuid, order_id text, resolution text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
BEGIN
  RETURN QUERY
  WITH c AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE o.status='dispatching' AND o.lease_until < now()
    ORDER BY o.lease_until FOR UPDATE SKIP LOCKED LIMIT p_limit
  ), u AS (
    UPDATE public.notification_outbox o
    SET status = CASE WHEN EXISTS (SELECT 1 FROM public.failover_logs fl
                   WHERE fl.channel='telegram' AND fl.status IN ('delivered','dispatched')
                     AND (fl.outbox_id=o.id OR fl.dispatch_payload->>'outbox_id'=o.id::text))
                 THEN 'processed' ELSE 'quarantined' END,
        processed_at = now(), claimed_by = NULL, lease_until = NULL
    FROM c WHERE o.id=c.id
    RETURNING o.id, o.user_id, o.order_id, o.status
  ) SELECT u.id, u.user_id, u.order_id, u.status FROM u;
END $f$;

CREATE FUNCTION public.claim_pending_notification_outbox(p_worker_id uuid, p_limit integer DEFAULT 20,
  p_lease_timeout interval DEFAULT '15 minutes')
RETURNS SETOF public.notification_outbox LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
BEGIN
  PERFORM public.quarantine_expired_notification_outbox(p_limit);
  RETURN QUERY
  WITH c AS (
    SELECT o.id FROM public.notification_outbox o
    WHERE (o.status='queued' AND o.next_attempt_at<=now()) OR (o.status='dispatching' AND o.lease_until<now())
    ORDER BY o.created_at FOR UPDATE SKIP LOCKED LIMIT p_limit
  )
  UPDATE public.notification_outbox o SET status='dispatching', claimed_by=p_worker_id, claimed_at=now(),
         lease_until=now()+p_lease_timeout
  FROM c WHERE o.id=c.id RETURNING o.*;
END $f$;

CREATE FUNCTION public.record_notification_outbox_dispatch_intent(p_outbox_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
DECLARE v int; BEGIN
  UPDATE public.notification_outbox SET attempt_count = attempt_count + 1
  WHERE id=p_outbox_id AND claimed_by=p_worker_id AND status IN ('queued','dispatching') AND lease_until>now();
  GET DIAGNOSTICS v = ROW_COUNT; RETURN v>0; END $f$;

CREATE FUNCTION public.mark_notification_outbox_processed(p_outbox_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.mark_notification_outbox_failed(p_outbox_id uuid, p_worker_id uuid, p_error text)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.mark_notification_outbox_dead_letter(p_outbox_id uuid, p_worker_id uuid, p_error text)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.schedule_notification_outbox_retry(p_outbox_id uuid, p_worker_id uuid,
  p_next_attempt_at timestamptz, p_error text, p_max_attempts integer DEFAULT 5)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;
CREATE FUNCTION public.enqueue_notification_outbox(p_user_id uuid, p_order_id text, p_trigger_reason text,
  p_destination_chat_id text DEFAULT NULL, p_domain_name text DEFAULT NULL, p_store_name text DEFAULT NULL,
  p_idempotency_key text DEFAULT NULL, p_channel text DEFAULT 'telegram', p_payload jsonb DEFAULT '{}'::jsonb,
  p_max_attempts integer DEFAULT 5)
RETURNS public.notification_outbox LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $f$
DECLARE r public.notification_outbox; BEGIN
  IF auth.role()='authenticated' AND auth.uid() IS DISTINCT FROM p_user_id THEN RAISE EXCEPTION 'forbidden'; END IF;
  INSERT INTO public.notification_outbox(user_id, order_id, trigger_reason, destination_chat_id, domain_name,
    store_name, idempotency_key, channel, payload, max_attempts)
  VALUES (p_user_id, p_order_id, p_trigger_reason, p_destination_chat_id, p_domain_name, p_store_name,
    p_idempotency_key, p_channel, p_payload, p_max_attempts) RETURNING * INTO r;
  RETURN r; END $f$;
CREATE FUNCTION public.schedule_delivery_failure_retry(p_event_id uuid, p_worker_id uuid,
  p_next_attempt_at timestamptz, p_error text, p_max_attempts integer DEFAULT 5)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT false $f$;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' AND (p.proname LIKE '%notification_outbox%' OR p.proname='schedule_delivery_failure_retry') LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', r.sig);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', r.sig);
  END LOOP; END $$;
"""

CONFLICT_SQL = r"""
-- Wrong return type for a contract name (CREATE OR REPLACE would fail on this).
CREATE FUNCTION public.complete_notification_outbox(p_outbox_id uuid, p_worker_id uuid)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT 0 $f$;
-- Stray overload that would make PostgREST resolution ambiguous.
CREATE FUNCTION public.claim_notification_outbox(p_worker_id uuid)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $f$ SELECT 0 $f$;
GRANT EXECUTE ON FUNCTION public.complete_notification_outbox(uuid, uuid) TO PUBLIC, anon, authenticated;
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_dsn(dbname: str | None = None) -> str:
    params = parse_dsn(DSN)  # type: ignore[arg-type]
    if dbname:
        params["dbname"] = dbname
    return make_dsn(**params)


def _assert_local_target() -> None:
    params = parse_dsn(DSN)  # type: ignore[arg-type]
    host = params.get("host") or urlparse(DSN).hostname or "localhost"
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip(f"Refusing to create/drop databases on non-local host {host!r}")


def _connect(dbname: str):
    conn = psycopg2.connect(_admin_dsn(dbname))
    conn.autocommit = True
    return conn


def _fresh_db(name: str) -> None:
    conn = psycopg2.connect(_admin_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{name}"')
    conn.close()


def _drop_db(name: str) -> None:
    conn = psycopg2.connect(_admin_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    conn.close()


def _apply_migration(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text(encoding="utf-8"))


def _scalar(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]


def _rows(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _as_role(conn, role: str, sql: str, params=()):
    """Run a statement as an API role inside a transaction-scoped SET ROLE."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {role}")
            cur.execute(sql, params)
            out = cur.fetchall() if cur.description else None
            cur.execute("COMMIT")
            return out
        except Exception:
            cur.execute("ROLLBACK")
            raise


def _insert_outbox(conn, user_id: str) -> str:
    cols = {r[0] for r in _rows(conn, "SELECT column_name FROM information_schema.columns "
                                       "WHERE table_schema='public' AND table_name='notification_outbox'")}
    values = {"user_id": user_id, "channel": "telegram", "payload": '{"order_id":"1001"}'}
    if "idempotency_key" in cols:
        values["idempotency_key"] = str(uuid.uuid4())
    if "order_id" in cols:
        values["order_id"] = "1001"
    if "trigger_reason" in cols:
        values["trigger_reason"] = "email_spam_detected"
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return _scalar(conn, f"INSERT INTO public.notification_outbox ({names}) VALUES ({marks}) RETURNING id::text",
                   tuple(values.values()))


def _assert_contract_and_acls(conn) -> None:
    # (a) contract functions exist with the exact backend signatures.
    assert _scalar(conn, "SELECT public.schema_contract_missing_functions(%s)", (CONTRACT,)) == []
    sigs = dict(_rows(conn, """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
               pg_get_function_result(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname='public' AND p.proname = ANY(%s)""", (CONTRACT,)))
    assert sigs == {
        "claim_notification_outbox(p_worker_id uuid, p_limit integer, p_lease_timeout interval)":
            "SETOF notification_outbox",
        "complete_notification_outbox(p_outbox_id uuid, p_worker_id uuid)": "boolean",
        "fail_or_retry_notification_outbox(p_outbox_id uuid, p_worker_id uuid, p_error text, p_retryable boolean, "
        "p_next_attempt_at timestamp with time zone, p_max_attempts integer)":
            "TABLE(id uuid, new_status text, attempt_count integer, next_attempt_at timestamp with time zone)",
        "record_notification_outbox_dispatch_intent(p_outbox_id uuid, p_worker_id uuid)": "boolean",
        "schema_contract_missing_functions(p_required text[])": "text[]",
    }, sigs
    # SECURITY DEFINER + pinned search_path on every contract function.
    bad = _rows(conn, """
        SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname = ANY(%s)
          AND NOT (p.prosecdef AND p.proconfig @> ARRAY['search_path=public, pg_temp'])""", (CONTRACT,))
    assert bad == []
    # (b) has_function_privilege matrix over every existing worker/outbox overload.
    matrix = _rows(conn, """
        SELECT p.oid::regprocedure::text,
               has_function_privilege('anon', p.oid, 'EXECUTE'),
               has_function_privilege('authenticated', p.oid, 'EXECUTE'),
               has_function_privilege('service_role', p.oid, 'EXECUTE'),
               (p.proacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(p.proacl) a
                                             WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE')) AS public_exec,
               p.prosecdef, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname = ANY(%s)""", (WORKER_FUNCTIONS,))
    assert len(matrix) >= 10, matrix
    for sig, anon, authn, svc, public_exec, secdef, config in matrix:
        assert (anon, authn, svc, public_exec) == (False, False, True, False), (sig, anon, authn, svc, public_exec)
        if secdef:
            assert config and any(c.startswith("search_path=") for c in config), (sig, config)


def _assert_behaviour(conn) -> None:
    uid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users(id) VALUES (%s)", (uid,))
        cur.execute("INSERT INTO public.profiles(id) VALUES (%s)", (uid,))
    a, b, c = (_insert_outbox(conn, uid) for _ in range(3))
    w1, w2 = str(uuid.uuid4()), str(uuid.uuid4())

    # API roles cannot drive worker state transitions.
    for role in ("anon", "authenticated"):
        with pytest.raises(pg_errors.InsufficientPrivilege):
            _as_role(conn, role, "SELECT * FROM public.claim_notification_outbox(%s::uuid, 10, '5 minutes')", (w1,))
        with pytest.raises(pg_errors.InsufficientPrivilege):
            _as_role(conn, role, "SELECT public.record_delivery_failure_dispatch_intent(%s::uuid, %s::uuid)", (w1, w1))
        with pytest.raises(pg_errors.InsufficientPrivilege):
            _as_role(conn, role, "SELECT public.schema_contract_missing_functions(ARRAY['x'])")

    svc = lambda sql, params=(): _as_role(conn, "service_role", sql, params)  # noqa: E731

    # claim with lease — exactly the kwargs the backend sends (p_lease_timeout as text).
    claimed = svc("SELECT id::text, status, claimed_by::text, lease_until > now(), attempt_count "
                  "FROM public.claim_notification_outbox(p_worker_id => %s::uuid, p_limit => %s, "
                  "p_lease_timeout => %s::interval)", (w1, 20, "300 seconds"))
    assert sorted(r[0] for r in claimed) == sorted([a, b, c])
    assert all(r[1:] == ("dispatching", w1, True, 1) for r in claimed), claimed

    # dispatch intent: owner only, one-way.
    assert svc("SELECT public.record_notification_outbox_dispatch_intent(%s::uuid, %s::uuid)", (a, w2)) == [(False,)]
    assert svc("SELECT public.record_notification_outbox_dispatch_intent(%s::uuid, %s::uuid)", (a, w1)) == [(True,)]
    assert svc("SELECT public.record_notification_outbox_dispatch_intent(%s::uuid, %s::uuid)", (a, w1)) == [(False,)]

    # complete is lease-fenced on worker identity.
    assert svc("SELECT public.complete_notification_outbox(%s::uuid, %s::uuid)", (b, w2)) == [(False,)]
    assert svc("SELECT public.complete_notification_outbox(%s::uuid, %s::uuid)", (b, w1)) == [(True,)]
    assert _scalar(conn, "SELECT status FROM public.notification_outbox WHERE id=%s", (b,)) == "processed"

    # fail_or_retry (retryable) schedules a retry; wrong worker gets no row.
    assert svc("SELECT * FROM public.fail_or_retry_notification_outbox(%s::uuid, %s::uuid, 'x', true, "
               "now() + interval '1 hour', 5)", (c, w2)) == []
    res = svc("SELECT id::text, new_status, attempt_count, next_attempt_at > now() + interval '50 minutes' "
              "FROM public.fail_or_retry_notification_outbox(p_outbox_id => %s::uuid, p_worker_id => %s::uuid, "
              "p_error => 'HTTP 429', p_retryable => true, p_next_attempt_at => now() + interval '1 hour', "
              "p_max_attempts => 5)", (c, w1))
    assert res == [(c, "queued", 1, True)], res
    assert _rows(conn, "SELECT status, claimed_by, lease_until FROM public.notification_outbox WHERE id=%s",
                 (c,)) == [("queued", None, None)]

    # Force lease expiry on the intent-recorded row: lease fence rejects the stale worker...
    with conn.cursor() as cur:
        cur.execute("UPDATE public.notification_outbox SET lease_until = now() - interval '1 second' WHERE id=%s", (a,))
    assert svc("SELECT public.complete_notification_outbox(%s::uuid, %s::uuid)", (a, w1)) == [(False,)]
    assert svc("SELECT * FROM public.fail_or_retry_notification_outbox(%s::uuid, %s::uuid, 'x', true, now(), 5)",
               (a, w1)) == []
    # ...and it is NEVER re-claimed for re-send; it is quarantined to dead_letter instead.
    reclaimed = svc("SELECT id::text FROM public.claim_notification_outbox(%s::uuid, 20, '5 minutes')", (w2,))
    assert a not in {r[0] for r in reclaimed}
    assert reclaimed == []  # c is not due yet, b is processed
    st, err, claimed_by = _rows(conn, "SELECT status, last_error, claimed_by FROM public.notification_outbox "
                                      "WHERE id=%s", (a,))[0]
    assert st == "dead_letter" and err.startswith("AMBIGUOUS_EXTERNAL_DISPATCH:") and claimed_by is None

    # A claimed row WITHOUT send intent is safely re-claimable after lease expiry.
    with conn.cursor() as cur:
        cur.execute("UPDATE public.notification_outbox SET next_attempt_at = now() - interval '1 second' WHERE id=%s",
                    (c,))
    assert svc("SELECT id::text FROM public.claim_notification_outbox(%s::uuid, 20, '5 minutes')", (w1,)) == [(c,)]
    with conn.cursor() as cur:
        cur.execute("UPDATE public.notification_outbox SET lease_until = now() - interval '1 second' WHERE id=%s", (c,))
    assert svc("SELECT id::text, attempt_count FROM public.claim_notification_outbox(%s::uuid, 20, '5 minutes')",
               (w2,)) == [(c, 3)]
    # An AMBIGUOUS-tagged failure can never be requeued even if flagged retryable.
    res = svc("SELECT new_status FROM public.fail_or_retry_notification_outbox(%s::uuid, %s::uuid, "
              "'AMBIGUOUS_EXTERNAL_DISPATCH: timeout', true, now(), 5)", (c, w2))
    assert res == [("dead_letter",)]

    # (e) contract helper.
    assert svc("SELECT public.schema_contract_missing_functions(ARRAY['claim_notification_outbox','nope'])") \
        == [(["nope"],)]


def _run_scenario(name: str, *setup_sql: str, pre_checks=None, post_checks=None) -> None:
    _assert_local_target()
    _fresh_db(name)
    conn = _connect(name)
    try:
        with conn.cursor() as cur:
            for sql in setup_sql:
                cur.execute(sql)
        if pre_checks:
            pre_checks(conn)
        _apply_migration(conn)
        _assert_contract_and_acls(conn)
        _assert_behaviour(conn)
        if post_checks:
            post_checks(conn)
        # (d) idempotency: second application must succeed and preserve everything.
        _apply_migration(conn)
        _assert_contract_and_acls(conn)
        _assert_behaviour(conn)
        if post_checks:
            post_checks(conn)
    finally:
        conn.close()
        _drop_db(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _prod_pre_checks(conn) -> None:
    # The harness really reproduces the outage + security findings before the fix.
    missing = _scalar(conn, """
        SELECT array_agg(x ORDER BY x) FROM unnest(%s::text[]) x
        WHERE NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                          WHERE n.nspname='public' AND p.proname=x)""",
                      (["claim_notification_outbox", "complete_notification_outbox",
                        "fail_or_retry_notification_outbox"],))
    assert missing == ["claim_notification_outbox", "complete_notification_outbox",
                       "fail_or_retry_notification_outbox"]
    assert _scalar(conn, "SELECT has_function_privilege('anon', "
                         "'public.record_delivery_failure_dispatch_intent(uuid,uuid)', 'EXECUTE')") is True
    assert _scalar(conn, "SELECT has_function_privilege('authenticated', "
                         "'public.quarantine_expired_dispatch_intent_events(integer)', 'EXECUTE')") is True


def test_prod_state_reconciliation():
    _run_scenario("ic_prod_state", BASE_SQL, PROD_OUTBOX_SQL, pre_checks=_prod_pre_checks)


_BACKEND_SHAPED_INSERT = """
    INSERT INTO public.notification_outbox
      (id, user_id, channel, idempotency_key, payload, status, attempt_count, max_attempts, next_attempt_at)
    VALUES (gen_random_uuid(), %s, 'telegram', %s,
            '{"order_id":"1001","trigger_reason":"email_spam_detected"}'::jsonb, 'queued', 0, 5, now())
"""


def test_prod_backend_shaped_enqueue_succeeds_after_migration():
    """Lead-added regression: SupabaseService.enqueue_notification_outbox inserts
    without order_id/trigger_reason (they live in payload). Production's drift
    table makes them NOT NULL, so every enqueue failed with 23502 before 1b."""
    import psycopg2  # noqa: F401  (harness dependency; skipped module-wide otherwise)

    _assert_local_target()
    name = "ic_prod_enqueue"
    _fresh_db(name)
    conn = _connect(name)
    try:
        with conn.cursor() as cur:
            cur.execute(BASE_SQL)
            cur.execute(PROD_OUTBOX_SQL)
            cur.execute("INSERT INTO public.profiles(id) VALUES (gen_random_uuid()) RETURNING id")
            user_id = cur.fetchone()[0]
        conn.commit()

        # Before: reproduces the production failure.
        with conn.cursor() as cur:
            try:
                cur.execute(_BACKEND_SHAPED_INSERT, (user_id, "before-fix"))
                raise AssertionError("backend-shaped insert unexpectedly succeeded before migration")
            except psycopg2.errors.NotNullViolation:
                conn.rollback()

        _apply_migration(conn)

        # After: the same insert succeeds; applying twice stays valid.
        with conn.cursor() as cur:
            cur.execute(_BACKEND_SHAPED_INSERT, (user_id, "after-fix"))
        conn.commit()
        _apply_migration(conn)
        with conn.cursor() as cur:
            cur.execute(_BACKEND_SHAPED_INSERT, (user_id, "after-reapply"))
        conn.commit()
        assert _scalar(conn, "SELECT count(*) FROM public.notification_outbox WHERE user_id=%s", (user_id,)) == 2
    finally:
        conn.close()
        _drop_db(name)


def test_source_chain_state_reconciliation():
    chain = [
        (MIGRATIONS / "20261031000002_durable_notification_outbox_and_retry_scheduling.sql").read_text("utf-8"),
        (MIGRATIONS / "20261104000003_notification_outbox_dispatch_quarantine.sql").read_text("utf-8"),
    ]
    _run_scenario("ic_source_state", BASE_SQL, *chain)


def test_conflicting_overloads_are_replaced():
    def pre(conn):
        assert _scalar(conn, "SELECT count(*) FROM pg_proc WHERE proname='claim_notification_outbox'") == 1

    _run_scenario("ic_conflict_state", BASE_SQL, PROD_OUTBOX_SQL, CONFLICT_SQL, pre_checks=pre)


# REV-6: a SECURITY DEFINER worker function whose proconfig carries OTHER settings
# (statement_timeout) but no search_path must still get search_path pinned.
_PROCONFIG_WITHOUT_SEARCH_PATH_SQL = r"""
CREATE FUNCTION public.mark_delivery_failure_event_dead_letter(p_event_id uuid, p_worker_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET statement_timeout = '5s' AS $f$ SELECT false $f$;
"""


def test_secdef_with_other_proconfig_gets_search_path_pinned():
    sig = "public.mark_delivery_failure_event_dead_letter(uuid,uuid)"

    def pre(conn):
        config = _scalar(conn, "SELECT proconfig FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
        assert config == ["statement_timeout=5s"], config

    def post(conn):
        config = _scalar(conn, "SELECT proconfig FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
        assert "statement_timeout=5s" in config, config
        assert "search_path=public, pg_temp" in config, config
        assert sum(c.startswith("search_path=") for c in config) == 1, config

    _run_scenario("ic_proconfig_state", BASE_SQL, PROD_OUTBOX_SQL, _PROCONFIG_WITHOUT_SEARCH_PATH_SQL,
                  pre_checks=pre, post_checks=post)
