"""
AUTHZ-ENTITLEMENTS-01 regression tests: Stripe subscription lifecycle events must only change the
entitlement of the subscription the profile currently holds.

Defect (stripe_service.process_webhook_event, customer.subscription.updated/deleted): the user is
resolved from metadata or customer id and the event is applied without checking that
data.object.id is the profile's current stripe_subscription_id. checkout.session.completed stores
that id, but nothing validated it afterwards, and the checkout route does not stop an active
subscriber from starting a second subscription. A late `deleted` or `past_due` event for the
superseded subscription therefore downgraded or locked out an account that still holds a paid,
active subscription.

Expected: when the profile stores a different subscription id, the event remains retryable unless a
concurrent checkout makes the event's subscription current before the guarded update. Events
without a subscription id are ignored because ownership cannot be established.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from postgrest import SyncPostgrestClient

from app.services.billing.stripe_service import stripe_service
from app.services.supabase_client import SupabaseService, supabase_service

USER = "sub-owner-user"
CURRENT_SUB = "sub_current_Y"
OLD_SUB = "sub_superseded_X"


@pytest.fixture
def harness(monkeypatch):
    update = MagicMock()
    guarded_update = MagicMock(return_value=True)
    monkeypatch.setattr(supabase_service, "update_user_profile", update)
    monkeypatch.setattr(
        supabase_service,
        "update_user_profile_if_subscription_matches",
        guarded_update,
        raising=False,
    )
    processed = set()
    monkeypatch.setattr(stripe_service, "is_event_processed", lambda event_id: event_id in processed)
    mark_processed = MagicMock(side_effect=lambda event_id, **_kwargs: processed.add(event_id))
    monkeypatch.setattr(stripe_service, "mark_event_processed", mark_processed)
    profile_state = {}
    guarded_update.side_effect = lambda _uid, expected, _updates: (
        profile_state.get("stripe_subscription_id") == expected
    )

    def set_profile(stored_subscription_id, status="active"):
        profile = {"id": USER, "subscription_tier": "growth", "subscription_status": status}
        if stored_subscription_id is not None:
            profile["stripe_subscription_id"] = stored_subscription_id
        profile_state.clear()
        profile_state.update(profile)
        monkeypatch.setattr(
            supabase_service,
            "get_user_profile",
            lambda uid, *a, **k: dict(profile_state),
        )

    return set_profile, update, guarded_update, mark_processed, profile_state


def _event(event_type, sub_status, sub_id=OLD_SUB):
    obj = {"status": sub_status, "customer": "cus_owner", "metadata": {"user_id": USER}}
    if sub_id is not None:
        obj["id"] = sub_id
    return {"id": f"evt_{event_type}_{sub_status}_{sub_id}", "type": event_type, "data": {"object": obj}}


def test_late_delete_of_superseded_subscription_does_not_downgrade_the_current_one(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    with pytest.raises(HTTPException) as failure:
        stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", OLD_SUB))
    assert failure.value.status_code == 503
    update.assert_not_called()
    assert guarded_update.call_args.args[0:2] == (USER, OLD_SUB)
    _mark_processed.assert_not_called()


def test_late_past_due_update_of_superseded_subscription_does_not_change_status(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    with pytest.raises(HTTPException) as failure:
        stripe_service.process_webhook_event(_event("customer.subscription.updated", "past_due", OLD_SUB))
    assert failure.value.status_code == 503
    update.assert_not_called()
    assert guarded_update.call_args.args[0:2] == (USER, OLD_SUB)
    _mark_processed.assert_not_called()


def test_deleting_the_current_subscription_still_downgrades(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", CURRENT_SUB))
    assert result["action"] == "subscription_downgraded"
    assert guarded_update.call_args.args[0:2] == (USER, CURRENT_SUB)
    assert guarded_update.call_args.args[2]["subscription_status"] == "canceled"
    update.assert_not_called()


def test_current_subscription_update_is_still_applied(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.updated", "past_due", CURRENT_SUB))
    assert result["action"] == "subscription_updated"
    assert guarded_update.call_args.args[0:2] == (USER, CURRENT_SUB)
    assert guarded_update.call_args.args[2]["subscription_status"] == "past_due"
    update.assert_not_called()


def test_profile_without_a_stored_subscription_id_keeps_existing_behaviour(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile(None)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", OLD_SUB))
    assert result["action"] == "subscription_downgraded"
    assert guarded_update.call_args.args[0:2] == (USER, None)
    assert guarded_update.call_args.args[2]["stripe_subscription_id"] == OLD_SUB
    update.assert_not_called()


def test_empty_stored_subscription_id_is_compared_and_rebound(harness):
    set_profile, update, guarded_update, _mark_processed, _profile = harness
    set_profile("")

    result = stripe_service.process_webhook_event(
        _event("customer.subscription.updated", "active", CURRENT_SUB)
    )

    assert result["action"] == "subscription_updated"
    assert guarded_update.call_args.args[0:2] == (USER, "")
    assert guarded_update.call_args.args[2]["stripe_subscription_id"] == CURRENT_SUB
    update.assert_not_called()


def test_event_without_a_subscription_id_is_ignored(harness):
    set_profile, update, guarded_update, mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", None))
    assert result == {
        "status": "ignored",
        "reason": "missing_subscription_id",
        "event_type": "customer.subscription.deleted",
    }
    update.assert_not_called()
    guarded_update.assert_not_called()
    mark_processed.assert_called_once()


def test_concurrent_checkout_replacement_prevents_stale_subscription_write(harness):
    set_profile, update, guarded_update, mark_processed, profile = harness
    set_profile(CURRENT_SUB)

    def lose_to_new_checkout(_user_id, _expected_subscription_id, _updates):
        profile["stripe_subscription_id"] = "sub_replacement_Z"
        return False

    guarded_update.side_effect = lose_to_new_checkout

    for _ in range(2):
        with pytest.raises(HTTPException) as failure:
            stripe_service.process_webhook_event(
                _event("customer.subscription.deleted", "canceled", CURRENT_SUB)
            )
        assert failure.value.status_code == 503
    assert guarded_update.call_args_list[0].args[0:2] == (USER, CURRENT_SUB)
    update.assert_not_called()
    mark_processed.assert_not_called()
    assert profile["stripe_subscription_id"] == "sub_replacement_Z"


def test_database_failure_does_not_mark_event_processed_for_retry(harness):
    set_profile, update, guarded_update, mark_processed, _profile = harness
    set_profile(CURRENT_SUB)
    guarded_update.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        stripe_service.process_webhook_event(
            _event("customer.subscription.updated", "past_due", CURRENT_SUB)
        )

    update.assert_not_called()
    mark_processed.assert_not_called()


def test_concurrent_checkout_for_event_subscription_retries_with_new_snapshot(harness):
    set_profile, update, guarded_update, mark_processed, profile = harness
    set_profile(None)

    def checkout_race(user_id, expected_subscription_id, _updates):
        if guarded_update.call_count == 1:
            assert (user_id, expected_subscription_id) == (USER, None)
            profile["stripe_subscription_id"] = CURRENT_SUB
            return False
        assert (user_id, expected_subscription_id) == (USER, CURRENT_SUB)
        return True

    guarded_update.side_effect = checkout_race
    result = stripe_service.process_webhook_event(
        _event("customer.subscription.updated", "active", CURRENT_SUB)
    )

    assert result["action"] == "subscription_updated"
    assert guarded_update.call_count == 2
    assert mark_processed.call_count == 1
    update.assert_not_called()


def test_initial_mismatch_retries_if_checkout_makes_event_subscription_current(harness):
    set_profile, update, guarded_update, mark_processed, profile = harness
    set_profile("sub_checkout_B")

    def checkout_race(user_id, expected_subscription_id, _updates):
        if guarded_update.call_count == 1:
            assert (user_id, expected_subscription_id) == (USER, CURRENT_SUB)
            profile["stripe_subscription_id"] = CURRENT_SUB
            return False
        assert (user_id, expected_subscription_id) == (USER, CURRENT_SUB)
        return True

    guarded_update.side_effect = checkout_race
    result = stripe_service.process_webhook_event(
        _event("customer.subscription.updated", "active", CURRENT_SUB)
    )

    assert result["action"] == "subscription_updated"
    assert guarded_update.call_count == 2
    assert mark_processed.call_count == 1
    update.assert_not_called()


class _ProfileUpdateQuery:
    def __init__(self, client):
        self.client = client
        self.filters = []
        self.updates = {}
        self.upsert_payload = None
        self.ignore_duplicates = False

    def update(self, updates):
        self.updates = updates
        return self

    def upsert(self, payload, *, ignore_duplicates=False):
        self.upsert_payload = payload
        self.ignore_duplicates = ignore_duplicates
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def select(self, _columns):
        return self

    def execute(self):
        row = self.client.row
        if self.upsert_payload is not None:
            if row is not None:
                return SimpleNamespace(data=[])
            self.client.row = dict(self.upsert_payload)
            return SimpleNamespace(data=[{"id": self.client.row["id"]}])

        matches = row is not None and all(
            row.get(column) == value if operator == "eq" else row.get(column) is None
            for operator, column, value in self.filters
        )
        if matches:
            row.update(self.updates)
        return SimpleNamespace(data=[{"id": row["id"]}] if matches else [])


class _ProfileUpdateClient:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def table(self, _table_name):
        query = _ProfileUpdateQuery(self)
        self.queries.append(query)
        return query


def test_database_compare_and_set_filters_by_tenant_and_current_subscription():
    row = {"id": USER, "stripe_subscription_id": "sub_replaced"}
    client = _ProfileUpdateClient(row)
    service = SupabaseService.__new__(SupabaseService)
    service._client = client

    updated = service.update_user_profile_if_subscription_matches(
        USER,
        CURRENT_SUB,
        {"subscription_status": "canceled"},
    )

    assert updated is False
    assert "subscription_status" not in row
    assert client.queries[0].filters == [
        ("eq", "id", USER),
        ("eq", "stripe_subscription_id", CURRENT_SUB),
    ]
    assert client.queries[1].ignore_duplicates is True


def test_database_compare_and_set_uses_null_predicate_for_unbound_profile():
    row = {"id": USER, "stripe_subscription_id": None}
    client = _ProfileUpdateClient(row)
    service = SupabaseService.__new__(SupabaseService)
    service._client = client

    updated = service.update_user_profile_if_subscription_matches(
        USER,
        None,
        {
            "subscription_status": "canceled",
            "stripe_subscription_id": CURRENT_SUB,
        },
    )

    assert updated is True
    assert row["subscription_status"] == "canceled"
    assert client.queries[0].filters == [
        ("eq", "id", USER),
        ("is", "stripe_subscription_id", "null"),
    ]


def test_database_compare_and_set_does_not_update_another_tenant_profile():
    other_user = "different-tenant-user"
    row = {"id": other_user, "stripe_subscription_id": CURRENT_SUB}
    client = _ProfileUpdateClient(row)
    service = SupabaseService.__new__(SupabaseService)
    service._client = client

    updated = service.update_user_profile_if_subscription_matches(
        USER,
        CURRENT_SUB,
        {"subscription_status": "canceled"},
    )

    assert updated is False
    assert "subscription_status" not in row
    assert client.queries[0].filters[0] == ("eq", "id", USER)


def test_database_compare_and_set_self_heals_missing_profile_without_overwriting_race():
    client = _ProfileUpdateClient(None)
    service = SupabaseService.__new__(SupabaseService)
    service._client = client

    updated = service.update_user_profile_if_subscription_matches(
        USER,
        None,
        {
            "subscription_status": "canceled",
            "stripe_subscription_id": CURRENT_SUB,
        },
    )

    assert updated is True
    assert client.row == {
        "id": USER,
        "email": f"{USER}@store.com",
        "tier": "starter",
        "subscription_tier": "starter",
        "subscription_status": "canceled",
        "stripe_subscription_id": CURRENT_SUB,
    }
    assert client.queries[1].ignore_duplicates is True


def test_pinned_postgrest_builders_encode_cas_and_insert_only_preferences():
    client = SyncPostgrestClient("http://127.0.0.1:9")
    try:
        compare_and_set = (
            client.from_("profiles")
            .update({"subscription_status": "canceled"})
            .eq("id", USER)
            .eq("stripe_subscription_id", CURRENT_SUB)
        )
        assert str(compare_and_set.params) == (
            f"id=eq.{USER}&stripe_subscription_id=eq.{CURRENT_SUB}"
        )
        assert compare_and_set.headers["Prefer"] == "return=representation"

        unbound_compare_and_set = (
            client.from_("profiles")
            .update({"subscription_status": "canceled"})
            .eq("id", USER)
            .is_("stripe_subscription_id", "null")
        )
        assert str(unbound_compare_and_set.params) == (
            f"id=eq.{USER}&stripe_subscription_id=is.null"
        )

        empty_subscription_compare_and_set = (
            client.from_("profiles")
            .update({"subscription_status": "canceled"})
            .eq("id", USER)
            .eq("stripe_subscription_id", "")
        )
        assert str(empty_subscription_compare_and_set.params) == (
            f"id=eq.{USER}&stripe_subscription_id=eq."
        )

        insert_only = client.from_("profiles").upsert(
            {"id": USER},
            ignore_duplicates=True,
        )
        assert insert_only.headers["Prefer"] == "return=representation,resolution=ignore-duplicates"
    finally:
        client.session.close()


def test_new_subscription_event_before_checkout_remains_retryable(harness):
    from fastapi import HTTPException

    set_profile, update, guarded_update, mark_processed, profile = harness
    set_profile(OLD_SUB)
    event = _event("customer.subscription.updated", "past_due", CURRENT_SUB)
    event["data"]["object"]["current_period_end"] = 1900000000
    with pytest.raises(HTTPException) as failure:
        stripe_service.process_webhook_event(event)
    assert failure.value.status_code == 503
    mark_processed.assert_not_called()
    update.assert_not_called()
    assert profile["stripe_subscription_id"] == OLD_SUB

    # Checkout binds B after the first delivery; retry the identical event ID.
    profile["stripe_subscription_id"] = CURRENT_SUB
    result = stripe_service.process_webhook_event(event)
    assert result["action"] == "subscription_updated"
    assert guarded_update.call_args.args[:2] == (USER, CURRENT_SUB)
    assert guarded_update.call_args.args[2]["subscription_status"] == "past_due"
    assert guarded_update.call_args.args[2]["current_period_end"]
    mark_processed.assert_called_once()
    calls = guarded_update.call_count
    assert stripe_service.process_webhook_event(event)["status"] == "already_processed"
    assert guarded_update.call_count == calls


@pytest.mark.parametrize("event_type,status", [("customer.subscription.updated", "past_due"), ("customer.subscription.deleted", "canceled")])
def test_ownership_mismatch_reaches_webhook_as_retryable_http(harness, monkeypatch, event_type, status):
    import asyncio
    import json
    from app.api.v1.billing import stripe_webhook_handler

    set_profile, update, guarded_update, mark_processed, profile = harness
    set_profile(OLD_SUB)
    payload = json.dumps(_event(event_type, status, CURRENT_SUB)).encode()

    class Request:
        headers = {"Stripe-Signature": "synthetic-test-signature"}

        async def body(self):
            return payload

    monkeypatch.setattr(stripe_service, "verify_webhook_signature", lambda *_: True)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(stripe_webhook_handler(Request()))
    assert failure.value.status_code == 503
    assert failure.value.detail == "Subscription ownership reconciliation pending"
    mark_processed.assert_not_called()
    update.assert_not_called()
    assert profile["stripe_subscription_id"] == OLD_SUB
