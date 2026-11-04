"""INV-15: conservative crash recovery, not exactly-once Telegram delivery."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest

from app.core.config import settings
from app.services import supabase_client
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import telegram_alert_service as service
from app.workers.failover_worker import process_notification_outbox_item, process_delivery_failure_event


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "STAGING_MODE", False)
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    database = supabase_client.SupabaseService()
    monkeypatch.setattr(supabase_client, "supabase_service", database)
    monkeypatch.setattr(repository, "supabase", database)
    service.disable_mock_mode()
    yield database
    service.disable_mock_mode()


def new_job(store):
    user_id, worker_id = str(uuid.uuid4()), str(uuid.uuid4())
    service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "123456:RegressionSyntheticToken",
        "telegram_chat_id": "-1001234567890",
    })
    row = repository.enqueue_notification_outbox(user_id, "telegram", "regression", {"order_id": "#R1"})
    item = repository.claim_notification_outbox(worker_id)[0]
    return user_id, worker_id, item, store._in_memory_notification_outbox[f"{user_id}:regression"]


def expire(row):
    row["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()


@pytest.mark.asyncio
async def test_same_claim_cannot_dispatch_twice(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(return_value={"success": True})) as send:
        assert await process_notification_outbox_item(item, worker) is True
        assert await process_notification_outbox_item(item, worker) is False
        send.assert_awaited_once()
    assert row["status"] == "processed"


@pytest.mark.asyncio
async def test_presend_crash_is_reclaimable_but_old_worker_is_fenced(store):
    user, worker, item, row = new_job(store)
    expire(row)  # No intent was ever acquired; no external request could start.
    replacement = str(uuid.uuid4())
    recovered = repository.claim_notification_outbox(replacement)
    assert [i["id"] for i in recovered] == [item["id"]]
    with patch.object(service, "send_telegram_alert", new=AsyncMock(return_value={"success": True})) as send:
        assert await process_notification_outbox_item(item, worker) is False
        send.assert_not_awaited()
        assert await process_notification_outbox_item(recovered[0], replacement) is True
        send.assert_awaited_once()


@pytest.mark.asyncio
async def test_crash_after_possible_acceptance_never_reclaims_or_resends(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(side_effect=RuntimeError("crash after acceptance"))) as send:
        with pytest.raises(RuntimeError, match="crash after acceptance"):
            await process_notification_outbox_item(item, worker)
        assert row["dispatch_started_at"]
        expire(row)
        assert repository.claim_notification_outbox(str(uuid.uuid4())) == []
        assert row["status"] == "dead_letter"
        assert "AMBIGUOUS_EXTERNAL_DISPATCH" in row["last_error"]
        assert await process_notification_outbox_item(item, worker) is False
        send.assert_awaited_once()


@pytest.mark.asyncio
async def test_accepted_but_ack_lost_never_resends(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(return_value={"success": True})) as send:
        with patch.object(repository, "complete_notification_outbox", return_value=False):
            assert await process_notification_outbox_item(item, worker) is False
        assert row["status"] == "dispatching"
        expire(row)
        assert repository.claim_notification_outbox(str(uuid.uuid4())) == []
        assert row["status"] == "dead_letter"
        assert await process_notification_outbox_item(item, worker) is False
        send.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_after_intent_is_quarantined(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await process_notification_outbox_item(item, worker)
    expire(row)
    assert repository.claim_notification_outbox(str(uuid.uuid4())) == []
    assert row["status"] == "dead_letter"


@pytest.mark.asyncio
async def test_explicit_rate_limit_rejection_can_retry_with_fresh_intent(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(side_effect=[
        {"success": False, "retryable": True, "status_code": 429, "retry_after": 60, "error": "rejected"},
        {"success": True},
    ])) as send:
        assert await process_notification_outbox_item(item, worker) is False
        assert row["status"] == "queued" and row["dispatch_started_at"] is None
        assert repository.claim_notification_outbox(worker) == []
        row["next_attempt_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        retry = repository.claim_notification_outbox(worker)[0]
        assert await process_notification_outbox_item(retry, worker) is True
        assert send.await_count == 2


@pytest.mark.asyncio
async def test_uncertain_flag_wins_over_retryable_flag(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(return_value={
        "success": False, "uncertain": True, "retryable": True, "error": "read response lost",
    })):
        assert await process_notification_outbox_item(item, worker) is False
    assert row["status"] == "dead_letter"
    assert "AMBIGUOUS_EXTERNAL_DISPATCH" in row["last_error"]
    assert repository.claim_notification_outbox(worker) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadTimeout("read lost"), httpx.WriteError("write lost"), httpx.RemoteProtocolError("response lost")])
async def test_transport_unknown_outcome_is_not_retried(failure):
    service.disable_mock_mode()
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=failure)) as post:
        result = await service.send_telegram_alert("123456:RegressionSyntheticToken", "-1001234567890", "notice")
    assert result["success"] is False
    assert result["uncertain"] is True and result["retryable"] is False
    post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 500, 501, 502, 503, 504, 507])
async def test_server_error_is_uncertain_and_never_retried(status):
    service.disable_mock_mode()
    response = httpx.Response(status, text="gateway response lost")
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as post:
        result = await service.send_telegram_alert("123456:RegressionSyntheticToken", "-1001234567890", "notice")
    assert result["uncertain"] is True and result["retryable"] is False
    post.assert_awaited_once()


@pytest.mark.asyncio
async def test_staging_mock_mode_does_not_bypass_durable_config_requirement(store, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    service.enable_mock_mode()
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        with pytest.raises(supabase_client.DatabaseUnavailableError):
            await service.dispatch_alert(user_id=str(uuid.uuid4()), failure_type="bounce")
        post.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_error_before_intent_safely_releases_claim(store):
    worker, event_id = str(uuid.uuid4()), str(uuid.uuid4())
    row = {"id": event_id, "user_id": str(uuid.uuid4()), "event_type": "bounce", "processing_status": "received"}
    store._in_memory_delivery_failure_events[event_id] = row
    event = repository.claim_pending_delivery_failure_events(worker)[0]
    with patch("app.workers.failover_worker.incident_factory.from_event_and_registry", side_effect=RuntimeError("before send")):
        with pytest.raises(RuntimeError, match="before send"):
            await process_delivery_failure_event(event, worker)
    assert row["processing_status"] == "received"
    assert row["claimed_by"] is None
    assert not row.get("dispatch_intent_at")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"ok": True}, ["not a Telegram response"]])
async def test_invalid_acknowledgement_remains_uncertain(payload):
    service.disable_mock_mode()
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=httpx.Response(200, json=payload))) as post:
        result = await service.send_telegram_alert("123456:RegressionSyntheticToken", "-1001234567890", "notice")
    assert result["success"] is False and result["uncertain"] is True
    post.assert_awaited_once()


@pytest.mark.asyncio
async def test_quarantined_event_without_owner_cannot_be_resurrected(store):
    event_id = str(uuid.uuid4())
    row = {"id": event_id, "user_id": str(uuid.uuid4()), "event_type": "bounce",
           "processing_status": "quarantined", "claimed_by": None}
    store._in_memory_delivery_failure_events[event_id] = row
    with patch.object(service, "dispatch_alert", new=AsyncMock()) as send:
        assert await process_delivery_failure_event(dict(row), str(uuid.uuid4())) is False
        send.assert_not_awaited()
    assert row["processing_status"] == "quarantined"


@pytest.mark.asyncio
async def test_dispatch_result_preserves_definitive_retry_metadata(store):
    user, worker, item, row = new_job(store)
    with patch.object(service, "send_telegram_alert", new=AsyncMock(return_value={
        "success": False, "retryable": True, "retry_after": 60, "error": "Telegram rejected rate-limited send",
    })):
        result = await service.dispatch_alert(user_id=user, failure_type="bounce")
    assert result.retryable is True and result.retry_after == 60 and result.uncertain is False


def test_missing_intent_rpc_fails_closed_without_memory_fallback(store):
    user, worker, item, row = new_job(store)
    class MissingIntentRpc:
        def rpc(self, name, params):
            assert name == "record_notification_outbox_dispatch_intent"
            raise RuntimeError("RPC unavailable")
    store._client = MissingIntentRpc()
    with pytest.raises(supabase_client.DatabaseUnavailableError, match="persist notification dispatch intent"):
        repository.record_notification_outbox_dispatch_intent(item["id"], worker)
    assert not row.get("dispatch_started_at")


def test_expired_owner_cannot_acknowledge_or_requeue_unknown_send(store):
    user, worker, item, row = new_job(store)
    assert repository.record_notification_outbox_dispatch_intent(item["id"], worker)
    expire(row)
    assert repository.complete_notification_outbox(item["id"], worker) is False
    assert repository.fail_or_retry_notification_outbox(
        item["id"], worker, "late failure", True, datetime.now(timezone.utc)
    ) is None
    assert repository.claim_notification_outbox(str(uuid.uuid4())) == []
    assert row["status"] == "dead_letter"
