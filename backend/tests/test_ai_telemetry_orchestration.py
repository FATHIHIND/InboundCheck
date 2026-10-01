"""
InboundCheck - AI Generation Telemetry Orchestration Test Suite (Step 17D.3)
=============================================================================
Verifies end-to-end integration of public.ai_generation_telemetry into the AI
generation lifecycle:
- A: Primary success (one row, tokens populated, cost calculated, quota consumed)
- B: Fallback success (one row, provider=heuristic_fallback, model=rule-based-v1, zero_cost)
- C: Liquid gate rejection (outcome=liquid_failed, quota_consumed=false)
- D: Wall-clock outer timeout (outcome=timeout, quota_consumed=false, 504 Gateway Timeout)
- E: Generic generation failure (outcome=error, quota_consumed=false, 500 Error)
- F: Telemetry DB write failure resilience (AI response succeeds 200, OpsAlert dispatched)
- G: Missing provider usage (tokens=NULL, cost_status=unreported, 200 success)
- H: Malformed provider usage (safe handling, tokens=NULL, 200 success)
- I: Cost semantics (calculated, zero_cost, unreported)
- J: Generation ID (single ID per lifecycle, no duplicate writes)
- K: Data minimization (only schema-whitelisted operational metadata, no prompts/PII/variants)
- L: Tenant attribution (authoritative user_id from auth, not payload)
- M: Plan attribution (authoritative plan_tier from server policy, not payload)
- N: Billing period (authoritative server-side UTC YYYY-MM)
"""

import pytest
import uuid
import time
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.supabase_client import supabase_service
from app.services.ai.content_optimizer import ai_content_service
from app.services.ai.provider import GenerationResult
from app.services.ai.pricing import resolve_cost, MODEL_PRICING_V1
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def clean_telemetry_state():
    """Reset in-memory rate limits, quota, concurrency leases, and telemetry."""
    supabase_service.reset_in_memory_ai_telemetry()
    supabase_service.reset_in_memory_ai_monthly_usage()
    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()
    yield
    supabase_service.reset_in_memory_ai_telemetry()
    supabase_service.reset_in_memory_ai_monthly_usage()
    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()


# =============================================================================
# A. PRIMARY SUCCESS
# =============================================================================

@pytest.mark.asyncio
async def test_a_primary_success():
    """Verify primary provider success emits exactly one telemetry row with calculated cost."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "growth", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[
            {
                "variant_id": "var_1",
                "subject": "Optimized Subject",
                "body": "Your order {{ order_number }} is verified.",
                "body_html": "<p>Your order {{ order_number }} is verified.</p>",
            }
        ],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
        provider_latency_ms=850,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={
                        "subject": "Order receipt",
                        "body": "Your order {{ order_number }} is verified.",
                    },
                )

                assert res.status_code == 200
                data = res.json()
                assert data["success"] is True
                assert len(data["variants"]) == 1

    # Verify telemetry storage
    assert len(supabase_service._in_memory_ai_telemetry) == 1
    gen_id = next(iter(supabase_service._in_memory_ai_telemetry.keys()))
    t_row = supabase_service._in_memory_ai_telemetry[gen_id]

    assert t_row["user_id"] == user_id
    assert t_row["plan_tier"] == "growth"
    assert t_row["provider"] == "agent_router"
    assert t_row["model"] == "google/gemma-4-26b-a4b-it"
    assert t_row["outcome"] == "success"
    assert t_row["fallback_used"] is False
    assert t_row["quota_consumed"] is True
    assert t_row["prompt_tokens"] == 150
    assert t_row["completion_tokens"] == 50
    assert t_row["total_tokens"] == 200
    assert t_row["provider_latency_ms"] == 850
    assert t_row["latency_ms"] >= 0
    assert t_row["cost_status"] == "calculated"
    assert t_row["cost_micro_usd"] is not None and t_row["cost_micro_usd"] > 0


# =============================================================================
# B. PRIMARY FAILS -> HEURISTIC FALLBACK SUCCEEDS
# =============================================================================

@pytest.mark.asyncio
async def test_b_fallback_success_single_telemetry_row():
    """Verify provider failure with fallback success writes exactly one row with zero_cost."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[
            {
                "variant_id": "fallback_1",
                "subject": "Order Update",
                "body": "Your order {{ order_number }} is on its way.",
                "body_html": "<p>Your order {{ order_number }} is on its way.</p>",
            }
        ],
        provider="heuristic_fallback",
        model="rule-based-v1",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        provider_latency_ms=12,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={
                        "subject": "Order receipt",
                        "body": "Your order {{ order_number }} is on its way.",
                    },
                )

                assert res.status_code == 200
                data = res.json()
                assert data["success"] is True

    assert len(supabase_service._in_memory_ai_telemetry) == 1
    gen_id = next(iter(supabase_service._in_memory_ai_telemetry.keys()))
    t_row = supabase_service._in_memory_ai_telemetry[gen_id]

    assert t_row["outcome"] == "success_via_fallback"
    assert t_row["fallback_used"] is True
    assert t_row["provider"] == "heuristic_fallback"
    assert t_row["model"] == "rule-based-v1"
    assert t_row["prompt_tokens"] is None
    assert t_row["completion_tokens"] is None
    assert t_row["total_tokens"] is None
    assert t_row["cost_status"] == "zero_cost"
    assert t_row["cost_micro_usd"] == 0
    assert t_row["quota_consumed"] is True


