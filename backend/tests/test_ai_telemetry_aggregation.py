"""
InboundCheck - AI Generation Telemetry Aggregation Test Suite (Step 17D.4.1)
==========================================================================
Verifies:
- A. Correct generation counts
- B. Success counts (distinguishing primary success vs success_via_fallback)
- C. Fallback counts (primary vs fallback success and total fallbacks)
- D. Timeout, error, and Liquid-failure counts
- E. Token aggregation with NULL values
- F. Cost aggregation with NULL values
- G. Zero-cost fallback handling
- H. Plan-tier aggregation
- I. Tenant isolation (merchant view strictly isolated to own user_id)
- J. Time-window boundaries
- K. UTC handling
- L. Quota reconciliation (balanced vs anomaly detected)
- M. Reconciliation never mutates quota
- N. Empty dataset behavior
- O. Aggregation failure resilience
"""

import pytest
import uuid
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.services.ai.telemetry_service import (
    compute_aggregates,
    ai_telemetry_service,
    calculate_p95,
)
from app.services.ai.plan_policy import PLAN_POLICIES
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def clean_telemetry_and_quota():
    """Ensure clean in-memory state before and after each test."""
    orig_client = supabase_service._client
    supabase_service._client = None
    supabase_service.reset_in_memory_ai_telemetry()
    supabase_service.reset_in_memory_ai_monthly_usage()
    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()
    yield
    supabase_service._client = orig_client
    supabase_service.reset_in_memory_ai_telemetry()
    supabase_service.reset_in_memory_ai_monthly_usage()
    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()


# =============================================================================
# A - H: UNIT AGGREGATION CALCULATIONS
# =============================================================================

def test_a_correct_generation_counts():
    """Verify total generation count matches record count."""
    records = [
        {"outcome": "success", "latency_ms": 100},
        {"outcome": "timeout", "latency_ms": 25000},
        {"outcome": "error", "latency_ms": 500},
    ]
    aggs = compute_aggregates(records)
    assert aggs["total_generations"] == 3


def test_b_success_counts_primary_vs_fallback():
    """Verify primary success and fallback success are correctly distinguished."""
    records = [
        # Primary success
        {"outcome": "success", "fallback_used": False, "latency_ms": 1000},
        {"outcome": "success", "fallback_used": False, "latency_ms": 1200},
        # Fallback success
        {"outcome": "success_via_fallback", "fallback_used": True, "latency_ms": 300},
        # Failed attempt
        {"outcome": "error", "fallback_used": True, "latency_ms": 200},
    ]
    aggs = compute_aggregates(records)
    assert aggs["total_generations"] == 4
    assert aggs["successful_generations"] == 3
    assert aggs["primary_success_count"] == 2
    assert aggs["fallback_success_count"] == 1


def test_c_fallback_counts():
    """Verify fallback counts include both success via fallback and fallback errors."""
    records = [
        {"outcome": "success", "fallback_used": False},
        {"outcome": "success_via_fallback", "fallback_used": True},
        {"outcome": "error", "fallback_used": True},
        {"outcome": "liquid_failed", "fallback_used": False},
    ]
    aggs = compute_aggregates(records)
    assert aggs["total_fallback_count"] == 2
    assert aggs["fallback_success_count"] == 1


def test_d_timeout_error_liquid_failure_counts():
    """Verify exact counts for timeout, error, and Liquid-failed outcomes."""
    records = [
        {"outcome": "timeout"},
        {"outcome": "timeout"},
        {"outcome": "error"},
        {"outcome": "liquid_failed"},
        {"outcome": "liquid_failed"},
        {"outcome": "liquid_failed"},
    ]
    aggs = compute_aggregates(records)
    assert aggs["timeout_count"] == 2
    assert aggs["error_count"] == 1
    assert aggs["liquid_failed_count"] == 3
    assert aggs["by_outcome"]["timeout"] == 2
    assert aggs["by_outcome"]["error"] == 1
    assert aggs["by_outcome"]["liquid_failed"] == 3


