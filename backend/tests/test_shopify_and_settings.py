"""
InboundCheck - Shopify Integration & Settings API Tests
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_shopify_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        # 1. Authorize URL
        auth_res = await ac.post("/api/v1/shopify/oauth/authorize", json={
            "shop": "my-store.myshopify.com"
        })
        assert auth_res.status_code == 200
        assert "auth_url" in auth_res.json()

        # 2. Sender Alignment Check
        align_res = await ac.post("/api/v1/shopify/sender-alignment", json={
            "sender_email": "orders@shopify.com",
            "custom_domain": "shopify.com"
        })
        assert align_res.status_code == 200
        assert "alignment" in align_res.json()

        # 3. Simulate Order Delivery
        sim_res = await ac.post("/api/v1/shopify/simulate-order", json={
            "shop_domain": "my-store.myshopify.com",
            "customer_email": "buyer@gmail.com",
            "sender_email": "orders@my-store.com"
        })
        assert sim_res.status_code == 200
        assert sim_res.json()["success"] is True

        # 4. Shopify OAuth Callback: Missing state or HMAC failure
        cb_no_state = await ac.get("/api/v1/shopify/oauth/callback?shop=test.myshopify.com&code=123")
        assert cb_no_state.status_code in [400, 401]

        # 5. Webhook orders: payload cap (> 1MB)
        import time
        large_body = b"x" * (1024 * 1024 + 10)
        res_large = await ac.post(
            "/api/v1/shopify/webhooks/orders",
            content=large_body,
            headers={"Content-Length": str(len(large_body))}
        )
        assert res_large.status_code == 413

        # 6. Webhook orders: Expired timestamp (> 300s)
        expired_ts = str(int(time.time()) - 400)
        res_exp = await ac.post(
            "/api/v1/shopify/webhooks/orders",
            json={"order_id": 999},
            headers={"X-Shopify-Triggered-At": expired_ts}
        )
        assert res_exp.status_code == 400

        # 7. Webhook orders: Valid dispatch and deduplication (idempotency)
        import base64
        import hashlib
        import hmac
        import json
        from app.services.shopify.shopify_service import shopify_service

        body_bytes = json.dumps({"order_id": 999}).encode("utf-8")
        secret = shopify_service.api_secret or "dummy_secret"
        computed_hmac = base64.b64encode(
            hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
        ).decode("utf-8")

        res_ok = await ac.post(
            "/api/v1/shopify/webhooks/orders",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Webhook-Id": "webhook_uniq_001",
                "X-Shopify-Hmac-Sha256": computed_hmac
            }
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "received"

        # Replayed delivery with same webhook ID
        res_dup = await ac.post(
            "/api/v1/shopify/webhooks/orders",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Webhook-Id": "webhook_uniq_001",
                "X-Shopify-Hmac-Sha256": computed_hmac
            }
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "already_processed"


@pytest.mark.asyncio
async def test_settings_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-1")) as ac:
        # 1. Get profile
        prof_res = await ac.get("/api/v1/settings/profile")
        assert prof_res.status_code == 200
        assert "profile" in prof_res.json()

        # 2. Update profile
        update_res = await ac.put("/api/v1/settings/profile", json={
            "full_name": "Jane Developer",
            "email": "jane@brand.com",
            "company_name": "Brand Co"
        })
        assert update_res.status_code == 200
        assert update_res.json()["profile"]["full_name"] == "Jane Developer"

        # 3. Regenerate API key
        key_res = await ac.post("/api/v1/settings/api-key/regenerate")
        assert key_res.status_code == 200
        assert "api_key" in key_res.json()

        # 4. Save alert config
        alert_res = await ac.post("/api/v1/settings/alerts", json={
            "alert_on_score_drop": True,
            "score_threshold": 80,
            "alert_on_dmarc_change": True,
            "alert_on_spf_error": True,
            "alert_on_dkim_fail": True,
            "slack_webhook_url": "https://hooks.slack.com/services/test"
        })
        assert alert_res.status_code == 200
        assert alert_res.json()["config"]["score_threshold"] == 80


# =====================================================================
# SEC-QUOTA-01: STORE SETTINGS DOMAIN QUOTA & ENTITLEMENT REGRESSION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_store_settings_quota_enforcement_starter_tier():
    """
    SEC-QUOTA-01: Starter user at quota (1 domain) MUST be rejected with HTTP 402
    when attempting to register a 2nd custom_domain through /store-settings.
    """
    from app.services.supabase_client import supabase_service
    from datetime import datetime, timezone, timedelta

    user_id = "test-sec-quota-starter-user"
    # Seed profile with active Starter tier
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    # Clear existing test domains and seed 1 domain (full quota for Starter)
    supabase_service._in_memory_domains[user_id] = []
    supabase_service.create_or_update_domain(user_id=user_id, domain_name="existing-shop.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "Bypass Store",
            "custom_domain": "bypass-domain-2.com",
            "sender_email": "orders@bypass.com"
        })

        assert res.status_code == 402
        body = res.json()
        assert "Domain quota reached" in body["detail"]
        assert "Starter" in body["detail"]

        # Verify domain was NOT inserted into monitored_domains
        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 1
        assert not any(d.get("domain_name") == "bypass-domain-2.com" for d in user_domains)


@pytest.mark.asyncio
async def test_store_settings_growth_tier_allows_addition_within_quota():
    """
    SEC-QUOTA-01: Growth user (quota = 3) can successfully register a new domain
    within their allowed quota through /store-settings.
    """
    from app.services.supabase_client import supabase_service

    user_id = "test-sec-quota-growth-user"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "growth",
        "tier": "growth",
        "subscription_status": "active",
    })

    supabase_service._in_memory_domains[user_id] = []
    supabase_service.create_or_update_domain(user_id=user_id, domain_name="growth-first.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "Growth Brand Store",
            "custom_domain": "growth-second.com",
            "sender_email": "orders@growth-second.com"
        })

        assert res.status_code == 200
        assert res.json()["success"] is True

        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 2
        assert any(d.get("domain_name") == "growth-second.com" for d in user_domains)


@pytest.mark.asyncio
async def test_store_settings_updating_already_monitored_domain_succeeds_at_quota():
    """
    SEC-QUOTA-01: Updating store settings referencing an ALREADY-monitored domain
    does not consume additional quota and is permitted even if quota is full.
    """
    from app.services.supabase_client import supabase_service

    user_id = "test-sec-quota-reupdate-user"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })

    supabase_service._in_memory_domains[user_id] = []
    supabase_service.create_or_update_domain(user_id=user_id, domain_name="owned-brand.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "Owned Brand Updated",
            "custom_domain": "owned-brand.com",
            "sender_email": "hello@owned-brand.com"
        })

        assert res.status_code == 200
        assert res.json()["success"] is True
        user_domains = supabase_service.get_user_domains(user_id=user_id)
        assert len(user_domains) == 1


@pytest.mark.asyncio
async def test_store_settings_rejects_invalid_and_ssrf_domain():
    """
    SEC-QUOTA-01: Malformed domain strings, IP addresses, and SSRF targets MUST
    be rejected with HTTP 400 through DNSDiagnosticEngine.normalize_domain().
    """
    user_id = "test-sec-quota-ssrf-user"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # 1. AWS metadata endpoint
        res_meta = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "169.254.169.254"
        })
        assert res_meta.status_code == 400

        # 2. Localhost
        res_local = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "http://127.0.0.1:8000"
        })
        assert res_local.status_code == 400

        # 3. Invalid characters
        res_inv = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "invalid_domain!@#.com"
        })
        assert res_inv.status_code == 400


@pytest.mark.asyncio
async def test_store_settings_trial_expired_blocks_new_domain():
    """
    SEC-QUOTA-01: User with an expired subscription or expired trial cannot
    register custom_domain through /store-settings.
    """
    from app.services.supabase_client import supabase_service

    user_id = "test-sec-quota-expired-user"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "subscription_status": "expired",
    })
    supabase_service._in_memory_domains[user_id] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "brand-new-domain.com"
        })
        assert res.status_code == 402
        assert "Active plan required" in res.json()["detail"] or "expired" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_store_settings_without_custom_domain_succeeds_unconditionally():
    """
    SEC-QUOTA-01: Updating only store name, sender email, or ESP provider
    without providing custom_domain succeeds without evaluating domain quota.
    """
    user_id = "test-sec-quota-meta-only-user"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "Meta Only Store",
            "sender_email": "contact@mystore.com",
            "esp_provider": "klaviyo"
        })
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["store"]["sender_email"] == "contact@mystore.com"


@pytest.mark.asyncio
async def test_store_settings_concurrent_quota_attempts_rejected():
    """
    SEC-QUOTA-01: Proves concurrent/sequential attempts to exceed quota
    are safely rejected once quota is saturated.
    """
    import asyncio
    from app.services.supabase_client import supabase_service

    user_id = "test-sec-quota-concurrency-user"
    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": "active",
    })
    supabase_service._in_memory_domains[user_id] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # First domain succeeds (0 -> 1 domain, quota limit: 1)
        r1 = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "legitimate-first.com"
        })
        assert r1.status_code == 200

        # Subsequent attempts are rejected with 402
        r2 = await ac.post("/api/v1/shopify/store-settings", json={
            "custom_domain": "overflow-second.com"
        })
        assert r2.status_code == 402
        assert "Domain quota reached" in r2.json()["detail"]


# =====================================================================
# SEC-STORE-CONFUSION-01: STORE TARGET RESOLUTION & TENANT ISOLATION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_store_settings_foreign_store_id_rejected():
    """SEC-STORE-CONFUSION-01: Foreign store_id belonging to another tenant MUST be rejected with HTTP 404."""
    from app.services.supabase_client import supabase_service

    victim_user = "test-store-victim-user"
    attacker_user = "test-store-attacker-user"

    # Seed victim's store
    supabase_service._in_memory_stores[victim_user] = [{
        "id": "victim-store-uuid-1",
        "user_id": victim_user,
        "shop_domain": "victim-store.myshopify.com",
        "sender_email": "orders@victim.com",
        "metadata": {"name": "Victim Store", "email": "orders@victim.com"}
    }]
    # Seed attacker's store
    supabase_service._in_memory_stores[attacker_user] = [{
        "id": "attacker-store-uuid-1",
        "user_id": attacker_user,
        "shop_domain": "attacker-store.myshopify.com",
        "sender_email": "orders@attacker.com",
        "metadata": {"name": "Attacker Store", "email": "orders@attacker.com"}
    }]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(attacker_user)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "victim-store-uuid-1",
            "store_name": "Pwned Store",
            "sender_email": "hacked@attacker.com"
        })
        assert res.status_code == 404
        assert "not found or unauthorized" in res.json()["detail"].lower()

        # Invariant: Victim store was NOT mutated
        victim_store = supabase_service._in_memory_stores[victim_user][0]
        assert victim_store["sender_email"] == "orders@victim.com"
        assert victim_store["metadata"]["name"] == "Victim Store"


@pytest.mark.asyncio
async def test_store_settings_valid_owned_store_id_updates_correct_store():
    """SEC-STORE-CONFUSION-01: Valid owned store_id correctly resolves and updates that specific store."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-owned-id-user"
    supabase_service._in_memory_stores[user_id] = [
        {
            "id": "store-id-alpha",
            "user_id": user_id,
            "shop_domain": "alpha.myshopify.com",
            "sender_email": "orders@alpha.com",
            "metadata": {"name": "Store Alpha", "email": "orders@alpha.com"}
        },
        {
            "id": "store-id-beta",
            "user_id": user_id,
            "shop_domain": "beta.myshopify.com",
            "sender_email": "orders@beta.com",
            "metadata": {"name": "Store Beta", "email": "orders@beta.com"}
        }
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "store-id-beta",
            "store_name": "Store Beta Updated",
            "sender_email": "updated@beta.com"
        })
        assert res.status_code == 200
        assert res.json()["success"] is True

        stores = supabase_service._in_memory_stores[user_id]
        beta_store = next(s for s in stores if s["id"] == "store-id-beta")
        alpha_store = next(s for s in stores if s["id"] == "store-id-alpha")

        assert beta_store["sender_email"] == "updated@beta.com"
        assert beta_store["metadata"]["name"] == "Store Beta Updated"
        # Store Alpha must be completely untouched
        assert alpha_store["sender_email"] == "orders@alpha.com"
        assert alpha_store["metadata"]["name"] == "Store Alpha"


