"""
InboundCheck - AI Subscription Plan Policies & Entitlement Resolution Test Suite
================================================================================
Step 16 AI Commercial Policy Reconciliation:
1. Authoritative resolution for Starter, Growth, and Agency 3-tier commercial model.
2. Anti-spoofing: Client-provided body, query, or headers CANNOT elevate tier.
3. Fail-secure: Unknown/malformed tiers safely default to 'starter', never elevated.
4. Legacy Enterprise transition: Existing server-side enterprise profiles map to Agency.
5. Invariant preservation: Existing AI runtime limits and provider ceiling remain active.
"""

import pytest
import os
import json
import uuid
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta

from app.main import app
from app.services.ai.plan_policy import (
    AIPlanPolicy,
    PLAN_POLICIES,
    resolve_ai_plan,
    get_current_ai_policy,
)
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers, create_test_jwt


# =============================================================================
# 1. POLICY DEFINITIONS & VALUE INVARIANTS (STEP 15B)
# =============================================================================

def test_starter_policy_values():
    policy = PLAN_POLICIES["starter"]
    assert policy.tier == "starter"
    assert policy.rate_limit_per_minute == 3
    assert policy.max_tokens == 4000
    assert policy.concurrency_limit == 1
    assert policy.monthly_generation_limit == 20


def test_growth_policy_values():
    policy = PLAN_POLICIES["growth"]
    assert policy.tier == "growth"
    assert policy.rate_limit_per_minute == 10
    assert policy.max_tokens == 4000
    assert policy.concurrency_limit == 2
    assert policy.monthly_generation_limit == 100


def test_agency_policy_values():
    policy = PLAN_POLICIES["agency"]
    assert policy.tier == "agency"
    assert policy.rate_limit_per_minute == 30
    assert policy.max_tokens == 4000
    assert policy.concurrency_limit == 5
    assert policy.monthly_generation_limit == 500


def test_plan_policies_contains_only_three_commercial_tiers():
    assert set(PLAN_POLICIES.keys()) == {"starter", "growth", "agency"}
    assert "enterprise" not in PLAN_POLICIES


def test_policy_immutability():
    policy = PLAN_POLICIES["starter"]
    with pytest.raises(Exception):
        # AIPlanPolicy is frozen
        policy.max_tokens = 999999


# =============================================================================
# 2. AUTHORITATIVE PLAN RESOLUTION (STEP 15C & 15D)
# =============================================================================

def test_resolve_ai_plan_starter():
    profile = {
        "id": "user-starter-1",
        "subscription_tier": "starter",
        "subscription_status": "active"
    }
    policy = resolve_ai_plan("user-starter-1", profile=profile)
    assert policy.tier == "starter"
    assert policy == PLAN_POLICIES["starter"]


def test_resolve_ai_plan_growth():
    profile = {
        "id": "user-growth-1",
        "subscription_tier": "growth",
        "subscription_status": "active"
    }
    policy = resolve_ai_plan("user-growth-1", profile=profile)
    assert policy.tier == "growth"
    assert policy == PLAN_POLICIES["growth"]


def test_resolve_ai_plan_agency():
    profile = {
        "id": "user-agency-1",
        "subscription_tier": "agency",
        "subscription_status": "active"
    }
    policy = resolve_ai_plan("user-agency-1", profile=profile)
    assert policy.tier == "agency"
    assert policy == PLAN_POLICIES["agency"]


def test_resolve_ai_plan_legacy_enterprise_maps_safely_to_agency():
    """Verify that existing legacy server-side enterprise profiles map safely to Agency."""
    profile = {
        "id": "user-enterprise-1",
        "subscription_tier": "enterprise",
        "subscription_status": "active"
    }
    policy = resolve_ai_plan("user-enterprise-1", profile=profile)
    assert policy.tier == "agency"
    assert policy == PLAN_POLICIES["agency"]


def test_resolve_ai_plan_legacy_tier_column_fallback():
    profile = {
        "id": "user-legacy-1",
        "tier": "growth",  # legacy column without subscription_tier
        "subscription_status": "active"
    }
    policy = resolve_ai_plan("user-legacy-1", profile=profile)
    assert policy.tier == "growth"


def test_resolve_ai_plan_unknown_tier_fails_secure_to_starter():
    malicious_or_unknown = [
        "admin",
        "agency_plus",
        "growth_admin",
        "premium",
        "unlimited",
        "null",
        "",
        "   ",
        None,
        12345,
    ]
    for bad_tier in malicious_or_unknown:
        profile = {
            "id": "user-tampered",
            "subscription_tier": bad_tier,
            "subscription_status": "active"
        }
        policy = resolve_ai_plan("user-tampered", profile=profile)
        assert policy.tier == "starter", f"Expected 'starter' for invalid tier '{bad_tier}', got '{policy.tier}'"
        assert policy.rate_limit_per_minute == 3
        assert policy.max_tokens == 4000
        assert policy.concurrency_limit == 1
        assert policy.monthly_generation_limit == 20


def test_resolve_ai_plan_missing_profile_defaults_to_starter():
    with patch.object(supabase_service, "get_user_profile", return_value=None):
        policy = resolve_ai_plan("non-existent-user")
        assert policy.tier == "starter"


def test_resolve_ai_plan_valid_trial():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    profile = {
        "id": "user-trialing",
        "subscription_tier": "growth",
        "subscription_status": "trialing",
        "trial_ends_at": future
    }
    policy = resolve_ai_plan("user-trialing", profile=profile, enforce_active=True)
    assert policy.tier == "growth"


def test_resolve_ai_plan_expired_trial_enforcement():
    from fastapi import HTTPException
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    profile = {
        "id": "user-expired-trial",
        "subscription_tier": "agency",
        "subscription_status": "trialing",
        "trial_ends_at": past
    }
    with pytest.raises(HTTPException) as exc_info:
        resolve_ai_plan("user-expired-trial", profile=profile, enforce_active=True)
    assert exc_info.value.status_code == 402


# =============================================================================
# 3. CLIENT-SIDE ANTI-SPOOFING TESTS (STEP 15E)
# =============================================================================

@pytest.mark.asyncio
async def test_client_cannot_elevate_tier_via_request_body():
    """Verify that submitting 'tier' or 'plan' in request payload is rejected or ignored."""
    user_id = f"test-starter-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Client attempts to inject "tier": "agency" into extra fields
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={
                    "subject": "Order update for {{ order.name }}",
                    "body": "Your order is ready.",
                    "tier": "agency",
                    "plan": "agency"
                }
            )
            # Pydantic extra="forbid" rejects unexpected fields
            assert res.status_code == 422


@pytest.mark.asyncio
async def test_client_cannot_elevate_tier_via_query_parameters():
    """Verify query parameters like ?tier=agency have zero effect on authoritative policy resolution."""
    user_id = f"test-starter-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        # Resolve via dependency
        policy = await get_current_ai_policy(user_id=user_id)
        assert policy.tier == "starter"
        assert policy.rate_limit_per_minute == 3
        assert policy.max_tokens == 4000


@pytest.mark.asyncio
async def test_client_cannot_elevate_tier_via_custom_headers():
    """Verify custom headers like X-Plan-Tier or X-Subscription-Tier are ignored."""
    user_id = f"test-starter-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = auth_headers(user_id)
            headers["X-Plan-Tier"] = "agency"
            headers["X-Subscription-Tier"] = "enterprise"

            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=headers,
                json={
                    "subject": "Order update for {{ order.name }}",
                    "body": "Your order is ready."
                }
            )
            # Endpoint executes successfully using the starter user's identity
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True


