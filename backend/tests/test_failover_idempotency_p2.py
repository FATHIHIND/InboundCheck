"""
InboundCheck - Failover Idempotency & P2 Duplicate Dispatch Mitigation Tests
=============================================================================
Verification suite for P2 duplicate Telegram dispatch remediation:
1. Unit: _is_telegram_incident_unique_violation correctly discriminates SQLSTATE 23505 on target constraint.
2. Unit: is_reliable_successful_incident only suppresses on verified success/simulation (never on failed/pending).
3. Pre-Dispatch: Existing successful incident (status='delivered') suppresses duplicate dispatch.
4. Pre-Dispatch: Failed prior incident (status='failed') does NOT suppress legitimate dispatch.
5. Pre-Dispatch: Simulated prior incident (provider_status='simulated' or is_simulated=True) suppresses duplicate dispatch.
6. Post-Dispatch Error Safety: Telegram succeeds, but incident logging fails -> event is NOT released to 'received'.
7. Concurrency / 23505: Constraint violation on idx_failover_logs_one_telegram_incident_per_event is handled safely and marks event processed.
8. Unrelated DB Errors: Unrelated database exception (e.g. connection timeout or foreign key 23503) is NOT swallowed.
9. Lease Expiry / Stale Recovery: Event whose lease expired after dispatch is claimed and resolved without duplicate dispatch.
10. End-to-End Worker: Full loop with run_failover_worker(once=True) respects idempotency across multiple cycles.
"""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from postgrest.exceptions import APIError

from app.workers.failover_worker import (
    process_delivery_failure_event,
    run_failover_worker,
    _is_telegram_incident_unique_violation,
    is_reliable_successful_incident,
)
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import (
    telegram_alert_service,
    TelegramDispatchResult,
)
from app.services.supabase_client import supabase_service


@pytest.fixture(autouse=True)
def clean_mock_and_in_memory():
    """Reset mock mode and clear in-memory logs before and after each test."""
    telegram_alert_service.disable_mock_mode()
    orig_client = supabase_service._client
    supabase_service._client = None
    if hasattr(supabase_service, "_in_memory_failover_logs"):
        supabase_service._in_memory_failover_logs.clear()
    if hasattr(supabase_service, "_in_memory_delivery_failure_events"):
        supabase_service._in_memory_delivery_failure_events.clear()
    yield
    supabase_service._client = orig_client
    telegram_alert_service.disable_mock_mode()
    if hasattr(supabase_service, "_in_memory_failover_logs"):
        supabase_service._in_memory_failover_logs.clear()
    if hasattr(supabase_service, "_in_memory_delivery_failure_events"):
        supabase_service._in_memory_delivery_failure_events.clear()


# ===========================================================================
# 1. Unit: _is_telegram_incident_unique_violation
# ===========================================================================
def test_unique_violation_recognizes_target_constraint_23505():
    """Must return True only when SQLSTATE is 23505 AND constraint is idx_failover_logs_one_telegram_incident_per_event."""
    api_err = APIError({
        "message": 'duplicate key value violates unique constraint "idx_failover_logs_one_telegram_incident_per_event"',
        "code": "23505",
        "details": "Key (delivery_failure_event_id)=(123) already exists.",
    })
    assert _is_telegram_incident_unique_violation(api_err) is True


def test_unique_violation_rejects_unrelated_constraint_23505():
    """Must return False if code is 23505 but constraint is a different index/table."""
    api_err = APIError({
        "message": 'duplicate key value violates unique constraint "users_email_key"',
        "code": "23505",
        "details": "Key (email)=(test@example.com) already exists.",
    })
    assert _is_telegram_incident_unique_violation(api_err) is False


def test_unique_violation_rejects_unrelated_sqlstate():
    """Must return False for foreign key violations (23503) or check constraints."""
    api_err = APIError({
        "message": 'insert or update violates foreign key constraint on idx_failover_logs_one_telegram_incident_per_event',
        "code": "23503",
        "details": "Key (user_id)=(missing) is not present.",
    })
    assert _is_telegram_incident_unique_violation(api_err) is False