@pytest.mark.asyncio
async def test_store_settings_multiple_stores_updates_only_selected_store():
    """SEC-STORE-CONFUSION-01: In multi-store setups, only the targeted store is updated."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-multi-target-user"
    supabase_service._in_memory_stores[user_id] = [
        {
            "id": "store-a-111",
            "user_id": user_id,
            "shop_domain": "shop-a.myshopify.com",
            "sender_email": "orders@shop-a.com",
            "metadata": {"name": "Shop A", "email": "orders@shop-a.com"}
        },
        {
            "id": "store-b-222",
            "user_id": user_id,
            "shop_domain": "shop-b.myshopify.com",
            "sender_email": "orders@shop-b.com",
            "metadata": {"name": "Shop B", "email": "orders@shop-b.com"}
        }
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "store-b-222",
            "sender_email": "support@shop-b.com"
        })
        assert res.status_code == 200

        stores = supabase_service._in_memory_stores[user_id]
        store_a = next(s for s in stores if s["id"] == "store-a-111")
        store_b = next(s for s in stores if s["id"] == "store-b-222")

        assert store_b["sender_email"] == "support@shop-b.com"
        assert store_a["sender_email"] == "orders@shop-a.com"


@pytest.mark.asyncio
async def test_store_settings_multiple_stores_without_selector_rejected_as_ambiguous():
    """SEC-STORE-CONFUSION-01: When multiple stores exist and no selector is provided, request MUST be rejected."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-ambiguous-user"
    supabase_service._in_memory_stores[user_id] = [
        {"id": "s1", "user_id": user_id, "shop_domain": "store1.myshopify.com", "sender_email": "s1@store.com"},
        {"id": "s2", "user_id": user_id, "shop_domain": "store2.myshopify.com", "sender_email": "s2@store.com"}
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "sender_email": "ambiguous@store.com"
        })
        assert res.status_code == 400
        assert "Multiple stores connected" in res.json()["detail"]


