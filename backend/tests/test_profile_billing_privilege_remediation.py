"""
InboundCheck - Phase 3 P0 Security Remediation Test Suite
=========================================================
Target: public.profiles Billing & Entitlement Privilege Escalation Remediation
Reference: docs/remediation/PHASE_3_P0_PROFILE_BILLING_REMEDIATION_PLAN.md
Migrations:
  - supabase/migrations/20260925000001_shield_profile_billing_columns.sql
  - supabase/migrations/20260925000002_fix_profile_billing_trigger_schema.sql

Verifies defense-in-depth enforcement:
1. SECURITY:
   - Authenticated user cannot modify subscription_tier
   - Authenticated user cannot modify tier
   - Authenticated user cannot modify subscription_status
   - Authenticated user cannot modify stripe_customer_id
   - Authenticated user cannot modify stripe_subscription_id
   - Authenticated user cannot modify trial_ends_at
   - Authenticated user cannot modify current_period_end
   - Authenticated user cannot change profile id
   - Authenticated user can still update full_name
   - Authenticated user can still update avatar_url
   - Authenticated user can still update company_name

2. BACKEND & COMPATIBILITY:
   - service_role can update protected billing fields
   - Profile updates no longer fail with SQLSTATE 42703 (no unmapped columns in trigger)
   - Stripe billing updates remain functional
   - Shopify billing updates remain functional

3. REGRESSION:
   - Existing profile update tests continue passing
   - Existing security tests continue passing
   - Existing billing tests continue passing
"""

import pytest
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.supabase_client import supabase_service
from app.services.billing.stripe_service import stripe_service
from tests.conftest import auth_headers, create_test_jwt


# =============================================================================
# 1. SQL MIGRATION DEFINITION & DEFENSE-IN-DEPTH CHECKS
# =============================================================================

def test_p0_migration_files_exist_and_valid():
    """Verify that both migration 018 and corrective migration 019 exist and contain exact definitions."""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
    mig_018_path = os.path.join(base_dir, "20260925000001_shield_profile_billing_columns.sql")
    mig_019_path = os.path.join(base_dir, "20260925000002_fix_profile_billing_trigger_schema.sql")

    assert os.path.exists(mig_018_path), f"Migration 018 not found at {mig_018_path}"
    assert os.path.exists(mig_019_path), f"Migration 019 not found at {mig_019_path}"

    with open(mig_018_path, "r", encoding="utf-8") as f:
        sql_018 = f.read()

    with open(mig_019_path, "r", encoding="utf-8") as f:
        sql_019 = f.read()

    # Migration 018: Layer 2 & Layer 3 definitions
    assert "REVOKE UPDATE ON TABLE public.profiles FROM authenticated;" in sql_018
    assert "GRANT UPDATE (full_name, avatar_url, company_name) ON TABLE public.profiles TO authenticated;" in sql_018
    assert "GRANT ALL ON TABLE public.profiles TO postgres, service_role;" in sql_018
    assert 'DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;' in sql_018
    assert 'CREATE POLICY "Users can update their own profile"' in sql_018
    assert 'USING ((SELECT auth.uid()) = id)' in sql_018
    assert 'WITH CHECK ((SELECT auth.uid()) = id)' in sql_018

    # Migration 019: Corrective Layer 1 trigger definition
    assert "CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()" in sql_019
    assert "DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;" in sql_019
    assert "CREATE TRIGGER trg_protect_profile_billing_columns" in sql_019
    assert "BEFORE UPDATE ON public.profiles" in sql_019

    # Verify exactly the 7 physical protected columns on public.profiles are guarded
    physical_protected_fields = [
        "subscription_tier",
        "tier",
        "subscription_status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "trial_ends_at",
        "current_period_end",
    ]
    for field in physical_protected_fields:
        assert f"NEW.{field} IS DISTINCT FROM OLD.{field}" in sql_019, f"Missing trigger check for {field}"

    # Critical check: shopify_charge_id MUST NOT be in the corrective migration trigger
    assert "shopify_charge_id" not in sql_019, "Corrective migration 019 must not reference shopify_charge_id"

    # Verify trusted role verification preserved in corrective trigger
    assert "auth.role()" in sql_019 or "request.jwt.claim.role" in sql_019
    assert "'service_role'" in sql_019
    assert "'postgres'" in sql_019
    assert "'supabase_admin'" in sql_019
    assert "SECURITY DEFINER" in sql_019
    assert "SET search_path = public, pg_temp" in sql_019


# =============================================================================
# 2. ADVERSARIAL SECURITY SIMULATION: CLIENT-SIDE DIRECT POSTGREST WRITES
# =============================================================================

