"""
InboundCheck - Integration Tests for Dedicated Workers (Phase 4 Step 2)
=======================================================================
Verifies:
1. sanitize_error masks credentials and truncates messages.
2. audit_claimed_domain completes domain lease upon success.
3. audit_claimed_domain fails domain lease and logs sanitized error on failure.
4. run_audit_worker loop honors stop_event termination.
5. failover_worker processes eligible delivery failures as Telegram incidents.
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from app.services.supabase_client import supabase_service
from app.workers.audit_worker import (
    sanitize_error,
    audit_claimed_domain,
    run_audit_worker,
)
from app.workers.failover_worker import (
    process_failover_event,
    run_failover_worker,
)


def test_sanitize_error_masks_sensitive_tokens():
    """Verify that credentials, tokens, and verbose traces are redacted."""
    raw_error = "Failed to connect: token=secret123456789 and bearer=eyJh... password=supersecret"
    sanitized = sanitize_error(Exception(raw_error))
    assert "secret123456789" not in sanitized
    assert "supersecret" not in sanitized
    assert "[REDACTED]" in sanitized

    # Test long truncation
    long_error = "A" * 1000
    sanitized_long = sanitize_error(Exception(long_error))
    assert len(sanitized_long) <= 500


@pytest.mark.asyncio
async def test_audit_claimed_domain_success_lifecycle():
    """Verify that a leased domain audit succeeds and releases lease cleanly."""
    user_id = f"test-worker-user-{uuid.uuid4()}"
    worker_id = str(uuid.uuid4())
    dom_id = f"dom_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "worker-success.com",
        "is_active": True,
        "audit_lease_owner": worker_id,
        "audit_lease_until": (datetime.now(timezone.utc)).isoformat(),
    }
    supabase_service._in_memory_domains[user_id] = [domain]

    # Execute audit
    await audit_claimed_domain(domain, worker_id)

    # Check lease was completed and released
    assert domain.get("audit_lease_owner") is None
    assert domain.get("last_audited_at") is not None
    assert domain.get("audit_failure_count") == 0


@pytest.mark.asyncio
async def test_audit_claimed_domain_failure_lifecycle():
    """Verify that an exception in audit fails the lease and records sanitized error."""
    user_id = f"test-worker-user-{uuid.uuid4()}"
    worker_id = str(uuid.uuid4())
    dom_id = f"dom_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "worker-fail.com",
        "is_active": True,
        "audit_lease_owner": worker_id,
        "audit_lease_until": (datetime.now(timezone.utc)).isoformat(),
    }
    supabase_service._in_memory_domains[user_id] = [domain]

    with patch("app.workers.audit_worker.diagnostic_engine.audit_domain", side_effect=ValueError("DNS socket error key=secrettoken")):
        await audit_claimed_domain(domain, worker_id)

    assert domain.get("audit_lease_owner") is None
    assert domain.get("audit_failure_count", 0) >= 1
    assert "DNS socket error" in domain.get("last_audit_error", "")
    assert "secrettoken" not in domain.get("last_audit_error", "")


@pytest.mark.asyncio
async def test_run_audit_worker_graceful_stop():
    """Verify that run_audit_worker terminates immediately when stop_event is set."""
    stop_event = asyncio.Event()
    stop_event.set()  # Immediately set

    # Should exit loop without blocking
    await run_audit_worker(stop_event=stop_event, idle_sleep_seconds=1)


@pytest.mark.asyncio
async def test_failover_worker_processing():
    """Verify failover worker event processing."""
    event = {
        "id": "evt_test_123",
        "user_id": "test-user-failover",
        "order_id": "#10999",
        "domain_name": "testshop.com",
        "store_name": "Test Store",
        "event_type": "bounce",
        "esp_provider": "postmark",
        "event_payload": {"details": "550 mailbox unavailable"},
    }
    worker_id = str(uuid.uuid4())

    with patch("app.workers.failover_worker.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"status": "delivered", "log_id": "tg_mock_1", "success": True}
        success = await process_failover_event(event, worker_id)
        assert success is True
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["bounce", "dropped", "rejected"])
async def test_eligible_events_invoke_telegram_alert(event_type: str):
    """Verify that bounce, dropped, and rejected events invoke TelegramAlertService.dispatch_alert()."""
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())
    event = {
        "id": evt_id,
        "user_id": user_id,
        "order_id": "#12001",
        "domain_name": "brandshop.com",
        "store_name": "Brand DTC",
        "event_type": event_type,
        "esp_provider": "sendgrid",
        "event_payload": {"reason": "550 mailbox dropped/rejected"},
    }
    worker_id = str(uuid.uuid4())

    with patch("app.workers.failover_worker.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"status": "delivered", "telegram_message_id": "tg_999", "success": True}
        res = await process_failover_event(event, worker_id)
        assert res is True
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["deferred", "complaint", "open", "click"])
async def test_non_eligible_events_do_not_invoke_telegram(event_type: str):
    """Verify that deferred, complaint, or other events do not invoke Telegram dispatch."""
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())
    event = {
        "id": evt_id,
        "user_id": user_id,
        "order_id": "#12002",
        "domain_name": "brandshop.com",
        "store_name": "Brand DTC",
        "event_type": event_type,
        "esp_provider": "mailgun",
        "event_payload": {"reason": "Soft bounce retry later"},
    }
    worker_id = str(uuid.uuid4())

    with patch("app.workers.failover_worker.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        await process_failover_event(event, worker_id)
        mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_successful_dispatch_writes_log_and_marks_processed():
    """Verify successful dispatch writes complete failover_logs record and marks event processed."""
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())
    event = {
        "id": evt_id,
        "user_id": user_id,
        "order_id": "#12003",
        "domain_name": "ordershop.com",
        "store_name": "Order DTC",
        "event_type": "bounce",
        "esp_provider": "postmark",
        "event_payload": {"details": "550 5.1.1 User unknown"},
    }
    worker_id = str(uuid.uuid4())

    # Seed in-memory event so we can check state transitions
    key = str(("postmark", evt_id))
    supabase_service._in_memory_delivery_failure_events[key] = {
        "id": evt_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
    }

    with patch("app.workers.failover_worker.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {
            "status": "delivered",
            "provider": "telegram",
            "telegram_message_id": "tg_msg_success_123",
            "success": True,
        }
        res = await process_failover_event(event, worker_id)
        assert res is True

    # 1. Verify log attributes
    logs = supabase_service.get_failover_logs(user_id=user_id)
    assert len(logs) >= 1
    log = logs[0]
    assert log["fallback_channel"] == "telegram"
    assert log["channel"] == "telegram"
    assert log["provider"] == "telegram"
    assert log["provider_status"] == "delivered"
    assert log["status"] == "delivered"
    assert log["attempted_at"] is not None
    assert log["delivered_at"] is not None
    assert log["delivery_failure_event_id"] == evt_id

    # 2. Verify source event marked processed
    cached_evt = supabase_service._in_memory_delivery_failure_events.get(key)
    assert cached_evt is not None
    assert cached_evt["processing_status"] == "processed"


@pytest.mark.asyncio
async def test_telegram_failure_marks_event_failed():
    """Verify that when Telegram dispatch fails, event is marked failed."""
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())
    event = {
        "id": evt_id,
        "user_id": user_id,
        "order_id": "#12004",
        "domain_name": "failshop.com",
        "store_name": "Fail DTC",
        "event_type": "bounce",
        "esp_provider": "ses",
        "event_payload": {"reason": "550 Mailbox does not exist"},
    }
    worker_id = str(uuid.uuid4())

    key = str(("ses", evt_id))
    supabase_service._in_memory_delivery_failure_events[key] = {
        "id": evt_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
    }

    with patch("app.workers.failover_worker.telegram_alert_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {
            "status": "failed",
            "provider": "telegram",
            "error_message": "Bot blocked by user or invalid chat ID",
            "success": False,
        }
        res = await process_failover_event(event, worker_id)
        assert res is False

    cached_evt = supabase_service._in_memory_delivery_failure_events.get(key)
    assert cached_evt is not None
    assert cached_evt["processing_status"] == "failed"
    assert "Bot blocked" in (cached_evt.get("processing_error") or "")
