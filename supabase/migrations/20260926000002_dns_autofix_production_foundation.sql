-- InboundCheck Migration: 20260926000002_dns_autofix_production_foundation.sql
-- ==============================================================================
-- Production-grade foundation for 1-Click DNS Auto-Fixer:
-- 1. Credential lifecycle (revocation, usage tracking, metadata)
-- 2. Complete mutation & rollback lifecycle states (PLANNED -> VERIFIED / ROLLED_BACK)
-- 3. Immutable pre- & post-mutation snapshots, target record tracking, idempotency
-- 4. B-Tree indexes for concurrent lock detection and fast history lookups
-- ==============================================================================

-- 1. Extend dns_provider_credentials
ALTER TABLE public.dns_provider_credentials
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- 2. Extend dns_auto_fix_logs lifecycle status constraint
ALTER TABLE public.dns_auto_fix_logs
    DROP CONSTRAINT IF EXISTS dns_auto_fix_logs_status_check;

ALTER TABLE public.dns_auto_fix_logs
    ADD CONSTRAINT dns_auto_fix_logs_status_check
    CHECK (status IN (
        'PLANNED', 'SNAPSHOTTED', 'APPLYING', 'APPLIED', 'VERIFIED', 'FAILED',
        'ROLLBACK_REQUESTED', 'ROLLING_BACK', 'ROLLED_BACK', 'ROLLBACK_FAILED',
        'applied', 'rolled_back', 'failed'
    ));

-- 3. Extend dns_auto_fix_logs audit columns
ALTER TABLE public.dns_auto_fix_logs
    ADD COLUMN IF NOT EXISTS target_record_id TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS zone_id TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS error_message TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS verification_result JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS snapshot_after JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ttl INTEGER DEFAULT 3600,
    ADD COLUMN IF NOT EXISTS fingerprint TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT DEFAULT NULL;

-- 4. Safe indexes for concurrency, idempotency, and audit trails
CREATE INDEX IF NOT EXISTS idx_dns_auto_fix_logs_idempotency
    ON public.dns_auto_fix_logs USING btree (user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dns_auto_fix_logs_active_target
    ON public.dns_auto_fix_logs USING btree (domain_name, host, record_type, status);

CREATE INDEX IF NOT EXISTS idx_dns_auto_fix_logs_fingerprint
    ON public.dns_auto_fix_logs USING btree (fingerprint);

CREATE INDEX IF NOT EXISTS idx_dns_provider_credentials_active
    ON public.dns_provider_credentials USING btree (user_id, provider_name, is_active);
