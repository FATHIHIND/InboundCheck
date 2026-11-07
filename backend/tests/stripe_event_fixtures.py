"""Realistic, complete Stripe envelopes for positive billing tests only.

These helpers construct input fixtures; they do not patch reconciliation or
relax validation. Customer ownership is persisted explicitly by each caller.
"""
from copy import deepcopy
import time

from app.services.billing.stripe_service import stripe_service

_created_by_tenant = {}


def bind_stripe_customer(service, user_id, customer_id):
    """Establish the local server-owned customer mapping before delivery."""
    service.get_user_profile(user_id)
    profile = service.update_user_profile(user_id, {"stripe_customer_id": customer_id})
    assert profile["stripe_customer_id"] == customer_id


def complete_stripe_event(event, *, tier=None):
    """Complete a positive synthetic event with realistic Stripe-owned fields.

    Supply a canonical configured tier for paid checkout/subscription events.
    Explicit fields remain untouched, so intentional metadata remains testable.
    Separate events for one tenant have strictly increasing creation timestamps;
    callers reuse the returned envelope for duplicate-delivery tests.
    """
    event = deepcopy(event)
    obj = event["data"]["object"]
    tenant = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id") or obj["customer"]
    created = max(int(time.time()), _created_by_tenant.get(tenant, 0) + 1)
    event.setdefault("created", created)
    _created_by_tenant[tenant] = event["created"]
    event.setdefault("object", "event")
    event.setdefault("livemode", False)
    checkout = event["type"] == "checkout.session.completed"
    obj.setdefault("object", "checkout.session" if checkout else "subscription")
    if checkout:
        obj.setdefault("id", "cs_test_" + event["id"])
        obj.setdefault("mode", "subscription")
        obj.setdefault("payment_status", "paid")
        obj.setdefault("status", "complete")
    if tier is not None:
        price_id = stripe_service.prices[tier]
        assert isinstance(price_id, str) and price_id, "Test requires a configured server Price ID"
        # Expanded checkout line items make price authority explicit, including
        # legacy enterprise metadata whose actual purchased price is Agency.
        obj.setdefault("line_items" if checkout else "items", {
            "object": "list",
            "data": [{"id": "li_test_" + event["id"], "quantity": 1,
                      "price": {"id": price_id, "object": "price"}}],
            "has_more": False,
        })
    return event
