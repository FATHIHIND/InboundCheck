"""
InboundCheck - Shopify GraphQL Recurring Billing Test Suite
============================================================
Verifies:
1. Shopify GraphQL appSubscriptionCreate mutation execution & confirmationUrl generation
2. GraphQL userErrors and network exception handling
3. AppSubscription status verification query
4. Hybrid checkout routing (Shopify store -> GraphQL confirmationUrl vs Direct user -> Stripe)
5. Billing callback activation endpoint and Supabase profile upgrade
"""

import pytest
import uuid
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport, Response

from app.main import app
from app.services.shopify.shopify_billing_service import shopify_billing_service, SHOPIFY_PLAN_PRICING
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers


# =============================================================================
# 1. Shopify GraphQL Billing Service Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_create_shopify_recurring_charge_success():
    """Verify appSubscriptionCreate mutation generates confirmationUrl with correct parameters."""
    mock_response_data = {
        "data": {
            "appSubscriptionCreate": {
                "appSubscription": {
                    "id": "gid://shopify/AppSubscription/998877",
                    "status": "PENDING",
                    "name": "InboundCheck Growth Plan"
                },
                "confirmationUrl": "https://admin.shopify.com/store/test-brand/charges/998877/confirm",
                "userErrors": []
            }
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_response_data)

        url = await shopify_billing_service.create_shopify_recurring_charge(
            shop_domain="test-brand.myshopify.com",
            access_token="shpat_mock_token_123",
            plan_name="growth",
            price_usd=29.0,
            return_url="https://app.inboundcheck.com/billing/callback",
            test=True
        )

        assert url == "https://admin.shopify.com/store/test-brand/charges/998877/confirm"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        sent_variables = call_kwargs["json"]["variables"]
        assert sent_variables["name"] == "InboundCheck Growth Plan"
        assert sent_variables["lineItems"][0]["plan"]["appRecurringPricingDetails"]["price"]["amount"] == 29.0
        assert sent_variables["lineItems"][0]["plan"]["appRecurringPricingDetails"]["interval"] == "EVERY_30_DAYS"
        assert sent_variables["test"] is True


@pytest.mark.asyncio
async def test_create_shopify_recurring_charge_user_errors():
    """Verify GraphQL userErrors raise a descriptive RuntimeError."""
    mock_response_data = {
        "data": {
            "appSubscriptionCreate": {
                "appSubscription": None,
                "confirmationUrl": None,
                "userErrors": [
                    {"field": ["lineItems"], "message": "Store payment method is not configured."}
                ]
            }
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_response_data)

        with pytest.raises(RuntimeError) as exc_info:
            await shopify_billing_service.create_shopify_recurring_charge(
                shop_domain="test-brand.myshopify.com",
                access_token="shpat_mock_token_123",
                plan_name="agency"
            )

        assert "Store payment method is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_shopify_recurring_charge_http_error():
    """Verify HTTP failure from Shopify API raises RuntimeError."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(502, text="Bad Gateway from upstream")

        with pytest.raises(RuntimeError) as exc_info:
            await shopify_billing_service.create_shopify_recurring_charge(
                shop_domain="test-brand.myshopify.com",
                access_token="shpat_mock_token_123",
                plan_name="starter"
            )

        assert "Shopify Billing API HTTP 502" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_and_activate_subscription_node():
    """Verify subscription query returns node data."""
    mock_query_data = {
        "data": {
            "node": {
                "id": "gid://shopify/AppSubscription/998877",
                "status": "ACTIVE",
                "name": "InboundCheck Growth Plan",
                "currentPeriodEnd": "2026-10-18T18:00:00Z"
            }
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_query_data)

        node = await shopify_billing_service.verify_and_activate_subscription(
            shop_domain="test-brand.myshopify.com",
            access_token="shpat_mock_token_123",
            charge_id="998877"
        )

        assert node["id"] == "gid://shopify/AppSubscription/998877"
        assert node["status"] == "ACTIVE"


# =============================================================================
# 2. Hybrid Checkout Routing Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_hybrid_checkout_routes_shopify_merchant_to_graphql_charge():
    """Verify merchant with active Shopify store receives Shopify GraphQL confirmationUrl."""
    user_id = f"shopify_merchant_{uuid.uuid4().hex[:8]}"
    shop_domain = "boutique-style.myshopify.com"
    encrypted_token = shopify_service.encrypt_token("shpat_test_access_token")

    # Connect Shopify store for this user
    supabase_service.save_monitored_store(
        user_id=user_id,
        shop_domain=shop_domain,
        access_token_encrypted=encrypted_token,
        sender_email="orders@boutiquestyle.com"
    )

    mock_confirmation_url = "https://admin.shopify.com/store/boutique-style/charges/1234/confirm"

    with patch.object(
        shopify_billing_service,
        "create_shopify_recurring_charge",
        new_callable=AsyncMock,
        return_value=mock_confirmation_url
    ) as mock_charge:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            res = await ac.post("/api/v1/billing/checkout-session", json={
                "plan_tier": "growth",
                "shop_domain": shop_domain
            })

            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["billing_provider"] == "shopify"
            assert data["url"] == mock_confirmation_url
            assert data["checkout_url"] == mock_confirmation_url
            mock_charge.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_checkout_routes_direct_user_to_stripe():
    """Verify user without Shopify store routes to standard Stripe Checkout."""
    direct_user_id = f"direct_user_{uuid.uuid4().hex[:8]}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(direct_user_id)) as ac:
        res = await ac.post("/api/v1/billing/checkout-session", json={
            "plan_tier": "starter"
        })

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["billing_provider"] == "stripe"
        assert "checkout.stripe.com" in data["url"] or "checkout_url" in data


# =============================================================================
# 3. Shopify Billing Callback Activation Endpoint Tests
# =============================================================================

@pytest.mark.asyncio
async def test_shopify_billing_callback_activates_subscription():
    """Verify callback activates tier in Supabase profile and redirects to dashboard with success."""
    cb_user_id = f"cb_user_{uuid.uuid4().hex[:8]}"
    shop_domain = "artisanal-wares.myshopify.com"
    encrypted_token = shopify_service.encrypt_token("shpat_test_access_token")

    # Connect store and seed profile
    supabase_service.save_monitored_store(
        user_id=cb_user_id,
        shop_domain=shop_domain,
        access_token_encrypted=encrypted_token
    )
    supabase_service.update_user_profile(cb_user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing"
    })

    with patch.object(
        shopify_billing_service,
        "verify_and_activate_subscription",
        new_callable=AsyncMock,
        return_value={"status": "ACTIVE"}
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
            res = await ac.get(
                f"/api/v1/shopify/billing/callback?charge_id=776655&plan_tier=agency&shop={shop_domain}&user_id={cb_user_id}"
            )

            assert res.status_code == 302
            redirect_location = res.headers.get("location")
            assert redirect_location is not None
            assert "/dashboard/billing?checkout=success&billing=success&plan=agency" in redirect_location

            # Assert profile updated
            updated_profile = supabase_service.get_user_profile(cb_user_id)
            assert updated_profile.get("subscription_tier") == "agency"
            assert updated_profile.get("subscription_status") == "active"
            assert updated_profile.get("billing_provider") == "shopify"
            assert updated_profile.get("shopify_charge_id") == "776655"
