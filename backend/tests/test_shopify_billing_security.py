"""
InboundCheck - Adversarial Shopify Billing Security Test Suite
=============================================================
Validates remediation of P0 - Shopify Billing Enterprise Upgrade Bypass:
1. Billing verification failure never upgrades profile to Enterprise.
2. Shopify API exceptions fail closed (HTTP 400/502) and never upgrade profile.
3. Missing billing records (null node) fail closed and never upgrade profile.
4. Non-active/declined billing statuses (DECLINED, PENDING, EXPIRED) fail closed (HTTP 402).
5. Invalid/missing callback parameters fail closed.
6. Wrong merchant cannot activate another tenant's store.
7. Client cannot tamper with plan_tier query parameter to escalate to Enterprise.
8. Unverified subscription IDs fail closed.
9. Verified billing activates the correct plan tier.
10. Repeated callback is idempotent.
11. Billing exceptions return safe, opaque error details.
12. No credentials, tokens, or raw exceptions leak in responses.
"""

import pytest
import uuid
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.shopify.shopify_service import shopify_service
from app.services.shopify.shopify_billing_service import shopify_billing_service
from app.services.supabase_client import supabase_service


@pytest.fixture
def seeded_merchant():
    """Setup an isolated merchant, store, and profile for billing tests."""
    user_id = f"merchant_{uuid.uuid4().hex[:8]}"
    shop_domain = f"test-store-{uuid.uuid4().hex[:6]}.myshopify.com"
    encrypted_token = shopify_service.encrypt_token("shpat_valid_test_token_12345")

    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted=encrypted_token
    )
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing",
    })
    return {"user_id": user_id, "shop_domain": shop_domain}


# =============================================================================
# 1. Billing Verification Failures & Exceptions Do NOT Grant Enterprise
# =============================================================================

@pytest.mark.asyncio
async def test_billing_verification_failure_does_not_upgrade_to_enterprise(seeded_merchant):
    """
    CRITICAL PROOF OF P0 REMEDIATION:
    When verification fails, the profile MUST NOT be upgraded to Enterprise.
    """
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        side_effect=RuntimeError("Subscription charge verification failed")
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=99999&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            # Must fail closed with error status
            assert res.status_code == 400
            assert "verification failed" in res.json()["detail"].lower()

            # Profile MUST remain starter, NEVER enterprise
            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "starter"
            assert profile.get("subscription_status") != "active"


@pytest.mark.asyncio
async def test_shopify_api_exception_does_not_upgrade_to_enterprise(seeded_merchant):
    """When Shopify GraphQL API throws an HTTP or network exception, fail closed."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        side_effect=Exception("Shopify GraphQL service unavailable (HTTP 503)")
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=fake_charge_123&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 400

            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "starter"


@pytest.mark.asyncio
async def test_missing_billing_record_does_not_upgrade_to_enterprise(seeded_merchant):
    """When Shopify returns null node for charge_id, fail closed."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value=None
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=nonexistent_charge&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 400

            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "starter"


# =============================================================================
# 2. Billing Status Enforcement (DECLINED, PENDING, EXPIRED)
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("unapproved_status", ["DECLINED", "PENDING", "EXPIRED", "FROZEN", "CANCELLED"])
async def test_invalid_billing_status_does_not_upgrade_to_enterprise(seeded_merchant, unapproved_status):
    """If Shopify subscription status is anything other than ACTIVE or ACCEPTED, reject with 402."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value={"id": "gid://shopify/AppSubscription/123", "status": unapproved_status, "name": "InboundCheck Enterprise Plan"}
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=123&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 402
            assert "not active" in res.json()["detail"].lower()

            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "starter"


# =============================================================================
# 3. Parameter Validation & Tenant Boundary Tests
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_callback_does_not_upgrade_to_enterprise():
    """Missing or invalid callback parameters must fail closed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Missing charge_id redirects to cancel
        res_cancel = await ac.get("/api/v1/shopify/billing/callback")
        assert res_cancel.status_code == 302
        assert "checkout=cancelled" in res_cancel.headers.get("location", "")

        # Missing shop returns 400
        res_no_shop = await ac.get("/api/v1/shopify/billing/callback?charge_id=12345")
        assert res_no_shop.status_code == 400


