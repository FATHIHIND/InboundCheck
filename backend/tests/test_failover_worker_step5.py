"""
InboundCheck - Telegram Incident Alert Worker & Lifecycle Tests (Phase 4 Step 5)
================================================================================
Validates atomic event claiming, eligibility filtering, tenant correlation,
Telegram Markdown alert construction without PII, and failure/completion transitions.
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.workers.failover_worker import (
    process_delivery_failure_event,
    run_failover_worker,
    TELEGRAM_INCIDENT_ELIGIBLE_EVENTS,
    incident_factory,
)
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import (
    TelegramIncidentContext,
    TelegramDispatchResult,
    telegram_alert_service,
)
from app.services.supabase_client import supabase_service


@pytest.mark.asyncio
async def test_claim_received_delivery_failure_events_atomic():
    """Verify that claiming atomically moves events from 'received' to 'queued'."""
    worker_1 = str(uuid.uuid4())
    worker_2 = str(uuid.uuid4())

    event_id = f"evt_{uuid.uuid4()}"
    evt = supabase_service.record_delivery_failure_event(
        esp_provider="sendgrid",
        provider_event_id=event_id,
        provider_message_id="msg_test_claim_1",
        event_type="bounce",
        processing_status="received"
    )

    # Worker 1 claims
    claimed_w1 = repository.claim_received_delivery_failure_events(worker_id=worker_1, limit=100)
    claimed_ids = [e.get("id") for e in claimed_w1]
    assert evt["id"] in claimed_ids

    # Worker 2 attempts to claim simultaneously -> must NOT receive the already queued event
    claimed_w2 = repository.claim_received_delivery_failure_events(worker_id=worker_2, limit=100)
    w2_ids = [e.get("id") for e in claimed_w2]
    assert evt["id"] not in w2_ids


@pytest.mark.asyncio
async def test_non_eligible_event_types_are_ignored():
    """Deferred and complaint events must be marked ignored and NEVER trigger Telegram."""
    worker_id = str(uuid.uuid4())
    evt_id = f"evt_deferred_{uuid.uuid4()}"

    evt = supabase_service.record_delivery_failure_event(
        esp_provider="postmark",
        provider_event_id=evt_id,
        provider_message_id="msg_deferred_1",
        event_type="deferred",
        processing_status="queued"
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_dispatch.assert_not_called()

    # Verify event state in storage
    stored = supabase_service._in_memory_delivery_failure_events.get(str(("postmark", evt_id)))
    if stored:
        assert stored.get("processing_status") == "ignored"
        assert "not Telegram-incident eligible" in stored.get("processing_error", "")


@pytest.mark.asyncio
async def test_tenant_correlation_via_transactional_registry():
    """Verify event correlates order_id and user_id from transactional_message_registry."""
    user_id = str(uuid.uuid4())
    esp_provider = "mailgun"
    provider_msg_id = f"mg_corr_{uuid.uuid4()}"

    # 1. Register message in registry
    supabase_service.register_transactional_message(
        user_id=user_id,
        order_id="#10888",
        esp_provider=esp_provider,
        provider_message_id=provider_msg_id,
        recipient_email="customer@brand.com",
        message_type="order_confirmation"
    )

    # 2. Ingest failure without direct user_id
    evt_id = f"evt_{uuid.uuid4()}"
    evt = supabase_service.record_delivery_failure_event(
        esp_provider=esp_provider,
        provider_event_id=evt_id,
        provider_message_id=provider_msg_id,
        event_type="bounce",
        event_payload={"reason": "550 User unknown", "details": "Mailbox does not exist"},
        processing_status="queued"
    )

    # 3. Incident factory should derive user_id and order_id
    incident = incident_factory.from_event_and_registry(evt)
    assert incident.user_id == user_id
    assert incident.order_id == "#10888"
    assert incident.esp_provider == "mailgun"
    assert incident.failure_type == "bounce"


@pytest.mark.asyncio
async def test_uncorrelated_event_marked_failed():
    """An event that cannot be correlated to any tenant must be marked failed."""
    worker_id = str(uuid.uuid4())
    evt_id = f"evt_orphan_{uuid.uuid4()}"

    evt = supabase_service.record_delivery_failure_event(
        esp_provider="sendgrid",
        provider_event_id=evt_id,
        provider_message_id=f"msg_orphan_{uuid.uuid4()}",
        event_type="bounce",
        user_id=None,
        processing_status="queued"
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_dispatch.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events.get(str(("sendgrid", evt_id)))
    if stored:
        assert stored.get("processing_status") == "failed"
        assert "Unable to correlate delivery failure to tenant" in stored.get("processing_error", "")


@pytest.mark.asyncio
async def test_telegram_incident_dispatch_lifecycle_and_zero_pii():
    """Verify successful Telegram dispatch, markdown formatting without PII, and incident log creation."""
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    evt_id = f"evt_bounce_{uuid.uuid4()}"
    order_id = "#10999"

    evt = supabase_service.record_delivery_failure_event(
        esp_provider="postmark",
        provider_event_id=evt_id,
        provider_message_id="msg_bounce_pm",
        event_type="bounce",
        user_id=user_id,
        event_payload={"reason": "550 5.1.1 Recipient mailbox not found", "order_id": order_id},
        processing_status="queued"
    )

    # Mock Telegram Bot API send_telegram_alert directly to inspect rendered text
    with patch.object(telegram_alert_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "success": True,
            "data": {"result": {"message_id": 991823}}
        }

        success = await process_delivery_failure_event(evt, worker_id)
        assert success is True
        mock_send.assert_called_once()

        # Inspect alert markdown payload
        call_args = mock_send.call_args[1]
        text = call_args["text"]

        assert "🚨 *INBOUNDCHECK DELIVERY INCIDENT*" in text
        assert "Store:" in text
        assert "Domain:" in text
        assert order_id in text
        assert "ESP: POSTMARK" in text
        assert "Failure: BOUNCE" in text
        assert "Recommended action: Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan." in text
        assert "/dashboard/inspector?domain=" in text

        # ZERO-PII validation
        assert "@" not in text  # No email address
        assert "+1" not in text  # No phone number

    # Verify event marked processed
    stored = supabase_service._in_memory_delivery_failure_events.get(str(("postmark", evt_id)))
    if stored:
        assert stored.get("processing_status") == "processed"

    # Verify incident log exists in failover_logs
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) > 0
    tg_log = next((l for l in logs if l.get("delivery_failure_event_id") == evt["id"]), None)
    assert tg_log is not None
    assert tg_log["channel"] == "telegram"
    assert tg_log["status"] == "delivered"
    assert tg_log["provider_sid"] == "991823"
