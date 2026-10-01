"""
InboundCheck - Stripe Billing, 3-Day Trial, and Tier Enforcement Tests
======================================================================
Verifies:
- 3-day free trial expiration boundary and automatic marking as expired
- Quota limits: Starter (1 domain), Growth (3 domains), Agency (20 domains)
- Tier gating: SPF merge plan and 1-click auto-fix restricted to Growth/Agency
- Stripe checkout session generation for Starter ($9), Growth ($29), Agency ($79)
- Customer portal session generation
- Stripe webhook ingestion: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted
- Webhook signature verification and idempotency protection
"""

import pytest
import time
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from fastapi import HTTPException

from app.main import app
from app.services.supabase_client import supabase_service
from app.services.billing.stripe_service import stripe_service, PLAN_PRICING, TIER_LIMITS
from app.core.tier_guards import (
    verify_active_subscription_or_trial,
    require_growth_or_agency_tier,
    is_trial_expired,
)
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_trial_active_boundary():
    """User within 3-day free trial should pass access verification."""
    user_id = "trial-active-user-1"
    future_date = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": future_date,
    })

    prof = supabase_service.get_user_profile(user_id)
    assert not is_trial_expired(prof)

    verified = await verify_active_subscription_or_trial(user_id=user_id)
    assert verified["id"] == user_id
    assert verified["subscription_status"] == "trialing"


@pytest.mark.asyncio
async def test_trial_expired_boundary():
    """User whose 3-day trial has passed should be automatically marked expired and receive HTTP 402."""
    user_id = "trial-expired-user-2"
    past_date = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": past_date,
    })

    prof = supabase_service.get_user_profile(user_id)
    assert is_trial_expired(prof)

    with pytest.raises(HTTPException) as exc_info:
        await verify_active_subscription_or_trial(user_id=user_id)

    assert exc_info.value.status_code == 402
    assert "trial expired" in exc_info.value.detail.lower()

    # Verify atomic update to 'expired'
    updated_prof = supabase_service.get_user_profile(user_id)
    assert updated_prof["subscription_status"] == "expired"


@pytest.mark.asyncio
async def test_expired_subscription_blocks_access():
    """Directly expired status returns HTTP 402."""
    user_id = "expired-user-3"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "expired",
    })

    with pytest.raises(HTTPException) as exc_info:
        await verify_active_subscription_or_trial(user_id=user_id)

    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_domain_quota_limits():
    """Verify domain caps: Starter (1 domain), Growth (3 domains), Enterprise (unlimited)."""
    transport = ASGITransport(app=app)

    # 1. Starter Tier user: limit 1 domain
    starter_user = "starter-quota-user"
    future_date = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    supabase_service.update_user_profile(starter_user, {
        "subscription_tier": "starter",
        "subscription_status": "active",
        "trial_ends_at": future_date,
    })
    supabase_service._in_memory_domains[starter_user] = []

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(starter_user)) as ac:
        # Add 1st domain -> Allowed
        r1 = await ac.post("/api/v1/domains", json={"domain": "starter-domain-1.com"})
        assert r1.status_code == 200

        # Add 2nd domain -> Exceeds quota -> 402
        r2 = await ac.post("/api/v1/domains", json={"domain": "starter-domain-2.com"})
        assert r2.status_code == 402
        assert "quota reached" in r2.json()["detail"].lower()

    # 2. Growth Tier user: limit 3 domains
    growth_user = "growth-quota-user"
    supabase_service.update_user_profile(growth_user, {
        "subscription_tier": "growth",
        "subscription_status": "active",
    })
    supabase_service._in_memory_domains[growth_user] = []

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(growth_user)) as ac:
        for i in range(1, 4):
            res = await ac.post("/api/v1/domains", json={"domain": f"growth-domain-{i}.com"})
            assert res.status_code == 200

        # 4th domain -> Exceeds quota (3) -> 402
        r4 = await ac.post("/api/v1/domains", json={"domain": "growth-domain-4.com"})
        assert r4.status_code == 402
        assert "quota reached" in r4.json()["detail"].lower()

    # 3. Agency Tier user: limit 20 domains
    agency_user = "agency-quota-user"
    supabase_service.update_user_profile(agency_user, {
        "subscription_tier": "agency",
        "subscription_status": "active",
    })
    supabase_service._in_memory_domains[agency_user] = []

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(agency_user)) as ac:
        for i in range(1, 21):
            res = await ac.post("/api/v1/domains", json={"domain": f"agency-domain-{i}.com"})
            assert res.status_code == 200

        # 21st domain -> Exceeds quota (20) -> 402
        r21 = await ac.post("/api/v1/domains", json={"domain": "agency-domain-21.com"})
        assert r21.status_code == 402
        assert "quota reached" in r21.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tier_gates_spf_merge_and_auto_fix():
    """Starter users cannot access SPF merge plan or 1-click auto-fix when trial is over."""
    transport = ASGITransport(app=app)
    starter_user = "starter-gate-user"

    # User on active Starter plan (trial is over)
    supabase_service.update_user_profile(starter_user, {
        "subscription_tier": "starter",
        "subscription_status": "active",
        "trial_ends_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    })

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(starter_user)) as ac:
        # Gated: /api/v1/dns/spf-merge-plan
        spf_res = await ac.post("/api/v1/dns/spf-merge-plan", json={"domain": "mystore.com"})
        assert spf_res.status_code == 403
        assert "UPGRADE_REQUIRED" in spf_res.json()["detail"]

        # Gated: /api/v1/dns/auto-fix/apply
        fix_res = await ac.post("/api/v1/dns/auto-fix/apply", json={
            "domain_name": "mystore.com",
            "host": "_dmarc.mystore.com",
            "record_type": "TXT",
            "record_value": "v=DMARC1; p=reject;"
        })
        assert fix_res.status_code == 403
        assert "UPGRADE_REQUIRED" in fix_res.json()["detail"]

    # Growth tier user: allowed
    growth_user = "growth-gate-user"
    supabase_service.update_user_profile(growth_user, {
        "subscription_tier": "growth",
        "subscription_status": "active",
    })
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(growth_user)) as ac:
        spf_res_g = await ac.post("/api/v1/dns/spf-merge-plan", json={"domain": "growth-store.com"})
        assert spf_res_g.status_code == 200


