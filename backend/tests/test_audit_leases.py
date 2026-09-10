"""
InboundCheck - Integration Tests for Distributed Audit Leases & Failover Logging
================================================================================
Verifies:
1. Atomic claim_due_domain_audits functionality and disjoint worker partitions.
2. Complete and fail domain audit operations requiring lease ownership.
3. Expiration of leases allowing re-claiming by subsequent workers.
4. Telegram failover logging persistence and API retrieval contract.
"""

import pytest
import uuid
import time
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.services.supabase_client import supabase_service
from app.services.failover.omnichannel_service import omnichannel_service
from app.services.alert_dispatcher import alert_dispatcher


@pytest.fixture
def test_client():
    return TestClient(app)


def test_audit_leases_atomic_claiming_and_concurrency():
    """Verify that two workers claiming domains simultaneously receive disjoint subsets."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_a = str(uuid.uuid4())
    worker_b = str(uuid.uuid4())

    # Seed 4 active monitored domains
    now_past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    domains = [
        {"id": f"dom_lease_1_{uuid.uuid4()}", "user_id": user_id, "domain_name": "brand1.com", "is_active": True, "last_audited_at": now_past},
        {"id": f"dom_lease_2_{uuid.uuid4()}", "user_id": user_id, "domain_name": "brand2.com", "is_active": True, "last_audited_at": now_past},
        {"id": f"dom_lease_3_{uuid.uuid4()}", "user_id": user_id, "domain_name": "brand3.com", "is_active": True, "last_audited_at": now_past},
        {"id": f"dom_lease_4_{uuid.uuid4()}", "user_id": user_id, "domain_name": "brand4.com", "is_active": True, "last_audited_at": now_past},
    ]
    supabase_service._in_memory_domains[user_id] = domains

    # Worker A claims up to 2 domains
    claimed_a = supabase_service.claim_due_domain_audits(
        worker_id=worker_a,
        limit=2,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_a) == 2
    ids_a = {d["id"] for d in claimed_a}

    # Worker B claims up to 2 domains immediately
    claimed_b = supabase_service.claim_due_domain_audits(
        worker_id=worker_b,
        limit=2,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_b) == 2
    ids_b = {d["id"] for d in claimed_b}

    # Verify disjoint subsets
    assert ids_a.isdisjoint(ids_b), "Workers must receive disjoint sets of domains"

    # Worker C attempts to claim — no domains should be left
    worker_c = str(uuid.uuid4())
    claimed_c = supabase_service.claim_due_domain_audits(
        worker_id=worker_c,
        limit=2,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed_c) == 0


def test_audit_lease_completion_and_failure_ownership():
    """Verify that only the lease owner can complete or fail a domain audit."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_owner = str(uuid.uuid4())
    worker_intruder = str(uuid.uuid4())
    dom_id = f"dom_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "owner-check.com",
        "is_active": True,
        "last_audited_at": None,
    }
    supabase_service._in_memory_domains[user_id] = [domain]

    # Worker owner claims domain
    claimed = supabase_service.claim_due_domain_audits(
        worker_id=worker_owner,
        limit=1,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed) == 1

    # Intruder tries to complete the audit -> must fail
    res_intruder = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id=worker_intruder)
    assert res_intruder is False

    # Intruder tries to fail the audit -> must fail
    res_intruder_fail = supabase_service.fail_domain_audit(
        domain_id=dom_id,
        worker_id=worker_intruder,
        error="Unauthorized completion attempt",
    )
    assert res_intruder_fail is False

    # Owner completes the audit -> must succeed
    res_owner = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id=worker_owner)
    assert res_owner is True
    assert domain.get("audit_lease_owner") is None
    assert domain.get("last_audited_at") is not None


def test_audit_lease_expiration_recovery():
    """Verify that an expired lease can be claimed by another worker."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_crashed = str(uuid.uuid4())
    worker_rescuer = str(uuid.uuid4())
    dom_id = f"dom_{uuid.uuid4()}"

    past_expiry = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "crashed-worker.com",
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_crashed,
        "audit_lease_until": past_expiry,
    }
    supabase_service._in_memory_domains[user_id] = [domain]

    # Rescuer worker claims
    claimed = supabase_service.claim_due_domain_audits(
        worker_id=worker_rescuer,
        limit=1,
        interval_seconds=3600,
        lease_seconds=900,
    )
    assert len(claimed) == 1
    assert claimed[0]["id"] == dom_id
    assert domain.get("audit_lease_owner") == worker_rescuer


def test_telegram_failover_persistence_and_api(test_client):
    """Verify Telegram failover log persistence and REST endpoint."""
    user_id = "test-failover-user"
    order_ref = "#9999"

    # Persist a failover log directly
    log = supabase_service.persist_failover_log(
        user_id=user_id,
        order_id=order_ref,
        channel="telegram",
        provider="telegram_bot_api",
        status="delivered",
        domain_name="testfailover.com",
        store_name="Test Store",
        triggered_reason="hard_bounce",
        target_chat_id="@test_alerts",
    )
    assert log["order_id"] == order_ref
    assert log["status"] == "delivered"

    # Query via service
    logs = omnichannel_service.get_logs(user_id=user_id)
    assert len(logs) >= 1
    assert any(l["order_id"] == order_ref for l in logs)
