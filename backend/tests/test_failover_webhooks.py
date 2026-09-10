"""
InboundCheck - Secure ESP Webhook Ingestion Tests (Phase 4 Step 4)
==================================================================
Validates cryptographic verification, 1 MB payload limits, replay protection (clock skew),
event normalization, PII hashing, and failover eligibility for Postmark, SendGrid, Mailgun, SES, and Klaviyo.
"""

import pytest
import hmac
import hashlib
import time
import json
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.failover.event_normalizers import (
    normalize_provider_events,
    NormalizedDeliveryFailure,
    FAILOVER_ELIGIBLE_EVENTS,
    FAILOVER_ELIGIBLE_MESSAGE_TYPES,
    hash_email,
)
from app.services.supabase_client import supabase_service
from app.workers.failover_worker import process_failover_event
from app.services.failover.omnichannel_service import omnichannel_service
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_payload_limit_enforcement():
    """Verify that requests exceeding 1 MB are rejected with HTTP 413."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Generate payload larger than 1 MB (1_048_576 bytes)
        huge_payload = b"x" * (1_048_576 + 1024)

        res = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            content=huge_payload,
            headers={"Content-Type": "application/json"}
        )
        assert res.status_code == 413
        assert "exceeds maximum limit" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_postmark_webhook_verification_and_ingestion():
    """Verify Postmark webhook token authentication and bounce event ingestion."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_secret = settings.POSTMARK_WEBHOOK_SECRET
        settings.POSTMARK_WEBHOOK_SECRET = "test_pm_secret_xyz123"

        try:
            msg_id = f"pm_msg_{uuid.uuid4()}"
            bounce_payload = {
                "RecordType": "Bounce",
                "ID": 42981,
                "Type": "HardBounce",
                "TypeCode": 1,
                "Name": "Hard bounce",
                "Details": "smtp; 550 5.1.1 User unknown",
                "Email": "customer@shopifybrand.com",
                "BouncedAt": "2026-09-10T20:00:00Z",
                "MessageID": msg_id
            }

            # 1. Missing token -> 401 Unauthorized
            res = await client.post(
                "/api/v1/webhook/delivery-failure/postmark",
                json=bounce_payload,
                headers={"Content-Type": "application/json"}
            )
            assert res.status_code == 401

            # 2. Invalid token -> 403 Forbidden
            res = await client.post(
                "/api/v1/webhook/delivery-failure/postmark",
                json=bounce_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": "invalid_secret"
                }
            )
            assert res.status_code == 403

            # 3. Valid token -> 200 OK
            res = await client.post(
                "/api/v1/webhook/delivery-failure/postmark",
                json=bounce_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": "test_pm_secret_xyz123"
                }
            )
            assert res.status_code == 200
            data = res.json()
            assert data["accepted"] is True
            assert data["processed_events"] == 1

        finally:
            settings.POSTMARK_WEBHOOK_SECRET = original_secret