@pytest.mark.asyncio
async def test_wrong_merchant_cannot_activate_enterprise(seeded_merchant):
    """An attacker passing an unowned shop domain must be rejected with 403."""
    attacker_id = f"attacker_{uuid.uuid4().hex[:8]}"
    shop = seeded_merchant["shop_domain"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            f"/api/v1/shopify/billing/callback?charge_id=12345&plan_tier=enterprise&shop={shop}&user_id={attacker_id}"
        )
        assert res.status_code == 403
        assert "not associated" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_store_missing_access_token_cannot_upgrade(seeded_merchant):
    """If store record lacks an encrypted access token, verification fails closed."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    # Remove access token
    stores = supabase_service.get_user_stores(user_id)
    if stores:
        stores[0]["access_token_encrypted"] = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            f"/api/v1/shopify/billing/callback?charge_id=12345&plan_tier=enterprise&shop={shop}&user_id={user_id}"
        )
        assert res.status_code == 400
        assert "not properly connected" in res.json()["detail"].lower()

        profile = supabase_service.get_user_profile(user_id)
        assert profile.get("subscription_tier") == "starter"


# =============================================================================
# 4. Plan Tier Spoofing Defense
# =============================================================================

@pytest.mark.asyncio
async def test_client_cannot_select_enterprise_tier(seeded_merchant):
    """
    CRITICAL TIER INTEGRITY TEST:
    If a merchant purchased a 'Growth' plan ($29), but passes ?plan_tier=enterprise
    in the callback query string, the system MUST enforce the verified subscription's
    plan tier ('growth') and NOT elevate them to 'enterprise'.
    """
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value={
            "id": "gid://shopify/AppSubscription/554433",
            "status": "ACTIVE",
            "name": "InboundCheck Growth Plan",
        }
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=554433&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 302
            # Redirect should indicate verified growth plan, NOT enterprise
            assert "plan=growth" in res.headers.get("location", "")

            # Database profile must be updated to growth, NOT enterprise
            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "growth"
            assert profile.get("subscription_tier") != "enterprise"


@pytest.mark.asyncio
async def test_unverified_subscription_id_cannot_activate_enterprise(seeded_merchant):
    """Arbitrary/unverified charge IDs must be rejected."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        side_effect=RuntimeError("Subscription gid://shopify/AppSubscription/fake_id not found in Shopify")
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=fake_id&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 400
            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "starter"


# =============================================================================
# 5. Legitimate Flow, Idempotency & Error Hygiene
# =============================================================================

@pytest.mark.asyncio
async def test_successful_verified_billing_activates_correct_plan(seeded_merchant):
    """A legitimately verified charge activates the subscription and redirects with success."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value={
            "id": "gid://shopify/AppSubscription/778899",
            "status": "ACTIVE",
            "name": "InboundCheck Enterprise Plan",
        }
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=778899&plan_tier=enterprise&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 302
            assert "billing=success" in res.headers.get("location", "")
            assert "plan=enterprise" in res.headers.get("location", "")

            profile = supabase_service.get_user_profile(user_id)
            assert profile.get("subscription_tier") == "enterprise"
            assert profile.get("subscription_status") == "active"
            assert profile.get("shopify_charge_id") == "778899"


@pytest.mark.asyncio
async def test_repeated_callback_is_idempotent(seeded_merchant):
    """Re-executing callback for an already active charge succeeds idempotently."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    # Pre-activate
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "growth",
        "subscription_status": "active",
        "shopify_charge_id": "charge_id_already_active",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        res = await ac.get(
            f"/api/v1/shopify/billing/callback?charge_id=charge_id_already_active&shop={shop}&user_id={user_id}"
        )
        assert res.status_code == 302
        assert "plan=growth" in res.headers.get("location", "")


@pytest.mark.asyncio
async def test_billing_exception_returns_safe_error(seeded_merchant):
    """Ensure error response does not leak internal stack traces or exception strings."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        side_effect=RuntimeError("Sensitive internal database connection failed at 10.0.0.5:5432")
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=fail_charge&shop={shop}&user_id={user_id}"
            )
            assert res.status_code == 400
            data = res.json()
            assert data["detail"] == "Shopify billing verification failed"
            assert "10.0.0.5" not in res.text
            assert "database" not in res.text.lower()


@pytest.mark.asyncio
async def test_no_sensitive_billing_data_in_error_response(seeded_merchant):
    """Ensure access tokens or secrets are never reflected in response payloads."""
    user_id = seeded_merchant["user_id"]
    shop = seeded_merchant["shop_domain"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            f"/api/v1/shopify/billing/callback?charge_id=invalid_charge&shop={shop}&user_id={user_id}"
        )
        assert "shpat_" not in res.text
        assert "secret" not in res.text.lower()
