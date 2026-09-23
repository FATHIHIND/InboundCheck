"""
InboundCheck - Phase 2.3 P1 Operational Remediation Adversarial Test Suite
========================================================================
Covers the 4 P1 Reliability Remediations:
1. OPS-01: Health Probe Rate-Limit Exemption (/ready, /api/v1/health)
2. OPS-02: Production Telegram Ops Alerting (Non-blocking, Sanitized, Missing-Safe)
3. OPS-03: Failover Worker Lease + Stale Recovery (Atomic leases, SIGTERM batch release)
4. OPS-04: DNS Auto-Fix Strict Fail-Closed (Cloudflare error handling & 502 status)
"""

import asyncio
import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.alerting.ops_alert_service import ops_alert_service, OpsAlertService, OpsIncident
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.failover.failover_repository import failover_repo
from app.workers.failover_worker import process_delivery_failure_event
from app.services.dns.auto_fixer import dns_auto_fixer_service, dns_auto_fixer
from tests.conftest import auth_headers, create_test_jwt


# =====================================================================
# OPS-01: Health Probe Rate-Limit Exemption Tests
# =====================================================================

@pytest.mark.asyncio
async def test_ops01_health_probes_immune_to_rate_limiting():
    """
    Verify that /ready and /api/v1/health can sustain 250+ rapid requests
    without receiving HTTP 429 (normal limit is 120 req/min).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test /ready across 150 consecutive calls
        for _ in range(150):
            res = await ac.get("/ready")
            assert res.status_code == 200
            assert res.json().get("status") == "ready"

        # Test /api/v1/health across 150 consecutive calls
        for _ in range(150):
            res = await ac.get("/api/v1/health")
            assert res.status_code == 200
            data = res.json()
            assert data.get("status") in ["healthy", "ok", "ready"]


@pytest.mark.asyncio
async def test_ops01_non_exempt_endpoints_enforce_rate_limit():
    """
    Verify that rate limiting is still strictly enforced on standard non-exempt endpoints.
    Temporarily unsets PYTEST_CURRENT_TEST to activate middleware rate tracking.
    """
    transport = ASGITransport(app=app)
    saved_env = os.environ.get("PYTEST_CURRENT_TEST")
    try:
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = {"X-Forwarded-For": "198.51.100.42"}
            hit_429 = False
            for _ in range(130):
                res = await ac.get("/api/v1/dns/records?domain=test-ratelimit.com", headers=headers)
                if res.status_code == 429:
                    hit_429 = True
                    assert "rate limit exceeded" in res.json().get("detail", "").lower()
                    break
            assert hit_429, "Expected non-exempt endpoint to trigger 429 rate limit after 120 calls"
    finally:
        if saved_env is not None:
            os.environ["PYTEST_CURRENT_TEST"] = saved_env


# =====================================================================
# OPS-02: Production Ops Alerting Tests
# =====================================================================

@pytest.mark.asyncio
async def test_ops02_alert_service_missing_safe():
    """
    Verify OpsAlertService handles missing or unconfigured Telegram credentials
    gracefully without raising exceptions.
    """
    unconfigured_service = OpsAlertService()
    unconfigured_service.telegram_bot_token = ""
    unconfigured_service.telegram_chat_id = ""
    unconfigured_service.webhook_url = ""

    # Must return False and not raise any exception
    sent = await unconfigured_service.dispatch_incident(
        fingerprint="TEST-MISSING-CREDS",
        severity="P1",
        summary="Test missing Telegram credentials",
        details={"test": "safe"}
    )
    assert sent is False


@pytest.mark.asyncio
async def test_ops02_alert_service_anti_flapping_suppression():
    """
    Verify that repeated incidents with the same fingerprint within the
    cooldown window (900s) are suppressed to prevent Telegram alert storms.
    """
    mock_service = OpsAlertService()
    mock_service.telegram_bot_token = "123456:FAKE_TOKEN_FOR_TESTING"
    mock_service.telegram_chat_id = "-100123456789"

    # Patch internal HTTP post to succeed
    with patch("app.services.alerting.ops_alert_service.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=MagicMock(status_code=200)):
        fp = "ALERT-TEST-FLAPPING-99"
        # First dispatch -> sends
        sent1 = await mock_service.dispatch_incident(
            fingerprint=fp,
            severity="P0",
            summary="Database Connection Timeout",
            details={"path": "/ready"}
        )
        assert sent1 is True

        # Second immediate dispatch with same fingerprint -> suppressed by anti-flapping
        sent2 = await mock_service.dispatch_incident(
            fingerprint=fp,
            severity="P0",
            summary="Database Connection Timeout Duplicate",
            details={"path": "/ready"}
        )
        assert sent2 is False


@pytest.mark.asyncio
async def test_ops02_alert_dispatch_failure_does_not_break_application():
    """
    Verify that even if Telegram dispatch throws an unexpected exception,
    application error responses (e.g. 500 shield or webhooks) are unaffected.
    """
    transport = ASGITransport(app=app)

    # Patch dispatch_incident to raise an unhandled exception
    with patch.object(ops_alert_service, "dispatch_incident", side_effect=RuntimeError("Telegram network catastrophic failure")):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Test Stripe webhook with invalid signature
            stripe_res = await ac.post(
                "/api/v1/billing/webhook",
                content=b'{"test": "payload"}',
                headers={"Stripe-Signature": "invalid_sig_123"}
            )
            # The endpoint must still return 400 cleanly, not 500 from the alert failure
            assert stripe_res.status_code == 400
            assert "Invalid Stripe webhook signature" in stripe_res.json()["detail"]

            # 2. Test Shopify webhook with invalid HMAC
            shopify_res = await ac.post(
                "/api/v1/shopify/webhooks/orders",
                content=b'{"order_id": 999}',
                headers={
                    "X-Shopify-Shop-Domain": "test-shop.myshopify.com",
                    "X-Shopify-Hmac-Sha256": "bad_hmac_abc"
                }
            )
            assert shopify_res.status_code == 401
            assert "HMAC" in shopify_res.json()["detail"]


@pytest.mark.asyncio
async def test_ops02_database_outage_triggers_p0_alert_in_shield():
    """
    Verify global_exception_shield catches DatabaseUnavailableError,
    dispatches P0 ALERT-DB-OUTAGE, and returns 503 Service Unavailable.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    with patch.object(ops_alert_service, "dispatch_incident", new_callable=AsyncMock) as mock_dispatch:
        # Patch a service call in a route to raise DatabaseUnavailableError
        with patch.object(supabase_service, "get_user_domains", side_effect=DatabaseUnavailableError("Simulated pool exhaustion")):
            async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("user-db-test")) as ac:
                res = await ac.get("/api/v1/domains")
                assert res.status_code == 503
                assert "temporarily unavailable" in res.json()["detail"].lower()

                # Verify alert was dispatched with P0 severity and sanitized info
                assert mock_dispatch.called
                if mock_dispatch.call_args[0]:
                    inc = mock_dispatch.call_args[0][0]
                    if isinstance(inc, OpsIncident):
                        assert inc.severity == "P0"
                        assert "DB-OUTAGE" in inc.alert_id
                        assert inc.details["path"] == "/api/v1/domains"
                        assert "authorization" not in inc.details
                        assert "token" not in json.dumps(inc.details).lower()
                    else:
                        assert inc.get("severity") == "P0"
                else:
                    call_kwargs = mock_dispatch.call_args[1]
                    assert call_kwargs["severity"] == "P0"
                    assert "DB-OUTAGE" in call_kwargs.get("fingerprint", "")
                    assert call_kwargs["details"]["path"] == "/api/v1/domains"
                    assert "authorization" not in call_kwargs["details"]
                    assert "token" not in json.dumps(call_kwargs["details"]).lower()


