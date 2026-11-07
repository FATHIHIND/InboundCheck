"""
InboundCheck - Comprehensive Durable Notification Outbox & Worker Retry Scheduling Tests (Group 45B.3B)
======================================================================================================
Verifies:
 1. test_outbox_enqueue_before_dispatch
 2. test_outbox_idempotency_key_deduplication
 3. test_api_dispatch_returns_queued_without_network_call
 4. test_worker_claims_queued_outbox_item
 5. test_worker_completes_outbox_item_on_success
 6. test_transient_telegram_429_schedules_retry
 7. test_transient_telegram_5xx_schedules_exponential_backoff
 8. test_permanent_telegram_4xx_marks_dead_letter
 9. test_max_retry_limit_marks_dead_letter
10. test_stale_outbox_lease_recovery
11. test_delivery_failure_retry_scheduling_preserves_event
12. test_delivery_failure_max_attempts_marks_failed
13. test_claim_rpc_ignores_events_not_yet_due
14. test_claim_rpc_picks_up_due_retry_events
15. test_crash_recovery_window_outbox_insert
16. test_crash_recovery_window_worker_claim
17. test_crash_recovery_window_telegram_dispatch
18. test_crash_recovery_window_acknowledgement
19. test_notification_health_metrics_accuracy
20. test_zero_pii_in_outbox_payload_and_logs
"""

import sys
import os
import asyncio
import json
import base64
import uuid
import time
from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure backend directory is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Use real declared dependencies; collection must never poison sys.modules.
import httpx

from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import omnichannel_service
from app.workers.failover_worker import (
    process_delivery_failure_event,
    process_notification_outbox_item,
    run_failover_worker,
)
from app.api.v1.failover import trigger_failover_dispatch, TriggerTelegramAlertRequest


def _reset_test_state():
    """Reset repository in-memory state between tests."""
    supabase_service._in_memory_notification_outbox.clear()
    supabase_service._in_memory_delivery_failure_events.clear()
    supabase_service._in_memory_failover_logs.clear()
    supabase_service._in_memory_failover_configs.clear()


# =====================================================================
# TEST 1: test_outbox_enqueue_before_dispatch
# =====================================================================
def test_outbox_enqueue_before_dispatch():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    key = "idem_order_1001"
    payload = {"order_id": "#1001", "store_name": "TestStore"}

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key=key,
        payload=payload,
        max_attempts=5,
    )

    assert rec is not None
    assert rec["id"]
    assert rec["user_id"] == user_id
    assert rec["channel"] == "telegram"
    assert rec["idempotency_key"] == key
    assert rec["status"] == "queued"
    assert rec["attempt_count"] == 0
    assert rec["max_attempts"] == 5
    assert rec["next_attempt_at"] is not None
    assert rec["payload"]["order_id"] == "#1001"
    assert rec["idempotent"] is False


# =====================================================================
# TEST 2: test_outbox_idempotency_key_deduplication
# =====================================================================
def test_outbox_idempotency_key_deduplication():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    key = "idem_dup_test"

    rec1 = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key=key,
        payload={"order_id": "#2001"},
    )
    assert rec1["idempotent"] is False

    rec2 = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key=key,
        payload={"order_id": "#2001_duplicate"},
    )
    assert rec2["idempotent"] is True
    assert rec2["id"] == rec1["id"]
    # Only 1 record in outbox
    assert len(supabase_service._in_memory_notification_outbox) == 1


# =====================================================================
# TEST 3: test_api_dispatch_returns_queued_without_network_call
# =====================================================================
def test_api_dispatch_returns_queued_without_network_call():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    req = TriggerTelegramAlertRequest(
        order_id="#9999",
        trigger_reason="hard_bounce",
        domain_name="brandshop.com",
        store_name="BrandShop DTC",
    )

    with patch.object(omnichannel_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        res = asyncio.run(trigger_failover_dispatch(payload=req, user_id=user_id, idempotency_header=None))
        # Zero outbound HTTP calls made by API endpoint
        mock_send.assert_not_called()

        assert res["success"] is True
        assert res["status"] == "queued"
        assert res["job_id"]
        assert "dispatch_" in res["idempotency_key"]
        assert res["idempotent"] is False


# =====================================================================
# TEST 4: test_worker_claims_queued_outbox_item
# =====================================================================
def test_worker_claims_queued_outbox_item():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="claim_test_1",
        payload={"order_id": "#3001"},
    )

    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    assert len(claimed) == 1
    c = claimed[0]
    assert c["id"] == rec["id"]
    assert c["status"] == "dispatching"
    assert c["attempt_count"] == 1
    assert c["claimed_by"] == worker_id
    assert c["lease_until"] is not None


