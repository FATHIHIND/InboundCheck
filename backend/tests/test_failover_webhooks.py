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
async def test_webhook_returns_503_when_durable_persistence_fails():
    """Verify webhook returns HTTP 503 when durable persistence fails, requesting provider retry."""
    from app.services.supabase_client import DatabaseUnavailableError
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_secret = settings.POSTMARK_WEBHOOK_SECRET
        settings.POSTMARK_WEBHOOK_SECRET = "test_pm_secret_xyz123"

        try:
            bounce_payload = {
                "RecordType": "Bounce",
                "ID": 99999,
                "Type": "HardBounce",
                "TypeCode": 1,
                "Name": "Hard bounce",
                "Details": "smtp; 550 5.1.1 User unknown",
                "Email": "customer@shopifybrand.com",
                "BouncedAt": "2026-09-10T20:00:00Z",
                "MessageID": f"pm_msg_{uuid.uuid4()}"
            }

            with patch("app.api.v1.failover_webhooks.failure_event_repository.insert_if_absent", side_effect=DatabaseUnavailableError("Database unreachable")):
                res = await client.post(
                    "/api/v1/webhook/delivery-failure/postmark",
                    json=bounce_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Postmark-Server-Token": "test_pm_secret_xyz123"
                    }
                )
                assert res.status_code == 503
                assert "Durable event persistence temporarily unavailable" in res.json().get("detail", "")
        finally:
            settings.POSTMARK_WEBHOOK_SECRET = original_secret


@pytest.mark.asyncio
async def test_sendgrid_webhook_verification_and_clock_skew():
    """Verify SendGrid ECDSA P-256 + SHA-256 signature check, clock skew tolerance rejection, and event batch parsing."""
    from app.services.failover.esp_webhook_service import (
        generate_sendgrid_ecdsa_keypair,
        sign_sendgrid_ecdsa_webhook,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_key = settings.SENDGRID_WEBHOOK_VERIFICATION_KEY
        priv_scalar, pub_b64_spki, _ = generate_sendgrid_ecdsa_keypair()
        settings.SENDGRID_WEBHOOK_VERIFICATION_KEY = pub_b64_spki

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
            old_sig = sign_sendgrid_ecdsa_webhook(priv_scalar, old_ts, raw_payload)

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

            # 2. Valid ECDSA P-256 signature and fresh timestamp -> 200 OK
            valid_ts = str(now)
            valid_sig = sign_sendgrid_ecdsa_webhook(priv_scalar, valid_ts, raw_payload)

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


# Stage 4.2 / T3 (C-1, C-2): synthetic test-only tenant Telegram credentials (no
# placeholder substrings; deliberately not shaped like a real Telegram bot token so
# secret scanners cannot flag them) and an isolated in-memory event store per test.
_SYNTHETIC_TG_TOKEN = "stage42-synthetic-telegram-credential-webhooks"
_SYNTHETIC_TG_CHAT = "-1004242424243"


def _record_claimed_event(monkeypatch, user_id, message_id):
    import app.services.failover.omnichannel_service as omni
    from app.services.failover.failover_repository import failure_event_repository

    monkeypatch.setattr(omni, "_mock_failover_configs", {})
    monkeypatch.setattr(supabase_service, "_in_memory_delivery_failure_events", {})
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
    claimed = failure_event_repository.claim_pending_delivery_failure_events("worker-test", limit=5)
    assert [c["id"] for c in claimed] == [event["id"]]
    assert claimed[0]["lease_until"]
    return omni, {**event, **claimed[0]}


@pytest.mark.asyncio
async def test_delivery_failure_generates_telegram_dispatch_log(monkeypatch):
    """An eligible event is recorded as a Telegram-only merchant incident."""
    user_id = f"telegram-worker-{uuid.uuid4()}"
    message_id = f"pm-message-{uuid.uuid4()}"
    omni, event = _record_claimed_event(monkeypatch, user_id, message_id)
    omni.omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": _SYNTHETIC_TG_TOKEN,
        "telegram_chat_id": _SYNTHETIC_TG_CHAT,
    })

    send = AsyncMock(return_value={"success": True, "data": {"ok": True}})
    with patch.object(omnichannel_service, "send_telegram_alert", new=send):
        assert await process_failover_event(event, "worker-test") is True
    send.assert_awaited_once()

    logs = supabase_service.get_failover_logs(user_id=user_id)
    assert len(logs) == 1
    assert logs[0]["channel"] == "telegram"
    assert logs[0]["provider"] == "telegram"
    assert logs[0]["provider_status"] == "delivered"
    assert logs[0]["delivery_failure_event_id"] == event["id"]


