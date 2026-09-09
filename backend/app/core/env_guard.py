"""
InboundCheck - Production Runtime Environment Integrity Guard
=============================================================
Fail-fast validation for backend API configurations. Enforces that all
critical production secrets, Supabase endpoints, and Stripe credentials
are present and not containing raw developer placeholders.
"""

from typing import List, Dict, Any, Tuple
import logging
from app.core.config import settings

logger = logging.getLogger("EnvGuard")

PLACEHOLDER_SUBSTRINGS = [
    "your_",
    "your-project",
    "placeholder",
    "dummy",
    "example",
    "change_me",
]


def check_is_placeholder(val: str) -> bool:
    """Detect if an environment string is an unconfigured placeholder."""
    if not val:
        return True
    lower = str(val).strip().lower()
    return any(p in lower for p in PLACEHOLDER_SUBSTRINGS)


def validate_runtime_environment() -> Tuple[bool, List[str]]:
    """
    Validate backend environment variables.
    Returns (is_valid: bool, issues: List[str]).
    Raises RuntimeError in production if critical security/billing credentials are missing.
    """
    issues: List[str] = []
    is_prod = settings.ENVIRONMENT.lower() in ["production", "prod"]

    # 1. Supabase Backend Persistence Checks
    if not settings.SUPABASE_URL or check_is_placeholder(settings.SUPABASE_URL):
        issues.append("SUPABASE_URL is missing or contains placeholder values.")

    service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    if not service_key or check_is_placeholder(service_key):
        issues.append("SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder.")

    # 2. Stripe Live Monetization Checks
    if is_prod:
        if not settings.STRIPE_SECRET_KEY or check_is_placeholder(settings.STRIPE_SECRET_KEY):
            issues.append("STRIPE_SECRET_KEY is required in production and cannot be placeholder.")
        elif not (settings.STRIPE_SECRET_KEY.startswith("sk_live_") or settings.STRIPE_SECRET_KEY.startswith("sk_test_")):
            issues.append("STRIPE_SECRET_KEY does not start with valid 'sk_live_' or 'sk_test_' prefix.")

        if not settings.STRIPE_WEBHOOK_SECRET or check_is_placeholder(settings.STRIPE_WEBHOOK_SECRET):
            issues.append("STRIPE_WEBHOOK_SECRET is required in production for cryptographic webhook verification.")

    is_valid = len(issues) == 0

    if not is_valid:
        msg = "Backend Environment Integrity Issues Detected:\n" + "\n".join([f"  • {i}" for i in issues])
        if is_prod:
            logger.critical(f"FAIL-FAST ABORT: {msg}")
            raise RuntimeError(f"Production Environment Integrity Failure:\n{msg}")
        else:
            logger.warning(f"Development Environment Notice:\n{msg}")
    else:
        logger.info(f"Environment integrity verified for mode: {settings.ENVIRONMENT}")

    return is_valid, issues