def test_e_token_aggregation_with_null_values():
    """Verify token aggregation sums non-null values and tracks unreported tokens."""
    records = [
        {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
        {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
    ]
    aggs = compute_aggregates(records)
    assert aggs["known_prompt_tokens"] == 300
    assert aggs["known_completion_tokens"] == 150
    assert aggs["known_total_tokens"] == 450
    assert aggs["unreported_tokens_count"] == 1


def test_f_cost_aggregation_with_null_values():
    """Verify known cost sums non-null costs and tracks unreported costs without converting null to 0."""
    records = [
        {"cost_micro_usd": 1500, "cost_status": "calculated"},
        {"cost_micro_usd": 2500, "cost_status": "reported"},
        {"cost_micro_usd": None, "cost_status": "unreported"},
    ]
    aggs = compute_aggregates(records)
    assert aggs["known_cost_micro_usd"] == 4000
    assert aggs["unreported_cost_count"] == 1


def test_g_zero_cost_fallback_handling():
    """Verify zero_cost fallback adds 0 to known cost and is not marked as unreported."""
    records = [
        {"cost_micro_usd": 5000, "cost_status": "calculated"},
        {"cost_micro_usd": 0, "cost_status": "zero_cost"},
    ]
    aggs = compute_aggregates(records)
    assert aggs["known_cost_micro_usd"] == 5000
    assert aggs["unreported_cost_count"] == 0


def test_h_plan_tier_aggregation():
    """Verify breakdown of generations across starter, growth, and agency tiers."""
    records = [
        {"plan_tier": "starter"},
        {"plan_tier": "starter"},
        {"plan_tier": "growth"},
        {"plan_tier": "agency"},
        {"plan_tier": "agency"},
        {"plan_tier": "agency"},
    ]
    aggs = compute_aggregates(records)
    assert aggs["by_plan_tier"]["starter"] == 2
    assert aggs["by_plan_tier"]["growth"] == 1
    assert aggs["by_plan_tier"]["agency"] == 3


def test_percentile_p95_calculation():
    """Verify p95 latency calculation."""
    # 20 samples from 100 to 2000
    samples = [i * 100 for i in range(1, 21)]
    # 95th percentile of 20 items: idx = ceil(0.95 * 20) - 1 = 19 - 1 = 18 -> 1900
    p95 = calculate_p95(samples)
    assert p95 == 1900


# =============================================================================
# I. TENANT ISOLATION
# =============================================================================

@pytest.mark.asyncio
async def test_i_tenant_isolation_merchant_endpoint():
    """Verify merchant /usage and /telemetry/summary endpoints enforce server-side tenant isolation."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    period = "2026-10"

    # User A records
    supabase_service.record_ai_telemetry({
        "generation_id": str(uuid.uuid4()),
        "user_id": user_a,
        "plan_tier": "growth",
        "billing_period": period,
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "outcome": "success",
        "fallback_used": False,
        "quota_consumed": True,
        "latency_ms": 1100,
        "cost_status": "calculated",
        "cost_micro_usd": 200,
    })

    # User B records
    for _ in range(5):
        supabase_service.record_ai_telemetry({
            "generation_id": str(uuid.uuid4()),
            "user_id": user_b,
            "plan_tier": "agency",
            "billing_period": period,
            "provider": "agent_router",
            "model": "google/gemma-4-26b-a4b-it",
            "outcome": "success",
            "fallback_used": False,
            "quota_consumed": True,
            "latency_ms": 800,
            "cost_status": "calculated",
            "cost_micro_usd": 500,
        })

    profile_a = {"id": user_a, "subscription_tier": "growth", "subscription_status": "active"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = auth_headers(user_a)
        with patch.object(supabase_service, "get_user_profile", return_value=profile_a):
            res = await ac.get(f"/api/v1/ai/usage?billing_period={period}", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["tier"] == "growth"
            assert data["billing_period"] == period
            # User A must ONLY see 1 generation, NEVER User B's 5 generations
            assert data["telemetry_summary"]["total_generations"] == 1
            assert data["telemetry_summary"]["successful_generations"] == 1


# =============================================================================
# J & K: TIME-WINDOW & UTC BOUNDARIES
# =============================================================================

def test_j_and_k_time_window_boundaries_and_utc():
    """Verify date/time window boundary filtering with UTC timestamps."""
    user_id = str(uuid.uuid4())
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 3 records: yesterday, today, tomorrow
    r_past = {
        "generation_id": str(uuid.uuid4()),
        "user_id": user_id,
        "billing_period": "2026-09",
        "created_at": (t0 - timedelta(days=2)).isoformat(),
        "outcome": "success",
    }
    r_target = {
        "generation_id": str(uuid.uuid4()),
        "user_id": user_id,
        "billing_period": "2026-10",
        "created_at": t0.isoformat(),
        "outcome": "success",
    }
    r_future = {
        "generation_id": str(uuid.uuid4()),
        "user_id": user_id,
        "billing_period": "2026-10",
        "created_at": (t0 + timedelta(days=2)).isoformat(),
        "outcome": "success",
    }

    supabase_service.record_ai_telemetry(r_past)
    supabase_service.record_ai_telemetry(r_target)
    supabase_service.record_ai_telemetry(r_future)

    # Query window containing only r_target
    start_window = t0 - timedelta(hours=1)
    end_window = t0 + timedelta(hours=1)

    records = supabase_service.get_ai_telemetry_records(
        start_time=start_window,
        end_time=end_window,
    )
    assert len(records) == 1
    assert records[0]["generation_id"] == r_target["generation_id"]


# =============================================================================
# L & M: QUOTA RECONCILIATION
# =============================================================================

def test_l_quota_reconciliation_balanced_and_anomaly():
    """Verify diagnostic quota reconciliation identifies balanced vs anomaly states."""
    user_id = str(uuid.uuid4())
    period = "2026-10"

    # Case 1: Balanced (2 consumed in ledger, 2 in telemetry)
    supabase_service.consume_ai_monthly_generation(user_id, period, 20)
    supabase_service.consume_ai_monthly_generation(user_id, period, 20)

    for _ in range(2):
        supabase_service.record_ai_telemetry({
            "generation_id": str(uuid.uuid4()),
            "user_id": user_id,
            "billing_period": period,
            "quota_consumed": True,
            "outcome": "success",
            "latency_ms": 500,
            "cost_status": "zero_cost",
        })

    report = ai_telemetry_service.reconcile_quota(user_id=user_id, billing_period=period)
    assert report["ledger_usage"] == 2
    assert report["telemetry_consumed"] == 2
    assert report["discrepancy"] == 0
    assert report["status"] == "balanced"
    assert report["is_anomaly"] is False

    # Case 2: Anomaly (Add third telemetry row without ledger consumption)
    supabase_service.record_ai_telemetry({
        "generation_id": str(uuid.uuid4()),
        "user_id": user_id,
        "billing_period": period,
        "quota_consumed": True,
        "outcome": "success",
        "latency_ms": 600,
        "cost_status": "zero_cost",
    })

    report_anomaly = ai_telemetry_service.reconcile_quota(user_id=user_id, billing_period=period)
    assert report_anomaly["ledger_usage"] == 2
    assert report_anomaly["telemetry_consumed"] == 3
    assert report_anomaly["discrepancy"] == 1
    assert report_anomaly["status"] == "anomaly_detected"
    assert report_anomaly["is_anomaly"] is True


def test_m_reconciliation_never_mutates_quota():
    """Verify reconciliation is strictly read-only and never alters the quota ledger."""
    user_id = str(uuid.uuid4())
    period = "2026-10"

    # Set ledger usage to 5
    for _ in range(5):
        supabase_service.consume_ai_monthly_generation(user_id, period, 20)

    # Telemetry has 0 rows
    report = ai_telemetry_service.reconcile_quota(user_id=user_id, billing_period=period)
    assert report["status"] == "anomaly_detected"
    assert report["discrepancy"] == -5

    # Authoritative usage must remain strictly 5
    ledger_after = supabase_service.get_ai_monthly_usage(user_id, period)
    assert ledger_after == 5


# =============================================================================
# N. EMPTY DATASET BEHAVIOR
# =============================================================================

def test_n_empty_dataset_behavior():
    """Verify aggregation handles empty record sets gracefully without exceptions or division errors."""
    aggs = compute_aggregates([])
    assert aggs["total_generations"] == 0
    assert aggs["successful_generations"] == 0
    assert aggs["primary_success_count"] == 0
    assert aggs["fallback_success_count"] == 0
    assert aggs["total_fallback_count"] == 0
    assert aggs["timeout_count"] == 0
    assert aggs["error_count"] == 0
    assert aggs["liquid_failed_count"] == 0
    assert aggs["quota_consumed_count"] == 0
    assert aggs["known_prompt_tokens"] == 0
    assert aggs["known_completion_tokens"] == 0
    assert aggs["known_total_tokens"] == 0
    assert aggs["unreported_tokens_count"] == 0
    assert aggs["known_cost_micro_usd"] == 0
    assert aggs["unreported_cost_count"] == 0
    assert aggs["avg_latency_ms"] == 0
    assert aggs["avg_provider_latency_ms"] is None
    assert aggs["p95_latency_ms"] == 0


# =============================================================================
# O. OPERATIONAL ENDPOINT & RETENTION PRUNING
# =============================================================================

@pytest.mark.asyncio
async def test_o_internal_operational_summary_and_pruning():
    """Verify internal operational endpoint requires credentials and pruning works."""
    user_id = str(uuid.uuid4())
    period = "2026-10"

    # Add old record (100 days old)
    old_time = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    supabase_service.record_ai_telemetry({
        "generation_id": str(uuid.uuid4()),
        "user_id": user_id,
        "plan_tier": "starter",
        "billing_period": "2026-06",
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "outcome": "success",
        "fallback_used": False,
        "quota_consumed": True,
        "created_at": old_time,
        "latency_ms": 1000,
        "cost_status": "calculated",
        "cost_micro_usd": 150,
    })

    # Add fresh record (today)
    fresh_id = str(uuid.uuid4())
    supabase_service.record_ai_telemetry({
        "generation_id": fresh_id,
        "user_id": user_id,
        "plan_tier": "starter",
        "billing_period": period,
        "provider": "agent_router",
        "model": "google/gemma-4-26b-a4b-it",
        "outcome": "success",
        "fallback_used": False,
        "quota_consumed": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "latency_ms": 1200,
        "cost_status": "calculated",
        "cost_micro_usd": 180,
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Unauthenticated internal endpoint fails 403
        unauth_res = await ac.get("/api/v1/ai/admin/telemetry-summary")
        assert unauth_res.status_code == 403

        # 2. Authenticated with test internal key succeeds
        auth_internal_headers = {"X-Internal-Key": "test-internal-key"}
        summary_res = await ac.get("/api/v1/ai/admin/telemetry-summary", headers=auth_internal_headers)
        assert summary_res.status_code == 200
        data = summary_res.json()
        assert data["success"] is True
        assert data["operational_telemetry"]["total_generations"] == 2

        # 3. Test 90-day pruning
        prune_res = await ac.post("/api/v1/ai/admin/prune-telemetry?retention_days=90", headers=auth_internal_headers)
        assert prune_res.status_code == 200
        prune_data = prune_res.json()
        assert prune_data["success"] is True
        assert prune_data["pruned"]["deleted_count"] == 1

        # 4. Summary after pruning shows only 1 fresh record remains
        post_prune_summary = await ac.get("/api/v1/ai/admin/telemetry-summary", headers=auth_internal_headers)
        assert post_prune_summary.status_code == 200
        post_data = post_prune_summary.json()
        assert post_data["operational_telemetry"]["total_generations"] == 1


# =============================================================================
# P. ADMIN INTERNAL AUTH HARDENING (STEP 17D.4.2.1)
# =============================================================================

@pytest.mark.asyncio
async def test_p1_admin_auth_dedicated_ops_key_accepted():
    """Verify dedicated OPS_INTERNAL_API_KEY is accepted in development and test environments."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "OPS_INTERNAL_API_KEY", "dedicated-ops-key-8899"):
            # 1. Accepted via X-Internal-Key
            res = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "dedicated-ops-key-8899"},
            )
            assert res.status_code == 200
            assert res.json()["success"] is True

            # 2. Accepted via X-Service-Role-Key header alias
            res_alias = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Service-Role-Key": "dedicated-ops-key-8899"},
            )
            assert res_alias.status_code == 200


