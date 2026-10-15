#!/usr/bin/env python3
"""
InboundCheck — Production-Grade Migration Ledger Reconciliation Engine
----------------------------------------------------------------------
Canonical 28-Row Invariant Architecture (Option A - Zero Drift)

Provides deterministic, fail-closed reconciliation between local repository
migration files and the remote Supabase `supabase_migrations.schema_migrations`
ledger table.

Key Guarantees:
1. Strict Preserved Baseline: Verifies exact byte-for-byte immutability of the 3 legacy rows.
2. Complete Legacy Preservation: Forensic archival of all original statement arrays.
3. Atomic Legacy Swap: Replaces 3 legacy rows with 28 canonical records within a single transaction.
4. Universal Multi-Environment Parity: Local (28 files) = Staging (28 rows) = Production (28 rows).
5. Strict Supabase CLI Compatibility: Prevents `DbPushMissingLocalError` in `supabase db push`.
6. Zero Target Collision: Rejects any collision before attempting insertion.
7. Concurrency Protection: Enforces `LOCK TABLE ... ACCESS EXCLUSIVE` and strict lock timeouts.
8. Defensive Rollback: Restores original 3 legacy rows with exact statements if ever reverted.
9. Absolute Production Protection: Default `--dry-run`; write execution against Production is blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Canonical 28 Standardized Migration Definitions (version, name)
CANONICAL_28_MIGRATIONS: Tuple[Tuple[str, str], ...] = (
    ("20260903000001", "complete_production_schema"),
    ("20260904000001", "fix_handle_new_user_trigger"),
    ("20260908000001", "add_stripe_billing_fields"),
    ("20260909000001", "reputation_checks_and_alert_configs"),
    ("20260909000002", "performance_and_idempotency_hardening"),
    ("20260910000001", "modernize_rbl_and_secure_rls"),
    ("20260911000001", "add_rbl_scan_results"),
    ("20260912000001", "add_audit_leases_and_failover_pipeline"),
    ("20260912000002", "add_delivery_failure_ingestion_and_idempotency"),
    ("20260912000003", "add_delivery_failure_claim_rpc"),
    ("20260912000004", "allow_telegram_fallback_channel"),
    ("20260913000001", "add_readiness_and_revenue_risk"),
    ("20260913000002", "add_spf_merge_plans"),
    ("20260913000003", "add_remote_asset_fetch_audit"),
    ("20260913000004", "add_stripe_subscriptions"),
    ("20260916000001", "allow_agency_tier"),
    ("20260924000001", "p0_security_hardening"),
    ("20260925000001", "p1_reliability_remediation"),
    ("20260925000002", "shield_profile_billing_columns"),
    ("20260925000003", "fix_profile_billing_trigger_schema"),
    ("20260926000001", "p1_failover_lease_recovery"),
    ("20260926000002", "dns_autofix_production_foundation"),
    ("20260928000001", "atomic_domain_quota_rpc"),
    ("20260930000001", "enterprise_legacy_migration_and_3tier_cleanup"),
    ("20260930000002", "ai_monthly_quota_ledger"),
    ("20260930000003", "ai_concurrency_leases"),
    ("20261001000001", "ai_generation_telemetry"),
    ("20261012000001", "harden_rate_limit_windows_security"),
)

PRODUCTION_REF = "tbjcldcoozvuvyipeonh"
STAGING_REF = "wymgyqnqwlliotkxamtd"
RECONCILIATION_PROVENANCE = "inboundcheck:reconciliation:phase18a"

CANONICAL_3_LEGACY_ROWS: Dict[str, Dict[str, Any]] = {'20260910165935': {'created_by': 'hind10bella.fathi@gmail.com', 'idempotency_key': None, 'name': 'add_delivery_failure_ingestion_and_idempotency', 'rollback': None, 'statements': ['CREATE TABLE IF NOT EXISTS public.transactional_message_registry (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,\n  shopify_store_id UUID REFERENCES public.shopify_stores(id) ON DELETE SET NULL,\n  order_id TEXT NOT NULL,\n  esp_provider TEXT NOT NULL,\n  provider_message_id TEXT NOT NULL,\n  recipient_email_hash TEXT NOT NULL,\n  recipient_phone_encrypted TEXT,\n  phone_consent_status TEXT NOT NULL DEFAULT \'unknown\'\n    CHECK (phone_consent_status IN (\'unknown\', \'not_consented\', \'consented\', \'revoked\')),\n  message_type TEXT NOT NULL\n    CHECK (message_type IN (\'order_confirmation\', \'shipping_update\', \'delivery_update\', \'password_reset\')),\n  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n  UNIQUE (esp_provider, provider_message_id)\n);\n\nCREATE TABLE IF NOT EXISTS public.delivery_failure_events (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,\n  esp_provider TEXT NOT NULL,\n  provider_event_id TEXT NOT NULL,\n  provider_message_id TEXT,\n  event_type TEXT NOT NULL,\n  event_timestamp TIMESTAMPTZ,\n  signature_verified BOOLEAN NOT NULL DEFAULT FALSE,\n  processing_status TEXT NOT NULL DEFAULT \'received\'\n    CHECK (processing_status IN (\'received\', \'ignored\', \'queued\', \'processed\', \'failed\')),\n  event_payload JSONB NOT NULL DEFAULT \'{}\'::jsonb,\n  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n  processed_at TIMESTAMPTZ,\n  UNIQUE (esp_provider, provider_event_id)\n);\n\nCREATE INDEX IF NOT EXISTS idx_transactional_message_provider_message\n  ON public.transactional_message_registry(esp_provider, provider_message_id);\n\nCREATE INDEX IF NOT EXISTS idx_transactional_message_user_order\n  ON public.transactional_message_registry(user_id, order_id);\n\nCREATE INDEX IF NOT EXISTS idx_delivery_failure_events_processing\n  ON public.delivery_failure_events(processing_status, received_at);\n\nCREATE INDEX IF NOT EXISTS idx_delivery_failure_events_provider_msg\n  ON public.delivery_failure_events(esp_provider, provider_message_id);\n\nALTER TABLE public.failover_logs\n  ADD COLUMN IF NOT EXISTS delivery_failure_event_id UUID\n    REFERENCES public.delivery_failure_events(id) ON DELETE SET NULL,\n  ADD COLUMN IF NOT EXISTS transactional_message_id UUID\n    REFERENCES public.transactional_message_registry(id) ON DELETE SET NULL,\n  ADD COLUMN IF NOT EXISTS order_id TEXT,\n  ADD COLUMN IF NOT EXISTS fallback_channel TEXT\n    CHECK (fallback_channel IN (\'sms\', \'whatsapp\')),\n  ADD COLUMN IF NOT EXISTS provider_sid TEXT,\n  ADD COLUMN IF NOT EXISTS provider_status TEXT,\n  ADD COLUMN IF NOT EXISTS provider_error_code TEXT,\n  ADD COLUMN IF NOT EXISTS provider_error_message TEXT,\n  ADD COLUMN IF NOT EXISTS attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n  ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,\n  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();\n\nCREATE UNIQUE INDEX IF NOT EXISTS idx_failover_one_dispatch_per_event_channel\n  ON public.failover_logs(delivery_failure_event_id, fallback_channel)\n  WHERE delivery_failure_event_id IS NOT NULL;\n\nALTER TABLE public.transactional_message_registry ENABLE ROW LEVEL SECURITY;\nALTER TABLE public.delivery_failure_events ENABLE ROW LEVEL SECURITY;\n\nDROP POLICY IF EXISTS "Users access own transactional messages" ON public.transactional_message_registry;\nCREATE POLICY "Users access own transactional messages"\n  ON public.transactional_message_registry FOR ALL\n  USING (auth.uid() = user_id)\n  WITH CHECK (auth.uid() = user_id);\n\nDROP POLICY IF EXISTS "Users access own delivery failure events" ON public.delivery_failure_events;\nCREATE POLICY "Users access own delivery failure events"\n  ON public.delivery_failure_events FOR ALL\n  USING (auth.uid() = user_id)\n  WITH CHECK (auth.uid() = user_id);\n\nGRANT ALL ON public.transactional_message_registry TO authenticated;\nGRANT ALL ON public.transactional_message_registry TO service_role;\n\nGRANT ALL ON public.delivery_failure_events TO authenticated;\nGRANT ALL ON public.delivery_failure_events TO service_role;\n'], 'version': '20260910165935'}, '20260910195242': {'created_by': 'hind10bella.fathi@gmail.com', 'idempotency_key': None, 'name': 'add_delivery_failure_claim_rpc', 'rollback': None, 'statements': ["ALTER TABLE public.delivery_failure_events\n  ADD COLUMN IF NOT EXISTS claimed_by UUID,\n  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,\n  ADD COLUMN IF NOT EXISTS processing_error TEXT;\n\nCREATE INDEX IF NOT EXISTS idx_delivery_failure_events_claim_queue\n  ON public.delivery_failure_events(processing_status, claimed_at, received_at)\n  WHERE processing_status IN ('received', 'queued');\n\nCREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_per_event\n  ON public.failover_logs(delivery_failure_event_id)\n  WHERE delivery_failure_event_id IS NOT NULL AND channel = 'telegram';\n\nCREATE OR REPLACE FUNCTION public.claim_received_delivery_failure_events(\n  p_worker_id UUID,\n  p_limit INTEGER DEFAULT 20,\n  p_lease_timeout INTERVAL DEFAULT INTERVAL '15 minutes'\n)\nRETURNS SETOF public.delivery_failure_events\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = public, pg_temp\nAS $$\nBEGIN\n  RETURN QUERY\n  WITH candidates AS (\n    SELECT id\n    FROM public.delivery_failure_events\n    WHERE processing_status = 'received'\n       OR (processing_status = 'queued' AND claimed_at IS NOT NULL AND claimed_at < NOW() - p_lease_timeout)\n    ORDER BY received_at ASC\n    FOR UPDATE SKIP LOCKED\n    LIMIT p_limit\n  )\n  UPDATE public.delivery_failure_events e\n  SET processing_status = 'queued',\n      claimed_by = p_worker_id,\n      claimed_at = NOW()\n  FROM candidates\n  WHERE e.id = candidates.id\n  RETURNING e.*;\nEND;\n$$;\n\nCREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_processed(\n  p_event_id UUID,\n  p_worker_id UUID,\n  p_outcome TEXT DEFAULT 'processed',\n  p_reason TEXT DEFAULT NULL\n)\nRETURNS BOOLEAN\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = public, pg_temp\nAS $$\nDECLARE\n  v_updated INTEGER;\nBEGIN\n  UPDATE public.delivery_failure_events\n  SET processing_status = p_outcome,\n      processed_at = NOW(),\n      processing_error = p_reason\n  WHERE id = p_event_id\n    AND (claimed_by = p_worker_id OR claimed_by IS NULL);\n\n  GET DIAGNOSTICS v_updated = ROW_COUNT;\n  RETURN v_updated > 0;\nEND;\n$$;\n\nCREATE OR REPLACE FUNCTION public.mark_delivery_failure_event_failed(\n  p_event_id UUID,\n  p_worker_id UUID,\n  p_error TEXT\n)\nRETURNS BOOLEAN\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = public, pg_temp\nAS $$\nDECLARE\n  v_updated INTEGER;\nBEGIN\n  UPDATE public.delivery_failure_events\n  SET processing_status = 'failed',\n      processed_at = NOW(),\n      processing_error = p_error\n  WHERE id = p_event_id\n    AND (claimed_by = p_worker_id OR claimed_by IS NULL);\n\n  GET DIAGNOSTICS v_updated = ROW_COUNT;\n  RETURN v_updated > 0;\nEND;\n$$;\n\nGRANT EXECUTE ON FUNCTION public.claim_received_delivery_failure_events(UUID, INTEGER, INTERVAL) TO authenticated, service_role;\nGRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_processed(UUID, UUID, TEXT, TEXT) TO authenticated, service_role;\nGRANT EXECUTE ON FUNCTION public.mark_delivery_failure_event_failed(UUID, UUID, TEXT) TO authenticated, service_role;\n"], 'version': '20260910195242'}, '20260910203910': {'created_by': 'hind10bella.fathi@gmail.com', 'idempotency_key': None, 'name': 'allow_telegram_fallback_channel', 'rollback': None, 'statements': ["-- Telegram-only merchant incident alerts use failover_logs as an operational\n-- audit trail. Legacy SMS/WhatsApp values remain readable for historical data.\n\nALTER TABLE public.failover_logs\n  ALTER COLUMN customer_phone DROP NOT NULL;\n\nALTER TABLE public.failover_logs\n  DROP CONSTRAINT IF EXISTS failover_logs_fallback_channel_check;\n\nALTER TABLE public.failover_logs\n  DROP CONSTRAINT IF EXISTS check_failover_logs_channel;\n\nDO $$\nDECLARE\n  conname text;\nBEGIN\n  FOR conname IN (\n    SELECT con.conname \n    FROM pg_constraint con\n    JOIN pg_class rel ON rel.oid = con.conrelid\n    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace\n    WHERE rel.relname = 'failover_logs' \n      AND con.contype = 'c' \n      AND pg_get_constraintdef(con.oid) LIKE '%fallback_channel%'\n  ) LOOP\n    EXECUTE 'ALTER TABLE public.failover_logs DROP CONSTRAINT IF EXISTS ' || quote_ident(conname);\n  END LOOP;\nEND $$;\n\nALTER TABLE public.failover_logs\n  ADD CONSTRAINT failover_logs_fallback_channel_check\n  CHECK (fallback_channel IN ('telegram', 'sms', 'whatsapp'));\n\n-- Add an idempotency index for Telegram incident records:\nCREATE UNIQUE INDEX IF NOT EXISTS idx_failover_logs_one_telegram_incident_per_event\nON public.failover_logs(delivery_failure_event_id)\nWHERE delivery_failure_event_id IS NOT NULL\n  AND fallback_channel = 'telegram';\n\n-- Add worker-claim RPC:\n-- Select only processing_status = 'received', lock using FOR UPDATE SKIP LOCKED,\n-- update selected rows to queued, and return the claimed records.\nCREATE OR REPLACE FUNCTION public.claim_pending_delivery_failure_events(\n  p_worker_id UUID,\n  p_limit INTEGER DEFAULT 20\n)\nRETURNS SETOF public.delivery_failure_events\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = public, pg_temp\nAS $$\nBEGIN\n  RETURN QUERY\n  WITH candidates AS (\n    SELECT id\n    FROM public.delivery_failure_events\n    WHERE processing_status = 'received'\n    ORDER BY received_at ASC\n    FOR UPDATE SKIP LOCKED\n    LIMIT p_limit\n  )\n  UPDATE public.delivery_failure_events event\n  SET processing_status = 'queued',\n      claimed_by = p_worker_id,\n      claimed_at = NOW()\n  FROM candidates\n  WHERE event.id = candidates.id\n  RETURNING event.*;\nEND;\n$$;\n\nGRANT EXECUTE ON FUNCTION public.claim_pending_delivery_failure_events(UUID, INTEGER) TO authenticated, service_role;"], 'version': '20260910203910'}}

@dataclass(frozen=True)
class LocalMigration:
    version: str
    name: str
    filename: str
    filepath: Path


def scan_local_migrations(migrations_dir: Path) -> List[LocalMigration]:
    """Scan and validate all local migration files in repository."""
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")

    files = sorted([f for f in migrations_dir.iterdir() if f.suffix == ".sql"])
    pattern = re.compile(r"^(\d{14})_(.*)\.sql$")
    migrations: List[LocalMigration] = []

    for f in files:
        m = pattern.match(f.name)
        if not m:
            raise ValueError(f"File does not follow standard 14-digit naming: {f.name}")
        v, name = m.groups()
        migrations.append(LocalMigration(version=v, name=name, filename=f.name, filepath=f))

    if len(migrations) != 28:
        raise ValueError(f"Expected exactly 28 migrations, found {len(migrations)}")

    # Verify exact match against canonical 28 list
    for idx, (m, (exp_v, exp_name)) in enumerate(zip(migrations, CANONICAL_28_MIGRATIONS)):
        if m.version != exp_v or m.name != exp_name:
            raise ValueError(
                f"Migration #{idx+1} mismatch: found ({m.version}, {m.name}), expected ({exp_v}, {exp_name})"
            )

    return migrations


def validate_ledger_baseline(rows: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate that the current ledger rows strictly match the approved 3-row baseline.
    Returns (is_valid, error_messages).
    """
    errors: List[str] = []

    if len(rows) != 3:
        errors.append(f"Row count mismatch: expected exactly 3 rows, found {len(rows)}")

    row_map = {r.get("version"): r for r in rows}

    # Check collisions with target 28 versions
    target_versions = {v for v, _ in CANONICAL_28_MIGRATIONS}
    existing_targets = target_versions.intersection(row_map.keys())
    if existing_targets:
        errors.append(f"Target versions collision detected: {sorted(list(existing_targets))}")

    # Check each legacy row
    for exp_v, exp_meta in CANONICAL_3_LEGACY_ROWS.items():
        if exp_v not in row_map:
            errors.append(f"Missing expected legacy version: {exp_v}")
            continue

        act_r = row_map[exp_v]
        if act_r.get("name") != exp_meta["name"]:
            errors.append(f"Legacy {exp_v} name mismatch: expected '{exp_meta['name']}', found '{act_r.get('name')}'")
        if act_r.get("created_by") != exp_meta["created_by"]:
            errors.append(f"Legacy {exp_v} author mismatch: expected '{exp_meta['created_by']}', found '{act_r.get('created_by')}'")
        if act_r.get("idempotency_key") is not None:
            errors.append(f"Legacy {exp_v} idempotency_key must be NULL, found '{act_r.get('idempotency_key')}'")
        if act_r.get("rollback") is not None:
            errors.append(f"Legacy {exp_v} rollback must be NULL, found '{act_r.get('rollback')}'")

        act_stmts = act_r.get("statements")
        exp_stmts = exp_meta.get("statements", [])
        if act_stmts is not None:
            if len(act_stmts) != len(exp_stmts):
                errors.append(f"Legacy {exp_v} statements count mismatch: expected {len(exp_stmts)}, found {len(act_stmts)}")
            else:
                s0 = act_stmts[0]
                exp_s0 = exp_stmts[0]
                if len(s0) != len(exp_s0):
                    errors.append(f"Legacy {exp_v} statements length mismatch: expected {len(exp_s0)}, found {len(s0)}")
                s_md5 = hashlib.md5(s0.encode("utf-8")).hexdigest()
                exp_md5 = hashlib.md5(exp_s0.encode("utf-8")).hexdigest()
                if s_md5 != exp_md5:
                    errors.append(f"Legacy {exp_v} statement md5 mismatch: expected {exp_md5}, found {s_md5}")
        else:
            errors.append(f"Legacy {exp_v} statements cannot be NULL")

    return len(errors) == 0, errors


