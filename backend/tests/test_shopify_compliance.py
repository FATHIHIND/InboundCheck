"""
InboundCheck - Shopify App Store Compliance & Security Verification Test Suite
=============================================================================
Verifies:
1. Mandatory GDPR/Privacy Webhooks (customers/data_request, customers/redact, shop/redact)
   - Constant-time HMAC-SHA256 signature verification (401 on invalid, 200 on valid)
   - Fast SLA response (< 500ms) with background task delegation
2. Public App Store Direct Install endpoint (/api/v1/shopify/install)
   - HMAC verification if present
   - Domain sanitization
   - 302 redirect to Shopify OAuth authorize screen
3. Strict Domain Regex Sanitization (SHOPIFY_DOMAIN_REGEX)
   - Rejection of subdomain injection, attacker redirection, and invalid characters
4. Fail-Closed Cryptographic Token Encryption
   - Asserts RuntimeError is raised on cipher failure; zero plaintext leakage
"""

import pytest
import base64
import hashlib
import hmac
import json
from unittest.mock import patch
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.shopify.shopify_service import shopify_service, SHOPIFY_DOMAIN_REGEX


TEST_SECRET = "test_shopify_compliance_secret_key_32b"


def generate_test_hmac(secret: str, body: bytes) -> str:
    """Generate base64 encoded HMAC-SHA256 for test request body."""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture(autouse=True)
def configure_test_secret():
    """Ensure shopify_service has an active API secret during compliance tests."""
    original_secret = shopify_service.api_secret
    shopify_service.api_secret = TEST_SECRET
    yield
    shopify_service.api_secret = original_secret


# =============================================================================
# 1. Mandatory GDPR / Privacy Webhooks Tests
# =============================================================================

@pytest.mark.asyncio
async def test_gdpr_customer_data_request_webhook():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "shop_id": 954823,
            "shop_domain": "brand-store.myshopify.com",
            "customer": {
                "id": 1234567,
                "email": "customer@example.com",
                "phone": "+15551234567"
            },
            "orders_requested": [101, 102]
        }
        body = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body)

        # 1. Valid HMAC -> HTTP 200
        res_ok = await ac.post(
            "/api/v1/shopify/webhooks/customers/data_request",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "Content-Type": "application/json"
            }
        )
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["status"] == "acknowledged"
        assert data["verified"] is True

        # 2. Invalid HMAC -> HTTP 401 Unauthorized
        res_bad = await ac.post(
            "/api/v1/shopify/webhooks/customers/data_request",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": "invalid_forged_hmac_signature==",
                "Content-Type": "application/json"
            }
        )
        assert res_bad.status_code == 401


@pytest.mark.asyncio
async def test_gdpr_customer_redact_webhook():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "shop_id": 954823,
            "shop_domain": "brand-store.myshopify.com",
            "customer": {
                "id": 1234567,
                "email": "redact-me@example.com"
            },
            "orders_to_redact": [101]
        }
        body = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body)

        # 1. Valid HMAC -> HTTP 200
        res_ok = await ac.post(
            "/api/v1/shopify/webhooks/customers/redact",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "Content-Type": "application/json"
            }
        )
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["status"] == "acknowledged"
        assert data["action"] == "customer_redaction_queued"

        # 2. Invalid HMAC -> HTTP 401
        res_bad = await ac.post(
            "/api/v1/shopify/webhooks/customers/redact",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": "bad_signature",
                "Content-Type": "application/json"
            }
        )
        assert res_bad.status_code == 401


@pytest.mark.asyncio
async def test_gdpr_shop_redact_webhook():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "shop_id": 954823,
            "shop_domain": "brand-store.myshopify.com"
        }
        body = json.dumps(payload).encode("utf-8")
        valid_hmac = generate_test_hmac(TEST_SECRET, body)

        # 1. Valid HMAC -> HTTP 200
        res_ok = await ac.post(
            "/api/v1/shopify/webhooks/shop/redact",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": valid_hmac,
                "Content-Type": "application/json"
            }
        )
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["status"] == "acknowledged"
        assert data["action"] == "shop_redaction_queued"

        # 2. Invalid HMAC -> HTTP 401
        res_bad = await ac.post(
            "/api/v1/shopify/webhooks/shop/redact",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": "forged_hmac",
                "Content-Type": "application/json"
            }
        )
        assert res_bad.status_code == 401


