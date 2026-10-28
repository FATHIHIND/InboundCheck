"""
InboundCheck - Delivery-Failure Ingestion & Transactional Message Registry Tests (Phase 4 Step 3)
=================================================================================================
Verifies transactional message correlation, delivery-failure event idempotency,
and Telegram incident-log persistence.
"""

import pytest
import uuid
import hashlib
from datetime import datetime, timezone

from app.services.supabase_client import supabase_service


@pytest.mark.asyncio
async def test_transactional_message_registration_and_hash():
    """Verify registration creates SHA-256 hash of email and preserves consent status."""
    user_id = f"test-user-{uuid.uuid4()}"
    esp_provider = "sendgrid"
    provider_message_id = f"msg_{uuid.uuid4()}"
    raw_email = "Merchant.Customer@Example.com"
    expected_hash = hashlib.sha256("merchant.customer@example.com".encode("utf-8")).hexdigest()

    record = supabase_service.register_transactional_message(
        user_id=user_id,
        order_id="#10991",
        esp_provider=esp_provider,
        provider_message_id=provider_message_id,
        recipient_email=raw_email,
        message_type="order_confirmation"
    )

    assert record["user_id"] == user_id
    assert record["order_id"] == "#10991"
    assert record["esp_provider"] == "sendgrid"
    assert record["provider_message_id"] == provider_message_id
    assert record["recipient_email_hash"] == expected_hash
    assert record["message_type"] == "order_confirmation"

    # Query back
    queried = supabase_service.get_transactional_message(esp_provider, provider_message_id)
    assert queried is not None
    assert queried["order_id"] == "#10991"
    assert queried["recipient_email_hash"] == expected_hash


@pytest.mark.asyncio
async def test_delivery_failure_event_idempotency():
    """Verify duplicate delivery-failure webhook events are deduplicated by (esp_provider, provider_event_id)."""
    esp_provider = "postmark"
    provider_event_id = f"evt_{uuid.uuid4()}"
    provider_message_id = f"msg_{uuid.uuid4()}"

    # First event
    evt1 = supabase_service.record_delivery_failure_event(
        esp_provider=esp_provider,
        provider_event_id=provider_event_id,
        provider_message_id=provider_message_id,
        event_type="hard_bounce",
        signature_verified=True,
        event_payload={"bounce_type": "Permanent", "details": "550 5.1.1 User Unknown"}
    )
    assert evt1["esp_provider"] == "postmark"
    assert evt1["provider_event_id"] == provider_event_id
    assert evt1["signature_verified"] is True
    assert evt1["processing_status"] == "received"

    # Duplicate replay of identical webhook event
    evt2 = supabase_service.record_delivery_failure_event(
        esp_provider=esp_provider,
        provider_event_id=provider_event_id,
        provider_message_id=provider_message_id,
        event_type="hard_bounce",
        signature_verified=True,
        event_payload={"bounce_type": "Permanent", "details": "550 5.1.1 User Unknown"}
    )
    assert evt2["id"] == evt1["id"]

    # Status update to processed
    updated = supabase_service.update_delivery_failure_event_status(
        event_id=evt1["id"],
        processing_status="processed",
        user_id="user_correlate_123"
    )
    assert updated is True


@pytest.mark.asyncio
async def test_failover_log_with_delivery_correlation_fields():
    """Verify failover_logs persist Telegram incident correlation fields."""
    user_id = f"test-user-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    log = supabase_service.persist_failover_log(
        user_id=user_id,
        order_id="#10992",
        channel="telegram",
        provider="telegram",
        status="delivered",
        domain_name="brandshop.com",
        store_name="BrandShop DTC",
        triggered_reason="hard_bounce",
        delivery_failure_event_id=event_id,
        transactional_message_id=msg_id,
        fallback_channel="telegram",
        provider_status="delivered"
    )

    assert log["user_id"] == user_id
    assert log["order_id"] == "#10992"
    assert log["delivery_failure_event_id"] == event_id
    assert log["transactional_message_id"] == msg_id
    assert log["fallback_channel"] == "telegram"
    assert log["provider"] == "telegram"
    assert log["status"] == "delivered"
    assert log["delivered_at"] is not None


@pytest.mark.asyncio
async def test_record_delivery_failure_event_production_guard_on_client_failure():
    """Verify in non-dev environments (e.g. production), database failures raise DatabaseUnavailableError."""
    from app.core.config import settings
    from app.services.supabase_client import DatabaseUnavailableError
    from unittest.mock import MagicMock

    original_env = settings.ENVIRONMENT
    original_client = supabase_service._client
    try:
        settings.ENVIRONMENT = "production"

        # Case 1: _client is None in production
        supabase_service._client = None
        evt_id = f"evt_prod_none_{uuid.uuid4()}"
        with pytest.raises(DatabaseUnavailableError) as exc_info:
            supabase_service.record_delivery_failure_event(
                esp_provider="postmark",
                provider_event_id=evt_id,
                provider_message_id=None,
                event_type="hard_bounce",
            )
        assert "Database client is not connected" in str(exc_info.value)

        # Case 2: Query / deduplication check raises exception
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("Connection timeout")
        supabase_service._client = mock_client
        with pytest.raises(DatabaseUnavailableError) as exc_info:
            supabase_service.record_delivery_failure_event(
                esp_provider="postmark",
                provider_event_id=evt_id,
                provider_message_id=None,
                event_type="hard_bounce",
            )
        assert "Database query failed during webhook deduplication check" in str(exc_info.value)

        # Case 3: Insert raises exception
        mock_query = MagicMock()
        mock_query.data = []  # No existing record
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = None
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_query
        mock_client.table.return_value.insert.return_value.execute.side_effect = Exception("Write replica offline")
        with pytest.raises(DatabaseUnavailableError) as exc_info:
            supabase_service.record_delivery_failure_event(
                esp_provider="postmark",
                provider_event_id=evt_id,
                provider_message_id=None,
                event_type="hard_bounce",
            )
        assert "Durable persistence failed for delivery failure event" in str(exc_info.value)

        # Case 4: Insert returns empty data
        empty_res = MagicMock()
        empty_res.data = []
        mock_client.table.return_value.insert.return_value.execute.side_effect = None
        mock_client.table.return_value.insert.return_value.execute.return_value = empty_res
        with pytest.raises(DatabaseUnavailableError) as exc_info:
            supabase_service.record_delivery_failure_event(
                esp_provider="postmark",
                provider_event_id=evt_id,
                provider_message_id=None,
                event_type="hard_bounce",
            )
        assert "database insert returned empty response" in str(exc_info.value)

    finally:
        settings.ENVIRONMENT = original_env
        supabase_service._client = original_client


@pytest.mark.asyncio
async def test_record_delivery_failure_event_dev_fallback_intact():
    """Verify development and test environments preserve in-memory fallback without raising."""
    from app.core.config import settings
    original_env = settings.ENVIRONMENT
    original_client = supabase_service._client
    try:
        settings.ENVIRONMENT = "development"
        supabase_service._client = None
        evt_id = f"evt_dev_{uuid.uuid4()}"
        record = supabase_service.record_delivery_failure_event(
            esp_provider="sendgrid",
            provider_event_id=evt_id,
            provider_message_id=None,
            event_type="hard_bounce",
        )
        assert record is not None
        assert record["provider_event_id"] == evt_id
    finally:
        settings.ENVIRONMENT = original_env
        supabase_service._client = original_client