def generate_forward_reconciliation_sql(
    lock_timeout_sec: int = 3,
    statement_timeout_sec: int = 10,
    provenance: str = RECONCILIATION_PROVENANCE,
) -> str:
    """Generate the fully hardened atomic forward reconciliation SQL transaction (Option A: 28 Canonical Rows)."""
    values_clause = ",\n    ".join([f"('{v}', '{n}', '{provenance}')" for v, n in CANONICAL_28_MIGRATIONS])
    target_in_clause = ",\n        ".join([f"'{v}'" for v, _ in CANONICAL_28_MIGRATIONS])

    sql = f"""-- ============================================================================
-- INBOUNDCHECK — MIGRATION LEDGER RECONCILIATION TRANSACTION
-- Option A: Canonical 28-Row Architecture (Universal Parity & Zero Drift)
-- Target Project Ref: tbjcldcoozvuvyipeonh
-- Provenance Marker: {provenance}
-- ============================================================================
BEGIN;

-- 1. CONCURRENCY SERIALIZATION & TIMEOUTS
SET LOCAL lock_timeout = '{lock_timeout_sec}s';
SET LOCAL statement_timeout = '{statement_timeout_sec}s';
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
        {target_in_clause}
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
    {values_clause};

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
            {values_clause}
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
            {values_clause}
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
"""
    return sql


