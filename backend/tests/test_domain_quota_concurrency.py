"""
InboundCheck - SEC-QUOTA-01 Atomic Domain Quota Concurrency Tests
================================================================
Validates atomic database-level quota enforcement, eliminating TOCTOU race
conditions under true concurrent load (asyncio.gather).
"""

import pytest
import asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from app.main import app
from app.services.supabase_client import supabase_service, QuotaExceededError, DatabaseUnavailableError
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def clean_memory():
    """Ensure clean in-memory state for test isolation."""
    supabase_service._in_memory_domains.clear()
    supabase_service._in_memory_profiles.clear()
    supabase_service._in_memory_stores.clear()
    yield


@pytest.mark.asyncio
async def test_concurrent_domain_provisioning_starter_tier_toctou_prevented():
    """
    SEC-QUOTA-01: Starter tenant (quota = 1) fires 5 simultaneous requests
    for 5 distinct domains. Exactly 1 MUST succeed (HTTP 200) and exactly 4
    MUST be rejected (HTTP 402). Final tenant domain count MUST be exactly 1.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    domains_to_test = [
        f"domain-burst-{i}-{uuid.uuid4().hex[:6]}.com"
        for i in range(5)
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        tasks = [
            ac.post("/api/v1/domains", json={"domain": dom})
            for dom in domains_to_test
        ]

        # Fire all 5 requests concurrently
        responses = await asyncio.gather(*tasks)

        status_codes = [r.status_code for r in responses]
        success_count = status_codes.count(200)
        quota_rejected_count = status_codes.count(402)

        assert success_count == 1, f"Expected exactly 1 success, got {success_count}. Statuses: {status_codes}"
        assert quota_rejected_count == 4, f"Expected exactly 4 quota rejections, got {quota_rejected_count}"

        # Final database state verification
        user_domains = supabase_service.get_user_domains(user_id=user_id, limit=100)
        assert len(user_domains) == 1, f"Expected exactly 1 domain in DB, found {len(user_domains)}"


@pytest.mark.asyncio
async def test_idempotent_resubmission_at_max_quota():
    """
    SEC-QUOTA-01: An already-owned domain re-submitted when tenant is at max quota (1/1)
    MUST succeed (HTTP 200) and NOT consume an additional quota slot.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    domain_name = "already-owned-domain.com"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # First creation -> succeeds (1/1)
        r1 = await ac.post("/api/v1/domains", json={"domain": domain_name})
        assert r1.status_code == 200

        # Re-submission of the SAME domain -> succeeds (does not consume extra slot)
        r2 = await ac.post("/api/v1/domains", json={"domain": domain_name})
        assert r2.status_code == 200

        # Re-submission via shopify store-settings -> also succeeds
        r3 = await ac.post("/api/v1/shopify/store-settings", json={"custom_domain": domain_name})
        assert r3.status_code == 200

        # Database state: still exactly 1 domain
        user_domains = supabase_service.get_user_domains(user_id=user_id, limit=100)
        assert len(user_domains) == 1


@pytest.mark.asyncio
async def test_multi_tenant_concurrent_isolation():
    """
    SEC-QUOTA-01: Two different tenants concurrently provision domains.
    Both MUST succeed independently without deadlock or cross-tenant interference.
    """
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    for uid in (user_a, user_b):
        supabase_service.update_user_profile(uid, {
            "subscription_tier": "starter",
            "tier": "starter",
            "subscription_status": "active",
        })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        task_a = ac.post("/api/v1/domains", json={"domain": "brand-alpha.com"}, headers=auth_headers(user_a))
        task_b = ac.post("/api/v1/domains", json={"domain": "brand-beta.com"}, headers=auth_headers(user_b))

        res_a, res_b = await asyncio.gather(task_a, task_b)

        assert res_a.status_code == 200
        assert res_b.status_code == 200

        domains_a = supabase_service.get_user_domains(user_id=user_a)
        domains_b = supabase_service.get_user_domains(user_id=user_b)
        assert len(domains_a) == 1
        assert len(domains_b) == 1
        assert domains_a[0]["domain_name"] == "brand-alpha.com"
        assert domains_b[0]["domain_name"] == "brand-beta.com"


@pytest.mark.asyncio
async def test_growth_tier_boundary_enforcement():
    """
    SEC-QUOTA-01: Growth tier allows exactly 3 domains.
    4th distinct domain MUST be rejected with HTTP 402.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "growth",
        "tier": "growth",
        "subscription_status": "active",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        for i in range(3):
            res = await ac.post("/api/v1/domains", json={"domain": f"growth-domain-{i}.com"})
            assert res.status_code == 200, f"Domain {i} should succeed on Growth tier"

        # 4th domain exceeds quota
        res_4 = await ac.post("/api/v1/domains", json={"domain": "overflow-fourth.com"})
        assert res_4.status_code == 402
        assert "Domain quota reached" in res_4.json()["detail"]

        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 3


@pytest.mark.asyncio
async def test_agency_tier_capacity():
    """
    SEC-QUOTA-01: Agency tier allows up to 20 domains (highest commercial tier).
    Multiple distinct domains provision without rejection up to limit.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "agency",
        "tier": "agency",
        "subscription_status": "active",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        for i in range(5):
            res = await ac.post("/api/v1/domains", json={"domain": f"agency-brand-{i}.com"})
            assert res.status_code == 200

        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 5


@pytest.mark.asyncio
async def test_legacy_enterprise_profile_resolves_to_agency_domain_capacity():
    """
    SEC-QUOTA-01: Legacy server-side profiles with 'enterprise' tier safely resolve
    to Agency limits (20 domains), preventing fallback to Starter (1 domain)
    while eliminating the deprecated 999-domain ceiling.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "enterprise",
        "tier": "enterprise",
        "subscription_status": "active",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # User can add multiple domains beyond Starter limit (1)
        for i in range(3):
            res = await ac.post("/api/v1/domains", json={"domain": f"legacy-ent-brand-{i}.com"})
            assert res.status_code == 200

        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 3


@pytest.mark.asyncio
async def test_provisioning_fails_closed_on_rpc_database_failure():
    """
    SEC-QUOTA-01: When database RPC fails or is unavailable in production,
    the endpoint MUST fail closed (HTTP 500) and NOT create any rogue domain.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    transport = ASGITransport(app=app)
    with patch.object(supabase_service, "provision_monitored_domain", side_effect=DatabaseUnavailableError("Simulated DB connection failure")):
        async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
            res = await ac.post("/api/v1/domains", json={"domain": "unreachable-db.com"})
            assert res.status_code == 500
            assert "Failed to add monitored domain" in res.json()["detail"]

    # Verify no rogue domain persisted
    user_domains = supabase_service.get_user_domains(user_id=user_id)
    assert len(user_domains) == 0


@pytest.mark.asyncio
async def test_shopify_store_settings_concurrent_toctou_prevented():
    """
    SEC-QUOTA-01: Concurrent /shopify/store-settings requests targeting distinct
    custom sending domains are atomically capped to plan quota.
    """
    user_id = str(uuid.uuid4())
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        t1 = ac.post("/api/v1/shopify/store-settings", json={"custom_domain": "shopify-brand-a.com"})
        t2 = ac.post("/api/v1/shopify/store-settings", json={"custom_domain": "shopify-brand-b.com"})

        res1, res2 = await asyncio.gather(t1, t2)

        statuses = [res1.status_code, res2.status_code]
        assert 200 in statuses
        assert 402 in statuses

        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 1