def test_unique_violation_rejects_generic_exceptions():
    """Must return False for connection errors, timeouts, or unexpected exceptions."""
    assert _is_telegram_incident_unique_violation(Exception("Connection timeout")) is False
    assert _is_telegram_incident_unique_violation(RuntimeError("Database pool exhausted")) is False
    assert _is_telegram_incident_unique_violation(None) is False


# ===========================================================================
# 2. Unit: is_reliable_successful_incident
# ===========================================================================
def test_is_reliable_successful_incident_evaluations():
    """Validates accurate classification of incident states."""
    # Never suppress on None or empty
    assert is_reliable_successful_incident(None) is False
    assert is_reliable_successful_incident({}) is False

    # Never suppress on failed
    assert is_reliable_successful_incident({"status": "failed", "provider_status": "failed"}) is False
    assert is_reliable_successful_incident({"status": "failed", "provider_status": "delivered"}) is False
    assert is_reliable_successful_incident({"status": "delivered", "provider_status": "failed"}) is False

    # Never suppress on pending or incomplete
    assert is_reliable_successful_incident({"status": "pending"}) is False
    assert is_reliable_successful_incident({"status": "unknown"}) is False

    # Reliable success states
    assert is_reliable_successful_incident({"status": "delivered", "provider_status": "delivered"}) is True
    assert is_reliable_successful_incident({"status": "dispatched", "provider_status": "sent"}) is True

    # Reliable simulated states
    assert is_reliable_successful_incident({"status": "dispatched", "provider_status": "simulated", "is_simulated": True}) is True
    assert is_reliable_successful_incident({"provider_status": "simulated"}) is True


# ===========================================================================
# 3. Pre-Dispatch: Existing Successful Incident Suppresses Duplicate Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_existing_successful_incident_suppresses_dispatch():
    """When a successful incident already exists, worker must NOT call dispatch_alert and must mark event processed."""
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "hard_bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "provider_message_id": "sg_msg_101",
    }

    # Record existing delivered incident in failover_logs
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#1001",
        domain_name="testbrand.com",
        store_name="Test Brand",
        triggered_reason="Permanent mailbox bounce",
        target_chat_id="@merchant_ops",
        provider_status="delivered",
        provider_message_id="tg_msg_existing",
        is_simulated=False,
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        result = await process_delivery_failure_event(event, worker_id)

        assert result is True
        mock_dispatch.assert_not_called()
        mock_mark_processed.assert_called_once()
        assert mock_mark_processed.call_args[1]["event_id"] == evt_id
        assert mock_mark_processed.call_args[1]["outcome"] == "processed"


# ===========================================================================
# 4. Pre-Dispatch: Failed Prior Incident Does NOT Suppress Legitimate Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_failed_prior_incident_does_not_suppress_dispatch():
    """A prior failed incident must NOT suppress retry dispatch."""
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "postmark",
    }

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "postmark",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Record a failed incident log
    supabase_service.persist_failover_log(
        user_id=user_id,
        order_id="#1002",
        channel="telegram",
        fallback_channel="telegram",
        provider="telegram",
        status="failed",
        provider_status="failed",
        domain_name="testbrand.com",
        store_name="Test Brand",
        triggered_reason="Network error during earlier attempt",
        target_chat_id="@merchant_ops",
        delivery_failure_event_id=evt_id,
    )

    fake_dispatch_result = TelegramDispatchResult(
        channel="telegram",
        status="delivered",
        provider_status="delivered",
        dispatched=True,
        success=True,
        target_chat_id="@merchant_ops",
        telegram_message_id="tg_msg_new_success",
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "create_telegram_incident_log") as mock_create_log, \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        mock_dispatch.return_value = fake_dispatch_result

        result = await process_delivery_failure_event(event, worker_id)

        assert result is True
        mock_dispatch.assert_called_once()
        mock_create_log.assert_called_once()
        mock_mark_processed.assert_called_once()