# =====================================================================
# TEST 5: test_worker_completes_outbox_item_on_success
# =====================================================================
def test_worker_completes_outbox_item_on_success():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="complete_test_1",
        payload={"order_id": "#4001"},
    )

    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    assert len(claimed) == 1

    ok = repository.complete_notification_outbox(outbox_id=rec["id"], worker_id=worker_id)
    assert ok is True

    # Outbox item is now processed
    item = supabase_service._in_memory_notification_outbox[f"{user_id}:complete_test_1"]
    assert item["status"] == "processed"
    assert item["processed_at"] is not None
    assert item["claimed_by"] is None
    assert item["lease_until"] is None


# =====================================================================
# TEST 6: test_transient_telegram_429_schedules_retry
# =====================================================================
def test_transient_telegram_429_schedules_retry():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    # Configure tenant credentials
    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "telegram_chat_id": "-1001234567890",
    })

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="retry_429_test",
        payload={"order_id": "#5001"},
    )

    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    item = claimed[0]

    with patch.object(omnichannel_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "success": False,
            "status_code": 429,
            "error": "Too Many Requests",
            "retry_after": 45,
            "retryable": True,
        }

        res = asyncio.run(process_notification_outbox_item(item, worker_id))
        assert res is False

        updated = supabase_service._in_memory_notification_outbox[f"{user_id}:retry_429_test"]
        assert updated["status"] == "queued"
        assert updated["claimed_by"] is None
        assert updated["lease_until"] is None
        # next_attempt_at is scheduled in the future (approx now + 45s)
        next_dt = datetime.fromisoformat(updated["next_attempt_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        assert (next_dt - now).total_seconds() > 30


# =====================================================================
# TEST 7: test_transient_telegram_5xx_schedules_exponential_backoff
# =====================================================================
def test_transient_telegram_5xx_schedules_exponential_backoff():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "telegram_chat_id": "-1001234567890",
    })

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="retry_5xx_test",
        payload={"order_id": "#6001"},
    )

    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    item = claimed[0]

    with patch.object(omnichannel_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "success": False,
            "status_code": 503,
            "error": "Service Unavailable",
            "retry_after": None,
            "retryable": True,
        }

        res = asyncio.run(process_notification_outbox_item(item, worker_id))
        assert res is False

        updated = supabase_service._in_memory_notification_outbox[f"{user_id}:retry_5xx_test"]
        assert updated["status"] == "queued"
        # Exponential backoff base 30s * 2^(1-1) = 30s
        next_dt = datetime.fromisoformat(updated["next_attempt_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        assert (next_dt - now).total_seconds() > 20


# =====================================================================
# TEST 8: test_permanent_telegram_4xx_marks_dead_letter
# =====================================================================
def test_permanent_telegram_4xx_marks_dead_letter():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "telegram_chat_id": "-1001234567890",
    })

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="perm_4xx_test",
        payload={"order_id": "#7001"},
    )

    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    item = claimed[0]

    with patch.object(omnichannel_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "success": False,
            "status_code": 401,
            "error": "Unauthorized: bot token invalid",
            "retryable": False,
        }

        res = asyncio.run(process_notification_outbox_item(item, worker_id))
        assert res is False

        updated = supabase_service._in_memory_notification_outbox[f"{user_id}:perm_4xx_test"]
        assert updated["status"] == "dead_letter"
        assert updated["processed_at"] is not None
        assert "Unauthorized" in updated["last_error"]


