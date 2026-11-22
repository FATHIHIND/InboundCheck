"""
AUTHZ-ENTITLEMENTS-01 regression tests: paid AI endpoints must require an active entitlement.

Defect: get_current_ai_policy() resolved the plan with resolve_ai_plan(user_id), whose
enforce_active parameter defaults to False and is never set to True anywhere. The 402 logic for
expired trials and non-active subscriptions therefore never ran. The AI template-analysis and
variant-generation endpoints accepted any signed-in user, including expired-trial, canceled and
past-due accounts, and applied the tier still stored on the profile.

Expected (existing rule, from tier_guards.verify_active_subscription_or_trial and
resolve_ai_plan(enforce_active=True)): only `active` and unexpired `trialing` accounts are served;
every other status returns 402 before any expensive work (concurrency lease, quota, LLM) starts.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers

ANALYZE = "/api/v1/ai/analyze-template"
GENERATE = "/api/v1/ai/generate-variants"
ANALYZE_BODY = {"subject": "Your order has shipped", "body": "Thanks for your purchase."}
GENERATE_BODY = {"subject": "Order update", "body": "Your order is ready."}


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()


def _profile(user_id, status, tier="growth", trial_ends_at=None):
    profile = {"id": user_id, "subscription_tier": tier, "subscription_status": status}
    if trial_ends_at is not None:
        profile["trial_ends_at"] = trial_ends_at
    return profile


INELIGIBLE = [
    ("expired_trial", "trialing", _past),
    ("trial_without_end_date", "trialing", None),
    ("expired_status", "expired", None),
    ("canceled", "canceled", None),
    ("past_due", "past_due", None),
    ("incomplete", "incomplete", None),
    ("unrecognized", "paused", None),
]


async def _post(user_id, path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(path, headers=auth_headers(user_id), json=body)


@pytest.fixture
def downstream():
    """Mocks every expensive step so a request that gets past authorization is observable."""
    analyze = AsyncMock(return_value={"spam_score": 1, "risk_level": "low", "flagged_triggers": [], "recommendations": []})
    lease = MagicMock(return_value={"allowed": False, "current_active": 0, "concurrency_limit": 1})
    with patch("app.api.v1.ai.ai_content_service.analyze_template", analyze), \
         patch.object(supabase_service, "acquire_ai_concurrency_slot", lease), \
         patch.object(supabase_service, "update_user_profile", MagicMock()):
        yield SimpleNamespaceLike(analyze=analyze, lease=lease)


class SimpleNamespaceLike:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("label,status,trial", INELIGIBLE, ids=[c[0] for c in INELIGIBLE])
async def test_analyze_template_denies_ineligible_accounts_before_any_work(downstream, label, status, trial):
    user_id = f"ent-{label}-{uuid.uuid4().hex[:6]}"
    profile = _profile(user_id, status, trial_ends_at=trial() if trial else None)
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        res = await _post(user_id, ANALYZE, ANALYZE_BODY)
    assert res.status_code == 402, res.text
    downstream.analyze.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("label,status,trial", INELIGIBLE, ids=[c[0] for c in INELIGIBLE])
async def test_generate_variants_denies_ineligible_accounts_before_any_work(downstream, label, status, trial):
    user_id = f"ent-{label}-{uuid.uuid4().hex[:6]}"
    profile = _profile(user_id, status, trial_ends_at=trial() if trial else None)
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        res = await _post(user_id, GENERATE, GENERATE_BODY)
    assert res.status_code == 402, res.text
    downstream.lease.assert_not_called()  # no concurrency lease, quota or LLM work started


@pytest.mark.asyncio
@pytest.mark.parametrize("status,trial", [("active", None), ("trialing", _future)], ids=["active", "valid_trial"])
async def test_eligible_accounts_keep_access(downstream, status, trial):
    user_id = f"ent-ok-{uuid.uuid4().hex[:6]}"
    profile = _profile(user_id, status, trial_ends_at=trial() if trial else None)
    with patch.object(supabase_service, "get_user_profile", return_value=profile):
        res = await _post(user_id, ANALYZE, ANALYZE_BODY)
    assert res.status_code == 200, res.text
    downstream.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_tenants_subscription_does_not_grant_another_tenant_access(downstream):
    paying = f"ent-paying-{uuid.uuid4().hex[:6]}"
    lapsed = f"ent-lapsed-{uuid.uuid4().hex[:6]}"
    profiles = {paying: _profile(paying, "active"), lapsed: _profile(lapsed, "canceled")}
    with patch.object(supabase_service, "get_user_profile", side_effect=lambda uid, *a, **k: profiles.get(uid)):
        ok = await _post(paying, ANALYZE, ANALYZE_BODY)
        denied = await _post(lapsed, ANALYZE, ANALYZE_BODY)
    assert ok.status_code == 200
    assert denied.status_code == 402


@pytest.mark.asyncio
async def test_usage_view_remains_available_to_lapsed_accounts(downstream):
    """Read-only usage reporting is not a paid action and keeps its existing behaviour."""
    user_id = f"ent-usage-{uuid.uuid4().hex[:6]}"
    with patch.object(supabase_service, "get_user_profile", return_value=_profile(user_id, "canceled")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.get("/api/v1/ai/usage", headers=auth_headers(user_id))
    assert res.status_code != 402
