# Phase 3 P0 Security Remediation Implementation Plan: `public.profiles` Billing & Entitlement Protection

**Document Version:** 1.0.0-PLAN
**Date:** September 24, 2026
**Author:** Principal Security Architect & Cloud Reliability Commander
**Target Migration:** `supabase/migrations/20260925000001_shield_profile_billing_columns.sql`
**Classification:** P0 Security Remediation Plan — Strict Read-Only (Plan Only, No Code/Database Changes Made)

---

## 1. Executive Summary

During the Phase 3 Product Readiness Audit, a critical **P0 privilege-escalation vulnerability** (`P3-AUD-01`) was uncovered in the InboundCheck data layer.

The PostgreSQL Row Level Security (RLS) `UPDATE` policy on `public.profiles` only filters target rows via `USING ((SELECT auth.uid()) = id)`. Because table-wide `UPDATE` privileges were granted to the `authenticated` database role without column-level restrictions or protective validation triggers, **any authenticated user can directly modify entitlement and billing columns on their own profile row via Supabase client-side API calls**. An attacker can freely self-assign `'enterprise'` tier and `'active'` status, completely bypassing Stripe and Shopify billing mechanisms.

This implementation plan details the complete, defense-in-depth engineering solution to permanently neutralize this vulnerability while ensuring 100% backward compatibility with all legitimate backend billing pipelines (Stripe webhooks, Shopify callbacks, trial expiration guards, and user profile management).

---

## 2. Confirmed Root Cause

