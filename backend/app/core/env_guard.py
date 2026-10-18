"""
InboundCheck - Production Runtime Environment Integrity Guard
=============================================================
Fail-fast validation for backend API configurations. Enforces that all
critical production secrets, Supabase endpoints, and Stripe credentials
are present and not containing raw developer placeholders.
"""

from typing import List, Dict, Any, Tuple, Optional
import os
import logging
import urllib.parse
import re

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


def sanitize_exception(exc: Any) -> str:
    """Mask common sensitive patterns in exceptions without leaking secrets."""
    msg = str(exc).strip()
    msg = re.sub(r"(token|key|secret|password|bearer)[=:\s]+[A-Za-z0-9_\-\.]+", r"\1=[REDACTED]", msg, flags=re.IGNORECASE)
    return msg[:500] if len(msg) > 500 else (msg or "Unknown error")


def validate_supabase_url(raw_url: str, is_prod: bool = False) -> Tuple[bool, List[str], str]:
    """
    Validate Supabase URL with strict control character and format enforcement.
    Returns (is_valid: bool, issues: List[str], normalized_url: str).
    """
    issues: List[str] = []
    if not raw_url:
        return False, ["SUPABASE_URL is missing or empty."], ""

    # 1. Reject ASCII control characters (0x00-0x1F, 0x7F) anywhere in raw string (CR, LF, NUL, tabs)
    if any(ord(c) < 32 or ord(c) == 127 for c in raw_url):
        return False, ["SUPABASE_URL contains invalid ASCII control characters (e.g. CR, LF, NUL)."], ""

    # 2. Deliberate outer space normalization (strictly spaces, no embedded control chars)
    normalized_url = raw_url.strip(" ").rstrip("/")

    # 3. Placeholder checks
    if check_is_placeholder(normalized_url):
        issues.append("SUPABASE_URL contains placeholder values.")
        return False, issues, ""

    # 4. Strict URL structure parsing
    try:
        parsed = urllib.parse.urlparse(normalized_url)
    except Exception:
        issues.append("SUPABASE_URL is not a parseable URL.")
        return False, issues, ""

    # 5. Protocol / Scheme checks
    scheme = (parsed.scheme or "").lower()
    if is_prod and scheme != "https":
        issues.append("SUPABASE_URL must use HTTPS in production.")
    elif not is_prod and scheme not in ("http", "https"):
        issues.append("SUPABASE_URL must use http or https protocol.")

    # 6. Host / netloc checks
    host = (parsed.netloc or "").lower()
    if not host:
        issues.append("SUPABASE_URL is missing a valid host.")
    elif "." not in host and host != "localhost":
        issues.append("SUPABASE_URL host is invalid or missing domain suffix.")

    # 7. Disallow query parameters or URL fragments
    if parsed.query or parsed.fragment:
        issues.append("SUPABASE_URL must not contain query parameters or fragments.")

    return len(issues) == 0, issues, normalized_url if len(issues) == 0 else ""


def validate_runtime_environment() -> Tuple[bool, List[str]]:
    """
    Validate backend environment variables.
    Returns (is_valid: bool, issues: List[str]).
    Raises RuntimeError in production if critical security/billing credentials are missing.
    """
    from app.core.config import settings

    issues: List[str] = []
    is_prod = settings.ENVIRONMENT.lower() in ["production", "prod"]

    # 1. Supabase Backend Persistence Checks
    url_valid, url_issues, _ = validate_supabase_url(settings.SUPABASE_URL, is_prod=is_prod)
    issues.extend(url_issues)

    service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    if not service_key or check_is_placeholder(service_key):
        issues.append("SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder.")

    if is_prod:
        if not settings.SUPABASE_JWT_SECRET or check_is_placeholder(settings.SUPABASE_JWT_SECRET):
            issues.append("SUPABASE_JWT_SECRET is required in production for cryptographic JWT verification.")

    # 2. Stripe Live Monetization Checks & Mode Logging
    stripe_key = settings.STRIPE_SECRET_KEY
    if stripe_key and not check_is_placeholder(stripe_key):
        if stripe_key.startswith("sk_live_"):
            logger.info("💳 [STRIPE_STARTUP] Stripe Billing Engine: LIVE_PRODUCTION_MODE (Live Keys Active)")
        elif stripe_key.startswith("sk_test_"):
            logger.info("💳 [STRIPE_STARTUP] Stripe Billing Engine: LIVE_TEST_MODE (Stripe Test Suite Active)")
        else:
            logger.warning(f"💳 [STRIPE_STARTUP] Stripe Billing Engine: UNKNOWN_KEY_PREFIX ({stripe_key[:7]}...)")
    else:
        logger.warning("💳 [STRIPE_STARTUP] Stripe Billing Engine: OFFLINE_FALLBACK (No Stripe Secret Key Detected - Simulation Active)")

    if is_prod:
        if not settings.STRIPE_SECRET_KEY or check_is_placeholder(settings.STRIPE_SECRET_KEY):
            issues.append("STRIPE_SECRET_KEY is required in production and cannot be placeholder.")
        elif not (settings.STRIPE_SECRET_KEY.startswith("sk_live_") or settings.STRIPE_SECRET_KEY.startswith("sk_test_")):
            issues.append("STRIPE_SECRET_KEY does not start with valid 'sk_live_' or 'sk_test_' prefix.")

        if not settings.STRIPE_WEBHOOK_SECRET or check_is_placeholder(settings.STRIPE_WEBHOOK_SECRET):
            issues.append("STRIPE_WEBHOOK_SECRET is required in production for cryptographic webhook verification.")

        for tier_name, price_val in [
            ("STRIPE_PRICE_STARTER", settings.STRIPE_PRICE_STARTER),
            ("STRIPE_PRICE_GROWTH", settings.STRIPE_PRICE_GROWTH),
            ("STRIPE_PRICE_AGENCY", getattr(settings, "STRIPE_PRICE_AGENCY", None)),
        ]:
            if not price_val or not price_val.startswith("price_") or price_val.endswith("_monthly"):
                issues.append(f"{tier_name} is not set to a valid production Stripe price ID (e.g. price_1UFZ...). Found: '{price_val}'")

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


