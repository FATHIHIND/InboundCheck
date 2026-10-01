"""
InboundCheck - Structured Generation Result & Usage Contract Tests (Step 17D.2)
==============================================================================
Verifies:
A. Agent Router successful response with usage (prompt_tokens, completion_tokens, total_tokens, provider/model).
B. Agent Router response without usage (generation succeeds, tokens are None, no fabricated zeros).
C. Malformed usage (negative, string, boolean, float - safe parsing, unknown values become None).
D. Provider latency measured via timer.
E. Heuristic fallback contract (provider='heuristic_fallback', model='rule-based-v1', tokens are None).
F. Provider failure fallback behavior preserved.
G. Liquid preservation gate strictly enforced through GenerationResult.
H. No sensitive content leakage (extra forbid, safe repr, zero prompt/secrets exposed).
I. Backwards-compatible container semantics (__iter__, __len__, __getitem__, __eq__).
"""

import pytest
import json
import uuid
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from pydantic import SecretStr, ValidationError

from app.services.ai.provider import (
    GenerationResult,
    BaseLLMProvider,
    AgentRouterLLMProvider,
    HeuristicFallbackProvider,
    DisabledLLMProvider,
    LLMProviderConfig,
    LLMProviderNotConfiguredError,
    LLMGenerationError,
)
from app.services.ai.content_optimizer import AIContentOptimizer, ai_content_service


# =============================================================================
# Helper Fixtures & Mock Responses
# =============================================================================

def make_valid_agent_router_json_payload(usage: dict | None = None) -> dict:
    payload = {
        "id": "gen-test-12345",
        "model": "google/gemma-4-26b-a4b-it",
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "variants": [
                            {
                                "variant_id": "v1_professional",
                                "variant_name": "Professional Transactional",
                                "subject": "Order update for {{ order.name }}",
                                "body_html": "<p>Hello {{ customer.first_name }}, your order {{ order.name }} is confirmed.</p>",
                                "estimated_spam_risk": 2,
                                "rationale": "Neutral tone."
                            }
                        ]
                    })
                }
            }
        ]
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


# =============================================================================
# Test A: Agent Router Successful Response with Usage
# =============================================================================

@pytest.mark.asyncio
async def test_agent_router_successful_response_with_usage():
    """Verify usage tokens and provider metadata extracted cleanly from provider payload."""
    raw_payload = make_valid_agent_router_json_payload(usage={
        "prompt_tokens": 128,
        "completion_tokens": 256,
        "total_tokens": 384,
    })

    mock_response = httpx.Response(status_code=200, json=raw_payload)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    config = LLMProviderConfig(
        provider_name="agent_router",
        model_name="google/gemma-4-26b-a4b-it",
        api_base="https://openrouter.ai/api/v1",
        api_key=SecretStr("sk-mock-key"),
        enabled=True,
    )
    provider = AgentRouterLLMProvider(config=config, http_client=mock_client)

    result = await provider.generate_variants(
        subject="Order {{ order.name }}",
        body_content="Hello {{ customer.first_name }}",
        count=1,
    )

    assert isinstance(result, GenerationResult)
    assert result.provider == "agent_router"
    assert result.model == "google/gemma-4-26b-a4b-it"
    assert result.prompt_tokens == 128
    assert result.completion_tokens == 256
    assert result.total_tokens == 384
    assert result.provider_latency_ms is not None
    assert result.provider_latency_ms >= 0
    assert len(result.variants) == 1
    assert result.variants[0]["variant_id"] == "v1_professional"


# =============================================================================
# Test B: Agent Router Response Without Usage
# =============================================================================

@pytest.mark.asyncio
async def test_agent_router_response_without_usage():
    """Verify generation succeeds when usage is omitted; tokens must be None (never fabricated zero)."""
    raw_payload = make_valid_agent_router_json_payload(usage=None)

    mock_response = httpx.Response(status_code=200, json=raw_payload)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    config = LLMProviderConfig(
        provider_name="agent_router",
        model_name="google/gemma-4-26b-a4b-it",
        api_base="https://openrouter.ai/api/v1",
        api_key=SecretStr("sk-mock-key"),
        enabled=True,
    )
    provider = AgentRouterLLMProvider(config=config, http_client=mock_client)

    result = await provider.generate_variants(
        subject="Order {{ order.name }}",
        body_content="Hello {{ customer.first_name }}",
        count=1,
    )

    assert isinstance(result, GenerationResult)
    assert len(result.variants) == 1
    # Tokens must remain None, not fabricated 0
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.total_tokens is None


