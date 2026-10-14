"""
InboundCheck - Phase 18A.19 Rate Limiter Forensic Investigation & Verification Suite
=====================================================================================
Covers:
1. Exact Request Limits & Off-by-one Boundaries (N allowed, N+1 blocked, remaining clamped).
2. Fixed-Window Rollover, Reset Time Calculation (reset_seconds >= 1, never 0, accurate Retry-After).
3. Concurrency & Thread-Safety (Atomic RPC locking, in-memory mutex, fallback lock).
4. RPC Path Verification with Mocked Supabase Client (Success, 429 denial, malformed payload).
5. Degraded Database Outage Policy (Production fail-closed, conservative fallback engagement).
6. Multi-Tenant, User, and Endpoint Bucket Isolation.
7. Reverse-Proxy Anti-Spoofing & Trusted Client IP Resolution.
8. Direct RPC Function Permissions & Catalog Assertions (42501 simulation, SQL grants).
9. Safe Pruning Resilience against Malformed or Non-Integer Keys.
10. Clean Fixture Teardown & Global Singleton State Invariance.
"""

import pytest
import os
import time
import uuid
import threading
import concurrent.futures
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limiter import (
    EndpointRateLimiter,
    ai_rate_limiter,
    dns_rate_limiter,
    rbl_rate_limiter,
    domain_re_audit_limiter,
    user_manual_audit_limiter,
    get_trusted_client_ip,
    is_ip_trusted_proxy,
    reset_rate_limiter_stores,
    _FALLBACK_STORES,
    _FALLBACK_LOCK,
)
from app.services.supabase_client import supabase_service, DatabaseUnavailableError


@pytest.fixture(autouse=True)
def isolate_rate_limiter_state():
    """Ensure complete test isolation across all rate-limiting stores and Supabase client."""
    orig_client = supabase_service._client
    orig_rate_limits = dict(supabase_service._in_memory_rate_limits)
    orig_env = getattr(settings, "ENVIRONMENT", "test")

    supabase_service._client = None
    with supabase_service._in_memory_lock:
        supabase_service._in_memory_rate_limits.clear()
    reset_rate_limiter_stores()

    yield

    supabase_service._client = orig_client
    with supabase_service._in_memory_lock:
        supabase_service._in_memory_rate_limits = orig_rate_limits
    reset_rate_limiter_stores()
    settings.ENVIRONMENT = orig_env


# =============================================================================
# 1. EXACT REQUEST LIMITS & OFF-BY-ONE BOUNDARIES
# =============================================================================

