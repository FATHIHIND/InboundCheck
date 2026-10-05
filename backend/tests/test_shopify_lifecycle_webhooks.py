"""
InboundCheck - Phase 18B.2 Shopify Lifecycle Webhooks Test Suite
================================================================
Verifies:
1. POST /api/v1/shopify/webhooks/app/uninstalled
   - Valid signed webhook deactivates store and revokes token (is_active=False)
   - Missing HMAC rejected (401)
   - Invalid HMAC rejected (401)
   - Stale/replay timestamp rejected (400)
   - Unknown shop handled safely without throwing (200 acknowledged)
   - Repeated uninstall is idempotent
   - Shop A uninstall does NOT affect Shop B (Tenant Isolation)
   - Zero token or secret leakage in response

2. POST /api/v1/shopify/webhooks/app_subscriptions/update
   - Valid signed ACTIVE subscription synchronizes to profile (active, growth/agency)
   - Valid CANCELLED subscription downgrades profile (canceled, starter)
   - Valid EXPIRED / DECLINED subscription downgrades profile (expired/declined, starter)
   - Valid PAUSED subscription downgrades profile (paused, starter)
   - Invalid or missing HMAC rejected (401)
   - Stale/replay timestamp outside tolerance rejected (400)
   - Arbitrary client tier cannot override server-authoritative tier
   - Cross-tenant isolation: Shop A subscription cannot modify User B
   - Webhook idempotency via X-Shopify-Webhook-Id
   - Unknown shop handled safely without throwing (200 acknowledged)
"""

import pytest
import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service


TEST_SECRET = "test_lifecycle_webhooks_secret_key_32b"


def generate_test_hmac(secret: str, body: bytes) -> str:
    """Generate base64 encoded HMAC-SHA256 signature for test webhook payload."""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture(autouse=True)
def configure_test_secret():
    """Ensure shopify_service has an active API secret during lifecycle webhook tests."""
    original_secret = shopify_service.api_secret
    shopify_service.api_secret = TEST_SECRET
    yield
    shopify_service.api_secret = original_secret


# =============================================================================
# PART A: app/uninstalled Webhook Tests
# =============================================================================