# =============================================================================
# Test C: Malformed Usage Handling
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_usage", [
    {"prompt_tokens": -10, "completion_tokens": 50, "total_tokens": 40},
    {"prompt_tokens": "one_hundred", "completion_tokens": 200},
    {"prompt_tokens": True, "completion_tokens": False},  # Booleans must not coerce to 1 / 0
    {"prompt_tokens": 12.5, "completion_tokens": 44.2},
    "not_a_dict_at_all",
    None,
])
async def test_agent_router_malformed_usage_fails_safely(bad_usage):
    """Verify malformed or invalid usage fields never crash generation; invalid values become None."""
    raw_payload = make_valid_agent_router_json_payload()
    if bad_usage is not None:
        raw_payload["usage"] = bad_usage

    mock_response = httpx.Response(status_code=200, json=raw_payload)
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    config = LLMProviderConfig(
        provider_name="agent_router",
        model_name="google/gemma-4-26b-a4b-it",
        api_base="https://openrouter.ai/api/v1",
        api_key=SecretStr("sk-mock-key"),
        enabled=True,
    )
    provider = AgentRouterLLMProvider(config=config, http_client=mock_client)

    result = await provider.generate_variants(
        subject="Order {{ order.name }}",
        body_content="Hello {{ customer.first_name }}",
        count=1,
    )

    assert isinstance(result, GenerationResult)
    assert len(result.variants) == 1
    # Invalid token types/values must not crash or store negative/boolean values
    if isinstance(bad_usage, dict):
        if not isinstance(bad_usage.get("prompt_tokens"), int) or isinstance(bad_usage.get("prompt_tokens"), bool) or bad_usage.get("prompt_tokens") < 0:
            assert result.prompt_tokens is None


# =============================================================================
# Test D: Provider Latency Measurement
# =============================================================================

@pytest.mark.asyncio
async def test_provider_latency_measured_separately():
    """Verify provider latency measures network dispatch duration."""
    raw_payload = make_valid_agent_router_json_payload()

    async def delayed_post(*args, **kwargs):
        await asyncio.sleep(0.05)  # 50ms simulated provider network latency
        return httpx.Response(status_code=200, json=raw_payload)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=delayed_post)

    config = LLMProviderConfig(
        provider_name="agent_router",
        model_name="google/gemma-4-26b-a4b-it",
        api_base="https://openrouter.ai/api/v1",
        api_key=SecretStr("sk-mock-key"),
        enabled=True,
    )
    provider = AgentRouterLLMProvider(config=config, http_client=mock_client)

    result = await provider.generate_variants("Subject", "Body", count=1)
    assert result.provider_latency_ms is not None
    assert result.provider_latency_ms >= 40  # Bound checks 50ms sleep


# =============================================================================
# Test E: Heuristic Fallback Provider Contract
# =============================================================================

@pytest.mark.asyncio
async def test_heuristic_fallback_contract():
    """Verify HeuristicFallbackProvider returns GenerationResult with expected constants and None tokens."""
    provider = HeuristicFallbackProvider()
    result = await provider.generate_variants("Subject {{ order.name }}", "Body {{ customer.first_name }}")

    assert isinstance(result, GenerationResult)
    assert result.provider == "heuristic_fallback"
    assert result.model == "rule-based-v1"
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.total_tokens is None
    assert result.provider_latency_ms is not None
    assert len(result.variants) == 3


# =============================================================================
# Test F: Provider Failure and Fallback Semantics
# =============================================================================

@pytest.mark.asyncio
async def test_disabled_provider_fails_closed():
    """Verify DisabledLLMProvider fails closed with LLMProviderNotConfiguredError."""
    disabled = DisabledLLMProvider(provider_name="disabled_test")
    with pytest.raises(LLMProviderNotConfiguredError):
        await disabled.generate_variants("Subject", "Body")


