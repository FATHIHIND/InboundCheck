-- ============================================================================
-- INBOUNDCHECK — POST-RECONCILIATION VERIFICATION QUERY (READ-ONLY)
-- Option A: Exact 28-Pair Validation, Universal Parity & Zero Drift
-- Expected Total Rows: 28 Canonical Standardized Records (0 Legacy Residuals)
-- Required Provenance: inboundcheck:reconciliation:phase18a
-- ============================================================================
WITH expected_canonical_pairs(version, name) AS (
    VALUES
        ('20260903000001', 'complete_production_schema'),
        ('20260904000001', 'fix_handle_new_user_trigger'),
        ('20260908000001', 'add_stripe_billing_fields'),
        ('20260909000001', 'reputation_checks_and_alert_configs'),
        ('20260909000002', 'performance_and_idempotency_hardening'),
        ('20260910000001', 'modernize_rbl_and_secure_rls'),
        ('20260911000001', 'add_rbl_scan_results'),
        ('20260912000001', 'add_audit_leases_and_failover_pipeline'),
        ('20260912000002', 'add_delivery_failure_ingestion_and_idempotency'),
        ('20260912000003', 'add_delivery_failure_claim_rpc'),
        ('20260912000004', 'allow_telegram_fallback_channel'),
        ('20260913000001', 'add_readiness_and_revenue_risk'),
        ('20260913000002', 'add_spf_merge_plans'),
        ('20260913000003', 'add_remote_asset_fetch_audit'),
        ('20260913000004', 'add_stripe_subscriptions'),
        ('20260916000001', 'allow_agency_tier'),
        ('20260924000001', 'p0_security_hardening'),
        ('20260925000001', 'p1_reliability_remediation'),
        ('20260925000002', 'shield_profile_billing_columns'),
        ('20260925000003', 'fix_profile_billing_trigger_schema'),
        ('20260926000001', 'p1_failover_lease_recovery'),
        ('20260926000002', 'dns_autofix_production_foundation'),
        ('20260928000001', 'atomic_domain_quota_rpc'),
        ('20260930000001', 'enterprise_legacy_migration_and_3tier_cleanup'),
        ('20260930000002', 'ai_monthly_quota_ledger'),
        ('20260930000003', 'ai_concurrency_leases'),
        ('20261001000001', 'ai_generation_telemetry'),
        ('20261012000001', 'harden_rate_limit_windows_security')
),
verification_metrics AS (
    SELECT
        (SELECT count(*) FROM supabase_migrations.schema_migrations) AS total_actual_rows,
        -- Check canonical pairs exact match
        (SELECT count(*) 
         FROM expected_canonical_pairs e
         LEFT JOIN supabase_migrations.schema_migrations s 
           ON s.version = e.version AND s.name = e.name
         WHERE s.version IS NULL) AS missing_or_mismatched_canonical_count,
        -- Check canonical provenance
        (SELECT count(*) 
         FROM expected_canonical_pairs e
         JOIN supabase_migrations.schema_migrations s 
           ON s.version = e.version
         WHERE s.created_by <> 'inboundcheck:reconciliation:phase18a') AS invalid_provenance_count,
        -- Check legacy rows absence
        (SELECT count(*)
         FROM supabase_migrations.schema_migrations s
         WHERE s.version IN ('20260910165935', '20260910195242', '20260910203910')) AS legacy_residuals_count,
        -- Check for any rogue rows outside the 28 approved canonical versions
        (SELECT count(*)
         FROM supabase_migrations.schema_migrations s
         LEFT JOIN expected_canonical_pairs a ON s.version = a.version
         WHERE a.version IS NULL) AS unexpected_rogue_rows_count
)
SELECT 
    CASE WHEN total_actual_rows = 28 THEN 'PASSED: Total ledger count is exactly 28'
         ELSE 'FAILED [COUNT_MISMATCH]: Expected exactly 28 rows, found ' || total_actual_rows
    END AS check_total_count,

    CASE WHEN missing_or_mismatched_canonical_count = 0 
         THEN 'PASSED: All 28 canonical (version, name) pairs verified exactly'
         ELSE 'FAILED [CANONICAL_MISMATCH]: ' || missing_or_mismatched_canonical_count || ' canonical pairs missing or mismatched'
    END AS check_canonical_pairs,

    CASE WHEN invalid_provenance_count = 0
         THEN 'PASSED: All 28 canonical records bear explicit provenance inboundcheck:reconciliation:phase18a'
         ELSE 'FAILED [PROVENANCE_MISMATCH]: ' || invalid_provenance_count || ' canonical records have missing/wrong provenance'
    END AS check_canonical_provenance,

    CASE WHEN legacy_residuals_count = 0 
         THEN 'PASSED: Zero legacy residuals found in active ledger'
         ELSE 'FAILED [LEGACY_RESIDUALS]: ' || legacy_residuals_count || ' legacy records still exist in active ledger'
    END AS check_legacy_absence,

    CASE WHEN unexpected_rogue_rows_count = 0 
         THEN 'PASSED: Zero unexpected rogue rows detected'
         ELSE 'FAILED [ROGUE_ROWS]: ' || unexpected_rogue_rows_count || ' unexpected rogue rows detected'
    END AS check_rogue_rows
FROM verification_metrics;
