"""Pure service contract tests; not PostgreSQL/RLS/concurrency integration proof."""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.privacy.minimization import PrivacyValidationError, minimize_diagnostics, minimize_request
from app.services.privacy.repository import PrivacyAcceptanceError, accept_gdpr_request
from app.workers.gdpr_worker import GDPRWorker


SHOP = "alpha.myshopify.com"
EMAIL = "Secret.Customer@example.com"
JOB = str(uuid4())
WORKER = str(uuid4())


class Client:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.handler(name, params)))


def receipt(**changes):
    return {"status": "accepted", "job_id": JOB, "state": "queued", "idempotent": False, **changes}


def accept(client, **changes):
    args = {"kind": "customers/redact", "shop": SHOP, "payload": {"customer": {"email": EMAIL, "id": 42, "phone": "+33123456789"}, "unknown": EMAIL}, "delivery_id": "delivery-1", "client": client}
    args.update(changes)
    return accept_gdpr_request(**args)


def test_acceptance_is_durable_receipt_not_completion():
    c = Client(lambda *args: receipt())
    assert accept(c) == receipt()
    name, p = c.calls[0]
    assert name == "enqueue_privacy_job"
    assert p["p_shop_domain"] == SHOP
    assert p["p_subject_hash"] == hashlib.sha256(EMAIL.lower().encode()).hexdigest()
    assert p["p_customer_id"] == hashlib.sha256(b"42").hexdigest()
    serialized = json.dumps(c.calls)
    assert EMAIL not in serialized and "phone" not in serialized and "unknown" not in serialized
    assert "user_id" not in serialized


@pytest.mark.parametrize("data", [None, [], {}, {"status": "completed"}, receipt(job_id="bad"), receipt(idempotent="true"), receipt(state="unknown")])
def test_malformed_or_missing_receipt_never_acknowledged(data):
    with pytest.raises(PrivacyAcceptanceError):
        accept(Client(lambda *args: data))


def test_storage_failure_is_safe_retryable_not_logged(caplog):
    def fail(*args):
        raise RuntimeError(EMAIL)
    with pytest.raises(PrivacyAcceptanceError) as error:
        accept(Client(fail))
    assert EMAIL not in str(error.value) and EMAIL not in caplog.text
    with pytest.raises(PrivacyAcceptanceError):
        accept(None)


@pytest.mark.parametrize("changes", [
    {"shop": "evil.example.com"}, {"payload": []}, {"payload": {"customer": []}},
    {"payload": {"customer": {"email": "broken"}}}, {"payload": {"customer": {"id": True}}},
    {"payload": {"customer": {}}}, {"delivery_id": None},
    {"payload": {"shop_domain": "beta.myshopify.com", "customer": {"email": EMAIL}}},
])
def test_malformed_request_rejected_before_rpc(changes):
    c = Client(lambda *args: receipt())
    with pytest.raises(PrivacyValidationError):
        accept(c, **changes)
    assert not c.calls


def test_canonical_identity_stable_and_shop_bound():
    c = Client(lambda *args: receipt())
    accept(c)
    accept(c, payload={"customer": {"email": "  " + EMAIL.upper() + "  ", "id": 42}, "raw": "different"})
    accept(c, shop="beta.myshopify.com")
    assert c.calls[0][1]["p_request_hash"] == c.calls[1][1]["p_request_hash"]
    assert c.calls[0][1]["p_request_hash"] != c.calls[2][1]["p_request_hash"]


def test_duplicate_returns_persisted_state():
    c = Client(lambda *args: receipt(idempotent=True, state="requires_manual_review"))
    assert accept(c)["idempotent"] is True
    assert accept(c)["state"] == "requires_manual_review"


def test_diagnostics_allowlist_drops_nested_free_text_and_pii():
    assert minimize_diagnostics({"reason": EMAIL, "nested": {"email": EMAIL}, "http_status": 503, "smtp_status": True}) == {"http_status": 503}
    assert minimize_diagnostics(EMAIL) == {}


def test_customer_id_only_is_hashed_not_invented_email_mapping():
    _, data = minimize_request("customers/redact", SHOP, {"customer": {"id": 42}})
    assert set(data) == {"customer_id_hash"}