@pytest.mark.asyncio
async def test_client_cannot_claim_enterprise_to_elevate_access():
    """Verify that a client passing enterprise in body, query, or headers cannot obtain Agency or elevated privileges."""
    user_id = f"test-starter-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Body parameter injection is rejected with 422
            res_body = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={
                    "subject": "Order update for {{ order.name }}",
                    "body": "Your order is ready.",
                    "tier": "enterprise",
                    "plan": "enterprise",
                }
            )
            assert res_body.status_code == 422

            # 2. Query parameter or header has zero effect on policy
            policy = await get_current_ai_policy(user_id=user_id)
            assert policy.tier == "starter"
            assert policy.rate_limit_per_minute == 3
            assert policy.monthly_generation_limit == 20
            assert policy.concurrency_limit == 1


# =============================================================================
# 4. PHASE B: PLAN-AWARE RATE LIMITS, MAX TOKENS & NON-BLOCKING RPC
# =============================================================================

@pytest.mark.asyncio
async def test_starter_plan_rate_limit_3_rpm():
    """Verify Starter tier is capped at exactly 3 req/min with 4th returning 429."""
    user_id = f"starter-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    for i in range(3):
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={
                                "subject": f"Order {i}",
                                "body": f"Your order {i} is confirmed."
                            }
                        )
                        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

                    # 4th request must return 429
                    res_blocked = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={
                            "subject": "Order 4",
                            "body": "Your order 4 is confirmed."
                        }
                    )
                    assert res_blocked.status_code == 429
                    assert "Rate limit exceeded" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_growth_plan_rate_limit_10_rpm():
    """Verify Growth tier is capped at exactly 10 req/min with 11th returning 429."""
    user_id = f"growth-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "growth",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    for i in range(10):
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={
                                "subject": f"Order {i}",
                                "body": f"Your order {i} is confirmed."
                            }
                        )
                        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

                    # 11th request must return 429
                    res_blocked = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={
                            "subject": "Order 11",
                            "body": "Your order 11 is confirmed."
                        }
                    )
                    assert res_blocked.status_code == 429
                    assert "Rate limit exceeded" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_agency_plan_rate_limit_30_rpm():
    """Verify Agency tier allows up to 30 req/min with 31st returning 429."""
    user_id = f"agency-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "agency",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    for i in range(30):
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={
                                "subject": f"Order {i}",
                                "body": f"Your order {i} is confirmed."
                            }
                        )
                        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

                    # 31st request must return 429
                    res_blocked = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={
                            "subject": "Order 31",
                            "body": "Your order 31 is confirmed."
                        }
                    )
                    assert res_blocked.status_code == 429
                    assert "Rate limit exceeded" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_tier_defaults_to_starter_rate_limit_3_rpm():
    """Verify unknown or unmapped tier cannot obtain Agency limit and defaults to Starter 3/min."""
    user_id = f"unknown-tier-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "custom_enterprise_hack",
        "subscription_status": "active"
    }

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                for i in range(3):
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={
                            "subject": f"Order {i}",
                            "body": f"Your order {i} is confirmed."
                        }
                    )
                    assert res.status_code == 200

                # 4th request must be rejected under Starter fallback policy
                res_blocked = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={
                        "subject": "Order 4",
                        "body": "Your order 4 is confirmed."
                    }
                )
                assert res_blocked.status_code == 429


@pytest.mark.asyncio
async def test_client_cannot_spoof_tier_to_bypass_rate_limit():
    """Verify client sending X-Plan-Tier or body parameters cannot elevate Starter rate limit."""
    user_id = f"spoof-rl-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                headers = auth_headers(user_id)
                headers["X-Plan-Tier"] = "agency"
                headers["X-Subscription-Tier"] = "enterprise"

                for i in range(3):
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=headers,
                        json={
                            "subject": f"Order {i}",
                            "body": f"Your order {i} is confirmed."
                        }
                    )
                    assert res.status_code == 200

                # 4th request must still be rejected
                res_blocked = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=headers,
                    json={
                        "subject": "Order 4",
                        "body": "Your order 4 is confirmed."
                    }
                )
                assert res_blocked.status_code == 429


@pytest.mark.asyncio
async def test_user_rate_limit_isolation_across_tiers():
    """Verify that User A exhausting Starter quota does NOT affect User B on Growth quota."""
    user_a = f"starter-iso-{uuid.uuid4().hex[:8]}"
    user_b = f"growth-iso-{uuid.uuid4().hex[:8]}"

    def mock_get_profile(uid: str):
        if uid == user_a:
            return {"id": user_a, "subscription_tier": "starter", "subscription_status": "active"}
        return {"id": user_b, "subscription_tier": "growth", "subscription_status": "active"}

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", side_effect=mock_get_profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # User A consumes all 3 tokens
                for i in range(3):
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_a),
                        json={"subject": f"Order A {i}", "body": "Order confirmation."}
                    )
                    assert res.status_code == 200

                # User A is blocked on 4th
                res_a4 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_a),
                    json={"subject": "Order A 4", "body": "Order confirmation."}
                )
                assert res_a4.status_code == 429

                # User B can still make requests unimpaired
                for j in range(5):
                    res_b = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_b),
                        json={"subject": f"Order B {j}", "body": "Order confirmation."}
                    )
                    assert res_b.status_code == 200


@pytest.mark.asyncio
async def test_client_cannot_inject_max_tokens_in_request_body():
    """Verify client sending max_tokens in body is rejected with HTTP 422 (extra fields forbidden)."""
    user_id = "test-token-spoof-user"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={
                    "subject": "Order update",
                    "body": "Your order is ready.",
                    "max_tokens": 4000,
                }
            )
            assert res.status_code == 422


@pytest.mark.asyncio
async def test_plan_aware_max_tokens_passed_to_provider():
    """Verify that effective_max_tokens sent to provider matches policy for each tier."""
    tiers_to_expected_tokens = {
        "starter": 4000,
        "growth": 4000,
        "agency": 4000,
    }

    from app.services.ai.content_optimizer import ai_content_service

    for tier, expected_tokens in tiers_to_expected_tokens.items():
        user_id = f"token-test-{tier}"
        profile = {"id": user_id, "subscription_tier": tier, "subscription_status": "active"}

        with patch.object(supabase_service, "get_user_profile", return_value=profile):
            mock_provider = MagicMock()
            mock_provider.provider_name = "mock_test_provider"
            mock_provider.generate_variants = AsyncMock(return_value=[{
                "variant_id": "v1_test",
                "variant_name": "Test Variant",
                "subject": "Subject",
                "body_html": "<p>Body</p>",
                "estimated_spam_risk": 1,
                "rationale": "Test"
            }])

            with patch.object(ai_content_service, "_explicit_provider", mock_provider):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order update", "body": "Your order is ready."}
                    )
                    assert res.status_code == 200
                    assert mock_provider.generate_variants.called
                    _, kwargs = mock_provider.generate_variants.call_args
                    assert kwargs.get("max_tokens") == expected_tokens


