"""
InboundCheck - Monetization & Tier Enforcement Guards
=====================================================
Enforces 3-day free trial boundaries, domain limits, and feature gating:
- Starter: 1 domain, manual DNS snippets.
- Growth: 3 domains, SPF Merge Engine, 1-Click DNS Auto-Fix, 48-72h Risk Forecast.
- Enterprise: Unlimited domains, Developer API keys, real-time worker priority.
"""

from typing import Dict, Any, Optional, Union
from datetime import datetime, timezone
import logging
from fastapi import Depends, HTTPException, status

from app.core.security import get_current_user_id
from app.services.supabase_client import supabase_service

logger = logging.getLogger("TierGuards")

TIER_DOMAIN_LIMITS = {
    "starter": 1,
    "growth": 3,
    "enterprise": 999,
}


def parse_utc_datetime(dt_val: Union[str, datetime, None]) -> Optional[datetime]:
    """Parse string or datetime to timezone-aware UTC datetime."""
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    try:
        # Handle ISO strings (e.g. 2026-09-15T12:00:00Z or with offset)
        clean = dt_val.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{dt_val}': {e}")
        return None


def is_trial_expired(profile: Dict[str, Any]) -> bool:
    """Check if the 3-day free trial has expired."""
    trial_ends_at_val = profile.get("trial_ends_at")
    dt = parse_utc_datetime(trial_ends_at_val)
    if not dt:
        return False
    return datetime.now(timezone.utc) > dt


async def verify_active_subscription_or_trial(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Enforce active subscription or valid 3-day free trial.
    If subscription_status == 'trialing' and NOW() > trial_ends_at:
      - Automatically marks status as 'expired'
      - Returns HTTP 402 (Payment Required)
    """
    profile = supabase_service.get_user_profile(user_id)
    if not profile:
        profile = {
            "id": user_id,
            "subscription_tier": "starter",
            "tier": "starter",
            "subscription_status": "trialing",
        }

    sub_status = (profile.get("subscription_status") or "trialing").lower()

    if sub_status == "trialing":
        if is_trial_expired(profile):
            supabase_service.update_user_profile(
                user_id,
                {
                    "subscription_status": "expired",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Free trial expired. Upgrade to a paid plan to maintain continuous inbox protection.",
            )
        return profile

    if sub_status == "active":
        return profile

    if sub_status in ("expired", "past_due", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Subscription is {sub_status}. Active plan required to continue.",
        )

    return profile


def enforce_domain_quota(user_id: str, profile: Optional[Dict[str, Any]] = None) -> None:
    """
    Enforce domain quota caps:
    - Starter: 1 domain
    - Growth: 3 domains
    - Enterprise: 999 (unlimited)
    """
    prof = profile or supabase_service.get_user_profile(user_id) or {}
    tier = (prof.get("subscription_tier") or prof.get("tier") or "starter").lower()
    quota_limit = TIER_DOMAIN_LIMITS.get(tier, 1)

    existing_count = supabase_service.get_user_domain_count(user_id)
    if existing_count >= quota_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Domain quota reached ({existing_count}/{quota_limit}) for '{tier.capitalize()}' tier. Upgrade to add more domains.",
        )


async def require_growth_or_enterprise_tier(
    profile: Dict[str, Any] = Depends(verify_active_subscription_or_trial),
) -> Dict[str, Any]:
    """
    Gates advanced features (SPF Merge Engine, 1-Click DNS Auto-Fix)
    to Growth and Enterprise tiers.
    Throws HTTP 403 UPGRADE_REQUIRED for Starter users when trial is over.
    """
    tier = (profile.get("subscription_tier") or profile.get("tier") or "starter").lower()
    sub_status = (profile.get("subscription_status") or "trialing").lower()

    if tier == "starter":
        # If user is on trial and trial is not expired, allow trial preview;
        # otherwise throw HTTP 403 UPGRADE_REQUIRED.
        if sub_status != "trialing" or is_trial_expired(profile):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="UPGRADE_REQUIRED: 1-Click DNS Auto-Fix and SPF Merge Engine require a Growth or Enterprise subscription.",
            )

    return profile