# ===========================================================================
# 5. Pre-Dispatch: Simulated Incident Suppresses Duplicate Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_simulated_incident_suppresses_dispatch():
    """Simulated staging/mock incident logs must suppress duplicate live dispatch."""
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "dropped",
        "user_id": user_id,
        "esp_provider": "sendgrid",
    }

    # Record a simulated incident log
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#1003",
        domain_name="testbrand.com",
        store_name="Test Brand",
        triggered_reason="Recipient dropped",
        target_chat_id="@merchant_ops",
        provider_status="simulated",
        provider_message_id="mock_tg_sim1",
        is_simulated=True,
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        result = await process_delivery_failure_event(event, worker_id)

        assert result is True
        mock_dispatch.assert_not_called()
        mock_mark_processed.assert_called_once()


# ===========================================================================
# 6. Post-Dispatch Error Safety: Event Is NOT Released to 'received' After Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_post_dispatch_database_error_does_not_release_event_to_received():
    """
    CRITICAL P2 SAFETY INVARIANT:
    If Telegram dispatch succeeds, but writing the incident log encounters a database error,
    the worker must NOT call release_claimed_delivery_failure_event (which would reset it to 'received'
    and cause immediate duplicate dispatch by another worker).
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "hard_bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
    }

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "hard_bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    fake_dispatch_result = TelegramDispatchResult(
        channel="telegram",
        status="delivered",
        provider_status="delivered",
        dispatched=True,
        success=True,
        target_chat_id="@merchant_ops",
        telegram_message_id="tg_msg_post_err",
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "create_telegram_incident_log", side_effect=RuntimeError("Database connection lost")), \
         patch.object(repository, "release_claimed_delivery_failure_event") as mock_release:

        mock_dispatch.return_value = fake_dispatch_result

        with pytest.raises(RuntimeError, match="Database connection lost"):
            await process_delivery_failure_event(event, worker_id)

        # Telegram dispatch was invoked and succeeded
        mock_dispatch.assert_called_once()
        # Event must NOT be released back to 'received'
        mock_release.assert_not_called()


# ===========================================================================
# 7. Concurrency / 23505: Unique Constraint Violation Handled Safely
# ===========================================================================
@pytest.mark.asyncio
async def test_unique_constraint_violation_marks_event_processed():
    """
    If another worker or racing task already inserted the incident log (SQLSTATE 23505 on
    idx_failover_logs_one_telegram_incident_per_event), the worker must treat this as idempotency
    resolution and mark the event processed without raising.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "rejected",
        "user_id": user_id,
        "esp_provider": "mailgun",
    }

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "rejected",
        "user_id": user_id,
        "esp_provider": "mailgun",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    fake_dispatch_result = TelegramDispatchResult(
        channel="telegram",
        status="delivered",
        provider_status="delivered",
        dispatched=True,
        success=True,
        target_chat_id="@merchant_ops",
        telegram_message_id="tg_msg_race_1",
    )

    api_err_23505 = APIError({
        "message": 'duplicate key value violates unique constraint "idx_failover_logs_one_telegram_incident_per_event"',
        "code": "23505",
        "details": f"Key (delivery_failure_event_id)=({evt_id}) already exists.",
    })

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "create_telegram_incident_log", side_effect=api_err_23505), \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        mock_dispatch.return_value = fake_dispatch_result

        result = await process_delivery_failure_event(event, worker_id)

        assert result is True
        mock_dispatch.assert_called_once()
        mock_mark_processed.assert_called_once()
        assert mock_mark_processed.call_args[1]["outcome"] == "processed"


# ===========================================================================
# 8. Unrelated Database Errors Are NOT Swallowed
# ===========================================================================
@pytest.mark.asyncio
async def test_unrelated_database_error_is_re_raised():
    """Unrelated database errors (e.g. foreign key 23503, schema error, or connection reset) must propagate."""
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
    }

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    fake_dispatch_result = TelegramDispatchResult(
        channel="telegram",
        status="delivered",
        provider_status="delivered",
        dispatched=True,
        success=True,
        target_chat_id="@merchant_ops",
        telegram_message_id="tg_msg_fk_err",
    )

    fk_err_23503 = APIError({
        "message": 'insert or update on table "failover_logs" violates foreign key constraint',
        "code": "23503",
        "details": f"Key (user_id)=({user_id}) is not present in table profiles.",
    })

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "create_telegram_incident_log", side_effect=fk_err_23503):

        mock_dispatch.return_value = fake_dispatch_result

        with pytest.raises(APIError) as exc_info:
            await process_delivery_failure_event(event, worker_id)

        assert exc_info.value.code == "23503"


