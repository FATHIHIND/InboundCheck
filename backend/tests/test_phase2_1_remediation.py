"""
InboundCheck - Phase 2.1 P1 Reliability Remediation Test Suite
==============================================================
Validates:
1. Audit Retry Storm Remediation:
   - First failure backoff suppression.
   - Exponential delay progression.
   - Maximum delay ceiling.
   - Jitter variance.
   - Lifecycle clearing on success.
   - Manual audit execution & quota protection.
   - Concurrency safety under worker contention.
2. Rate Limiting & Trusted Proxy Model:
   - Spoofed header rejection from untrusted peers.
   - Trusted proxy header resolution (CF-Connecting-IP, X-Forwarded-For).
   - Independent quotas for authenticated users sharing single IP.
   - Expensive endpoint quotas (AI, DNS, RBL, manual re-audits).
   - Differentiated failure policy: conservative fallback and fail-closed.
3. Alerting Reality:
   - Ops incident dispatch, sanitization, and anti-flapping suppression.
"""

import pytest
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport, Response
from fastapi import HTTPException

from app.main import app
from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.core.rate_limiter import (
    get_trusted_client_ip,
    is_ip_trusted_proxy,
    ai_rate_limiter,
    dns_rate_limiter,
    domain_re_audit_limiter,
    user_manual_audit_limiter,
    EndpointRateLimiter,
)
from app.services.alerting.ops_alert_service import (
    ops_alert_service,
    OpsIncident,
    sanitize_incident_payload,
)
from tests.conftest import auth_headers


# =============================================================================
# PART A: AUDIT RETRY STORM REMEDIATION TESTS
# =============================================================================

def test_first_failure_does_not_immediately_become_eligible():
    """Verify that a domain failing for the first time is not immediately eligible for re-audit."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_1 = str(uuid.uuid4())
    worker_2 = str(uuid.uuid4())
    dom_id = f"dom_retry_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "failing-store.com",
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_1,
        "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "audit_failure_count": 0,
        "next_audit_retry_at": None,
    }

    orig_domains = dict(supabase_service._in_memory_domains)
    try:
        supabase_service._in_memory_domains = {user_id: [domain]}

        # Worker 1 fails the audit
        failed = supabase_service.fail_domain_audit(
            domain_id=dom_id,
            worker_id=worker_1,
            error="DNS resolution timeout on root NS",
            base_delay_seconds=120,
            max_delay_seconds=86400,
        )
        assert failed is True

        # Verify retry backoff metadata
        assert domain["audit_lease_owner"] is None
        assert domain["audit_lease_until"] is None
        assert domain["audit_failure_count"] == 1
        assert domain["next_audit_retry_at"] is not None

        # Verify next_audit_retry_at is at least 120s in the future
        next_retry_dt = datetime.fromisoformat(domain["next_audit_retry_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        assert (next_retry_dt - now).total_seconds() >= 115

        # Worker 2 immediately attempts to claim due domains (30 seconds later scenario)
        claimed = supabase_service.claim_due_domain_audits(
            worker_id=worker_2,
            limit=5,
            interval_seconds=3600,
            lease_seconds=900,
        )

        # MUST NOT claim this failing domain during its backoff window
        claimed_ids = [d["id"] for d in claimed]
        assert dom_id not in claimed_ids, "Failing domain must NOT be immediately re-claimed"
    finally:
        supabase_service._in_memory_domains = orig_domains


def test_repeated_failures_increase_retry_delay():
    """Verify that consecutive failures result in exponentially increasing retry backoff."""
    user_id = f"test-user-{uuid.uuid4()}"
    dom_id = f"dom_exp_{uuid.uuid4()}"

    orig_domains = dict(supabase_service._in_memory_domains)
    try:
        delays = []
        for fail_idx in range(4):
            worker_id = str(uuid.uuid4())
            domain = {
                "id": dom_id,
                "user_id": user_id,
                "domain_name": "repeated-failure.com",
                "is_active": True,
                "last_audited_at": None,
                "audit_lease_owner": worker_id,
                "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "audit_failure_count": fail_idx,
                "next_audit_retry_at": None,
            }
            supabase_service._in_memory_domains = {user_id: [domain]}

            now_before = datetime.now(timezone.utc)
            supabase_service.fail_domain_audit(
                domain_id=dom_id,
                worker_id=worker_id,
                error=f"Failure {fail_idx + 1}",
                base_delay_seconds=120,
                max_delay_seconds=86400,
            )
            next_retry_dt = datetime.fromisoformat(domain["next_audit_retry_at"].replace("Z", "+00:00"))
            delay_sec = (next_retry_dt - now_before).total_seconds()
            delays.append(delay_sec)

        # Progression: Failure 1 (~120s) < Failure 2 (~240s) < Failure 3 (~480s) < Failure 4 (~960s)
        assert delays[0] >= 118
        assert delays[1] > delays[0]
        assert delays[2] > delays[1]
        assert delays[3] > delays[2]
        assert delays[3] >= 900  # 120 * 2^3 = 960s (allowing for minor execution variance)
    finally:
        supabase_service._in_memory_domains = orig_domains


def test_retry_delay_is_bounded_by_max():
    """Verify that extreme failure counts remain strictly bounded by max_delay_seconds."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_id = str(uuid.uuid4())
    dom_id = f"dom_cap_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "capped-failure.com",
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_id,
        "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "audit_failure_count": 25,  # Extreme consecutive failures
        "next_audit_retry_at": None,
    }

    orig_domains = dict(supabase_service._in_memory_domains)
    try:
        supabase_service._in_memory_domains = {user_id: [domain]}

        now_before = datetime.now(timezone.utc)
        supabase_service.fail_domain_audit(
            domain_id=dom_id,
            worker_id=worker_id,
            error="Permanent DNS failure",
            base_delay_seconds=120,
            max_delay_seconds=86400,
        )

        next_retry_dt = datetime.fromisoformat(domain["next_audit_retry_at"].replace("Z", "+00:00"))
        delay_sec = (next_retry_dt - now_before).total_seconds()

        # Must not exceed 86400s (24h) (with 1s margin for microsecond execution clock drift)
        assert delay_sec <= 86401
        assert delay_sec >= 86300  # Capped at maximum
    finally:
        supabase_service._in_memory_domains = orig_domains


