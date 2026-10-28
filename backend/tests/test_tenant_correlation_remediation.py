"""
InboundCheck Enterprise - Group 36 Tenant Correlation & Failover Verification Suite
===================================================================================
Comprehensive regression tests for:
1. Multi-path tenant correlation (direct user_id, payload metadata, custom_args, user-variables).
2. Transactional message registry correlation (exact, angle brackets, SendGrid filter suffix, internal UUID).
3. Fallback correlation by order_id + recipient_email_hash.
4. Unique domain fallback correlation.
5. Strict tenant isolation on ambiguous domain lookups (fails closed, zero guessing).
6. Bounded deterministic retry for race condition / delayed message registration.
7. Retry exhaustion marking terminal failure.
8. Eligibility of hard_bounce / hardbounce events for Telegram incident dispatch.
9. Filtering out non-eligible message types (e.g. marketing, promotional).
10. Telegram dispatch failure handling.
"""

import pytest
import uuid
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from app.services.supabase_client import supabase_service
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import (
    telegram_alert_service,
    TelegramIncidentContext,
    TelegramDispatchResult,
)
from app.workers.failover_worker import (
    incident_factory,
    process_delivery_failure_event,
    canonicalize_event_type,
    TELEGRAM_INCIDENT_ELIGIBLE_EVENTS,
)


def _all_failover_logs():
    """Retrieve all persisted failover logs across all tenants in memory."""
    logs = []
    for tenant_logs in supabase_service._in_memory_failover_logs.values():
        logs.extend(tenant_logs)
    return logs


@pytest.fixture(autouse=True)
def clean_in_memory_state():
    """Ensure in-memory mock collections and mock mode are cleanly reset between tests."""
    supabase_service._in_memory_delivery_failure_events.clear()
    supabase_service._in_memory_failover_logs.clear()
    supabase_service._in_memory_transactional_messages.clear()
    supabase_service._in_memory_domains.clear()
    supabase_service._in_memory_stores.clear()
    telegram_alert_service.enable_mock_mode()
    yield
    telegram_alert_service.disable_mock_mode()
    supabase_service._in_memory_delivery_failure_events.clear()
    supabase_service._in_memory_failover_logs.clear()
    supabase_service._in_memory_transactional_messages.clear()
    supabase_service._in_memory_domains.clear()
    supabase_service._in_memory_stores.clear()


# =====================================================================
# 1. Direct Tenant ID & Metadata Extraction Tests
# =====================================================================

