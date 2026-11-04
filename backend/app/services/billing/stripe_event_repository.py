"""Atomic Stripe reconciliation. Production persistence is ONE database RPC.

Only signature-verified Stripe events and server-owned prices belong here.
The memory implementation is a local test model, not database verification.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import threading

from app.services.supabase_client import DatabaseUnavailableError

_SUPPORTED = {"checkout.session.completed", "customer.subscription.updated", "customer.subscription.deleted"}
_LIMITS = {"starter": 1, "growth": 3, "agency": 20}
_MEMORY_LOCK = threading.RLock()


def _failure(message):
    raise DatabaseUnavailableError(message)


def _identifier(value):
    if isinstance(value, dict):
        return value.get("id")
    return value if isinstance(value, str) and value else None


def _tier(obj, prices, checkout):
    # Subscription events require actual prices. Checkout metadata is authored
    # by our server checkout API, carried in a signature-verified Stripe event,
    # and accepted only after mandatory server-side customer/tenant binding.
    items = (obj.get("line_items") if checkout else obj.get("items")) or {}
    rows = items.get("data", [])
    if checkout and not rows and isinstance(obj.get("subscription"), dict):
        rows = (obj["subscription"].get("items") or {}).get("data", [])
    if checkout and not rows:
        metadata = obj.get("metadata") or {}
        candidates = [metadata[key] for key in ("subscription_tier", "plan_tier") if metadata.get(key)]
        if not candidates or any(tier not in _LIMITS or not prices.get(tier) for tier in candidates) or len(set(candidates)) != 1:
            _failure("Checkout metadata must name one exact configured server tier")
        return candidates[0]
    if len(rows) != 1:
        _failure("Stripe event requires exactly one expanded subscription price")
    price_id = _identifier(rows[0].get("price"))
    matches = [tier for tier in _LIMITS if prices.get(tier) and prices[tier] == price_id]
    if len(matches) != 1:
        _failure("Unknown or ambiguous server Stripe price")
    return matches[0]


def process_atomic_stripe_event(event: dict, supabase_service, prices: dict) -> dict:
    """Return legacy action results; raise DatabaseUnavailableError for retry.

    With any client present, make exactly one process_stripe_billing_event RPC.
    RPC errors, malformed responses and ambiguous ordering NEVER fall back to
    profile table reads/writes or memory, including in development.
    """
    client = getattr(supabase_service, "_client", None)
    if client is not None:
        try:
            response = client.rpc("process_stripe_billing_event", {
                "p_event": event, "p_prices": prices,
            }).execute()
            result = response.data
            if not isinstance(result, dict) or result.get("status") not in {
                "success", "ignored", "already_processed"
            }:
                _failure("Invalid atomic Stripe RPC response")
            if result["status"] == "success" and (
                not result.get("user_id") or result.get("action") not in {
                    "subscription_activated", "subscription_updated", "subscription_downgraded"
                }
            ):
                _failure("Incomplete atomic Stripe RPC action")
            if result["status"] == "already_processed" and (
                result.get("event_id") != event.get("id") or result.get("idempotent") is not True
                or not isinstance(result.get("result"), dict)
            ):
                _failure("Incomplete atomic Stripe RPC duplicate result")
            if result["status"] == "ignored" and "event_type" not in result:
                _failure("Incomplete atomic Stripe RPC ignored result")
            return result
        except Exception as exc:
            raise DatabaseUnavailableError("Atomic Stripe reconciliation failed; retry required") from exc
    if not supabase_service._allow_in_memory_fallback():
        _failure("Atomic Stripe database is unavailable; memory fallback prohibited")
    with _MEMORY_LOCK:
        return _process_memory(event, supabase_service, prices)


def _process_memory(event, service, prices):
    kind = event.get("type")
    if kind not in _SUPPORTED:
        return {"status": "ignored", "event_type": kind}
    event_id, created = event.get("id"), event.get("created")
    if not isinstance(event_id, str) or not event_id or type(created) is not int or created < 0:
        _failure("Stripe event id and integer created are required")
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    state = getattr(service, "_atomic_stripe_state", None)
    if state is None:
        state = {"events": {}, "watermarks": {}}
        service._atomic_stripe_state = state
    previous = state["events"].get(event_id)
    if previous:
        if previous["hash"] != digest:
            _failure("Conflicting payload for existing Stripe event id")
        return {"status": "already_processed", "idempotent": True, "event_id": event_id, "result": deepcopy(previous["result"])}
    obj = (event.get("data") or {}).get("object") or {}
    customer = _identifier(obj.get("customer"))
    profiles = service._in_memory_profiles
    owners = [(uid, profile) for uid, profile in profiles.items() if customer and profile.get("stripe_customer_id") == customer]
    if len(owners) != 1:
        _failure("Stripe customer must have a unique server-side profile mapping")
    uid, profile = owners[0]
    metadata_uid = (obj.get("metadata") or {}).get("user_id")
    reference_uid = obj.get("client_reference_id")
    if any(str(value) != str(uid) for value in (metadata_uid, reference_uid) if value):
        _failure("Stripe event tenant metadata conflicts with customer mapping")
    watermark = state["watermarks"].get(uid)
    if watermark is not None and created == watermark[0]:
        _failure("Equal Stripe timestamps require authoritative reconciliation; retry required")
    if watermark is not None and created < watermark[0]:
        result = {"status": "ignored", "event_type": kind, "reason": "stale_event"}
        state["events"][event_id] = {"hash": digest, "result": result}
        return deepcopy(result)
    checkout = kind == "checkout.session.completed"
    subscription = _identifier(obj.get("subscription") if checkout else obj.get("id"))
    if not subscription:
        _failure("Stripe subscription id is required")
    existing = profile.get("stripe_subscription_id")
    if subscription in state.get("retired_subscriptions", {}).get(uid, set()):
        _failure("Retired subscription requires authoritative reconciliation; retry required")
    if not checkout and existing and existing != subscription:
        _failure("Different subscription requires authoritative reconciliation; retry required")
    if checkout:
        if obj.get("mode") != "subscription" or obj.get("payment_status") not in {"paid", "no_payment_required"}:
            _failure("Checkout must be subscription mode and paid or require no payment")
        expanded_subscription = obj.get("subscription")
        expanded_status = expanded_subscription.get("status") if isinstance(expanded_subscription, dict) else None
        if expanded_status is not None and expanded_status not in {"active", "trialing"}:
            _failure("Checkout subscription is not active or trialing")
        # no_payment_required is a Stripe-confirmed zero-payment checkout, not
        # an unpaid checkout. Do not infer trialing without subscription status.
        status = expanded_status or "active"
    else:
        status = obj.get("status")
    downgrade = kind == "customer.subscription.deleted" or status in {"canceled", "unpaid"}
    if not downgrade and status not in {"active", "past_due", "trialing"}:
        result = {"status": "ignored", "event_type": kind}
        state["events"][event_id] = {"hash": digest, "result": result}
        return deepcopy(result)
    tier = "starter" if downgrade else _tier(obj, prices, checkout)
    status = ("canceled" if status == "canceled" else "expired") if downgrade else status
    updates = {"subscription_tier": tier, "tier": tier, "subscription_status": status,
               "stripe_subscription_id": subscription, "updated_at": datetime.now(timezone.utc).isoformat()}
    if obj.get("current_period_end") is not None:
        period = obj["current_period_end"]
        if type(period) is not int or period < 0:
            _failure("Invalid subscription current_period_end")
        updates["current_period_end"] = datetime.fromtimestamp(period, timezone.utc).isoformat()
    result = {"status": "success", "user_id": uid}
    if checkout:
        result.update(action="subscription_activated", subscription_tier=tier, tier=tier, customer_id=customer)
    else:
        result.update(action="subscription_downgraded" if downgrade else "subscription_updated", subscription_status=status)
    snapshot = deepcopy(profiles)
    try:
        updated = service.update_user_profile(uid, updates)
        if not updated or any(updated.get(key) != value for key, value in updates.items()):
            _failure("Stripe profile update did not persist")
    except Exception as exc:
        profiles.clear()
        profiles.update(snapshot)
        service._in_memory_profiles = profiles
        raise DatabaseUnavailableError("Atomic local Stripe profile update failed") from exc
    if existing and existing != subscription:
        state.setdefault("retired_subscriptions", {}).setdefault(uid, set()).add(existing)
    state["watermarks"][uid] = (created, event_id)
    state["events"][event_id] = {"hash": digest, "result": deepcopy(result)}
    return result
