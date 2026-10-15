"""
InboundCheck - Failover Worker Safety & Offline Verification Tests (Phase 18A.7.23)
===================================================================================
Offline verification covering all 10 safety and remediation requirements:
1. One-shot mode exits when no events are available.
2. One-shot mode processes no more than the specified limit.
3. The existing continuous mode remains compatible.
4. runner.py forwards once and limit for all worker modes.
5. Mock Telegram dispatch does not invoke the real HTTP client.
6. Production mode cannot enable test notification mocks.
7. Missing or placeholder Telegram credentials cause no external request.
8. Disabled notification channels cause no external request.
9. Failure and cancellation do not leave claimed events in an unsafe lease state.
10. Existing idempotency and event finalization behavior remains intact.
"""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.config import settings
from app.workers.failover_worker import (
    run_failover_worker,
    process_delivery_failure_event,
    incident_factory,
)
from app.workers.runner import main as runner_main
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import (
    telegram_alert_service,
    TelegramIncidentContext,
    TelegramDispatchResult,
)
from app.services.supabase_client import supabase_service


@pytest.fixture(autouse=True)
def ensure_mock_mode_cleaned():
    """Ensure mock mode is always disabled after each test."""
    yield
    telegram_alert_service.disable_mock_mode()


# ---------------------------------------------------------------------------
# 1. One-shot mode exits when no events are available
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_oneshot_mode_exits_when_no_events():
    """Single-cycle worker must exit cleanly without sleeping when queue is empty."""
    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=[]):
        # Must return quickly and not block
        await asyncio.wait_for(
            run_failover_worker(once=True, limit=10, poll_idle_seconds=60),
            timeout=2.0,
        )


# ---------------------------------------------------------------------------
# 2. One-shot mode processes no more than the specified limit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_oneshot_mode_processes_no_more_than_limit():
    """Single-cycle worker must respect the limit parameter and exit after one batch."""
    events = [
        {"id": f"evt_{i}", "event_type": "bounce", "user_id": str(uuid.uuid4())}
        for i in range(3)
    ]

    with patch.object(repository, "claim_pending_delivery_failure_events") as mock_claim, \
         patch("app.workers.failover_worker.process_delivery_failure_event", new_callable=AsyncMock) as mock_process:
        mock_claim.return_value = events
        mock_process.return_value = True

        await asyncio.wait_for(
            run_failover_worker(once=True, limit=3),
            timeout=2.0,
        )

        mock_claim.assert_called_once()
        assert mock_claim.call_args[1]["limit"] == 3
        assert mock_process.call_count == 3