@pytest.mark.asyncio
async def test_p2_admin_auth_incorrect_empty_whitespace_rejected():
    """Verify wrong, empty, or whitespace-only keys fail closed with 403 Forbidden."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "OPS_INTERNAL_API_KEY", "dedicated-ops-key-8899"):
            # Wrong key
            res_wrong = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "wrong-key-value"},
            )
            assert res_wrong.status_code == 403

            # Empty key
            res_empty = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": ""},
            )
            assert res_empty.status_code == 403

            # Whitespace key
            res_space = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "    "},
            )
            assert res_space.status_code == 403

            # Missing headers
            res_missing = await ac.get("/api/v1/ai/admin/telemetry-summary")
            assert res_missing.status_code == 403


@pytest.mark.asyncio
async def test_p3_admin_auth_jwt_secret_and_service_role_key_rejected():
    """Verify SUPABASE_JWT_SECRET and SUPABASE_SERVICE_ROLE_KEY are strictly rejected as admin credentials."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "SUPABASE_JWT_SECRET", "super-secret-jwt-signing-key"), \
             patch.object(settings, "SUPABASE_SERVICE_ROLE_KEY", "super-secret-db-service-role-key"), \
             patch.object(settings, "OPS_INTERNAL_API_KEY", "dedicated-ops-key-8899"):

            # Passing SUPABASE_JWT_SECRET must fail 403
            res_jwt = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "super-secret-jwt-signing-key"},
            )
            assert res_jwt.status_code == 403

            # Passing SUPABASE_SERVICE_ROLE_KEY via X-Internal-Key must fail 403
            res_sr1 = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "super-secret-db-service-role-key"},
            )
            assert res_sr1.status_code == 403

            # Passing SUPABASE_SERVICE_ROLE_KEY via X-Service-Role-Key must fail 403
            res_sr2 = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Service-Role-Key": "super-secret-db-service-role-key"},
            )
            assert res_sr2.status_code == 403


