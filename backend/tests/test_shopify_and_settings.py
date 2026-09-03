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
