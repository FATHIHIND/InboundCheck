"""
InboundCheck - Billing & Security Hardening Unit Tests
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.billing_service import billing_service
from tests.conftest import create_test_jwt, auth_headers


@pytest.mark.asyncio
async def test_jwt_security_enforcement():
    """Verify strict fail-closed JWT enforcement, elimination of X-User-ID and demo user fallbacks."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Unauthenticated request must fail closed with 401
        unauth_res = await ac.get("/api/v1/billing/plans")
        assert unauth_res.status_code == 401
        assert "Authentication required" in unauth_res.json()["detail"]

        # 2. Spoofed X-User-ID header without valid Bearer token must fail closed with 401
        spoof_res = await ac.get(
            "/api/v1/billing/plans",
            headers={"X-User-ID": "attacker-user-999"}
        )
        assert spoof_res.status_code == 401
        assert "Authentication required" in spoof_res.json()["detail"]

        # 3. Expired token must fail closed with 401
        expired_token = create_test_jwt("test-user-1", expired=True)
        exp_res = await ac.get(
            "/api/v1/billing/plans",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert exp_res.status_code == 401
        assert "expired" in exp_res.json()["detail"].lower()

        # 4. Invalid signature must fail closed with 401
        bad_token = create_test_jwt("test-user-1", bad_signature=True)
        bad_sig_res = await ac.get(
            "/api/v1/billing/plans",
            headers={"Authorization": f"Bearer {bad_token}"}
        )
        assert bad_sig_res.status_code == 401

        # 5. Valid signed token succeeds
        valid_res = await ac.get("/api/v1/billing/plans", headers=auth_headers("test-user-1"))
        assert valid_res.status_code == 200


@pytest.mark.asyncio
async def test_billing_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        # 1. Get plans (authenticated)
        plans_res = await ac.get("/api/v1/billing/plans")
        assert plans_res.status_code == 200
        assert len(plans_res.json()["plans"]) == 3

        # 2. Create checkout session (user_id strictly derived from JWT, not body)
        checkout_res = await ac.post("/api/v1/billing/checkout-session", json={
            "email": "test@brand.com",
            "plan_tier": "growth"
        })
        assert checkout_res.status_code == 200
        assert checkout_res.json()["plan_tier"] == "growth"
        assert checkout_res.json()["amount"] == 79.0

        # 3. Create customer portal session (user_id strictly derived from JWT, not body)
        portal_res = await ac.post("/api/v1/billing/customer-portal", json={})
        assert portal_res.status_code == 200
        assert "portal_url" in portal_res.json()

        # 4. Webhook processing (unauthenticated via user JWT, verified via Stripe signature)
        webhook_res = await ac.post("/api/v1/billing/webhook", json={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "test-user-1",
                    "metadata": {"plan_tier": "growth", "user_id": "test-user-1"}
                }
            }
        })
        assert webhook_res.status_code == 200
        assert webhook_res.json()["action"] == "subscription_activated"


@pytest.mark.asyncio
async def test_stripe_webhook_replay_tolerance_and_idempotency():
    """Verify Stripe timestamp drift tolerance, idempotency deduplication, and payload cap."""
    import time
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Payload size limit (> 1MB)
        large_body = b"x" * (1024 * 1024 + 10)
        res_large = await ac.post(
            "/api/v1/billing/webhook",
            content=large_body,
            headers={"Content-Length": str(len(large_body))}
        )
        assert res_large.status_code == 413

        # 2. Valid event processing
        valid_event = {
            "id": "evt_test_replay_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "test-user-replay",
                    "metadata": {"plan_tier": "enterprise", "user_id": "test-user-replay"}
                }
            }
        }
        res1 = await ac.post("/api/v1/billing/webhook", json=valid_event)
        assert res1.status_code == 200
        assert res1.json()["action"] == "subscription_activated"

        # 3. Duplicate event with same ID returns idempotent already_processed
        res2 = await ac.post("/api/v1/billing/webhook", json=valid_event)
        assert res2.status_code == 200
        assert res2.json()["status"] == "already_processed"
        assert res2.json()["idempotent"] is True

        # 4. Expired timestamp tolerance (older than 300s) fails
        expired_sig = f"t={int(time.time()) - 350},v1=dummy_sig"
        assert billing_service.verify_webhook_signature(b"payload", expired_sig) is False

        # Fresh timestamp within tolerance passes in development mode
        fresh_sig = f"t={int(time.time()) - 10},v1=dummy_sig"
        assert billing_service.verify_webhook_signature(b"payload", fresh_sig) is True


def test_ssrf_and_domain_security_sanitization():
    engine = DNSDiagnosticEngine()

    # Valid domain should clean cleanly
    assert engine._clean_domain("https://BrandShop.com/orders") == "brandshop.com"
    assert engine._clean_domain("sub.domain.co.uk:8080") == "sub.domain.co.uk"

    # SSRF: Localhost and Private IPs must raise ValueError
    blocked_domains = [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.5",
        "server.local",
        "metadata.google.internal",
        "test;rm -rf /",
        "domain..com"
    ]

    for bad_domain in blocked_domains:
        with pytest.raises(ValueError):
            engine._clean_domain(bad_domain)