@pytest.mark.asyncio
async def test_content_optimizer_fallback_returns_generation_result():
    """Verify content optimizer safely catches provider error and returns heuristic GenerationResult."""
    failing_provider = MagicMock(spec=BaseLLMProvider)
    failing_provider.provider_name = "failing_router"
    failing_provider.generate_variants = AsyncMock(side_effect=LLMGenerationError("Upstream 502"))

    optimizer = AIContentOptimizer(provider=failing_provider)
    result = await optimizer.generate_polymorphic_variants_result(
        subject="Order {{ order.name }}",
        body_content="Hello {{ customer.first_name }}",
    )

    assert isinstance(result, GenerationResult)
    assert result.provider == "heuristic_fallback"
    assert result.model == "rule-based-v1"
    assert result.prompt_tokens is None
    assert len(result.variants) >= 1


# =============================================================================
# Test G: Liquid Preservation Gate with GenerationResult
# =============================================================================

@pytest.mark.asyncio
async def test_liquid_preservation_gate_filters_variants_in_generation_result():
    """Verify that corrupt Liquid variants are dropped while preserving metadata on valid variants."""
    corrupted_variants = [
        {
            "variant_id": "v1_valid",
            "variant_name": "Valid Variant",
            "subject": "Order {{ order.name }}",
            "body_html": "<p>Order {{ order.name }} confirmed for {{ customer.first_name }}.</p>",
            "estimated_spam_risk": 1,
            "rationale": "Clear copy"
        },
        {
            "variant_id": "v2_corrupted",
            "variant_name": "Corrupted Variant",
            "subject": "Missing tags",
            "body_html": "<p>Your order has been confirmed.</p>",  # Missing both Liquid tags!
            "estimated_spam_risk": 1,
            "rationale": "Bad copy"
        }
    ]

    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "agent_router"
    mock_provider.generate_variants = AsyncMock(return_value=GenerationResult(
        variants=corrupted_variants,
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=150,
        completion_tokens=300,
        total_tokens=450,
        provider_latency_ms=620,
    ))

    optimizer = AIContentOptimizer(provider=mock_provider)
    result = await optimizer.generate_polymorphic_variants_result(
        subject="Receipt {{ order.name }}",
        body_content="Hello {{ customer.first_name }}, order {{ order.name }}",
    )

    # v2 must be filtered out, leaving only v1
    assert len(result.variants) == 1
    assert result.variants[0]["variant_id"] == "v1_valid"
    # Metadata is preserved
    assert result.provider == "agent_router"
    assert result.model == "google/gemma-4-26b-a4b-it"
    assert result.prompt_tokens == 150
    assert result.completion_tokens == 300
    assert result.total_tokens == 450


# =============================================================================
# Test H: Data Minimization & No Sensitive Leakage
# =============================================================================

def test_generation_result_forbids_extra_fields():
    """Verify GenerationResult refuses extra unvetted fields (strict schema boundary)."""
    with pytest.raises(ValidationError):
        GenerationResult(
            variants=[],
            provider="agent_router",
            model="google/gemma-4-26b-a4b-it",
            raw_prompt="Secret merchant prompt",  # Must be rejected!
        )


def test_generation_result_repr_sanitization():
    """Verify __repr__ does not output variants content or prompt strings."""
    result = GenerationResult(
        variants=[{"variant_id": "v1", "body_html": "<p>Sensitive merchant copy</p>"}],
        provider="agent_router",
        model="google/gemma-4-26b-a4b-it",
        prompt_tokens=100,
    )
    repr_str = repr(result)
    assert "Sensitive merchant copy" not in repr_str
    assert "variants_count=1" in repr_str
    assert "provider='agent_router'" in repr_str


# =============================================================================
# Test I: Container / Sequence Backwards-Compatibility
# =============================================================================

def test_generation_result_sequence_compatibility():
    """Verify GenerationResult behaves like a list of variants for backwards compatibility."""
    var1 = {"variant_id": "v1", "subject": "S1"}
    var2 = {"variant_id": "v2", "subject": "S2"}

    result = GenerationResult(
        variants=[var1, var2],
        provider="heuristic_fallback",
        model="rule-based-v1",
    )

    # __len__
    assert len(result) == 2

    # __getitem__
    assert result[0] == var1
    assert result[1] == var2

    # __iter__
    items = [v["variant_id"] for v in result]
    assert items == ["v1", "v2"]

    # __contains__
    assert var1 in result

    # __bool__
    assert bool(result) is True
    empty_result = GenerationResult(variants=[], provider="test", model="test")
    assert bool(empty_result) is False

    # list equality
    assert result == [var1, var2]
    assert empty_result == []