@pytest.mark.asyncio
async def test_delivery_failure_without_tenant_telegram_config_fails_closed(monkeypatch):
    """Negative: with no tenant Telegram credentials nothing is sent and nothing is 'delivered'."""
    user_id = f"telegram-worker-{uuid.uuid4()}"
    message_id = f"pm-message-{uuid.uuid4()}"
    _, event = _record_claimed_event(monkeypatch, user_id, message_id)

    send = AsyncMock(return_value={"success": True, "data": {"ok": True}})
    with patch.object(omnichannel_service, "send_telegram_alert", new=send):
        assert await process_failover_event(event, "worker-test") is False
    send.assert_not_called()

    # Pin the outcome to the credential guard, not some other early exit.
    stored = next(e for e in supabase_service._in_memory_delivery_failure_events.values() if str(e.get("id")) == str(event["id"]))
    assert stored["processing_status"] == "failed"
    assert "must be explicitly configured" in (stored.get("processing_error") or "")

    delivered = [l for l in supabase_service.get_failover_logs(user_id=user_id) if l.get("provider_status") == "delivered"]
    assert delivered == []


@pytest.mark.asyncio
async def test_valid_signed_esp_creates_received_record_and_replay_is_idempotent():
    """Valid signed ESP delivery failure creates one record with 'received', replay does not duplicate."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        evt_id = f"evt_{uuid.uuid4()}"
        msg_id = f"msg_{uuid.uuid4()}"
        payload = {
            "RecordType": "Bounce",
            "ID": evt_id,
            "Type": "HardBounce",
            "Details": "smtp; 550 5.1.1 User unknown",
            "Email": "bounce@brand.com",
            "MessageID": msg_id,
        }

        # 1. First signed ingestion -> 200 OK and record created with 'received'
        res1 = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            json=payload,
            headers={"Content-Type": "application/json", "X-Postmark-Server-Token": "test_secret_token"}
        )
        assert res1.status_code == 200
        assert res1.json()["accepted"] is True
        assert res1.json()["processed_events"] == 1

        rec = next(
            (e for e in supabase_service._in_memory_delivery_failure_events.values() if e.get("provider_event_id") == str(evt_id)),
            None
        )
        assert rec is not None
        assert rec["processing_status"] == "received"
        initial_db_id = rec["id"]

        # 2. Replay of identical event -> Accepted but deduplicated to same record
        res2 = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            json=payload,
            headers={"Content-Type": "application/json", "X-Postmark-Server-Token": "test_secret_token"}
        )
        assert res2.status_code == 200
        assert res2.json()["accepted"] is True

        rec_after = next(
            (e for e in supabase_service._in_memory_delivery_failure_events.values() if e.get("provider_event_id") == str(evt_id)),
            None
        )
        assert rec_after is not None
        assert rec_after["id"] == initial_db_id


@pytest.mark.asyncio
async def test_no_carrier_callback_endpoint_exists():
    """Verify carrier callback endpoints do not exist and return 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for route in [
            "/api/v1/carrier/delivery-status",
            "/api/v1/carrier/sms",
            "/api/v1/twilio/status",
            "/api/v1/whatsapp/status",
            "/api/v1/meta/status",
        ]:
            res = await client.post(route, json={"status": "delivered"})
            assert res.status_code == 404


