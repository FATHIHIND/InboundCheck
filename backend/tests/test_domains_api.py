"""
InboundCheck - Domains API & Supabase Service Tests
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_domains_api_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers("test-user-999")) as ac:
        # 1. List initial domains
        res = await ac.get("/api/v1/domains")
        assert res.status_code == 200
        domains = res.json()
        assert isinstance(domains, list)

        # 2. Add new domain
        add_res = await ac.post("/api/v1/domains", json={
            "domain": "test-store.myshopify.com"
        })
        assert add_res.status_code == 200
        add_data = add_res.json()
        assert add_data["success"] is True
        created_id = add_data["domain"]["id"]

        # 3. Re-audit domain
        audit_res = await ac.post(f"/api/v1/domains/{created_id}/audit?domain_name=test-store.myshopify.com")
        assert audit_res.status_code == 200
        assert audit_res.json()["success"] is True

        # 4. Delete domain
        del_res = await ac.delete(f"/api/v1/domains/{created_id}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True