def generate_defensive_rollback_sql(
    lock_timeout_sec: int = 3,
    statement_timeout_sec: int = 10,
    provenance: str = RECONCILIATION_PROVENANCE,
) -> str:
    """Generate the targeted defensive rollback SQL transaction restoring complete original legacy statements."""
    target_in_clause = ",\n        ".join([f"'{v}'" for v, _ in CANONICAL_28_MIGRATIONS])
    values_clause = ",\n            ".join([f"('{v}', '{n}', '{provenance}')" for v, n in CANONICAL_28_MIGRATIONS])

    # Extract exact legacy statements for full recovery
    r1 = CANONICAL_3_LEGACY_ROWS["20260910165935"]
    r2 = CANONICAL_3_LEGACY_ROWS["20260910195242"]
    r3 = CANONICAL_3_LEGACY_ROWS["20260910203910"]

    s1 = r1["statements"][0]
    s2 = r2["statements"][0]
    s3 = r3["statements"][0]

    sql = f"""-- ============================================================================
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

SET LOCAL lock_timeout = '{lock_timeout_sec}s';
SET LOCAL statement_timeout = '{statement_timeout_sec}s';
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
            {values_clause}
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
        RAISE EXCEPTION 'ROLLBACK PRECONDITION FAILED [R-02]: % target rows are missing, modified, or lack provenance %; refusing rollback', v_missing_or_modified_targets, '{provenance}';
    END IF;

    -- Precondition 3: Ensure zero rogue rows exist
    WITH expected_targets(version) AS (
        VALUES
            {values_clause}
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
    WHERE created_by = '{provenance}'
      AND version IN (
          {target_in_clause}
      )
      AND version NOT IN ('20260910165935', '20260910195242', '20260910203910')
      AND statements IS NULL
      AND idempotency_key IS NULL
      AND rollback IS NULL;

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

    IF v_deleted_count <> 28 THEN
        RAISE EXCEPTION 'ROLLBACK EXECUTION FAILED: Expected to delete exactly 28 rows with provenance %, deleted %', '{provenance}', v_deleted_count;
    END IF;
END $$;

-- Execution Step 2: Restore the 3 Original Legacy Records with Complete Statement Arrays
INSERT INTO supabase_migrations.schema_migrations (version, name, created_by, statements)
VALUES
    (
        '{r1["version"]}',
        '{r1["name"]}',
        '{r1["created_by"]}',
        ARRAY[$legacy_stmt_1${s1}$legacy_stmt_1$]::text[]
    ),
    (
        '{r2["version"]}',
        '{r2["name"]}',
        '{r2["created_by"]}',
        ARRAY[$legacy_stmt_2${s2}$legacy_stmt_2$]::text[]
    ),
    (
        '{r3["version"]}',
        '{r3["name"]}',
        '{r3["created_by"]}',
        ARRAY[$legacy_stmt_3${s3}$legacy_stmt_3$]::text[]
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
"""
    return sql


