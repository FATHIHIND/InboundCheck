"""
InboundCheck - RBL Scanning API & Background Auditor Integration Tests
======================================================================
Verifies:
1. Rejection of unauthenticated requests (missing/invalid JWT Bearer token).
2. Anti-SSRF enforcement on user-supplied domains.
3. GET /rbl-status returns 404 on missing prior scan (no fabricated clean matrix).
4. POST /rbl-scan executes live scan and persists detailed evidence.
5. GET /rbl-status retrieves persisted scan data.
6. BackgroundAuditor stores measured scanner counts and status, never hardcoded 10/10.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
import dns.resolver

from app.main import app
from tests.conftest import auth_headers
from app.services.dns.rbl_scanner import rbl_scanner, RBLScanResult, RBLListingResult
from app.services.scheduler.background_auditor import BackgroundAuditor
from app.services.supabase_client import supabase_service
from app.services.dns.scorer import DeliverabilityScorer


@pytest.mark.asyncio
async def test_api_auth_enforcement():
    """Verify that both RBL endpoints reject unauthenticated requests."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. POST /rbl-scan unauthenticated
        res1 = await ac.post("/api/v1/dns/rbl-scan", json={"domain": "brandshop.com"})
        assert res1.status_code == 401

        # 2. GET /rbl-status unauthenticated
        res2 = await ac.get("/api/v1/dns/rbl-status?domain=brandshop.com")
        assert res2.status_code == 401


@pytest.mark.asyncio
async def test_api_ssrf_protection():
    """Verify Anti-SSRF protection blocks illegal targets."""
    transport = ASGITransport(app=app)
    headers = auth_headers("tenant-rbl-ssrf")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        # Loopback
        res = await ac.post("/api/v1/dns/rbl-scan", json={"domain": "127.0.0.1"})
        assert res.status_code == 400

        # AWS Metadata
        res = await ac.post("/api/v1/dns/rbl-scan", json={"domain": "169.254.169.254"})
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_rbl_status_404_when_no_scan_exists():
    """Verify GET /rbl-status returns 404 if domain has never been scanned."""
    transport = ASGITransport(app=app)
    headers = auth_headers("tenant-fresh-user")

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        res = await ac.get("/api/v1/dns/rbl-status?domain=unscanned-brand.com")
        assert res.status_code == 404
        assert "No RBL scan recorded" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_rbl_scan_and_status_roundtrip():
    """Verify POST /rbl-scan executes scan, persists it, and GET /rbl-status returns it."""
    transport = ASGITransport(app=app)
    headers = auth_headers("tenant-roundtrip-user")

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(side_effect=dns.resolver.NXDOMAIN)

    with patch.object(rbl_scanner, "_get_resolver", return_value=mock_resolver), \
         patch.object(rbl_scanner, "resolve_public_a_records", return_value=["198.51.100.25"]):

        async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
            # 1. POST scan
            scan_res = await ac.post("/api/v1/dns/rbl-scan", json={"domain": "roundtrip-brand.com"})
            assert scan_res.status_code == 200
            data = scan_res.json()

            assert data["domain"] == "roundtrip-brand.com"
            assert data["overall_status"] == "clean"
            assert data["rbl_clean_count"] == 10
            assert data["rbl_listed_count"] == 0
            assert len(data["results"]) == 10

            # 2. GET status returns the exact persisted scan
            status_res = await ac.get("/api/v1/dns/rbl-status?domain=roundtrip-brand.com")
            assert status_res.status_code == 200
            status_data = status_res.json()

            assert status_data["domain"] == "roundtrip-brand.com"
            assert status_data["rbl_clean_count"] == 10
            assert status_data["overall_status"] == "clean"


@pytest.mark.asyncio
async def test_background_auditor_stores_actual_scanner_counts():
    """Verify that BackgroundAuditor records actual measured scanner counts rather than 10/10."""
    auditor = BackgroundAuditor()

    # Prepopulate an active domain
    user_id = "user_bg_audit_test"
    supabase_service._in_memory_domains[user_id] = [{
        "id": "dom_bg_1",
        "domain_name": "bg-audit-test.com",
        "user_id": user_id,
        "is_active": True
    }]

    mock_scan_result = RBLScanResult(
        domain="bg-audit-test.com",
        resolved_ips=["198.51.100.50"],
        results=[],
        rbl_clean_count=8,
        rbl_listed_count=1,
        rbl_unknown_count=1,
        rbl_error_count=0,
        rbl_total_count=10,
        overall_status="listed",
        highest_severity="critical",
        execution_time_ms=45.2
    )

    with patch.object(supabase_service, "_client", None), \
         patch.object(rbl_scanner, "scan_domain", AsyncMock(return_value=mock_scan_result)), \
         patch.object(auditor.diagnostic_engine, "audit_domain", AsyncMock(return_value=(
             MagicMock(model_dump=lambda: {}),
             {},
             12.0
         ))), \
         patch.object(DeliverabilityScorer, "calculate_health_score", return_value=(95, "optimal", MagicMock(), [], [])):

        await auditor.run_audit_cycle()

        # Check reputation snapshots recorded
        snapshots = supabase_service._in_memory_reputation.get(user_id, [])
        assert len(snapshots) >= 1
        latest_snap = snapshots[-1]

        assert latest_snap["rbl_clean_count"] == 8
        assert latest_snap["rbl_listed_count"] == 1
        assert latest_snap["rbl_unknown_count"] == 1
        assert latest_snap["rbl_overall_status"] == "listed"
        assert latest_snap["predicted_risk_48h"] in ("critical", "high")