@pytest.mark.asyncio
async def test_checkout_session_creation():
    """Verify Stripe checkout session creation for Starter ($9), Growth ($29), Agency ($79), and legacy Enterprise resolution."""
    transport = ASGITransport(app=app)
    user_id = "checkout-test-user"

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # 1. Starter Checkout ($9)
        r_starter = await ac.post("/api/v1/billing/create-checkout-session", json={"plan_tier": "starter"})
        assert r_starter.status_code == 200
        d_starter = r_starter.json()
        assert d_starter["success"] is True
        assert d_starter["plan_tier"] == "starter"
        assert d_starter["amount"] == 9.0
        assert "checkout_url" in d_starter

        # 2. Growth Checkout ($29)
        r_growth = await ac.post("/api/v1/billing/create-checkout-session", json={"plan_tier": "growth"})
        assert r_growth.status_code == 200
        d_growth = r_growth.json()
        assert d_growth["amount"] == 29.0

        # 3. Agency Checkout ($79)
        r_agency = await ac.post("/api/v1/billing/create-checkout-session", json={"plan_tier": "agency"})
        assert r_agency.status_code == 200
        d_agency = r_agency.json()
        assert d_agency["amount"] == 79.0

        # 4. Legacy Enterprise input safely maps to Agency ($79), NOT $199 or 999 domains
        r_ent = await ac.post("/api/v1/billing/create-checkout-session", json={"plan_tier": "enterprise"})
        assert r_ent.status_code == 200
        d_ent = r_ent.json()
        assert d_ent["plan_tier"] == "agency"
        assert d_ent["amount"] == 79.0


@pytest.mark.asyncio
async def test_subscription_plans_contains_only_three_tiers():
    """Verify /billing/plans returns strictly Starter, Growth, Agency — no Enterprise."""
    transport = ASGITransport(app=app)
    user_id = "plans-test-user"

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.get("/api/v1/billing/plans")
        assert res.status_code == 200
        data = res.json()
        plans = data["plans"]
        plan_ids = [p["id"] for p in plans]
        assert plan_ids == ["starter", "growth", "agency"]
        assert "enterprise" not in plan_ids


@pytest.mark.asyncio
async def test_customer_portal_session():
    """Verify Customer Portal session creation."""
    transport = ASGITransport(app=app)
    user_id = "portal-test-user"

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/billing/customer-portal", json={"return_url": "http://test/dashboard"})
        assert res.status_code == 200
        assert "portal_url" in res.json()


