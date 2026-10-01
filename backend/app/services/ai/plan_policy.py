"""
InboundCheck - AI Subscription Plan Policies & Entitlement Resolution
====================================================================
Defines plan-aware AI policies and provides authoritative, tamper-proof
tier resolution from PostgreSQL public.profiles.

Customer-Facing Plans (3-Tier Commercial Model):
- starter: $9/mo, 1 store/domain, 20 AI runs/mo, 3 req/min, concurrency 1, max_tokens 4000
- growth:  $29/mo, 3 stores/domains, 100 AI runs/mo, 10 req/min, concurrency 2, max_tokens 4000
- agency:  $79/mo, 20 stores/domains, 500 AI runs/mo, 30 req/min, concurrency 5, max_tokens 4000

Legacy Enterprise Transition:
- Enterprise is NO LONGER a customer-facing or internal active plan.
- Server-side profiles containing legacy 'enterprise' resolve safely to 'agency'.

Security Invariant:
Plan resolution is strictly server-governed via authenticated Supabase JWT
and PostgreSQL public.profiles. Client-supplied plan/tier parameters in
request bodies, query strings, or headers are NEVER trusted and cannot elevate privileges.
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import logging
from fastapi import Depends, HTTPException, status

from app.core.security import get_current_user_id
from app.services.supabase_client import supabase_service
from app.core.tier_guards import is_trial_expired

logger = logging.getLogger("AIPlanPolicy")


class AIPlanPolicy(BaseModel):
    """
    Plan-aware AI operational policy definition.
    Defines rate limits, max output tokens, concurrency, and monthly generation quotas.
    """
    model_config = {"frozen": True}

    tier: str = Field(..., description="Subscription plan tier (starter, growth, agency)")
    rate_limit_per_minute: int = Field(..., description="Allowed requests per minute")
    max_tokens: int = Field(..., description="Maximum generation token budget")
    concurrency_limit: int = Field(..., description="Maximum concurrent in-flight generations")
    monthly_generation_limit: int = Field(..., description="Total allowed generations per billing cycle")


# Policy Definitions for InboundCheck Tiers (3-Tier Commercial Model)
PLAN_POLICIES: Dict[str, AIPlanPolicy] = {
    "starter": AIPlanPolicy(
        tier="starter",
        rate_limit_per_minute=3,
        max_tokens=4000,
        concurrency_limit=1,
        monthly_generation_limit=20,
    ),
    "growth": AIPlanPolicy(
        tier="growth",
        rate_limit_per_minute=10,
        max_tokens=4000,
        concurrency_limit=2,
        monthly_generation_limit=100,
    ),
    "agency": AIPlanPolicy(
        tier="agency",
        rate_limit_per_minute=30,
        max_tokens=4000,
        concurrency_limit=5,
        monthly_generation_limit=500,
    ),
}


def resolve_ai_plan(
    user_id: str,
    profile: Optional[Dict[str, Any]] = None,
    enforce_active: bool = False,
) -> AIPlanPolicy:
    """
    Authoritatively resolve the AI entitlement policy for a user based on backend profile.
    
    Security Controls:
    1. NEVER accepts client-supplied plan/tier parameters.
    2. Reads authoritative public.profiles row via Supabase service.
    3. Legacy transition: existing server-side 'enterprise' profiles map safely to 'agency'.
    4. Safely defaults unknown, missing, or malformed tiers to 'starter' (fail-secure).
    5. Handles trial expiration: if enforce_active=True and trial/sub is expired, raises HTTP 402.
    """
    prof = profile
    if prof is None:
        prof = supabase_service.get_user_profile(user_id) or {}

    # Check trial / subscription status if enforcement requested
    sub_status = (prof.get("subscription_status") or "trialing").lower().strip()
    if enforce_active:
        if sub_status == "trialing":
            if is_trial_expired(prof):
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Free trial expired. Upgrade to a paid plan to maintain continuous inbox protection.",
                )
        elif sub_status != "active":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Subscription is {sub_status}. Active plan required to continue.",
            )

    raw_tier = prof.get("subscription_tier") or prof.get("tier") or "starter"
    if not isinstance(raw_tier, str):
        clean_tier = "starter"
    else:
        clean_tier = raw_tier.lower().strip()

    # Controlled legacy transition: existing server-side 'enterprise' profile maps safely to 'agency'
    if clean_tier == "enterprise":
        logger.info(
            f"Legacy 'enterprise' tier detected in profile for user '{user_id}'. "
            "Safely resolving to 'agency' policy."
        )
        clean_tier = "agency"

    # Fail-secure: Map only recognized tiers; unknown/unauthorized tiers safely fall back to 'starter'
    resolved_policy = PLAN_POLICIES.get(clean_tier)
    if resolved_policy is None:
        logger.warning(
            f"Unrecognized subscription tier '{raw_tier}' for user '{user_id}'. "
            "Defaulting safely to 'starter' policy."
        )
        return PLAN_POLICIES["starter"]

    return resolved_policy


async def get_current_ai_policy(
    user_id: str = Depends(get_current_user_id),
) -> AIPlanPolicy:
    """
    FastAPI route dependency: Resolves the authenticated user's authoritative AI plan policy.
    Extracts user_id from the cryptographically verified JWT Bearer token.
    Ignores any client-supplied body, query, or header parameters.
    """
    return resolve_ai_plan(user_id)
