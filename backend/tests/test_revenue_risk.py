"""
InboundCheck - Shopify Readiness & Revenue-at-Risk Unit Tests
============================================================
Tests:
1. DeliverabilityReadinessService 6 core checks evaluation.
2. RevenueRiskService Expected Risk calculation formula and versioned confidence bands.
3. API Endpoints:
   - POST /api/v1/shopify/deliverability-readiness
   - GET /api/v1/analytics/revenue-at-risk
   - POST /api/v1/analytics/revenue-at-risk
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.shopify.deliverability_readiness_service import deliverability_readiness_service
from app.services.analytics.revenue_risk_service import revenue_risk_service
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_deliverability_readiness_service_checks():
    """Verify evaluation of all 6 core deliverability checks."""
    # 1. Evaluate clean apex domain
    res = await deliverability_readiness_service.evaluate_readiness(
        domain="shopify.com",
        user_id="test-user-1"
    )
    assert res.domain == "shopify.com"
    assert 0 <= res.readiness_score <= 100
    assert len(res.checks) == 6
    check_ids = [c.check_id for c in res.checks]
    assert "custom_sending_domain" in check_ids
    assert "shopify_dkim" in check_ids
    assert "spf_alignment" in check_ids
    assert "dmarc_policy" in check_ids
    assert "spf_conflict" in check_ids
    assert "shared_pool_exposure" in check_ids

    # 2. Evaluate unbranded myshopify domain (must fail custom_sending_domain)
    res_myshopify = await deliverability_readiness_service.evaluate_readiness(
        domain="mystore.myshopify.com",
        user_id="test-user-1"
    )
    custom_check = next(c for c in res_myshopify.checks if c.check_id == "custom_sending_domain")
    assert custom_check.status == "fail"
    assert res_myshopify.can_activate_zero_spam is False


def test_revenue_risk_formula_and_confidence_bands():
    """Verify Expected Risk formula and high/medium/low confidence bands."""
    test_user = "test-user-risk-1"

    # High order volume (>= 1000 orders)
    res_high = revenue_risk_service.calculate_and_record_risk(
        user_id=test_user,
        domain="luxurystore.com",
        order_count=2000,
        average_order_value_cents=10000,  # $100.00
        customer_impact_factor=1.0
    )
    # Monthly GMV = 2000 * 10000 = 20,000,000 cents ($200,000)
    assert res_high.monthly_gmv_cents == 20000000
    # Expected Risk = GMV * Impairment * Impact
    expected_calc = int(res_high.monthly_gmv_cents * res_high.impairment_probability * res_high.customer_impact_factor)
    assert abs(res_high.expected_risk_cents - expected_calc) <= 1
    assert res_high.band_details.lower_bound_cents <= res_high.expected_risk_cents <= res_high.band_details.upper_bound_cents

    # Medium order volume (250-999 orders)
    res_med = revenue_risk_service.calculate_and_record_risk(
        user_id=test_user,
        domain="boutique.com",
        order_count=500,
        average_order_value_cents=6500,  # $65.00
        customer_impact_factor=1.2
    )
    assert res_med.confidence_band == "medium"
    assert res_med.band_details.margin_error_pct == 0.18

    # Low order volume (< 250 orders)
    res_low = revenue_risk_service.calculate_and_record_risk(
        user_id=test_user,
        domain="newstore.com",
        order_count=50,
        average_order_value_cents=5000,  # $50.00
        customer_impact_factor=1.0
    )
    assert res_low.confidence_band == "low"
    assert res_low.band_details.margin_error_pct == 0.32


@pytest.mark.asyncio
async def test_shopify_readiness_and_revenue_risk_endpoints():
    """Verify HTTP API contracts for deliverability-readiness and revenue-at-risk."""
    transport = ASGITransport(app=app)
    headers = auth_headers("test-user-api-1")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        # 1. POST /api/v1/shopify/deliverability-readiness
        readiness_res = await ac.post("/api/v1/shopify/deliverability-readiness", json={
            "domain": "shopify.com"
        })
        assert readiness_res.status_code == 200
        data = readiness_res.json()
        assert data["domain"] == "shopify.com"
        assert "readiness_score" in data
        assert len(data["checks"]) == 6

        # 2. GET /api/v1/analytics/revenue-at-risk
        risk_get_res = await ac.get("/api/v1/analytics/revenue-at-risk?domain=shopify.com&order_count=1000&aov_cents=8000")
        assert risk_get_res.status_code == 200
        risk_data = risk_get_res.json()
        assert "expected_risk_cents" in risk_data
        assert "confidence_band" in risk_data
        assert "band_details" in risk_data
        assert "breakdown" in risk_data

        # 3. POST /api/v1/analytics/revenue-at-risk
        risk_post_res = await ac.post("/api/v1/analytics/revenue-at-risk", json={
            "domain": "shopify.com",
            "order_count": 1500,
            "average_order_value_cents": 12000,
            "customer_impact_factor": 1.1
        })
        assert risk_post_res.status_code == 200
        post_data = risk_post_res.json()
        assert post_data["monthly_gmv_cents"] == 1500 * 12000
        assert post_data["customer_impact_factor"] == 1.1
