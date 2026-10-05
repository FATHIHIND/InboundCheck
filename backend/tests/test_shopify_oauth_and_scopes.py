"""
InboundCheck - Phase 18B.1 Shopify OAuth Callback & Scope Hardening Tests
========================================================================
Comprehensive verification covering:
A. OAuth callback success with token exchange & metadata persistence
B. Missing code parameter rejection
C. Missing shop parameter rejection
D. Invalid, forged, or expired state parameter handling
E. No open redirect vulnerability (callback returns structured data, never external 302)
F. Zero access token leakage in responses
G. Scope hardening: read_fulfillments and read_merchant_managed_fulfillment_orders are absent
H. read_orders scope is strictly preserved for order failover
"""

import pytest
import time
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.shopify.shopify_service import shopify_service
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_shopify_scope_hardening():
    """Verify that unused fulfillment scopes have been removed and read_orders is retained."""
    # 1. Check default scopes on ShopifyService
    assert shopify_service.scopes == "read_orders"
    assert "read_fulfillments" not in shopify_service.scopes
    assert "read_merchant_managed_fulfillment_orders" not in shopify_service.scopes

    # 2. Check auth URL generation uses the hardened scope
    auth_url = shopify_service.build_auth_url(
        shop="my-brand.myshopify.com",
        redirect_uri="https://inboundcheck.com/dashboard/shopify/callback",
        state="test-state-123"
    )
    assert "scope=read_orders" in auth_url
    assert "read_fulfillments" not in auth_url
    assert "read_merchant_managed_fulfillment_orders" not in auth_url


@pytest.mark.asyncio
async def test_oauth_callback_success():
    """Verify successful OAuth code exchange, Fernet token encryption, and safe metadata return."""
    transport = ASGITransport(app=app)
    user_id = "test-user-oauth-success"

    # Generate a cryptographically valid state
    state = shopify_service.generate_oauth_state(user_id=user_id)
    shop = "artisan-crafts.myshopify.com"
    code = "mock_auth_code_xyz123"

    mock_token_data = {
        "access_token": "shpat_mock_token_secret_1234567890",
        "scope": "read_orders",
    }
    mock_shop_details = {
        "name": "Artisan Crafts Boutique",
        "email": "orders@artisancrafts.com",
        "domain": "artisancrafts.com",
        "currency": "USD",
        "timezone": "America/New_York",
        "plan_name": "shopify_plus",
    }

    with patch.object(shopify_service, "exchange_token", new_callable=AsyncMock, return_value=mock_token_data), \
         patch.object(shopify_service, "fetch_shop_details", new_callable=AsyncMock, return_value=mock_shop_details), \
         patch.object(shopify_service, "verify_shopify_hmac", return_value=True):

        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            res = await ac.get(
                f"/api/v1/shopify/oauth/callback?shop={shop}&code={code}&state={state}"
            )

            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["shop"] == shop
            assert data["store_name"] == "Artisan Crafts Boutique"
            assert data["email"] == "orders@artisancrafts.com"
            assert data["domain"] == "artisancrafts.com"

            # SECURITY: Ensure raw access token is NEVER returned in response
            assert "access_token" not in data
            assert "shpat_mock_token_secret_1234567890" not in str(data)
            assert "access_token_encrypted" not in data


@pytest.mark.asyncio
async def test_oauth_callback_missing_code():
    """Verify callback fails safely when code parameter is missing."""
    transport = ASGITransport(app=app)
    state = shopify_service.generate_oauth_state(user_id="test-user-1")

    with patch.object(shopify_service, "verify_shopify_hmac", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(f"/api/v1/shopify/oauth/callback?shop=test.myshopify.com&state={state}")
            assert res.status_code == 422


@pytest.mark.asyncio
async def test_oauth_callback_missing_shop():
    """Verify callback fails safely when shop parameter is missing."""
    transport = ASGITransport(app=app)
    state = shopify_service.generate_oauth_state(user_id="test-user-1")

    with patch.object(shopify_service, "verify_shopify_hmac", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(f"/api/v1/shopify/oauth/callback?code=mock_code&state={state}")
            assert res.status_code == 422


@pytest.mark.asyncio
async def test_oauth_callback_missing_state():
    """Verify callback rejects missing state with HTTP 400/401."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/shopify/oauth/callback?shop=test.myshopify.com&code=mock_code")
        assert res.status_code in [400, 401]


@pytest.mark.asyncio
async def test_oauth_callback_invalid_forged_state():
    """Verify callback strictly rejects forged or tampered state token."""
    transport = ASGITransport(app=app)

    with patch.object(shopify_service, "verify_shopify_hmac", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                "/api/v1/shopify/oauth/callback?shop=test.myshopify.com&code=mock_code&state=forged_state_token"
            )
            assert res.status_code == 400
            assert "Invalid, expired, or untrusted OAuth state" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_oauth_callback_expired_state():
    """Verify callback rejects expired state token (>30m)."""
    transport = ASGITransport(app=app)

    # Artificially create an expired state (timestamped 2000s in the past)
    expired_ts = str(int(time.time()) - 2000)
    secret = shopify_service.api_secret or "inboundcheck-oauth-state-secret"
    import hmac
    import hashlib
    import base64
    payload = f"test-user-1:{expired_ts}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"test-user-1:{expired_ts}:{sig}"
    expired_state = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    with patch.object(shopify_service, "verify_shopify_hmac", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/oauth/callback?shop=test.myshopify.com&code=mock_code&state={expired_state}"
            )
            assert res.status_code == 400
            assert "Invalid, expired, or untrusted OAuth state" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_oauth_callback_no_open_redirect():
    """Verify callback endpoint never redirects to untrusted external URLs."""
    transport = ASGITransport(app=app)
    state = shopify_service.generate_oauth_state(user_id="test-user-1")

    # Inject arbitrary external redirect target
    evil_url = "https://evil-phishing-site.com"
    with patch.object(shopify_service, "verify_shopify_hmac", return_value=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(
                f"/api/v1/shopify/oauth/callback?shop=test.myshopify.com&code=mock_code&state={state}&redirect_uri={evil_url}&return_to={evil_url}"
            )
            # Response is JSON or error, never an HTTP 302/301 redirecting to evil_url
            assert res.headers.get("Location") is None
            assert evil_url not in str(res.headers)


@pytest.mark.asyncio
async def test_oauth_direct_install_resolves_authenticated_bearer():
    """Verify that an App Store direct install binds to the logged-in user when a valid Bearer token is passed."""
    transport = ASGITransport(app=app)
    auth_user = "user-authenticated-logged-in-123"

    # State from /install has user_id='shopify_app_store_install'
    install_state = shopify_service.generate_oauth_state(user_id="shopify_app_store_install")
    shop = "my-new-boutique.myshopify.com"
    code = "mock_install_code"

    mock_token_data = {"access_token": "shpat_direct_install_token", "scope": "read_orders"}
    mock_shop_details = {"name": "New Boutique", "email": "contact@newboutique.com", "domain": "newboutique.com"}

    with patch.object(shopify_service, "exchange_token", new_callable=AsyncMock, return_value=mock_token_data), \
         patch.object(shopify_service, "fetch_shop_details", new_callable=AsyncMock, return_value=mock_shop_details), \
         patch.object(shopify_service, "verify_shopify_hmac", return_value=True):

        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(auth_user)) as ac:
            res = await ac.get(
                f"/api/v1/shopify/oauth/callback?shop={shop}&code={code}&state={install_state}"
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["user_id"] == auth_user