def test_exact_n_requests_accepted_n_plus_one_rejected():
    """Verify exactly N requests are allowed, request N+1 is rejected, and remaining decreases to 0."""
    bucket_key = f"rl:test:exact_limits_{uuid.uuid4().hex[:8]}"
    max_requests = 5
    window_seconds = 60

    with patch("app.services.supabase_client.time.time", return_value=1700000000.0):
        for i in range(1, max_requests + 1):
            res = supabase_service.consume_rate_limit(
                bucket_key=bucket_key,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
            assert res["allowed"] is True
            assert res["current_requests"] == i
            assert res["remaining"] == max_requests - i

        # Request N+1 (6th) must be rejected
        res_blocked = supabase_service.consume_rate_limit(
            bucket_key=bucket_key,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        assert res_blocked["allowed"] is False
        assert res_blocked["current_requests"] == 6
        assert res_blocked["remaining"] == 0


def test_endpoint_rate_limiter_raises_429_on_limit_exceeded():
    """Verify EndpointRateLimiter.check() succeeds up to max_requests and raises HTTP 429 on overflow."""
    limiter = EndpointRateLimiter(name="test_quota", max_requests=3, window_seconds=60)
    identity = f"user_{uuid.uuid4().hex[:8]}"

    with patch("app.services.supabase_client.time.time", return_value=1700000000.0):
        for _ in range(3):
            limiter.check(identity)  # Must not raise

        with pytest.raises(HTTPException) as exc_info:
            limiter.check(identity)

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded for test_quota" in exc_info.value.detail
        assert "Retry-After" in exc_info.value.headers
        assert int(exc_info.value.headers["Retry-After"]) >= 1


# =============================================================================
# 2. FIXED-WINDOW ROLLOVER & RESET METADATA
# =============================================================================

def test_fixed_window_rollover_resets_quota():
    """Verify that moving past window_seconds cleanly resets the counter in the new window."""
    bucket_key = f"rl:test:rollover_{uuid.uuid4().hex[:8]}"
    t_start = 1700000000.0  # window 1: 1700000000..1700000059

    # Exhaust quota in window 1
    with patch("app.services.supabase_client.time.time", return_value=t_start):
        for _ in range(3):
            res = supabase_service.consume_rate_limit(bucket_key, max_requests=3, window_seconds=60)
            assert res["allowed"] is True
        res_blocked = supabase_service.consume_rate_limit(bucket_key, max_requests=3, window_seconds=60)
        assert res_blocked["allowed"] is False

    # Advance clock into window 2: 1700000060.0
    t_next = t_start + 60.0
    with patch("app.services.supabase_client.time.time", return_value=t_next):
        res_new_window = supabase_service.consume_rate_limit(bucket_key, max_requests=3, window_seconds=60)
        assert res_new_window["allowed"] is True
        assert res_new_window["current_requests"] == 1
        assert res_new_window["remaining"] == 2


def test_reset_seconds_is_strictly_positive_at_boundary():
    """Verify reset_seconds is never 0 or negative even at the final second of the window."""
    bucket_key = f"rl:test:boundary_{uuid.uuid4().hex[:8]}"
    # Final second of a 60-second window starting at 1700000040:
    t_boundary = 1700000099.0

    with patch("app.services.supabase_client.time.time", return_value=t_boundary):
        res = supabase_service.consume_rate_limit(bucket_key, max_requests=1, window_seconds=60)
        assert res["reset_seconds"] >= 1
        assert res["reset_seconds"] == 1


# =============================================================================
# 3. CONCURRENCY & MULTITHREADING SAFETY
# =============================================================================

def test_concurrent_requests_do_not_exceed_limit_in_memory():
    """Verify that 20 concurrent threads attempting to consume quota of 5 never allow > 5 requests."""
    bucket_key = f"rl:test:concurrency_{uuid.uuid4().hex[:8]}"
    max_requests = 5
    results = []

    def consume_attempt():
        return supabase_service.consume_rate_limit(
            bucket_key=bucket_key,
            max_requests=max_requests,
            window_seconds=60,
        )

    with patch("app.services.supabase_client.time.time", return_value=1700000010.0):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(consume_attempt) for _ in range(20)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

    allowed_count = sum(1 for r in results if r["allowed"] is True)
    blocked_count = sum(1 for r in results if r["allowed"] is False)

    assert allowed_count == 5, f"Expected exactly 5 allowed, got {allowed_count}"
    assert blocked_count == 15, f"Expected exactly 15 blocked, got {blocked_count}"


def test_concurrent_fallback_store_lock_prevents_race_condition():
    """Verify that _FALLBACK_LOCK prevents data corruption and over-allocation under concurrent fallback."""
    limiter = EndpointRateLimiter(name="concurrency_fallback", max_requests=10, conservative_fallback_max=4)
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    results = []

    def fallback_attempt():
        allowed, reset_sec = limiter._check_fallback(user_id, max_allowed=4)
        return allowed

    with patch("app.core.rate_limiter.time.time", return_value=1700000010.0):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fallback_attempt) for _ in range(16)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

    allowed_count = sum(1 for r in results if r is True)
    assert allowed_count == 4, f"Expected exactly 4 allowed under fallback limit, got {allowed_count}"


# =============================================================================
# 4. RPC PATH VERIFICATION WITH MOCKED SUPABASE CLIENT
# =============================================================================

def test_consume_rate_limit_uses_rpc_when_client_present():
    """Verify consume_rate_limit invokes self._client.rpc with correct parameters and normalizes reset_seconds."""
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = {
        "allowed": True,
        "current_requests": 2,
        "remaining": 8,
        "reset_seconds": 45,
    }

    supabase_service._client = mock_client
    res = supabase_service.consume_rate_limit("rl:test:rpc_call", max_requests=10, window_seconds=60)

    assert mock_client.rpc.called
    call_args = mock_client.rpc.call_args
    assert call_args[0][0] == "consume_rate_limit"
    assert call_args[0][1]["p_bucket_key"] == "rl:test:rpc_call"
    assert call_args[0][1]["p_max_requests"] == 10
    assert call_args[0][1]["p_window_seconds"] == 60

    assert res["allowed"] is True
    assert res["reset_seconds"] == 45


def test_consume_rate_limit_normalizes_zero_reset_seconds_from_sql_rpc():
    """If remote SQL returns reset_seconds = 0, client must normalize to at least 1."""
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = {
        "allowed": False,
        "current_requests": 11,
        "remaining": 0,
        "reset_seconds": 0,  # Boundary zero from SQL
    }

    supabase_service._client = mock_client
    res = supabase_service.consume_rate_limit("rl:test:zero_reset", max_requests=10, window_seconds=60)

    assert res["allowed"] is False
    assert res["reset_seconds"] >= 1


def test_endpoint_limiter_rejects_malformed_rpc_payload_fail_secure():
    """If consume_rate_limit returns an empty or malformed dict missing allowed, limiter fails closed (429)."""
    with patch.object(supabase_service, "consume_rate_limit", return_value={"corrupted": True}):
        limiter = EndpointRateLimiter(name="malformed_test", max_requests=5)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user_test")
        assert exc_info.value.status_code == 429


# =============================================================================
# 5. DEGRADED DATABASE OUTAGE & CONSERVATIVE FALLBACK POLICY
# =============================================================================

def test_production_environment_fails_closed_on_database_rpc_error():
    """In production, an unhandled RPC exception raises DatabaseUnavailableError, never silently falling open."""
    settings.ENVIRONMENT = "production"
    mock_client = MagicMock()
    mock_client.rpc.side_effect = RuntimeError("PostgreSQL connection refused")
    supabase_service._client = mock_client

    with pytest.raises(DatabaseUnavailableError, match="Database RPC consume_rate_limit failed in production"):
        supabase_service.consume_rate_limit("rl:test:prod_fail", max_requests=10, window_seconds=60)


def test_production_disconnected_client_fails_closed():
    """In production, if _client is None, consume_rate_limit must raise DatabaseUnavailableError."""
    settings.ENVIRONMENT = "production"
    supabase_service._client = None

    with pytest.raises(DatabaseUnavailableError, match="Database client is not connected in production"):
        supabase_service.consume_rate_limit("rl:test:prod_none", max_requests=10, window_seconds=60)


def test_limiter_catches_db_outage_and_engages_conservative_fallback():
    """
    When database is down (raising DatabaseUnavailableError), EndpointRateLimiter engages
    conservative fallback (3 req/min for AI) and rejects the 4th request with degraded detail.
    """
    limiter = EndpointRateLimiter(
        name="ai",
        max_requests=10,
        window_seconds=60,
        conservative_fallback_max=3,
    )
    user_id = f"outage_user_{uuid.uuid4().hex[:8]}"

    def failing_consume(*args, **kwargs):
        raise DatabaseUnavailableError("Supabase connection timeout in production")

    with patch.object(supabase_service, "consume_rate_limit", side_effect=failing_consume):
        # Requests 1..3 succeed under conservative fallback
        for _ in range(3):
            limiter.check(user_id)

        # 4th request must be rejected under conservative budget
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(user_id)

        assert exc_info.value.status_code == 429
        assert "Rate limit service temporarily degraded for ai" in exc_info.value.detail
        assert "Request rejected under conservative safety budget" in exc_info.value.detail
        assert int(exc_info.value.headers["Retry-After"]) >= 1


# =============================================================================
# 6. BUCKET ISOLATION ACROSS USERS, TENANTS & ENDPOINTS
# =============================================================================

def test_tenant_and_user_bucket_isolation():
    """User A exhausting quota does NOT impact User B on the same endpoint."""
    limiter = EndpointRateLimiter(name="isolation_test", max_requests=2)
    user_a = "user_alpha"
    user_b = "user_beta"

    limiter.check(user_a)
    limiter.check(user_a)

    # User A is blocked on 3rd
    with pytest.raises(HTTPException):
        limiter.check(user_a)

    # User B must still be permitted
    limiter.check(user_b)
    limiter.check(user_b)


def test_endpoint_bucket_isolation_for_same_user():
    """Same user exhausting AI rate limit does NOT impact their DNS or RBL quota."""
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    ai_lim = EndpointRateLimiter(name="ai", max_requests=1)
    dns_lim = EndpointRateLimiter(name="dns", max_requests=1)

    ai_lim.check(user_id)
    with pytest.raises(HTTPException):
        ai_lim.check(user_id)

    # DNS endpoint for same user is independent
    dns_lim.check(user_id)  # Must NOT raise


# =============================================================================
# 7. REVERSE-PROXY ANTI-SPOOFING & CLIENT IP RESOLUTION
# =============================================================================

def test_untrusted_peer_ignores_spoofed_forwarded_headers():
    """If direct peer is an untrusted public IP, forwarded headers must be ignored."""
    req = MagicMock(spec=Request)
    req.client.host = "203.0.113.195"  # Untrusted external IP
    req.headers = {
        "CF-Connecting-IP": "198.51.100.5",
        "X-Forwarded-For": "198.51.100.5, 10.0.0.1",
    }

    resolved = get_trusted_client_ip(req)
    assert resolved == "203.0.113.195", f"Expected direct peer, got {resolved}"


def test_trusted_proxy_extracts_valid_cf_connecting_ip():
    """If direct peer is trusted (127.0.0.1), CF-Connecting-IP is extracted."""
    req = MagicMock(spec=Request)
    req.client.host = "127.0.0.1"
    req.headers = {
        "CF-Connecting-IP": "198.51.100.42",
        "X-Forwarded-For": "198.51.100.42, 127.0.0.1",
    }

    resolved = get_trusted_client_ip(req)
    assert resolved == "198.51.100.42"


def test_trusted_proxy_parses_rightmost_untrusted_hop_in_xff():
    """If CF-Connecting-IP is absent, rightmost untrusted hop in XFF is selected."""
    req = MagicMock(spec=Request)
    req.client.host = "127.0.0.1"
    req.headers = {
        "X-Forwarded-For": "203.0.113.10, 198.51.100.22, 127.0.0.1",
    }

    resolved = get_trusted_client_ip(req)
    assert resolved == "198.51.100.22"


def test_malformed_ips_in_forwarded_headers_rejected_safely():
    """Malformed non-IP strings in headers do not crash and fall back safely to direct peer."""
    req = MagicMock(spec=Request)
    req.client.host = "127.0.0.1"
    req.headers = {
        "CF-Connecting-IP": "malicious<script>alert(1)</script>",
        "X-Forwarded-For": "invalid_ip_format",
    }

    resolved = get_trusted_client_ip(req)
    assert resolved == "127.0.0.1"


# =============================================================================
# 8. DIRECT RPC PRIVILEGES & STATIC CATALOG ASSERTIONS
# =============================================================================

def test_migration_hardens_consume_rate_limit_privileges():
    """Verify that migration 20261012000001 revokes consume_rate_limit from PUBLIC/anon/authenticated."""
    mig_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "supabase",
        "migrations",
        "20261012000001_harden_rate_limit_windows_security.sql"
    )
    assert os.path.exists(mig_path), "Hardened migration file must exist"

    with open(mig_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # Revocations
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM PUBLIC;" in sql
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM anon;" in sql
    assert "REVOKE ALL ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) FROM authenticated;" in sql

    # Grants
    assert "GRANT EXECUTE ON FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) TO postgres, service_role;" in sql

    # Search path & ownership
    assert "ALTER FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) OWNER TO postgres;" in sql
    assert "ALTER FUNCTION public.consume_rate_limit(TEXT, INTEGER, INTEGER) SET search_path = public, pg_temp;" in sql


def test_client_direct_rpc_invocation_denied_simulation():
    """Simulate PostgREST rejecting direct client RPC calls with 42501 (permission denied)."""
    mock_postgrest_error = Exception("PGRST301: permission denied for function consume_rate_limit")
    mock_client = MagicMock()
    mock_client.rpc.side_effect = mock_postgrest_error

    with patch.object(supabase_service, "_client", mock_client):
        with pytest.raises(Exception) as exc_info:
            supabase_service._client.rpc("consume_rate_limit", {
                "p_bucket_key": "rl:test:denied",
                "p_max_requests": 10,
                "p_window_seconds": 60,
            }).execute()
        assert "permission denied" in str(exc_info.value)


# =============================================================================
# 9. SAFE PRUNING RESILIENCE AGAINST MALFORMED KEYS
# =============================================================================

def test_in_memory_pruning_survives_malformed_keys():
    """Ensure in-memory rate limit pruning does not crash if non-standard keys exist."""
    with supabase_service._in_memory_lock:
        # Insert valid and invalid format keys
        supabase_service._in_memory_rate_limits["rl:test:clean:1700000000"] = 1
        supabase_service._in_memory_rate_limits["malformed_key_without_timestamp"] = 2
        supabase_service._in_memory_rate_limits["another:colon:non_int_timestamp:abc"] = 3

    # Must complete without ValueError or crash
    res = supabase_service.consume_rate_limit("rl:test:clean", max_requests=5, window_seconds=60)
    assert res["allowed"] is True