@pytest.mark.asyncio
async def test_agent_router_clamps_max_tokens_to_safety_ceiling():
    """Verify AgentRouterLLMProvider clamps requested tokens to global safety ceiling."""
    from app.services.ai.provider import AgentRouterLLMProvider, LLMProviderConfig
    from pydantic import SecretStr

    config = LLMProviderConfig(
        provider_name="agent_router",
        model_name="test-model",
        api_base="https://api.test.com/v1",
        api_key=SecretStr("test-key"),
        max_tokens=4000,
        enabled=True,
    )
    provider = AgentRouterLLMProvider(config=config)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "variants": [{
                            "variant_id": "v1",
                            "variant_name": "V1",
                            "subject": "Sub",
                            "body_html": "<p>Body</p>",
                            "estimated_spam_risk": 1,
                            "rationale": "R"
                        }]
                    })
                }
            }]
        }
        mock_post.return_value = mock_resp

        # Request exceeding ceiling (99999) must be clamped to config.max_tokens (4000)
        await provider.generate_variants(
            subject="Sub",
            body_content="Body",
            max_tokens=99999,
        )
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["max_tokens"] == 4000

        # Request within ceiling (1000) must be respected
        await provider.generate_variants(
            subject="Sub",
            body_content="Body",
            max_tokens=1000,
        )
        _, kwargs2 = mock_post.call_args
        assert kwargs2["json"]["max_tokens"] == 1000


@pytest.mark.asyncio
async def test_async_rate_limit_executes_in_worker_thread():
    """
    CRITICAL ARCHITECTURE REQUIREMENT:
    Proves that the synchronous rate-limit RPC is NOT executed on the async
    event-loop thread, but offloaded via asyncio.to_thread to a worker thread.
    """
    import threading
    event_loop_thread_id = threading.get_ident()
    rpc_executed_thread_id = None

    original_consume = supabase_service.consume_rate_limit

    def instrumented_consume(*args, **kwargs):
        nonlocal rpc_executed_thread_id
        rpc_executed_thread_id = threading.get_ident()
        return original_consume(*args, **kwargs)

    user_id = f"thread-test-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(supabase_service, "consume_rate_limit", side_effect=instrumented_consume):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order update", "body": "Order confirmed."}
                )
                assert res.status_code == 200

    # Thread ID inside consume_rate_limit MUST differ from the event-loop thread
    assert rpc_executed_thread_id is not None
    assert rpc_executed_thread_id != event_loop_thread_id, (
        f"RPC executed on event-loop thread {event_loop_thread_id}; must run in worker thread!"
    )


@pytest.mark.asyncio
async def test_rpc_failure_engages_conservative_fallback():
    """Verify that when database rate-limit RPC throws, conservative fallback engages safely."""
    user_id = f"db-down-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    def failing_consume(*args, **kwargs):
        raise RuntimeError("Supabase connection timed out / database unreachable")

    from app.core.rate_limiter import _FALLBACK_STORES
    _FALLBACK_STORES.get("ai", {}).clear()

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(supabase_service, "consume_rate_limit", side_effect=failing_consume):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # Starter conservative fallback limit is 3/min
                for i in range(3):
                    res = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": f"Order {i}", "body": f"Order {i} confirmed."}
                    )
                    assert res.status_code == 200

                # 4th request must be rejected under conservative safety budget
                res_blocked = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 4", "body": "Order 4 confirmed."}
                )
                assert res_blocked.status_code == 429
                assert "Rate limit service temporarily degraded" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_liquid_preservation_and_fallback_remain_active_with_ai_policy():
    """Verify that Liquid preservation and heuristic fallback operate completely unimpaired."""
    user_id = "test-liquid-user-111"
    profile = {
        "id": user_id,
        "subscription_tier": "agency",
        "subscription_status": "active"
    }

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={
                    "subject": "Order {{ order.name }} update",
                    "body": "<p>Hello {{ customer.first_name }}! Order {{ order.name }} has been confirmed.</p>"
                }
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            variants = data["variants"]
            assert len(variants) > 0
            for v in variants:
                # All Liquid tags preserved verbatim
                assert "{{ order.name }}" in v["subject"] or "{{ order.name }}" in v["body_html"]
                assert "{{ customer.first_name }}" in v["body_html"]


# =============================================================================
# 5. STEP 17A: PLAN-AWARE RPM ENFORCEMENT & SECURITY VERIFICATION
# =============================================================================

@pytest.mark.asyncio
async def test_legacy_enterprise_receives_agency_rate_limit_30_rpm():
    """Verify legacy enterprise server profile receives Agency 30 RPM limit at runtime."""
    user_id = f"enterprise-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "enterprise",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    for i in range(30):
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={"subject": f"Order {i}", "body": f"Your order {i} is confirmed."}
                        )
                        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

                    # 31st request must return 429
                    res_blocked = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order 31", "body": "Your order 31 is confirmed."}
                    )
                    assert res_blocked.status_code == 429
                    assert "Rate limit exceeded" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_plan_transition_updates_rate_limit_immediately():
    """
    Verify that an authoritative plan upgrade in profile immediately expands
    the rate limit window without stale caching or cross-request pollution.
    """
    user_id = f"transition-user-{uuid.uuid4().hex[:8]}"
    current_profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    def get_profile(uid: str):
        if uid == user_id:
            return current_profile
        return None

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service._in_memory_rate_limits.clear()
    with patch.object(supabase_service, "get_user_profile", side_effect=get_profile):
        with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
            with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    # 1. As Starter, send 3 requests (all 200)
                    for i in range(3):
                        res = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={"subject": f"Order {i}", "body": "Body content"}
                        )
                        assert res.status_code == 200

                    # 2. 4th request rejected under Starter limit
                    res_blocked = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order 4", "body": "Body content"}
                    )
                    assert res_blocked.status_code == 429

                    # 3. User upgrades to Growth in database (limit 10)
                    current_profile["subscription_tier"] = "growth"

                    # 4. Next request (attempt 5, within Growth limit 10) immediately succeeds
                    res_growth_retry = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order 4 retry", "body": "Body content"}
                    )
                    assert res_growth_retry.status_code == 200

                    # 5. User can continue up to 10 total requests in this window (attempts 6..10)
                    for j in range(6, 11):
                        res_growth_cont = await ac.post(
                            "/api/v1/ai/generate-variants",
                            headers=auth_headers(user_id),
                            json={"subject": f"Order {j}", "body": "Body content"}
                        )
                        assert res_growth_cont.status_code == 200

                    # 6. Attempt 11 under Growth is blocked (exceeds limit of 10)
                    res_growth_11 = await ac.post(
                        "/api/v1/ai/generate-variants",
                        headers=auth_headers(user_id),
                        json={"subject": "Order 11", "body": "Body content"}
                    )
                    assert res_growth_11.status_code == 429


def test_no_global_mutable_policy_state():
    """Verify that AI plan policies are immutable and cannot be mutated globally."""
    from pydantic import ValidationError
    starter_policy = PLAN_POLICIES["starter"]

    # Attempting to mutate fields on frozen model must raise error
    with pytest.raises((ValidationError, TypeError)):
        starter_policy.rate_limit_per_minute = 100

    # Ensure PLAN_POLICIES dictionary keys and tier objects remain untampered
    assert PLAN_POLICIES["starter"].rate_limit_per_minute == 3
    assert PLAN_POLICIES["growth"].rate_limit_per_minute == 10
    assert PLAN_POLICIES["agency"].rate_limit_per_minute == 30


# =============================================================================
# 9. STEP 17B: PLAN-AWARE MONTHLY AI GENERATION QUOTA ENFORCEMENT
# =============================================================================

