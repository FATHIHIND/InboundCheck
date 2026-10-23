"""
InboundCheck - GoDaddy DNS Truthful Capability & Regression Test Suite
=====================================================================
Validates Phase Truthful DNS Capability Alignment:
1. GoDaddy credentials cannot receive a false "verified" result from /verify.
2. GoDaddy auto-fix cannot reach Cloudflare mutation functions or execute DNS mutations.
3. Existing Cloudflare auto-fix behavior remains 100% intact and functional.
4. Customer-facing copy (landing page, dashboard, billing, paywall) does not claim live GoDaddy API mutation.
5. Inspector UI does not present unsupported "Auto-Insert to GoDaddy" direct mutation actions.
"""

import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.dns.auto_fixer import dns_auto_fixer
from app.services.dns.cloudflare_client import cloudflare_client
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend" / "src" / "app"


@pytest.fixture(autouse=True)
def isolate_supabase_state():
    """Ensure in-memory state is isolated between test runs."""
    orig_client = supabase_service._client
    supabase_service._client = None
    supabase_service._in_memory_dns_provider_creds.clear()
    supabase_service._in_memory_dns_auto_fix_logs.clear()
    supabase_service._in_memory_domains.clear()
    yield
    supabase_service._client = orig_client
    supabase_service._in_memory_dns_provider_creds.clear()
    supabase_service._in_memory_dns_auto_fix_logs.clear()
    supabase_service._in_memory_domains.clear()


# =====================================================================
# 1. GODADDY CREDENTIAL VERIFICATION CANNOT RECEIVE FALSE SUCCESS
# =====================================================================

@pytest.mark.asyncio
async def test_godaddy_credential_verification_returns_unsupported():
    """Verify that submitting GoDaddy credentials to /verify fails with HTTP 400 and clear explanation."""
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/dns/auto-fix/verify", json={
            "provider_name": "godaddy",
            "token_or_key": "some_api_key:some_api_secret",
        })

        assert res.status_code == 400
        data = res.json()
        assert "Direct GoDaddy API verification is currently unsupported" in data["detail"]
        assert "Cloudflare" in data["detail"]
        assert "manual DNS" in data["detail"]


# =====================================================================
# 2. GODADDY AUTO-FIX CANNOT REACH CLOUDFLARE MUTATION FUNCTIONS
# =====================================================================

@pytest.mark.asyncio
async def test_godaddy_auto_fix_rejected_without_calling_cloudflare_client():
    """Verify that applying an auto-fix with provider_name='godaddy' rejects before Cloudflare client calls."""
    user_id = str(uuid.uuid4())
    domain = "godaddy-test-store.com"
    host = "_dmarc.godaddy-test-store.com"
    val = "v=DMARC1; p=reject;"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)

    with patch.object(cloudflare_client, "create_dns_record", new=AsyncMock()) as mock_create, \
         patch.object(cloudflare_client, "update_dns_record", new=AsyncMock()) as mock_update, \
         patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock()) as mock_get_zone:

        result = await dns_auto_fixer.apply_dns_fix(
            user_id=user_id,
            domain_name=domain,
            provider_name="godaddy",
            record_type="TXT",
            host=host,
            record_value=val,
        )

        assert result["applied"] is False
        assert "Direct DNS automated remediation is not supported for provider 'godaddy'" in result["error"]
        assert result["fix_entry"]["status"] == "failed"

        # Cloudflare mutations must NEVER be called
        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_get_zone.assert_not_called()


@pytest.mark.asyncio
async def test_godaddy_auto_fix_via_rest_api_returns_http_400():
    """Verify that POST /api/v1/dns/auto-fix/apply with provider_name='godaddy' returns HTTP 400 Bad Request."""
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    domain = "godaddy-api-store.com"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)

    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers(user_id)) as ac:
        res = await ac.post("/api/v1/dns/auto-fix/apply", json={
            "domain_name": domain,
            "provider_name": "godaddy",
            "record_type": "TXT",
            "host": f"_dmarc.{domain}",
            "record_value": "v=DMARC1; p=quarantine;",
        })

        assert res.status_code == 400
        data = res.json()
        assert data["success"] is False
        assert data["applied"] is False
        assert "Direct DNS automated remediation is not supported for provider 'godaddy'" in data["error"]


