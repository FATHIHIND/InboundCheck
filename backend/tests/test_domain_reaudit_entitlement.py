"""
AUTHZ-ENTITLEMENTS-01 regression tests: POST /domains/{id}/audit (on-demand re-audit) must require
the same entitlement as POST /domains (add domain).

Defect: add_monitored_domain depends on verify_active_subscription_or_trial, and runs the live DNS
audit and stores the result. re_audit_domain runs the same pipeline (diagnostic_engine.audit_domain,
then create_or_update_domain and save_audit_log) but only depended on get_current_user_id. An
expired, canceled or past-due account with an existing monitored domain could keep running live
audits and updating stored records.

Expected: 402 before any audit or write for every non-entitled status; active and valid-trial
accounts keep access; another tenant's entitlement or domain gives no access (404 ownership check).
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.dns.scorer import DeliverabilityScorer
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers

DOMAIN = "reaudit-ent.example"


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()


def _profile(user_id, status, trial_ends_at=None):
    profile = {"id": user_id, "subscription_tier": "growth", "subscription_status": status}
    if trial_ends_at is not None:
        profile["trial_ends_at"] = trial_ends_at
    return profile


INELIGIBLE = [
    ("expired_trial", "trialing", _past),
    ("expired_status", "expired", None),
    ("canceled", "canceled", None),
    ("past_due", "past_due", None),
    ("incomplete", "incomplete", None),
]


@pytest.fixture
def pipeline():
    summary = MagicMock()
    summary.model_dump.return_value = {}
    audit = AsyncMock(return_value=(summary, {}, 5))
    save = MagicMock(return_value={"id": "domain-1", "domain_name": DOMAIN})
    log = MagicMock()
    with patch("app.api.v1.domains.diagnostic_engine.audit_domain", audit), \
         patch.object(DeliverabilityScorer, "calculate_health_score", return_value=(90, "healthy", {}, [], [])), \
         patch.object(supabase_service, "create_or_update_domain", save), \
         patch.object(supabase_service, "save_audit_log", log), \
         patch.object(supabase_service, "update_user_profile", MagicMock()):
        yield MagicMock(audit=audit, save=save, log=log)


async def _reaudit(user_id, domain_id):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(f"/api/v1/domains/{domain_id}/audit?domain_name={DOMAIN}", headers=auth_headers(user_id))


def _owned(user_id, domain_id):
    return lambda uid=None, *a, **k: [{"id": domain_id, "domain_name": DOMAIN}] if (k.get("user_id") or uid) == user_id else []


@pytest.mark.asyncio
@pytest.mark.parametrize("label,status,trial", INELIGIBLE, ids=[c[0] for c in INELIGIBLE])
async def test_reaudit_denies_ineligible_accounts_before_any_audit_or_write(pipeline, label, status, trial):
    user_id = f"reaudit-{label}-{uuid.uuid4().hex[:6]}"
    domain_id = str(uuid.uuid4())
    profile = _profile(user_id, status, trial_ends_at=trial() if trial else None)
    with patch.object(supabase_service, "get_user_profile", return_value=profile), \
         patch.object(supabase_service, "get_user_domains", side_effect=_owned(user_id, domain_id)):
        res = await _reaudit(user_id, domain_id)
    assert res.status_code == 402, res.text
    pipeline.audit.assert_not_awaited()
    pipeline.save.assert_not_called()
    pipeline.log.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,trial", [("active", None), ("trialing", _future)], ids=["active", "valid_trial"])
async def test_reaudit_keeps_access_for_entitled_accounts(pipeline, status, trial):
    user_id = f"reaudit-ok-{uuid.uuid4().hex[:6]}"
    domain_id = str(uuid.uuid4())
    profile = _profile(user_id, status, trial_ends_at=trial() if trial else None)
    with patch.object(supabase_service, "get_user_profile", return_value=profile), \
         patch.object(supabase_service, "get_user_domains", side_effect=_owned(user_id, domain_id)):
        res = await _reaudit(user_id, domain_id)
    assert res.status_code == 200, res.text
    pipeline.audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_tenant_cannot_reaudit_another_tenants_domain(pipeline):
    owner = f"reaudit-owner-{uuid.uuid4().hex[:6]}"
    other = f"reaudit-other-{uuid.uuid4().hex[:6]}"
    domain_id = str(uuid.uuid4())
    with patch.object(supabase_service, "get_user_profile", return_value=_profile(other, "active")), \
         patch.object(supabase_service, "get_user_domains", side_effect=_owned(owner, domain_id)):
        res = await _reaudit(other, domain_id)
    assert res.status_code == 404
    pipeline.audit.assert_not_awaited()