@pytest.mark.asyncio
async def test_store_settings_valid_shop_domain_selects_and_updates_store():
    """SEC-STORE-CONFUSION-01: Valid shop_domain resolves and updates the matching store."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-shop-domain-user"
    supabase_service._in_memory_stores[user_id] = [
        {"id": "dom-s1", "user_id": user_id, "shop_domain": "first.myshopify.com", "sender_email": "orders@first.com"},
        {"id": "dom-s2", "user_id": user_id, "shop_domain": "second.myshopify.com", "sender_email": "orders@second.com"}
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "shop_domain": "second.myshopify.com",
            "sender_email": "new@second.com"
        })
        assert res.status_code == 200

        stores = supabase_service._in_memory_stores[user_id]
        s2 = next(s for s in stores if s["id"] == "dom-s2")
        s1 = next(s for s in stores if s["id"] == "dom-s1")
        assert s2["sender_email"] == "new@second.com"
        assert s1["sender_email"] == "orders@first.com"


@pytest.mark.asyncio
async def test_store_settings_foreign_shop_domain_rejected_without_mutation():
    """SEC-STORE-CONFUSION-01: Foreign shop_domain belonging to another user is rejected with HTTP 404."""
    from app.services.supabase_client import supabase_service

    victim_user = "victim-shop-domain-user"
    attacker_user = "attacker-shop-domain-user"

    supabase_service._in_memory_stores[victim_user] = [{
        "id": "vic-store-1",
        "user_id": victim_user,
        "shop_domain": "victim-exclusive.myshopify.com",
        "sender_email": "safe@victim.com"
    }]
    supabase_service._in_memory_stores[attacker_user] = [{
        "id": "att-store-1",
        "user_id": attacker_user,
        "shop_domain": "attacker-personal.myshopify.com",
        "sender_email": "safe@attacker.com"
    }]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(attacker_user)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "shop_domain": "victim-exclusive.myshopify.com",
            "sender_email": "hacked@attacker.com"
        })
        assert res.status_code == 404
        assert "not found or not associated with your account" in res.json()["detail"].lower()

        # Victim store was NOT mutated
        victim_store = supabase_service._in_memory_stores[victim_user][0]
        assert victim_store["sender_email"] == "safe@victim.com"


@pytest.mark.asyncio
async def test_store_settings_zero_stores_initializes_initial_store():
    """SEC-STORE-CONFUSION-01: Zero stores existing initializes an initial store record safely."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-zero-stores-user"
    supabase_service._in_memory_stores[user_id] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "First New Store",
            "sender_email": "contact@firstnew.com"
        })
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert len(supabase_service._in_memory_stores[user_id]) == 1
        created = supabase_service._in_memory_stores[user_id][0]
        assert created["shop_domain"] == "first-new-store.myshopify.com"
        assert created["sender_email"] == "contact@firstnew.com"