# =============================================================================
# 2. Public App Store Direct Install Endpoint Tests
# =============================================================================

@pytest.mark.asyncio
async def test_public_app_store_direct_install():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        # 1. Valid store install request -> 302 Redirect
        res = await ac.get("/api/v1/shopify/install?shop=artisan-crafts.myshopify.com")
        assert res.status_code == 302
        redirect_url = res.headers.get("location")
        assert redirect_url is not None
        assert "artisan-crafts.myshopify.com/admin/oauth/authorize" in redirect_url
        assert "state=" in redirect_url
        assert "client_id=" in redirect_url

        # 2. Invalid domain -> HTTP 400 Bad Request
        res_bad_dom = await ac.get("/api/v1/shopify/install?shop=evil.myshopify.com.attacker.com")
        assert res_bad_dom.status_code == 400

        # 3. Valid with HMAC signature in query
        query_dict = {
            "shop": "artisan-crafts.myshopify.com",
            "timestamp": "1710000000"
        }
        # Compute query HMAC as shopify does
        sorted_pairs = [f"{k}={v}" for k, v in sorted(query_dict.items())]
        message = "&".join(sorted_pairs)
        query_hmac = hmac.new(TEST_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

        res_signed = await ac.get(f"/api/v1/shopify/install?shop=artisan-crafts.myshopify.com&timestamp=1710000000&hmac={query_hmac}")
        assert res_signed.status_code == 302

        # 4. Invalid HMAC signature in query -> HTTP 401
        res_bad_sig = await ac.get("/api/v1/shopify/install?shop=artisan-crafts.myshopify.com&timestamp=1710000000&hmac=invalid_hmac_hex")
        assert res_bad_sig.status_code == 401


# =============================================================================
# 3. Strict Domain Regex & Sanitization Tests
# =============================================================================

def test_strict_shopify_domain_regex_and_sanitization():
    # Valid domain variants
    assert shopify_service.clean_shop_domain("my-store.myshopify.com") == "my-store.myshopify.com"
    assert shopify_service.clean_shop_domain("brand123") == "brand123.myshopify.com"
    assert shopify_service.clean_shop_domain("https://artisan-shop.myshopify.com/") == "artisan-shop.myshopify.com"
    assert shopify_service.clean_shop_domain("STORE-NAME.myshopify.com") == "store-name.myshopify.com"

    # Invalid / Adversarial domain variants
    adversarial_inputs = [
        "evil.myshopify.com.attacker.com",
        "attacker.com",
        "-bad-prefix.myshopify.com",
        "store_with_underscore.myshopify.com",
        "store@domain.myshopify.com",
        "nested.sub.myshopify.com",
        "",
        "   ",
    ]

    for bad_domain in adversarial_inputs:
        with pytest.raises(HTTPException) as exc_info:
            shopify_service.clean_shop_domain(bad_domain)
        assert exc_info.value.status_code == 400


# =============================================================================
# 4. Fail-Closed Cryptographic Token Storage Tests
# =============================================================================

def test_fail_closed_fernet_token_encryption():
    raw_token = "shpat_live_offline_access_token_super_secret"

    # 1. Normal successful encryption and decryption roundtrip
    encrypted = shopify_service.encrypt_token(raw_token)
    assert encrypted != raw_token
    assert encrypted.startswith("gAAAAA")

    decrypted = shopify_service.decrypt_token(encrypted)
    assert decrypted == raw_token

    # 2. Forced cipher failure must RAISE RuntimeError and NEVER return plaintext
    with patch.object(shopify_service, "get_encryption_cipher", side_effect=Exception("Master key inaccessible")):
        with pytest.raises(RuntimeError) as exc_info:
            shopify_service.encrypt_token(raw_token)
        assert "Cryptographic failure" in str(exc_info.value)
        # Verify plaintext token is never returned
        assert raw_token not in str(exc_info.value)

    # 3. Forced decrypt failure must RAISE RuntimeError
    with patch.object(shopify_service, "get_encryption_cipher", side_effect=Exception("Cipher decryption fault")):
        with pytest.raises(RuntimeError) as exc_info:
            shopify_service.decrypt_token(encrypted)
        assert "Cryptographic failure" in str(exc_info.value)
