"""
AUTHZ-STRIPE-01 regression tests: the checkout.session.completed email fallback must only bind a
payment to the profile whose email is exactly the checkout email (case-insensitive), and only when
that profile is unique.

Defect (stripe_service.process_webhook_event, Fallback 1): when a signature-verified checkout
session has no client_reference_id or metadata.user_id, the profile is looked up with
`.ilike("email", cust_email)` and `res.data[0]` is taken. In an ILIKE pattern `_` and `%` are
wildcards, so `john_doe@...` also matches `john.doe@...`. The matched profile is then set to an
active paid subscription and its stripe_customer_id / stripe_subscription_id are overwritten.

The database is mocked to return the rows an unescaped ILIKE would return, and the tests assert
which profile, if any, is updated.
"""

from unittest.mock import MagicMock, PropertyMock

import pytest

from app.services.billing.stripe_service import stripe_service
from app.services.supabase_client import supabase_service

CHECKOUT_EMAIL = "john_doe@example.com"


@pytest.fixture
def harness(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(supabase_service, "_client", client)
    monkeypatch.setattr(type(supabase_service), "is_connected", PropertyMock(return_value=True), raising=False)
    monkeypatch.setattr(supabase_service, "_in_memory_profiles", {}, raising=False)
    update_mock = MagicMock()
    monkeypatch.setattr(supabase_service, "update_user_profile", update_mock)
    monkeypatch.setattr(stripe_service, "is_event_processed", lambda _eid: False)
    monkeypatch.setattr(stripe_service, "mark_event_processed", lambda *_a, **_k: None)

    def returning(rows):
        client.table.return_value.select.return_value.ilike.return_value.execute.return_value = MagicMock(data=rows)

    return returning, update_mock


def _event(email=CHECKOUT_EMAIL):
    return {
        "id": "evt_authz_email_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "customer_details": {"email": email},
            "customer": None,  # isolate Fallback 1 (no stripe_customer_id fallback)
            "subscription": "sub_authz_1",
            "metadata": {"plan_tier": "growth"},
        }},
    }


def _updated_user_ids(update_mock):
    return [call.args[0] for call in update_mock.call_args_list]


def test_wildcard_near_match_is_not_bound_to_the_payment(harness):
    returning, update_mock = harness
    returning([{"id": "victim-dot", "email": "john.doe@example.com"}])
    stripe_service.process_webhook_event(_event())
    assert "victim-dot" not in _updated_user_ids(update_mock)


def test_exact_match_is_chosen_over_wildcard_rows_case_insensitively(harness):
    returning, update_mock = harness
    returning([
        {"id": "victim-x", "email": "johnxdoe@example.com"},
        {"id": "payer", "email": "John_Doe@Example.com"},
    ])
    result = stripe_service.process_webhook_event(_event())
    assert _updated_user_ids(update_mock) == ["payer"]
    assert result["user_id"] == "payer"


def test_ambiguous_case_insensitive_duplicates_are_not_bound(harness):
    returning, update_mock = harness
    returning([
        {"id": "dup-1", "email": "john_doe@example.com"},
        {"id": "dup-2", "email": "JOHN_DOE@example.com"},
    ])
    stripe_service.process_webhook_event(_event())
    assert _updated_user_ids(update_mock) == []


def test_pure_wildcard_email_binds_nothing(harness):
    returning, update_mock = harness
    returning([{"id": "anyone-1", "email": "a@b.example"}, {"id": "anyone-2", "email": "c@d.example"}])
    stripe_service.process_webhook_event(_event(email="%@%"))
    assert _updated_user_ids(update_mock) == []


def test_metadata_user_id_path_is_unchanged(harness):
    returning, update_mock = harness
    event = _event()
    event["data"]["object"]["client_reference_id"] = "owner-from-session"
    stripe_service.process_webhook_event(event)
    assert _updated_user_ids(update_mock) == ["owner-from-session"]