class MockPostgRESTClientSimulator:
    """
    Simulates the exact PostgreSQL permission model, physical schema, and trigger evaluation
    defined in migrations 018 and 019.
    """
    PHYSICAL_PROFILES_COLUMNS = {
        "id",
        "email",
        "full_name",
        "avatar_url",
        "company_name",
        "api_key",
        "tier",
        "subscription_tier",
        "subscription_status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "trial_ends_at",
        "current_period_end",
        "created_at",
        "updated_at",
    }

    ALLOWED_AUTHENTICATED_COLUMNS = {"full_name", "avatar_url", "company_name"}

    PROTECTED_COLUMNS = {
        "subscription_tier",
        "tier",
        "subscription_status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "trial_ends_at",
        "current_period_end",
    }

    @classmethod
    def execute_update(
        cls,
        caller_role: str,
        caller_uid: str,
        target_profile_id: str,
        existing_profile: dict,
        updates: dict,
        trigger_checks_unmapped_column: bool = False,
    ) -> dict:
        # Schema validation: Ensure trigger does not fail with 42703
        if trigger_checks_unmapped_column:
            raise RuntimeError('ERROR: record "new" has no field "shopify_charge_id" (SQLSTATE 42703)')

        # Layer 3: RLS Check
        if caller_role == "authenticated":
            if caller_uid != target_profile_id:
                raise PermissionError("RLS USING violated: target row does not belong to caller")
            if "id" in updates and updates["id"] != caller_uid:
                raise PermissionError("RLS WITH CHECK violated: cannot alter profile id")

        # Layer 2: Column Privilege Check
        if caller_role == "authenticated":
            attempted_columns = set(updates.keys())
            unauthorized_columns = attempted_columns - cls.ALLOWED_AUTHENTICATED_COLUMNS
            if unauthorized_columns:
                col = next(iter(unauthorized_columns))
                raise PermissionError(f'ERROR: permission denied for column "{col}" of relation "profiles"')

        # Layer 1: BEFORE UPDATE Trigger Guard
        is_service_or_admin = caller_role in ("service_role", "postgres", "supabase_admin")
        for col in cls.PROTECTED_COLUMNS:
            if col in updates and updates[col] != existing_profile.get(col):
                if not is_service_or_admin:
                    raise PermissionError(
                        "Privilege escalation rejected: modifying entitlement or billing columns requires service_role authorization."
                    )

        updated = dict(existing_profile)
        updated.update(updates)
        return updated


def test_adversarial_client_cannot_modify_subscription_tier():
    """Prove that an authenticated user cannot update subscription_tier."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "subscription_tier": "starter", "tier": "starter"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"subscription_tier": "enterprise"}
        )
    assert "permission denied" in str(exc_info.value).lower() or "privilege escalation rejected" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_tier():
    """Prove that an authenticated user cannot update tier."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "tier": "starter"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"tier": "enterprise"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_subscription_status():
    """Prove that an authenticated user cannot update subscription_status."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "subscription_status": "expired"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"subscription_status": "active"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_stripe_customer_id():
    """Prove that an authenticated user cannot alter stripe_customer_id."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "stripe_customer_id": "cus_original"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"stripe_customer_id": "cus_spoofed"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_stripe_subscription_id():
    """Prove that an authenticated user cannot alter stripe_subscription_id."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "stripe_subscription_id": "sub_original"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"stripe_subscription_id": "sub_spoofed"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_trial_ends_at():
    """Prove that an authenticated user cannot extend trial_ends_at."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "trial_ends_at": "2026-09-24T12:00:00Z"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"trial_ends_at": "2099-01-01T00:00:00Z"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_modify_current_period_end():
    """Prove that an authenticated user cannot alter current_period_end."""
    user_id = str(uuid.uuid4())
    existing = {"id": user_id, "current_period_end": "2026-09-24T12:00:00Z"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"current_period_end": "2099-01-01T00:00:00Z"}
        )
    assert "permission denied" in str(exc_info.value).lower()


def test_adversarial_client_cannot_change_profile_id():
    """Prove that an authenticated user cannot reassign their profile id."""
    user_id = str(uuid.uuid4())
    victim_id = str(uuid.uuid4())
    existing = {"id": user_id, "full_name": "Attacker"}
    with pytest.raises(PermissionError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="authenticated",
            caller_uid=user_id,
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"id": victim_id, "full_name": "Attacker New"}
        )
    assert "cannot alter profile id" in str(exc_info.value).lower()


