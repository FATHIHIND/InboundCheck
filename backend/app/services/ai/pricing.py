"""
InboundCheck - AI Generation Pricing Registry & Cost Resolution (Phase 17D)
========================================================================
Server-side versioned pricing registry for calculating AI generation cost.
Provides integer-arithmetic micro-USD cost resolution and status tracking.

Cost Status Semantics:
- 'calculated': Computed from authoritative server-side token rates.
- 'reported': Provider-reported cost (only if explicitly supplied).
- 'zero_cost': Deterministic rule-based or zero-rate model/provider.
- 'unreported': Missing/unparseable usage tokens or unmapped paid model.

Constraints:
- micro_usd integer precision: 1 USD = 1,000,000 micro-USD.
- Ceiling division prevents fractional undercounting on small requests.
- No client-side pricing discovery or external network calls.
"""

from typing import Dict, Any, Optional, Tuple

# Versioned registry of token pricing per 1,000,000 tokens (in micro-USD)
# 1 USD = 1,000,000 micro-USD ($0.27 / 1M = 270,000 micro-USD)
MODEL_PRICING_V1: Dict[str, Dict[str, int]] = {
    # Active production model (OpenRouter Google Gemma 4 26B)
    "google/gemma-4-26b-a4b-it": {
        "prompt_micro_usd_per_1m": 270_000,
        "completion_micro_usd_per_1m": 270_000,
    },
    # Development / test default model
    "moonshot-v1-8k": {
        "prompt_micro_usd_per_1m": 12_000_000,
        "completion_micro_usd_per_1m": 12_000_000,
    },
    # Deterministic heuristic fallback (zero cost)
    "rule-based-v1": {
        "prompt_micro_usd_per_1m": 0,
        "completion_micro_usd_per_1m": 0,
    },
}

ZERO_COST_PROVIDERS = {"heuristic_fallback"}
ZERO_COST_MODELS = {"rule-based-v1"}


def resolve_cost(
    model: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    provider: Optional[str] = None,
) -> Tuple[Optional[int], str]:
    """
    Resolve integer micro-USD cost and cost_status according to Phase 17D invariants.

    Returns:
        (cost_micro_usd, cost_status)
        - cost_status in ('calculated', 'reported', 'zero_cost', 'unreported')
        - logical consistency:
            'unreported' -> cost_micro_usd is None
            'zero_cost'   -> cost_micro_usd == 0
            'calculated'  -> cost_micro_usd is not None (>= 0)
    """
    # 1. Deterministic zero-cost providers / models
    clean_provider = (provider or "").strip().lower()
    clean_model = (model or "").strip()

    if clean_provider in ZERO_COST_PROVIDERS or clean_model in ZERO_COST_MODELS:
        return 0, "zero_cost"

    # 2. If token counts are missing, unparseable, or negative -> unreported
    if prompt_tokens is None or completion_tokens is None:
        return None, "unreported"

    if prompt_tokens < 0 or completion_tokens < 0:
        return None, "unreported"

    # 3. Model lookup in authoritative pricing registry
    rates = MODEL_PRICING_V1.get(clean_model)
    if not rates:
        return None, "unreported"

    p_rate = rates.get("prompt_micro_usd_per_1m", 0)
    c_rate = rates.get("completion_micro_usd_per_1m", 0)

    # 4. Zero-rate model check
    if p_rate == 0 and c_rate == 0:
        return 0, "zero_cost"

    # 5. Integer ceiling division calculation
    # prompt_cost = ceil(prompt_tokens * p_rate / 1_000_000)
    prompt_cost = (prompt_tokens * p_rate + 999_999) // 1_000_000 if prompt_tokens > 0 else 0
    completion_cost = (completion_tokens * c_rate + 999_999) // 1_000_000 if completion_tokens > 0 else 0
    total_cost_micro_usd = prompt_cost + completion_cost

    return total_cost_micro_usd, "calculated"