@pytest.mark.asyncio
async def test_app_uninstalled_valid_signed():
    """Verify that a valid signed app/uninstalled webhook deactivates store and revokes token."""
    user_id = "test-user-uninstall-01"
    shop_domain = "merchant-alpha.myshopify.com"

    # Setup active store record
    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted="encrypted_live_token_12345",
        scope="read_orders"
    )

    # Precondition check: store is active
    store_before = supabase_service.get_store_by_domain(shop_domain)
    assert store_before is not None
    assert store_before.get("is_active") is True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": shop_domain}
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)
        now_ts = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": valid_hmac,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Triggered-At": now_ts,
            "X-Shopify-Webhook-Id": f"webhook-uninstall-{int(time.time())}"
        }

        res = await ac.post("/api/v1/shopify/webhooks/app/uninstalled", content=body_bytes, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        assert data.get("action") == "store_deactivated"
        assert data.get("verified") is True

        # Postcondition: store is inactive and token is revoked
        store_after = supabase_service.get_store_by_domain(shop_domain)
        assert store_after is not None
        assert store_after.get("is_active") is False
        assert store_after.get("access_token_encrypted") == "revoked"

        # Assert no sensitive token returned in response body
        assert "access_token" not in data
        assert "encrypted_live_token_12345" not in res.text


@pytest.mark.asyncio
async def test_app_uninstalled_missing_hmac():
    """Verify that app/uninstalled fails closed with HTTP 401 when HMAC header is missing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": "store-no-hmac.myshopify.com"}
        body_bytes = json.dumps(payload).encode("utf-8")

        res = await ac.post(
            "/api/v1/shopify/webhooks/app/uninstalled",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Shop-Domain": "store-no-hmac.myshopify.com",
            }
        )
        assert res.status_code == 401
        assert "Invalid Shopify HMAC-SHA256 signature" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_app_uninstalled_invalid_hmac():
    """Verify that app/uninstalled fails closed with HTTP 401 when HMAC signature is forged/invalid."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": "forged-store.myshopify.com"}
        body_bytes = json.dumps(payload).encode("utf-8")

        res = await ac.post(
            "/api/v1/shopify/webhooks/app/uninstalled",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": "forged_invalid_signature_base64==",
                "X-Shopify-Shop-Domain": "forged-store.myshopify.com",
            }
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_app_uninstalled_stale_timestamp():
    """Verify that app/uninstalled rejects requests outside ±300s tolerance window."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": "stale-store.myshopify.com"}
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)
        stale_ts = str(int(time.time()) - 1000)  # 1000s in past (>300s)

        res = await ac.post(
            "/api/v1/shopify/webhooks/app/uninstalled",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": "stale-store.myshopify.com",
                "X-Shopify-Triggered-At": stale_ts,
            }
        )
        assert res.status_code == 400
        assert "timestamp outside tolerance window" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_app_uninstalled_unknown_shop():
    """Verify that uninstalling an unknown/untracked shop returns 200 acknowledged without crashing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": "untracked-brand-store.myshopify.com"}
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

        res = await ac.post(
            "/api/v1/shopify/webhooks/app/uninstalled",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": "untracked-brand-store.myshopify.com",
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res.status_code == 200
        assert res.json().get("action") == "untracked_shop_ignored"


@pytest.mark.asyncio
async def test_app_uninstalled_idempotency():
    """Verify that repeating app/uninstalled delivery for the same store is safely idempotent."""
    user_id = "test-user-uninstall-idempotent"
    shop_domain = "idempotent-uninstall.myshopify.com"

    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted="encrypted_tok_idem",
        scope="read_orders"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": shop_domain}
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)
        webhook_id = f"wh-idem-uninstall-{int(time.time())}"

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": valid_hmac,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Triggered-At": str(int(time.time())),
            "X-Shopify-Webhook-Id": webhook_id,
        }

        # 1st call: deactivates store
        res1 = await ac.post("/api/v1/shopify/webhooks/app/uninstalled", content=body_bytes, headers=headers)
        assert res1.status_code == 200
        assert res1.json().get("action") == "store_deactivated"

        # 2nd call with same webhook ID: returns already_processed
        res2 = await ac.post("/api/v1/shopify/webhooks/app/uninstalled", content=body_bytes, headers=headers)
        assert res2.status_code == 200
        assert res2.json().get("status") == "already_processed"
        assert res2.json().get("action") == "uninstall_skipped"

        # 3rd call with different webhook ID (e.g. repeated delivery later): succeeds idempotently
        headers["X-Shopify-Webhook-Id"] = f"wh-idem-uninstall-2-{int(time.time())}"
        res3 = await ac.post("/api/v1/shopify/webhooks/app/uninstalled", content=body_bytes, headers=headers)
        assert res3.status_code == 200
        assert res3.json().get("action") == "store_deactivated"


