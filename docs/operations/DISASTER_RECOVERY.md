# INBOUNDCHECK — DISASTER RECOVERY & BACKUP AUDIT

**Document Version:** 1.0 (Phase 2 Reliability & Continuity)  
**Governing Standard:** Realistic Resilience & Zero False Continuity Claims  
**Target Platform:** InboundCheck (Supabase PostgreSQL, Docker Deployments, Configuration Vaults)  
**Date:** 2026-09-23  

---

## 1. Executive Summary & Verification Notice

In accordance with strict operational integrity guidelines, **this document does not claim backups or restoration capabilities unless directly verified in the codebase and infrastructure configuration**. 

InboundCheck utilizes a managed Supabase PostgreSQL instance for production persistence and Docker container images for compute. The recovery parameters below distinguish between features enforced by code and those dependent on external cloud tier provisioning.

---

## 2. Disaster Recovery Parameters (RPO / RTO)

| Metric | Measured Status | Governing Factor |
|---|:---:|---|
| **Recovery Point Objective (RPO)** | **NOT VERIFIED** (Tier Dependent) | Free / Pro Supabase tiers offer daily physical backups (RPO ~24 hours). Point-in-Time Recovery (PITR, RPO ~2 minutes) requires Supabase Pro with PITR add-on enabled. Production tier must be confirmed in Supabase dashboard. |
| **Recovery Time Objective (RTO)** | **NOT VERIFIED** | Restoring from daily snapshot or replay requires manual intervention via Supabase CLI or management dashboard. Estimated 30–60 minutes depending on database volume. |

---

## 3. Database Backup Sources & Retention

| Backup Tier | Mechanism | Retention Period | Verification Status | Notes |
|---|---|---|:---:|---|
| **Supabase Daily Snapshot** | Managed PostgreSQL physical snapshots | 7 days (Free) / 30 days (Pro) | **ASSUMED MANAGED** | Handled natively by Supabase infrastructure; verify schedule in Supabase Project Settings. |
| **Supabase Point-in-Time Recovery (PITR)** | Write-Ahead Log (WAL) continuous archiving | Up to 7 days | **NOT VERIFIED** (Requires paid Supabase add-on) | Allows restoring state to any specified minute prior to an incident. |
| **Schema Migration History** | Versioned SQL files in `supabase/migrations/` | Perpetual in Git repository | **VERIFIED** | 17 idempotent migration scripts starting from initial schema to Migration 017 (`20260924000001_p0_security_hardening.sql`). |
| **In-Memory Buffer State** | Ephemeral process dictionaries | Lost on container restart | **VERIFIED BY DESIGN** | In production (`ENVIRONMENT="production"`), in-memory fallback is disabled. No business data is accepted into memory when DB is down. |

---

## 4. Restoration Procedure (Step-by-Step Runbook)

### 4.1 Schema Reconstruction on Clean Database
If a complete database loss occurs, a fresh Supabase or vanilla PostgreSQL 15+ database can be restored to the current schema using the migration chain:
```bash
# 1. Link to new project
supabase link --project-ref <new-project-ref>

# 2. Push all sequential migrations
supabase db push
```

### 4.2 Restoring from Supabase Backup Snapshot
1. Navigate to **Supabase Dashboard** -> Project -> **Database** -> **Backups**.
2. Select the latest clean snapshot taken prior to data corruption or incident.
3. Click **Restore**. Note: Database will be briefly unavailable during restoration.
4. Verify schema integrity and verify that `profiles`, `monitored_domains`, and `shopify_stores` tables contain valid row counts.
5. Re-run backend test suite against the restored instance to confirm connectivity:
   ```bash
   py -m pytest tests/test_p0_security_remediation.py
   ```

### 4.3 Credential & Secret Recovery
* **Shopify Store Access Tokens:** Encrypted at rest via Fernet in `public.shopify_stores.access_token_encrypted`. Key is derived from `SHOPIFY_API_SECRET` or `SUPABASE_JWT_SECRET`. If server secrets are lost, existing encrypted tokens cannot be decrypted; merchants will be prompted to re-authorize via Shopify OAuth.
* **DNS Provider Tokens:** Future per-tenant Cloudflare tokens will be similarly protected in `dns_provider_credentials`.
* **Stripe Subscriptions:** Stripe remains the source of truth for customer subscriptions. In the event of catastrophic data loss, subscriptions can be reconciled by querying Stripe Customer and Subscription APIs via customer email.

---

## 5. Known Gaps & Action Items Before Production

1. **Verify Supabase PITR Subscription:** Confirm whether production project has Point-in-Time Recovery (PITR) enabled. If not enabled, RPO remains bounded by the 24-hour daily backup snapshot window.
2. **Automate Scheduled Offsite Backups:** Implement a daily `pg_dump` cron workflow piping encrypted database backups to an isolated S3/GCS bucket to prevent reliance on a single cloud vendor.
3. **Validate Disaster Dry-Run:** Schedule a quarterly staging drill restoring a snapshot to a secondary test project to empirically measure RTO.