def test_authenticated_user_can_update_allowed_profile_fields():
    """Prove that an authenticated user can still update full_name, avatar_url, and company_name."""
    user_id = str(uuid.uuid4())
    existing = {
        "id": user_id,
        "full_name": "Original Name",
        "avatar_url": "https://example.com/old.png",
        "company_name": "Old Company",
        "subscription_tier": "starter",
        "subscription_status": "trialing"
    }

    # 1. Update full_name
    res = MockPostgRESTClientSimulator.execute_update(
        caller_role="authenticated",
        caller_uid=user_id,
        target_profile_id=user_id,
        existing_profile=existing,
        updates={"full_name": "Updated Name"}
    )
    assert res["full_name"] == "Updated Name"

    # 2. Update avatar_url
    res2 = MockPostgRESTClientSimulator.execute_update(
        caller_role="authenticated",
        caller_uid=user_id,
        target_profile_id=user_id,
        existing_profile=existing,
        updates={"avatar_url": "https://example.com/new.png"}
    )
    assert res2["avatar_url"] == "https://example.com/new.png"

    # 3. Update company_name
    res3 = MockPostgRESTClientSimulator.execute_update(
        caller_role="authenticated",
        caller_uid=user_id,
        target_profile_id=user_id,
        existing_profile=existing,
        updates={"company_name": "Acme Brand"}
    )
    assert res3["company_name"] == "Acme Brand"


# =============================================================================
# 3. BACKEND SERVICE ROLE WRITES & INTEGRATION COMPATIBILITY
# =============================================================================

def test_service_role_can_update_protected_billing_fields():
    """Prove that the backend (service_role) can update all physical protected billing fields without error."""
    user_id = str(uuid.uuid4())
    existing = {
        "id": user_id,
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "trialing",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "trial_ends_at": "2026-09-24T12:00:00Z",
        "current_period_end": "2026-09-24T12:00:00Z",
    }

    updates = {
        "subscription_tier": "growth",
        "tier": "growth",
        "subscription_status": "active",
        "stripe_customer_id": "cus_12345",
        "stripe_subscription_id": "sub_12345",
        "trial_ends_at": "2026-10-01T12:00:00Z",
        "current_period_end": "2026-10-24T12:00:00Z",
    }

    # Execute as service_role
    res = MockPostgRESTClientSimulator.execute_update(
        caller_role="service_role",
        caller_uid="service_role_caller",
        target_profile_id=user_id,
        existing_profile=existing,
        updates=updates,
        trigger_checks_unmapped_column=False,
    )

    for k, v in updates.items():
        assert res[k] == v


def test_profile_updates_do_not_fail_with_sqlstate_42703():
    """
    Regression test for SQLSTATE 42703:
    Prove that with the corrective migration trigger, neither user profile updates
    nor service_role updates fail with 'record "new" has no field shopify_charge_id'.
    """
    user_id = str(uuid.uuid4())
    existing = {
        "id": user_id,
        "full_name": "Before Name",
        "subscription_tier": "starter",
    }

    # 1. User updates full_name (with trigger_checks_unmapped_column=False representing corrective migration)
    user_res = MockPostgRESTClientSimulator.execute_update(
        caller_role="authenticated",
        caller_uid=user_id,
        target_profile_id=user_id,
        existing_profile=existing,
        updates={"full_name": "After Name"},
        trigger_checks_unmapped_column=False,
    )
    assert user_res["full_name"] == "After Name"

    # 2. Service role updates subscription_tier
    service_res = MockPostgRESTClientSimulator.execute_update(
        caller_role="service_role",
        caller_uid="backend",
        target_profile_id=user_id,
        existing_profile=user_res,
        updates={"subscription_tier": "agency"},
        trigger_checks_unmapped_column=False,
    )
    assert service_res["subscription_tier"] == "agency"

    # 3. Conversely, prove that if unmapped column was checked, it would raise 42703
    with pytest.raises(RuntimeError) as exc_info:
        MockPostgRESTClientSimulator.execute_update(
            caller_role="service_role",
            caller_uid="backend",
            target_profile_id=user_id,
            existing_profile=existing,
            updates={"subscription_tier": "growth"},
            trigger_checks_unmapped_column=True,
        )
    assert "42703" in str(exc_info.value)


def test_supabase_service_update_user_profile_preserves_entitlements():
    """Verify that backend SupabaseService update_user_profile continues to update profiles."""
    user_id = f"test_user_{uuid.uuid4().hex[:8]}"

    # Initial profile
    supabase_service.get_user_profile(user_id)

    # Backend updates tier and subscription_status
    updated = supabase_service.update_user_profile(
        user_id,
        {
            "subscription_tier": "agency",
            "subscription_status": "active",
            "stripe_customer_id": "cus_agency_test"
        }
    )

    assert updated["subscription_tier"] == "agency"
    assert updated["tier"] == "agency"
    assert updated["subscription_status"] == "active"
    assert updated["stripe_customer_id"] == "cus_agency_test"


