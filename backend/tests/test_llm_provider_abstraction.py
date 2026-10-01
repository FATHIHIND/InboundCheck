"""
InboundCheck - LLM Provider Abstraction & Security Tests (Phase 2.4B Step 4)
============================================================================
Verifies:
1. Provider configuration contract (LLMProviderConfig) with SecretStr credential shielding.
2. Provider abstraction instantiation through AIContentOptimizer service layer.
3. Zero network calls made during polymorphic candidate generation.
4. Client cannot supply credentials, select providers, or control configuration (HTTP 422).
5. Missing or disabled provider fails safely without leaking secrets.
6. Safe service-layer fallback when active provider is disabled/unconfigured.
7. Liquid preservation gate strictly enforced after candidate generation.
8. Backward compatibility with existing AI endpoints and response contracts.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pydantic import SecretStr
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai.provider import (
    BaseLLMProvider,
    HeuristicFallbackProvider,
    DisabledLLMProvider,
    LLMProviderConfig,
    LLMProviderError,
    LLMProviderNotConfiguredError,
    get_llm_provider,
)
from app.services.ai.content_optimizer import AIContentOptimizer, ai_content_service
from app.services.supabase_client import supabase_service
from app.core.config import settings
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("test-llm-user-1"))


# =============================================================================
# 1. Configuration Contract & Credential Shielding Tests
# =============================================================================

def test_provider_config_secret_masking():
    """Verify that API keys in LLMProviderConfig are shielded as SecretStr and not leaked."""
    secret_value = "sk-super-secret-key-9876543210"
    config = LLMProviderConfig(
        provider_name="test_provider",
        model_name="test-model-v1",
        api_base="https://api.testprovider.com/v1",
        api_key=SecretStr(secret_value),
        enabled=True,
    )

    # 1. Secret must not appear in string representation or repr
    repr_str = repr(config)
    assert secret_value not in repr_str
    assert "api_key=***" in repr_str

    # 2. safe_summary must exclude the raw secret and only expose a boolean flag
    summary = config.safe_summary()
    assert summary["has_api_key"] is True
    assert "api_key" not in summary
    assert secret_value not in str(summary)

    # 3. Raw secret retrieval only via get_secret_value()
    assert config.api_key.get_secret_value() == secret_value


def test_provider_config_defaults_and_validation():
    """Verify default values and bounds on provider configuration."""
    config = LLMProviderConfig()
    assert config.provider_name == "heuristic_fallback"
    assert config.enabled is False
    assert config.api_key is None
    assert config.timeout_seconds == 10.0
    assert config.max_tokens == 1000
    assert config.temperature == 0.7


# =============================================================================
# 2. Provider Abstraction & Factory Instantiation Tests
# =============================================================================

def test_provider_instantiation_through_service_layer():
    """Verify that BaseLLMProvider can be instantiated and wired through AIContentOptimizer."""
    fallback = HeuristicFallbackProvider()
    service = AIContentOptimizer(provider=fallback)

    assert isinstance(service.provider, BaseLLMProvider)
    assert service.provider.provider_name == "heuristic_fallback"
    assert service.provider.is_available is True


def test_provider_factory_resolution():
    """Verify server-side get_llm_provider factory handles registered and unconfigured providers."""
    # 1. Default heuristic provider
    p1 = get_llm_provider("heuristic_fallback")
    assert isinstance(p1, HeuristicFallbackProvider)
    assert p1.is_available is True

    # 2. Unconfigured provider returns DisabledLLMProvider
    p2 = get_llm_provider("moonshot")
    assert isinstance(p2, DisabledLLMProvider)
    assert p2.is_available is False

    # 3. Unknown provider returns DisabledLLMProvider
    p3 = get_llm_provider("non_existent_provider_xyz")
    assert isinstance(p3, DisabledLLMProvider)
    assert p3.is_available is False


# =============================================================================
# 3. Zero Network Calls Verification
# =============================================================================

@pytest.mark.asyncio
async def test_zero_network_calls_during_generation():
    """
    Verify that polymorphic variant generation executes completely offline when
    the HeuristicFallbackProvider is explicitly injected.
    This test is provider-routing-agnostic: it uses explicit injection so that
    AGENT_ROUTER_ENABLED in settings has no effect on the assertion.
    """
    # Explicitly inject HeuristicFallbackProvider to ensure offline-only execution
    service = AIContentOptimizer(provider=HeuristicFallbackProvider())

    with patch("httpx.AsyncClient") as mock_client:
        variants = await service.generate_polymorphic_variants(
            subject="Order #{{ order.name }} confirmed",
            body_content="<p>Hi {{ customer.first_name }}, your order #{{ order.name }} is ready.</p>"
        )

        # Assert no HTTP client was ever instantiated or called
        mock_client.assert_not_called()
        assert len(variants) == 3


# =============================================================================
# 4. Security: Provider Configuration is NOT Client-Controlled (HTTP 422)
# =============================================================================

def test_client_cannot_inject_provider():
    """Verify that client passing 'provider' field is rejected with HTTP 422."""
    res = client.post(
        "/api/v1/ai/generate-polymorphic-variants",
        json={
            "subject": "Order Confirmation",
            "body": "<p>Thank you for your order!</p>",
            "provider": "openai",
        }
    )
    assert res.status_code == 422
    assert "extra_forbidden" in str(res.json())


def test_client_cannot_inject_api_key():
    """Verify that client passing 'api_key' field is rejected with HTTP 422."""
    res = client.post(
        "/api/v1/ai/generate-variants",
        json={
            "subject": "Order Confirmation",
            "body": "<p>Thank you for your order!</p>",
            "api_key": "sk-injected-credential-12345",
        }
    )
    assert res.status_code == 422
    assert "extra_forbidden" in str(res.json())


def test_client_cannot_inject_model():
    """Verify that client passing 'model' or 'model_name' field is rejected with HTTP 422."""
    res = client.post(
        "/api/v1/ai/generate-variants",
        json={
            "subject": "Order Confirmation",
            "body": "<p>Thank you for your order!</p>",
            "model": "gpt-4-turbo",
        }
    )
    assert res.status_code == 422
    assert "extra_forbidden" in str(res.json())


# =============================================================================
# 5. Missing / Disabled Provider Fails Safely
# =============================================================================

@pytest.mark.asyncio
async def test_disabled_provider_raises_not_configured_error():
    """Verify that invoking a disabled provider directly raises LLMProviderNotConfiguredError."""
    disabled = DisabledLLMProvider(
        provider_name="future_provider",
        reason="No network calls permitted in Phase 2.4B Step 4"
    )

    with pytest.raises(LLMProviderNotConfiguredError) as exc_info:
        await disabled.generate_variants(
            subject="Order update",
            body_content="<p>Test</p>"
        )

    err_msg = str(exc_info.value)
    assert "future_provider" in err_msg
    assert "not configured or disabled" in err_msg
    # Ensure no credentials appear in error message
    assert "sk-" not in err_msg
    assert "token" not in err_msg.lower()


@pytest.mark.asyncio
async def test_service_layer_falls_back_safely_when_provider_disabled():
    """
    Verify that AIContentOptimizer gracefully catches LLMProviderNotConfiguredError
    and falls back to deterministic heuristic generation without breaking.
    """
    disabled = DisabledLLMProvider(provider_name="offline_engine")
    service = AIContentOptimizer(provider=disabled)

    variants = await service.generate_polymorphic_variants(
        subject="Order #{{ order.name }} confirmed",
        body_content="<p>Hi {{ customer.first_name }}, your order #{{ order.name }} has shipped.</p>"
    )

    # Must safely produce the 3 fallback candidates and pass Liquid preservation
    assert len(variants) == 3
    assert all("variant_id" in v for v in variants)


# =============================================================================
# 6. Liquid Preservation Gate Runs Strictly AFTER Candidate Generation
# =============================================================================

class MockCorruptingProvider(BaseLLMProvider):
    """Test double simulating a provider that corrupts Liquid tags."""

    @property
    def provider_name(self) -> str:
        return "mock_corrupting"

    @property
    def is_available(self) -> bool:
        return True

    async def generate_variants(self, subject: str, body_content: str, count: int = 3, **kwargs):
        return [
            {
                "variant_id": "v_corrupt",
                "variant_name": "Corrupted Tag Variant",
                "subject": "Receipt",
                "body_html": "<p>Order #[ORDER_NUMBER] is confirmed.</p>",  # Liquid {{ order.name }} stripped!
                "estimated_spam_risk": 1,
                "rationale": "Corrupted tag."
            }
        ]


@pytest.mark.asyncio
async def test_liquid_preservation_gate_filters_provider_output():
    """Verify that any candidate produced by an external provider is filtered out if Liquid tags are missing."""
    service = AIContentOptimizer(provider=MockCorruptingProvider())

    variants = await service.generate_polymorphic_variants(
        subject="Order #{{ order.name }}",
        body_content="<p>Your order #{{ order.name }} is confirmed.</p>"
    )

    # Liquid preservation gate must reject the corrupt candidate and return empty list
    assert variants == []


# =============================================================================
# 7. Endpoint Backward Compatibility & Contract Preservation
# =============================================================================

def test_api_endpoint_backward_compatibility():
    """Verify that both polymorphic endpoints maintain their existing response format."""
    growth_profile = {"id": "test-llm-user-1", "subscription_tier": "growth", "subscription_status": "active"}
    with patch.object(supabase_service, "get_user_profile", return_value=growth_profile):
        for endpoint in ("/api/v1/ai/generate-polymorphic-variants", "/api/v1/ai/generate-variants"):
            res = client.post(
                endpoint,
                json={
                    "subject": "Order #1234 confirmed",
                    "body": "<p>Hello {{ customer.first_name }}, your order #{{ order.name }} is confirmed.</p>"
                }
            )
            assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "variants" in data
        assert len(data["variants"]) == 3

        # Verify variant dictionary structure
        first_variant = data["variants"][0]
        assert "variant_id" in first_variant
        assert "variant_name" in first_variant
        assert "subject" in first_variant
        assert "body_html" in first_variant
        assert "estimated_spam_risk" in first_variant
        assert "rationale" in first_variant


# =============================================================================
# 8. Provider-Routing Invariant Regression Tests (Phase 2.4B Step 9D)
# =============================================================================

def test_content_optimizer_resolves_agent_router_when_enabled():
    """
    TEST 1 — AGENT_ROUTER_ENABLED=true with no explicit provider
    => provider property must resolve to AgentRouterLLMProvider.
    """
    from app.services.ai.provider import AgentRouterLLMProvider

    # Temporarily override AGENT_ROUTER_ENABLED on settings object
    original = settings.AGENT_ROUTER_ENABLED
    try:
        settings.AGENT_ROUTER_ENABLED = True
        service = AIContentOptimizer()  # no explicit provider
        resolved = service.provider
        assert isinstance(resolved, AgentRouterLLMProvider), (
            f"Expected AgentRouterLLMProvider when AGENT_ROUTER_ENABLED=True, "
            f"got {type(resolved).__name__}"
        )
    finally:
        settings.AGENT_ROUTER_ENABLED = original


def test_content_optimizer_resolves_heuristic_fallback_when_disabled():
    """
    TEST 2 — AGENT_ROUTER_ENABLED=false with no explicit provider
    => provider property must resolve to HeuristicFallbackProvider.
    """
    original = settings.AGENT_ROUTER_ENABLED
    try:
        settings.AGENT_ROUTER_ENABLED = False
        service = AIContentOptimizer()  # no explicit provider
        resolved = service.provider
        assert isinstance(resolved, HeuristicFallbackProvider), (
            f"Expected HeuristicFallbackProvider when AGENT_ROUTER_ENABLED=False, "
            f"got {type(resolved).__name__}"
        )
    finally:
        settings.AGENT_ROUTER_ENABLED = original


def test_content_optimizer_preserves_explicit_provider_injection():
    """
    TEST 3 — Explicit provider injection must be preserved regardless of AGENT_ROUTER_ENABLED.
    Critical for tests and dependency injection.
    """
    from app.services.ai.provider import AgentRouterLLMProvider

    injected = HeuristicFallbackProvider()
    original = settings.AGENT_ROUTER_ENABLED
    try:
        # Even with AGENT_ROUTER_ENABLED=True, explicit injection must win
        settings.AGENT_ROUTER_ENABLED = True
        service = AIContentOptimizer(provider=injected)
        resolved = service.provider
        assert resolved is injected, (
            "Explicit provider injection must be preserved; "
            f"AGENT_ROUTER_ENABLED=True must NOT override it. Got: {type(resolved).__name__}"
        )
        assert isinstance(resolved, HeuristicFallbackProvider)
        assert not isinstance(resolved, AgentRouterLLMProvider)
    finally:
        settings.AGENT_ROUTER_ENABLED = original


@pytest.mark.asyncio
async def test_content_optimizer_fallback_when_agent_router_fails():
    """
    TEST 4 — When agent_router provider fails with LLMGenerationError,
    generate_polymorphic_variants must fall back to HeuristicFallbackProvider
    and still return 3 valid candidates.
    """
    from app.services.ai.provider import LLMGenerationError

    class _FailingProvider(BaseLLMProvider):
        """Simulates an AgentRouter that raises LLMGenerationError."""
        @property
        def provider_name(self) -> str:
            return "failing_agent_router"

        @property
        def is_available(self) -> bool:
            return True

        async def generate_variants(self, subject: str, body_content: str, count: int = 3, **kwargs):
            raise LLMGenerationError("Simulated network timeout from agent router")

    service = AIContentOptimizer(provider=_FailingProvider())
    variants = await service.generate_polymorphic_variants(
        subject="Order #{{ order.name }} confirmed",
        body_content="<p>Hi {{ customer.first_name }}, your order #{{ order.name }} is confirmed.</p>"
    )

    # Fallback must recover and produce 3 valid, Liquid-preserving candidates
    assert len(variants) == 3, (
        f"Expected 3 fallback candidates after agent_router failure, got {len(variants)}"
    )
    for v in variants:
        assert "{{ order.name }}" in v["body_html"]
        assert "{{ customer.first_name }}" in v["body_html"]


@pytest.mark.asyncio
async def test_content_optimizer_liquid_gate_still_works_with_agent_router():
    """
    TEST 5 — Liquid preservation gate must still reject variants that corrupt
    Liquid tags regardless of which provider is active.
    Uses an explicit MockCorruptingProvider (no real HTTP call).
    """
    class _CorruptingProvider(BaseLLMProvider):
        """Returns a candidate that strips a Liquid tag."""
        @property
        def provider_name(self) -> str:
            return "corrupting_provider"

        @property
        def is_available(self) -> bool:
            return True

        async def generate_variants(self, subject: str, body_content: str, count: int = 3, **kwargs):
            return [
                {
                    "variant_id": "v1_corrupted",
                    "variant_name": "Corrupted",
                    "subject": "Order receipt",
                    # Liquid {{ order.name }} intentionally stripped
                    "body_html": "<p>Hi {{ customer.first_name }}, your order is confirmed.</p>",
                    "estimated_spam_risk": 1,
                    "rationale": "Tag removed.",
                }
            ]

    original = settings.AGENT_ROUTER_ENABLED
    try:
        settings.AGENT_ROUTER_ENABLED = True
        service = AIContentOptimizer(provider=_CorruptingProvider())
        variants = await service.generate_polymorphic_variants(
            subject="Order #{{ order.name }} confirmed",
            body_content="<p>Hi {{ customer.first_name }}, your order #{{ order.name }} is ready.</p>"
        )
        # Liquid gate must reject the corrupted candidate — variants must be empty
        assert variants == [], (
            f"Expected Liquid gate to reject all corrupted variants; got {len(variants)} variants"
        )
    finally:
        settings.AGENT_ROUTER_ENABLED = original