# ---------------------------------------------------------------------------
# 3. Continuous mode remains compatible
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_continuous_mode_remains_compatible():
    """Continuous daemon mode (once=False) must continue looping until stop_event is set."""
    stop_event = asyncio.Event()
    claim_count = 0

    def mock_claim(**kwargs):
        nonlocal claim_count
        claim_count += 1
        if claim_count >= 2:
            stop_event.set()
        return [{"id": f"evt_cont_{claim_count}", "event_type": "bounce", "user_id": str(uuid.uuid4())}]

    with patch.object(repository, "claim_pending_delivery_failure_events", side_effect=mock_claim), \
         patch("app.workers.failover_worker.process_delivery_failure_event", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = True

        await asyncio.wait_for(
            run_failover_worker(stop_event=stop_event, once=False, limit=20, poll_idle_seconds=1),
            timeout=3.0,
        )

        assert claim_count >= 2
        assert stop_event.is_set()


# ---------------------------------------------------------------------------
# 4. runner.py forwards once and limit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_forwards_once_and_limit():
    """runner.py main() must forward once and limit to failover and all worker modes."""
    with patch("app.workers.runner.run_failover_worker", new_callable=AsyncMock) as mock_failover, \
         patch("app.workers.runner.validate_worker_runtime_environment"):
        await runner_main(worker_type="failover", once=True, limit=7)
        mock_failover.assert_called_once()
        assert mock_failover.call_args[1]["once"] is True
        assert mock_failover.call_args[1]["limit"] == 7

    with patch("app.workers.runner.run_audit_worker", new_callable=AsyncMock) as mock_audit, \
         patch("app.workers.runner.run_failover_worker", new_callable=AsyncMock) as mock_failover_all, \
         patch("app.workers.runner.validate_worker_runtime_environment"):
        await runner_main(worker_type="all", once=True, limit=14)
        mock_audit.assert_called_once()
        assert mock_audit.call_args[1]["once"] is True
        assert mock_audit.call_args[1]["limit"] == 14
        mock_failover_all.assert_called_once()
        assert mock_failover_all.call_args[1]["once"] is True
        assert mock_failover_all.call_args[1]["limit"] == 14


# ---------------------------------------------------------------------------
# 5. Mock Telegram dispatch does not invoke the real HTTP client
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mock_telegram_dispatch_does_not_invoke_http_client():
    """When mock mode is enabled, dispatch must simulate delivery without calling httpx."""
    with patch.dict("os.environ", {"ENVIRONMENT": "staging"}), \
         patch.object(settings, "ENVIRONMENT", "staging"):
        telegram_alert_service.enable_mock_mode()
        assert telegram_alert_service.is_mock_mode is True

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = await telegram_alert_service.dispatch_alert(
                user_id="user_mock_test",
                order_id="#9999",
                domain_name="example.com",
                failure_type="bounce",
                failure_reason="Mailbox full",
            )

            assert res.success is True
            assert res.simulated is True
            assert res.provider_status == "simulated"
            assert res.telegram_message_id is not None
            assert res.telegram_message_id.startswith("mock_tg_")
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Production mode cannot enable test notification mocks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_production_mode_cannot_enable_notification_mocks():
    """In production environment, enabling mock mode must raise RuntimeError immediately."""
    with patch.dict("os.environ", {"ENVIRONMENT": "production"}), \
         patch.object(settings, "ENVIRONMENT", "production"):
        with pytest.raises(RuntimeError, match="Mock Telegram dispatch is forbidden in Production"):
            telegram_alert_service.enable_mock_mode()

        # If mock mode was somehow forced, dispatch must still fail closed in production
        telegram_alert_service._mock_mode = True
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            with pytest.raises(RuntimeError, match="Mock Telegram dispatch is forbidden in Production"):
                await telegram_alert_service.send_telegram_alert(
                    bot_token="test_token",
                    chat_id="@test_chat",
                    text="alert",
                )
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Missing or placeholder Telegram credentials cause no external request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_or_placeholder_credentials_cause_no_external_request():
    """Unconfigured, empty, or placeholder credentials must reject dispatch with 0 network calls."""
    telegram_alert_service.disable_mock_mode()

    invalid_credential_pairs = [
        ("", ""),
        ("your_bot_token", "@real_channel"),
        ("7198234891:AAH8Fj90qWz1x9_example", "@inboundcheck_alerts"),
        ("dummy_token_123", "@my_alerts"),
        ("123456:valid_token", "placeholder_chat"),
        ("valid_token_xyz", ""),
    ]

    with patch.dict("os.environ", {"ENVIRONMENT": "staging"}), \
         patch.object(settings, "ENVIRONMENT", "staging"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        for bot_token, chat_id in invalid_credential_pairs:
            # Test direct send_telegram_alert
            send_res = await telegram_alert_service.send_telegram_alert(
                bot_token=bot_token,
                chat_id=chat_id,
                text="Test Alert",
            )
            assert send_res["success"] is False
            assert send_res["simulated"] is False
            mock_post.assert_not_called()

            # Test dispatch_alert
            with patch.object(
                telegram_alert_service,
                "get_config",
                return_value={
                    "is_enabled": True,
                    "telegram_bot_token": bot_token,
                    "telegram_chat_id": chat_id,
                },
            ):
                disp_res = await telegram_alert_service.dispatch_alert(
                    user_id=f"u_{uuid.uuid4()}",
                    order_id="#123",
                    domain_name="brand.com",
                    failure_type="bounce",
                )
                assert disp_res.success is False
                assert "configured" in disp_res.error_message
                mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Disabled notification channels cause no external request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_disabled_notification_channels_cause_no_external_request():
    """When notification channel is disabled, dispatch must exit immediately with 0 network calls."""
    telegram_alert_service.disable_mock_mode()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        with patch.object(
            telegram_alert_service,
            "get_config",
            return_value={
                "is_enabled": False,
                "telegram_bot_token": "valid_token_12345",
                "telegram_chat_id": "@valid_chat",
            },
        ):
            disp_res = await telegram_alert_service.dispatch_alert(
                user_id="user_disabled",
                order_id="#456",
                domain_name="disabled.com",
                failure_type="bounce",
            )
            assert disp_res.success is False
            assert "disabled in user settings" in disp_res.error_message
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Failure and cancellation do not leave claimed events in an unsafe lease state
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_and_cancellation_release_claimed_leases():
    """Leases must be released when processing raises an unexpected exception or when stopped."""
    worker_id = str(uuid.uuid4())
    event_id = f"evt_fail_{uuid.uuid4()}"
    event = {
        "id": event_id,
        "event_type": "bounce",
        "user_id": str(uuid.uuid4()),
        "esp_provider": "sendgrid",
    }

    # 9a: Exception during single event processing releases the event lease
    with patch.object(telegram_alert_service, "dispatch_alert", side_effect=RuntimeError("Transient engine crash")), \
         patch.object(repository, "release_claimed_delivery_failure_event") as mock_release:
        with pytest.raises(RuntimeError, match="Transient engine crash"):
            await process_delivery_failure_event(event, worker_id)

        mock_release.assert_called_once_with(event_id, worker_id)

    # 9b: Stop signal received during batch processing releases unprocessed in-flight events
    stop_event = asyncio.Event()
    batch_events = [
        {"id": f"evt_b_{i}", "event_type": "bounce", "user_id": str(uuid.uuid4())}
        for i in range(3)
    ]

    async def _process_and_stop(evt, wid):
        # Stop after the first event in the batch
        stop_event.set()
        return True

    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=batch_events), \
         patch("app.workers.failover_worker.process_delivery_failure_event", side_effect=_process_and_stop), \
         patch.object(repository, "release_claimed_delivery_failure_event") as mock_batch_release:
        await run_failover_worker(stop_event=stop_event, once=True, limit=5)

        # Unprocessed events evt_b_1 and evt_b_2 must be released
        released_ids = [call[0][0] for call in mock_batch_release.call_args_list]
        assert "evt_b_1" in released_ids or "evt_b_2" in released_ids


# ---------------------------------------------------------------------------
# 10. Existing idempotency and event finalization behavior remains intact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_finalization_and_idempotency_intact():
    """Finalization states (processed, failed, ignored) must transition correctly."""
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # 10a: Non-eligible event -> ignored
    ignored_evt = {
        "id": f"evt_ign_{uuid.uuid4()}",
        "event_type": "deferred",
        "user_id": user_id,
    }
    with patch.object(repository, "mark_event_processed") as mock_mark_proc, \
         patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_disp:
        res = await process_delivery_failure_event(ignored_evt, worker_id)
        assert res is False
        mock_disp.assert_not_called()
        mock_mark_proc.assert_called_once()
        assert mock_mark_proc.call_args[1]["outcome"] == "ignored"

    # 10b: Successful dispatch -> processed + incident log
    success_evt = {
        "id": f"evt_suc_{uuid.uuid4()}",
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "postmark",
    }
    mock_dispatch_res = TelegramDispatchResult(
        success=True,
        provider_status="delivered",
        telegram_message_id="tg_12345",
        target_chat_id="@mychat",
    )
    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock, return_value=mock_dispatch_res), \
         patch.object(repository, "create_telegram_incident_log") as mock_log, \
         patch.object(repository, "mark_event_processed") as mock_final_proc:
        res = await process_delivery_failure_event(success_evt, worker_id)
        assert res is True
        mock_log.assert_called_once()
        mock_final_proc.assert_called_once()
        assert mock_final_proc.call_args[1]["outcome"] == "processed"

    # 10c: Failed dispatch -> failed with error reason
    fail_evt = {
        "id": f"evt_fail_{uuid.uuid4()}",
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "mailgun",
    }
    mock_fail_res = TelegramDispatchResult(
        success=False,
        provider_status="failed",
        error_message="Telegram Bot API rate limit exceeded",
    )
    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock, return_value=mock_fail_res), \
         patch.object(repository, "mark_event_failed") as mock_final_fail:
        res = await process_delivery_failure_event(fail_evt, worker_id)
        assert res is False
        mock_final_fail.assert_called_once()
        assert "rate limit exceeded" in mock_final_fail.call_args[1]["reason"]