# ===========================================================================
# 9. Lease Expiry / Stale Recovery With Existing Incident Suppresses Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_expired_lease_recovery_suppresses_telegram_dispatch():
    """
    Scenario: Worker A dispatched Telegram and recorded the incident, but crashed before
    mark_event_processed. Worker B claims the event after lease expiry.
    Worker B must detect the existing incident log and mark the event processed without re-dispatching Telegram.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_b_id = str(uuid.uuid4())

    # Pre-populate delivery failure event in queued status with an existing incident log
    event = {
        "id": evt_id,
        "event_type": "hard_bounce",
        "user_id": user_id,
        "processing_status": "queued",
        "esp_provider": "sendgrid",
    }

    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#RECOVER-44",
        domain_name="brand.com",
        store_name="Brand Store",
        triggered_reason="Mailbox not found",
        target_chat_id="@merchant_channel",
        provider_status="delivered",
        provider_message_id="tg_prior_crash_msg",
        is_simulated=False,
    )

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        result = await process_delivery_failure_event(event, worker_b_id)

        assert result is True
        # Telegram dispatch MUST NOT be called again
        mock_dispatch.assert_not_called()
        # Event is finalized as processed
        mock_mark_processed.assert_called_once()
        assert mock_mark_processed.call_args[1]["outcome"] == "processed"


# ===========================================================================
# 10. End-to-End Worker Loop Respects Idempotency Across Multiple Cycles
# ===========================================================================
@pytest.mark.asyncio
async def test_worker_loop_single_cycle_idempotent_execution():
    """
    Verifies that running run_failover_worker(once=True) on a batch containing an already-logged
    event suppresses duplicate dispatch and completes cleanly.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
    }

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Populate incident log to simulate previous cycle
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#BATCH-01",
        domain_name="batchstore.com",
        store_name="Batch Store",
        triggered_reason="Mailbox quota exceeded",
        target_chat_id="@batch_ops",
        provider_status="delivered",
        provider_message_id="tg_batch_1",
    )

    with patch.object(repository, "claim_pending_delivery_failure_events", return_value=[event]), \
         patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch, \
         patch.object(repository, "mark_event_processed") as mock_mark_processed:

        await run_failover_worker(once=True, limit=1)

        mock_dispatch.assert_not_called()
        mock_mark_processed.assert_called_once()


# ===========================================================================
# 11. Dispatch Intent Is Persisted Before Telegram Call
# ===========================================================================
@pytest.mark.asyncio
async def test_dispatch_intent_persisted_before_telegram_call():
    """
    Worker must durably transition event to 'dispatching' and record dispatch_intent_at
    prior to invoking the external Telegram dispatch.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    # Pre-populate event in queued status owned by worker_id
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    intent_observed_during_dispatch = None

    async def mock_dispatch_inspector(*args, **kwargs):
        nonlocal intent_observed_during_dispatch
        # Check database/in-memory status at the exact moment dispatch_alert is executing
        intent_observed_during_dispatch = supabase_service._in_memory_delivery_failure_events[evt_id].copy()
        return TelegramDispatchResult(
            channel="telegram",
            status="delivered",
            provider_status="delivered",
            dispatched=True,
            success=True,
            target_chat_id="@ops",
            telegram_message_id="tg_123",
        )

    with patch.object(telegram_alert_service, "dispatch_alert", side_effect=mock_dispatch_inspector):
        event = supabase_service._in_memory_delivery_failure_events[evt_id]
        res = await process_delivery_failure_event(event, worker_id)

        assert res is True
        assert intent_observed_during_dispatch is not None
        assert intent_observed_during_dispatch["processing_status"] == "dispatching"
        assert intent_observed_during_dispatch["dispatch_intent_at"] is not None
        assert intent_observed_during_dispatch["dispatch_attempt_count"] >= 1


# ===========================================================================
# 12. Failure to Persist Intent Aborts Telegram Dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_failure_to_persist_intent_aborts_dispatch():
    """
    If the worker cannot acquire durable dispatch intent (e.g. lease expired or DB error),
    it must fail closed and NEVER call dispatch_alert.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    event = {
        "id": evt_id,
        "event_type": "hard_bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
    }

    with patch.object(repository, "record_delivery_failure_dispatch_intent", return_value=False), \
         patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:

        res = await process_delivery_failure_event(event, worker_id)

        assert res is False
        mock_dispatch.assert_not_called()