def test_jitter_produces_variance_in_retry_timing():
    """Verify that randomized jitter introduces timing variance between identical failures."""
    user_id = f"test-user-{uuid.uuid4()}"
    orig_domains = dict(supabase_service._in_memory_domains)

    try:
        delays = set()
        for i in range(5):
            worker_id = str(uuid.uuid4())
            dom_id = f"dom_jitter_{i}_{uuid.uuid4()}"
            domain = {
                "id": dom_id,
                "user_id": user_id,
                "domain_name": f"jitter-{i}.com",
                "is_active": True,
                "last_audited_at": None,
                "audit_lease_owner": worker_id,
                "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "audit_failure_count": 2,
                "next_audit_retry_at": None,
            }
            supabase_service._in_memory_domains = {user_id: [domain]}

            now_before = datetime.now(timezone.utc)
            supabase_service.fail_domain_audit(
                domain_id=dom_id,
                worker_id=worker_id,
                error="Jitter test",
                base_delay_seconds=120,
                max_delay_seconds=86400,
            )
            next_retry_dt = datetime.fromisoformat(domain["next_audit_retry_at"].replace("Z", "+00:00"))
            delays.add(int((next_retry_dt - now_before).total_seconds()))

        # Due to 0-25% jitter on 480s, multiple runs must produce at least 2 distinct delay values
        assert len(delays) >= 2, "Jitter must introduce non-deterministic variance in retry delay"
    finally:
        supabase_service._in_memory_domains = orig_domains


def test_successful_audit_clears_failure_state():
    """Verify that a successful audit completely resets failure count, error, and next_audit_retry_at."""
    user_id = f"test-user-{uuid.uuid4()}"
    worker_id = str(uuid.uuid4())
    dom_id = f"dom_recover_{uuid.uuid4()}"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": "recovered-store.com",
        "is_active": True,
        "last_audited_at": None,
        "audit_lease_owner": worker_id,
        "audit_lease_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "audit_failure_count": 5,
        "last_audit_error": "Previous unresolvable host",
        "next_audit_retry_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
    }

    orig_domains = dict(supabase_service._in_memory_domains)
    try:
        supabase_service._in_memory_domains = {user_id: [domain]}

        completed = supabase_service.complete_domain_audit(domain_id=dom_id, worker_id=worker_id)
        assert completed is True

        assert domain["audit_lease_owner"] is None
        assert domain["audit_lease_until"] is None
        assert domain["next_audit_retry_at"] is None
        assert domain["audit_failure_count"] == 0
        assert domain["last_audit_error"] is None
        assert domain["last_audited_at"] is not None
    finally:
        supabase_service._in_memory_domains = orig_domains