# =====================================================================
# 3. CLOUDFLARE AUTO-FIX BEHAVIOR REMAINS FULLY FUNCTIONAL
# =====================================================================

@pytest.mark.asyncio
async def test_cloudflare_auto_fix_behavior_preserved():
    """Verify that valid Cloudflare auto-fix continues to execute, create records, and verify."""
    user_id = str(uuid.uuid4())
    domain = "cf-preserved-store.com"
    host = "_dmarc.cf-preserved-store.com"
    val = "v=DMARC1; p=reject;"

    supabase_service.update_user_profile(user_id, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(user_id, domain)
    dns_auto_fixer.save_credentials(user_id, "cloudflare", "cf-valid-token-1234", "cf-zone-123")

    mock_zone = {"zone_id": "cf-zone-123", "name": domain}
    mock_created = {"id": "rec_cf_999", "type": "TXT", "name": host, "content": val, "ttl": 3600}

    with patch.object(cloudflare_client, "get_zone_by_domain", new=AsyncMock(return_value=mock_zone)), \
         patch.object(cloudflare_client, "get_dns_record", new=AsyncMock(side_effect=[None, mock_created])), \
         patch.object(cloudflare_client, "create_dns_record", new=AsyncMock(return_value=mock_created)) as mock_create:

        result = await dns_auto_fixer.apply_dns_fix(
            user_id=user_id,
            domain_name=domain,
            provider_name="cloudflare",
            record_type="TXT",
            host=host,
            record_value=val,
        )

        assert result["applied"] is True
        assert result["verified"] is True
        mock_create.assert_awaited_once()


# =====================================================================
# 4. CUSTOMER-FACING COPY DOES NOT CLAIM GODADDY API MUTATION
# =====================================================================

def test_marketing_and_pricing_claims_do_not_advertise_godaddy_direct_api():
    """Verify customer-facing pages do not claim GoDaddy direct API auto-fix or sub-5s mutation."""
    files_to_check = [
        FRONTEND_DIR / "page.tsx",
        FRONTEND_DIR / "dashboard" / "page.tsx",
        FRONTEND_DIR / "dashboard" / "billing" / "page.tsx",
        ROOT_DIR / "frontend" / "src" / "components" / "billing" / "ObsidianPaywallModal.tsx",
        FRONTEND_DIR / "terms" / "page.tsx",
        FRONTEND_DIR / "privacy" / "page.tsx",
        FRONTEND_DIR / "security" / "page.tsx",
    ]

    prohibited_patterns = [
        "1-click cloudflare & godaddy",
        "1-click cloudflare and godaddy",
        "cloudflare & godaddy apis",
        "cloudflare and godaddy apis",
        "direct cloudflare & godaddy api",
        "direct cloudflare and godaddy api",
        "godaddy dns auto-fix",
        "godaddy zone auto-patch",
        "connect your cloudflare api token or godaddy key",
    ]

    for f in files_to_check:
        assert f.exists(), f"Expected file not found: {f}"
        content = f.read_text(encoding="utf-8").lower()
        for pattern in prohibited_patterns:
            assert pattern not in content, f"Found prohibited claim '{pattern}' in {f.name}!"


# =====================================================================
# 5. INSPECTOR UI DOES NOT PRESENT AUTO-INSERT TO GODADDY ACTION
# =====================================================================

def test_inspector_does_not_offer_godaddy_direct_auto_insert():
    """Verify inspector UI has no 'Auto-Insert to GoDaddy' action button."""
    inspector_file = FRONTEND_DIR / "dashboard" / "inspector" / "page.tsx"
    assert inspector_file.exists()

    content = inspector_file.read_text(encoding="utf-8")
    assert "Auto-Insert to GoDaddy" not in content
    assert 'Auto-Insert to {activeProviderName === "godaddy" ? "GoDaddy" : "Cloudflare"}' not in content
