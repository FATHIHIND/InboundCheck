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

Expected: when the profile stores a subscription id and the event names a different one, the event
is ignored. Matching ids, events without an id, and profiles with no stored id keep the existing
behaviour.
"""

from unittest.mock import MagicMock

import pytest

from app.services.billing.stripe_service import stripe_service
from app.services.supabase_client import supabase_service

USER = "sub-owner-user"
CURRENT_SUB = "sub_current_Y"
OLD_SUB = "sub_superseded_X"


@pytest.fixture
def harness(monkeypatch):
    update = MagicMock()
    monkeypatch.setattr(supabase_service, "update_user_profile", update)
    monkeypatch.setattr(stripe_service, "is_event_processed", lambda _eid: False)
    monkeypatch.setattr(stripe_service, "mark_event_processed", lambda *_a, **_k: None)

    def set_profile(stored_subscription_id, status="active"):
        profile = {"id": USER, "subscription_tier": "growth", "subscription_status": status}
        if stored_subscription_id:
            profile["stripe_subscription_id"] = stored_subscription_id
        monkeypatch.setattr(supabase_service, "get_user_profile", lambda uid, *a, **k: dict(profile))

    return set_profile, update


def _event(event_type, sub_status, sub_id=OLD_SUB):
    obj = {"status": sub_status, "customer": "cus_owner", "metadata": {"user_id": USER}}
    if sub_id is not None:
        obj["id"] = sub_id
    return {"id": f"evt_{event_type}_{sub_status}_{sub_id}", "type": event_type, "data": {"object": obj}}


def test_late_delete_of_superseded_subscription_does_not_downgrade_the_current_one(harness):
    set_profile, update = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", OLD_SUB))
    update.assert_not_called()
    assert result["status"] == "ignored"


def test_late_past_due_update_of_superseded_subscription_does_not_change_status(harness):
    set_profile, update = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.updated", "past_due", OLD_SUB))
    update.assert_not_called()
    assert result["status"] == "ignored"


def test_deleting_the_current_subscription_still_downgrades(harness):
    set_profile, update = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", CURRENT_SUB))
    assert result["action"] == "subscription_downgraded"
    assert update.call_args.args[1]["subscription_status"] == "canceled"


def test_current_subscription_update_is_still_applied(harness):
    set_profile, update = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.updated", "past_due", CURRENT_SUB))
    assert result["action"] == "subscription_updated"
    assert update.call_args.args[1]["subscription_status"] == "past_due"


def test_profile_without_a_stored_subscription_id_keeps_existing_behaviour(harness):
    set_profile, update = harness
    set_profile(None)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", OLD_SUB))
    assert result["action"] == "subscription_downgraded"
    update.assert_called_once()


def test_event_without_a_subscription_id_keeps_existing_behaviour(harness):
    set_profile, update = harness
    set_profile(CURRENT_SUB)
    result = stripe_service.process_webhook_event(_event("customer.subscription.deleted", "canceled", None))
    assert result["action"] == "subscription_downgraded"
    update.assert_called_once()