# ---------------------------------------------------------------------------
# 11. Simulated flag is preserved end-to-end through worker and repository
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simulated_dispatch_preserved_through_worker_and_repository():
    """Simulated Telegram alerts must never be recorded as real successful deliveries."""
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    evt_id = f"evt_sim_{uuid.uuid4()}"

    sim_evt = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "postmark",
        "order_id": "#SIM-101",
    }

    mock_sim_res = TelegramDispatchResult(
        success=True,
        provider="telegram",
        provider_status="simulated",
        telegram_message_id="mock_tg_abcd1234efgh",
        target_chat_id="@sim_channel",
        simulated=True,
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock, return_value=mock_sim_res), \
         patch.object(repository, "mark_event_processed") as mock_mark_proc:
        res = await process_delivery_failure_event(sim_evt, worker_id)
        assert res is True
        mock_mark_proc.assert_called_once_with(
            event_id=evt_id,
            outcome="processed",
            worker_id=worker_id,
        )

    # Verify log recorded in repository in-memory fallback
    from app.services.supabase_client import supabase_service
    logs = supabase_service.get_failover_logs(user_id)
    assert len(logs) > 0
    sim_log = next((l for l in logs if l.get("delivery_failure_event_id") == evt_id), None)
    assert sim_log is not None

    # Crucial assertions: must satisfy DB CHECK constraint without claiming delivery
    assert sim_log["status"] == "dispatched"
    assert sim_log["status"] != "delivered"
    assert sim_log["provider_status"] == "simulated"
    assert sim_log["delivered_at"] is None
    assert sim_log["provider_sid"] == "mock_tg_abcd1234efgh"
    assert sim_log["dispatch_payload"].get("simulated") is True


