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
from datetime import datetime, timezone, timedelta
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


# =====================================================================
# PHASE 2.3 WORKER PRODUCTION READINESS & SCHEDULER TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_worker_runner_main_validates_environment():
    """Verify that worker runner main() executes fail-fast validate_runtime_environment()."""
    from app.workers.runner import main as runner_main

    with patch("app.workers.runner.validate_runtime_environment") as mock_val, \
         patch("app.workers.runner.run_audit_worker", new_callable=AsyncMock) as mock_worker:
        await runner_main("audit")
        mock_val.assert_called_once()
        mock_worker.assert_called_once()


@pytest.mark.asyncio
async def test_worker_runner_all_mode_concurrent_dispatch():
    """Verify that runner main('all') concurrently launches both audit and failover workers."""
    from app.workers.runner import main as runner_main

    with patch("app.workers.runner.validate_runtime_environment"), \
         patch("app.workers.runner.run_audit_worker", new_callable=AsyncMock) as mock_audit, \
         patch("app.workers.runner.run_failover_worker", new_callable=AsyncMock) as mock_failover:
        await runner_main("all")
        mock_audit.assert_called_once()
        mock_failover.assert_called_once()


@pytest.mark.asyncio
async def test_ops_alert_service_telegram_settings_fallback():
    """Verify OpsAlertService correctly detects TELEGRAM_BOT_TOKEN when OPS_ALERT_ prefix is omitted."""
    from app.services.alerting.ops_alert_service import OpsAlertService
    from app.core.config import settings

    with patch.object(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", ""), \
         patch.object(settings, "OPS_ALERT_TELEGRAM_CHAT_ID", ""), \
         patch.object(settings, "TELEGRAM_BOT_TOKEN", "fallback_token_12345"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-100123456789"):
        svc = OpsAlertService()
        assert svc.telegram_bot_token == "fallback_token_12345"
        assert svc.telegram_chat_id == "-100123456789"
        assert svc.is_configured() is True


@pytest.mark.asyncio
async def test_ops_alert_service_webhook_dispatch_success():
    """Verify OpsAlertService dispatches sanitized incident to configured webhook."""
    from app.services.alerting.ops_alert_service import OpsAlertService, OpsIncident
    from unittest.mock import MagicMock

    svc = OpsAlertService()
    svc.webhook_url = "https://hooks.slack.com/services/test/mock/webhook"
    svc.telegram_bot_token = ""
    svc.telegram_chat_id = ""

    mock_resp = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        incident = OpsIncident(
            alert_id="ALERT-TEST-OPS",
            severity="P1",
            summary="Worker heartbeat probe",
            details={"api_key": "secret_abc_123", "normal": "value"},
        )
        sent = await svc.dispatch_incident(incident)
        assert sent is True
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args[1]
        sent_json = call_kwargs.get("json", {})
        assert sent_json.get("alert_id") == "ALERT-TEST-OPS"
        # Verify sanitization
        assert sent_json["details"]["api_key"] == "[REDACTED]"
        assert sent_json["details"]["normal"] == "value"


@pytest.mark.asyncio
async def test_audit_worker_scheduled_sweep_lifecycle():
    """
    Verify complete scheduled audit worker cycle:
    1. Discovers due domain
    2. Claims lease via claim_due_domain_audits
    3. Runs DNS and RBL audits
    4. Persists audit log to dns_audit_logs
    5. Releases lease and sets last_audited_at
    """
    user_id = str(uuid.uuid4())
    dom_id = str(uuid.uuid4())
    now_past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "auto-scheduled-audit.com",
        "is_active": True,
        "last_audited_at": now_past,
    }
    supabase_service._in_memory_domains[user_id] = [domain]

    stop_event = asyncio.Event()

    # Run one pass of audit worker and stop after first batch
    orig_claim = supabase_service.claim_due_domain_audits
    def claim_and_stop(*args, **kwargs):
        res = orig_claim(*args, **kwargs)
        stop_event.set()
        return res

    with patch.object(supabase_service, "_client", None):
        with patch.object(supabase_service, "claim_due_domain_audits", side_effect=claim_and_stop):
            await run_audit_worker(stop_event=stop_event, idle_sleep_seconds=1)

        # Assert domain was audited and lease released
        assert domain.get("audit_lease_owner") is None
        assert domain.get("last_audited_at") is not None
        assert domain.get("health_score") is not None
        assert domain.get("spf_status") is not None

        # Assert audit log was recorded
        history = supabase_service.get_audit_history(user_id=user_id, domain_name="auto-scheduled-audit.com")
        assert len(history) >= 1
        assert history[0]["domain_name"] == "auto-scheduled-audit.com"