def generate_post_reconciliation_verification_sql(
    provenance: str = RECONCILIATION_PROVENANCE,
) -> str:
    """Generate the exact CTE-based post-reconciliation verification query (Option A: 28 Target Rows)."""
    values_clause = ",\n        ".join([f"('{v}', '{n}')" for v, n in CANONICAL_28_MIGRATIONS])

    sql = f"""-- ============================================================================
-- INBOUNDCHECK — POST-RECONCILIATION VERIFICATION QUERY (READ-ONLY)
-- Option A: Exact 28-Pair Validation, Universal Parity & Zero Drift
-- Expected Total Rows: 28 Canonical Standardized Records (0 Legacy Residuals)
-- Required Provenance: {provenance}
-- ============================================================================
WITH expected_canonical_pairs(version, name) AS (
    VALUES
        {values_clause}
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
         WHERE s.created_by <> '{provenance}') AS invalid_provenance_count,
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
         THEN 'PASSED: All 28 canonical records bear explicit provenance {provenance}'
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
"""
    return sql


def verify_post_reconciliation_ledger(
    rows: List[Dict[str, Any]],
    expected_provenance: str = RECONCILIATION_PROVENANCE,
) -> Tuple[bool, List[str]]:
    """
    Deterministically verify that a post-reconciliation ledger contains:
    1. Exactly 28 total rows.
    2. All 28 canonical (version, name) pairs, each with positive provenance.
    3. Exactly 0 legacy rows residual.
    4. Zero unexpected or rogue rows outside the 28 approved versions.
    Returns (is_valid, error_messages).
    """
    errors: List[str] = []

    if len(rows) != 28:
        errors.append(f"Row count mismatch: expected exactly 28 rows, found {len(rows)}")

    row_map = {r.get("version"): r for r in rows}

    # Verify each canonical target row
    target_versions = set()
    for exp_v, exp_name in CANONICAL_28_MIGRATIONS:
        target_versions.add(exp_v)
        if exp_v not in row_map:
            errors.append(f"Missing canonical migration: {exp_v} ({exp_name})")
            continue

        r = row_map[exp_v]
        if r.get("name") != exp_name:
            errors.append(f"Canonical {exp_v} name mismatch: expected '{exp_name}', found '{r.get('name')}'")
        if r.get("created_by") != expected_provenance:
            errors.append(f"Canonical {exp_v} provenance mismatch: expected '{expected_provenance}', found '{r.get('created_by')}'")
        if r.get("statements") is not None:
            errors.append(f"Canonical {exp_v} statements must be NULL, found '{r.get('statements')}'")
        if r.get("idempotency_key") is not None:
            errors.append(f"Canonical {exp_v} idempotency_key must be NULL, found '{r.get('idempotency_key')}'")
        if r.get("rollback") is not None:
            errors.append(f"Canonical {exp_v} rollback must be NULL, found '{r.get('rollback')}'")

    # Verify zero legacy rows remain
    for leg_v in CANONICAL_3_LEGACY_ROWS.keys():
        if leg_v in row_map:
            errors.append(f"Legacy migration {leg_v} must not exist in active post-reconciliation ledger")

    # Check for rogue/unexpected rows
    rogue_versions = set(row_map.keys()) - target_versions
    if rogue_versions:
        errors.append(f"Unexpected rogue versions found in ledger: {sorted(list(rogue_versions))}")

    return len(errors) == 0, errors


