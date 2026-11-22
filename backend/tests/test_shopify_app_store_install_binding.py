"""
AUTHZ-SHOPIFY-02 regression tests: an App Store direct-install OAuth callback must be bound to an
authenticated user, or be rejected before the authorization code is exchanged.

Defect (api/v1/shopify.py shopify_auth_callback): /install signs the placeholder user
"shopify_app_store_install" into the OAuth state. In the callback, the placeholder is replaced only if a
valid Supabase Bearer token is present; a missing header or a failed verification (exception swallowed)
left user_id as the shared placeholder. The callback then exchanged the code and saved the store and its
encrypted access token under that shared pseudo-tenant.

Expected: 401 before exchange_token is called, and no store is saved.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers

SHOP = "placeholder-binding.myshopify.com"


def _install_state():
    return shopify_service.generate_oauth_state(user_id="shopify_app_store_install")


async def _callback(headers=None):
    exchange = AsyncMock(return_value={"access_token": "shpat_should_never_be_obtained", "scope": "read_orders"})
    details = AsyncMock(return_value={"name": "Placeholder Shop", "domain": "placeholder.example"})
    save = MagicMock(return_value={"id": "store-placeholder"})
    with patch.object(shopify_service, "exchange_token", exchange), \
         patch.object(shopify_service, "fetch_shop_details", details), \
         patch.object(shopify_service, "verify_shopify_hmac", return_value=True), \
         patch.object(supabase_service, "save_monitored_store", save):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers or {}) as ac:
            res = await ac.get(f"/api/v1/shopify/oauth/callback?shop={SHOP}&code=install_code&state={_install_state()}")
    return res, exchange, save


@pytest.mark.asyncio
async def test_app_store_install_without_session_is_rejected_before_code_exchange():
    res, exchange, save = await _callback()
    assert res.status_code == 401
    exchange.assert_not_awaited()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_app_store_install_with_invalid_bearer_is_rejected_before_code_exchange():
    res, exchange, save = await _callback(headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert res.status_code == 401
    exchange.assert_not_awaited()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_app_store_install_with_valid_session_binds_to_that_user():
    res, exchange, save = await _callback(headers=auth_headers("user-placeholder-owner"))
    assert res.status_code == 200
    exchange.assert_awaited_once()
    assert save.call_args.kwargs["user_id"] == "user-placeholder-owner"