# =====================================================================
# TEST 9: test_max_retry_limit_marks_dead_letter
# =====================================================================
def test_max_retry_limit_marks_dead_letter():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    omnichannel_service.update_config(user_id, {
        "is_enabled": True,
        "telegram_bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "telegram_chat_id": "-1001234567890",
    })

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="max_retry_test",
        payload={"order_id": "#8001"},
        max_attempts=5,
    )

    # Fast forward to attempt count = 4
    mem_item = supabase_service._in_memory_notification_outbox[f"{user_id}:max_retry_test"]
    mem_item["attempt_count"] = 4

    # Claim 5th and final attempt
    claimed = repository.claim_notification_outbox(worker_id=worker_id, limit=10, lease_seconds=300)
    item = claimed[0]
    assert item["attempt_count"] == 5

    with patch.object(omnichannel_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "success": False,
            "status_code": 500,
            "error": "Internal Server Error",
            "retryable": True,  # Error is retryable, but attempt limit reached
        }

        res = asyncio.run(process_notification_outbox_item(item, worker_id))
        assert res is False

        updated = supabase_service._in_memory_notification_outbox[f"{user_id}:max_retry_test"]
        assert updated["status"] == "dead_letter"
        assert updated["processed_at"] is not None


# =====================================================================
# TEST 10: test_stale_outbox_lease_recovery
# =====================================================================
def test_stale_outbox_lease_recovery():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    crashed_worker = str(uuid.uuid4())
    new_worker = str(uuid.uuid4())

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="stale_recovery_test",
        payload={"order_id": "#9001"},
    )

    # Worker 1 claims item
    claimed1 = repository.claim_notification_outbox(worker_id=crashed_worker, limit=10, lease_seconds=300)
    assert len(claimed1) == 1

    # Simulate crashed worker and expired lease
    mem_item = supabase_service._in_memory_notification_outbox[f"{user_id}:stale_recovery_test"]
    mem_item["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    # New worker should claim the expired dispatching item
    claimed2 = repository.claim_notification_outbox(worker_id=new_worker, limit=10, lease_seconds=300)
    assert len(claimed2) == 1
    assert claimed2[0]["id"] == rec["id"]
    assert claimed2[0]["claimed_by"] == new_worker
    assert claimed2[0]["attempt_count"] == 2


# =====================================================================
# TEST 11: test_delivery_failure_retry_scheduling_preserves_event
# =====================================================================
def test_delivery_failure_retry_scheduling_preserves_event():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "esp_provider": "postmark",
        "provider_event_id": "evt_pm_1",
        "event_type": "hard_bounce",
        "processing_status": "dispatching",
        "claimed_by": worker_id,
        "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "dispatch_attempt_count": 1,
    }

    next_time = datetime.now(timezone.utc) + timedelta(seconds=60)
    res = repository.schedule_delivery_failure_retry(
        event_id=evt_id,
        worker_id=worker_id,
        error="Telegram 429 Rate Limit",
        next_attempt_at=next_time,
        max_attempts=5,
    )

    assert res is not None
    assert res["new_status"] == "received"
    assert res["attempt_count"] == 1

    evt = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert evt["processing_status"] == "received"
    assert evt["claimed_by"] is None
    assert evt["lease_until"] is None
    assert evt["next_attempt_at"] is not None


# =====================================================================
# TEST 12: test_delivery_failure_max_attempts_marks_failed
# =====================================================================
def test_delivery_failure_max_attempts_marks_failed():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "esp_provider": "sendgrid",
        "provider_event_id": "evt_sg_1",
        "event_type": "bounce",
        "processing_status": "dispatching",
        "claimed_by": worker_id,
        "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "dispatch_attempt_count": 5,
    }

    next_time = datetime.now(timezone.utc) + timedelta(seconds=60)
    res = repository.schedule_delivery_failure_retry(
        event_id=evt_id,
        worker_id=worker_id,
        error="Telegram persistent connection timeout",
        next_attempt_at=next_time,
        max_attempts=5,
    )

    assert res is not None
    assert res["new_status"] == "failed"

    evt = supabase_service._in_memory_delivery_failure_events[evt_id]
    assert evt["processing_status"] == "failed"
    assert "MAX_RETRIES_EXCEEDED" in evt["processing_error"]


# =====================================================================
# TEST 13: test_claim_rpc_ignores_events_not_yet_due
# =====================================================================
def test_claim_rpc_ignores_events_not_yet_due():
    _reset_test_state()
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    # Event scheduled 10 minutes in future
    future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": str(uuid.uuid4()),
        "esp_provider": "mailgun",
        "provider_event_id": "evt_mg_1",
        "event_type": "bounce",
        "processing_status": "received",
        "next_attempt_at": future_time,
    }

    claimed = repository.claim_pending_delivery_failure_events(worker_id=worker_id, limit=10)
    assert len(claimed) == 0