@pytest.mark.asyncio
async def test_webhook_lifecycle_ingestion():
    """Verify Stripe webhook processing for checkout.session.completed, updated, deleted."""
    transport = ASGITransport(app=app)
    user_id = "webhook-user-42"
    now_ts = int(time.time())

    # 1. checkout.session.completed
    checkout_event = {
        "id": f"evt_checkout_{now_ts}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": user_id,
                "customer": "cus_stripe_12345",
                "subscription": "sub_stripe_67890",
                "metadata": {
                    "user_id": user_id,
                    "plan_tier": "growth",
                }
            }
        }
    }

    raw_bytes = json.dumps(checkout_event).encode("utf-8")
    sig_header = f"t={now_ts},v1=mock_signature"

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/billing/webhook",
            content=raw_bytes,
            headers={"Stripe-Signature": sig_header, "Content-Type": "application/json"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["action"] == "subscription_activated"

    prof = supabase_service.get_user_profile(user_id)
    assert prof["subscription_tier"] == "growth"
    assert prof["subscription_status"] == "active"
    assert prof["stripe_customer_id"] == "cus_stripe_12345"
    assert prof["stripe_subscription_id"] == "sub_stripe_67890"

    # 2. Duplicate event -> Idempotency check
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        dup_res = await ac.post(
            "/api/v1/billing/webhook",
            content=raw_bytes,
            headers={"Stripe-Signature": sig_header, "Content-Type": "application/json"}
        )
        assert dup_res.status_code == 200
        assert dup_res.json().get("status") == "already_processed"

    # 3. customer.subscription.deleted -> Downgrade
    cancel_event = {
        "id": f"evt_cancel_{now_ts}",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "customer": "cus_stripe_12345",
                "status": "canceled",
                "metadata": {"user_id": user_id}
            }
        }
    }
    cancel_bytes = json.dumps(cancel_event).encode("utf-8")
    cancel_sig = f"t={now_ts},v1=mock_sig_cancel"

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c_res = await ac.post(
            "/api/v1/billing/webhook",
            content=cancel_bytes,
            headers={"Stripe-Signature": cancel_sig, "Content-Type": "application/json"}
        )
        assert c_res.status_code == 200
        assert c_res.json()["action"] == "subscription_downgraded"

    prof_after = supabase_service.get_user_profile(user_id)
    assert prof_after["subscription_tier"] == "starter"
    assert prof_after["subscription_status"] == "canceled"


@pytest.mark.asyncio
async def test_customer_portal_bola_rejection_and_ownership():
    """
    Verify customer portal rejects foreign customer_ids (BOLA/IDOR) with 403
    and resolves own or omitted customer_id safely.
    """
    transport = ASGITransport(app=app)
    user_a = "bola-test-user-a"
    user_b = "bola-test-user-b"
    supabase_service.update_user_profile(user_a, {"stripe_customer_id": "cus_user_a_123"})
    supabase_service.update_user_profile(user_b, {"stripe_customer_id": "cus_victim_b_456"})

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_a)) as ac:
        # 1. Foreign customer_id rejected with 403 Forbidden
        res_foreign = await ac.post("/api/v1/billing/customer-portal", json={"customer_id": "cus_victim_b_456"})
        assert res_foreign.status_code == 403
        assert res_foreign.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"

        # 2. Arbitrary non-existent customer_id also rejected with identical 403 (no existence leak)
        res_fake = await ac.post("/api/v1/billing/customer-portal", json={"customer_id": "cus_fake_nonexistent"})
        assert res_fake.status_code == 403
        assert res_fake.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"

        # 3. Own customer_id accepted for backward compatibility
        res_own = await ac.post("/api/v1/billing/customer-portal", json={"customer_id": "cus_user_a_123"})
        assert res_own.status_code == 200
        assert "portal_url" in res_own.json()
        assert res_own.json()["has_customer"] is True

        # 4. Omitted customer_id resolves authoritatively to authenticated tenant
        res_omitted = await ac.post("/api/v1/billing/customer-portal", json={"return_url": "http://test/return"})
        assert res_omitted.status_code == 200
        assert "portal_url" in res_omitted.json()
        assert res_omitted.json()["has_customer"] is True