# ===========================================================================
# 13. Concurrent Claims Cannot Both Acquire Dispatch Authorization
# ===========================================================================
def test_concurrent_workers_cannot_both_acquire_intent():
    """
    When Worker 1 holds the lease, Worker 2 must be rejected.
    Once Worker 1 acquires intent (status -> dispatching), a second call is also rejected.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": w1,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Worker 2 attempts to acquire intent -> must fail (lease owner mismatch)
    assert repository.record_delivery_failure_dispatch_intent(evt_id, w2) is False

    # Worker 1 acquires intent -> succeeds
    assert repository.record_delivery_failure_dispatch_intent(evt_id, w1) is True
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "dispatching"

    # Worker 1 calls again -> fails (status is already dispatching, not queued)
    assert repository.record_delivery_failure_dispatch_intent(evt_id, w1) is False


# ===========================================================================
# 14. Crash After Intent: Expired Lease Quarantines Event Without Redispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_crash_after_intent_quarantines_expired_event():
    """
    SIMULATED CRASH SCENARIO:
    1. Worker 1 records intent (status becomes 'dispatching').
    2. Worker 1 crashes (simulated: local process dies, in-memory state destroyed).
    3. Lease expires.
    4. Worker 2 (fresh worker instance) sweeps the queue.
    5. Event is quarantined with AMBIGUOUS_EXTERNAL_DISPATCH.
    6. Telegram dispatch is NEVER called.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())

    # Event left in 'dispatching' with expired lease from crashed Worker 1
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "dispatching",
        "claimed_by": w1,
        "lease_until": "2020-01-01T00:00:00+00:00",  # Expired in past
        "dispatch_intent_at": "2020-01-01T00:00:00+00:00",
        "dispatch_attempt_count": 1,
    }

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        # Worker 2 executes claim_pending_delivery_failure_events
        claimed = repository.claim_pending_delivery_failure_events(worker_id=w2)

        # The expired dispatching event must NOT be returned for dispatch
        assert not any(c.get("id") == evt_id for c in claimed)
        mock_dispatch.assert_not_called()

        # The event must now be durably quarantined
        stored = supabase_service._in_memory_delivery_failure_events[evt_id]
        assert stored["processing_status"] == "quarantined"
        assert "AMBIGUOUS_EXTERNAL_DISPATCH" in stored.get("processing_error", "")


# ===========================================================================
# 15. Crash After Dispatch Succeeded & Logged: Recovers to Processed
# ===========================================================================
@pytest.mark.asyncio
async def test_crash_after_dispatch_recovers_to_processed_if_incident_logged():
    """
    If Worker 1 dispatched Telegram and durably recorded the incident log, but crashed
    before updating delivery_failure_events to 'processed':
    Worker 2's sweep must detect the incident log and resolve the event to 'processed'
    without re-dispatching Telegram.
    """
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())

    # Existing durable incident log from Worker 1
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#REC-01",
        domain_name="store.com",
        store_name="Store",
        triggered_reason="Permanent bounce",
        target_chat_id="@ops",
        provider_status="delivered",
        provider_message_id="tg_rec_99",
        is_simulated=False,
    )

    # Event left in 'dispatching' with expired lease
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "event_type": "bounce",
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "processing_status": "dispatching",
        "claimed_by": w1,
        "lease_until": "2020-01-01T00:00:00+00:00",
        "dispatch_intent_at": "2020-01-01T00:00:00+00:00",
        "dispatch_attempt_count": 1,
    }

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        # Worker 2 claims
        repository.claim_pending_delivery_failure_events(worker_id=w2)

        mock_dispatch.assert_not_called()
        stored = supabase_service._in_memory_delivery_failure_events[evt_id]
        assert stored["processing_status"] == "processed"