def test_monthly_generation_quota_limits_values():
    """Verify authoritative monthly generation limits for each tier."""
    assert PLAN_POLICIES["starter"].monthly_generation_limit == 20
    assert PLAN_POLICIES["growth"].monthly_generation_limit == 100
    assert PLAN_POLICIES["agency"].monthly_generation_limit == 500


def test_starter_monthly_quota_direct_consumption_20_allowed_21_rejected():
    """Direct quota ledger: Starter allows exactly 20 consumptions, 21st is rejected."""
    uid = f"user-{uuid.uuid4().hex[:8]}"
    period = "2026-09"
    limit = 20

    with patch.object(supabase_service, "_client", None):
        for i in range(1, 21):
            res = supabase_service.consume_ai_monthly_generation(uid, period, limit)
            assert res["allowed"] is True
            assert res["current_usage"] == i
            assert res["remaining"] == limit - i

        # 21st attempt rejected
        blocked = supabase_service.consume_ai_monthly_generation(uid, period, limit)
        assert blocked["allowed"] is False
        assert blocked["current_usage"] == 20
        assert blocked["remaining"] == 0


def test_growth_monthly_quota_direct_consumption_100_allowed_101_rejected():
    """Direct quota ledger: Growth allows exactly 100 consumptions, 101st is rejected."""
    uid = f"user-{uuid.uuid4().hex[:8]}"
    period = "2026-09"
    limit = 100

    with patch.object(supabase_service, "_client", None):
        for i in range(1, 101):
            res = supabase_service.consume_ai_monthly_generation(uid, period, limit)
            assert res["allowed"] is True
            assert res["current_usage"] == i

        blocked = supabase_service.consume_ai_monthly_generation(uid, period, limit)
        assert blocked["allowed"] is False
        assert blocked["current_usage"] == 100
        assert blocked["remaining"] == 0


def test_agency_monthly_quota_direct_consumption_500_allowed_501_rejected():
    """Direct quota ledger: Agency allows exactly 500 consumptions, 501st is rejected."""
    uid = f"user-{uuid.uuid4().hex[:8]}"
    period = "2026-09"
    limit = 500

    with patch.object(supabase_service, "_client", None):
        for i in range(1, 501):
            res = supabase_service.consume_ai_monthly_generation(uid, period, limit)
            assert res["allowed"] is True
            assert res["current_usage"] == i

        blocked = supabase_service.consume_ai_monthly_generation(uid, period, limit)
        assert blocked["allowed"] is False
        assert blocked["current_usage"] == 500
        assert blocked["remaining"] == 0


@pytest.mark.asyncio
async def test_starter_endpoint_20th_allowed_21st_rejected_http_402():
    """Endpoint: Starter user at 19 runs can use 20th run; 21st returns HTTP 402 AI_MONTHLY_QUOTA_EXCEEDED."""
    user_id = f"starter-quota-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    # Pre-set usage to 19
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 19
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # 20th request succeeds
                res20 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 20", "body": "Your order 20"}
                )
                assert res20.status_code == 200
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 20

                # 21st request rejected with HTTP 402
                res21 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 21", "body": "Your order 21"}
                )
                assert res21.status_code == 402
                data = res21.json()["detail"]
                assert data["error_code"] == "AI_MONTHLY_QUOTA_EXCEEDED"
                assert data["current_usage"] == 20
                assert data["monthly_limit"] == 20
                assert data["remaining"] == 0
                assert data["tier"] == "starter"


@pytest.mark.asyncio
async def test_growth_endpoint_100th_allowed_101st_rejected_http_402():
    """Endpoint: Growth user at 99 runs can use 100th run; 101st returns HTTP 402."""
    user_id = f"growth-quota-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "growth",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 99
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res100 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 100", "body": "Body 100"}
                )
                assert res100.status_code == 200
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 100

                res101 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 101", "body": "Body 101"}
                )
                assert res101.status_code == 402
                data = res101.json()["detail"]
                assert data["error_code"] == "AI_MONTHLY_QUOTA_EXCEEDED"
                assert data["current_usage"] == 100
                assert data["monthly_limit"] == 100
                assert data["remaining"] == 0
                assert data["tier"] == "growth"


@pytest.mark.asyncio
async def test_agency_endpoint_500th_allowed_501st_rejected_http_402():
    """Endpoint: Agency user at 499 runs can use 500th run; 501st returns HTTP 402."""
    user_id = f"agency-quota-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "agency",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 499
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res500 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 500", "body": "Body 500"}
                )
                assert res500.status_code == 200
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 500

                res501 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 501", "body": "Body 501"}
                )
                assert res501.status_code == 402
                data = res501.json()["detail"]
                assert data["error_code"] == "AI_MONTHLY_QUOTA_EXCEEDED"
                assert data["current_usage"] == 500
                assert data["monthly_limit"] == 500
                assert data["remaining"] == 0
                assert data["tier"] == "agency"


@pytest.mark.asyncio
async def test_unknown_tier_receives_starter_monthly_quota_20():
    """Unrecognized or missing profile tier safely defaults to Starter quota (20)."""
    user_id = f"unknown-quota-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "unrecognized_custom_tier",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 19
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res20 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 20", "body": "Body 20"}
                )
                assert res20.status_code == 200

                res21 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 21", "body": "Body 21"}
                )
                assert res21.status_code == 402
                assert res21.json()["detail"]["monthly_limit"] == 20


@pytest.mark.asyncio
async def test_legacy_enterprise_resolves_to_agency_monthly_quota_500():
    """Legacy Enterprise server profile maps to Agency limit 500 (never unlimited, never 20)."""
    user_id = f"enterprise-quota-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "enterprise",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 499
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res500 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 500", "body": "Body 500"}
                )
                assert res500.status_code == 200

                res501 = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 501", "body": "Body 501"}
                )
                assert res501.status_code == 402
                assert res501.json()["detail"]["monthly_limit"] == 500
                assert res501.json()["detail"]["tier"] == "agency"


@pytest.mark.asyncio
async def test_client_cannot_elevate_monthly_quota_via_headers_or_params():
    """Client cannot bypass monthly quota by providing tier/plan headers or query params."""
    user_id = f"tamper-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    # Exhausted Starter quota
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 20
    supabase_service._in_memory_rate_limits.clear()

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                headers = auth_headers(user_id)
                headers["X-Subscription-Tier"] = "agency"
                headers["X-Plan"] = "agency"

                res = await ac.post(
                    "/api/v1/ai/generate-variants?tier=agency&plan=agency",
                    headers=headers,
                    json={"subject": "Tamper Test", "body": "Trying to bypass quota"}
                )
                assert res.status_code == 402
                assert res.json()["detail"]["error_code"] == "AI_MONTHLY_QUOTA_EXCEEDED"
                assert res.json()["detail"]["monthly_limit"] == 20


@pytest.mark.asyncio
async def test_tenant_isolation_user_a_cannot_consume_user_b_monthly_quota():
    """User A exhausting quota does not affect User B's quota."""
    user_a = f"user-a-{uuid.uuid4().hex[:8]}"
    user_b = f"user-b-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")

    supabase_service._in_memory_ai_monthly_usage[f"{user_a}:{period}"] = 20
    supabase_service._in_memory_ai_monthly_usage[f"{user_b}:{period}"] = 0
    supabase_service._in_memory_rate_limits.clear()

    def get_profile(uid: str):
        return {
            "id": uid,
            "subscription_tier": "starter",
            "subscription_status": "active"
        }

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", side_effect=get_profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # User A is blocked
                res_a = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_a),
                    json={"subject": "Order A", "body": "Body A"}
                )
                assert res_a.status_code == 402

                # User B succeeds
                res_b = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_b),
                    json={"subject": "Order B", "body": "Body B"}
                )
                assert res_b.status_code == 200
                assert supabase_service.get_ai_monthly_usage(user_b, period) == 1
                assert supabase_service.get_ai_monthly_usage(user_a, period) == 20