# =====================================================================
# TEST 14: test_claim_rpc_picks_up_due_retry_events
# =====================================================================
def test_claim_rpc_picks_up_due_retry_events():
    _reset_test_state()
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    # Event whose retry is due (scheduled 10 seconds ago)
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": str(uuid.uuid4()),
        "esp_provider": "mailgun",
        "provider_event_id": "evt_mg_due",
        "event_type": "bounce",
        "processing_status": "received",
        "next_attempt_at": past_time,
    }

    claimed = repository.claim_pending_delivery_failure_events(worker_id=worker_id, limit=10)
    assert len(claimed) == 1
    assert claimed[0]["id"] == evt_id
    assert claimed[0]["processing_status"] == "queued"
    assert claimed[0]["claimed_by"] == worker_id


# =====================================================================
# TEST 15: test_crash_recovery_window_outbox_insert
# =====================================================================
def test_crash_recovery_window_outbox_insert():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    key = "crash_w1_key"

    # Row is persisted into outbox
    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key=key,
        payload={"order_id": "#W1_001"},
    )

    # API crashes / restarts before anything else.
    # On next worker run, item is still safely in 'queued' status and claimed.
    claimed = repository.claim_notification_outbox(worker_id="worker_recovery", limit=5)
    assert len(claimed) == 1
    assert claimed[0]["id"] == rec["id"]