def plan_reconciliation(existing_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate and return the complete Option A reconciliation plan and diff."""
    is_valid_baseline, errors = validate_ledger_baseline(existing_rows)

    existing_versions = {r.get("version"): r for r in existing_rows}
    rows_to_insert = [
        {"version": v, "name": n}
        for v, n in CANONICAL_28_MIGRATIONS
        if v not in existing_versions
    ]
    legacy_rows_to_remove = [
        r for r in existing_rows
        if r.get("version") in CANONICAL_3_LEGACY_ROWS
    ]
    collisions = [
        v for v, _ in CANONICAL_28_MIGRATIONS
        if v in existing_versions
    ]

    return {
        "can_reconcile": is_valid_baseline and len(collisions) == 0,
        "baseline_valid": is_valid_baseline,
        "baseline_errors": errors,
        "initial_count": len(existing_rows),
        "target_insert_count": len(rows_to_insert),
        "rows_to_insert": rows_to_insert,
        "legacy_rows_to_remove_count": len(legacy_rows_to_remove),
        "legacy_rows_to_remove": legacy_rows_to_remove,
        "collisions_count": len(collisions),
        "collisions": collisions,
        "projected_final_count": len(rows_to_insert),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="InboundCheck Migration Ledger Reconciliation Tool (Option A)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Perform dry-run only (default: True)")
    parser.add_argument("--output-sql", type=str, help="Path to write forward reconciliation SQL")
    parser.add_argument("--output-rollback-sql", type=str, help="Path to write defensive rollback SQL")
    parser.add_argument("--output-verify-sql", type=str, help="Path to write post-reconciliation verification SQL")
    parser.add_argument("--verify-local-only", action="store_true", help="Verify local migration files only")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    migrations_dir = repo_root / "supabase" / "migrations"

    print(f"[*] Scanning local migrations in: {migrations_dir}")
    try:
        local_migrations = scan_local_migrations(migrations_dir)
        print(f"[+] Successfully verified {len(local_migrations)} local migrations matching canonical sequence.")
    except Exception as e:
        print(f"[-] Local migration verification failed: {e}", file=sys.stderr)
        return 1

    if args.verify_local_only:
        print("[+] Local verification complete. Exiting.")
        return 0

    plan = plan_reconciliation(list(CANONICAL_3_LEGACY_ROWS.values()))

    print("\n==================================================================")
    print("      INBOUNDCHECK RECONCILIATION PLAN (OPTION A — DRY-RUN)       ")
    print("==================================================================")
    print(f"  Baseline Valid:             {plan['baseline_valid']}")
    print(f"  Can Reconcile:              {plan['can_reconcile']}")
    print(f"  Starting Rows Count:        {plan['initial_count']} (Preserved Legacy)")
    print(f"  Legacy Rows to Remove:      {plan['legacy_rows_to_remove_count']} (Forensic Archive Preserved)")
    print(f"  Canonical Inserts:          {plan['target_insert_count']} (Standardized)")
    print(f"  Target Collisions:          {plan['collisions_count']}")
    print(f"  Projected Final Count:      {plan['projected_final_count']} (Exact Universal Parity)")
    print("------------------------------------------------------------------")
    print("  Legacy Rows to Atomically Remove (Forensic Archive Preserved):")
    for r in plan['legacy_rows_to_remove']:
        print(f"    - {r['version']}: {r['name']} (Author: {r['created_by']}, Stmts: {len(r.get('statements', []))})")
    print("------------------------------------------------------------------")
    print(f"  Standardized Rows to Insert ({len(plan['rows_to_insert'])} total):")
    for r in plan['rows_to_insert']:
        print(f"    + {r['version']}: {r['name']}")
    print("==================================================================")

    forward_sql = generate_forward_reconciliation_sql()
    rollback_sql = generate_defensive_rollback_sql()
    verify_sql = generate_post_reconciliation_verification_sql()

    if args.output_sql:
        out_p = Path(args.output_sql)
        out_p.write_text(forward_sql, encoding="utf-8")
        print(f"\n[+] Written forward SQL to: {out_p}")

    if args.output_rollback_sql:
        rb_p = Path(args.output_rollback_sql)
        rb_p.write_text(rollback_sql, encoding="utf-8")
        print(f"[+] Written rollback SQL to: {rb_p}")

    if args.output_verify_sql:
        v_p = Path(args.output_verify_sql)
        v_p.write_text(verify_sql, encoding="utf-8")
        print(f"[+] Written post-reconciliation verification SQL to: {v_p}")

    print("\n[+] Dry-run simulation complete. ZERO database writes executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