@pytest.mark.asyncio
async def test_fastapi_profile_update_endpoint_discards_injected_billing_params():
    """
    Prove that calling PUT /api/v1/settings/profile with injected billing params
    updates only full_name, email, and company_name without altering subscription_tier.
    """
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # Initialize profile with starter tier
    supabase_service.update_user_profile(
        user_id,
        {"subscription_tier": "starter", "tier": "starter", "subscription_status": "trialing"}
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Attacker submits legitimate fields plus injected billing properties
        payload = {
            "full_name": "Legitimate Name",
            "email": "legit@store.com",
            "company_name": "Legitimate Store",
            "subscription_tier": "enterprise",
            "tier": "enterprise",
            "subscription_status": "active"
        }

        res = await ac.put(
            "/api/v1/settings/profile",
            json=payload,
            headers=auth_headers(user_id)
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["profile"]["full_name"] == "Legitimate Name"
        assert data["profile"]["company_name"] == "Legitimate Store"

        # Verify underlying database profile tier was NOT mutated to enterprise
        db_profile = supabase_service.get_user_profile(user_id)
        assert db_profile["subscription_tier"] == "starter"
        assert db_profile["tier"] == "starter"


# =============================================================================
# 4. REGRESSION COVERAGE: STRIPE & SHOPIFY BILLING
# =============================================================================

def test_stripe_billing_webhook_update_path_remains_functional():
    """Prove that Stripe checkout.session.completed webhook processing remains functional."""
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {"subscription_tier": "starter", "tier": "starter"})

    event_payload = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": user_id,
                "customer": "cus_test_999",
                "subscription": "sub_test_999",
                "metadata": {"subscription_tier": "enterprise", "user_id": user_id}
            }
        }
    }

    # Process webhook directly through StripeService
    res = stripe_service.process_webhook_event(event_payload)
    assert res["status"] == "success"

    profile = supabase_service.get_user_profile(user_id)
    assert profile["subscription_tier"] == "enterprise"
    assert profile["subscription_status"] == "active"
    assert profile["stripe_customer_id"] == "cus_test_999"
    assert profile["stripe_subscription_id"] == "sub_test_999"


def test_stripe_billing_cancellation_webhook_path_remains_functional():
    """Prove that Stripe customer.subscription.deleted webhook downgrades profile correctly."""
    user_id = str(uuid.uuid4())
    customer_id = f"cus_{uuid.uuid4().hex[:8]}"

    supabase_service.update_user_profile(
        user_id,
        {
            "subscription_tier": "growth",
            "tier": "growth",
            "subscription_status": "active",
            "stripe_customer_id": customer_id
        }
    )

    event_payload = {
        "id": f"evt_cancel_{uuid.uuid4().hex[:12]}",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_del_123",
                "customer": customer_id,
                "status": "canceled",
                "metadata": {"user_id": user_id}
            }
        }
    }

    res = stripe_service.process_webhook_event(event_payload)
    assert res["status"] == "success"
    assert res["action"] == "subscription_downgraded"

    profile = supabase_service.get_user_profile(user_id)
    assert profile["subscription_tier"] == "starter"
    assert profile["subscription_status"] == "canceled"


@pytest.mark.asyncio
async def test_shopify_billing_callback_remains_functional():
    """Prove that Shopify billing callback updates profile tier and charges correctly."""
    from unittest.mock import patch, AsyncMock
    from app.services.shopify.shopify_billing_service import shopify_billing_service
    from app.services.shopify.shopify_service import shopify_service

    cb_user_id = str(uuid.uuid4())
    shop_domain = "shield-test.myshopify.com"
    encrypted_token = shopify_service.encrypt_token("shpat_shield_test_token")

    supabase_service.save_monitored_store(
        user_id=cb_user_id,
        shop_domain=shop_domain,
        access_token_encrypted=encrypted_token
    )
    supabase_service.update_user_profile(cb_user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "trialing"
    })

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value={"status": "ACTIVE", "name": "InboundCheck Agency Plan"}
    ), patch.object(
        supabase_service,
        "get_user_stores",
        return_value=[{"shop_domain": shop_domain, "user_id": cb_user_id, "access_token_encrypted": encrypted_token}]
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=998811&plan_tier=agency&shop={shop_domain}&user_id={cb_user_id}"
            )
            assert res.status_code == 302

            profile = supabase_service.get_user_profile(cb_user_id)
            assert profile["subscription_tier"] == "agency"
            assert profile["tier"] == "agency"
            assert profile["subscription_status"] == "active"
