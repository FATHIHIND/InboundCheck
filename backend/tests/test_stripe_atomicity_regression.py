"""INV-14 mocks/local model only: not a live PostgreSQL transaction test.

No SQL is executed by this file. Database rollback/concurrency still needs a
separately approved ephemeral-Postgres integration suite before deployment.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.billing.stripe_event_repository import process_atomic_stripe_event
from app.services.supabase_client import DatabaseUnavailableError

PRICES = {"starter": "price_starter", "growth": "price_growth", "agency": "price_agency", "enterprise": "price_agency"}
USER = "00000000-0000-0000-0000-000000000001"


class MemoryService:
    def __init__(self, allowed=True):
        self._client = None
        self.allowed = allowed
        self.calls = 0
        self.fail = False
        self._in_memory_profiles = {USER: {"id": USER, "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1", "subscription_tier": "starter", "tier": "starter"}}

    def _allow_in_memory_fallback(self):
        return self.allowed

    def update_user_profile(self, uid, updates):
        self.calls += 1
        self._in_memory_profiles[uid].update(updates)
        if self.fail:
            raise RuntimeError("simulated failure after partial local mutation")
        return self._in_memory_profiles[uid]


def event(eid="evt_1", created=100, kind="customer.subscription.updated", price="price_growth", subscription="sub_1"):
    obj = {"id": subscription, "customer": "cus_1", "status": "active", "metadata": {"user_id": USER}, "items": {"data": [{"price": {"id": price}}]}}
    if kind == "checkout.session.completed":
        obj.update(id="cs_1", subscription=subscription, client_reference_id=USER, line_items=obj["items"], mode="subscription", payment_status="paid")
    return {"id": eid, "created": created, "type": kind, "data": {"object": obj}}


def process(service, payload):
    return process_atomic_stripe_event(payload, service, PRICES)


def test_concurrent_duplicate_mutates_once_and_caches_original_result():
    service = MemoryService()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: process(service, event()), range(16)))
    assert service.calls == 1
    assert sum(r["status"] == "success" for r in results) == 1
    duplicates = [r for r in results if r["status"] == "already_processed"]
    assert len(duplicates) == 15
    assert all(r["result"]["action"] == "subscription_updated" for r in duplicates)


def test_reversed_delivery_does_not_restore_older_tier():
    service = MemoryService()
    process(service, event("evt_new", 200, price="price_agency"))
    result = process(service, event("evt_old", 100, price="price_growth"))
    assert result["reason"] == "stale_event"
    assert service.calls == 1
    assert service._in_memory_profiles[USER]["tier"] == "agency"
    assert service._atomic_stripe_state["watermarks"][USER] == (200, "evt_new")


def test_equal_timestamps_are_retryable_not_lexically_ordered():
    service = MemoryService()
    process(service, event("evt_z", 100))
    with pytest.raises(DatabaseUnavailableError, match="Equal Stripe timestamps"):
        process(service, event("evt_a", 100, price="price_agency"))
    assert "evt_a" not in service._atomic_stripe_state["events"]
    assert service.calls == 1


def test_conflicting_duplicate_payload_rejected():
    service = MemoryService()
    process(service, event())
    with pytest.raises(DatabaseUnavailableError, match="Conflicting payload"):
        process(service, event(price="price_agency"))
    assert service.calls == 1


def test_failed_update_rolls_back_profile_claim_and_watermark_then_retry_succeeds():
    service = MemoryService()
    before = deepcopy(service._in_memory_profiles)
    service.fail = True
    with pytest.raises(DatabaseUnavailableError, match="local Stripe profile update failed"):
        process(service, event())
    assert service._in_memory_profiles == before
    assert service._atomic_stripe_state == {"events": {}, "watermarks": {}}
    service.fail = False
    assert process(service, event())["status"] == "success"


def test_new_checkout_then_later_old_subscription_notification_cannot_overwrite():
    service = MemoryService()
    result = process(service, event("evt_checkout", 200, "checkout.session.completed", "price_agency", "sub_new"))
    assert result["action"] == "subscription_activated"
    assert result["customer_id"] == "cus_1"
    with pytest.raises(DatabaseUnavailableError, match="subscription requires authoritative reconciliation"):
        process(service, event("evt_old_subscription", 300, subscription="sub_1"))
    with pytest.raises(DatabaseUnavailableError, match="Retired subscription"):
        process(service, event("evt_retired_checkout", 301, "checkout.session.completed", subscription="sub_1"))
    assert service._in_memory_profiles[USER]["stripe_subscription_id"] == "sub_new"
    assert service._in_memory_profiles[USER]["tier"] == "agency"


def test_deleted_contract_and_tombstone_prevent_stale_reactivation():
    service = MemoryService()
    payload = event("evt_deleted", 200, "customer.subscription.deleted")
    payload["data"]["object"]["status"] = "canceled"
    result = process(service, payload)
    assert result == {"status": "success", "action": "subscription_downgraded", "user_id": USER, "subscription_status": "canceled"}
    assert process(service, event("evt_old", 100))["reason"] == "stale_event"
    assert service._in_memory_profiles[USER]["tier"] == "starter"


@pytest.mark.parametrize("mutation", ["unknown_price", "nickname", "metadata_only", "missing_created", "float_created", "wrong_customer", "wrong_metadata", "email_only"])
def test_untrusted_or_incomplete_event_fails_closed(mutation):
    service = MemoryService()
    payload = event()
    obj = payload["data"]["object"]
    if mutation == "unknown_price":
        obj["items"]["data"][0]["price"]["id"] = "price_other"
    elif mutation == "nickname":
        obj["items"]["data"][0]["price"] = {"id": "price_other", "nickname": "agency"}
    elif mutation == "metadata_only":
        obj.pop("items")
        obj["metadata"]["subscription_tier"] = "agency"
    elif mutation == "missing_created":
        payload.pop("created")
    elif mutation == "float_created":
        payload["created"] = 100.0
    elif mutation == "wrong_customer":
        obj["customer"] = "cus_not_owned"
    elif mutation == "wrong_metadata":
        obj["metadata"]["user_id"] = "another-user"
    else:
        obj.pop("customer")
        obj["customer_email"] = "same@example.com"
        service._in_memory_profiles[USER]["email"] = "same@example.com"
    before = deepcopy(service._in_memory_profiles)
    with pytest.raises(DatabaseUnavailableError):
        process(service, payload)
    assert service.calls == 0
    assert service._in_memory_profiles == before


def test_unsupported_event_has_no_local_claim_or_mutation():
    service = MemoryService()
    assert process(service, {"type": "invoice.created"}) == {"status": "ignored", "event_type": "invoice.created"}
    assert service.calls == 0
    assert not hasattr(service, "_atomic_stripe_state")


def test_no_memory_fallback_when_production_guard_denies():
    service = MemoryService(allowed=False)
    with pytest.raises(DatabaseUnavailableError, match="fallback prohibited"):
        process(service, event())
    assert service.calls == 0


@pytest.mark.parametrize("allowed", [True, False])
def test_rpc_failure_never_reads_tables_or_uses_memory_even_in_development(allowed):
    service = MemoryService(allowed=allowed)
    service._client = Mock()
    service._client.rpc.return_value.execute.side_effect = RuntimeError("RPC unavailable")
    with pytest.raises(DatabaseUnavailableError, match="retry required"):
        process(service, event())
    service._client.rpc.assert_called_once_with("process_stripe_billing_event", {"p_event": event(), "p_prices": PRICES})
    service._client.table.assert_not_called()
    assert service.calls == 0
    assert not hasattr(service, "_atomic_stripe_state")


@pytest.mark.parametrize("data", [None, [], {}, {"status": "retryable_error"}, {"status": "error"}, {"status": "success"}, {"status": "already_processed"}, {"status": "ignored"}])
def test_malformed_rpc_result_fails_closed(data):
    service = MemoryService()
    service._client = Mock()
    service._client.rpc.return_value.execute.return_value = SimpleNamespace(data=data)
    with pytest.raises(DatabaseUnavailableError):
        process(service, event())
    service._client.table.assert_not_called()
    assert service.calls == 0


def test_connected_path_is_one_rpc_and_returns_legacy_result_unchanged():
    service = MemoryService()
    service._client = Mock()
    expected = {"status": "success", "action": "subscription_updated", "user_id": USER, "subscription_status": "active"}
    service._client.rpc.return_value.execute.return_value = SimpleNamespace(data=expected)
    assert process(service, event()) == expected
    service._client.rpc.assert_called_once()
    service._client.table.assert_not_called()
    assert service.calls == 0


def test_migration_source_has_restricted_transactional_rpc_contract():
    source = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261104000001_atomic_stripe_billing_events.sql").read_text(encoding="utf-8")
    assert "SET search_path = pg_catalog" in source
    assert "event_id text PRIMARY KEY" in source
    assert "FOR UPDATE" in source
    assert "USING ERRCODE = '40001'" in source
    assert "REVOKE ALL ON FUNCTION public.process_stripe_billing_event(jsonb,jsonb) FROM PUBLIC, anon, authenticated" in source
    assert "GRANT EXECUTE ON FUNCTION public.process_stripe_billing_event(jsonb,jsonb) TO service_role" in source
    assert source.count("ENABLE ROW LEVEL SECURITY") == 2
    assert "payload jsonb" not in source.lower()
    assert "v_previous.payload <>" not in source
    assert "sha256(convert_to(p_event::text" in source
    assert "event_id,event_type,event_created,payload_hash)" in source


def test_standard_unexpanded_checkout_uses_exact_server_authored_metadata():
    service = MemoryService()
    payload = event(kind="checkout.session.completed")
    obj = payload["data"]["object"]
    obj.pop("line_items")
    obj.pop("items")
    obj["metadata"].update(subscription_tier="agency", plan_tier="agency")
    result = process(service, payload)
    assert result["action"] == "subscription_activated"
    assert result["subscription_tier"] == "agency"


@pytest.mark.parametrize("metadata", [{}, {"plan_tier": "enterprise"}, {"plan_tier": "agency_special"}, {"plan_tier": "unknown"}, {"plan_tier": "agency", "subscription_tier": "growth"}])
def test_standard_checkout_rejects_missing_unknown_or_conflicting_tier_metadata(metadata):
    service = MemoryService()
    payload = event(kind="checkout.session.completed")
    obj = payload["data"]["object"]
    obj.pop("line_items")
    obj.pop("items")
    obj["metadata"] = {"user_id": USER, **metadata}
    with pytest.raises(DatabaseUnavailableError, match="exact configured server tier"):
        process(service, payload)
    assert service.calls == 0


@pytest.mark.parametrize("mode,payment", [("payment", "paid"), ("setup", "paid"), ("subscription", "unpaid"), (None, "paid"), ("subscription", None)])
def test_strict_checkout_rejects_wrong_mode_or_unpaid(mode, payment):
    service = MemoryService()
    payload = event(kind="checkout.session.completed")
    payload["data"]["object"].update(mode=mode, payment_status=payment)
    with pytest.raises(DatabaseUnavailableError, match="subscription mode"):
        process(service, payload)
    assert service.calls == 0


def test_no_payment_required_does_not_invent_trial_status_and_expanded_trial_is_preserved():
    service = MemoryService()
    payload = event(kind="checkout.session.completed")
    obj = payload["data"]["object"]
    obj["payment_status"] = "no_payment_required"
    process(service, payload)
    assert service._in_memory_profiles[USER]["subscription_status"] == "active"
    trial = event("evt_trial", 200, "checkout.session.completed")
    trial["data"]["object"].update(payment_status="no_payment_required", subscription={"id": "sub_1", "status": "trialing"})
    process(service, trial)
    assert service._in_memory_profiles[USER]["subscription_status"] == "trialing"


def test_expanded_unknown_checkout_price_cannot_fall_back_to_metadata():
    service = MemoryService()
    payload = event(kind="checkout.session.completed", price="price_unknown")
    payload["data"]["object"]["metadata"]["subscription_tier"] = "agency"
    with pytest.raises(DatabaseUnavailableError, match="Unknown or ambiguous"):
        process(service, payload)
    assert service.calls == 0


def test_migration_source_preserves_known_legacy_duplicates_before_profile_mutation():
    source = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261104000001_atomic_stripe_billing_events.sql").read_text(encoding="utf-8")
    claim = source.index("INSERT INTO public.stripe_billing_events(")
    legacy = source.index("IF EXISTS (SELECT 1 FROM public.processed_webhook_events WHERE id = v_id)")
    profile_lookup = source.index("SELECT * INTO STRICT v_profile FROM public.profiles")
    assert claim < legacy < profile_lookup
    legacy_block = source[legacy:source.index("    v_customer :=", legacy)]
    assert "'reason','legacy_processed'" in legacy_block
    assert "UPDATE public.stripe_billing_events SET result = v_result, completed_at = clock_timestamp()" in legacy_block
    assert "'status','already_processed','idempotent',true,'event_id',v_id,'result',v_result" in legacy_block
    assert "UPDATE public.profiles" not in legacy_block
    assert "INSERT INTO public.stripe_billing_watermarks" not in legacy_block
    assert "48 hours" in source
