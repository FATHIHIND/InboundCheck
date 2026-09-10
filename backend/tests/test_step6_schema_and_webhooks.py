"""
InboundCheck - Step 6 Integration & Schema Alignment Tests
==========================================================
Tests:
1. Migration requirements & failover_logs schema:
   - channel = 'telegram'
   - fallback_channel = 'telegram'
   - provider = 'telegram'
   - status = 'delivered'
   - provider_status = 'delivered'
   - attempted_at & delivered_at timestamps
   - delivery_failure_event_id
   - triggered_reason
   - domain_name & order_id (with 'unknown' fallback)
   - zero customer phone population
2. Rejection of deprecated carrier / SMS / WhatsApp routes:
   - /api/v1/twilio/status -> 404
   - /api/v1/whatsapp/status -> 404
   - /api/v1/meta/status -> 404
   - /api/v1/carrier/dispatch -> 404
3. Worker claim RPC (claim_pending_delivery_failure_events):
   - Only claims events with processing_status = 'received'
   - Transitions claimed events to 'queued'
4. Zero phone / PII storage in transactional_message_registry
"""

import pytest
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.services.supabase_client import supabase_service
from app.services.failover.failover_repository import failover_repository

client = TestClient(app)


def test_deprecated_carrier_routes_rejected():
    """Verify that all carrier, Twilio, WhatsApp, and Meta webhook endpoints are rejected with 404."""
    for path in [
        "/api/v1/twilio/status",
        "/api/v1/whatsapp/status",
        "/api/v1/meta/status",
        "/api/v1/carrier/delivery-receipt",
        "/api/v1/carrier/webhook",
    ]:
        res_post = client.post(path, json={"status": "delivered"})
        assert res_post.status_code == 404, f"Expected 404 for POST {path}, got {res_post.status_code}"

        res_get = client.get(path)
        assert res_get.status_code == 404, f"Expected 404 for GET {path}, got {res_get.status_code}"


def test_failover_logs_required_columns_and_zero_phone():
    """Verify all required failover_logs columns are populated and customer phone is not."""
    user_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    
    # 1. Create with defaults/empty values -> must fallback to 'unknown'
    log = failover_repository.create_telegram_incident_log(
        delivery_failure_event_id=event_id,
        user_id=user_id,
        order_id=None,
        domain_name=None,
        store_name=None,
        triggered_reason="550 5.1.1 User unknown",
        target_chat_id="@merchant_alerts",
        provider_status="delivered",
        provider_message_id="tg_msg_999",
    )

    assert log["channel"] == "telegram"
    assert log["fallback_channel"] == "telegram"
    assert log["provider"] == "telegram"
    assert log["provider_status"] == "delivered"
    assert log["status"] == "delivered"
    assert log["attempted_at"] is not None
    assert log["delivered_at"] is not None
    assert log["delivery_failure_event_id"] == event_id
    assert log["triggered_reason"] == "550 5.1.1 User unknown"
    assert log["domain_name"] == "unknown"
    assert log["order_id"] == "unknown"
    assert "customer_phone" not in log or log.get("customer_phone") is None


def test_claim_pending_delivery_failure_events_semantics():
    """Verify claim_pending_delivery_failure_events only claims received events and marks them queued."""
    worker_id = str(uuid.uuid4())
    
    # Seed events
    evt_received = supabase_service.record_delivery_failure_event(
        esp_provider="postmark",
        provider_event_id=f"evt_{uuid.uuid4()}",
        provider_message_id=f"msg_{uuid.uuid4()}",
        event_type="bounce",
        processing_status="received",
    )
    evt_processed = supabase_service.record_delivery_failure_event(
        esp_provider="postmark",
        provider_event_id=f"evt_{uuid.uuid4()}",
        provider_message_id=f"msg_{uuid.uuid4()}",
        event_type="bounce",
        processing_status="processed",
    )

    # Claim
    claimed = failover_repository.claim_pending_delivery_failure_events(
        worker_id=worker_id,
        limit=20,
    )

    claimed_ids = [e["id"] for e in claimed]
    assert evt_received["id"] in claimed_ids
    assert evt_processed["id"] not in claimed_ids

    # The claimed event must now be queued
    for c in claimed:
        if c["id"] == evt_received["id"]:
            assert c["processing_status"] == "queued"


def test_transactional_message_zero_phone_storage():
    """Verify register_transactional_message ignores deprecated phone kwargs and stores zero phone PII."""
    user_id = str(uuid.uuid4())
    msg_id = f"msg_{uuid.uuid4()}"

    record = supabase_service.register_transactional_message(
        user_id=user_id,
        order_id="#10882",
        esp_provider="ses",
        provider_message_id=msg_id,
        recipient_email="test.customer@gmail.com",
        recipient_phone_encrypted="+1234567890", # deprecated kwarg
        phone_consent_status="consented",         # deprecated kwarg
    )

    assert "recipient_phone_encrypted" not in record
    assert "phone_consent_status" not in record
    assert record["order_id"] == "#10882"
    assert record["esp_provider"] == "ses"
    assert record["provider_message_id"] == msg_id