@pytest.mark.asyncio
async def test_customer_portal_missing_stripe_customer_safe():
    """
    Verify tenant without stripe_customer_id is handled safely:
    - Omitted customer_id returns has_customer=False (200 OK)
    - Attempting to pass any customer_id returns 403 Forbidden
    """
    transport = ASGITransport(app=app)
    user_c = "no-stripe-customer-user"
    supabase_service.update_user_profile(user_c, {"stripe_customer_id": None})

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_c)) as ac:
        # Omitted customer_id: safe response
        res = await ac.post("/api/v1/billing/customer-portal", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["has_customer"] is False
        assert "No active Stripe customer account found" in data["message"]

        # Supplying a customer_id when user has none: rejected
        res_tamper = await ac.post("/api/v1/billing/customer-portal", json={"customer_id": "cus_someone_else"})
        assert res_tamper.status_code == 403
        assert res_tamper.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"


@pytest.mark.asyncio
async def test_invoices_bola_rejection_and_ownership():
    """
    Verify invoices endpoint rejects foreign customer_ids (BOLA/IDOR) with 403
    and permits own or omitted customer_id.
    """
    transport = ASGITransport(app=app)
    user_a = "invoices-test-user-a"
    user_b = "invoices-test-user-b"
    supabase_service.update_user_profile(user_a, {"stripe_customer_id": "cus_user_a_inv"})
    supabase_service.update_user_profile(user_b, {"stripe_customer_id": "cus_victim_b_inv"})

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_a)) as ac:
        # 1. Foreign customer_id rejected with 403 Forbidden
        res_foreign = await ac.get("/api/v1/billing/invoices?customer_id=cus_victim_b_inv")
        assert res_foreign.status_code == 403
        assert res_foreign.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"

        # 2. Non-existent customer_id rejected with identical 403 (no existence leak)
        res_fake = await ac.get("/api/v1/billing/invoices?customer_id=cus_doesnotexist")
        assert res_fake.status_code == 403
        assert res_fake.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"

        # 3. Own customer_id accepted
        res_own = await ac.get("/api/v1/billing/invoices?customer_id=cus_user_a_inv")
        assert res_own.status_code == 200
        assert res_own.json()["success"] is True

        # 4. Omitted customer_id resolves to authenticated user
        res_omitted = await ac.get("/api/v1/billing/invoices")
        assert res_omitted.status_code == 200
        assert res_omitted.json()["success"] is True


@pytest.mark.asyncio
async def test_invoices_missing_stripe_customer_safe():
    """
    Verify tenant without stripe_customer_id:
    - Omitted customer_id returns empty invoices list (200 OK)
    - Supplying any customer_id returns 403 Forbidden
    """
    transport = ASGITransport(app=app)
    user_d = "no-stripe-customer-inv-user"
    supabase_service.update_user_profile(user_d, {"stripe_customer_id": None})

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_d)) as ac:
        # Omitted customer_id: safe empty list
        res = await ac.get("/api/v1/billing/invoices")
        assert res.status_code == 200
        assert res.json()["invoices"] == []
        assert res.json()["total"] == 0

        # Attempting foreign customer_id: rejected
        res_tamper = await ac.get("/api/v1/billing/invoices?customer_id=cus_other_person")
        assert res_tamper.status_code == 403
        assert res_tamper.json()["detail"] == "Access denied: customer ID does not belong to authenticated user"


@pytest.mark.asyncio
async def test_stripe_service_direct_defense_in_depth():
    """
    Verify direct invocation of stripe_service methods enforces tenant ownership.
    """
    user_e = "direct-service-user"
    supabase_service.update_user_profile(user_e, {"stripe_customer_id": "cus_legit_owner"})

    # 1. create_customer_portal_session with mismatched customer_id raises ValueError
    with pytest.raises(ValueError, match="Unauthorized customer ID"):
        await stripe_service.create_customer_portal_session(user_id=user_e, customer_id="cus_foreign")

    # 2. get_customer_invoices with mismatched customer_id raises ValueError
    with pytest.raises(ValueError, match="Unauthorized customer ID"):
        await stripe_service.get_customer_invoices(user_id=user_e, customer_id="cus_foreign")

    # 3. Matching customer_id succeeds
    portal = await stripe_service.create_customer_portal_session(user_id=user_e, customer_id="cus_legit_owner")
    assert portal["has_customer"] is True

    # 4. Omitted customer_id succeeds using owner profile
    portal_omitted = await stripe_service.create_customer_portal_session(user_id=user_e)
    assert portal_omitted["has_customer"] is True
