"""INV-13: mock-only regression tests; no Stripe or database operations."""
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import importlib
billing = importlib.import_module("app.services.billing.stripe_service")


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(billing.settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(billing.settings, "STAGING_MODE", False)
    monkeypatch.setenv("STAGING_MODE", "false")
    profile = {"id": "tenant_a", "email": "a@example.invalid"}
    def update(uid, values):
        assert uid == "tenant_a"
        profile.update(values)
        return dict(profile)
    db = SimpleNamespace(get_user_profile=Mock(side_effect=lambda uid: dict(profile)), update_user_profile=Mock(side_effect=update))
    monkeypatch.setattr(billing, "supabase_service", db)
    service = billing.StripeService()
    service.secret_key = "sk_test_local_stub_only"
    real_client = httpx.AsyncClient
    requests = []
    def transport(handler):
        def capture(request):
            requests.append(request)
            return handler(request)
        monkeypatch.setattr(billing.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(capture), **kw))
    return service, db, profile, requests, transport


@pytest.mark.asyncio
async def test_checkout_email_is_contact_only_never_customer_lookup(isolated):
    service, db, profile, requests, transport = isolated
    transport(lambda req: httpx.Response(200, json={"id": "cus_created", "metadata": {"user_id": "tenant_a"}}))
    assert await service.get_or_create_customer("tenant_a", email="victim@example.invalid") == "cus_created"
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "https://api.stripe.com/v1/customers"
    assert "metadata%5Buser_id%5D=tenant_a" in requests[0].content.decode()
    assert requests[0].headers["Idempotency-Key"].startswith("inboundcheck-customer-v1-")
    assert profile["stripe_customer_id"] == "cus_created"


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata,deleted", [({"user_id": "tenant_b"}, False), ({}, False), ({"user_id": "tenant_a"}, True)])
async def test_existing_customer_requires_tenant_metadata(isolated, metadata, deleted):
    service, db, profile, requests, transport = isolated
    profile["stripe_customer_id"] = "cus_existing"
    transport(lambda req: httpx.Response(200, json={"id": "cus_existing", "metadata": metadata, "deleted": deleted}))
    with pytest.raises(ValueError, match="does not belong"):
        await service.get_or_create_customer("tenant_a")
    db.update_user_profile.assert_not_called()


@pytest.mark.asyncio
async def test_existing_owned_customer_is_verified_not_recreated(isolated):
    service, db, profile, requests, transport = isolated
    profile["stripe_customer_id"] = "cus_owned"
    transport(lambda req: httpx.Response(200, json={"id": "cus_owned", "metadata": {"user_id": "tenant_a"}}))
    assert await service.get_or_create_customer("tenant_a") == "cus_owned"
    assert [r.method for r in requests] == ["GET"]
    db.update_user_profile.assert_not_called()


@pytest.mark.asyncio
async def test_customer_persistence_failure_propagates_without_mock_write(isolated):
    service, db, profile, requests, transport = isolated
    transport(lambda req: httpx.Response(200, json={"id": "cus_created", "metadata": {"user_id": "tenant_a"}}))
    db.update_user_profile.side_effect = RuntimeError("synthetic persistence failure")
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        await service.get_or_create_customer("tenant_a")
    db.update_user_profile.assert_called_once_with("tenant_a", {"stripe_customer_id": "cus_created"})
    assert "stripe_customer_id" not in profile


@pytest.mark.asyncio
async def test_empty_persistence_result_fails_closed(isolated):
    service, db, profile, requests, transport = isolated
    transport(lambda req: httpx.Response(200, json={"id": "cus_created", "metadata": {"user_id": "tenant_a"}}))
    db.update_user_profile.side_effect = None
    db.update_user_profile.return_value = {}
    with pytest.raises(RuntimeError, match="could not be persisted"):
        await service.get_or_create_customer("tenant_a")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_customer_portal_session", "get_customer_invoices"])
async def test_portal_and_invoices_reverify_poisoned_mapping(isolated, operation):
    service, db, profile, requests, transport = isolated
    profile["stripe_customer_id"] = "cus_foreign"
    transport(lambda req: httpx.Response(200, json={"id": "cus_foreign", "metadata": {"user_id": "tenant_b"}}))
    with pytest.raises(ValueError, match="does not belong"):
        await getattr(service, operation)("tenant_a")
    assert len(requests) == 1 and requests[0].method == "GET"
    assert "/billing_portal/" not in str(requests[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["production", "staging"])
async def test_unconfigured_deployed_environment_never_creates_mock(isolated, monkeypatch, mode):
    service, db, profile, requests, transport = isolated
    monkeypatch.setattr(billing.settings, "ENVIRONMENT", mode)
    service.secret_key = ""
    with pytest.raises(RuntimeError, match="not configured"):
        await service.get_or_create_customer("tenant_a")
    db.update_user_profile.assert_not_called()


@pytest.mark.asyncio
async def test_failed_stripe_request_does_not_persist_customer(isolated):
    service, db, profile, requests, transport = isolated
    transport(lambda req: httpx.Response(503, json={"error": "synthetic"}))
    with pytest.raises(RuntimeError, match="creation failed"):
        await service.get_or_create_customer("tenant_a")
    db.update_user_profile.assert_not_called()


@pytest.mark.asyncio
async def test_idempotency_key_is_stable_across_retry(isolated):
    service, db, profile, requests, transport = isolated
    transport(lambda req: httpx.Response(200, json={"id": "cus_created", "metadata": {"user_id": "tenant_a"}}))
    db.update_user_profile.side_effect = RuntimeError("synthetic failure")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await service.get_or_create_customer("tenant_a")
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
