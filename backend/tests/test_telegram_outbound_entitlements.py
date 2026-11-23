"""Subscription checks must run before Telegram sends, decrypts, or outbox writes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.failover.omnichannel_service import omnichannel_service
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers


ROUTES = {
    "dispatch": ("/api/v1/failover/dispatch", {"order_id": "#10499"}),
    "ping": ("/api/v1/failover/test-ping", {"chat_id": "@synthetic", "bot_token": ""}),
    "settings_ping": ("/api/v1/settings/telegram/test", {"chat_id": "@synthetic", "bot_token": ""}),
}


def _profile(user_id, status, trial_ends_at=None):
    return {"id": user_id, "subscription_tier": "starter", "subscription_status": status,
            "trial_ends_at": trial_ends_at}


async def _post(user_id, route):
    path, body = ROUTES[route]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, headers=auth_headers(user_id), json=body)


@pytest.fixture
def operations():
    enqueue = MagicMock(return_value={"id": "synthetic-job", "status": "queued"})
    ping = AsyncMock(return_value={"success": True})
    decrypt = MagicMock(return_value="synthetic-stored-token")
    with patch.object(supabase_service, "enqueue_notification_outbox", enqueue), patch.object(
        omnichannel_service, "send_test_ping", ping
    ), patch.object(omnichannel_service, "get_decrypted_token", decrypt), patch.object(
        supabase_service, "update_user_profile", MagicMock()
    ):
        yield enqueue, ping, decrypt


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status,trial", [
    ("canceled", None), ("past_due", None), ("trialing", "expired"),
])
async def test_lapsed_account_denied_before_operation(operations, route, status, trial):
    user_id = f"telegram-lapsed-{uuid.uuid4().hex}"
    trial_end = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat() if trial else None
    with patch.object(supabase_service, "get_user_profile", return_value=_profile(user_id, status, trial_end)):
        response = await _post(user_id, route)
    assert response.status_code == 402, response.text
    for operation in operations:
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status,trial", [("active", None), ("trialing", "valid")])
async def test_entitled_account_retains_access(operations, route, status, trial):
    user_id = f"telegram-entitled-{uuid.uuid4().hex}"
    trial_end = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat() if trial else None
    with patch.object(supabase_service, "get_user_profile", return_value=_profile(user_id, status, trial_end)):
        response = await _post(user_id, route)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ROUTES)
async def test_one_tenants_subscription_does_not_authorize_another(operations, route):
    paying, lapsed = f"paying-{uuid.uuid4().hex}", f"lapsed-{uuid.uuid4().hex}"
    profiles = {paying: _profile(paying, "active"), lapsed: _profile(lapsed, "canceled")}
    with patch.object(supabase_service, "get_user_profile", side_effect=lambda uid, *args, **kwargs: profiles.get(uid)):
        allowed = await _post(paying, route)
        denied = await _post(lapsed, route)
    assert allowed.status_code == 200, allowed.text
    assert denied.status_code == 402, denied.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ROUTES)
async def test_missing_jwt_is_rejected_before_any_operation(operations, route):
    path, body = ROUTES[route]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 401, response.text
    for operation in operations:
        operation.assert_not_called()
