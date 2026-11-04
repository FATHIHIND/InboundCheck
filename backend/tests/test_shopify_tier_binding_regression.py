"""INV-18: entitlement binding uses server pricing and verified Shopify data only.

All persistence, token decryption and Shopify HTTP calls are mocked. Run with the
project's isolated safe test runner; this module never seeds a real database.
"""
import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import shopify as routes
from app.services.shopify.shopify_billing_service import (
    SHOPIFY_PLAN_PRICING,
    ShopifyBillingService,
    shopify_billing_service,
)


def subscription(amount="29.00", currency="USD", interval="EVERY_30_DAYS", name="Unlabelled"):
    return {
        "id": "gid://shopify/AppSubscription/123",
        "status": "ACTIVE",
        "name": name,
        "lineItems": [{"plan": {"pricingDetails": {
            "__typename": "AppRecurringPricing",
            "interval": interval,
            "price": {"amount": amount, "currencyCode": currency},
        }}}],
    }


@pytest.fixture
def callback_dependencies(monkeypatch):
    persistence = MagicMock()
    persistence.get_user_stores.return_value = [{
        "shop_domain": "test.myshopify.com",
        "access_token_encrypted": "mock-encrypted-token",
    }]
    persistence.get_user_profile.return_value = {
        "subscription_tier": "starter", "subscription_status": "trialing"
    }
    shop_service = MagicMock()
    shop_service.clean_shop_domain.return_value = "test.myshopify.com"
    shop_service.decrypt_token.return_value = "mock-token"
    monkeypatch.setattr(routes, "supabase_service", persistence)
    monkeypatch.setattr(routes, "shopify_service", shop_service)
    return persistence


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,tier", [("9.00", "starter"), ("29.0", "growth"), (79, "agency")])
@pytest.mark.parametrize("name", ["", "Unlabelled subscription", "InboundCheck Enterprise Agency Plan"])
@pytest.mark.parametrize("requested", [None, "agency", "enterprise", "invalid", "starter"])
async def test_callback_uses_price_not_requested_tier_or_name(callback_dependencies, amount, tier, name, requested):
    node = subscription(amount=amount, name=name)
    with patch.object(shopify_billing_service, "verify_and_activate_subscription", AsyncMock(return_value=node)):
        result = await routes.shopify_billing_callback(
            charge_id="123", plan_tier=requested, shop="test.myshopify.com", user_id="mock-user"
        )
    assert result.status_code == 302
    assert "plan=" + tier in result.headers["location"]
    callback_dependencies.update_user_profile.assert_called_once_with("mock-user", {
        "subscription_tier": tier,
        "subscription_status": "active",
        "billing_provider": "shopify",
        "shopify_charge_id": "123",
    })


def invalid_subscriptions():
    cases = [
        {"status": "ACTIVE", "name": "InboundCheck Agency Plan"},
        subscription(amount="0"), subscription(amount="-9"),
        subscription(amount="79.01"), subscription(amount="999"),
        subscription(amount=None), subscription(amount=True),
        subscription(amount="not-a-price"), subscription(amount="NaN"),
        subscription(amount="Infinity"), subscription(amount="-Infinity"),
        subscription(currency="EUR"), subscription(currency=None),
        subscription(interval="ANNUAL"), subscription(interval=None),
    ]
    for field, value in [("lineItems", []), ("lineItems", None), ("lineItems", {}),
                         ("lineItems", [None]), ("lineItems", [{"plan": None}])]:
        node = subscription()
        node[field] = value
        cases.append(node)
    multiple = subscription()
    multiple["lineItems"] *= 2
    cases.append(multiple)
    for key, value in [("__typename", "AppUsagePricing"), ("__typename", None), ("price", None), ("price", {})]:
        node = subscription()
        node["lineItems"][0]["plan"]["pricingDetails"][key] = value
        cases.append(node)
    return cases


@pytest.mark.asyncio
@pytest.mark.parametrize("node", invalid_subscriptions())
async def test_callback_rejects_unknown_pricing_without_writes(callback_dependencies, node):
    original = copy.deepcopy(node)
    with patch.object(shopify_billing_service, "verify_and_activate_subscription", AsyncMock(return_value=node)):
        with pytest.raises(HTTPException) as error:
            await routes.shopify_billing_callback(
                charge_id="123", plan_tier="agency", shop="test.myshopify.com", user_id="mock-user"
            )
    assert error.value.status_code == 400
    assert "unsupported subscription pricing" in error.value.detail
    callback_dependencies.update_user_profile.assert_not_called()
    assert node == original


def test_resolver_uses_server_owned_catalog(monkeypatch):
    monkeypatch.setitem(SHOPIFY_PLAN_PRICING, "growth", 31.0)
    assert ShopifyBillingService.resolve_subscription_tier(subscription("31.00")) == "growth"
    with pytest.raises(ValueError):
        ShopifyBillingService.resolve_subscription_tier(subscription("29.00"))


def test_ambiguous_server_prices_fail_closed(monkeypatch):
    monkeypatch.setitem(SHOPIFY_PLAN_PRICING, "agency", 29.0)
    with pytest.raises(ValueError):
        ShopifyBillingService.resolve_subscription_tier(subscription("29.00"))


@pytest.mark.asyncio
async def test_subscription_query_fetches_authoritative_recurring_price():
    node = subscription()
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": {"node": node}}
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.shopify.shopify_billing_service.httpx.AsyncClient", return_value=context):
        result = await ShopifyBillingService().verify_and_activate_subscription(
            "test.myshopify.com", "mock-token", "123"
        )
    assert result == node
    query = client.post.call_args.kwargs["json"]["query"]
    for required in ("lineItems", "pricingDetails", "__typename", "AppRecurringPricing", "interval", "amount", "currencyCode"):
        assert required in query
    assert client.post.call_args.kwargs["json"]["variables"] == {"id": "gid://shopify/AppSubscription/123"}
