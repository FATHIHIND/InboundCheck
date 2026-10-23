-- ============================================================================
-- INBOUNDCHECK — MIGRATION LEDGER RECONCILIATION TRANSACTION
-- Option A: Canonical 28-Row Architecture (Universal Parity & Zero Drift)
-- Target Project Ref: tbjcldcoozvuvyipeonh
-- Provenance Marker: inboundcheck:reconciliation:phase18a
-- ============================================================================
BEGIN;

-- 1. CONCURRENCY SERIALIZATION & TIMEOUTS
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '10s';
LOCK TABLE supabase_migrations.schema_migrations IN ACCESS EXCLUSIVE MODE;

-- 2. PRECONDITION ASSERTIONS: Verify Exact Baseline State
DO $$
DECLARE
    v_initial_count INT;
    v_collision_count INT;
    v_rec RECORD;
BEGIN
    -- Precondition 1: Initial ledger MUST contain exactly 3 rows
    SELECT count(*) INTO v_initial_count 
    FROM supabase_migrations.schema_migrations;
    
    IF v_initial_count <> 3 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-01]: Expected exactly 3 starting rows in schema_migrations, found %', v_initial_count;
    END IF;

    -- Precondition 2: Zero target versions may already exist
    SELECT count(*) INTO v_collision_count
    FROM supabase_migrations.schema_migrations
    WHERE version IN (
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
    );

    IF v_collision_count <> 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-02]: % of 28 target versions already exist in ledger', v_collision_count;
    END IF;

    -- Precondition 3: Verify Legacy Row 1 (20260910165935)
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910165935';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-03]: Legacy version 20260910165935 missing';
    END IF;
    IF v_rec.name <> 'add_delivery_failure_ingestion_and_idempotency'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR v_rec.idempotency_key IS NOT NULL
       OR v_rec.rollback IS NOT NULL
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 4077
       OR md5(v_rec.statements[1]) <> '03b0f9b6a641244e586c522967ccc12e' THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-04]: Legacy version 20260910165935 metadata differs from baseline';
    END IF;

    -- Precondition 4: Verify Legacy Row 2 (20260910195242)
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910195242';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-05]: Legacy version 20260910195242 missing';
    END IF;
    IF v_rec.name <> 'add_delivery_failure_claim_rpc'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR v_rec.idempotency_key IS NOT NULL
       OR v_rec.rollback IS NOT NULL
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 2951
       OR md5(v_rec.statements[1]) <> '28d5d7e69f6f50fc2133d85c6d67095b' THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-06]: Legacy version 20260910195242 metadata differs from baseline';
    END IF;

    -- Precondition 5: Verify Legacy Row 3 (20260910203910)
    SELECT * INTO v_rec FROM supabase_migrations.schema_migrations WHERE version = '20260910203910';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-07]: Legacy version 20260910203910 missing';
    END IF;
    IF v_rec.name <> 'allow_telegram_fallback_channel'
       OR v_rec.created_by <> 'hind10bella.fathi@gmail.com'
       OR v_rec.idempotency_key IS NOT NULL
       OR v_rec.rollback IS NOT NULL
       OR array_length(v_rec.statements, 1) <> 1
       OR length(v_rec.statements[1]) <> 2303
       OR md5(v_rec.statements[1]) <> '8f447b1417713536f7b965104051477e' THEN
        RAISE EXCEPTION 'PRECONDITION FAILED [P-08]: Legacy version 20260910203910 metadata differs from baseline';
    END IF;
END $$;

-- 3. ATOMIC LEGACY SWAP: Remove Only the 3 Verified Legacy Rows
DO $$
DECLARE
    v_deleted_count INT;
BEGIN
    DELETE FROM supabase_migrations.schema_migrations
    WHERE version IN ('20260910165935', '20260910195242', '20260910203910')
      AND created_by = 'hind10bella.fathi@gmail.com'
      AND statements IS NOT NULL;

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
    IF v_deleted_count <> 3 THEN
        RAISE EXCEPTION 'SWAP FAILED: Expected to delete exactly 3 legacy rows, deleted %', v_deleted_count;
    END IF;
END $$;

-- 4. FAIL-CLOSED INGESTION: Insert 28 Standardized Target Versions with Positive Provenance
INSERT INTO supabase_migrations.schema_migrations (version, name, created_by)
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
    ('20261012000001', 'harden_rate_limit_windows_security', 'inboundcheck:reconciliation:phase18a');

-- 5. POSTCONDITION ASSERTIONS: Verify Exact Set Equality, Provenance & Zero Legacy Residuals
DO $$
DECLARE
    v_final_count INT;
    v_missing_pairs INT;
    v_unexpected_rows INT;
    v_legacy_residual INT;
BEGIN
    -- Postcondition 1: Total rows MUST equal exactly 28
    SELECT count(*) INTO v_final_count 
    FROM supabase_migrations.schema_migrations;

    IF v_final_count <> 28 THEN
        RAISE EXCEPTION 'POSTCONDITION FAILED [Q-01]: Expected exactly 28 rows, found %', v_final_count;
    END IF;

    -- Postcondition 2: Exact matching of all 28 (version, name, created_by) tuples
    WITH expected_pairs(version, name, created_by) AS (
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
    SELECT count(*) INTO v_missing_pairs
    FROM expected_pairs e
    LEFT JOIN supabase_migrations.schema_migrations s 
      ON s.version = e.version 
     AND s.name = e.name 
     AND s.created_by = e.created_by
     AND s.statements IS NULL
     AND s.idempotency_key IS NULL
     AND s.rollback IS NULL
    WHERE s.version IS NULL;

    IF v_missing_pairs <> 0 THEN
        RAISE EXCEPTION 'POSTCONDITION FAILED [Q-02]: % expected (version, name, created_by) tuples missing or mismatched', v_missing_pairs;
    END IF;

    -- Postcondition 3: Ensure zero rogue rows outside the 28 approved canonical versions
    WITH approved_versions(version) AS (
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
    LEFT JOIN approved_versions a ON s.version = a.version
    WHERE a.version IS NULL;

    IF v_unexpected_rows <> 0 THEN
        RAISE EXCEPTION 'POSTCONDITION FAILED [Q-03]: % unexpected rows found in schema_migrations', v_unexpected_rows;
    END IF;

    -- Postcondition 4: Ensure zero legacy rows remain in the active ledger
    SELECT count(*) INTO v_legacy_residual
    FROM supabase_migrations.schema_migrations
    WHERE version IN ('20260910165935', '20260910195242', '20260910203910');

    IF v_legacy_residual <> 0 THEN
        RAISE EXCEPTION 'POSTCONDITION FAILED [Q-04]: % legacy rows still exist in schema_migrations', v_legacy_residual;
    END IF;
END $$;

COMMIT;