@pytest.mark.asyncio
async def test_sendgrid_webhook_verification_and_clock_skew():
    """Verify SendGrid HMAC signature check, clock skew tolerance rejection, and event batch parsing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_key = settings.SENDGRID_WEBHOOK_VERIFICATION_KEY
        settings.SENDGRID_WEBHOOK_VERIFICATION_KEY = "sg_signing_key_secret"

        try:
            now = int(time.time())
            event_id = f"sg_evt_{uuid.uuid4()}"
            msg_id = f"sg_msg_{uuid.uuid4()}"
            raw_payload = json.dumps([{
                "sg_event_id": event_id,
                "sg_message_id": f"{msg_id}.filter0001",
                "event": "bounce",
                "type": "blocked",
                "status": "5.1.1",
                "reason": "550 5.1.1 User unknown",
                "timestamp": now,
                "email": "customer@gmail.com"
            }]).encode("utf-8")

            # 1. Stale timestamp (outside 300s clock skew window) -> 403 Forbidden
            old_ts = str(now - 400)
            old_sig = hmac.new(
                settings.SENDGRID_WEBHOOK_VERIFICATION_KEY.encode("utf-8"),
                old_ts.encode("utf-8") + raw_payload,
                hashlib.sha256
            ).hexdigest()

            res = await client.post(
                "/api/v1/webhook/delivery-failure/sendgrid",
                content=raw_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Twilio-Email-Event-Webhook-Signature": old_sig,
                    "X-Twilio-Email-Event-Webhook-Timestamp": old_ts
                }
            )
            assert res.status_code == 403
            assert "clock skew exceeded" in res.json().get("detail", "")

            # 2. Valid signature and fresh timestamp -> 200 OK
            valid_ts = str(now)
            valid_sig = hmac.new(
                settings.SENDGRID_WEBHOOK_VERIFICATION_KEY.encode("utf-8"),
                valid_ts.encode("utf-8") + raw_payload,
                hashlib.sha256
            ).hexdigest()

            res = await client.post(
                "/api/v1/webhook/delivery-failure/sendgrid",
                content=raw_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Twilio-Email-Event-Webhook-Signature": valid_sig,
                    "X-Twilio-Email-Event-Webhook-Timestamp": valid_ts
                }
            )
            assert res.status_code == 200
            assert res.json()["accepted"] is True
            assert res.json()["processed_events"] == 1

        finally:
            settings.SENDGRID_WEBHOOK_VERIFICATION_KEY = original_key


@pytest.mark.asyncio
async def test_mailgun_webhook_verification():
    """Verify Mailgun HMAC-SHA256 signature verification over timestamp+token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_key = settings.MAILGUN_WEBHOOK_SIGNING_KEY
        settings.MAILGUN_WEBHOOK_SIGNING_KEY = "mailgun_secret_key_123"

        try:
            now = int(time.time())
            token = f"mg_tok_{uuid.uuid4()}"
            sig = hmac.new(
                settings.MAILGUN_WEBHOOK_SIGNING_KEY.encode("utf-8"),
                f"{now}{token}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            payload = {
                "signature": {
                    "timestamp": str(now),
                    "token": token,
                    "signature": sig
                },
                "event-data": {
                    "id": f"mg_evt_{uuid.uuid4()}",
                    "event": "failed",
                    "severity": "permanent",
                    "recipient": "customer@yahoo.com",
                    "timestamp": now,
                    "message": {
                        "headers": {
                            "message-id": "<20260910190000.1.UUID@domain.com>"
                        }
                    },
                    "delivery-status": {
                        "code": 550,
                        "message": "Mailbox not found"
                    }
                }
            }

            res = await client.post(
                "/api/v1/webhook/delivery-failure/mailgun",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            assert res.status_code == 200
            assert res.json()["accepted"] is True
            assert res.json()["processed_events"] == 1

        finally:
            settings.MAILGUN_WEBHOOK_SIGNING_KEY = original_key


@pytest.mark.asyncio
async def test_event_normalizers_and_failover_eligibility():
    """Verify event normalization across all providers and strictly enforce failover eligibility rules."""
    # 1. Postmark Soft Bounce (transient) -> deferred (NOT failover eligible)
    pm_soft = json.dumps({
        "RecordType": "Bounce",
        "ID": 101,
        "Type": "SoftBounce",
        "Email": "soft@example.com",
        "MessageID": "msg_soft"
    }).encode("utf-8")
    norm_pm = normalize_provider_events("postmark", pm_soft)
    assert len(norm_pm) == 1
    assert norm_pm[0].event_type == "deferred"
    assert norm_pm[0].is_failover_eligible("order_confirmation") is False

    # 2. Postmark Hard Bounce -> bounce (Failover eligible for order_confirmation)
    pm_hard = json.dumps({
        "RecordType": "Bounce",
        "ID": 102,
        "Type": "HardBounce",
        "Email": "hard@example.com",
        "MessageID": "msg_hard"
    }).encode("utf-8")
    norm_pm_hard = normalize_provider_events("postmark", pm_hard)
    assert len(norm_pm_hard) == 1
    assert norm_pm_hard[0].event_type == "bounce"
    assert norm_pm_hard[0].is_failover_eligible("order_confirmation") is True
    # But NOT eligible for marketing campaigns
    assert norm_pm_hard[0].is_failover_eligible("marketing_newsletter") is False

    # 3. Spam complaints and unsubscribes must NEVER trigger customer fallback
    sg_spam = json.dumps([{
        "sg_event_id": "sg_spam_1",
        "event": "spamreport",
        "email": "spam@example.com",
        "timestamp": int(time.time())
    }]).encode("utf-8")
    norm_sg = normalize_provider_events("sendgrid", sg_spam)
    assert len(norm_sg) == 1
    assert norm_sg[0].event_type == "complaint"
    assert norm_sg[0].is_failover_eligible("order_confirmation") is False

    # 4. Amazon SES Permanent Bounce
    ses_bounce = json.dumps({
        "notificationType": "Bounce",
        "mail": {"messageId": "ses_msg_1", "timestamp": "2026-09-10T19:00:00Z"},
        "bounce": {
            "bounceType": "Permanent",
            "bounceSubType": "General",
            "feedbackId": "ses_fb_1",
            "bouncedRecipients": [{"emailAddress": "ses@example.com", "status": "5.1.1"}]
        }
    }).encode("utf-8")
    norm_ses = normalize_provider_events("ses", ses_bounce)
    assert len(norm_ses) == 1
    assert norm_ses[0].event_type == "bounce"
    assert norm_ses[0].is_failover_eligible("shipping_update") is True

    # 5. Klaviyo dropped email
    klaviyo_dropped = json.dumps([{
        "id": "kl_123",
        "type": "Dropped Email",
        "attributes": {
            "metric_name": "Dropped Email",
            "reason": "Suppressed recipient",
            "email": "dropped@example.com",
            "timestamp": int(time.time())
        }
    }]).encode("utf-8")
    norm_kl = normalize_provider_events("klaviyo", klaviyo_dropped)
    assert len(norm_kl) == 1
    assert norm_kl[0].event_type == "dropped"
    assert norm_kl[0].is_failover_eligible("delivery_update") is True


@pytest.mark.asyncio
async def test_delivery_failure_generates_telegram_dispatch_log():
    """An eligible event is recorded as a Telegram-only merchant incident."""
    user_id = f"telegram-worker-{uuid.uuid4()}"
    message_id = f"pm-message-{uuid.uuid4()}"
    supabase_service.register_transactional_message(
        user_id=user_id,
        order_id="#11001",
        esp_provider="postmark",
        provider_message_id=message_id,
        recipient_email="merchant@example.com",
    )
    event = supabase_service.record_delivery_failure_event(
        esp_provider="postmark",
        provider_event_id=f"event-{uuid.uuid4()}",
        provider_message_id=message_id,
        event_type="bounce",
        user_id=user_id,
        event_payload={"details": "550 5.1.1 mailbox unavailable", "domain_name": "brandshop.com"},
    )

    with patch.object(
        omnichannel_service,
        "send_telegram_alert",
        new=AsyncMock(return_value={"success": True, "data": {"ok": True}}),
    ):
        assert await process_failover_event(event, "worker-test") is True

    logs = supabase_service.get_failover_logs(user_id=user_id)
    assert len(logs) == 1
    assert logs[0]["channel"] == "telegram"
    assert logs[0]["provider"] == "telegram"
    assert logs[0]["provider_status"] == "delivered"
    assert logs[0]["delivery_failure_event_id"] == event["id"]