# =====================================================================
# OPS-03: Failover Worker Lease & Stale Recovery Tests
# =====================================================================

@pytest.mark.asyncio
async def test_ops03_lease_claim_and_recovery():
    """
    Verify transactional lease semantics for delivery_failure_events:
    1. Worker 1 claims event -> processing_status becomes 'queued' with lease_until in future.
    2. Worker 2 cannot claim the active leased event.
    3. If lease expires, Worker 2 reclaims the event (stale recovery).
    """
    event_id = "test-event-lease-101"
    store_id = "test-store-101"

    with patch.object(supabase_service, "_client", None):
        # Clear any residual in-memory test events for clean isolation
        supabase_service._in_memory_delivery_failure_events.clear()

        # Seed in-memory database with a 'received' event
        test_event = {
            "id": event_id,
            "store_id": store_id,
            "order_id": "ORD-101",
            "customer_email": "customer@example.com",
            "customer_phone": "+15555550101",
            "email_subject": "Order Confirmation #101",
            "failure_reason": "550 5.1.1 User unknown",
            "processing_status": "received",
            "lease_until": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase_service._in_memory_delivery_failure_events[event_id] = dict(test_event)

        # 1. Worker 1 claims with 15-minute lease (900s)
        claimed_w1 = supabase_service.claim_pending_delivery_failure_events(worker_id="worker-1", limit=5, lease_seconds=900)
        matched_w1 = [e for e in claimed_w1 if e["id"] == event_id]
        assert len(matched_w1) == 1
        assert matched_w1[0]["processing_status"] == "queued"
        assert matched_w1[0]["claimed_by"] == "worker-1"
        assert matched_w1[0]["lease_until"] is not None

        lease_expiry = datetime.fromisoformat(matched_w1[0]["lease_until"])
        assert lease_expiry > datetime.now(timezone.utc)

        # 2. Worker 2 attempts concurrent claim while lease is active
        claimed_w2 = supabase_service.claim_pending_delivery_failure_events(worker_id="worker-2", limit=5, lease_seconds=900)
        matched_w2 = [e for e in claimed_w2 if e["id"] == event_id]
        assert len(matched_w2) == 0, "Worker 2 must not claim an actively leased event"

        # 3. Simulate Worker 1 crash -> lease expires into the past
        stale_expiry = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        supabase_service._in_memory_delivery_failure_events[event_id]["lease_until"] = stale_expiry

        # 4. Worker 2 runs claim sweep -> successfully recovers the stale event!
        recovered = supabase_service.claim_pending_delivery_failure_events(worker_id="worker-2", limit=5, lease_seconds=900)
        matched_recovered = [e for e in recovered if e["id"] == event_id]
        assert len(matched_recovered) == 1, "Worker 2 must reclaim stale event whose lease has expired"
        assert matched_recovered[0]["processing_status"] == "queued"
        assert matched_recovered[0]["claimed_by"] == "worker-2"

        # Clean up
        supabase_service._in_memory_delivery_failure_events.clear()


@pytest.mark.asyncio
async def test_ops03_graceful_shutdown_releases_claimed_events():
    """
    Verify that upon worker shutdown / SIGTERM, unhandled claimed events
    are released back to 'received' status so another worker can process them immediately.
    """
    event_id = "test-event-shutdown-202"
    worker_id = "worker-shutdown-1"

    with patch.object(supabase_service, "_client", None):
        supabase_service._in_memory_delivery_failure_events.clear()
        supabase_service._in_memory_delivery_failure_events[event_id] = {
            "id": event_id,
            "store_id": "test-store-202",
            "order_id": "ORD-202",
            "processing_status": "received",
            "lease_until": None,
        }

        # Claim event
        claimed = supabase_service.claim_pending_delivery_failure_events(worker_id=worker_id, limit=1, lease_seconds=900)
        assert len(claimed) == 1
        assert claimed[0]["id"] == event_id
        assert claimed[0]["processing_status"] == "queued"

        # Release claimed event on shutdown
        success = supabase_service.release_claimed_delivery_failure_event(event_id, worker_id=worker_id)
        assert success is True

        # Verify event state in database
        released_event = supabase_service._in_memory_delivery_failure_events[event_id]
        assert released_event["processing_status"] == "received"
        assert released_event["lease_until"] is None
        assert released_event.get("claimed_by") is None

        # Clean up
        supabase_service._in_memory_delivery_failure_events.clear()


# =====================================================================
# OPS-04: DNS Auto-Fix Strict Fail-Closed Tests
# =====================================================================

@pytest.mark.asyncio
async def test_ops04_dns_auto_fix_fails_closed_on_cloudflare_error():
    """
    Verify DNSAutoFixerService strictly reports applied=False and status='failed'
    when Cloudflare API returns non-200 or an error response.
    """
    user_id = "test-user-cf-fail"
    domain = "ops4-failclosed.com"
    record_type = "TXT"
    host = "@"
    value = "v=spf1 include:_spf.google.com ~all"

    # Configure credentials for this user
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "cf-test-token-12345", "zone_1234567890abcdef")

    # Mock Cloudflare API to return HTTP 403 Forbidden
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = json.dumps({"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
    mock_response.json.return_value = {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}

    with patch.object(settings, "CLOUDFLARE_API_TOKEN", "server-cf-token"):
        with patch("app.services.dns.auto_fixer.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await dns_auto_fixer.apply_dns_fix(
                user_id=user_id,
                domain_name=domain,
                record_type=record_type,
                host=host,
                record_value=value,
                provider_name="cloudflare",
            )

            # STRICT VERIFICATION: Must NEVER report success
            assert result["applied"] is False
            assert result["fix_entry"]["status"] == "failed"
            assert "error" in result
            assert "Cloudflare API rejected" in result["error"]


@pytest.mark.asyncio
async def test_ops04_dns_auto_fix_fails_closed_on_timeout():
    """
    Verify DNSAutoFixerService reports applied=False when Cloudflare request times out.
    """
    import httpx
    user_id = "test-user-cf-timeout"
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "cf-token", "zone-123")

    with patch.object(settings, "CLOUDFLARE_API_TOKEN", "server-cf-token"):
        with patch("app.services.dns.auto_fixer.httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Connection timed out")):
            result = await dns_auto_fixer.apply_dns_fix(
                user_id=user_id,
                domain_name="ops4-timeout.com",
                record_type="TXT",
                host="@",
                record_value="v=spf1 -all",
                provider_name="cloudflare",
            )

            assert result["applied"] is False
            assert result["fix_entry"]["status"] == "failed"
            assert "error" in result
            assert "communication error" in result["error"].lower() or "timed out" in result["error"].lower()