def validate_worker_runtime_environment() -> Tuple[bool, List[str]]:
    """
    Validate environment variables required for dedicated background workers.
    Enforces fail-fast persistence and security integrity without requiring
    unrelated API HTTP/JWT or Stripe monetization keys.

    Returns (is_valid: bool, issues: List[str]).
    Raises RuntimeError in production if critical database credentials are missing.
    """
    from app.core.config import settings

    issues: List[str] = []
    env_clean = (settings.ENVIRONMENT or "").lower()
    is_prod = env_clean in ["production", "prod"]
    is_staging = env_clean == "staging"
    is_enforced = is_prod or is_staging

    # 1. Supabase Backend Persistence Checks
    url_valid, url_issues, _ = validate_supabase_url(settings.SUPABASE_URL, is_prod=is_enforced)
    issues.extend(url_issues)

    # 2. Strict Bidirectional Project Reference Isolation Guard
    if settings.SUPABASE_URL:
        from app.core.staging_guard import PROD_PROJECT_REF
        EXPECTED_STAGING_REF = "wymgyqnqwlliotkxamtd"
        if is_staging and PROD_PROJECT_REF in settings.SUPABASE_URL.lower():
            issues.append(
                f"CRITICAL ISOLATION BREACH: Staging SUPABASE_URL contains production reference '{PROD_PROJECT_REF}'."
            )
        elif is_prod and EXPECTED_STAGING_REF in settings.SUPABASE_URL.lower():
            issues.append(
                f"CRITICAL ISOLATION BREACH: Production SUPABASE_URL contains staging reference '{EXPECTED_STAGING_REF}'."
            )

    # Explicitly require service-role key for background worker cross-tenant RPC operations
    if not settings.SUPABASE_SERVICE_ROLE_KEY or check_is_placeholder(settings.SUPABASE_SERVICE_ROLE_KEY):
        issues.append("SUPABASE_SERVICE_ROLE_KEY is unconfigured or placeholder.")

    is_valid = len(issues) == 0

    if not is_valid:
        msg = "Worker Environment Integrity Issues Detected:\n" + "\n".join([f"  • {i}" for i in issues])
        if is_prod:
            logger.critical(f"FAIL-FAST ABORT: {msg}")
            raise RuntimeError(f"Production Worker Environment Integrity Failure:\n{msg}")
        elif is_staging:
            logger.critical(f"FAIL-FAST ABORT: {msg}")
            raise RuntimeError(f"Staging Worker Environment Integrity Failure:\n{msg}")
        else:
            logger.warning(f"Development Worker Environment Notice:\n{msg}")
    else:
        logger.info(f"Worker environment integrity verified for mode: {settings.ENVIRONMENT}")

    return is_valid, issues


def get_deployment_commit_sha(default: str = "dev") -> str:
    """
    Safely resolve a short (7-char) Git commit SHA from deployment runtime environment.
    Supports Railway's standard RAILWAY_GIT_COMMIT_SHA, generic GIT_COMMIT_SHA, or default fallback.
    Ensures safe formatting and truncation to at most 7 characters.
    """
    raw = (os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA") or "").strip()
    if not raw:
        return default[:7]
    hex_only = re.sub(r"[^a-fA-F0-9]", "", raw)
    if len(hex_only) >= 7:
        return hex_only[:7].lower()
    return raw[:7].lower()


def get_railway_service_name() -> Optional[str]:
    """Retrieve sanitized Railway service name if present in container runtime."""
    raw = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip()
    return raw[:50] if raw else None

