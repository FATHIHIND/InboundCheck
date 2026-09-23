"""
InboundCheck - Production Rate Limiting & Trusted Proxy Engine (Phase 2.1)
========================================================================
Implements:
1. Hardened reverse proxy IP resolution with anti-spoofing defense.
2. Identity-aware rate limiting (user ID, endpoint, domain).
3. Distributed multi-instance rate limiting via PostgreSQL windows.
4. Differentiated failure policy:
   - Low-cost endpoints: bounded in-memory fallback.
   - High-cost endpoints (AI/DNS/RBL): conservative local fallback with fail-closed enforcement.
"""

import ipaddress
import logging
import os
import time
from typing import Optional, Set, Tuple, Dict, Any
from fastapi import Request, HTTPException, status, Depends

from app.core.config import settings
from app.core.security import get_current_user_id
from app.services.supabase_client import supabase_service

logger = logging.getLogger("RateLimiter")

# Local conservative in-memory fallback stores when DB is unreachable
_FALLBACK_STORES: Dict[str, Dict[str, int]] = {
    "ai": {},
    "dns": {},
    "rbl": {},
    "manual_audit": {},
}


def get_trusted_proxy_sources() -> Tuple[Set[str], list]:
    """Parse trusted proxy IP sources and CIDR networks from settings/env."""
    exact_ips: Set[str] = {"127.0.0.1", "::1", "localhost", "testclient"}
    networks = []

    raw_cidrs = getattr(settings, "TRUSTED_PROXY_CIDRS", None) or os.getenv("TRUSTED_PROXY_CIDRS", "")
    if raw_cidrs:
        for item in raw_cidrs.split(","):
            clean = item.strip()
            if not clean:
                continue
            try:
                if "/" in clean:
                    networks.append(ipaddress.ip_network(clean, strict=False))
                else:
                    exact_ips.add(clean)
            except ValueError:
                logger.warning(f"Invalid trusted proxy CIDR or IP ignored: {clean}")

    return exact_ips, networks


def is_ip_trusted_proxy(ip_str: str) -> bool:
    """Check if direct socket IP belongs to configured trusted reverse proxies."""
    if not ip_str:
        return False

    clean_ip = ip_str.strip().lower()
    exact_ips, networks = get_trusted_proxy_sources()

    if clean_ip in exact_ips:
        return True

    try:
        addr = ipaddress.ip_address(clean_ip)
        for net in networks:
            if addr in net:
                return True
    except ValueError:
        return False

    return False


def get_trusted_client_ip(request: Request) -> str:
    """
    Safely resolve the client IP address enforcing strict anti-spoofing verification:
    - If direct peer (request.client.host) is NOT a trusted proxy:
      DISCARD ALL FORWARDED HEADERS and use request.client.host directly.
    - If direct peer IS a trusted proxy:
      Prefer valid CF-Connecting-IP, then rightmost untrusted hop in X-Forwarded-For.
    """
    direct_peer = request.client.host if request.client else "127.0.0.1"

    # Anti-spoofing check: If immediate socket peer is not a trusted proxy, ignore all forwarded headers
    if not is_ip_trusted_proxy(direct_peer):
        return direct_peer

    # 1. Cloudflare verified ingress header
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        clean_cf = cf_connecting_ip.strip()
        try:
            ipaddress.ip_address(clean_cf)
            return clean_cf
        except ValueError:
            logger.warning(f"Malformed CF-Connecting-IP header received from trusted proxy: {cf_connecting_ip}")

    # 2. X-Forwarded-For chain parsing (rightmost untrusted client)
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for hop in reversed(hops):
            try:
                addr = ipaddress.ip_address(hop)
                if not is_ip_trusted_proxy(str(addr)):
                    return str(addr)
            except ValueError:
                continue

    return direct_peer


