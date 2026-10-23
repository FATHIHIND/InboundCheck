"""
InboundCheck - Background Auditor & Degradation Alert Dispatcher Unit Tests
===========================================================================
Verifies:
1. Intelligent deliverability degradation alert evaluation on threshold dip.
2. Suppression of alerts on healthy/optimal domain verification.
3. Autonomous BackgroundAuditor cycle execution, snapshot creation, and alert dispatch.
4. Reputation trend telemetry endpoint (/api/v1/analytics/reputation-trend).
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.alert_dispatcher import alert_dispatcher
from app.services.scheduler.background_auditor import background_auditor
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def isolate_supabase_for_scheduler_tests():
    """Ensure scheduler tests are strictly isolated from any live Supabase instance."""
    orig_client = supabase_service._client
    orig_domains = dict(supabase_service._in_memory_domains)
    orig_reputation = dict(getattr(supabase_service, "_in_memory_reputation", {}))

    supabase_service._client = None
    supabase_service._in_memory_domains.clear()
    if hasattr(supabase_service, "_in_memory_reputation"):
        supabase_service._in_memory_reputation.clear()

    yield

    supabase_service._client = orig_client
    supabase_service._in_memory_domains = orig_domains
    if hasattr(supabase_service, "_in_memory_reputation"):
        supabase_service._in_memory_reputation = orig_reputation


@pytest.mark.asyncio
async def test_alert_dispatcher_degradation_triggers():
    """Verify alert is dispatched when score dips below threshold, and suppressed when optimal."""
    test_user = "22222222-2222-2222-2222-222222222222"
    alert_dispatcher.set_tenant_alert_config(test_user, {
        "alert_on_score_drop": True,
        "score_threshold": 80,
        "alert_on_spf_error": True,
        "alert_on_dkim_fail": True,
        "alert_on_dmarc_change": True,
        "telegram_bot_token": "mock_token_123",
        "telegram_chat_id": "@test_chat"
    })

    # 1. Healthy domain (92% >= 80% threshold, no protocol errors) must NOT trigger alert
    res_healthy = await alert_dispatcher.evaluate_and_dispatch(
        user_id=test_user,
        domain_name="clean-brand.com",
        health_score=92,
        overall_status="optimal",
        summary=None,
        issues=[]
    )
    assert res_healthy["dispatched"] is False
    assert len(res_healthy["reasons"]) == 0

    # 2. Degraded domain (68% < 80% threshold) MUST trigger alert
    res_degraded = await alert_dispatcher.evaluate_and_dispatch(
        user_id=test_user,
        domain_name="degraded-store.com",
        health_score=68,
        overall_status="warning",
        summary=None,
        issues=[]
    )
    assert res_degraded["dispatched"] is True
    assert any("dipped to 68%" in r for r in res_degraded["reasons"])

    # 2b. Repeated degraded evaluation within 6 hours MUST be suppressed by cooldown
    res_suppressed = await alert_dispatcher.evaluate_and_dispatch(
        user_id=test_user,
        domain_name="degraded-store.com",
        health_score=68,
        overall_status="warning",
        summary=None,
        issues=[]
    )
    assert res_suppressed["dispatched"] is False
    assert res_suppressed.get("cooldown") is True

    # Reset cooldown allows re-dispatch
    alert_dispatcher.reset_cooldown(test_user, "degraded-store.com")
    res_rearmed = await alert_dispatcher.evaluate_and_dispatch(
        user_id=test_user,
        domain_name="degraded-store.com",
        health_score=68,
        overall_status="warning",
        summary=None,
        issues=[]
    )
    assert res_rearmed["dispatched"] is True

    # 3. Failover alert dispatch
    failover_res = await alert_dispatcher.dispatch_failover_alert(
        user_id=test_user,
        domain_name="degraded-store.com",
        order_id="ORD-9999",
        trigger_reason="hard_bounce",
        customer_email="customer@example.com"
    )
    assert failover_res is not None


@pytest.mark.asyncio
async def test_background_auditor_cycle():
    """Verify BackgroundAuditor audits active domains, creates snapshots, and reports metrics."""
    test_user = "33333333-3333-3333-3333-333333333333"
    supabase_service._in_memory_domains[test_user] = [
        {
            "id": "dom_sched_1",
            "user_id": test_user,
            "domain_name": "shopify.com",
            "is_active": True,
            "health_score": 95
        }
    ]

    # Run single audit pass
    metrics = await background_auditor.run_audit_cycle()
    assert metrics["success"] is True
    assert metrics["audited_count"] >= 1
    assert metrics["cycle_number"] >= 1
    assert "timestamp" in metrics


@pytest.mark.asyncio
async def test_reputation_trend_endpoint():
    """Verify /api/v1/analytics/reputation-trend returns trajectory points."""
    test_user = "test-user-1"
    supabase_service._in_memory_reputation[test_user] = [
        {
            "id": "chk_trend_1",
            "domain_name": "shopify.com",
            "score": 92,
            "dns_score": 94,
            "rbl_clean_count": 10,
            "rbl_total_count": 10,
            "predicted_risk_48h": "low",
            "created_at": "2026-09-09T12:00:00Z"
        }
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(test_user)) as ac:
        res = await ac.get("/api/v1/analytics/reputation-trend")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["points"]) > 0
        point = data["points"][0]
        assert "unified_score" in point
        assert "dns_health_score" in point
        assert "risk_level" in point


@pytest.mark.asyncio
async def test_alert_dispatcher_dispatch_failover_alert_regression():
    """
    Focused regression test proving dispatch_failover_alert:
    1. Correctly constructs alert_text and dispatches via telegram_alert_service.
    2. Gracefully handles unconfigured credentials with skipped status.
    3. Persists failover incident record to supabase_service.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.failover.omnichannel_service import telegram_alert_service

    user_with_creds = "user-failover-creds-123"
    alert_dispatcher.set_tenant_alert_config(user_with_creds, {
        "telegram_bot_token": "9876543210:AAH8Fj90qWz1x9_liveTestTokenSafe123",
        "telegram_chat_id": "-100987654321",
    })

    with patch.object(telegram_alert_service, "send_telegram_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "data": {"message_id": "tg_msg_777"}}

        res = await alert_dispatcher.dispatch_failover_alert(
            user_id=user_with_creds,
            domain_name="test-failover-store.com",
            order_id="ORD-777",
            trigger_reason="hard_bounce",
            customer_email="buyer@brand.com",
        )

        assert res["success"] is True
        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["bot_token"] == "9876543210:AAH8Fj90qWz1x9_liveTestTokenSafe123"
        assert call_kwargs["chat_id"] == "-100987654321"
        dispatched_text = call_kwargs["text"]
        assert "test-failover-store.com" in dispatched_text
        assert "ORD-777" in dispatched_text
        assert "hard_bounce" in dispatched_text
        assert "buyer@brand.com" in dispatched_text

    # Test skipped path when credentials unconfigured
    user_no_creds = "user-failover-nocreds-456"
    alert_dispatcher.set_tenant_alert_config(user_no_creds, {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    })

    with patch("app.core.config.settings.TELEGRAM_BOT_TOKEN", None), \
         patch("app.core.config.settings.TELEGRAM_CHAT_ID", None):
        res_skipped = await alert_dispatcher.dispatch_failover_alert(
            user_id=user_no_creds,
            domain_name="unconfigured-store.com",
            order_id="ORD-000",
            trigger_reason="spam_trap",
            customer_email="anon@test.com",
        )
        assert res_skipped.get("skipped") is True
        assert res_skipped.get("success") is False


@pytest.mark.asyncio
async def test_background_auditor_zero_claimed_performs_zero_work():
    """
    P1 Regression Test 1:
    When claim_due_domain_audits returns no domains, BackgroundAuditor.run_audit_cycle
    must return a successful zero-work result immediately.
    Proves that NO diagnostic engine call, unleased upsert, audit log insertion,
    reputation snapshot, alert dispatch, or lease completion is attempted.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor

    auditor = BackgroundAuditor()
    supabase_service._in_memory_domains.clear()

    with patch.object(supabase_service, "claim_due_domain_audits", return_value=[]) as mock_claim, \
         patch.object(auditor.diagnostic_engine, "audit_domain", new_callable=AsyncMock) as mock_audit, \
         patch.object(supabase_service, "create_or_update_domain") as mock_upsert, \
         patch.object(supabase_service, "save_audit_log") as mock_save_log, \
         patch.object(alert_dispatcher, "evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert, \
         patch.object(supabase_service, "complete_domain_audit") as mock_complete:

        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is True
        assert metrics["audited_count"] == 0
        assert metrics["snapshots_created"] == 0
        assert metrics["alerts_dispatched"] == 0
        assert metrics["cycle_number"] >= 1
        assert "timestamp" in metrics

        mock_claim.assert_called_once()
        mock_audit.assert_not_called()
        mock_upsert.assert_not_called()
        mock_save_log.assert_not_called()
        mock_alert.assert_not_called()
        mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_background_auditor_actively_leased_by_other_worker_is_untouched():
    """
    P1 Regression Test 2:
    A domain actively leased by another worker (unexpired audit_lease_until)
    must NOT be claimed, audited, or modified by BackgroundAuditor.
    """
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor

    auditor = BackgroundAuditor()
    user_id = "user-other-lease-holder"
    future_lease = (datetime.now(timezone.utc) + timedelta(minutes=14)).isoformat()

    seeded_domain = {
        "id": "dom_leased_elsewhere",
        "user_id": user_id,
        "domain_name": "leased-by-other.com",
        "is_active": True,
        "health_score": 98,
        "spf_status": "optimal",
        "dkim_status": "optimal",
        "dmarc_status": "optimal",
        "audit_lease_owner": "worker-uuid-other-999",
        "audit_lease_until": future_lease,
        "last_audited_at": None,
        "audit_failure_count": 0,
    }
    supabase_service._in_memory_domains.clear()
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    with patch.object(auditor.diagnostic_engine, "audit_domain", new_callable=AsyncMock) as mock_dns:
        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is True
        assert metrics["audited_count"] == 0
        assert metrics["snapshots_created"] == 0
        mock_dns.assert_not_called()

        # Domain in database must remain 100% untouched
        persisted = supabase_service._in_memory_domains[user_id][0]
        assert persisted["audit_lease_owner"] == "worker-uuid-other-999"
        assert persisted["audit_lease_until"] == future_lease
        assert persisted["health_score"] == 98


@pytest.mark.asyncio
async def test_background_auditor_genuinely_claimed_domain_lifecycle():
    """
    P1 Regression Test 3:
    When a domain is legitimately claimed under lease, BackgroundAuditor executes
    the full audit, updates diagnostics, inserts logs & snapshots, dispatches alerts,
    and releases the lease.
    """
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.schemas.dns import DiagnosticSummary

    auditor = BackgroundAuditor()
    user_id = "user-claimed-lifecycle"
    dom_id = "dom_claimed_123"
    domain_name = "legitimately-claimed.com"

    seeded_domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": domain_name,
        "is_active": True,
        "health_score": 50,
        "last_audited_at": None,
        "audit_lease_owner": None,
        "audit_lease_until": None,
    }
    supabase_service._in_memory_domains.clear()
    supabase_service._in_memory_domains[user_id] = [seeded_domain]

    mock_summary = MagicMock(spec=DiagnosticSummary)
    mock_summary.model_dump.return_value = {
        "spf": {"status": "optimal"},
        "dkim": {"status": "optimal"},
        "dmarc": {"status": "optimal"},
        "mx": {"status": "optimal"},
        "bimi": {"status": "optimal"},
    }
    mock_raw = {"dns": {"a": ["198.51.100.1"]}}

    with patch.object(auditor.diagnostic_engine, "audit_domain", new_callable=AsyncMock) as mock_dns, \
         patch("app.services.scheduler.background_auditor.DeliverabilityScorer.calculate_health_score") as mock_calc:

        mock_dns.return_value = (mock_summary, mock_raw, 45.0)
        mock_calc.return_value = (96, "optimal", {}, [], [])

        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is True
        assert metrics["audited_count"] == 1
        assert metrics["snapshots_created"] == 1
        mock_dns.assert_called_once_with(domain_name)

        # Lease must have been released by complete_domain_audit
        persisted = supabase_service._in_memory_domains[user_id][0]
        assert persisted["audit_lease_owner"] is None
        assert persisted["audit_lease_until"] is None
        assert persisted["last_audited_at"] is not None
        assert persisted["health_score"] == 96


@pytest.mark.asyncio
async def test_synchronous_provisioning_and_manual_audit_independent_of_scheduler():
    """
    P1 Regression Test 4:
    Proves that legitimate synchronous domain-provisioning (provision_monitored_domain)
    and on-demand manual audit execution operate independently of BackgroundAuditor.
    """
    user_id = "user-sync-independence-99"
    domain_name = "sync-independent-store.com"
    supabase_service._in_memory_domains.clear()

    # 1. Provision domain synchronously
    audit_payload = {
        "health_score": 94,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "optimal"},
            "dmarc": {"status": "optimal"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "optimal"},
        }
    }
    provisioned = supabase_service.provision_monitored_domain(
        user_id=user_id,
        domain_name=domain_name,
        quota_limit=3,
        audit_result=audit_payload
    )

    assert provisioned["domain_name"] == domain_name
    assert provisioned["is_active"] is True
    assert provisioned["health_score"] == 94
    # Confirms no scheduler lease is held
    assert provisioned.get("audit_lease_owner") is None

    # 2. Manual re-audit update
    re_audit_payload = {
        "health_score": 99,
        "summary": {
            "spf": {"status": "optimal"},
            "dkim": {"status": "optimal"},
            "dmarc": {"status": "optimal"},
            "mx": {"status": "optimal"},
            "bimi": {"status": "optimal"},
        }
    }
    updated = supabase_service.create_or_update_domain(
        user_id=user_id,
        domain_name=domain_name,
        audit_result=re_audit_payload
    )

    assert updated["health_score"] == 99
    assert updated["domain_name"] == domain_name


@pytest.mark.asyncio
async def test_background_auditor_empty_queue_reports_cycle_status():
    """
    P2 Regression Test:
    A valid empty claim result explicitly reports cycle_status='empty_queue',
    success=True, audited_count=0, consecutive_claim_failures=0.
    """
    from unittest.mock import patch
    from app.services.scheduler.background_auditor import BackgroundAuditor

    auditor = BackgroundAuditor()
    with patch.object(supabase_service, "claim_due_domain_audits", return_value=[]):
        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is True
        assert metrics["cycle_status"] == "empty_queue"
        assert metrics["audited_count"] == 0
        assert auditor.last_cycle_status == "empty_queue"
        assert auditor.consecutive_claim_failures == 0
        assert auditor.last_error is None


@pytest.mark.asyncio
async def test_background_auditor_db_error_reports_failure_status():
    """
    P2 Regression Test:
    When claim_due_domain_audits raises DatabaseUnavailableError, BackgroundAuditor
    reports success=False, cycle_status='db_error', and executes ZERO side effects.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from app.services.supabase_client import DatabaseUnavailableError

    auditor = BackgroundAuditor()
    with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("Database client is not connected in production")) as mock_claim, \
         patch.object(auditor.diagnostic_engine, "audit_domain", new_callable=AsyncMock) as mock_dns, \
         patch.object(supabase_service, "create_or_update_domain") as mock_upsert, \
         patch.object(supabase_service, "save_audit_log") as mock_log, \
         patch.object(alert_dispatcher, "evaluate_and_dispatch", new_callable=AsyncMock) as mock_alert, \
         patch.object(supabase_service, "complete_domain_audit") as mock_complete:

        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is False
        assert metrics["cycle_status"] == "db_error"
        assert "Database client is not connected" in metrics["error"]
        assert metrics["audited_count"] == 0
        assert auditor.consecutive_claim_failures == 1
        assert auditor.last_cycle_status == "db_error"

        # Zero side effects verified
        mock_claim.assert_called_once()
        mock_dns.assert_not_called()
        mock_upsert.assert_not_called()
        mock_log.assert_not_called()
        mock_alert.assert_not_called()
        mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_background_auditor_invalid_rpc_response_reports_failure_status():
    """
    P2 Regression Test:
    When claim_due_domain_audits raises InvalidRPCResponseError, BackgroundAuditor
    reports success=False, cycle_status='invalid_rpc_response', and zero work.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from app.services.supabase_client import InvalidRPCResponseError

    auditor = BackgroundAuditor()
    with patch.object(supabase_service, "claim_due_domain_audits", side_effect=InvalidRPCResponseError("returned invalid response shape (NoneType)")) as mock_claim, \
         patch.object(auditor.diagnostic_engine, "audit_domain", new_callable=AsyncMock) as mock_dns:

        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is False
        assert metrics["cycle_status"] == "invalid_rpc_response"
        assert metrics["audited_count"] == 0
        assert auditor.consecutive_claim_failures == 1
        assert auditor.last_cycle_status == "invalid_rpc_response"
        mock_dns.assert_not_called()


@pytest.mark.asyncio
async def test_background_auditor_rpc_error_reports_failure_status():
    """
    P2 Regression Test:
    When claim_due_domain_audits raises generic RuntimeError or network timeout,
    BackgroundAuditor reports success=False, cycle_status='rpc_error'.
    """
    from unittest.mock import patch
    from app.services.scheduler.background_auditor import BackgroundAuditor

    auditor = BackgroundAuditor()
    with patch.object(supabase_service, "claim_due_domain_audits", side_effect=RuntimeError("connection reset by peer")):
        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is False
        assert metrics["cycle_status"] == "rpc_error"
        assert "connection reset" in metrics["error"]
        assert auditor.consecutive_claim_failures == 1
        assert auditor.last_cycle_status == "rpc_error"


@pytest.mark.asyncio
async def test_background_auditor_consecutive_failures_telemetry_and_reset():
    """
    P2 Regression Test:
    consecutive_claim_failures increments across multiple failing cycles
    and resets to 0 upon a valid empty queue cycle or successful audit cycle.
    """
    from unittest.mock import patch
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from app.services.supabase_client import DatabaseUnavailableError

    auditor = BackgroundAuditor()

    # Cycle 1: fails
    with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("error 1")):
        res1 = await auditor.run_audit_cycle()
        assert res1["success"] is False
        assert auditor.consecutive_claim_failures == 1

    # Cycle 2: fails
    with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("error 2")):
        res2 = await auditor.run_audit_cycle()
        assert res2["success"] is False
        assert auditor.consecutive_claim_failures == 2

    # Cycle 3: recovers with valid empty queue
    with patch.object(supabase_service, "claim_due_domain_audits", return_value=[]):
        res3 = await auditor.run_audit_cycle()
        assert res3["success"] is True
        assert res3["cycle_status"] == "empty_queue"
        assert auditor.consecutive_claim_failures == 0
        assert auditor.last_error is None


@pytest.mark.asyncio
async def test_background_auditor_ops_alert_on_consecutive_failure_threshold():
    """
    P2 Regression Test:
    OpsAlertService.dispatch_incident is called only when consecutive_claim_failures
    reaches alert_failure_threshold (default: 3), and is never called for empty queue.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from app.services.supabase_client import DatabaseUnavailableError
    from app.services.alerting.ops_alert_service import ops_alert_service

    auditor = BackgroundAuditor()
    auditor.alert_failure_threshold = 3

    with patch.object(ops_alert_service, "dispatch_incident", new_callable=AsyncMock) as mock_dispatch:
        # Failure 1: below threshold, no alert
        with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("fail 1")):
            await auditor.run_audit_cycle()
            mock_dispatch.assert_not_called()

        # Failure 2: below threshold, no alert
        with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("fail 2")):
            await auditor.run_audit_cycle()
            mock_dispatch.assert_not_called()

        # Failure 3: reaches threshold -> dispatches incident
        with patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("fail 3")):
            await auditor.run_audit_cycle()
            assert mock_dispatch.call_count == 1
            incident = mock_dispatch.call_args[0][0]
            assert incident.alert_id == "ALERT-SCHEDULER-CLAIM-FAIL"
            assert incident.severity == "P1"
            assert "fail 3" in incident.summary

        # Healthy empty queue: resets failures and does NOT alert
        with patch.object(supabase_service, "claim_due_domain_audits", return_value=[]):
            await auditor.run_audit_cycle()
            # Call count remains 1
            assert mock_dispatch.call_count == 1
            assert auditor.consecutive_claim_failures == 0


@pytest.mark.asyncio
async def test_background_auditor_ops_alert_failure_does_not_mask_claim_failure():
    """
    P2 Regression Test:
    If OpsAlertService.dispatch_incident raises an exception, BackgroundAuditor
    still records the failure and returns the structured failure dictionary safely.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.scheduler.background_auditor import BackgroundAuditor
    from app.services.supabase_client import DatabaseUnavailableError
    from app.services.alerting.ops_alert_service import ops_alert_service

    auditor = BackgroundAuditor()
    auditor.alert_failure_threshold = 1

    with patch.object(ops_alert_service, "dispatch_incident", new_callable=AsyncMock, side_effect=Exception("Webhook network timeout")), \
         patch.object(supabase_service, "claim_due_domain_audits", side_effect=DatabaseUnavailableError("DB failure")):

        metrics = await auditor.run_audit_cycle()

        assert metrics["success"] is False
        assert metrics["cycle_status"] == "db_error"
        assert "DB failure" in metrics["error"]
        assert auditor.consecutive_claim_failures == 1
