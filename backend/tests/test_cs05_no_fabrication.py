"""
CS-05 regression tests: DNS auto-fix must never report success it did not get
from Cloudflare.

Covers the removed defects:
  * simulated success (rec_sim_) and skipped calls for tokens containing "test"/"mock";
  * test-double detection in production code (httpx/AsyncMock checks);
  * a Cloudflare 2xx response without a record id counted as applied;
  * a hard-coded fallback zone id used for mutations;
  * rollback reported as successful without calling Cloudflare.

Environment is "development" (non-production, in-memory persistence allowed).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.services.dns.auto_fixer import dns_auto_fixer_service
from app.services.supabase_client import supabase_service

USER = "cs05-user"
DOMAIN = "cs05-example.com"
NON_PROD = "development"


@pytest.fixture(autouse=True)
def _cloudflare_lookups_stubbed(monkeypatch):
    """Zone and record lookups never reach the network; mutations use the real transport."""
    monkeypatch.setattr(dns_auto_fixer_service.cloudflare, "get_zone_by_domain", AsyncMock(return_value={"zone_id": "zone-stub-000"}))
    monkeypatch.setattr(dns_auto_fixer_service.cloudflare, "get_dns_record", AsyncMock(return_value=None))


@pytest.fixture
def owned_domain():
    supabase_service.update_user_profile(USER, {"subscription_tier": "growth", "subscription_status": "active"})
    supabase_service.create_or_update_domain(USER, DOMAIN)
    return DOMAIN


def _json_response(status_code, payload):
    res = MagicMock()
    res.status_code = status_code
    res.headers = {"content-type": "application/json"}
    res.json.return_value = payload
    res.text = str(payload)
    return res


async def _apply(domain):
    return await dns_auto_fixer_service.apply_dns_fix(
        user_id=USER,
        domain_name=domain,
        record_type="TXT",
        host="@",
        record_value="v=spf1 -all",
        provider_name="cloudflare",
    )


@pytest.mark.asyncio
async def test_token_containing_test_is_used_for_a_real_call_not_simulated(owned_domain):
    """A user token containing 'test' with no server token must reach Cloudflare, not be simulated."""
    dns_auto_fixer_service.save_credentials(USER, "cloudflare", "cf-test-user-token", "zone-cs05-1")
    created = {"id": "rec_cf_real_777", "type": "TXT", "name": DOMAIN, "content": "v=spf1 -all", "ttl": 3600, "proxied": False}
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", ""), \
         patch.object(dns_auto_fixer_service.cloudflare, "create_dns_record", AsyncMock(return_value=created)) as create_mock:
        result = await _apply(owned_domain)
    create_mock.assert_awaited_once()
    assert result["applied"] is True
    assert result["fix_entry"]["target_record_id"] == "rec_cf_real_777"
    assert "rec_sim_" not in str(result)


@pytest.mark.asyncio
async def test_success_without_record_id_is_not_reported_as_applied(owned_domain):
    """A 2xx success with no result.id must not be counted as applied."""
    dns_auto_fixer_service.save_credentials(USER, "cloudflare", "cf-live-user-token", "zone-cs05-2")
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", "server-cf-token"), \
         patch("app.services.dns.auto_fixer.httpx.AsyncClient.post", new_callable=AsyncMock,
               return_value=_json_response(200, {"success": True})):
        result = await _apply(owned_domain)
    assert result["applied"] is False
    assert result["fix_entry"]["status"] == "failed"


@pytest.mark.asyncio
async def test_real_transport_success_with_record_id_is_applied(owned_domain):
    """Positive control: a valid Cloudflare success with an id is reported as applied."""
    dns_auto_fixer_service.save_credentials(USER, "cloudflare", "cf-live-user-token", "zone-cs05-3")
    created = {"id": "rec_cf_real_123", "type": "TXT", "name": DOMAIN, "content": "v=spf1 -all", "ttl": 3600, "proxied": False}
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", "server-cf-token"), \
         patch("app.services.dns.auto_fixer.httpx.AsyncClient.post", new_callable=AsyncMock,
               return_value=_json_response(200, {"success": True, "result": created})):
        result = await _apply(owned_domain)
    assert result["applied"] is True
    assert result["fix_entry"]["status"] == "applied"
    assert result["fix_entry"]["target_record_id"] == "rec_cf_real_123"


@pytest.mark.asyncio
async def test_unresolved_zone_never_falls_back_to_hard_coded_zone(owned_domain):
    """With no stored zone and no discovered zone, no mutation may be sent anywhere."""
    dns_auto_fixer_service.save_credentials(USER, "cloudflare", "cf-live-user-token", "")
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", "server-cf-token"), \
         patch.object(dns_auto_fixer_service.cloudflare, "get_zone_by_domain", AsyncMock(return_value=None)), \
         patch("app.services.dns.auto_fixer.httpx.AsyncClient.post", new_callable=AsyncMock) as post_mock:
        result = await _apply(owned_domain)
    assert result["applied"] is False
    post_mock.assert_not_awaited()


_OPERATION = {
    "id": "fix_cs05_1", "domain_name": DOMAIN, "provider_name": "cloudflare",
    "record_type": "TXT", "host": "@", "status": "applied",
    "target_record_id": "cf_rec_cs05_1", "zone_id": "zone-cs05-4",
    "snapshot_before": {"exists": False}, "idempotency_key": "fix_cs05_1",
}


@pytest.mark.asyncio
async def test_rollback_with_test_token_and_no_server_token_calls_cloudflare():
    """Rollback must call Cloudflare; a 'test'-named token may not turn it into a skipped success."""
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", ""), \
         patch.object(supabase_service, "get_dns_auto_fix_operation",
                      return_value=dict(_OPERATION, target_record_id="rec_sim_cs05")), \
         patch.object(dns_auto_fixer_service, "get_decrypted_token", return_value="cf-test-user-token"), \
         patch.object(dns_auto_fixer_service.cloudflare, "delete_dns_record", AsyncMock(return_value=True)) as delete_mock:
        result = await dns_auto_fixer_service.rollback_dns_fix(USER, "fix_cs05_1")
    delete_mock.assert_awaited_once()
    assert result.get("rolled_back") is True


@pytest.mark.asyncio
async def test_rollback_without_any_token_is_refused():
    """With no decryptable user token and no server token, rollback must refuse and not delete."""
    with patch.object(settings, "ENVIRONMENT", NON_PROD), \
         patch.object(settings, "CLOUDFLARE_API_TOKEN", ""), \
         patch.object(supabase_service, "get_dns_auto_fix_operation", return_value=dict(_OPERATION)), \
         patch.object(dns_auto_fixer_service, "get_decrypted_token", return_value=None), \
         patch.object(dns_auto_fixer_service.cloudflare, "delete_dns_record", AsyncMock(return_value=True)) as delete_mock:
        result = await dns_auto_fixer_service.rollback_dns_fix(USER, "fix_cs05_1")
    assert result.get("rolled_back") is not True
    delete_mock.assert_not_awaited()