class EndpointRateLimiter:
    """
    Enforces identity-aware rate limiting with differentiated failure policies:
    - Normal operation: PostgreSQL atomic window via supabase_service.consume_rate_limit.
    - Degraded operation (DB down): Strict conservative local fallback; never unlimited.
    """

    def __init__(
        self,
        name: str,
        max_requests: int,
        window_seconds: int = 60,
        conservative_fallback_max: int = 3,
    ):
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.conservative_fallback_max = conservative_fallback_max

    def _check_fallback(self, key: str) -> bool:
        """
        Conservative local fallback when distributed storage is unreachable.
        Enforces conservative_fallback_max requests per minute before failing closed.
        """
        now_ts = int(time.time())
        window_start = (now_ts // self.window_seconds) * self.window_seconds
        store = _FALLBACK_STORES.setdefault(self.name, {})

        bucket_key = f"{key}:{window_start}"
        current = store.get(bucket_key, 0) + 1
        store[bucket_key] = current

        # Prune old window entries
        cutoff = now_ts - (self.window_seconds * 2)
        for k in list(store.keys()):
            try:
                if int(k.split(":")[-1]) < cutoff:
                    store.pop(k, None)
            except Exception:
                pass

        return current <= self.conservative_fallback_max

    def check(self, identity_key: str) -> None:
        """Check rate limit token consumption. Raises HTTP 429 if quota exceeded."""
        bucket_key = f"rl:{self.name}:{identity_key}"

        try:
            result = supabase_service.consume_rate_limit(
                bucket_key=bucket_key,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
            )
            if not result.get("allowed", True):
                reset_sec = result.get("reset_seconds", self.window_seconds)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for {self.name}. Please retry in {reset_sec} seconds.",
                    headers={"Retry-After": str(reset_sec)},
                )
        except HTTPException:
            raise
        except Exception as err:
            logger.warning(
                f"[RATE_LIMIT_STORAGE_DEGRADED] Storage error in {self.name} limiter: {err}. "
                f"Engaging conservative local fallback (limit: {self.conservative_fallback_max}/min)."
            )
            # Differentiated failure policy: Bounded conservative fallback, never unlimited
            if not self._check_fallback(identity_key):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit service temporarily degraded for {self.name}. "
                        "Request rejected under conservative safety budget."
                    ),
                    headers={"Retry-After": str(self.window_seconds)},
                )


# =============================================================================
# Granular Rate Limiter Instances
# =============================================================================

# AI Content Lab: 10 req/min user quota (conservative fallback: 3 req/min)
ai_rate_limiter = EndpointRateLimiter(
    name="ai",
    max_requests=10,
    window_seconds=60,
    conservative_fallback_max=3,
)

# DNS Diagnostics: 15 req/min user quota (conservative fallback: 5 req/min)
dns_rate_limiter = EndpointRateLimiter(
    name="dns",
    max_requests=15,
    window_seconds=60,
    conservative_fallback_max=5,
)

# RBL Probes: 15 req/min user quota (conservative fallback: 5 req/min)
rbl_rate_limiter = EndpointRateLimiter(
    name="rbl",
    max_requests=15,
    window_seconds=60,
    conservative_fallback_max=5,
)

# Manual Domain Re-Audits:
# - User level: 10 req/min
# - Domain level: 2 req/min
domain_re_audit_limiter = EndpointRateLimiter(
    name="manual_domain_audit",
    max_requests=2,
    window_seconds=60,
    conservative_fallback_max=1,
)
user_manual_audit_limiter = EndpointRateLimiter(
    name="manual_user_audit",
    max_requests=10,
    window_seconds=60,
    conservative_fallback_max=3,
)


# =============================================================================
# FastAPI Route Dependencies
# =============================================================================

async def rate_limit_ai_tier(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency: Enforce 10 req/min per user on AI content optimization endpoints."""
    ai_rate_limiter.check(user_id)
    return user_id


async def rate_limit_dns_tier(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency: Enforce 15 req/min per user on on-demand DNS diagnostic audits."""
    dns_rate_limiter.check(user_id)
    return user_id


async def rate_limit_rbl_tier(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency: Enforce 15 req/min per user on on-demand Blacklist Radar scans."""
    rbl_rate_limiter.check(user_id)
    return user_id
