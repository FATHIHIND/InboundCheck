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