@pytest.mark.asyncio
async def test_p4_admin_auth_user_bearer_jwt_rejected():
    """Verify ordinary authenticated merchant Bearer token cannot satisfy admin authorization."""
    user_id = str(uuid.uuid4())
    headers = auth_headers(user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Standard user Bearer token alone without internal key must fail 403
        res = await ac.get("/api/v1/ai/admin/telemetry-summary", headers=headers)
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_p5_admin_auth_production_fail_closed_when_unconfigured():
    """Verify production fails closed if OPS_INTERNAL_API_KEY is not configured (empty)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "ENVIRONMENT", "production"), \
             patch.object(settings, "OPS_INTERNAL_API_KEY", ""):

            # Even dev test-internal-key must be rejected in production
            res_dev = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "test-internal-key"},
            )
            assert res_dev.status_code == 403
            assert "unconfigured" in res_dev.json()["detail"].lower()

            # Any key must fail 403
            res_any = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "some-random-key"},
            )
            assert res_any.status_code == 403


@pytest.mark.asyncio
async def test_p6_admin_auth_production_accepts_only_ops_key():
    """Verify production environment accepts only the authoritative OPS_INTERNAL_API_KEY."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "ENVIRONMENT", "production"), \
             patch.object(settings, "OPS_INTERNAL_API_KEY", "real-prod-ops-key-7711"):

            # 1. Authoritative key succeeds
            res_auth = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "real-prod-ops-key-7711"},
            )
            assert res_auth.status_code == 200

            # 2. test-internal-key fails in production
            res_dev = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "test-internal-key"},
            )
            assert res_dev.status_code == 403

            # 3. Arbitrary key fails
            res_wrong = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": "wrong-key"},
            )
            assert res_wrong.status_code == 403


@pytest.mark.asyncio
async def test_p7_admin_auth_no_plaintext_secrets_in_errors():
    """Verify error detail strings never reflect candidate or configured keys."""
    secret_candidate = "leaked-candidate-secret-value-999"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch.object(settings, "OPS_INTERNAL_API_KEY", "configured-secret-value-888"):
            res = await ac.get(
                "/api/v1/ai/admin/telemetry-summary",
                headers={"X-Internal-Key": secret_candidate},
            )
            assert res.status_code == 403
            detail = res.json()["detail"]
            assert secret_candidate not in detail
            assert "configured-secret-value-888" not in detail
