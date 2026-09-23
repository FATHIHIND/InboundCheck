"""
InboundCheck - P0 Security & Data Integrity Regression Suite
=============================================================
Proves remediation of P0 vulnerabilities:
1. Tenant Isolation: User A cannot re-audit User B's domain; auto-fix logs never leak across tenants.
2. Trial State Security: NULL, malformed, or missing trial dates fail-closed (HTTP 402).
3. Production In-Memory Fallback Purge: Database outages in production fail-closed (DatabaseUnavailableError)
   and never produce fake in-memory persistence.
4. Health / Readiness Probes: Liveness (/health) reports alive; readiness (/ready) reports 503 during DB outage in production.
5. Shopify Billing Callback: Rejects unverified shop or mismatched store ownership.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.core.tier_guards import is_trial_expired, verify_active_subscription_or_trial
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.dns.auto_fixer import dns_auto_fixer_service
from tests.conftest import auth_headers


# =============================================================================
# 1. Tenant Isolation Tests (SEC-01, SEC-T1, SEC-T2, SEC-T3)
# =============================================================================

@pytest.mark.asyncio
async def test_tenant_isolation_cross_domain_reaudit_rejected():
    """Prove that User A cannot re-audit a domain owned by User B (returns 404)."""
    user_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
    user_b = f"tenant_b_{uuid.uuid4().hex[:6]}"

    # Setup User A with a monitored domain
    domain_a = supabase_service.create_or_update_domain(
        user_id=user_a,
        domain_name="brand-a.com"
    )
    domain_a_id = domain_a.get("id")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # User B attempts to re-audit User A's domain_id
        res = await ac.post(
            f"/api/v1/domains/{domain_a_id}/audit?domain_name=brand-a.com",
            headers=auth_headers(user_b)
        )
        assert res.status_code == 404
        assert "not found" in res.json().get("detail", "").lower()


def test_tenant_isolation_auto_fix_logs_do_not_leak_demo_data():
    """Prove that a new user never receives demo-user-123's DNS fix logs."""
    new_user = f"new_tenant_{uuid.uuid4().hex[:6]}"
    logs = dns_auto_fixer_service.get_logs(new_user)
    assert logs == []


@pytest.mark.asyncio
async def test_shopify_billing_callback_rejects_missing_shop():
    """Prove that billing callback rejects calls lacking shop parameter."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/shopify/billing/callback?charge_id=12345&user_id=victim")
        assert res.status_code == 400
        assert "missing required shop" in res.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_shopify_billing_callback_rejects_unowned_shop():
    """Prove that billing callback rejects shop not associated with the user."""
    attacker_user = f"user_{uuid.uuid4().hex[:6]}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            f"/api/v1/shopify/billing/callback?charge_id=12345&shop=unowned-store.myshopify.com&user_id={attacker_user}"
        )
        assert res.status_code == 403
        assert "not associated" in res.json().get("detail", "").lower()


# =============================================================================
# 2. Trial State & Entitlement Fail-Closed Tests (SEC-05)
# =============================================================================

def test_trial_state_fail_closed_on_null_date():
    """Prove that a trialing account with NULL trial_ends_at is expired (fail-closed)."""
    profile = {
        "id": "test_null_trial",
        "subscription_status": "trialing",
        "trial_ends_at": None,
    }
    assert is_trial_expired(profile) is True


def test_trial_state_fail_closed_on_malformed_date():
    """Prove that a trialing account with an unparseable date string is expired."""
    profile = {
        "id": "test_corrupted_trial",
        "subscription_status": "trialing",
        "trial_ends_at": "invalid-datetime-format-3000",
    }
    assert is_trial_expired(profile) is True


def test_trial_state_active_future_date():
    """Prove that a valid future UTC timestamp is recognized as active."""
    profile = {
        "id": "test_active_trial",
        "subscription_status": "trialing",
        "trial_ends_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    }
    assert is_trial_expired(profile) is False


def test_trial_state_past_date():
    """Prove that a past timestamp is recognized as expired."""
    profile = {
        "id": "test_past_trial",
        "subscription_status": "trialing",
        "trial_ends_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    assert is_trial_expired(profile) is True


@pytest.mark.asyncio
async def test_verify_active_subscription_rejects_expired_trial():
    """Prove verify_active_subscription_or_trial raises 402 on expired trial."""
    user_id = f"user_expired_{uuid.uuid4().hex[:6]}"
    supabase_service.update_user_profile(user_id, {
        "subscription_status": "trialing",
        "trial_ends_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
    })
    with pytest.raises(Exception) as excinfo:
        await verify_active_subscription_or_trial(user_id=user_id)
    assert "402" in str(excinfo.value)


@pytest.mark.asyncio
async def test_verify_active_subscription_rejects_null_trial():
    """Prove verify_active_subscription_or_trial raises 402 on NULL trial_ends_at."""
    user_id = f"user_null_trial_{uuid.uuid4().hex[:6]}"
    supabase_service.update_user_profile(user_id, {
        "subscription_status": "trialing",
        "trial_ends_at": None,
    })
    with pytest.raises(Exception) as excinfo:
        await verify_active_subscription_or_trial(user_id=user_id)
    assert "402" in str(excinfo.value)


@pytest.mark.asyncio
async def test_verify_active_subscription_permits_active_paid():
    """Prove verify_active_subscription_or_trial permits active paid accounts."""
    user_id = f"user_paid_{uuid.uuid4().hex[:6]}"
    supabase_service.update_user_profile(user_id, {
        "subscription_status": "active",
        "subscription_tier": "growth",
    })
    profile = await verify_active_subscription_or_trial(user_id=user_id)
    assert profile.get("subscription_status") == "active"


# =============================================================================
# 3. Production In-Memory Database Fallback Purge Tests (SEC-04)
# =============================================================================

def test_production_environment_rejects_in_memory_fallback(monkeypatch):
    """Prove that in ENVIRONMENT='production', database outage raises DatabaseUnavailableError."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    user_id = f"prod_user_{uuid.uuid4().hex[:6]}"

    # Mock client as disconnected
    with patch.object(supabase_service, "_client", None):
        assert supabase_service._allow_in_memory_fallback() is False

        with pytest.raises(DatabaseUnavailableError):
            supabase_service.get_user_domains(user_id)

        with pytest.raises(DatabaseUnavailableError):
            supabase_service.create_or_update_domain(user_id, "prod-domain.com")

        with pytest.raises(DatabaseUnavailableError):
            supabase_service.delete_domain(user_id, "dom_123")

        with pytest.raises(DatabaseUnavailableError):
            supabase_service.save_audit_log(user_id=user_id, domain_name="prod-domain.com", audit_result={})


# =============================================================================
# 4. Health and Readiness Separation Tests (SEC-02)
# =============================================================================

@pytest.mark.asyncio
async def test_liveness_endpoint_returns_alive():
    """Prove /health reports alive without probing external database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "alive"
        assert "timestamp" in data


@pytest.mark.asyncio
async def test_readiness_probe_fails_503_during_production_db_outage(monkeypatch):
    """Prove /ready and /api/v1/health return 503 when database is unreachable in production."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with patch.object(supabase_service, "check_db_health", return_value=False), \
         patch.object(supabase_service, "_allow_in_memory_fallback", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/ready")
            assert res.status_code == 503
            data = res.json()
            assert data.get("status") == "unavailable"
            assert data.get("dependencies", {}).get("database") == "unhealthy"

            # Also verify /api/v1/health readiness probe
            res_v1 = await ac.get("/api/v1/health")
            assert res_v1.status_code == 503