# ===========================================================================
# 16. Lease Owner Mismatch Rejected in Release
# ===========================================================================
def test_lease_owner_mismatch_cannot_release_event():
    """Worker 2 cannot release an event claimed by Worker 1."""
    evt_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "processing_status": "queued",
        "claimed_by": w1,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Worker 2 attempts to release -> must return False
    assert repository.release_claimed_delivery_failure_event(evt_id, w2) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"

    # Worker 1 releases -> succeeds
    assert repository.release_claimed_delivery_failure_event(evt_id, w1) is True
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "received"



# ===========================================================================
# 17. Quarantine Batch Limit Caps Total Across Both Resolution Categories
# ===========================================================================
def test_quarantine_batch_limit_caps_total_across_categories():
    """
    Validates that p_limit caps the total number of events transitioned during one invocation,
    including both events reconciled to 'processed' and events quarantined as 'quarantined'.
    """
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    # Create 3 events with logged incidents (should resolve to 'processed')
    resolved_ids = []
    for i in range(3):
        e_id = str(uuid.uuid4())
        resolved_ids.append(e_id)
        supabase_service._in_memory_delivery_failure_events[e_id] = {
            "id": e_id,
            "user_id": user_id,
            "processing_status": "dispatching",
            "claimed_by": worker_id,
            "lease_until": f"2020-01-0{i+1}T00:00:00+00:00",
        }
        repository.create_telegram_incident_log(
            delivery_failure_event_id=e_id,
            user_id=user_id,
            order_id=f"#RES-{i}",
            domain_name="test.com",
            store_name="Store",
            triggered_reason="Bounce",
            target_chat_id="@ops",
            provider_status="delivered",
            is_simulated=False,
        )

    # Create 3 events without incident logs (should quarantine)
    quarantined_ids = []
    for i in range(3):
        e_id = str(uuid.uuid4())
        quarantined_ids.append(e_id)
        supabase_service._in_memory_delivery_failure_events[e_id] = {
            "id": e_id,
            "user_id": user_id,
            "processing_status": "dispatching",
            "claimed_by": worker_id,
            "lease_until": f"2020-01-0{i+4}T00:00:00+00:00",
        }

    # We have 6 total expired dispatching events. Limit is 4.
    results = repository.quarantine_expired_dispatch_intent_events(limit=4)

    # Must strictly process exactly 4 events
    assert len(results) == 4

    # The 2 remaining events must still be in 'dispatching'
    all_events = supabase_service._in_memory_delivery_failure_events
    dispatching_count = sum(1 for e in all_events.values() if e.get("processing_status") == "dispatching")
    assert dispatching_count == 2

    # A subsequent sweep with limit=4 processes the remaining 2 events
    second_results = repository.quarantine_expired_dispatch_intent_events(limit=4)
    assert len(second_results) == 2
    dispatching_count_after = sum(1 for e in all_events.values() if e.get("processing_status") == "dispatching")
    assert dispatching_count_after == 0


# ===========================================================================
# 18. Quarantine Batch Limit Handles NULL, Zero, and Negative Limits Safely
# ===========================================================================
def test_quarantine_batch_limit_handles_invalid_limits_safely():
    """Validates that NULL, 0, or negative limits exit immediately with 0 changes."""
    user_id = str(uuid.uuid4())
    e_id = str(uuid.uuid4())
    supabase_service._in_memory_delivery_failure_events[e_id] = {
        "id": e_id,
        "user_id": user_id,
        "processing_status": "dispatching",
        "lease_until": "2020-01-01T00:00:00+00:00",
    }

    # Negative limit
    assert repository.quarantine_expired_dispatch_intent_events(limit=-5) == []
    assert supabase_service._in_memory_delivery_failure_events[e_id]["processing_status"] == "dispatching"

    # Zero limit
    assert repository.quarantine_expired_dispatch_intent_events(limit=0) == []
    assert supabase_service._in_memory_delivery_failure_events[e_id]["processing_status"] == "dispatching"

    # None limit
    assert repository.quarantine_expired_dispatch_intent_events(limit=None) == []
    assert supabase_service._in_memory_delivery_failure_events[e_id]["processing_status"] == "dispatching"