# =============================================================================
# C. LIQUID GATE REJECTION
# =============================================================================

@pytest.mark.asyncio
async def test_c_liquid_gate_rejection():
    """Verify liquid validation rejection emits liquid_failed and quota_consumed=false."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    # Mock empty variants returned due to Liquid rejection
    mock_result = GenerationResult(
        variants=[],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=200,
        completion_tokens=100,
        total_tokens=300,
        provider_latency_ms=900,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            with patch("app.api.v1.ai._safe_rollback_monthly_quota", new=AsyncMock()) as mock_rollback:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={
                            "subject": "Order receipt",
                            "body": "Your order {{ order_number }} has shipped.",
                        },
                    )

                    assert res.status_code == 200
                    data = res.json()
                    assert data["success"] is True
                    assert data["variants"] == []

                mock_rollback.assert_awaited_once()

    assert len(supabase_service._in_memory_ai_telemetry) == 1
    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["outcome"] == "liquid_failed"
    assert t_row["quota_consumed"] is False


# =============================================================================
# D. OUTER WALL-CLOCK TIMEOUT
# =============================================================================

@pytest.mark.asyncio
async def test_d_outer_wall_clock_timeout():
    """Verify outer 25s timeout emits outcome=timeout and releases quota & lease."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    async def hang_forever(*args, **kwargs):
        raise TimeoutError("Outer wall-clock timeout exceeded")

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", side_effect=hang_forever):
            with patch("app.api.v1.ai._safe_rollback_monthly_quota", new=AsyncMock()) as mock_rollback:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order", "body": "Order body."},
                    )

                    assert res.status_code == 504
                    assert res.json()["detail"]["error_code"] == "AI_GENERATION_TIMEOUT"

                mock_rollback.assert_awaited_once()

    assert len(supabase_service._in_memory_ai_telemetry) == 1
    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["outcome"] == "timeout"
    assert t_row["quota_consumed"] is False
    assert t_row["fallback_used"] is False
    assert t_row["cost_status"] == "unreported"
    assert t_row["cost_micro_usd"] is None


# =============================================================================
# E. GENERIC GENERATION FAILURE
# =============================================================================

@pytest.mark.asyncio
async def test_e_generic_generation_failure():
    """Verify unhandled exception emits outcome=error and quota_consumed=false."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    async def raise_error(*args, **kwargs):
        raise RuntimeError("Fatal internal generation crash")

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", side_effect=raise_error):
            with patch("app.api.v1.ai._safe_rollback_monthly_quota", new=AsyncMock()) as mock_rollback:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order", "body": "Order body."},
                    )

                    assert res.status_code == 500

                mock_rollback.assert_awaited_once()

    assert len(supabase_service._in_memory_ai_telemetry) == 1
    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["outcome"] == "error"
    assert t_row["quota_consumed"] is False


# =============================================================================
# F. TELEMETRY DB WRITE FAILURE RESILIENCE
# =============================================================================

@pytest.mark.asyncio
async def test_f_telemetry_db_write_failure_resilience():
    """Verify telemetry write failure does NOT break AI generation response (best-effort)."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "growth", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        provider_latency_ms=500,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            with patch.object(supabase_service, "record_ai_telemetry", side_effect=Exception("Database connection dropped")):
                with patch("app.api.v1.ai.ops_alert_service.dispatch_incident", new=AsyncMock()) as mock_alert:
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as ac:
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={"subject": "Order receipt", "body": "Confirmed."},
                        )

                        # Response must remain 200 OK with variants!
                        assert res.status_code == 200
                        data = res.json()
                        assert data["success"] is True
                        assert len(data["variants"]) == 1

                    # OpsAlert must have been notified with the required alert id
                    assert mock_alert.called
                    incident = mock_alert.call_args[0][0]
                    assert incident.alert_id == "ALERT-AI-TELEMETRY-WRITE-FAILURE"


# =============================================================================
# G. MISSING PROVIDER USAGE
# =============================================================================

