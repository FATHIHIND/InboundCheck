-- ============================================================================
-- INBOUNDCHECK — DEFENSIVE MIGRATION LEDGER ROLLBACK TRANSACTION
-- Option A: Complete Restoration of Original Legacy Baseline
-- ----------------------------------------------------------------------------
-- OPERATIONAL GOVERNANCE & PRODUCTION LIMITATIONS:
-- WARNING: Rollback of migration ledger entries is NOT the normal recovery
-- mechanism on live Production. Deleting ledger entries on a live database whose
-- physical schema already contains the objects of those migrations causes
-- deployment tools (e.g. `supabase db push`) to attempt redundant re-execution,
-- triggering relation collision errors.
--
-- Once any subsequent migration (e.g., version > 20261012000001) has been applied,
-- rollback is STRICTLY FORBIDDEN and will fail-closed. In all post-maintenance
-- scenarios, use reviewed FORWARD RECOVERY instead.
-- ============================================================================
BEGIN;

SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '10s';
LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;

-- Rollback Preconditions: Verify Exact 28-Row Canonical State & Positive Provenance
DO $$
DECLARE
    v_cnt INT;
    v_missing_or_modified_targets INT;
    v_unexpected_rows INT;
BEGIN
    -- Precondition 1: Total rows MUST equal exactly 28.
    -- If any subsequent migration has been applied (v_cnt > 28), rollback fails immediately.
    SELECT count(*) INTO v_cnt FROM supabase_migrations.schema_migrations;
    IF v_cnt <> 28 THEN
        RAISE EXCEPTION 'ROLLBACK PRECONDITION FAILED [R-01]: Expected exactly 28 rows in ledger, found %. Rollback is refused because ledger state has evolved.', v_cnt;
    END IF;

    -- Precondition 2: All 28 target rows MUST exist with exact names AND positive provenance
    WITH expected_targets(version, name, created_by) AS (
        VALUES
            ('20260903000001', 'complete_production_schema', 'inboundcheck:reconciliation:phase18a'),
            ('20260904000001', 'fix_handle_new_user_trigger', 'inboundcheck:reconciliation:phase18a'),
            ('20260908000001', 'add_stripe_billing_fields', 'inboundcheck:reconciliation:phase18a'),
            ('20260909000001', 'reputation_checks_and_alert_configs', 'inboundcheck:reconciliation:phase18a'),
            ('20260909000002', 'performance_and_idempotency_hardening', 'inboundcheck:reconciliation:phase18a'),
            ('20260910000001', 'modernize_rbl_and_secure_rls', 'inboundcheck:reconciliation:phase18a'),
            ('20260911000001', 'add_rbl_scan_results', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000001', 'add_audit_leases_and_failover_pipeline', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000002', 'add_delivery_failure_ingestion_and_idempotency', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000003', 'add_delivery_failure_claim_rpc', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000004', 'allow_telegram_fallback_channel', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000001', 'add_readiness_and_revenue_risk', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000002', 'add_spf_merge_plans', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000003', 'add_remote_asset_fetch_audit', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000004', 'add_stripe_subscriptions', 'inboundcheck:reconciliation:phase18a'),
            ('20260916000001', 'allow_agency_tier', 'inboundcheck:reconciliation:phase18a'),
            ('20260924000001', 'p0_security_hardening', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000001', 'p1_reliability_remediation', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000002', 'shield_profile_billing_columns', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000003', 'fix_profile_billing_trigger_schema', 'inboundcheck:reconciliation:phase18a'),
            ('20260926000001', 'p1_failover_lease_recovery', 'inboundcheck:reconciliation:phase18a'),
            ('20260926000002', 'dns_autofix_production_foundation', 'inboundcheck:reconciliation:phase18a'),
            ('20260928000001', 'atomic_domain_quota_rpc', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000001', 'enterprise_legacy_migration_and_3tier_cleanup', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000002', 'ai_monthly_quota_ledger', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000003', 'ai_concurrency_leases', 'inboundcheck:reconciliation:phase18a'),
            ('20261001000001', 'ai_generation_telemetry', 'inboundcheck:reconciliation:phase18a'),
            ('20261012000001', 'harden_rate_limit_windows_security', 'inboundcheck:reconciliation:phase18a')
    )
    SELECT count(*) INTO v_missing_or_modified_targets
    FROM expected_targets e
    LEFT JOIN supabase_migrations.schema_migrations s
      ON s.version = e.version 
     AND s.name = e.name
     AND s.created_by = e.created_by
     AND s.statements IS NULL
     AND s.idempotency_key IS NULL
     AND s.rollback IS NULL
    WHERE s.version IS NULL;

    IF v_missing_or_modified_targets <> 0 THEN
        RAISE EXCEPTION 'ROLLBACK PRECONDITION FAILED [R-02]: % target rows are missing, modified, or lack provenance %; refusing rollback', v_missing_or_modified_targets, 'inboundcheck:reconciliation:phase18a';
    END IF;

    -- Precondition 3: Ensure zero rogue rows exist
    WITH expected_targets(version) AS (
        VALUES
            ('20260903000001', 'complete_production_schema', 'inboundcheck:reconciliation:phase18a'),
            ('20260904000001', 'fix_handle_new_user_trigger', 'inboundcheck:reconciliation:phase18a'),
            ('20260908000001', 'add_stripe_billing_fields', 'inboundcheck:reconciliation:phase18a'),
            ('20260909000001', 'reputation_checks_and_alert_configs', 'inboundcheck:reconciliation:phase18a'),
            ('20260909000002', 'performance_and_idempotency_hardening', 'inboundcheck:reconciliation:phase18a'),
            ('20260910000001', 'modernize_rbl_and_secure_rls', 'inboundcheck:reconciliation:phase18a'),
            ('20260911000001', 'add_rbl_scan_results', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000001', 'add_audit_leases_and_failover_pipeline', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000002', 'add_delivery_failure_ingestion_and_idempotency', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000003', 'add_delivery_failure_claim_rpc', 'inboundcheck:reconciliation:phase18a'),
            ('20260912000004', 'allow_telegram_fallback_channel', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000001', 'add_readiness_and_revenue_risk', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000002', 'add_spf_merge_plans', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000003', 'add_remote_asset_fetch_audit', 'inboundcheck:reconciliation:phase18a'),
            ('20260913000004', 'add_stripe_subscriptions', 'inboundcheck:reconciliation:phase18a'),
            ('20260916000001', 'allow_agency_tier', 'inboundcheck:reconciliation:phase18a'),
            ('20260924000001', 'p0_security_hardening', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000001', 'p1_reliability_remediation', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000002', 'shield_profile_billing_columns', 'inboundcheck:reconciliation:phase18a'),
            ('20260925000003', 'fix_profile_billing_trigger_schema', 'inboundcheck:reconciliation:phase18a'),
            ('20260926000001', 'p1_failover_lease_recovery', 'inboundcheck:reconciliation:phase18a'),
            ('20260926000002', 'dns_autofix_production_foundation', 'inboundcheck:reconciliation:phase18a'),
            ('20260928000001', 'atomic_domain_quota_rpc', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000001', 'enterprise_legacy_migration_and_3tier_cleanup', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000002', 'ai_monthly_quota_ledger', 'inboundcheck:reconciliation:phase18a'),
            ('20260930000003', 'ai_concurrency_leases', 'inboundcheck:reconciliation:phase18a'),
            ('20261001000001', 'ai_generation_telemetry', 'inboundcheck:reconciliation:phase18a'),
            ('20261012000001', 'harden_rate_limit_windows_security', 'inboundcheck:reconciliation:phase18a')
    )
    SELECT count(*) INTO v_unexpected_rows
    FROM supabase_migrations.schema_migrations s
    LEFT JOIN expected_targets e ON s.version = e.version
    WHERE e.version IS NULL;

    IF v_unexpected_rows <> 0 THEN
        RAISE EXCEPTION 'ROLLBACK PRECONDITION FAILED [R-03]: % unexpected rows found outside approved canonical set; refusing rollback', v_unexpected_rows;
    END IF;
END $$;

-- Execution Step 1: Delete ONLY the 28 standardized versions bearing positive provenance
DO $$
DECLARE
    v_deleted_count INT;
BEGIN
    DELETE FROM supabase_migrations.schema_migrations
    WHERE created_by = 'inboundcheck:reconciliation:phase18a'
      AND version IN (
          '20260903000001',
        '20260904000001',
        '20260908000001',
        '20260909000001',
        '20260909000002',
        '20260910000001',
        '20260911000001',
        '20260912000001',
        '20260912000002',
        '20260912000003',
        '20260912000004',
        '20260913000001',
        '20260913000002',
        '20260913000003',
        '20260913000004',
        '20260916000001',
        '20260924000001',
        '20260925000001',
        '20260925000002',
        '20260925000003',
        '20260926000001',
        '20260926000002',
        '20260928000001',
        '20260930000001',
        '20260930000002',
        '20260930000003',
        '20261001000001',
        '20261012000001'
      )
      AND version NOT IN ('20260910165935', '20260910195242', '20260910203910')
      AND statements IS NULL
      AND idempotency_key IS NULL
      AND rollback IS NULL;

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

    IF v_deleted_count <> 28 THEN
        RAISE EXCEPTION 'ROLLBACK EXECUTION FAILED: Expected to delete exactly 28 rows with provenance %, deleted %', 'inboundcheck:reconciliation:phase18a', v_deleted_count;
    END IF;
END $$;

-- Execution Step 2: Restore the 3 Original Legacy Records with Complete Statement Arrays
INSERT INTO supabase_migrations.schema_migrations (version, name, created_by, statements)
VALUES
    (
        '20260910165935',
        'add_delivery_failure_ingestion_and_idempotency',
        'hind10bella.fathi@gmail.com',
        ARRAY[$legacy_stmt_1$CREATE TABLE IF NOT EXISTS public.transactional_message_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  shopify_store_id UUID REFERENCES public.shopify_stores(id) ON DELETE SET NULL,
  order_id TEXT NOT NULL,
  esp_provider TEXT NOT NULL,
  provider_message_id TEXT NOT NULL,
  recipient_email_hash TEXT NOT NULL,
  recipient_phone_encrypted TEXT,
  phone_consent_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (phone_consent_status IN ('unknown', 'not_consented', 'consented', 'revoked')),
  message_type TEXT NOT NULL
    CHECK (message_type IN ('order_confirmation', 'shipping_update', 'delivery_update', 'password_reset')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (esp_provider, provider_message_id)
);

CREATE TABLE IF NOT EXISTS public.delivery_failure_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  esp_provider TEXT NOT NULL,
  provider_event_id TEXT NOT NULL,
  provider_message_id TEXT,
  event_type TEXT NOT NULL,
  event_timestamp TIMESTAMPTZ,
  signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
  processing_status TEXT NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received', 'ignored', 'queued', 'processed', 'failed')),
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  UNIQUE (esp_provider, provider_event_id)
);

CREATE INDEX IF NOT EXISTS idx_transactional_message_provider_message
  ON public.transactional_message_registry(esp_provider, provider_message_id);

CREATE INDEX IF NOT EXISTS idx_transactional_message_user_order
  ON public.transactional_message_registry(user_id, order_id);

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_processing
  ON public.delivery_failure_events(processing_status, received_at);

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_provider_msg
  ON public.delivery_failure_events(esp_provider, provider_message_id);

ALTER TABLE public.failover_logs
  ADD COLUMN IF NOT EXISTS delivery_failure_event_id UUID
    REFERENCES public.delivery_failure_events(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS transactional_message_id UUID
    REFERENCES public.transactional_message_registry(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS order_id TEXT,
  ADD COLUMN IF NOT EXISTS fallback_channel TEXT
    CHECK (fallback_channel IN ('sms', 'whatsapp')),
  ADD COLUMN IF NOT EXISTS provider_sid TEXT,
  ADD COLUMN IF NOT EXISTS provider_status TEXT,
  ADD COLUMN IF NOT EXISTS provider_error_code TEXT,
  ADD COLUMN IF NOT EXISTS provider_error_message TEXT,
  ADD COLUMN IF NOT EXISTS attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_one_dispatch_per_event_channel
  ON public.failover_logs(delivery_failure_event_id, fallback_channel)
  WHERE delivery_failure_event_id IS NOT NULL;

ALTER TABLE public.transactional_message_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_failure_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users access own transactional messages" ON public.transactional_message_registry;
CREATE POLICY "Users access own transactional messages"
  ON public.transactional_message_registry FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users access own delivery failure events" ON public.delivery_failure_events;
CREATE POLICY "Users access own delivery failure events"
  ON public.delivery_failure_events FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

GRANT ALL ON public.transactional_message_registry TO authenticated;
GRANT ALL ON public.transactional_message_registry TO service_role;

GRANT ALL ON public.delivery_failure_events TO authenticated;
GRANT ALL ON public.delivery_failure_events TO service_role;
$legacy_stmt_1$]::text[]
    ),
    (
        '20260910195242',
        'add_delivery_failure_claim_rpc',
        'hind10bella.fathi@gmail.com',
        ARRAY[$legacy_stmt_2$ALTER TABLE public.delivery_failure_events
  ADD COLUMN IF NOT EXISTS claimed_by UUID,
  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS processing_error TEXT;

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_claim_queue
  ON public.delivery_failure_events(processing_status, claimed_at, received_at)
  WHERE processing_status IN ('received', 'queued');

CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_per_event
  ON public.failover_logs(delivery_failure_event_id)
  WHERE delivery_failure_event_id IS NOT NULL AND channel = 'telegram';

CREATE OR REPLACE FUNCTION public.claim_received_delivery_failure_events(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20,
  p_lease_timeout INTERVAL DEFAULT INTERVAL '15 minutes'
)
RETURNS SETOF public.delivery_failure_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.delivery_failure_events
    WHERE processing_status = 'received'
       OR (processing_status = 'queued' AND claimed_at IS NOT NULL AND claimed_at < NOW() - p_lease_timeout)
    ORDER BY received_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.delivery_failure_events e
  SET processing_status = 'queued',
      claimed_by = p_worker_id,
      claimed_at = NOW()
  FROM candidates
  WHERE e.id = candidates.id
  RETURNING e.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_processed(
  p_event_id UUID,
  p_worker_id UUID,
  p_outcome TEXT DEFAULT 'processed',
  p_reason TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  UPDATE public.delivery_failure_events
  SET processing_status = p_outcome,
      processed_at = NOW(),
      processing_error = p_reason
  WHERE id = p_event_id
    AND (claimed_by = p_worker_id OR claimed_by IS NULL);

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_failed(
  p_event_id UUID,
  p_worker_id UUID,
  p_error TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_updated INTEGER;
BEGIN
  UPDATE public.delivery_failure_events
  SET processing_status = 'failed',
      processed_at = NOW(),
      processing_error = p_error
  WHERE id = p_event_id
    AND (claimed_by = p_worker_id OR claimed_by IS NULL);

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated > 0;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) TO authenticated, service_role;
$legacy_stmt_2$]::text[]
    ),
    (
        '20260910203910',
        'allow_telegram_fallback_channel',
        'hind10bella.fathi@gmail.com',
        ARRAY[$legacy_stmt_3$-- Telegram-only merchant incident alerts use failover_logs as an operational
-- audit trail. Legacy SMS/WhatsApp values remain readable for historical data.

ALTER TABLE public.failover_logs
  ALTER COLUMN customer_phone DROP NOT NULL;

ALTER TABLE public.failover_logs
  DROP CONSTRAINT IF EXISTS failover_logs_fallback_channel_check;

ALTER TABLE public.failover_logs
  DROP CONSTRAINT IF EXISTS check_failover_logs_channel;

DO $$
DECLARE
  conname text;
BEGIN
  FOR conname IN (
    SELECT con.conname 
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE rel.relname = 'failover_logs' 
      AND con.contype = 'c' 
      AND pg_get_constraintdef(con.oid) LIKE '%fallback_channel%'
  ) LOOP
    EXECUTE 'ALTER TABLE public.failover_logs DROP CONSTRAINT IF EXISTS ' || quote_ident(conname);
  END LOOP;
END $$;

ALTER TABLE public.failover_logs
  ADD CONSTRAINT failover_logs_fallback_channel_check
  CHECK (fallback_channel IN ('telegram', 'sms', 'whatsapp'));

-- Add an idempotency index for Telegram incident records:
CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_incident_per_event
ON public.failover_logs(delivery_failure_event_id)
WHERE delivery_failure_event_id IS NOT NULL
  AND fallback_channel = 'telegram';

-- Add worker-claim RPC:
-- Select only processing_status = 'received', lock using FOR UPDATE SKIP LOCKED,
-- update selected rows to queued, and return the claimed records.
CREATE OR REPLACE FUNCTION public.claim_pending_delivery_failure_events(
  p_worker_id UUID,
  p_limit INTEGER DEFAULT 20
)
RETURNS SETOF public.delivery_failure_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.delivery_failure_events
    WHERE processing_status = 'received'
    ORDER BY received_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT p_limit
  )
  UPDATE public.delivery_failure_events event
  SET processing_status = 'queued',
      claimed_by = p_worker_id,
      claimed_at = NOW()
  FROM candidates
  WHERE event.id = candidates.id
  RETURNING event.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER) TO authenticated, service_role;$legacy_stmt_3$]::text[]
    );

-- Rollback Postcondition: Exactly the 3 legacy rows must remain with byte-identical metadata
DO $$
DECLARE
    v_final_cnt INT;
    v_rec RECORD;
BEGIN
    SELECT count(*) INTO v_final_cnt FROM supabase_migrations.schema_migrations;
    IF v_final_cnt <> 3 THEN
        RAISE EXCEPTION 'ROLLBACK POSTCONDITION FAILED [R-04]: Expected exactly 3 rows remaining, found %', v_final_cnt;
    END IF;

    -- Verify Legacy Row 1
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910165935';
    IF NOT FOUND 
       OR v_rec.name <> 'add_delivery_failure_ingestion_and_idempotency'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 4077
       OR md5(v_rec.statements[1]) <> '03b0f9b6a641244e586c522967ccc12e' THEN
        RAISE EXCEPTION 'ROLLBACK POSTCONDITION FAILED [R-05]: Legacy row 20260910165935 restoration failed verification';
    END IF;

    -- Verify Legacy Row 2
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910195242';
    IF NOT FOUND 
       OR v_rec.name <> 'add_delivery_failure_claim_rpc'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 2951
       OR md5(v_rec.statements[1]) <> '28d5d7e69f6f50fc2133d85c6d67095b' THEN
        RAISE EXCEPTION 'ROLLBACK POSTCONDITION FAILED [R-06]: Legacy row 20260910195242 restoration failed verification';
    END IF;

    -- Verify Legacy Row 3
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910203910';
    IF NOT FOUND 
       OR v_rec.name <> 'allow_telegram_fallback_channel'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 2303
       OR md5(v_rec.statements[1]) <> '8f447b1417713536f7b965104051477e' THEN
        RAISE EXCEPTION 'ROLLBACK POSTCONDITION FAILED [R-07]: Legacy row 20260910203910 restoration failed verification';
    END IF;
END $$;

COMMIT;