# ===========================================================================
# 19. Stale Worker Cannot Finalize After Competing Worker Takes Ownership
# ===========================================================================
def test_stale_worker_cannot_finalize_after_reclaimed():
    """Worker 1 loses ownership to Worker 2; Worker 1 cannot finalize the event."""
    evt_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "processing_status": "queued",
        "claimed_by": w2,  # Reclaimed by Worker 2
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Stale Worker 1 attempts to mark processed
    assert repository.mark_event_processed(evt_id, worker_id=w1) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"

    # Stale Worker 1 attempts to mark failed
    assert repository.mark_event_failed(evt_id, reason="Old failure", worker_id=w1) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"


# ===========================================================================
# 20. Stale Worker Cannot Overwrite Quarantined State Without Durable Incident
# ===========================================================================
def test_stale_worker_cannot_overwrite_quarantined_without_incident():
    """Worker 1 cannot mark a quarantined event processed if no durable incident log exists."""
    evt_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "processing_status": "quarantined",
        "claimed_by": w1,
        "lease_until": "2020-01-01T00:00:00+00:00",
    }

    # Attempt to mark processed without incident log -> must fail closed
    assert repository.mark_event_processed(evt_id, worker_id=w1) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "quarantined"

    # Attempt to mark failed -> must fail closed
    assert repository.mark_event_failed(evt_id, reason="Fail after quarantine", worker_id=w1) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "quarantined"


# ===========================================================================
# 21. Reconcile Quarantined Event If Confirmed Durable Incident Exists
# ===========================================================================
def test_quarantined_reconciliation_with_confirmed_durable_incident():
    """If confirmed durable incident log exists, worker can safely reconcile quarantined event to processed."""
    evt_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "quarantined",
        "claimed_by": w1,
        "lease_until": "2020-01-01T00:00:00+00:00",
    }

    # Insert confirmed incident log
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#RECONCILE-10",
        domain_name="test.com",
        store_name="Store",
        triggered_reason="Bounce",
        target_chat_id="@ops",
        provider_status="delivered",
    )

    # Worker 1 finalizes with verified durable incident -> succeeds
    assert repository.mark_event_processed(evt_id, worker_id=w1, user_id=user_id) is True
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "processed"


# ===========================================================================
# 22. Explicit Tenant Isolation Coverage
# ===========================================================================
def test_tenant_isolation_incident_query_and_boundaries():
    """
    Validates that:
    1. An incident for Event A cannot be returned for Event B.
    2. A tenant-scoped query cannot return an incident belonging to another tenant.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    event_a = str(uuid.uuid4())
    event_b = str(uuid.uuid4())

    # Create incident log for Tenant A on Event A
    repository.create_telegram_incident_log(
        delivery_failure_event_id=event_a,
        user_id=tenant_a,
        order_id="#TENANT-A",
        domain_name="tenant-a.com",
        store_name="Store A",
        triggered_reason="Bounce",
        target_chat_id="@tenant_a_ops",
        provider_status="delivered",
    )

    # Querying with Event B must return None
    assert repository.get_telegram_incident_log_by_event(event_b) is None

    # Querying Event A scoped to Tenant A returns the incident
    log_a = repository.get_telegram_incident_log_by_event(event_a, user_id=tenant_a)
    assert log_a is not None
    assert log_a["user_id"] == tenant_a

    # Querying Event A scoped to Tenant B returns None (tenant isolation enforced)
    assert repository.get_telegram_incident_log_by_event(event_a, user_id=tenant_b) is None


# ===========================================================================
# 23. Tenant Mismatch Cannot Authorize Finalization
# ===========================================================================
def test_tenant_mismatch_cannot_authorize_finalization():
    """Caller presenting Tenant B identity cannot finalize Tenant A's event."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": tenant_a,
        "processing_status": "dispatching",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    # Tenant B tries to mark processed -> rejected
    assert repository.mark_event_processed(evt_id, worker_id=worker_id, user_id=tenant_b) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "dispatching"

    # Tenant B tries to mark failed -> rejected
    assert repository.mark_event_failed(evt_id, reason="Unauthorized", worker_id=worker_id, user_id=tenant_b) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "dispatching"

    # Tenant A authorizes -> succeeds
    assert repository.mark_event_processed(evt_id, worker_id=worker_id, user_id=tenant_a) is True
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "processed"


