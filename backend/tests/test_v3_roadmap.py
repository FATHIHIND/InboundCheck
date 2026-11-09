"""
InboundCheck - V3 Roadmap Comprehensive Test Suite
===================================================
Tests Bloc A (AI Content Lab), Bloc B (Telegram Real-Time Alert Engine),
Bloc C (1-Click Auto-DNS Fixer), and Bloc D (Predictive Dispute Analytics).
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.failover.omnichannel_service import omnichannel_service
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("test-user-1"))


def test_bloc_a_ai_content_lab():
    """Test Bloc A: Template Analysis & Polymorphic Copy Generator."""
    # 1. Fetch Preset Templates
    sample_res = client.get("/api/v1/ai/sample-templates")
    assert sample_res.status_code == 200
    assert "order_confirmation" in sample_res.json().get("templates", {})

    # 2. Analyze Template
    analyze_res = client.post(
        "/api/v1/ai/analyze-template",
        json={
            "subject": "URGENT: 100% FREE discount inside!",
            "body_content": "Click here to claim your guaranteed prize ACT NOW!",
            "template_name": "Test Order Template"
        }
    )
    assert analyze_res.status_code == 200
    audit = analyze_res.json().get("audit", {})
    assert audit.get("spam_score", 0) > 0
    assert audit.get("risk_level") in ["low", "medium", "high"]
    assert len(audit.get("flagged_triggers", [])) > 0

    # 3. Generate Polymorphic Variants
    poly_res = client.post(
        "/api/v1/ai/generate-polymorphic-variants",
        json={
            "subject": "Order receipt #{{ order.name }}",
            "body_content": "<p>Hi {{ customer.first_name }}, thank you!</p>"
        }
    )
    assert poly_res.status_code == 200
    variants = poly_res.json().get("variants", [])
    assert len(variants) == 3
    assert variants[0].get("variant_id") == "v1_professional"


def test_polymorphic_generate_input_bounds_enforced():
    """Verify PolymorphicGenerateRequest strictly rejects oversized inputs (422) and accepts valid boundary."""
    growth_profile = {"id": "test-bounds-user", "subscription_tier": "growth", "subscription_status": "active"}
    with patch.object(supabase_service, "get_user_profile", return_value=growth_profile):
        bounds_client = TestClient(app, headers=auth_headers("test-bounds-user"))

        # 1. Oversized subject (> 255 chars) -> 422 Unprocessable Entity
        res_oversized_subject = bounds_client.post(
            "/api/v1/ai/generate-polymorphic-variants",
            json={
                "subject": "A" * 256,
                "body_content": "Valid body text"
            }
        )
        assert res_oversized_subject.status_code == 422

        # 2. Oversized body_content (> 15000 chars) -> 422 Unprocessable Entity
        res_oversized_body = bounds_client.post(
            "/api/v1/ai/generate-polymorphic-variants",
            json={
                "subject": "Valid subject",
                "body_content": "B" * 15001
            }
        )
        assert res_oversized_body.status_code == 422

        # 3. Oversized alternative 'body' key (> 15000 chars) -> 422 Unprocessable Entity
        res_oversized_alt_body = bounds_client.post(
            "/api/v1/ai/generate-variants",
            json={
                "subject": "Valid subject",
                "body": "C" * 15001
            }
        )
        assert res_oversized_alt_body.status_code == 422

        # 4. Valid maximum boundary (subject=255 chars, body_content=15000 chars) -> 200 OK
        res_valid_boundary = bounds_client.post(
            "/api/v1/ai/generate-polymorphic-variants",
            json={
                "subject": "A" * 255,
                "body_content": "B" * 15000
            }
        )
        assert res_valid_boundary.status_code == 200
        assert len(res_valid_boundary.json().get("variants", [])) == 3


def test_bloc_b_telegram_alert_engine(monkeypatch):
    """Test Bloc B: Telegram Real-Time Bot Alert Engine Config, Dispatch, & Test Ping.

    Stage 4.2 / T3 (C-4): /failover/dispatch is queue-first. It persists the incident to
    the durable notification outbox and returns status='queued' + job_id; delivery happens
    later in the outbox worker. The former assertions (dispatched=True, channel='telegram'
    in the HTTP response) predate that design. This test now asserts the queue contract,
    idempotent re-submission, a single worker-driven send, and tenant isolation.
    """
    import asyncio
    import uuid as _uuid
    from app.workers.failover_worker import process_notification_outbox_item

    # Fresh tenant per run (the module-level client shares "test-user-1" across tests),
    # and an isolated outbox so the claim below only sees this test's job.
    tenant_id = f"v3-tenant-{_uuid.uuid4()}"
    other_tenant_id = f"v3-other-{_uuid.uuid4()}"
    tenant = TestClient(app, headers=auth_headers(tenant_id))
    other = TestClient(app, headers=auth_headers(other_tenant_id))
    monkeypatch.setattr(supabase_service, "_in_memory_notification_outbox", {})

    # 1. Fetch Telegram Alert Config
    cfg_res = tenant.get("/api/v1/failover/config")
    assert cfg_res.status_code == 200
    assert cfg_res.json().get("config", {}).get("primary_channel") == "telegram"

    # 2. Update Telegram Alert Config
    update_res = tenant.post(
        "/api/v1/failover/config",
        json={
            "is_enabled": True,
            "primary_channel": "telegram",
            "provider": "telegram_bot_api",
            "telegram_bot_token": "7198234891:AAH8Fj90qWz1x9_test",
            "telegram_chat_id": "@inboundcheck_alerts",
            "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
            "store_name": "BrandShop DTC"
        }
    )
    assert update_res.status_code == 200

    dispatch_body = {
        "order_id": "#10505",
        "customer_email": "sarah@gmail.com",
        "trigger_reason": "email_spam_detected",
        "domain_name": "brandshop.com",
        "store_name": "BrandShop DTC"
    }
    send = AsyncMock(return_value={"success": True, "simulated": False, "data": {"ok": True, "result": {"message_id": 4242}}})
    with patch.object(omnichannel_service, "send_telegram_alert", new=send):
        # 3. Dispatch is queued durably, never sent synchronously in the request.
        dispatch_res = tenant.post("/api/v1/failover/dispatch", json=dispatch_body)
        assert dispatch_res.status_code == 200
        body = dispatch_res.json()
        assert body.get("success") is True
        assert body.get("status") == "queued"
        assert body.get("job_id")
        assert body.get("idempotent") is False
        send.assert_not_called()

        # 3b. Re-submitting the same incident is idempotent (same job, no second job).
        replay_res = tenant.post("/api/v1/failover/dispatch", json=dispatch_body)
        assert replay_res.status_code == 200
        assert replay_res.json().get("idempotent") is True
        assert replay_res.json().get("job_id") == body["job_id"]
        send.assert_not_called()

        # 3c. The outbox worker claims the single job and sends exactly once.
        claimed = supabase_service.claim_notification_outbox("v3-worker", limit=10)
        assert [str(c.get("id")) for c in claimed] == [body["job_id"]]
        assert str(claimed[0].get("user_id")) == tenant_id
        assert asyncio.run(process_notification_outbox_item(claimed[0], "v3-worker")) is True
        send.assert_awaited_once()
        assert send.call_args.kwargs.get("chat_id") == "@inboundcheck_alerts"
        assert supabase_service.claim_notification_outbox("v3-worker", limit=10) == []

        # 4. Trigger Interactive Test Ping
        ping_res = tenant.post(
            "/api/v1/settings/telegram/test",
            json={
                "bot_token": "test_token",
                "chat_id": "@inboundcheck_alerts",
                "store_name": "BrandShop DTC"
            }
        )
        assert ping_res.status_code == 200
        assert ping_res.json().get("success") is True

    # 5. Fetch Dispatch Logs: the tenant sees its incident, another tenant sees none of it.
    logs_res = tenant.get("/api/v1/failover/logs")
    assert logs_res.status_code == 200
    assert len(logs_res.json().get("logs", [])) > 0
    other_logs = other.get("/api/v1/failover/logs")
    assert other_logs.status_code == 200
    assert all(str(l.get("user_id")) != tenant_id for l in other_logs.json().get("logs", []))


@pytest.mark.asyncio
async def test_telegram_alert_failure_and_integrity():
    """Verify send_telegram_alert returns {"success": False, "error": ...} on HTTP errors or exceptions."""
    # 1. Non-200 HTTP Response
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=type("MockResp", (), {
        "status_code": 401,
        "text": '{"ok":false,"error_code":401,"description":"Unauthorized"}'
    })())):
        res = await omnichannel_service.send_telegram_alert(
            bot_token="invalid_token",
            chat_id="@invalid_channel",
            text="Test alert"
        )
        assert res["success"] is False
        assert "401" in res["error"]

    # 2. Network Exception
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=Exception("Connection timed out"))):
        res = await omnichannel_service.send_telegram_alert(
            bot_token="some_token",
            chat_id="@channel",
            text="Test alert"
        )
        assert res["success"] is False
        assert "Connection timed out" in res["error"]

    # 3. /settings/telegram/test Endpoint returns success=False on dispatch failure
    with patch.object(
        omnichannel_service,
        "send_test_ping",
        new=AsyncMock(return_value={"success": False, "error": "Invalid Telegram Bot Token"})
    ):
        ping_res = client.post(
            "/api/v1/settings/telegram/test",
            json={
                "bot_token": "bad_token",
                "chat_id": "@bad_chat",
                "store_name": "BrandShop DTC"
            }
        )
        assert ping_res.status_code == 200
        assert ping_res.json().get("success") is False
        assert "Invalid Telegram Bot Token" in ping_res.json().get("error")


def test_bloc_c_auto_dns_fixer():
    """Test Bloc C: Cloudflare / GoDaddy API Credentials, Auto-Fix, & Rollback."""
    from app.services.supabase_client import supabase_service
    supabase_service.update_user_profile("test-user-1", {
        "subscription_tier": "growth",
        "subscription_status": "active",
    })
    supabase_service.create_or_update_domain("test-user-1", "brandshop.com")

    # 1. Save Provider Credentials
    cred_res = client.post(
        "/api/v1/dns/auto-fix/credentials",
        json={
            "provider_name": "cloudflare",
            "token_or_key": "cf_token_test_12345",
            "secret_or_zone": "cf_zone_test_67890"
        }
    )
    assert cred_res.status_code == 200

    # 2. Apply 1-Click Auto-Fix
    apply_res = client.post(
        "/api/v1/dns/auto-fix/apply",
        json={
            "domain_name": "brandshop.com",
            "provider_name": "cloudflare",
            "record_type": "TXT",
            "host": "_dmarc.brandshop.com",
            "record_value": "v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@brandshop.com;"
        }
    )
    assert apply_res.status_code == 200
    assert apply_res.json().get("applied") is True
    fix_id = apply_res.json().get("fix_entry", {}).get("id")

    # 3. Rollback Fix
    if fix_id:
        rb_res = client.post(
            "/api/v1/dns/auto-fix/rollback",
            json={"fix_id": fix_id}
        )
        assert rb_res.status_code == 200
        assert rb_res.json().get("rolled_back") is True


def test_bloc_d_predictive_dispute_analytics():
    """Test Bloc D: Protected Revenue Metrics & Reputation Event Telemetry."""
    # 1. Fetch Protected Revenue Metrics
    rev_res = client.get("/api/v1/analytics/protected-revenue?monthly_gmv=150000")
    assert rev_res.status_code == 200
    analytics = rev_res.json().get("analytics", {})
    assert analytics.get("weekly_protected_revenue", 0) > 0
    assert analytics.get("roi_multiplier") is not None

    # 2. Fetch Reputation Events Log
    events_res = client.get("/api/v1/analytics/reputation-events")
    assert events_res.status_code == 200
    events = events_res.json().get("events", [])
    assert len(events) > 0