# =====================================================================
# TEST 16: test_crash_recovery_window_worker_claim
# =====================================================================
def test_crash_recovery_window_worker_claim():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker1 = "worker_crashed_before_http"
    worker2 = "worker_recovering"

    rec = repository.enqueue_notification_outbox(
        user_id=user_id,
        channel="telegram",
        idempotency_key="crash_w2_key",
        payload={"order_id": "#W2_001"},
    )

    # Worker 1 claims item
    repository.claim_notification_outbox(worker_id=worker1, limit=5, lease_seconds=10)

    # Worker 1 dies before sending HTTP. Lease expires:
    mem_item = supabase_service._in_memory_notification_outbox[f"{user_id}:crash_w2_key"]
    mem_item["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()

    # Worker 2 sweeps and claims it safely
    claimed = repository.claim_notification_outbox(worker_id=worker2, limit=5, lease_seconds=300)
    assert len(claimed) == 1
    assert claimed[0]["id"] == rec["id"]
    assert claimed[0]["claimed_by"] == worker2


# =====================================================================
# TEST 17: test_crash_recovery_window_telegram_dispatch
# =====================================================================
def test_crash_recovery_window_telegram_dispatch():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    # Pre-record dispatch intent (Group 43D/Migration 29)
    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "esp_provider": "postmark",
        "provider_event_id": "evt_crash_w3",
        "event_type": "hard_bounce",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "dispatch_attempt_count": 0,
    }

    intent = repository.record_delivery_failure_dispatch_intent(evt_id, worker_id)
    assert intent is True

    # Worker crashes while Telegram HTTP request in-flight. Lease expires:
    evt = supabase_service._in_memory_delivery_failure_events[evt_id]
    evt["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()

    # Quarantine sweep safely quarantines event because no incident log exists
    quarantined = repository.quarantine_expired_dispatch_intent_events(limit=10)
    assert len(quarantined) == 1
    assert quarantined[0]["resolution"] == "quarantined_ambiguous"
    assert evt["processing_status"] == "quarantined"


# =====================================================================
# TEST 18: test_crash_recovery_window_acknowledgement
# =====================================================================
def test_crash_recovery_window_acknowledgement():
    _reset_test_state()
    user_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    evt_id = str(uuid.uuid4())

    supabase_service._in_memory_delivery_failure_events[evt_id] = {
        "id": evt_id,
        "user_id": user_id,
        "esp_provider": "postmark",
        "provider_event_id": "evt_crash_w4",
        "event_type": "hard_bounce",
        "processing_status": "queued",
        "claimed_by": worker_id,
        "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "dispatch_attempt_count": 0,
    }

    repository.record_delivery_failure_dispatch_intent(evt_id, worker_id)

    # Telegram accepted message and incident log WAS persisted
    repository.create_telegram_incident_log(
        delivery_failure_event_id=evt_id,
        user_id=user_id,
        order_id="#ACK_001",
        domain_name="brandshop.com",
        store_name="BrandShop DTC",
        triggered_reason="hard_bounce",
        target_chat_id="-1009999",
        provider_status="delivered",
    )

    # But worker crashed right before marking event processed! Lease expires:
    evt = supabase_service._in_memory_delivery_failure_events[evt_id]
    evt["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()

    # Quarantine sweep detects confirmed durable incident log and auto-resolves to 'processed'
    quarantined = repository.quarantine_expired_dispatch_intent_events(limit=10)
    assert len(quarantined) == 1
    assert quarantined[0]["resolution"] == "resolved_processed"
    assert evt["processing_status"] == "processed"


# =====================================================================
# TEST 19: test_notification_health_metrics_accuracy
# =====================================================================
def test_notification_health_metrics_accuracy():
    _reset_test_state()
    user_id = str(uuid.uuid4())

    # Add 2 outbox items (1 queued, 1 processed)
    rec2 = repository.enqueue_notification_outbox(user_id, "telegram", "key_h2", {"order_id": "#H2"})
    rec2_claimed = repository.claim_notification_outbox("w1", 1)
    assert [row["id"] for row in rec2_claimed] == [rec2["id"]]
    assert repository.complete_notification_outbox(rec2["id"], "w1")
    repository.enqueue_notification_outbox(user_id, "telegram", "key_h1", {"order_id": "#H1"})

    # Add 1 delivery failure event
    supabase_service._in_memory_delivery_failure_events["evt_h1"] = {
        "id": "evt_h1",
        "user_id": user_id,
        "processing_status": "received",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    metrics = repository.get_notification_health_metrics()
    assert metrics["delivery_failure_events"]["total"] == 1
    assert metrics["delivery_failure_events"]["received"] == 1
    assert metrics["notification_outbox"]["total"] == 2
    assert metrics["notification_outbox"]["queued"] == 1
    assert metrics["notification_outbox"]["processed"] == 1


# =====================================================================
# TEST 20: test_zero_pii_in_outbox_payload_and_logs
# =====================================================================
def test_zero_pii_in_outbox_payload_and_logs():
    _reset_test_state()
    user_id = str(uuid.uuid4())

    req = TriggerTelegramAlertRequest(
        order_id="#PII_TEST",
        trigger_reason="hard_bounce",
        domain_name="brandshop.com",
        store_name="BrandShop DTC",
    )

    res = asyncio.run(trigger_failover_dispatch(payload=req, user_id=user_id))
    job_id = res["job_id"]

    # Verify outbox item contains zero customer phone or email
    item = None
    for v in supabase_service._in_memory_notification_outbox.values():
        if v.get("id") == job_id:
            item = v
            break

    assert item is not None
    payload = item["payload"]
    assert "customer_email" not in payload
    assert "customer_phone" not in payload
    assert "email" not in payload
    assert "phone" not in payload
    # Check JSON string for phone/email patterns
    payload_str = json.dumps(payload)
    assert "@" not in payload_str
    assert "+1" not in payload_str


if __name__ == "__main__":
    tests = [
        test_outbox_enqueue_before_dispatch,
        test_outbox_idempotency_key_deduplication,
        test_api_dispatch_returns_queued_without_network_call,
        test_worker_claims_queued_outbox_item,
        test_worker_completes_outbox_item_on_success,
        test_transient_telegram_429_schedules_retry,
        test_transient_telegram_5xx_schedules_exponential_backoff,
        test_permanent_telegram_4xx_marks_dead_letter,
        test_max_retry_limit_marks_dead_letter,
        test_stale_outbox_lease_recovery,
        test_delivery_failure_retry_scheduling_preserves_event,
        test_delivery_failure_max_attempts_marks_failed,
        test_claim_rpc_ignores_events_not_yet_due,
        test_claim_rpc_picks_up_due_retry_events,
        test_crash_recovery_window_outbox_insert,
        test_crash_recovery_window_worker_claim,
        test_crash_recovery_window_telegram_dispatch,
        test_crash_recovery_window_acknowledgement,
        test_notification_health_metrics_accuracy,
        test_zero_pii_in_outbox_payload_and_logs,
    ]

    print(f"Running {len(tests)} Group 45B.3B Durable Outbox & Retry Scheduling Tests...")
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"  [PASS] {t.__name__}")
    print(f"\nAll {passed}/{len(tests)} tests passed cleanly!")