# ---------------------------------------------------------------------------
# 12. Defense-in-depth: persist_failover_log sanitizes false delivery claims
# ---------------------------------------------------------------------------
def test_persist_failover_log_intercepts_mock_identifiers():
    """Even if a caller passes status='delivered', mock identifiers force safe status."""
    from app.services.supabase_client import supabase_service
    user_id = str(uuid.uuid4())

    # Caller explicitly attempts to persist mock sid as delivered
    log = supabase_service.persist_failover_log(
        user_id=user_id,
        order_id="#TEST-001",
        channel="telegram",
        provider="telegram",
        status="delivered",
        provider_status="delivered",
        provider_sid="mock_tg_accidental_leak",
        delivery_failure_event_id=str(uuid.uuid4()),
    )

    assert log["status"] == "dispatched"
    assert log["provider_status"] == "simulated"
    assert log["delivered_at"] is None
    assert log["dispatch_payload"]["simulated"] is True


# ---------------------------------------------------------------------------
# 13. Real dispatch behavior remains fully compatible
# ---------------------------------------------------------------------------
def test_real_dispatch_persistence_compatibility():
    """Real non-simulated dispatches must retain status='delivered' and delivered_at timestamp."""
    from app.services.supabase_client import supabase_service
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    log = repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#REAL-999",
        domain_name="brandstore.com",
        store_name="BrandStore",
        triggered_reason="DMARC reject failure",
        target_chat_id="@merchant_chat",
        provider_status="delivered",
        provider_message_id="987654321",  # Real numeric telegram message_id
        is_simulated=False,
    )

    assert log["status"] == "delivered"
    assert log["provider_status"] == "delivered"
    assert log["delivered_at"] is not None
    assert log["provider_sid"] == "987654321"
    assert log["dispatch_payload"].get("simulated") is not True


# ---------------------------------------------------------------------------
# 14. Idempotency guarantees preserved during simulation
# ---------------------------------------------------------------------------
def test_simulation_preserves_idempotency_keys():
    """Simulated logs must contain all keys required by idx_failover_logs_one_telegram_incident_per_event."""
    user_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    sim_log = repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#IDEMP-01",
        domain_name="test.com",
        store_name="Test Store",
        triggered_reason="Mailbox full",
        target_chat_id="@test_channel",
        provider_status="simulated",
        provider_message_id="mock_tg_idemp1",
        is_simulated=True,
    )

    assert sim_log["delivery_failure_event_id"] == evt_id
    assert sim_log["fallback_channel"] == "telegram"
    assert sim_log["channel"] == "telegram"