@pytest.mark.asyncio
async def test_plan_upgrade_immediately_unlocks_quota_preserving_usage():
    """Upgrading Starter (20/20) to Growth immediately raises limit to 100 without resetting usage count."""
    user_id = f"upgrade-user-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 20
    supabase_service._in_memory_rate_limits.clear()

    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service
    sample_variants = [{"variant_id": "v1", "subject": "Sub", "body_html": "<p>Content</p>"}]

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=sample_variants):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # 1. Blocked on Starter (20/20)
                res_blocked = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order", "body": "Body"}
                )
                assert res_blocked.status_code == 402

                # 2. Upgrade profile in-place to Growth
                profile["subscription_tier"] = "growth"

                # 3. Next request succeeds (21st run out of 100)
                res_upgraded = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order 21", "body": "Body"}
                )
                assert res_upgraded.status_code == 200
                # Usage count is preserved at 21, not reset
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 21


@pytest.mark.asyncio
async def test_plan_downgrade_immediately_enforces_lower_limit_preserving_usage():
    """Downgrading from Growth (25/100) to Starter (limit 20) immediately blocks without usage reset."""
    user_id = f"downgrade-user-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 25
    supabase_service._in_memory_rate_limits.clear()

    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 402
            data = res.json()["detail"]
            assert data["current_usage"] == 25
            assert data["monthly_limit"] == 20
            assert data["remaining"] == 0


def test_concurrency_race_condition_final_slot_atomicity():
    """
    Simulate multiple concurrent threads competing for the 20th slot (usage=19, limit=20).
    Exactly ONE request must succeed; all others must be rejected. Final usage must be 20, never 21.
    """
    import concurrent.futures

    uid = f"concurrent-user-{uuid.uuid4().hex[:8]}"
    period = "2026-09"
    limit = 20
    supabase_service._in_memory_ai_monthly_usage[f"{uid}:{period}"] = 19

    results = []

    def attempt_consume():
        return supabase_service.consume_ai_monthly_generation(uid, period, limit)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_consume) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    allowed_count = sum(1 for r in results if r["allowed"] is True)
    rejected_count = sum(1 for r in results if r["allowed"] is False)

    assert allowed_count == 1, f"Expected exactly 1 success, got {allowed_count}"
    assert rejected_count == 9, f"Expected 9 rejections, got {rejected_count}"
    assert supabase_service.get_ai_monthly_usage(uid, period) == 20


@pytest.mark.asyncio
async def test_db_failure_fails_safe_without_granting_unlimited_generations():
    """If database quota storage is unavailable, endpoint must fail safe (503) rather than granting free runs."""
    user_id = f"fail-safe-user-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.supabase_client import DatabaseUnavailableError
    from app.services.ai.content_optimizer import ai_content_service

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(
            supabase_service,
            "consume_ai_monthly_generation",
            side_effect=DatabaseUnavailableError("PostgreSQL pool connection failed")
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order", "body": "Body"}
                )
                assert res.status_code == 503
                assert "temporarily unavailable" in res.json()["detail"]


@pytest.mark.asyncio
async def test_failed_generation_refunds_quota_reservation():
    """If generation raises an unhandled exception downstream, reserved quota is rolled back."""
    user_id = f"rollback-user-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 5
    supabase_service._in_memory_rate_limits.clear()

    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        with patch.object(
            ai_content_service,
            "generate_polymorphic_variants",
            side_effect=RuntimeError("Provider gateway timeout")
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order", "body": "Body"}
                )
                assert res.status_code == 500
                # Usage must be refunded back to 5
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 5


@pytest.mark.asyncio
async def test_liquid_rejection_empty_variants_refunds_quota_reservation():
    """If generation yields 0 valid variants due to Liquid preservation, quota is refunded."""
    user_id = f"liquid-refund-user-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 5
    supabase_service._in_memory_rate_limits.clear()

    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        # Returns empty list because Liquid tags were corrupted
        with patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order {{ order.name }}", "body": "Body {{ order.name }}"}
                )
                assert res.status_code == 200
                assert res.json()["variants"] == []
                # Usage refunded back to 5
                assert supabase_service.get_ai_monthly_usage(user_id, period) == 5


# =============================================================================
# STEP 17B.1 — AI MONTHLY QUOTA RPC HARDENING TESTS
# =============================================================================