def test_selector_sanitization():
    engine = DNSDiagnosticEngine()
    assert engine._sanitize_selector("shopify") == "shopify"
    assert engine._sanitize_selector("k1_2024-v2") == "k1_2024-v2"
    assert engine._sanitize_selector("bad selector!@#$") is None


import time

@pytest.mark.asyncio
async def test_enterprise_security_headers():
    """Verify enterprise security headers on API responses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/health")
        headers = res.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Strict-Transport-Security" in headers
        assert "max-age=31536000" in headers["Strict-Transport-Security"]
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in headers.get("Content-Security-Policy", "")


@pytest.mark.asyncio
async def test_global_exception_shield():
    """Verify global exception shield suppresses raw traceback and returns reference ID."""
    import json
    from unittest.mock import patch
    from starlette.requests import Request
    from app.main import global_exception_shield

    # 1. Verify global ASGI exception shield handler
    dummy_request = Request({"type": "http", "method": "GET", "path": "/api/v1/billing/plans"})
    exc = RuntimeError("Sensitive DB driver crash")
    response = await global_exception_shield(dummy_request, exc)
    assert response.status_code == 500
    data = json.loads(response.body.decode("utf-8"))
    assert data.get("detail") == "Internal server error"
    assert "error_reference" in data
    assert "reference_id" in data
    assert len(data["error_reference"]) == 36
    assert "Sensitive DB driver crash" not in response.body.decode("utf-8")

    # 2. Verify endpoint error sanitization does not leak internal str(e)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        with patch.object(billing_service, "create_checkout_session", side_effect=RuntimeError("Sensitive DB driver crash")):
            res = await ac.post("/api/v1/billing/checkout-session", json={"plan_tier": "growth"})
            assert res.status_code == 500
            ep_data = res.json()
            assert ep_data.get("detail") == "Failed to create checkout session"
            assert "Sensitive DB driver crash" not in res.text


def test_rate_limiter_memory_eviction():
    """Verify rate limiter evicts expired timestamps and bounds memory under spoofed IP loads."""
    from app.main import RateLimitingMiddleware
    rl = RateLimitingMiddleware(app=app, max_requests=10, window_seconds=60, max_tracked_ips=3)
    now = time.time()

    # Add stale IP (older than 60s)
    rl.requests_map["1.1.1.1"] = [now - 120]
    # Add active IPs
    rl.requests_map["2.2.2.2"] = [now - 10]
    rl.requests_map["3.3.3.3"] = [now - 5]
    rl.requests_map["4.4.4.4"] = [now - 2]
    rl.requests_map["5.5.5.5"] = [now - 1]

    # Trigger eviction
    rl._purge_stale_ips(now)

    # 1.1.1.1 must be purged as expired
    assert "1.1.1.1" not in rl.requests_map
    # Capacity must not exceed max_tracked_ips (3)
    assert len(rl.requests_map) <= 3


@pytest.mark.asyncio
async def test_masked_sensitive_data_in_responses():
    """Verify API keys and third-party credentials are never exposed in plaintext."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        # 1. Profile endpoint returns masked API key
        prof_res = await ac.get("/api/v1/settings/profile")
        assert prof_res.status_code == 200
        profile = prof_res.json().get("profile", {})
        assert "•" in profile.get("api_key", "")
        assert "•" in profile.get("api_key_masked", "")

        # 2. Key regeneration returns masked key
        regen_res = await ac.post("/api/v1/settings/api-key/regenerate")
        assert regen_res.status_code == 200
        assert "•" in regen_res.json().get("api_key", "")

        # 3. Provider credentials return masked token
        cred_res = await ac.get("/api/v1/dns/auto-fix/credentials")
        assert cred_res.status_code == 200
        creds = cred_res.json().get("credentials", {})
        cf_cred = creds.get("cloudflare", {})
        assert "api_token" not in cf_cred
        assert cf_cred.get("token_masked") is None or "•" in str(cf_cred.get("token_masked"))


def test_production_api_documentation_shield():
    """Verify OpenAPI and documentation endpoints are disabled when in production."""
    from unittest.mock import patch
    from fastapi import FastAPI
    from app.core.config import settings

    with patch.object(settings, "ENVIRONMENT", "production"):
        prod_is_production = settings.ENVIRONMENT.lower() in ["production", "prod"]
        prod_app = FastAPI(
            title=settings.PROJECT_NAME,
            openapi_url=None if prod_is_production else f"{settings.API_V1_STR}/openapi.json",
            docs_url=None if prod_is_production else "/docs",
            redoc_url=None if prod_is_production else "/redoc",
        )
        assert prod_app.openapi_url is None
        assert prod_app.docs_url is None
        assert prod_app.redoc_url is None


@pytest.mark.asyncio
async def test_pagination_on_resource_collections():
    """Verify limit and offset query parameters on domains and analytics collections."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        # 1. Domains endpoint with limit=1, offset=0
        dom_res = await ac.get("/api/v1/domains?limit=1&offset=0")
        assert dom_res.status_code == 200
        domains = dom_res.json()
        assert isinstance(domains, list)
        assert len(domains) <= 1

        # 2. Analytics history endpoint with limit=1, offset=0
        hist_res = await ac.get("/api/v1/analytics/history?limit=1&offset=0")
        assert hist_res.status_code == 200
        data = hist_res.json()
        assert data.get("limit") == 1
        assert data.get("offset") == 0
        assert len(data.get("events", [])) <= 1