def job(kind="customers/redact"):
    return {"id": JOB, "claimed_by": WORKER, "state": "processing", "kind": kind}


def test_worker_crash_retry_uses_sql_lease_and_safe_failure_code():
    failed = False
    def handler(name, params):
        nonlocal failed
        if name == "claim_privacy_jobs":
            return [job()]
        if name == "execute_privacy_job":
            if not failed:
                failed = True
                raise RuntimeError(EMAIL)
            return {"status": "requires_manual_review", "job_id": JOB}
        assert params["p_error_code"] == "execution_unconfirmed"
        return {"status": "queued", "job_id": JOB, "attempt_count": 1}
    c = Client(handler)
    worker = GDPRWorker(c, worker_id=WORKER)
    assert worker.run_once()["retry_or_failed"] == 1
    assert worker.run_once()["requires_manual_review"] == 1
    assert EMAIL not in json.dumps(c.calls)
    assert all(p.get("p_worker_id") == WORKER for _, p in c.calls)


def test_worker_no_false_export_completion():
    def handler(name, params):
        if name == "claim_privacy_jobs":
            return [job("customers/data_request")]
        if name == "execute_privacy_job":
            return {"status": "completed", "job_id": JOB}
        return {"status": "failed", "job_id": JOB}
    result = GDPRWorker(Client(handler), worker_id=WORKER).run_once()
    assert result["completed"] == 0 and result["retry_or_failed"] == 1


def test_worker_rejects_foreign_lease():
    c = Client(lambda *args: [{**job(), "claimed_by": str(uuid4())}])
    with pytest.raises(PrivacyAcceptanceError):
        GDPRWorker(c, worker_id=WORKER).run_once()
    assert len(c.calls) == 1


def test_legacy_redact_queues_and_never_queries_wrong_column(caplog):
    from app.services.supabase_client import SupabaseService
    service = SupabaseService.__new__(SupabaseService)
    service._client = Client(lambda *args: receipt())
    assert service.redact_customer_records(SHOP, EMAIL, delivery_id="delivery-1")["status"] == "accepted"
    assert "recipient_email" not in json.dumps(service._client.calls)
    assert EMAIL not in caplog.text
    service._client = None
    with pytest.raises(PrivacyAcceptanceError):
        service.purge_store_records(SHOP, delivery_id="delivery-2")


@pytest.mark.parametrize("kind", [[], {}, None, "unexpected"])
def test_non_string_kind_is_validation_error(kind):
    with pytest.raises(PrivacyValidationError):
        minimize_request(kind, SHOP, {})


@pytest.mark.parametrize("shop", ["a-.myshopify.com", "-a.myshopify.com", "a" * 64 + ".myshopify.com"])
def test_invalid_dns_label_rejected(shop):
    with pytest.raises(PrivacyValidationError):
        minimize_request("shop/redact", shop, {})


def test_legacy_data_and_shop_handlers_queue_only():
    from app.services.supabase_client import SupabaseService
    service = SupabaseService.__new__(SupabaseService)
    service._client = Client(lambda *args: receipt())
    assert service.handle_customer_data_request(SHOP, "unused@example.net", {"customer": {"email": EMAIL}}, delivery_id="delivery-1")["status"] == "accepted"
    assert service.purge_store_records(SHOP, delivery_id="delivery-2")["status"] == "accepted"
    assert service._client.calls[-1][1]["p_kind"] == "shop/redact"
    assert service._client.calls[-1][1]["p_subject_hash"] is None
    assert "unused@example.net" not in json.dumps(service._client.calls)


def test_worker_failed_retry_receipt_never_synthesizes_success():
    def handler(name, params):
        if name == "claim_privacy_jobs":
            return [job()]
        raise RuntimeError("database unavailable " + EMAIL)
    with pytest.raises(PrivacyAcceptanceError) as error:
        GDPRWorker(Client(handler), worker_id=WORKER).run_once()
    assert EMAIL not in str(error.value)

# =============================================================================
# HTTP integration: routes acknowledge only after durable service acceptance.
# =============================================================================
def _privacy_hmac(secret: str, body: bytes) -> str:
    import base64, hmac
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("ascii")