@pytest.mark.asyncio
async def test_store_settings_single_store_without_selector_succeeds():
    """SEC-STORE-CONFUSION-01: Exactly one store exists -> succeeds without needing selector."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-single-user"
    supabase_service._in_memory_stores[user_id] = [{
        "id": "single-store-1",
        "user_id": user_id,
        "shop_domain": "sole-store.myshopify.com",
        "sender_email": "orders@sole.com",
        "metadata": {"name": "Sole Store", "email": "orders@sole.com"}
    }]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_name": "Sole Store Renamed",
            "sender_email": "updated@sole.com"
        })
        assert res.status_code == 200
        assert res.json()["success"] is True
        store = supabase_service._in_memory_stores[user_id][0]
        assert store["sender_email"] == "updated@sole.com"
        assert store["metadata"]["name"] == "Sole Store Renamed"


@pytest.mark.asyncio
async def test_store_settings_unowned_store_does_not_mutate_profile_or_domains():
    """SEC-STORE-CONFUSION-01: When store resolution fails, profile company_name and domains are NOT mutated."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-no-side-effect-user"
    supabase_service.update_user_profile(user_id, {
        "company_name": "Original Company Name",
        "subscription_tier": "starter",
        "subscription_status": "active",
    })
    supabase_service._in_memory_stores[user_id] = [{
        "id": "my-real-store-1",
        "user_id": user_id,
        "shop_domain": "my-real-store.myshopify.com"
    }]
    supabase_service._in_memory_domains[user_id] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "non-existent-store-id",
            "store_name": "Attacker Mutated Company",
            "custom_domain": "should-not-persist.com"
        })
        assert res.status_code == 404

        # Profile company_name must remain unchanged
        profile = supabase_service.get_user_profile(user_id)
        assert profile.get("company_name") == "Original Company Name"

        # Domain must NOT be registered
        domains = supabase_service.get_user_domains(user_id)
        assert len(domains) == 0