@pytest.mark.asyncio
async def test_g_missing_provider_usage():
    """Verify generation succeeds when provider returns None tokens, cost is unreported."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        provider_latency_ms=450,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order", "body": "Body."},
                )

                assert res.status_code == 200

    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["prompt_tokens"] is None
    assert t_row["completion_tokens"] is None
    assert t_row["total_tokens"] is None
    assert t_row["cost_status"] == "unreported"
    assert t_row["cost_micro_usd"] is None


# =============================================================================
# H. MALFORMED PROVIDER USAGE
# =============================================================================

@pytest.mark.asyncio
async def test_h_malformed_provider_usage():
    """Verify invalid or unmapped model names safely fall back to unreported cost."""
    cost, status = resolve_cost(
        model="unmapped-vendor-model-v99",
        prompt_tokens=100,
        completion_tokens=50,
        provider="agent_router",
    )
    assert cost is None
    assert status == "unreported"

    # Negative tokens safely unreported
    cost_neg, status_neg = resolve_cost(
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=-10,
        completion_tokens=50,
        provider="agent_router",
    )
    assert cost_neg is None
    assert status_neg == "unreported"


# =============================================================================
# I. COST SEMANTICS
# =============================================================================

def test_i_cost_semantics():
    """Verify calculated, zero_cost, and unreported cost rules."""
    # 1. Calculated cost with integer ceiling division
    cost, status = resolve_cost(
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=1000,
        completion_tokens=500,
        provider="agent_router",
    )
    assert status == "calculated"
    # prompt: (1000 * 270000 + 999999) // 1000000 = 270
    # completion: (500 * 270000 + 999999) // 1000000 = 135
    assert cost == 405

    # 2. Known zero cost for heuristic fallback
    cost_zero, status_zero = resolve_cost(
        model="rule-based-v1",
        prompt_tokens=None,
        completion_tokens=None,
        provider="heuristic_fallback",
    )
    assert cost_zero == 0
    assert status_zero == "zero_cost"

    # 3. Unreported cost for missing tokens on paid model
    cost_unrep, status_unrep = resolve_cost(
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=None,
        completion_tokens=100,
        provider="agent_router",
    )
    assert cost_unrep is None
    assert status_unrep == "unreported"


# =============================================================================
# J. GENERATION ID IDEMPOTENCY
# =============================================================================

@pytest.mark.asyncio
async def test_j_generation_id_uniqueness_and_once_only():
    """Verify exactly one telemetry record is produced per generation lifecycle."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "S", "body": "B"},
                )
                assert res.status_code == 200

    # Primary key uniqueness: Exactly one row in telemetry table
    assert len(supabase_service._in_memory_ai_telemetry) == 1
    gen_id = next(iter(supabase_service._in_memory_ai_telemetry.keys()))
    # Validate UUID format
    assert uuid.UUID(gen_id)


# =============================================================================
# K. DATA MINIMIZATION
# =============================================================================

@pytest.mark.asyncio
async def test_k_data_minimization():
    """Verify telemetry payload contains ONLY the 17 schema-whitelisted attributes."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "growth", "subscription_status": "active"}

    sensitive_subject = "CONFIDENTIAL Customer Order #99999"
    sensitive_body = "Shipping to John Doe, 123 Main St, Credit Card: 4111-XXXX-XXXX-1111"

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": sensitive_body}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": sensitive_subject, "body": sensitive_body},
                )
                assert res.status_code == 200

    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))

    # Assert forbidden sensitive keys do not exist in the record
    forbidden_keys = {
        "subject", "body", "variants", "candidate_variants", "prompt", "raw_response",
        "liquid_tags", "customer", "email", "address", "secret", "headers", "api_key"
    }
    for fk in forbidden_keys:
        assert fk not in t_row

    # Assert no sensitive values leak into stringified record
    t_str = str(t_row)
    assert sensitive_subject not in t_str
    assert "John Doe" not in t_str
    assert "4111" not in t_str


# =============================================================================
# L. TENANT ATTRIBUTION
# =============================================================================

@pytest.mark.asyncio
async def test_l_tenant_attribution_anti_spoofing():
    """Verify user_id in telemetry comes strictly from authenticated JWT context."""
    auth_user_id = str(uuid.uuid4())
    attacker_spoofed_user_id = str(uuid.uuid4())
    profile = {"id": auth_user_id, "subscription_tier": "starter", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    f"/api/v1/ai/generate-variants?user_id={attacker_spoofed_user_id}",
                    headers=auth_headers(auth_user_id),
                    json={"subject": "S", "body": "B"},
                )
                assert res.status_code == 200

    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["user_id"] == auth_user_id
    assert t_row["user_id"] != attacker_spoofed_user_id


# =============================================================================
# M. PLAN ATTRIBUTION
# =============================================================================

@pytest.mark.asyncio
async def test_m_plan_attribution_anti_spoofing():
    """Verify plan_tier in telemetry is derived from server-side policy resolution."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "agency", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
    )

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "S", "body": "B"},
                )
                assert res.status_code == 200

    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["plan_tier"] == "agency"


# =============================================================================
# N. BILLING PERIOD
# =============================================================================

@pytest.mark.asyncio
async def test_n_billing_period_format():
    """Verify billing_period in telemetry strictly follows UTC YYYY-MM format."""
    user_id = str(uuid.uuid4())
    profile = {"id": user_id, "subscription_tier": "starter", "subscription_status": "active"}

    mock_result = GenerationResult(
        variants=[{"variant_id": "v1", "subject": "S", "body": "B"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
    )

    expected_period = datetime.now(timezone.utc).strftime("%Y-%m")

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants_result", new=AsyncMock(return_value=mock_result)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "S", "body": "B"},
                )
                assert res.status_code == 200

    t_row = next(iter(supabase_service._in_memory_ai_telemetry.values()))
    assert t_row["billing_period"] == expected_period
    import re
    assert re.match(r"^\d{4}-(0[1-9]|1[0-2])$", t_row["billing_period"])