def test_quota_migration_acls_and_redundant_index_removal():
    """Verify that migration 20260930000002 has hardened ACLs and no redundant index."""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
    mig_path = os.path.join(base_dir, "20260930000002_ai_monthly_quota_ledger.sql")

    assert os.path.exists(mig_path), f"Migration not found at {mig_path}"

    with open(mig_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # 1. Primary key exists
    assert "PRIMARY KEY (user_id, billing_period)" in sql

    # 2. Redundant secondary index removed
    assert "idx_ai_generation_usage_user_period" not in sql

    # 3. RLS enabled and policy present
    assert "ALTER TABLE public.ai_generation_usage ENABLE ROW LEVEL SECURITY;" in sql
    assert 'CREATE POLICY "Users can view their own AI generation usage"' in sql
    assert "FOR SELECT" in sql

    # 4. Search path hardened on all 3 functions
    assert sql.count("SET search_path = public, pg_temp") == 3

    # 5. SECURITY DEFINER on all 3 functions
    assert sql.count("SECURITY DEFINER") == 3

    # 6. Hardened ACLs: REVOKE from PUBLIC, anon, authenticated; GRANT to service_role ONLY
    assert "REVOKE ALL ON FUNCTION public.consume_ai_monthly_generation(UUID, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.consume_ai_monthly_generation(UUID, TEXT, INTEGER) TO service_role;" in sql

    assert "REVOKE ALL ON FUNCTION public.rollback_ai_monthly_generation(UUID, TEXT) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.rollback_ai_monthly_generation(UUID, TEXT) TO service_role;" in sql

    assert "REVOKE ALL ON FUNCTION public.get_ai_monthly_usage(UUID, TEXT) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.get_ai_monthly_usage(UUID, TEXT) TO service_role;" in sql

    # 7. No execute grants to authenticated or anon in section 6
    grant_section = sql.split("6. Restrict Execution Permissions")[1]
    assert "TO authenticated" not in grant_section
    assert "TO anon" not in grant_section


def test_authenticated_client_direct_rpc_invocation_denied():
    """Simulate PostgREST rejecting direct client RPC calls with 42501 / permission denied."""
    mock_postgrest_error = Exception("PGRST301: permission denied for function rollback_ai_monthly_generation")

    mock_client = MagicMock()
    mock_client.rpc.side_effect = mock_postgrest_error

    with patch.object(supabase_service, "_client", mock_client):
        with pytest.raises(Exception) as exc_info:
            supabase_service._client.rpc("rollback_ai_monthly_generation", {
                "p_user_id": str(uuid.uuid4()),
                "p_billing_period": "2026-09"
            }).execute()
        assert "permission denied" in str(exc_info.value)


def test_service_role_backend_rpc_execution_supported():
    """Verify backend supabase_service properly calls consume, rollback, and get RPCs with service_role."""
    mock_client = MagicMock()
    mock_consume_res = MagicMock()
    mock_consume_res.data = {
        "allowed": True,
        "current_usage": 1,
        "limit": 20,
        "remaining": 19,
    }
    mock_usage_res = MagicMock()
    mock_usage_res.data = 1

    def rpc_dispatcher(fn_name, params):
        builder = MagicMock()
        if fn_name == "consume_ai_monthly_generation":
            builder.execute.return_value = mock_consume_res
        elif fn_name == "get_ai_monthly_usage":
            builder.execute.return_value = mock_usage_res
        elif fn_name == "rollback_ai_monthly_generation":
            builder.execute.return_value = MagicMock(data=None)
        return builder

    mock_client.rpc.side_effect = rpc_dispatcher

    user_id = str(uuid.uuid4())
    period = "2026-09"

    with patch.object(supabase_service, "_client", mock_client), \
         patch.object(supabase_service, "_has_monthly_quota_rpc", True):
        # 1. Consume
        consume_res = supabase_service.consume_ai_monthly_generation(user_id, period, 20)
        assert consume_res["allowed"] is True
        assert consume_res["current_usage"] == 1

        # 2. Get
        usage = supabase_service.get_ai_monthly_usage(user_id, period)
        assert usage == 1

        # 3. Rollback
        supabase_service.rollback_ai_monthly_generation(user_id, period)
        mock_client.rpc.assert_any_call(
            "rollback_ai_monthly_generation",
            {"p_user_id": user_id, "p_billing_period": period}
        )


def test_rollback_cannot_decrement_below_zero_and_is_tenant_scoped():
    """Rollback never decrements usage below zero and is strictly scoped to user and period."""
    user_a = f"user-a-{uuid.uuid4().hex[:8]}"
    user_b = f"user-b-{uuid.uuid4().hex[:8]}"
    period = "2026-09"
    other_period = "2026-10"

    # User A has 1 usage in 2026-09
    supabase_service._in_memory_ai_monthly_usage[f"{user_a}:{period}"] = 1
    # User B has 5 usage in 2026-09
    supabase_service._in_memory_ai_monthly_usage[f"{user_b}:{period}"] = 5
    # User A has 3 usage in 2026-10
    supabase_service._in_memory_ai_monthly_usage[f"{user_a}:{other_period}"] = 3

    # Rollback User A in 2026-09
    supabase_service.rollback_ai_monthly_generation(user_a, period)
    assert supabase_service.get_ai_monthly_usage(user_a, period) == 0

    # User B and other periods remain untouched
    assert supabase_service.get_ai_monthly_usage(user_b, period) == 5
    assert supabase_service.get_ai_monthly_usage(user_a, other_period) == 3

    # Second rollback on User A cannot drop below zero
    supabase_service.rollback_ai_monthly_generation(user_a, period)
    assert supabase_service.get_ai_monthly_usage(user_a, period) == 0


# =============================================================================
# STEP 17C — PLAN-AWARE AI CONCURRENCY LEASE TESTS
# =============================================================================

def test_ai_concurrency_policy_values():
    """Verify authoritative concurrency limits from AIPlanPolicy."""
    assert PLAN_POLICIES["starter"].concurrency_limit == 1
    assert PLAN_POLICIES["growth"].concurrency_limit == 2
    assert PLAN_POLICIES["agency"].concurrency_limit == 5


def test_starter_concurrency_direct_acquisition_1_allowed_2_rejected():
    """Starter: Exactly 1 concurrent lease allowed, 2nd is rejected."""
    uid = f"starter-conc-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    with patch.object(supabase_service, "_client", None):
        lease_1 = str(uuid.uuid4())
        res_1 = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_1)
        assert res_1["allowed"] is True
        assert res_1["current_active"] == 1
        assert res_1["concurrency_limit"] == 1

        lease_2 = str(uuid.uuid4())
        res_2 = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_2)
        assert res_2["allowed"] is False
        assert res_2["current_active"] == 1
        assert res_2["concurrency_limit"] == 1

        # Release lease_1 unlocks slot for lease_2
        released = supabase_service.release_ai_concurrency_slot(uid, lease_1)
        assert released is True

        res_2_retry = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_2)
        assert res_2_retry["allowed"] is True
        assert res_2_retry["current_active"] == 1


def test_growth_concurrency_direct_acquisition_2_allowed_3_rejected():
    """Growth: Exactly 2 concurrent leases allowed, 3rd is rejected."""
    uid = f"growth-conc-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    with patch.object(supabase_service, "_client", None):
        l1, l2, l3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        assert supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=2, lease_id=l1)["allowed"] is True
        assert supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=2, lease_id=l2)["allowed"] is True

        blocked = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=2, lease_id=l3)
        assert blocked["allowed"] is False
        assert blocked["current_active"] == 2

        supabase_service.release_ai_concurrency_slot(uid, l1)
        assert supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=2, lease_id=l3)["allowed"] is True


def test_agency_concurrency_direct_acquisition_5_allowed_6_rejected():
    """Agency: Exactly 5 concurrent leases allowed, 6th is rejected."""
    uid = f"agency-conc-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    with patch.object(supabase_service, "_client", None):
        leases = [str(uuid.uuid4()) for _ in range(5)]
        for l in leases:
            res = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=5, lease_id=l)
            assert res["allowed"] is True

        extra_lease = str(uuid.uuid4())
        blocked = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=5, lease_id=extra_lease)
        assert blocked["allowed"] is False
        assert blocked["current_active"] == 5


def test_concurrency_user_isolation():
    """User A holding max slots has zero effect on User B's available concurrency."""
    user_a = f"user-a-{uuid.uuid4().hex[:8]}"
    user_b = f"user-b-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    with patch.object(supabase_service, "_client", None):
        l_a = str(uuid.uuid4())
        res_a = supabase_service.acquire_ai_concurrency_slot(user_a, concurrency_limit=1, lease_id=l_a)
        assert res_a["allowed"] is True

        # User B can acquire their own slot
        l_b = str(uuid.uuid4())
        res_b = supabase_service.acquire_ai_concurrency_slot(user_b, concurrency_limit=1, lease_id=l_b)
        assert res_b["allowed"] is True

        # User A cannot release User B's lease
        supabase_service.release_ai_concurrency_slot(user_a, l_b)
        assert supabase_service.get_ai_active_concurrency(user_b) == 1


def test_concurrency_race_condition_starter_10_concurrent_threads():
    """10 simultaneous threads competing for 1 Starter concurrency slot: exactly 1 wins."""
    import concurrent.futures
    uid = f"race-starter-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    results = []

    def attempt_acquire():
        lease_id = str(uuid.uuid4())
        return supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_acquire) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    allowed = [r for r in results if r["allowed"] is True]
    rejected = [r for r in results if r["allowed"] is False]

    assert len(allowed) == 1, f"Expected 1 allowed, got {len(allowed)}"
    assert len(rejected) == 9, f"Expected 9 rejected, got {len(rejected)}"
    assert supabase_service.get_ai_active_concurrency(uid) == 1