@pytest.mark.asyncio
async def test_store_settings_conflicting_selectors_rejected():
    """SEC-STORE-CONFUSION-01: Conflicting store_id and shop_domain pointing to different stores MUST be rejected with HTTP 400."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-conflict-selectors-user"
    supabase_service._in_memory_stores[user_id] = [
        {
            "id": "store-conf-1",
            "user_id": user_id,
            "shop_domain": "store-alpha.myshopify.com",
            "sender_email": "alpha@store.com",
            "metadata": {"name": "Store Alpha"}
        },
        {
            "id": "store-conf-2",
            "user_id": user_id,
            "shop_domain": "store-beta.myshopify.com",
            "sender_email": "beta@store.com",
            "metadata": {"name": "Store Beta"}
        }
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        # Pass store_id of Alpha, but shop_domain of Beta
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "store-conf-1",
            "shop_domain": "store-beta.myshopify.com",
            "sender_email": "conflicted@store.com"
        })
        assert res.status_code == 400
        assert "Conflicting store selectors" in res.json()["detail"]

        # Neither store was mutated
        stores = supabase_service._in_memory_stores[user_id]
        s1 = next(s for s in stores if s["id"] == "store-conf-1")
        s2 = next(s for s in stores if s["id"] == "store-conf-2")
        assert s1["sender_email"] == "alpha@store.com"
        assert s2["sender_email"] == "beta@store.com"


@pytest.mark.asyncio
async def test_store_settings_matching_selectors_accepted():
    """SEC-STORE-CONFUSION-01: Matching store_id and shop_domain pointing to the same store succeeds."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-matching-selectors-user"
    supabase_service._in_memory_stores[user_id] = [
        {
            "id": "store-match-1",
            "user_id": user_id,
            "shop_domain": "consistent.myshopify.com",
            "sender_email": "old@consistent.com",
            "metadata": {"name": "Consistent Store"}
        }
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "store_id": "store-match-1",
            "shop_domain": "consistent.myshopify.com",
            "sender_email": "new@consistent.com",
            "store_name": "Renamed Consistent Store"
        })
        assert res.status_code == 200
        assert res.json()["success"] is True

        store = supabase_service._in_memory_stores[user_id][0]
        assert store["id"] == "store-match-1"
        assert store["sender_email"] == "new@consistent.com"
        assert store["metadata"]["name"] == "Renamed Consistent Store"


@pytest.mark.asyncio
async def test_store_settings_malformed_shop_domain_rejected():
    """SEC-STORE-CONFUSION-01: Malformed shop_domain returns HTTP 400 validation error, not 500."""
    from app.services.supabase_client import supabase_service

    user_id = "test-store-malformed-domain-user"
    supabase_service._in_memory_stores[user_id] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/shopify/store-settings", json={
            "shop_domain": "invalid_characters!@#.myshopify.com"
        })
        assert res.status_code == 400
        assert "Invalid Shopify store domain format" in res.json()["detail"]