@pytest.mark.asyncio
async def test_privacy_webhook_requires_durable_acceptance_before_ack():
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import patch
    from app.main import app
    from app.services.shopify.shopify_service import shopify_service

    secret_before = shopify_service.api_secret
    shopify_service.api_secret = "privacy-route-test-secret"
    payload = {"shop_domain": SHOP, "customer": {"email": EMAIL, "id": 42}}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _privacy_hmac(shopify_service.api_secret, body),
        "X-Shopify-Topic": "customers/redact", "X-Shopify-Shop-Domain": SHOP, "X-Shopify-Webhook-Id": "privacy-route-1",
    }
    receipt_data = {"status": "accepted", "job_id": JOB, "state": "queued", "idempotent": False}
    try:
        with patch("app.services.privacy.repository.accept_gdpr_request", return_value=receipt_data) as accept:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/shopify/webhooks/customers/redact", content=body, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"status": "accepted", "action": "privacy_request_persisted", "verified": True, "state": "queued", "idempotent": False}
        assert accept.call_args.args[0:2] == ("customers/redact", SHOP)
    finally:
        shopify_service.api_secret = secret_before


@pytest.mark.asyncio
async def test_privacy_webhook_fails_closed_when_durable_acceptance_unavailable():
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import patch
    from app.main import app
    from app.services.privacy.repository import PrivacyAcceptanceError
    from app.services.shopify.shopify_service import shopify_service

    secret_before = shopify_service.api_secret
    shopify_service.api_secret = "privacy-route-test-secret"
    payload = {"shop_domain": SHOP, "customer": {"email": EMAIL}}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _privacy_hmac(shopify_service.api_secret, body),
        "X-Shopify-Topic": "customers/data_request", "X-Shopify-Shop-Domain": SHOP, "X-Shopify-Webhook-Id": "privacy-route-2",
    }
    try:
        with patch("app.services.privacy.repository.accept_gdpr_request", side_effect=PrivacyAcceptanceError("unavailable")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/shopify/webhooks/customers/data_request", content=body, headers=headers)
        assert response.status_code == 503
        assert response.json()["detail"] == "Privacy request persistence temporarily unavailable"
    finally:
        shopify_service.api_secret = secret_before


@pytest.mark.asyncio
async def test_privacy_webhook_rejects_signed_shop_mismatch_before_persistence():
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import patch
    from app.main import app
    from app.services.shopify.shopify_service import shopify_service

    secret_before = shopify_service.api_secret
    shopify_service.api_secret = "privacy-route-test-secret"
    payload = {"shop_domain": "beta.myshopify.com", "customer": {"email": EMAIL}}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _privacy_hmac(shopify_service.api_secret, body),
        "X-Shopify-Topic": "customers/data_request", "X-Shopify-Shop-Domain": SHOP, "X-Shopify-Webhook-Id": "privacy-route-3",
    }
    try:
        with patch("app.services.privacy.repository.accept_gdpr_request") as accept:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/shopify/webhooks/customers/data_request", content=body, headers=headers)
        assert response.status_code == 400
        assert not accept.called
    finally:
        shopify_service.api_secret = secret_before

def test_privacy_migration_has_service_only_durable_contract():
    from pathlib import Path
    migration = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261106000002_p0_durable_shopify_privacy_jobs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.shopify_privacy_jobs" in migration
    assert "CONSTRAINT shopify_privacy_jobs_request_identity UNIQUE (shop_domain, request_hash)" in migration
    assert "ON CONFLICT DO NOTHING" in migration
    assert "GET DIAGNOSTICS v_inserted = ROW_COUNT" in migration
    assert "privacy event identifier was reused with a different request" in migration
    assert "GRANT ALL ON TABLE public.shopify_privacy_jobs TO service_role, postgres" in migration
    assert "REVOKE ALL ON TABLE public.shopify_privacy_jobs FROM PUBLIC, anon, authenticated" in migration
    for function in ("enqueue_privacy_job", "claim_privacy_jobs", "execute_privacy_job", "fail_privacy_job"):
        assert f"FUNCTION public.{function}" in migration
    assert "adapter_not_authorized" in migration