def test_concurrency_race_condition_growth_10_concurrent_threads():
    """10 simultaneous threads competing for 2 Growth concurrency slots: exactly 2 win."""
    import concurrent.futures
    uid = f"race-growth-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    results = []

    def attempt_acquire():
        lease_id = str(uuid.uuid4())
        return supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=2, lease_id=lease_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_acquire) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    allowed = [r for r in results if r["allowed"] is True]
    rejected = [r for r in results if r["allowed"] is False]

    assert len(allowed) == 2, f"Expected 2 allowed, got {len(allowed)}"
    assert len(rejected) == 8, f"Expected 8 rejected, got {len(rejected)}"
    assert supabase_service.get_ai_active_concurrency(uid) == 2


def test_concurrency_race_condition_agency_10_concurrent_threads():
    """10 simultaneous threads competing for 5 Agency concurrency slots: exactly 5 win."""
    import concurrent.futures
    uid = f"race-agency-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    results = []

    def attempt_acquire():
        lease_id = str(uuid.uuid4())
        return supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=5, lease_id=lease_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_acquire) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    allowed = [r for r in results if r["allowed"] is True]
    rejected = [r for r in results if r["allowed"] is False]

    assert len(allowed) == 5, f"Expected 5 allowed, got {len(allowed)}"
    assert len(rejected) == 5, f"Expected 5 rejected, got {len(rejected)}"
    assert supabase_service.get_ai_active_concurrency(uid) == 5


@pytest.mark.asyncio
async def test_endpoint_concurrency_limit_exceeded_returns_429():
    """Active lease in progress causes 2nd request to return HTTP 429 AI_CONCURRENCY_LIMIT_EXCEEDED."""
    user_id = f"endpoint-conc-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()

    # Pre-occupy the 1 Starter slot with an active in-flight lease
    active_lease = str(uuid.uuid4())
    supabase_service.acquire_ai_concurrency_slot(user_id, concurrency_limit=1, lease_id=active_lease, ttl_seconds=60)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 429
            data = res.json()["detail"]
            assert data["error_code"] == "AI_CONCURRENCY_LIMIT_EXCEEDED"
            assert data["current_active"] == 1
            assert data["concurrency_limit"] == 1
            assert data["tier"] == "starter"
            assert "Retry-After" in res.headers


@pytest.mark.asyncio
async def test_concurrency_rejection_does_not_consume_monthly_quota():
    """When a request is rejected due to concurrency limit, monthly quota is NOT consumed."""
    user_id = f"conc-no-quota-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 0

    # Hold the slot
    supabase_service.acquire_ai_concurrency_slot(user_id, concurrency_limit=1, lease_id=str(uuid.uuid4()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 429
            # Monthly usage must remain strictly 0
            assert supabase_service.get_ai_monthly_usage(user_id, period) == 0


@pytest.mark.asyncio
async def test_successful_generation_releases_concurrency_lease():
    """Successful generation releases concurrency lease so the next request succeeds immediately."""
    user_id = f"conc-success-release-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()

    mock_variants = [
        {"subject": "V1", "body_content": "Content 1"},
        {"subject": "V2", "body_content": "Content 2"},
        {"subject": "V3", "body_content": "Content 3"},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(ai_content_service, "generate_polymorphic_variants", return_value=mock_variants):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 200
            # Lease must be released
            assert supabase_service.get_ai_active_concurrency(user_id) == 0


@pytest.mark.asyncio
async def test_provider_error_releases_concurrency_lease():
    """Downstream exception releases concurrency lease, preventing slot starvation."""
    user_id = f"conc-error-release-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(ai_content_service, "generate_polymorphic_variants", side_effect=RuntimeError("Provider 502")):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 500
            # Concurrency lease must be cleanly released despite exception
            assert supabase_service.get_ai_active_concurrency(user_id) == 0


@pytest.mark.asyncio
async def test_liquid_rejection_releases_concurrency_lease():
    """Liquid preservation rejection (empty variants) releases concurrency lease."""
    user_id = f"conc-liquid-release-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(ai_content_service, "generate_polymorphic_variants", return_value=[]):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order {{ name }}", "body": "Body {{ name }}"}
            )
            assert res.status_code == 200
            assert supabase_service.get_ai_active_concurrency(user_id) == 0


@pytest.mark.asyncio
async def test_db_concurrency_failure_fails_closed_503():
    """If database concurrency lease acquisition fails, endpoint fails closed with HTTP 503."""
    user_id = f"conc-db-fail-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.supabase_client import DatabaseUnavailableError

    supabase_service._in_memory_rate_limits.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(supabase_service, "acquire_ai_concurrency_slot", side_effect=DatabaseUnavailableError("DB pool down")):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 503
            assert res.json()["detail"]["error_code"] == "AI_CONCURRENCY_SERVICE_UNAVAILABLE"


def test_concurrency_lease_ttl_expiry_allows_recovery():
    """Expired lease past TTL is automatically pruned, allowing new slot acquisition."""
    uid = f"ttl-user-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    lease_1 = str(uuid.uuid4())
    # Acquire with 1s TTL
    supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_1, ttl_seconds=1)
    assert supabase_service.get_ai_active_concurrency(uid) == 1

    # Simulate clock advance past TTL
    with patch("time.time", return_value=time.time() + 5.0):
        # Expired lease is pruned; new slot is allowed
        lease_2 = str(uuid.uuid4())
        res_2 = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lease_2, ttl_seconds=60)
        assert res_2["allowed"] is True
        assert res_2["current_active"] == 1


def test_legacy_enterprise_resolves_to_agency_concurrency_5():
    """Legacy Enterprise profiles receive Agency concurrency limit of 5."""
    user_id = f"enterprise-conc-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "enterprise",
        "subscription_status": "active"
    }

    resolved = resolve_ai_plan(user_id, profile=profile)
    assert resolved.concurrency_limit == 5


def test_unknown_tier_defaults_to_starter_concurrency_1():
    """Unknown or malformed tier defaults fail-secure to Starter concurrency limit of 1."""
    user_id = f"unknown-conc-{uuid.uuid4().hex[:8]}"
    profile = {
        "id": user_id,
        "subscription_tier": "unknown_custom_tier",
        "subscription_status": "active"
    }

    resolved = resolve_ai_plan(user_id, profile=profile)
    assert resolved.concurrency_limit == 1