1. **Table-Wide UPDATE Privilege Grant:**
   In [20260904000001_fix_handle_new_user_trigger.sql:108](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260904000001_fix_handle_new_user_trigger.sql#L108), the database executed:
   ```sql
   GRANT SELECT, UPDATE, INSERT ON TABLE public.profiles TO authenticated;
   ```
   In PostgreSQL, granting table-level `UPDATE` permits updating *every column* in the table unless explicitly revoked or restricted.

2. **Permissive RLS UPDATE Policy:**
   In [20260909000002_performance_and_idempotency_hardening.sql:38-41](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260909000002_performance_and_idempotency_hardening.sql#L38-L41), the RLS policy is:
   ```sql
   CREATE POLICY "Users can update their own profile"
       ON public.profiles FOR UPDATE
       USING ((SELECT auth.uid()) = id);
   ```
   PostgreSQL RLS `USING` clauses evaluate row visibility; they do not restrict which attributes can be mutated within visible rows.

3. **Absence of Validation Triggers:**
   The only trigger attached to `public.profiles` is `update_profiles_updated_at` ([20260903000001_complete_production_schema.sql:311-314](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260903000001_complete_production_schema.sql#L311-L314)), which merely updates the `updated_at` timestamp. No trigger exists to validate column mutation authorization.

---

## 3. Current RLS Behavior

Currently, when a request hits PostgREST on `PATCH /rest/v1/profiles?id=eq.<user_id>`:
1. PostgREST switches to local role `authenticated` and sets `auth.uid() = <user_id>`.
2. PostgreSQL checks RLS policy `"Users can update their own profile"`.
3. `(SELECT auth.uid()) = id` evaluates to `TRUE`.
4. PostgreSQL checks if role `authenticated` has `UPDATE` privilege on `public.profiles`. The privilege exists at the table level.
5. The update succeeds unconditionally, allowing client-driven writes to `subscription_tier`, `subscription_status`, `trial_ends_at`, and all other columns.

---

## 4. Current Table-Level & Column-Level Privileges

Inspection of active database migrations reveals the exact privilege state:

| Role | Object | Privileges | Defined In |
|---|---|---|---|
| `postgres`, `service_role` | `TABLE public.profiles` | `ALL` (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, etc.) | [20260904000001...sql:107](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260904000001_fix_handle_new_user_trigger.sql#L107) |
| `authenticated` | `TABLE public.profiles` | `SELECT`, `UPDATE`, `INSERT` (Table-Wide) | [20260904000001...sql:108](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260904000001_fix_handle_new_user_trigger.sql#L108) |
| `anon` | `TABLE public.profiles` | `NONE` (Explicitly blocked) | Default Supabase Hardening |

**Column-Level Privileges:** Currently **none**. The table-level grant gives the `authenticated` role access to every column.

---

## 5. Legitimate Backend Billing Write Paths

All legitimate writes to protected billing fields originate from server-side FastAPI code utilizing the trusted `SUPABASE_SERVICE_ROLE_KEY`:

```
[ External Webhook / Internal Trigger ]
                 │
                 ▼
[ FastAPI Backend Service (Service Role) ]
                 │
                 ├── Stripe Webhook (checkout.session.completed)  ──► writes subscription_tier, status, stripe_ids
                 ├── Stripe Webhook (customer.subscription.deleted) ──► writes subscription_tier='starter', status='canceled'
                 ├── Stripe Webhook (customer.subscription.updated) ──► writes status, subscription_tier, period_end
                 ├── Shopify Callback (/billing/callback)           ──► writes subscription_tier, status='active', shopify_charge_id
                 └── Tier Guard Expiration Check (tier_guards.py)   ──► writes status='expired'
                 │
                 ▼
[ SupabaseService.update_user_profile(user_id, updates) ]
                 │
                 ▼
[ PostgreSQL public.profiles (service_role: BYPASSRLS / Trusted) ]
```

### Exact Backend Write Locations:
1. **`app.services.supabase_client.SupabaseService.update_user_profile`** ([supabase_client.py:120-157](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/supabase_client.py#L120-L157)): Central entrypoint executing `_client.table("profiles").update(updates).eq("id", user_id).execute()`.
2. **`app.services.billing.stripe_service.StripeBillingService`** ([stripe_service.py:183, 524, 595, 620](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/services/billing/stripe_service.py)): Handles Stripe webhooks and updates `stripe_customer_id`, `stripe_subscription_id`, `subscription_tier`, and `subscription_status`.
3. **`app.api.v1.shopify`** ([shopify.py:359-363](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/shopify.py#L359-L363)): Handles Shopify App Store billing callback and updates `subscription_tier`, `subscription_status`, and `shopify_charge_id`.
4. **`app.core.tier_guards`** ([tier_guards.py:94](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/core/tier_guards.py#L94)): Evaluates trial validity and updates `subscription_status = 'expired'`.
5. **`app.api.v1.billing`** ([billing.py:61](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/backend/app/api/v1/billing.py#L61)): Updates `subscription_status = 'expired'` when billing status check detects expired trial.

---

## 6. Threat Model for Direct Authenticated Client Updates

### Adversary Profile:
- Registered end user with valid authentication credentials (email/password or OAuth session).
- Access to client browser DevTools, Postman, or custom Python/cURL scripts.
- Possesses `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and a valid Bearer JWT.

### Attack Scenarios:
1. **Paywall Bypass (Tier Escalation):**
   Target: `subscription_tier = 'enterprise'`, `tier = 'enterprise'`.
   Impact: Gain access to unlimited monitored domains, priority DNS scans, and automated DNS remediation without payment.
2. **Subscription Status Tampering:**
   Target: `subscription_status = 'active'`.
   Impact: Force an expired trial or canceled subscription back into active status, preventing feature gating.
3. **Trial Extension:**
   Target: `trial_ends_at = '2099-01-01T00:00:00Z'`.
   Impact: Permanently postpone trial expiration.
4. **Billing Link Hijacking:**
   Target: `stripe_customer_id` or `shopify_charge_id`.
   Impact: Overwrite billing identifiers, potentially attaching the profile to another customer or corrupting webhook reconciliation.

---

## 7. Exact Remediation Architecture (Defense-in-Depth)

The remediation uses a **3-Layer Defense-in-Depth Architecture**:

```
                       [ Incoming SQL UPDATE Request ]
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Layer 2: Column-Level Privilege Enforcement (SQL Parser / Planner)        │
│ - Revoke table-wide UPDATE from 'authenticated'                           │
│ - Grant UPDATE ONLY on (full_name, avatar_url, company_name)              │
│ ➔ If authenticated user attempts writing protected column:               │
│    REJECTED IMMEDIATELY WITH ERROR: permission denied for column ...      │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ (Allowed columns or service_role)
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Layer 3: RLS Policy Hardening with WITH CHECK                             │
│ - USING ((SELECT auth.uid()) = id)                                        │
│ - WITH CHECK ((SELECT auth.uid()) = id)                                   │
│ ➔ Prevents row-level tenant leakage or id tampering                       │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Layer 1: PostgreSQL BEFORE UPDATE Trigger Function (State Validation)     │
│ - protect_profile_billing_columns()                                       │
│ ➔ Inspects OLD vs NEW values for all 7 protected columns                  │
│ ➔ If values differ and caller is NOT service_role or postgres:            │
│    RAISES EXCEPTION: Privilege escalation rejected                        │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
                        [ Write Successfully Committed ]
```

---

## 8. Exact SQL Migration Design

**Proposed File:** `supabase/migrations/20260925000001_shield_profile_billing_columns.sql`

```sql
-- =====================================================================
-- Migration 018: Shield Profile Billing & Entitlement Columns (P0 Remediation)
-- Target: InboundCheck Production PostgreSQL 15 (Supabase)
-- Author: Principal Security & Cloud Architecture Specialist
-- Date: 2026-09-25
-- Purpose: Permanently prevent client-side privilege escalation on public.profiles
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. LAYER 1: BEFORE UPDATE Trigger Guard
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    -- Check if any protected billing/entitlement column is being altered
    IF (
        NEW.subscription_tier IS DISTINCT FROM OLD.subscription_tier OR
        NEW.tier IS DISTINCT FROM OLD.tier OR
        NEW.subscription_status IS DISTINCT FROM OLD.subscription_status OR
        NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id OR
        NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id OR
        NEW.shopify_charge_id IS DISTINCT FROM OLD.shopify_charge_id OR
        NEW.trial_ends_at IS DISTINCT FROM OLD.trial_ends_at
    ) THEN
        -- Allow modification ONLY if executed by service_role, postgres, or supabase_admin
        IF (
            COALESCE(auth.role(), '') != 'service_role' AND
            COALESCE(current_setting('request.jwt.claim.role', true), '') != 'service_role' AND
            current_user NOT IN ('postgres', 'supabase_admin')
        ) THEN
            RAISE EXCEPTION 'Privilege escalation rejected: modifying entitlement or billing columns requires service_role authorization.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

ALTER FUNCTION public.protect_profile_billing_columns() OWNER TO postgres;

DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;
CREATE TRIGGER trg_protect_profile_billing_columns
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.protect_profile_billing_columns();

-- ---------------------------------------------------------------------
-- 2. LAYER 2: Column-Level Privilege Restrictions
-- ---------------------------------------------------------------------

-- Revoke table-wide update privilege from regular authenticated users
REVOKE UPDATE ON TABLE public.profiles FROM authenticated;

-- Grant update privilege strictly for safe user-editable profile columns
GRANT UPDATE (full_name, avatar_url, company_name) ON TABLE public.profiles TO authenticated;

-- Ensure service_role and postgres maintain full table-wide permissions
GRANT ALL ON TABLE public.profiles TO postgres, service_role;

-- ---------------------------------------------------------------------
-- 3. LAYER 3: RLS Policy Hardening with Explicit WITH CHECK
-- ---------------------------------------------------------------------

DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING ((SELECT auth.uid()) = id)
    WITH CHECK ((SELECT auth.uid()) = id);

COMMIT;
```

---

## 9. Trigger Design & Authorization Logic Analysis

### Is the Trigger Authorization Check Safe in Supabase / PostgREST?
**Yes, 100% safe and authoritative.**

1. **How PostgREST Sets Context:**
   When PostgREST receives an HTTP request:
   - If using `SUPABASE_SERVICE_ROLE_KEY`: It runs under database role `service_role` and injects session setting `request.jwt.claim.role = 'service_role'`. In Supabase, the SQL function `auth.role()` directly evaluates `current_setting('request.jwt.claim.role', true)`.
   - If using user JWT: It runs under database role `authenticated` and injects `request.jwt.claim.role = 'authenticated'`.
2. **Dual-Check Redundancy:**
   The trigger uses both `auth.role()` and `current_setting('request.jwt.claim.role', true)` combined with `current_user`:
   ```sql
   COALESCE(auth.role(), '') != 'service_role' AND
   COALESCE(current_setting('request.jwt.claim.role', true), '') != 'service_role' AND
   current_user NOT IN ('postgres', 'supabase_admin')
   ```
   - If PostgREST calls with a user token: both evaluate to `'authenticated'`. The trigger condition matches and raises an exception.
   - If FastAPI calls with `service_role`: either evaluates to `'service_role'`. The trigger allows the write.
   - If database migrations or CLI scripts run as `postgres`: `current_user IN ('postgres', 'supabase_admin')` evaluates to `TRUE`. The trigger allows the write.
   - If `handle_new_user()` trigger runs: it is defined as `SECURITY DEFINER` owned by `postgres`, so `current_user` is `'postgres'`.

---

## 10. Column-Level GRANT / REVOKE Compatibility Analysis

### Could Column-Level Grants Break the FastAPI Backend?
**No. It is impossible for column-level grants on `authenticated` to affect the FastAPI backend.**

### Technical Proof:
1. In PostgreSQL, object permissions are evaluated against the **active role** executing the statement.
2. In Supabase, the FastAPI backend connects using `SUPABASE_SERVICE_ROLE_KEY`. PostgREST sets the active role to `service_role`.
3. The migration explicitly maintains:
   ```sql
   GRANT ALL ON TABLE public.profiles TO postgres, service_role;
   ```
   Role `service_role` possesses table-wide `UPDATE` on every single column.
4. `REVOKE UPDATE ON TABLE public.profiles FROM authenticated;` only strips privileges from the `authenticated` role (used by browser clients).
5. Therefore, `supabase_service.update_user_profile()` running on the FastAPI server continues to update all 7 protected columns without restriction.

---

## 11. RLS WITH CHECK Hardening

In the previous migration [20260909000002_performance_and_idempotency_hardening.sql:39-41](file:///c:/Users/pc/Desktop/inboundcheck%20VERSION%201/supabase/migrations/20260909000002_performance_and_idempotency_hardening.sql#L39-L41), the update policy omitted `WITH CHECK`:
```sql
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING ((SELECT auth.uid()) = id);
```
Without `WITH CHECK`:
- A client could theoretically execute `UPDATE profiles SET id = '<other_user_id>' WHERE id = auth.uid();`
- By adding `WITH CHECK ((SELECT auth.uid()) = id)`, PostgreSQL validates both the pre-state (`USING`) and post-state (`WITH CHECK`), guaranteeing that a user can never reassign profile ownership or move their record to another user ID.

---

## 12. Compatibility Analysis Across Product Flows

| Functional Flow | Write Mechanism | Role | Protected Columns Touched | Compatibility Verdict |
|---|---|---|---|---|
| **Stripe Checkout** | Webhook via `StripeBillingService` | `service_role` | `subscription_tier`, `tier`, `subscription_status`, `stripe_customer_id`, `stripe_subscription_id` | **100% Compatible.** `service_role` retains full table privileges and satisfies trigger check. |
| **Stripe Subscription Update** | Webhook via `StripeBillingService` | `service_role` | `subscription_status`, `subscription_tier`, `tier`, `current_period_end` | **100% Compatible.** `service_role` updates allowed. |
| **Stripe Cancellation** | Webhook via `StripeBillingService` | `service_role` | `subscription_tier = 'starter'`, `tier = 'starter'`, `subscription_status = 'canceled'` | **100% Compatible.** Downgrades proceed seamlessly. |
| **Shopify Billing Callback** | FastAPI `/shopify/billing/callback` | `service_role` | `subscription_tier`, `tier`, `subscription_status`, `shopify_charge_id` | **100% Compatible.** Full write access preserved. |
| **Trial Expiration Guard** | `tier_guards.py` / `billing.py` | `service_role` | `subscription_status = 'expired'` | **100% Compatible.** Automatic downgrade to expired permitted. |
| **User Settings Update** | Frontend calls `PUT /api/v1/settings/profile` | `service_role` (FastAPI backend proxy) | `full_name`, `company_name`, `email` | **100% Compatible.** Updates proceed through backend service role. |
| **Direct Browser Client Update** | `supabase.from('profiles').update()` | `authenticated` | Any of the 7 protected fields | **Blocked Fail-Closed.** Denied by column grants (Layer 2) and trigger exception (Layer 1). |
| **Direct Browser Profile Edit** | `supabase.from('profiles').update()` | `authenticated` | `full_name`, `company_name`, `avatar_url` | **Permitted.** Allowed by Layer 2 column grants and skipped by Layer 1 trigger. |

---

## 13. Test Strategy

To verify remediation without risking regressions, implement automated testing across two tiers:

1. **Integration Test Suite (`backend/tests/test_p0_security_remediation.py`):**
   - Execute tests using `supabase_service` and simulated JWT tokens.
2. **Adversarial Security Test Suite (`backend/tests/test_profile_billing_privilege_remediation.py`):**
   - Create explicit tests simulating browser client connections attempting privilege escalation.

---

## 14. Adversarial Security Test Cases

The following test cases must be added to the test suite:

### Test Case SEC-P0-01: Authenticated User Cannot Escalate Tier
- **Setup:** Authenticate a client with role `authenticated` and `auth.uid() = user_id`.
- **Action:** Execute `UPDATE public.profiles SET subscription_tier = 'enterprise' WHERE id = user_id`.
- **Expected Result:** Query fails with `permission denied for column "subscription_tier"` or trigger exception `Privilege escalation rejected`. Database column remains `'starter'`.

### Test Case SEC-P0-02: Authenticated User Cannot Extend Trial
- **Setup:** Authenticate as regular user.
- **Action:** Execute `UPDATE public.profiles SET trial_ends_at = '2099-01-01T00:00:00Z' WHERE id = user_id`.
- **Expected Result:** Query fails fail-closed. Database column retains original timestamp.

### Test Case SEC-P0-03: Authenticated User Cannot Override Subscription Status
- **Setup:** User with `subscription_status = 'expired'`.
- **Action:** Execute `UPDATE public.profiles SET subscription_status = 'active' WHERE id = user_id`.
- **Expected Result:** Query fails fail-closed. Status remains `'expired'`.

### Test Case SEC-P0-04: Authenticated User Cannot Reassign ID
- **Setup:** User A attempts to set `id = user_b_uuid`.
- **Expected Result:** Query rejected by RLS `WITH CHECK ((SELECT auth.uid()) = id)`.

---

## 15. Regression Test Cases

### Test Case REG-P0-01: Service Role Billing Updates Succeed
- **Setup:** FastAPI backend executing via `SUPABASE_SERVICE_ROLE_KEY`.
- **Action:** Call `supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})`.
- **Expected Result:** Update succeeds with HTTP 200 / database success.

### Test Case REG-P0-02: Normal User Profile Updates Continue to Work
- **Setup:** Authenticated tenant calls `PUT /api/v1/settings/profile` with `{"full_name": "Jane Doe", "company_name": "Acme Brand"}`.
- **Action:** Backend updates `public.profiles`.
- **Expected Result:** Updates committed successfully; profile response reflects new name and company.

### Test Case REG-P0-03: Stripe Webhook Pipeline Remains Functional
- **Setup:** Simulate Stripe `checkout.session.completed` webhook with HMAC signature.
- **Action:** Process webhook via `stripe_service.handle_webhook()`.
- **Expected Result:** `stripe_customer_id`, `stripe_subscription_id`, and `subscription_tier` updated correctly.

### Test Case REG-P0-04: Existing 236/236 Pytest Suite Remains 100% Green
- **Action:** Execute `py -m pytest tests/` in `backend/`.
- **Expected Result:** 236 tests pass with 0 regressions.

---

## 16. Deployment Sequence

When approved to implement:
1. **Pre-Flight Sanity Check:** Verify clean working tree on `main` branch.
2. **Author Migration File:** Write `supabase/migrations/20260925000001_shield_profile_billing_columns.sql`.
3. **Apply Migration:** Execute migration against target Supabase instance.
4. **Implement Automated Tests:** Add adversarial test suite in `backend/tests/test_profile_billing_privilege_remediation.py`.
5. **Execute Verification Gate:** Run `py -m pytest tests/` to confirm 100% passing rate.
6. **Frontend Compilation Check:** Run `npm run build` in `frontend/` to confirm 0 compilation errors.

---

## 17. Supabase Verification Procedure

Run the following SQL verification script in Supabase SQL Editor following migration:

```sql
-- 1. Verify Trigger is Attached
SELECT tgname, tgenabled, tgtype
FROM pg_trigger
WHERE tgname = 'trg_protect_profile_billing_columns';

-- 2. Verify Column-Level Permissions on public.profiles
SELECT grantee, privilege_type, column_name
FROM information_schema.column_privileges
WHERE table_name = 'profiles' AND grantee = 'authenticated';
-- Expected: Exactly 3 rows (full_name, avatar_url, company_name)

-- 3. Verify Table-Level Permissions
SELECT grantee, privilege_type
FROM information_schema.table_privileges
WHERE table_name = 'profiles' AND grantee = 'authenticated';
-- Expected: SELECT and INSERT (NO table-wide UPDATE)

-- 4. Verify RLS Policy
SELECT polname, polcmd, polqual, polwithcheck
FROM pg_policy
WHERE polrelid = 'public.profiles'::regclass AND polname = 'Users can update their own profile';
-- Expected: polqual and polwithcheck both equal ((SELECT auth.uid()) = id)
```

---

## 18. Rollback Strategy

If an unexpected production issue arises, execute the following atomic rollback SQL snippet:

```sql
BEGIN;

-- 1. Drop trigger and function
DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;
DROP FUNCTION IF EXISTS public.protect_profile_billing_columns();

-- 2. Restore table-wide UPDATE grant
GRANT UPDATE ON TABLE public.profiles TO authenticated;

-- 3. Restore original RLS update policy
DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING ((SELECT auth.uid()) = id);

COMMIT;
```

---

## 19. Risks & Edge Cases

1. **Edge Case: Migration Order During Cold Boot / Seeding**
   - *Risk:* If a seed script runs as role `authenticated` to seed test users, updates to `subscription_tier` will fail.
   - *Mitigation:* Ensure seed scripts run using `service_role` or connect as role `postgres`.
2. **Edge Case: Direct Supabase Client Calls in Legacy Frontend Branches**
   - *Risk:* If older frontend code called `supabase.from('profiles').update({ email: '...' })`, it would fail under column grants.
   - *Verification:* Code audit confirmed that `frontend/src/` contains 0 direct updates to `profiles`. All edits route through `/api/v1/settings/profile`.
3. **Edge Case: Multiple Schema Search Paths**
   - *Risk:* Function definition resolution.
   - *Mitigation:* Explicit `SET search_path = public, pg_temp` is set on the trigger function to prevent search path hijacking.

---

## 20. Definition of Done

- [ ] Migration `20260925000001_shield_profile_billing_columns.sql` is authored and committed.
- [ ] Layer 1 (Trigger), Layer 2 (Column Grants), and Layer 3 (RLS `WITH CHECK`) are applied to Supabase.
- [ ] Direct updates to `subscription_tier`, `tier`, `subscription_status`, `stripe_customer_id`, `stripe_subscription_id`, `shopify_charge_id`, and `trial_ends_at` by `authenticated` clients fail closed.
- [ ] Updates to `full_name`, `avatar_url`, and `company_name` by `authenticated` clients succeed.
- [ ] All backend service role writes (Stripe, Shopify, tier guards) succeed with 0 regressions.
- [ ] Full backend pytest suite passes with 100% of tests green (236+ tests).
- [ ] Frontend compiles with `npm run build` with 0 TypeScript/Webpack errors.

---

## IMPLEMENTATION STATUS: PLAN ONLY — NO CHANGES MADE
*(Strict read-only phase completed. No application code, schemas, or migrations have been modified.)*