@pytest.mark.asyncio
async def test_webhook_ingestion_does_not_dispatch_telegram_directly():
    """Webhook ingestion must only persist/queue the event and never dispatch Telegram directly."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "RecordType": "Bounce",
            "ID": f"evt_async_{uuid.uuid4()}",
            "Type": "HardBounce",
            "Details": "smtp; 550 5.1.1 User unknown",
            "Email": "async@brand.com",
            "MessageID": f"msg_async_{uuid.uuid4()}",
        }

        with patch("app.services.failover.omnichannel_service.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_tg:
            res = await client.post(
                "/api/v1/webhook/delivery-failure/postmark",
                json=payload,
                headers={"Content-Type": "application/json", "X-Postmark-Server-Token": "test_secret_token"}
            )
            assert res.status_code == 200
            # Verification: Telegram was NOT dispatched during webhook HTTP request
            mock_tg.assert_not_called()


# ==============================================================================
# Group 44: P0-01 ESP Webhook Security Remediation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_p0_01_all_five_providers_reject_test_tokens_in_production_and_persist_nothing(monkeypatch):
    """
    Prove that in ENVIRONMENT='production', all 5 providers (Postmark, SendGrid, Mailgun, SES, Klaviyo)
    reject 'test_secret_token' and 'valid_test_signature' both when secrets are unconfigured (500)
    and when secrets ARE configured (403), and zero events are persisted.
    """
    from app.services.failover.esp_webhook_service import generate_sendgrid_ecdsa_keypair

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    _, sg_pub_b64, _ = generate_sendgrid_ecdsa_keypair()

    now = int(time.time())
    pm_evt_id = f"pm_forged_{uuid.uuid4()}"
    sg_evt_id = f"sg_forged_{uuid.uuid4()}"
    mg_evt_id = f"mg_forged_{uuid.uuid4()}"
    ses_evt_id = f"ses_forged_{uuid.uuid4()}"
    kl_evt_id = f"kl_forged_{uuid.uuid4()}"

    pm_body = {"RecordType": "Bounce", "ID": pm_evt_id, "Type": "HardBounce", "Email": "a@b.com", "MessageID": "m1"}
    sg_body = [{"sg_event_id": sg_evt_id, "event": "bounce", "type": "blocked", "status": "5.1.1", "timestamp": now, "email": "a@b.com"}]
    mg_body = {
        "signature": {"timestamp": str(now), "token": "tok1", "signature": "valid_test_signature"},
        "event-data": {"id": mg_evt_id, "event": "failed", "severity": "permanent", "recipient": "a@b.com", "timestamp": now},
    }
    ses_body = {
        "notificationType": "Bounce",
        "mail": {"messageId": "ses_m1", "timestamp": "2026-10-31T12:00:00Z"},
        "bounce": {"bounceType": "Permanent", "feedbackId": ses_evt_id, "bouncedRecipients": [{"emailAddress": "a@b.com"}]},
    }
    kl_body = [{"id": kl_evt_id, "type": "Dropped Email", "attributes": {"metric_name": "Dropped Email", "email": "a@b.com", "timestamp": now}}]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Phase A: Production secrets UNCONFIGURED -> Must fail closed with HTTP 500 even when test tokens are sent
        monkeypatch.setattr(settings, "POSTMARK_WEBHOOK_SECRET", "")
        monkeypatch.setattr(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", "")
        monkeypatch.setattr(settings, "MAILGUN_WEBHOOK_SIGNING_KEY", "")
        monkeypatch.setattr(settings, "SES_WEBHOOK_SECRET", "")
        monkeypatch.setattr(settings, "KLAVIYO_WEBHOOK_SECRET", "")

        r_pm = await client.post("/api/v1/webhook/delivery-failure/postmark", json=pm_body, headers={"X-Postmark-Server-Token": "test_secret_token"})
        assert r_pm.status_code == 500

        r_sg = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            json=sg_body,
            headers={"X-Twilio-Email-Event-Webhook-Signature": "valid_test_signature", "X-Twilio-Email-Event-Webhook-Timestamp": str(now)},
        )
        assert r_sg.status_code == 500

        r_mg = await client.post("/api/v1/webhook/delivery-failure/mailgun", json=mg_body)
        assert r_mg.status_code == 500

        r_ses = await client.post("/api/v1/webhook/delivery-failure/ses", json=ses_body, headers={"X-SES-Webhook-Secret": "valid_test_signature"})
        assert r_ses.status_code == 500

        r_kl = await client.post("/api/v1/webhook/delivery-failure/klaviyo", json=kl_body, headers={"X-Klaviyo-Signature": "valid_test_signature"})
        assert r_kl.status_code == 500

        # Phase B: Production secrets CONFIGURED -> Must reject test tokens with HTTP 403
        monkeypatch.setattr(settings, "POSTMARK_WEBHOOK_SECRET", "prod_pm_secret_999")
        monkeypatch.setattr(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", sg_pub_b64)
        monkeypatch.setattr(settings, "MAILGUN_WEBHOOK_SIGNING_KEY", "prod_mg_key_999")
        monkeypatch.setattr(settings, "SES_WEBHOOK_SECRET", "prod_ses_secret_999")
        monkeypatch.setattr(settings, "KLAVIYO_WEBHOOK_SECRET", "prod_kl_secret_999")

        r_pm2 = await client.post("/api/v1/webhook/delivery-failure/postmark", json=pm_body, headers={"X-Postmark-Server-Token": "test_secret_token"})
        assert r_pm2.status_code == 403

        r_sg2 = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            json=sg_body,
            headers={"X-Twilio-Email-Event-Webhook-Signature": "valid_test_signature", "X-Twilio-Email-Event-Webhook-Timestamp": str(now)},
        )
        assert r_sg2.status_code == 403

        r_mg2 = await client.post("/api/v1/webhook/delivery-failure/mailgun", json=mg_body)
        assert r_mg2.status_code == 403

        r_ses2 = await client.post("/api/v1/webhook/delivery-failure/ses", json=ses_body, headers={"X-SES-Webhook-Secret": "valid_test_signature"})
        assert r_ses2.status_code == 403

        r_kl2 = await client.post("/api/v1/webhook/delivery-failure/klaviyo", json=kl_body, headers={"X-Klaviyo-Signature": "valid_test_signature"})
        assert r_kl2.status_code == 403

        # Verify zero forged events were persisted
        stored_ids = {e.get("provider_event_id") for e in supabase_service._in_memory_delivery_failure_events.values()}
        assert pm_evt_id not in stored_ids
        assert sg_evt_id not in stored_ids
        assert mg_evt_id not in stored_ids
        assert ses_evt_id not in stored_ids
        assert kl_evt_id not in stored_ids


@pytest.mark.asyncio
async def test_p0_01_sendgrid_ecdsa_p256_valid_and_invalid_signatures(monkeypatch):
    """
    Verify SendGrid ECDSA P-256 + SHA-256 verification:
    - Rejects 'valid_test_signature' when public key is configured (even in development/test).
    - Rejects invalid ECDSA signatures (wrong keypair, tampered body, tampered timestamp, symmetric HMAC).
    - Accepts valid ECDSA P-256 signatures with both raw Base64 SPKI and PEM public keys.
    - Fails closed (500) if SENDGRID_WEBHOOK_VERIFICATION_KEY is malformed.
    """
    from app.services.failover.esp_webhook_service import (
        generate_sendgrid_ecdsa_keypair,
        sign_sendgrid_ecdsa_webhook,
    )

    priv_1, pub_1_b64, pub_1_pem = generate_sendgrid_ecdsa_keypair()
    priv_2, _, _ = generate_sendgrid_ecdsa_keypair()

    now = int(time.time())
    ts_str = str(now)
    evt_id = f"sg_ecdsa_{uuid.uuid4()}"
    raw_body = json.dumps([{
        "sg_event_id": evt_id,
        "sg_message_id": "sg_msg_ecdsa.filter01",
        "event": "bounce",
        "type": "blocked",
        "status": "5.1.1",
        "reason": "550 User unknown",
        "timestamp": now,
        "email": "ecdsa@example.com",
    }]).encode("utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Configure valid Base64 SPKI public key in development mode
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", pub_1_b64)

        # 1a. Reject 'valid_test_signature' even in development when public key is configured
        res_test_sig = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": "valid_test_signature",
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_test_sig.status_code == 403

        # 1b. Reject signature generated by a different ECDSA P-256 private key
        wrong_key_sig = sign_sendgrid_ecdsa_webhook(priv_2, ts_str, raw_body)
        res_wrong_key = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": wrong_key_sig,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_wrong_key.status_code == 403

        # 1c. Reject valid signature when payload is tampered by 1 byte
        valid_sig = sign_sendgrid_ecdsa_webhook(priv_1, ts_str, raw_body)
        res_tampered = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body + b" ",
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": valid_sig,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_tampered.status_code == 403

        # 1d. Reject legacy symmetric HMAC digest string
        legacy_hmac = hmac.new(pub_1_b64.encode("utf-8"), ts_str.encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
        res_hmac = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": legacy_hmac,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_hmac.status_code == 403

        # 1e. Confirm event was NOT persisted after all failed verification attempts
        assert not any(
            e.get("provider_event_id") == evt_id
            for e in supabase_service._in_memory_delivery_failure_events.values()
        )

        # 2. Accept valid ECDSA P-256 signature with Base64 SPKI key
        res_ok_b64 = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": valid_sig,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_ok_b64.status_code == 200
        assert res_ok_b64.json()["accepted"] is True

        # 3. Accept valid ECDSA P-256 signature with PEM-wrapped public key
        monkeypatch.setattr(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", pub_1_pem)
        res_ok_pem = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": valid_sig,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_ok_pem.status_code == 200

        # 4. Malformed SENDGRID_WEBHOOK_VERIFICATION_KEY fails closed with HTTP 500
        monkeypatch.setattr(settings, "SENDGRID_WEBHOOK_VERIFICATION_KEY", "not_a_valid_ecdsa_public_key")
        res_bad_key = await client.post(
            "/api/v1/webhook/delivery-failure/sendgrid",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": valid_sig,
                "X-Twilio-Email-Event-Webhook-Timestamp": ts_str,
            },
        )
        assert res_bad_key.status_code == 500


@pytest.mark.asyncio
async def test_p0_01_dev_test_bypass_blocked_when_staging_mode_enabled(monkeypatch):
    """
    Verify that test-only bypasses work ONLY when ENVIRONMENT in ('development', 'test')
    AND STAGING_MODE is false, and are blocked when STAGING_MODE is true or ENVIRONMENT='staging'.
    """
    monkeypatch.setattr(settings, "POSTMARK_WEBHOOK_SECRET", "")
    payload = {
        "RecordType": "Bounce",
        "ID": f"pm_staging_{uuid.uuid4()}",
        "Type": "HardBounce",
        "Email": "staging@brand.com",
        "MessageID": "msg_stg",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. ENVIRONMENT='staging' -> test token rejected with 500 (unconfigured secret)
        monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
        res_stg_env = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            json=payload,
            headers={"X-Postmark-Server-Token": "test_secret_token"},
        )
        assert res_stg_env.status_code == 500

        # 2. ENVIRONMENT='development' + STAGING_MODE='true' -> test token rejected with 500
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setenv("STAGING_MODE", "true")
        res_stg_flag = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            json=payload,
            headers={"X-Postmark-Server-Token": "test_secret_token"},
        )
        assert res_stg_flag.status_code == 500

        # 3. ENVIRONMENT='test' + STAGING_MODE='false' -> test token allowed when secret unconfigured
        monkeypatch.setenv("STAGING_MODE", "false")
        monkeypatch.setattr(settings, "ENVIRONMENT", "test")
        res_test_ok = await client.post(
            "/api/v1/webhook/delivery-failure/postmark",
            json=payload,
            headers={"X-Postmark-Server-Token": "test_secret_token"},
        )
        assert res_test_ok.status_code == 200