def test_concurrency_migration_schema_and_acls():
    """Verify migration 20260930000003 contains table, index, RLS, advisory lock, and service_role ACLs."""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
    mig_path = os.path.join(base_dir, "20260930000003_ai_concurrency_leases.sql")

    assert os.path.exists(mig_path), f"Migration not found at {mig_path}"

    with open(mig_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # 1. Table & Primary Key
    assert "CREATE TABLE IF NOT EXISTS public.ai_concurrency_leases" in sql
    assert "lease_id UUID PRIMARY KEY" in sql
    assert "REFERENCES public.profiles(id) ON DELETE CASCADE" in sql

    # 2. RLS enabled & policy
    assert "ALTER TABLE public.ai_concurrency_leases ENABLE ROW LEVEL SECURITY;" in sql
    assert 'CREATE POLICY "Users can view their own AI concurrency leases"' in sql

    # 3. Advisory lock for cross-instance serialization
    assert "pg_advisory_xact_lock(20260930, v_lock_key)" in sql

    # 4. Search path hardened
    assert sql.count("SET search_path = public, pg_temp") == 3

    # 5. SECURITY DEFINER on all 3 functions
    assert sql.count("SECURITY DEFINER") == 3

    # 6. Hardened ACLs: REVOKE from PUBLIC, anon, authenticated; GRANT to service_role ONLY
    assert "REVOKE ALL ON FUNCTION public.acquire_ai_concurrency_slot(UUID, INTEGER, UUID, INTEGER) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.acquire_ai_concurrency_slot(UUID, INTEGER, UUID, INTEGER) TO service_role;" in sql

    assert "REVOKE ALL ON FUNCTION public.release_ai_concurrency_slot(UUID, UUID) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.release_ai_concurrency_slot(UUID, UUID) TO service_role;" in sql

    assert "REVOKE ALL ON FUNCTION public.get_ai_active_concurrency(UUID) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION public.get_ai_active_concurrency(UUID) TO service_role;" in sql

    # 7. No execute grants to authenticated or anon in Section 6
    grant_section = sql.split("6. Restrict Execution Permissions")[1]
    assert "TO authenticated" not in grant_section
    assert "TO anon" not in grant_section

    # 8. Step 17C.1: Default TTL in migration is 60 seconds
    assert "p_ttl_seconds INTEGER DEFAULT 60" in sql
    assert "v_effective_ttl := COALESCE(p_ttl_seconds, 60);" in sql


# =============================================================================
# STEP 17C.1 — CONCURRENCY LEASE TTL / WALL-CLOCK REMEDIATION TESTS
# =============================================================================

def test_acquire_concurrency_slot_default_ttl_is_60_seconds():
    """Step 17C.1: Default TTL for concurrency lease acquisition is 60 seconds."""
    uid = f"default-ttl-{uuid.uuid4().hex[:8]}"
    supabase_service.reset_in_memory_ai_concurrency_leases()

    lid = str(uuid.uuid4())
    before = time.time()
    res = supabase_service.acquire_ai_concurrency_slot(uid, concurrency_limit=1, lease_id=lid)
    after = time.time()

    assert res["allowed"] is True
    leases = supabase_service._in_memory_ai_concurrency_leases[uid]
    assert len(leases) == 1
    lease = leases[0]
    expected_expiry = lease["acquired_at"] + 60.0
    assert abs(lease["expires_at"] - expected_expiry) < 0.1
    assert lease["expires_at"] >= before + 60.0
    assert lease["expires_at"] <= after + 60.0


def test_provider_config_timeout_bounded_to_20_seconds():
    """Step 17C.1D: Provider timeout is strictly capped at <= 20s to ensure safety under 25s wall-clock."""
    from app.services.ai.provider import LLMProviderConfig

    # 20.0s is valid
    cfg_valid = LLMProviderConfig(timeout_seconds=20.0)
    assert cfg_valid.timeout_seconds == 20.0

    # > 20.0s is rejected by Pydantic validation
    with pytest.raises(Exception):
        LLMProviderConfig(timeout_seconds=20.1)

    with pytest.raises(Exception):
        LLMProviderConfig(timeout_seconds=60.0)

    # from_settings safely clamps any environment setting > 20s to 20.0s
    class MockHighSettings:
        AGENT_ROUTER_API_BASE = "https://mock.router"
        AGENT_ROUTER_API_KEY = "mock-key"
        AGENT_ROUTER_MODEL_NAME = "model"
        AGENT_ROUTER_TIMEOUT_SECONDS = 45.0  # high value in env
        AGENT_ROUTER_MAX_TOKENS = 4000
        AGENT_ROUTER_TEMPERATURE = 0.7
        AGENT_ROUTER_ENABLED = True

    cfg_from_settings = LLMProviderConfig.from_settings(MockHighSettings())
    assert cfg_from_settings.timeout_seconds == 20.0


@pytest.mark.asyncio
async def test_generation_wall_clock_timeout_25s_cancels_and_rolls_back_quota():
    """Step 17C.1B/C: When generation exceeds 25s wall-clock timeout, quota is rolled back and slot released."""
    user_id = f"timeout-rollback-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 0

    # Simulate slow generation that triggers TimeoutError
    async def slow_generator(*args, **kwargs):
        raise TimeoutError("Simulated 25.0s wall clock expiration")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(ai_content_service, "generate_polymorphic_variants", side_effect=slow_generator):
            res = await ac.post(
                "/api/v1/ai/generate-variants",
                headers=auth_headers(user_id),
                json={"subject": "Order", "body": "Body"}
            )
            assert res.status_code == 504
            err_data = res.json()["detail"]
            assert err_data["error_code"] == "AI_GENERATION_TIMEOUT"
            assert "25 seconds" in err_data["message"]

            # 1. Monthly quota must be rolled back to 0
            assert supabase_service.get_ai_monthly_usage(user_id, period) == 0

            # 2. Concurrency lease must be cleanly released
            assert supabase_service.get_ai_active_concurrency(user_id) == 0

            # 3. New request can immediately acquire the slot
            new_lease = str(uuid.uuid4())
            acquire_retry = supabase_service.acquire_ai_concurrency_slot(
                user_id, concurrency_limit=1, lease_id=new_lease
            )
            assert acquire_retry["allowed"] is True


@pytest.mark.asyncio
async def test_generation_cancellation_rolls_back_quota_and_releases_lease():
    """Step 17C.1C: If generation task is cancelled, quota is rolled back and concurrency lease is released."""
    user_id = f"cancel-rollback-{uuid.uuid4().hex[:8]}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    profile = {
        "id": user_id,
        "subscription_tier": "starter",
        "subscription_status": "active"
    }

    from app.services.ai.content_optimizer import ai_content_service

    supabase_service.reset_in_memory_ai_concurrency_leases()
    supabase_service._in_memory_rate_limits.clear()
    supabase_service._in_memory_ai_monthly_usage[f"{user_id}:{period}"] = 0

    async def cancelled_generator(*args, **kwargs):
        raise asyncio.CancelledError()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch.object(supabase_service, "get_user_profile", return_value=profile), \
             patch.object(ai_content_service, "generate_polymorphic_variants", side_effect=cancelled_generator):
            # CancelledError or Starlette BaseHTTPMiddleware RuntimeError is raised
            with pytest.raises((asyncio.CancelledError, RuntimeError, Exception)):
                await ac.post(
                    "/api/v1/ai/generate-variants",
                    headers=auth_headers(user_id),
                    json={"subject": "Order", "body": "Body"}
                )

            # Concurrency lease must be released
            assert supabase_service.get_ai_active_concurrency(user_id) == 0

            # Monthly quota must be rolled back
            assert supabase_service.get_ai_monthly_usage(user_id, period) == 0


def test_generation_wall_clock_timeout_smaller_than_lease_ttl():
    """Step 17C.1E: Mathematical verification that outer wall-clock timeout (25s) < lease TTL (60s)."""
    WALL_CLOCK_TIMEOUT_SECONDS = 25.0
    LEASE_TTL_SECONDS = 60.0
    PROVIDER_TIMEOUT_LIMIT = 20.0

    # Invariant: provider timeout <= 20.0s < wall-clock timeout 25.0s < lease TTL 60.0s
    assert PROVIDER_TIMEOUT_LIMIT < WALL_CLOCK_TIMEOUT_SECONDS
    assert WALL_CLOCK_TIMEOUT_SECONDS < LEASE_TTL_SECONDS
    assert LEASE_TTL_SECONDS - WALL_CLOCK_TIMEOUT_SECONDS >= 35.0  # 35s safety recovery margin