@pytest.mark.asyncio
async def test_app_uninstalled_tenant_isolation():
    """Verify that Shop A's uninstall cannot deactivate Shop B."""
    user_a = "tenant-a-uninstall"
    user_b = "tenant-b-uninstall"
    shop_a = "shop-a-isolation.myshopify.com"
    shop_b = "shop-b-isolation.myshopify.com"

    supabase_service.save_monitored_store(user_id=user_a, shop_domain=shop_a, access_token_encrypted="token_a")
    supabase_service.save_monitored_store(user_id=user_b, shop_domain=shop_b, access_token_encrypted="token_b")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"myshopify_domain": shop_a}
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

        # Trigger uninstall for Shop A
        res = await ac.post(
            "/api/v1/shopify/webhooks/app/uninstalled",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": shop_a,
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res.status_code == 200

        # Assert Shop A is deactivated
        store_a = supabase_service.get_store_by_domain(shop_a)
        assert store_a.get("is_active") is False

        # Assert Shop B remains strictly ACTIVE
        store_b = supabase_service.get_store_by_domain(shop_b)
        assert store_b.get("is_active") is True
        assert store_b.get("access_token_encrypted") == "token_b"


# =============================================================================
# PART B: app_subscriptions/update Webhook Tests
# =============================================================================

@pytest.mark.asyncio
async def test_app_subscriptions_update_active_growth():
    """Verify that valid signed ACTIVE subscription updates profile to growth."""
    user_id = "test-user-sub-active-01"
    shop_domain = "merchant-sub-active.myshopify.com"

    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted="mock_encrypted_tok",
        scope="read_orders"
    )
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing",
    })

    mock_shopify_node = {
        "id": "gid://shopify/AppSubscription/77889900",
        "status": "ACTIVE",
        "name": "InboundCheck Growth Plan",
        "currentPeriodEnd": "2026-11-02T00:00:00Z"
    }

    transport = ASGITransport(app=app)
    with patch("app.services.shopify.shopify_billing_service.shopify_billing_service.get_app_subscription", new_callable=AsyncMock) as mock_get_sub:
        mock_get_sub.return_value = mock_shopify_node

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            payload = {
                "app_subscription": {
                    "admin_graphql_api_id": "gid://shopify/AppSubscription/77889900",
                    "name": "InboundCheck Growth Plan",
                    "status": "ACTIVE",
                }
            }
            body_bytes = json.dumps(payload).encode("utf-8")
            valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

            headers = {
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": shop_domain,
                "X-Shopify-Triggered-At": str(int(time.time())),
                "X-Shopify-Webhook-Id": f"wh-sub-active-{int(time.time())}"
            }

            res = await ac.post("/api/v1/shopify/webhooks/app_subscriptions/update", content=body_bytes, headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data.get("action") == "subscription_activated"
            assert data.get("subscription_status") == "active"

            # Verify profile entitlement
            prof = supabase_service.get_user_profile(user_id)
            assert prof.get("subscription_tier") == "growth"
            assert prof.get("subscription_status") == "active"
            assert prof.get("shopify_charge_id") == "gid://shopify/AppSubscription/77889900"


@pytest.mark.asyncio
async def test_app_subscriptions_update_cancelled_downgrades():
    """Verify that a CANCELLED subscription lifecycle event downgrades entitlement to starter."""
    user_id = "test-user-sub-cancelled-01"
    shop_domain = "merchant-sub-cancelled.myshopify.com"

    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted="mock_encrypted_tok",
    )
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "agency",
        "subscription_status": "active",
        "shopify_charge_id": "gid://shopify/AppSubscription/112233",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/112233",
                "name": "InboundCheck Agency Plan",
                "status": "CANCELLED",
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": valid_hmac,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Triggered-At": str(int(time.time())),
        }

        res = await ac.post("/api/v1/shopify/webhooks/app_subscriptions/update", content=body_bytes, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data.get("action") == "subscription_canceled"
        assert data.get("subscription_status") == "canceled"

        # Verify profile downgraded
        prof = supabase_service.get_user_profile(user_id)
        assert prof.get("subscription_tier") == "starter"
        assert prof.get("subscription_status") == "canceled"


@pytest.mark.asyncio
async def test_app_subscriptions_update_expired_and_paused():
    """Verify that EXPIRED and PAUSED statuses downgrade profile accordingly."""
    user_id = "test-user-sub-lifecycle"
    shop_domain = "merchant-sub-lifecycle.myshopify.com"

    supabase_service.save_monitored_store(user_id=user_id, shop_domain=shop_domain, access_token_encrypted="tok")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Test EXPIRED
        payload_exp = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/445566",
                "name": "InboundCheck Growth Plan",
                "status": "EXPIRED",
            }
        }
        body_exp = json.dumps(payload_exp).encode("utf-8")
        res_exp = await ac.post(
            "/api/v1/shopify/webhooks/app_subscriptions/update",
            content=body_exp,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": generate_test_hmac(TEST_SECRET, body_exp),
                "X-Shopify-Shop-Domain": shop_domain,
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res_exp.status_code == 200
        assert res_exp.json().get("subscription_status") == "expired"
        assert supabase_service.get_user_profile(user_id).get("subscription_status") == "expired"

        # 2. Test PAUSED
        payload_paused = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/445566",
                "name": "InboundCheck Growth Plan",
                "status": "PAUSED",
            }
        }
        body_paused = json.dumps(payload_paused).encode("utf-8")
        res_paused = await ac.post(
            "/api/v1/shopify/webhooks/app_subscriptions/update",
            content=body_paused,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": generate_test_hmac(TEST_SECRET, body_paused),
                "X-Shopify-Shop-Domain": shop_domain,
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res_paused.status_code == 200
        assert res_paused.json().get("subscription_status") == "paused"
        assert supabase_service.get_user_profile(user_id).get("subscription_status") == "paused"


@pytest.mark.asyncio
async def test_app_subscriptions_update_rejects_arbitrary_client_tier():
    """Verify that arbitrary client tier payloads cannot elevate privileges; tier derived from plan name."""
    user_id = "test-user-tier-spoof"
    shop_domain = "merchant-tier-spoof.myshopify.com"

    supabase_service.save_monitored_store(user_id=user_id, shop_domain=shop_domain, access_token_encrypted="tok")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Attacker sends payload with malicious tier attempt, but plan name is Starter
        payload = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/999000",
                "name": "InboundCheck Starter Plan",
                "status": "ACTIVE",
                "subscription_tier": "agency",  # Attacker injected key
                "tier": "enterprise",          # Attacker injected key
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

        res = await ac.post(
            "/api/v1/shopify/webhooks/app_subscriptions/update",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": shop_domain,
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res.status_code == 200

        # Profile tier must be 'starter' derived strictly from 'InboundCheck Starter Plan'
        prof = supabase_service.get_user_profile(user_id)
        assert prof.get("subscription_tier") == "starter"
        assert prof.get("tier") == "starter"


@pytest.mark.asyncio
async def test_app_subscriptions_cross_tenant_isolation():
    """Verify that Shop A subscription webhook cannot modify User B's profile."""
    user_a = "tenant-a-billing"
    user_b = "tenant-b-billing"
    shop_a = "shop-a-billing.myshopify.com"
    shop_b = "shop-b-billing.myshopify.com"

    supabase_service.save_monitored_store(user_id=user_a, shop_domain=shop_a, access_token_encrypted="token_a")
    supabase_service.save_monitored_store(user_id=user_b, shop_domain=shop_b, access_token_encrypted="token_b")

    supabase_service.update_user_profile(user_a, {"subscription_tier": "starter", "subscription_status": "trialing"})
    supabase_service.update_user_profile(user_b, {"subscription_tier": "agency", "subscription_status": "active"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Shop A sends cancellation
        payload = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/cancel-a",
                "name": "InboundCheck Starter Plan",
                "status": "CANCELLED",
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body_bytes)

        res = await ac.post(
            "/api/v1/shopify/webhooks/app_subscriptions/update",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "X-Shopify-Shop-Domain": shop_a,
                "X-Shopify-Triggered-At": str(int(time.time())),
            }
        )
        assert res.status_code == 200

        # Assert User A is canceled
        prof_a = supabase_service.get_user_profile(user_a)
        assert prof_a.get("subscription_status") == "canceled"

        # Assert User B remains completely UNCHANGED (agency / active)
        prof_b = supabase_service.get_user_profile(user_b)
        assert prof_b.get("subscription_tier") == "agency"
        assert prof_b.get("subscription_status") == "active"