@pytest.mark.asyncio
async def test_correlation_direct_event_user_id():
    """Event already possesses user_id -> correlates directly and dispatches Telegram alert."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_{uuid.uuid4()}"
    evt_id = f"evt_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": "pm_direct_123",
        "event_type": "bounce",
        "user_id": user_id,
        "event_payload": {"order_id": "#1001", "details": "smtp 550"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "processed"

    # Confirm incident log created
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id
    assert logs[0]["order_id"] == "#1001"


@pytest.mark.asyncio
async def test_correlation_payload_metadata_user_id():
    """Event has user_id=None, but payload contains metadata.user_id -> successfully correlates."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_meta_{uuid.uuid4()}"
    evt_id = f"evt_meta_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "sg_meta_123",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {
            "metadata": {"user_id": user_id, "order_id": "#1002"},
            "reason": "Invalid mailbox",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "processed"
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_correlation_payload_custom_args_user_id():
    """Event has user_id in custom_args (SendGrid format) -> successfully correlates."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_custom_{uuid.uuid4()}"
    evt_id = f"evt_custom_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "sg_custom_456",
        "event_type": "dropped",
        "user_id": None,
        "event_payload": {
            "custom_args": {"user_id": user_id, "order_id": "#1003"},
            "reason": "Unsubscribed address",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "processed"
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


# =====================================================================
# 2. Transactional Message Registry Correlation Tests
# =====================================================================

@pytest.mark.asyncio
async def test_correlation_registry_exact_provider_message_id():
    """Correlates via transactional_message_registry with exact provider_message_id."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_reg_{uuid.uuid4()}"
    msg_id = f"msg_{uuid.uuid4()}"
    evt_id = f"evt_{uuid.uuid4()}"

    # Register outbound transactional message
    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id="#1004",
        recipient_email="customer@example.com",
        esp_provider="mailgun",
        provider_message_id=msg_id,
        message_type="order_receipt",
        domain_name="store.example.com",
        store_name="Demo Store",
    )

    evt = {
        "id": evt_id,
        "esp_provider": "mailgun",
        "provider_message_id": msg_id,
        "event_type": "rejected",
        "user_id": None,
        "event_payload": {"reason": "Policy rejection"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "processed"
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id
    assert logs[0]["order_id"] == "#1004"


@pytest.mark.asyncio
async def test_correlation_registry_angle_brackets_normalization():
    """Webhook has <id@mailgun.org> while registry has id@mailgun.org -> normalizes and correlates."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_mg_{uuid.uuid4()}"
    raw_id = f"20261027123456.abcdef@{uuid.uuid4()}.mailgun.org"
    evt_id = f"evt_{uuid.uuid4()}"

    # Stored without angle brackets
    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id="#1005",
        recipient_email="buyer@test.com",
        esp_provider="mailgun",
        provider_message_id=raw_id,
        message_type="shipping_update",
    )

    # Webhook arrives with angle brackets
    evt = {
        "id": evt_id,
        "esp_provider": "mailgun",
        "provider_message_id": f"<{raw_id}>",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {"reason": "550 5.1.1 User unknown"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_correlation_registry_sendgrid_filter_suffix_normalization():
    """Webhook has SendGrid composite message_id with filter suffix -> normalizes and correlates."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_sg_{uuid.uuid4()}"
    base_id = f"sg_{uuid.uuid4()}"
    composite_id = f"{base_id}.filterdrec-12345-abcde-0"
    evt_id = f"evt_{uuid.uuid4()}"

    # Stored with base message ID
    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id="#1006",
        recipient_email="buyer@test.com",
        esp_provider="sendgrid",
        provider_message_id=base_id,
        message_type="order_receipt",
    )

    # Webhook arrives with dot filter suffix
    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": composite_id,
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {"reason": "Mailbox quota exceeded"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


# =====================================================================
# 3. Fallback Correlation by Order ID + Recipient Email Hash
# =====================================================================

@pytest.mark.asyncio
async def test_correlation_by_order_id_and_recipient_hash():
    """When provider_message_id differs, correlates via order_id + recipient_email_hash."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_hash_{uuid.uuid4()}"
    order_id = "#1007"
    email = "customer@retailbrand.com"
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    evt_id = f"evt_{uuid.uuid4()}"

    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id=order_id,
        recipient_email=email,
        esp_provider="ses",
        provider_message_id="ses_msg_internal_999",
        message_type="order_receipt",
        domain_name="retailbrand.com",
    )

    # Webhook does not match ses_msg_internal_999, but contains order_id and recipient_email
    evt = {
        "id": evt_id,
        "esp_provider": "ses",
        "provider_message_id": "ses_unrelated_888",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {
            "order_id": order_id,
            "recipient_email": email,
            "reason": "Permanent bounce",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id
    assert logs[0]["order_id"] == order_id


# =====================================================================
# 4. Fallback Correlation by Domain & Strict Isolation
# =====================================================================

@pytest.mark.asyncio
async def test_correlation_by_unique_domain():
    """Single tenant monitors the sender domain -> correlates uniquely."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_domain_{uuid.uuid4()}"
    domain = "uniquelyownedbrand.com"
    evt_id = f"evt_{uuid.uuid4()}"

    # Register domain for tenant
    supabase_service.create_monitored_domain(
        user_id=user_id,
        domain_name=domain,
    )

    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": "pm_unknown_999",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {
            "sender": f"orders@{domain}",
            "order_id": "#1008",
            "reason": "Host not found",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_correlation_ambiguous_domain_fails_closed():
    """Domain monitored by multiple tenants -> FAILS CLOSED with zero cross-tenant guessing."""
    worker_id = f"worker_{uuid.uuid4()}"
    user1 = f"usr_tenant_1_{uuid.uuid4()}"
    user2 = f"usr_tenant_2_{uuid.uuid4()}"
    shared_domain = "sharedplatformstore.com"
    evt_id = f"evt_{uuid.uuid4()}"

    # Both tenants monitor same domain
    supabase_service.create_monitored_domain(user_id=user1, domain_name=shared_domain)
    supabase_service.create_monitored_domain(user_id=user2, domain_name=shared_domain)

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "sg_shared_999",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {
            "domain_name": shared_domain,
            "order_id": "#1009",
            "reason": "Policy rejection",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        # Absolutely NO dispatch must be triggered
        mock_dispatch.assert_not_called()

    # Must be marked failed with explicit ambiguity reason
    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert "Ambiguous tenant correlation" in stored.get("processing_error", "")
    # Zero logs created
    assert len(_all_failover_logs()) == 0


# =====================================================================
# 5. Bounded Deterministic Retry Tests (Delayed Registration Race)
# =====================================================================

@pytest.mark.asyncio
async def test_uncorrelated_delayed_registration_retry():
    """
    Scenario: Webhook arrives before transactional message registration (transient race condition).
    Attempt 1: Uncorrelated -> releases lease back to queue.
    Message arrives in registry.
    Attempt 2: Correlates successfully and dispatches incident.
    """
    worker_id = str(uuid.uuid4())
    user_id = f"usr_delayed_{uuid.uuid4()}"
    msg_id = f"delayed_msg_{uuid.uuid4()}"
    evt_id = str(uuid.uuid4())

    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": msg_id,
        "event_type": "bounce",
        "user_id": None,
        "processing_status": "queued",
        "claimed_by": worker_id,
        "event_payload": {
            "order_id": "#1010",
            "allow_delayed_retry": True,
            "max_correlation_attempts": 3,
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # 1. Attempt 1: Message not yet in registry -> Worker releases lease
    processed_1 = await process_delivery_failure_event(evt, worker_id)
    assert processed_1 is False

    stored_after_1 = supabase_service._in_memory_delivery_failure_events[evt_id]
    # Lease released: status is back to 'received'
    assert stored_after_1["processing_status"] == "received"
    assert stored_after_1["claimed_by"] is None
    # Correlation attempts counter recorded in payload
    assert stored_after_1["event_payload"]["correlation_attempts"] == 1

    # 2. Outbound message registration arrives in background
    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id="#1010",
        recipient_email="delayed@customer.com",
        esp_provider="postmark",
        provider_message_id=msg_id,
        message_type="order_receipt",
    )

    # 3. Attempt 2: Worker claims and re-processes event
    evt["event_payload"] = stored_after_1["event_payload"]
    evt["processing_status"] = "queued"
    evt["claimed_by"] = worker_id
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)
    processed_2 = await process_delivery_failure_event(evt, worker_id)
    assert processed_2 is True

    stored_after_2 = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored_after_2["processing_status"] == "processed"
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_uncorrelated_retry_exhaustion():
    """Delayed registration never arrives -> after max retries, transitions to failed with error."""
    worker_id = str(uuid.uuid4())
    msg_id = f"orphan_never_{uuid.uuid4()}"
    evt_id = str(uuid.uuid4())

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": msg_id,
        "event_type": "bounce",
        "user_id": None,
        "processing_status": "queued",
        "claimed_by": worker_id,
        "event_payload": {
            "order_id": "#1011",
            "allow_delayed_retry": True,
            "max_correlation_attempts": 3,
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # Attempt 1: releases lease
    res1 = await process_delivery_failure_event(evt, worker_id)
    assert res1 is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "received"
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["event_payload"]["correlation_attempts"] == 1

    # Attempt 2: releases lease
    evt["event_payload"] = supabase_service._in_memory_delivery_failure_events[evt_id]["event_payload"]
    evt["processing_status"] = "queued"
    evt["claimed_by"] = worker_id
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)
    res2 = await process_delivery_failure_event(evt, worker_id)
    assert res2 is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "received"
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["event_payload"]["correlation_attempts"] == 2

    # Attempt 3: max retries reached -> marks failed
    evt["event_payload"] = supabase_service._in_memory_delivery_failure_events[evt_id]["event_payload"]
    evt["processing_status"] = "queued"
    evt["claimed_by"] = worker_id
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)
    res3 = await process_delivery_failure_event(evt, worker_id)
    assert res3 is False
    final_stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert final_stored["processing_status"] == "failed"
    assert "Unable to correlate delivery failure to tenant (retries exhausted)" in final_stored.get("processing_error", "")


# =====================================================================
# 6. Hard Bounce Eligibility & Telegram Incident Creation
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("bounce_variant", ["hard_bounce", "hardbounce", "hard-bounce"])
async def test_hard_bounce_eligible_for_telegram_incident(bounce_variant):
    """
    Events with event_type='hard_bounce', 'hardbounce', or 'hard-bounce'
    MUST NOT be marked ignored; they must trigger Telegram incident creation.
    """
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_bounce_{uuid.uuid4()}"
    evt_id = f"evt_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "klaviyo",
        "provider_message_id": f"klav_{uuid.uuid4()}",
        "event_type": bounce_variant,
        "user_id": user_id,
        "event_payload": {"order_id": "#1012", "reason": "550 5.1.1 Recipient address rejected"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is True

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "processed"
    # Ensure not ignored
    assert stored.get("processing_status") != "ignored"
    # Ensure incident log created
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == user_id


# =====================================================================
# 7. Non-Eligible Events & Message Types Filtering
# =====================================================================

@pytest.mark.asyncio
async def test_non_eligible_event_type_ignored():
    """Transient errors (e.g. soft_bounce, deferred) are marked ignored."""
    worker_id = f"worker_{uuid.uuid4()}"
    evt_id = f"evt_soft_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "sg_soft_123",
        "event_type": "soft_bounce",
        "user_id": f"usr_{uuid.uuid4()}",
        "event_payload": {"reason": "Mailbox temporarily full"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_dispatch.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "ignored"
    assert "not Telegram-incident eligible" in stored.get("processing_error", "")
    assert len(_all_failover_logs()) == 0


@pytest.mark.asyncio
async def test_marketing_message_type_ignored():
    """Marketing or promotional emails are ignored even if they hard bounce."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_promo_{uuid.uuid4()}"
    msg_id = f"promo_msg_{uuid.uuid4()}"
    evt_id = f"evt_promo_{uuid.uuid4()}"

    supabase_service.record_transactional_message(
        user_id=user_id,
        order_id=None,
        recipient_email="promo@customer.com",
        esp_provider="mailgun",
        provider_message_id=msg_id,
        message_type="marketing",
    )

    evt = {
        "id": evt_id,
        "esp_provider": "mailgun",
        "provider_message_id": msg_id,
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {"reason": "550 User unknown"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_dispatch.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "ignored"
    assert len(_all_failover_logs()) == 0


# =====================================================================
# 8. Telegram Dispatch Failure Handling
# =====================================================================

@pytest.mark.asyncio
async def test_telegram_dispatch_failure_marks_event_failed():
    """If Telegram bot API returns failure, event is marked failed with error details."""
    worker_id = f"worker_{uuid.uuid4()}"
    user_id = f"usr_tg_fail_{uuid.uuid4()}"
    evt_id = f"evt_tg_fail_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": "pm_fail_123",
        "event_type": "bounce",
        "user_id": user_id,
        "event_payload": {"order_id": "#1015", "reason": "Hard bounce"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # Mock dispatch_alert returning failed
    failed_result = TelegramDispatchResult(
        success=False,
        provider="telegram",
        provider_status="failed",
        telegram_message_id=None,
        target_chat_id=None,
        error_message="Telegram API rate limit (HTTP 429)",
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock, return_value=failed_result):
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert "Telegram API rate limit (HTTP 429)" in stored.get("processing_error", "")
    assert len(_all_failover_logs()) == 0


# =====================================================================
# 9. Group 36.2 P0/P1 Adversarial Security & Reliability Test Suite
# =====================================================================

@pytest.mark.asyncio
async def test_conflicting_direct_user_id_and_registry_fails_closed():
    """P0: Direct event user_id conflicting with authoritative registry tenant must fail closed."""
    worker_id = f"worker_{uuid.uuid4()}"
    tenant_a = f"usr_a_{uuid.uuid4()}"
    tenant_b = f"usr_b_{uuid.uuid4()}"
    msg_id = f"sg_conflict_{uuid.uuid4()}"
    evt_id = f"evt_conflict_{uuid.uuid4()}"

    # Tenant B owns the message in registry
    supabase_service.record_transactional_message(
        user_id=tenant_b,
        order_id="#9999",
        recipient_email="customer@b.com",
        esp_provider="sendgrid",
        provider_message_id=msg_id,
        domain_name="store-b.com",
        store_name="Store B",
    )

    # Event arrives claiming Tenant A
    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": msg_id,
        "event_type": "hard_bounce",
        "user_id": tenant_a,
        "event_payload": {"order_id": "#1111", "reason": "550 unknown user"},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # Context must be marked ambiguous with empty user_id and zero tenant context merged
    ctx = incident_factory.from_event_and_registry(evt)
    assert ctx.is_ambiguous is True
    assert ctx.user_id == ""
    assert ctx.order_id is None
    assert ctx.domain_name is None
    assert ctx.store_name is None

    # Processing must fail closed: no alert, event marked failed
    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_dispatch.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert "Ambiguous tenant correlation" in stored.get("processing_error", "")
    assert len(_all_failover_logs()) == 0


@pytest.mark.asyncio
async def test_conflicting_payload_metadata_and_registry_fails_closed():
    """P0: Payload metadata user_id conflicting with authoritative registry tenant must fail closed."""
    worker_id = f"worker_{uuid.uuid4()}"
    tenant_a = f"usr_meta_a_{uuid.uuid4()}"
    tenant_b = f"usr_reg_b_{uuid.uuid4()}"
    msg_id = f"pm_conflict_{uuid.uuid4()}"
    evt_id = f"evt_conflict_{uuid.uuid4()}"

    # Registry message belongs to Tenant B
    supabase_service.record_transactional_message(
        user_id=tenant_b,
        order_id="#5555",
        recipient_email="customer@b.com",
        esp_provider="postmark",
        provider_message_id=msg_id,
        domain_name="store-b.com",
        store_name="Store B",
    )

    # Event has metadata claiming Tenant A
    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": msg_id,
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {
            "metadata": {"user_id": tenant_a},
            "reason": "Invalid address",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    ctx = incident_factory.from_event_and_registry(evt)
    assert ctx.is_ambiguous is True
    assert ctx.user_id == ""

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is False

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert len(_all_failover_logs()) == 0


@pytest.mark.asyncio
async def test_conflicting_tenant_context_is_not_merged():
    """P0: Ensure tenant B's order ID, domain, and store name are never merged into tenant A's context."""
    tenant_a = f"usr_a_{uuid.uuid4()}"
    tenant_b = f"usr_b_{uuid.uuid4()}"
    msg_id = f"msg_leak_test_{uuid.uuid4()}"
    evt_id = f"evt_leak_{uuid.uuid4()}"

    supabase_service.record_transactional_message(
        user_id=tenant_b,
        order_id="#SECRET_ORDER_B",
        recipient_email="victim@tenantb.com",
        esp_provider="sendgrid",
        provider_message_id=msg_id,
        domain_name="private-tenant-b.com",
        store_name="Private B Boutique",
    )

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": msg_id,
        "event_type": "hard_bounce",
        "user_id": tenant_a,
        "event_payload": {"reason": "550 user not found"},
    }

    ctx = incident_factory.from_event_and_registry(evt)
    assert ctx.is_ambiguous is True
    assert ctx.user_id == ""
    assert ctx.order_id is None
    assert ctx.domain_name is None
    assert ctx.store_name is None


@pytest.mark.asyncio
async def test_ambiguous_order_recipient_does_not_cascade_to_domain():
    """P1: When order_id + recipient match is ambiguous across tenants, halt immediately without domain fallback."""
    worker_id = f"worker_{uuid.uuid4()}"
    tenant_1 = str(uuid.uuid4())
    tenant_2 = str(uuid.uuid4())
    tenant_3 = str(uuid.uuid4())
    shared_order = "#COLLIDING_1001"
    email = "shared@buyer.com"
    h = hashlib.sha256(email.encode("utf-8")).hexdigest()
    evt_id = f"evt_order_ambig_{uuid.uuid4()}"

    # Both Tenant 1 and Tenant 2 have records for the same order + recipient hash
    supabase_service.record_transactional_message(
        user_id=tenant_1,
        order_id=shared_order,
        recipient_email=email,
        esp_provider="postmark",
        provider_message_id=f"pm_t1_{uuid.uuid4()}",
    )
    supabase_service.record_transactional_message(
        user_id=tenant_2,
        order_id=shared_order,
        recipient_email=email,
        esp_provider="postmark",
        provider_message_id=f"pm_t2_{uuid.uuid4()}",
    )

    # Tenant 3 uniquely monitors brand-store.com
    supabase_service.create_or_update_domain(tenant_3, "brand-store.com", is_active=True)

    # Event has colliding order+email and also mentions brand-store.com
    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": None,
        "event_type": "hard_bounce",
        "user_id": None,
        "event_payload": {
            "order_id": shared_order,
            "recipient_email": email,
            "recipient_email_hash": h,
            "from": "notifications@brand-store.com",
            "domain_name": "brand-store.com",
            "reason": "Hard bounce",
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    ctx = incident_factory.from_event_and_registry(evt)
    # Must fail closed as ambiguous and NOT attribute to Tenant 3!
    assert ctx.is_ambiguous is True
    assert ctx.user_id == ""
    assert ctx.domain_name is None

    processed = await process_delivery_failure_event(evt, worker_id)
    assert processed is False

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert len(_all_failover_logs()) == 0


def test_mailgun_dot_message_id_does_not_collide():
    """P1: Mailgun timestamped message IDs must not be split at the first dot."""
    tenant_1 = f"usr_mg_1_{uuid.uuid4()}"
    tenant_2 = f"usr_mg_2_{uuid.uuid4()}"
    msg_id_1 = "20261028120000.abc123def456@mailgun.org"
    msg_id_2 = "20261028120000.xyz789ghi012@mailgun.org"

    supabase_service.record_transactional_message(
        user_id=tenant_1,
        order_id="#101",
        recipient_email="r1@test.com",
        esp_provider="mailgun",
        provider_message_id=msg_id_1,
    )
    supabase_service.record_transactional_message(
        user_id=tenant_2,
        order_id="#102",
        recipient_email="r2@test.com",
        esp_provider="mailgun",
        provider_message_id=msg_id_2,
    )

    # Looking up msg_id_2 must return ONLY tenant 2
    res2 = supabase_service.get_transactional_message("mailgun", msg_id_2)
    assert res2 is not None
    assert res2["user_id"] == tenant_2
    assert res2["provider_message_id"] == msg_id_2

    # Querying prefix "20261028120000" must return None (not split arbitrary dots)
    res_prefix = supabase_service.get_transactional_message("mailgun", "20261028120000")
    assert res_prefix is None


def test_non_sendgrid_dot_ids_are_not_truncated():
    """P1: Dot splitting is restricted exclusively to SendGrid .filter suffix."""
    tenant_pm = f"usr_pm_{uuid.uuid4()}"
    pm_msg_id = "postmark.order.receipt.123"

    supabase_service.record_transactional_message(
        user_id=tenant_pm,
        order_id="#202",
        recipient_email="pm@test.com",
        esp_provider="postmark",
        provider_message_id=pm_msg_id,
    )

    # Postmark ID must not match by prefix "postmark"
    assert supabase_service.get_transactional_message("postmark", "postmark") is None
    # Must match by exact ID
    assert supabase_service.get_transactional_message("postmark", pm_msg_id) is not None

    # SendGrid ID with .filter DOES match base ID
    tenant_sg = f"usr_sg_{uuid.uuid4()}"
    base_sg_id = "sg_base_id_999"
    full_sg_filter_id = f"{base_sg_id}.filterdrecip001"

    supabase_service.record_transactional_message(
        user_id=tenant_sg,
        order_id="#303",
        recipient_email="sg@test.com",
        esp_provider="sendgrid",
        provider_message_id=base_sg_id,
    )

    # Incoming failure with .filter suffix matches registered base ID
    res_sg = supabase_service.get_transactional_message("sendgrid", full_sg_filter_id)
    assert res_sg is not None
    assert res_sg["user_id"] == tenant_sg


def test_uuid_lookup_cannot_cross_provider_boundary():
    """P1: UUID primary key lookup must be scoped to the specified ESP provider."""
    tenant_sg = str(uuid.uuid4())
    internal_uuid = str(uuid.uuid4())

    # Create message with internal UUID under sendgrid
    supabase_service.record_transactional_message(
        user_id=tenant_sg,
        order_id="#404",
        recipient_email="uuid@test.com",
        esp_provider="sendgrid",
        provider_message_id="sg_actual_id",
        message_id=internal_uuid,
    )

    # Query with matching UUID under sendgrid succeeds
    match_sg = supabase_service.get_transactional_message("sendgrid", internal_uuid)
    assert match_sg is not None
    assert match_sg["user_id"] == tenant_sg

    # Query with matching UUID under mailgun MUST return None (cannot cross provider boundary)
    match_mg = supabase_service.get_transactional_message("mailgun", internal_uuid)
    assert match_mg is None


@pytest.mark.asyncio
async def test_retry_payload_update_failure_does_not_release_lease():
    """P1: If updating retry attempt payload fails, worker must NOT release lease; mark failed."""
    worker_id = f"worker_{uuid.uuid4()}"
    evt_id = f"evt_db_fail_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "non_existent_msg_id",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {"reason": "550 unknown", "allow_delayed_retry": True},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # Mock update_event_payload returning False (simulating database exception or write rejection)
    with patch.object(repository, "update_event_payload", return_value=False), \
         patch.object(repository, "release_claimed_delivery_failure_event") as mock_release:

        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        # Lease must NOT be released!
        mock_release.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert "Failed to persist retry payload update" in stored.get("processing_error", "")


@pytest.mark.asyncio
async def test_retry_attempt_count_persists_across_reclaim():
    """P1: Attempt count persists and increments correctly across simulated worker reclaims."""
    worker_id = f"worker_{uuid.uuid4()}"
    evt_id = f"evt_retry_seq_{uuid.uuid4()}"

    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": "delayed_msg_1",
        "event_type": "bounce",
        "user_id": None,
        "event_payload": {"reason": "Temporary unresolvable host", "allow_delayed_retry": True},
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    # Attempt 1
    processed_1 = await process_delivery_failure_event(evt, worker_id)
    assert processed_1 is False

    stored_1 = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored_1["event_payload"]["correlation_attempts"] == 1
    assert "correlation_next_retry_at" in stored_1["event_payload"]

    # Attempt 2
    processed_2 = await process_delivery_failure_event(stored_1, worker_id)
    assert processed_2 is False

    stored_2 = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored_2["event_payload"]["correlation_attempts"] == 2


@pytest.mark.asyncio
async def test_retry_exhaustion_is_bounded():
    """P1: Retries are bounded by server-side limit (3 attempts), failing permanently on exhaustion."""
    worker_id = f"worker_{uuid.uuid4()}"
    evt_id = f"evt_exhaust_{uuid.uuid4()}"

    # Event already on attempt 2
    evt = {
        "id": evt_id,
        "esp_provider": "postmark",
        "provider_message_id": "will_never_match",
        "event_type": "hard_bounce",
        "user_id": None,
        "event_payload": {
            "correlation_attempts": 2,
            "reason": "Hard bounce permanent",
            "allow_delayed_retry": True,
        },
    }
    supabase_service._in_memory_delivery_failure_events[evt_id] = dict(evt)

    with patch.object(repository, "release_claimed_delivery_failure_event") as mock_release:
        processed = await process_delivery_failure_event(evt, worker_id)
        assert processed is False
        mock_release.assert_not_called()

    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "failed"
    assert "retries exhausted" in stored.get("processing_error", "")


def test_hard_bounce_variants_have_consistent_canonical_type():
    """Phase 8: Canonicalize hard bounce variants consistently across eligibility and context."""
    variants = ["hard_bounce", "hardbounce", "hard-bounce", "hard bounce", "HARD_BOUNCE", "Hard-Bounce"]
    for v in variants:
        canon = canonicalize_event_type(v)
        assert canon == "hard_bounce", f"Failed for variant: {v}"
        assert canon in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS, f"Not eligible: {canon}"

    assert canonicalize_event_type("bounce") == "bounce"
    assert "bounce" in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS

    # Dropped and rejected
    assert canonicalize_event_type("dropped") == "dropped"
    assert canonicalize_event_type("DROPPED") == "dropped"
    assert "dropped" in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS

    assert canonicalize_event_type("rejected") == "rejected"
    assert canonicalize_event_type("REJECTED") == "rejected"
    assert "rejected" in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS

    # Ineligible events
    for ineligible in ["soft_bounce", "soft-bounce", "delivered", "deferred", "complaint", "unsubscribe", "open", "click"]:
        canon = canonicalize_event_type(ineligible)
        assert canon not in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS, f"Ineligible event classified as eligible: {canon}"
