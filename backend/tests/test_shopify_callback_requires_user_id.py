"""
Regression tests: the Shopify billing callback must fail closed when the
user_id query parameter is missing or empty.

Root cause: when user_id was absent, shopify_billing_callback resolved the
tenant by scanning the process-local supabase_service._in_memory_stores
registry. That state is not shared across workers or pods and is not a
trustworthy tenant mapping, so the callback could proceed to verification
and profile activation for a tenant chosen by in-memory lookup.

Expected behaviour: the callback rejects the request before any Shopify
verification call or profile write, and never consults the in-memory store
registry for tenant resolution.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.shopify.shopify_billing_service import shopify_billing_service
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service


@pytest.fixture
def merchant_with_store():
    """Seed a merchant whose store is only discoverable via the in-memory registry."""
    user_id = f"merchant_{uuid.uuid4().hex[:8]}"
    shop_domain = f"cs03-{uuid.uuid4().hex[:6]}.myshopify.com"
    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted=shopify_service.encrypt_token("shpat_cs03_test_token"),
    )
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing",
    })
    return {"user_id": user_id, "shop_domain": shop_domain}


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id_query", ["", None])
async def test_callback_without_user_id_never_verifies_or_activates(merchant_with_store, user_id_query):
    shop = merchant_with_store["shop_domain"]
    owner = merchant_with_store["user_id"]
    url = f"/api/v1/shopify/billing/callback?charge_id=cs03-charge&plan_tier=agency&shop={shop}"
    if user_id_query is not None:
        url += f"&user_id={user_id_query}"

    verify_mock = AsyncMock(return_value={"status": "ACTIVE", "name": "agency"})
    with patch.object(shopify_billing_service, "verify_and_activate_subscription", verify_mock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(url)

    assert res.status_code == 400
    verify_mock.assert_not_awaited()

    profile = supabase_service.get_user_profile(owner)
    assert profile.get("subscription_tier") == "starter"
    assert profile.get("subscription_status") != "active"