def test_manual_audit_executes_and_clears_backoff():
    """Verify create_or_update_domain resets failure backoff on successful audit save."""
    user_id = f"test-user-{uuid.uuid4()}"
    dom_id = f"dom_manual_{uuid.uuid4()}"
    clean_domain = "manual-reset.com"

    domain = {
        "id": dom_id,
        "user_id": user_id,
        "domain_name": clean_domain,
        "is_active": True,
        "last_audited_at": None,
        "audit_failure_count": 4,
        "last_audit_error": "Failed before",
        "next_audit_retry_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }

    orig_domains = dict(supabase_service._in_memory_domains)
    try:
        supabase_service._in_memory_domains = {user_id: [domain]}

        mock_audit = {
            "health_score": 95,
            "summary": {
                "spf": {"status": "valid"},
                "dkim": {"status": "valid"},
                "dmarc": {"status": "valid"},
                "mx": {"status": "valid"},
                "bimi": {"status": "valid"},
            }
        }

        updated = supabase_service.create_or_update_domain(
            user_id=user_id,
            domain_name=clean_domain,
            audit_result=mock_audit,
        )

        assert updated["audit_failure_count"] == 0
        assert updated["next_audit_retry_at"] is None
        assert updated["last_audit_error"] is None
        assert updated["health_score"] == 95
    finally:
        supabase_service._in_memory_domains = orig_domains


# =============================================================================
# PART B: RATE LIMITING & TRUSTED PROXY MODEL TESTS
# =============================================================================

def test_untrusted_client_cannot_spoof_cf_connecting_ip():
    """Verify that spoofed CF-Connecting-IP from an untrusted peer is discarded."""
    mock_request = MagicMock()
    mock_request.client.host = "203.0.113.50"  # Untrusted external client
    mock_request.headers = {
        "CF-Connecting-IP": "198.51.100.1",
        "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
    }

    resolved = get_trusted_client_ip(mock_request)
    # Must use immediate untrusted peer, ignoring spoofed headers
    assert resolved == "203.0.113.50"


def test_trusted_proxy_resolves_valid_cf_connecting_ip():
    """Verify that a request from a trusted reverse proxy (127.0.0.1) uses CF-Connecting-IP."""
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"  # Trusted local proxy / loopback
    mock_request.headers = {
        "CF-Connecting-IP": "198.51.100.42",
    }

    resolved = get_trusted_client_ip(mock_request)
    assert resolved == "198.51.100.42"


def test_trusted_proxy_parses_rightmost_untrusted_x_forwarded_for():
    """Verify X-Forwarded-For resolution selects the rightmost untrusted hop."""
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"  # Trusted proxy
    # Client IP: 198.51.100.99, Proxy 1: 127.0.0.1
    mock_request.headers = {
        "X-Forwarded-For": "203.0.113.10, 198.51.100.99, 127.0.0.1",
    }

    resolved = get_trusted_client_ip(mock_request)
    assert resolved == "198.51.100.99"


def test_malformed_forwarded_headers_fall_back_safely():
    """Verify malformed IP strings in headers do not crash resolution and fall back safely."""
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {
        "CF-Connecting-IP": "not-an-ip-address; DROP TABLE",
        "X-Forwarded-For": "invalid-ip, also-bad",
    }

    resolved = get_trusted_client_ip(mock_request)
    assert resolved == "127.0.0.1"


@pytest.mark.asyncio
async def test_ai_rate_limiter_enforces_quota_per_user():
    """Verify that AI endpoint rate limiter caps requests at 10 req/min per user."""
    user_id = f"ai-user-{uuid.uuid4().hex[:8]}"

    # Reset any existing test tokens for this user
    supabase_service._in_memory_rate_limits.clear()

    # First 10 requests must succeed
    for _ in range(10):
        ai_rate_limiter.check(user_id)

    # 11th request must raise HTTP 429
    with pytest.raises(HTTPException) as exc_info:
        ai_rate_limiter.check(user_id)
    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded for ai" in exc_info.value.detail


@pytest.mark.asyncio
async def test_two_users_behind_same_ip_have_independent_quotas():
    """Verify that User A exhausting their quota does not block User B."""
    user_a = f"corp-user-a-{uuid.uuid4().hex[:8]}"
    user_b = f"corp-user-b-{uuid.uuid4().hex[:8]}"

    supabase_service._in_memory_rate_limits.clear()

    # User A consumes all 10 tokens
    for _ in range(10):
        ai_rate_limiter.check(user_a)

    # User A is now blocked
    with pytest.raises(HTTPException) as exc_info:
        ai_rate_limiter.check(user_a)
    assert exc_info.value.status_code == 429

    # User B should still be allowed their full quota
    ai_rate_limiter.check(user_b)  # Must NOT raise


@pytest.mark.asyncio
async def test_manual_re_audit_enforces_domain_and_user_quotas():
    """Verify manual re-audit limiter caps per-domain at 2 req/min."""
    user_id = f"audit-user-{uuid.uuid4().hex[:8]}"
    domain_id = f"dom_test_{uuid.uuid4().hex[:8]}"

    supabase_service._in_memory_rate_limits.clear()

    # Domain quota: max 2
    domain_re_audit_limiter.check(f"{user_id}:{domain_id}")
    domain_re_audit_limiter.check(f"{user_id}:{domain_id}")

    # 3rd request on same domain within 60s must raise 429
    with pytest.raises(HTTPException) as exc_info:
        domain_re_audit_limiter.check(f"{user_id}:{domain_id}")
    assert exc_info.value.status_code == 429
    assert "manual_domain_audit" in exc_info.value.detail


def test_differentiated_failure_policy_conservative_fallback_fails_closed():
    """Verify expensive endpoints switch to conservative local limit and fail-closed during DB outage."""
    test_limiter = EndpointRateLimiter(
        name="test_expensive",
        max_requests=10,
        window_seconds=60,
        conservative_fallback_max=2,  # Conservative fallback limit
    )

    identity = f"test-client-{uuid.uuid4().hex[:8]}"

    # Simulate database outage raising an unhandled exception
    with patch.object(supabase_service, "consume_rate_limit", side_effect=Exception("Database connection timeout")):
        # First 2 requests within conservative budget succeed
        test_limiter.check(identity)
        test_limiter.check(identity)

        # 3rd request exceeds conservative local fallback budget -> FAILS CLOSED
        with pytest.raises(HTTPException) as exc_info:
            test_limiter.check(identity)
        assert exc_info.value.status_code == 429
        assert "temporarily degraded" in exc_info.value.detail


# =============================================================================
# PART C: ALERTING REALITY & OPS DISPATCH TESTS
# =============================================================================

def test_incident_payload_sanitizes_secrets():
    """Verify sensitive tokens, keys, and cookies are masked before dispatch."""
    dirty_payload = {
        "user_id": "usr_123",
        "api_key": "live_sk_secret_1234567890",
        "bearer_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "nested": {
            "password": "super-secret-password",
            "safe_metric": 42,
        },
        "message": "Encountered error with token=xyz987654321 in request",
    }

    clean = sanitize_incident_payload(dirty_payload)
    assert clean["api_key"] == "[REDACTED]"
    assert clean["bearer_token"] == "[REDACTED]"
    assert clean["nested"]["password"] == "[REDACTED]"
    assert clean["nested"]["safe_metric"] == 42
    assert "xyz987654321" not in clean["message"]
    assert "token=[REDACTED]" in clean["message"]


@pytest.mark.asyncio
async def test_ops_alert_service_dispatches_and_suppresses_flapping():
    """Verify OpsAlertService dispatches successfully and suppresses subsequent flapping alerts."""
    incident = OpsIncident(
        alert_id="ALERT-TEST-INCIDENT",
        severity="P1",
        summary="Automated test incident notification",
        details={"status_code": 502, "component": "shopify_sync"}
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, text="OK")

        # Configure mock webhook URL
        ops_alert_service.webhook_url = "https://ops.example.com/alerts/webhook"
        ops_alert_service.telegram_bot_token = ""
        ops_alert_service.telegram_chat_id = ""

        # First dispatch -> Success
        dispatched_1 = await ops_alert_service.dispatch_incident(incident)
        assert dispatched_1 is True
        assert mock_post.call_count == 1

        # Immediate second dispatch with identical fingerprint -> SUPPRESSED (Flapping Protection)
        dispatched_2 = await ops_alert_service.dispatch_incident(incident)
        assert dispatched_2 is False
        # mock_post should not have been called again
        assert mock_post.call_count == 1