# ===========================================================================
# 24. Strict Active-Lease Enforcement Regression Tests (Group 43H)
# ===========================================================================
def test_dispatch_intent_valid_owner_future_lease_accepted():
    """Valid worker holding an active unexpired lease is accepted for dispatch intent."""
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    assert repository.record_delivery_failure_dispatch_intent(evt_id, worker_id) is True
    stored = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert stored["processing_status"] == "dispatching"
    assert stored["dispatch_intent_at"] is not None


def test_dispatch_intent_null_lease_rejected():
    """An event with lease_until=None must be rejected (cannot bypass lease validation)."""
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": None,  # Explicitly NULL
    }

    assert repository.record_delivery_failure_dispatch_intent(evt_id, worker_id) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"


def test_dispatch_intent_missing_lease_field_rejected():
    """An event with lease_until omitted entirely must be rejected."""
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
        # 'lease_until' key not present
    }

    assert repository.record_delivery_failure_dispatch_intent(evt_id, worker_id) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"


def test_dispatch_intent_expired_lease_rejected():
    """An event with an expired lease_until in the past must be rejected."""
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": "2020-01-01T00:00:00+00:00",  # In the past
    }

    assert repository.record_delivery_failure_dispatch_intent(evt_id, worker_id) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"


def test_dispatch_intent_different_worker_rejected():
    """A worker that does not match claimed_by cannot acquire dispatch intent."""
    evt_id = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    w2 = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "processing_status": "queued",
        "claimed_by": w1,
        "lease_until": "2099-01-01T00:00:00+00:00",
    }

    assert repository.record_delivery_failure_dispatch_intent(evt_id, w2) is False
    assert supabase_service._in_memory_delivery_failure_events[evt_id]["processing_status"] == "queued"


def test_dispatch_intent_non_queued_status_rejected():
    """Events in statuses other than 'queued' (e.g. received, dispatching, processed) are rejected."""
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    for status in ("received", "dispatching", "quarantined", "processed", "failed", "ignored"):
        evt_id = str(uuid.uuid4())
        supabase_service._in_memory_delivery_failure_events[evt_id] = {
            "id": evt_id,
            "user_id": user_id,
            "processing_status": status,
            "claimed_by": worker_id,
            "lease_until": "2099-01-01T00:00:00+00:00",
        }
        assert repository.record_delivery_failure_dispatch_intent(evt_id, worker_id) is False, f"Failed for status: {status}"


@pytest.mark.asyncio
async def test_dispatch_intent_rejection_aborts_dispatch_without_telegram_call():
    """When dispatch intent is rejected (e.g. NULL lease), process_delivery_failure_event aborts without calling Telegram."""
    evt_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Pre-populate event with NULL lease in storage
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "event_type": "bounce",
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": None,  # Causes intent rejection
    }

    event = {
        "id": evt_id,
        "user_id": user_id,
        "event_type": "bounce",
        "esp_provider": "sendgrid",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": None,
    }

    with patch.object(telegram_alert_service, "dispatch_alert", new_callable=AsyncMock) as mock_dispatch:
        result = await process_delivery_failure_event(event, worker_id)

        assert result is False
        mock_dispatch.assert_not_called()
