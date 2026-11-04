"""INV-14 HTTP boundary: never acknowledge uncommitted billing updates."""
import importlib
from unittest.mock import Mock

import httpx
import pytest
from app.main import app
from app.services.supabase_client import DatabaseUnavailableError

routes = importlib.import_module("app.api.v1.billing")


@pytest.mark.asyncio
async def test_atomic_storage_failure_returns_503_for_stripe_retry(monkeypatch):
    monkeypatch.setattr(routes.stripe_service, "verify_webhook_signature", Mock(return_value=True))
    process = Mock(side_effect=DatabaseUnavailableError("synthetic unavailable atomic RPC"))
    monkeypatch.setattr(routes.stripe_service, "process_webhook_event", process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/billing/webhook", json={"id": "evt_retry", "type": "checkout.session.completed"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Billing reconciliation temporarily unavailable"
    process.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_signature_never_calls_atomic_repository(monkeypatch):
    monkeypatch.setattr(routes.stripe_service, "verify_webhook_signature", Mock(return_value=False))
    process = Mock()
    monkeypatch.setattr(routes.stripe_service, "process_webhook_event", process)
    # Suppress operational notifications: this test concerns only the HTTP gate.
    from app.services.alerting.ops_alert_service import ops_alert_service
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ops_alert_service, "dispatch_incident", AsyncMock(return_value=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/billing/webhook", json={"id": "evt_invalid"})
    assert response.status_code == 400
    process.assert_not_called()
