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

    with patch("app.workers.failover_worker.omnichannel_service.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"status": "delivered", "log_id": "tg_mock_1"}
        success = await process_failover_event(event, worker_id)
        assert success is True
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args.kwargs["channel"] == "telegram"
        assert mock_dispatch.call_args.kwargs["esp_provider"] == "postmark"