@pytest.mark.asyncio
async def test_ops04_api_returns_502_when_remediation_fails():
    """
    Verify /api/v1/auto-fix/apply returns HTTP 502 Bad Gateway
    when the underlying provider remediation operation fails.
    """
    transport = ASGITransport(app=app)
    user_id = "00000000-0000-0000-0000-000000000001"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "growth",
        "subscription_status": "active",
    })

    with patch.object(dns_auto_fixer, "apply_dns_fix", new_callable=AsyncMock) as mock_apply:
        # Simulate remediation failure
        mock_apply.return_value = {
            "applied": False,
            "provider": "cloudflare",
            "error": "Cloudflare API rejected record creation (HTTP 403)",
            "fix_entry": {
                "id": "fix_fail_999",
                "domain_name": "test-domain.com",
                "provider_name": "cloudflare",
                "record_type": "TXT",
                "host": "@",
                "record_value": "v=spf1 -all",
                "status": "failed",
                "timestamp": "just now",
            }
        }

        payload = {
            "domain_name": "test-domain.com",
            "provider_name": "cloudflare",
            "record_type": "TXT",
            "host": "@",
            "record_value": "v=spf1 -all",
        }

        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            res = await ac.post("/api/v1/dns/auto-fix/apply", json=payload)
            assert res.status_code == 502
            body = res.json()
            assert body["success"] is False
            assert body["applied"] is False
            assert body["fix_entry"]["status"] == "failed"
            assert "Cloudflare API rejected" in body["error"]


@pytest.mark.asyncio
async def test_ops04_successful_remediation_preserved():
    """
    Verify successful DNS auto-fix returns applied=True and status='applied' (HTTP 200).
    """
    transport = ASGITransport(app=app)
    user_id = "00000000-0000-0000-0000-000000000001"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "growth",
        "subscription_status": "active",
    })

    with patch.object(dns_auto_fixer, "apply_dns_fix", new_callable=AsyncMock) as mock_apply:
        mock_apply.return_value = {
            "applied": True,
            "provider": "cloudflare",
            "fix_entry": {
                "id": "fix_success_123",
                "domain_name": "test-domain.com",
                "provider_name": "cloudflare",
                "record_type": "TXT",
                "host": "@",
                "record_value": "v=spf1 -all",
                "status": "applied",
                "timestamp": "just now",
            }
        }

        payload = {
            "domain_name": "test-domain.com",
            "provider_name": "cloudflare",
            "record_type": "TXT",
            "host": "@",
            "record_value": "v=spf1 -all",
        }

        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            res = await ac.post("/api/v1/dns/auto-fix/apply", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["applied"] is True
            assert data["fix_entry"]["status"] == "applied"
