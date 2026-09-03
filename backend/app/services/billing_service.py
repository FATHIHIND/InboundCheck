"""
InboundCheck - Stripe Billing & Subscription Service
====================================================
Handles Stripe Checkout Sessions, Customer Billing Portal, and webhook event processing.
"""

from typing import Dict, Any, Optional
import hmac
import hashlib
import time
import logging
import httpx

from app.core.config import settings
from app.services.supabase_client import supabase_service

logger = logging.getLogger("BillingService")

PLAN_PRICING = {
    "starter": {"name": "Starter Plan", "amount": 2900, "currency": "usd", "interval": "month"},
    "growth": {"name": "Growth Plan", "amount": 7900, "currency": "usd", "interval": "month"},
    "enterprise": {"name": "Enterprise Plan", "amount": 19900, "currency": "usd", "interval": "month"},
}


class BillingService:
    """
    Service for managing subscriptions, checkout sessions, and webhook reconciliation.
    """

    def __init__(self):
        self.secret_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        self._processed_events: Dict[str, float] = {}

    def is_event_processed(self, event_id: str) -> bool:
        """Check if Stripe event has already been processed (24-hour TTL)."""
        if not event_id:
            return False
        now = time.time()
        # Evict expired events older than 24 hours (86400s)
        self._processed_events = {
            eid: ts for eid, ts in self._processed_events.items() if now - ts < 86400
        }
        return event_id in self._processed_events

    def mark_event_processed(self, event_id: str):
        """Mark Stripe event as successfully reconciled."""
        if event_id:
            self._processed_events[event_id] = time.time()

    def get_price_for_tier(self, tier: str) -> Dict[str, Any]:
        """Return plan metadata and price amount in cents."""
        return PLAN_PRICING.get(tier.lower(), PLAN_PRICING["growth"])

    async def create_checkout_session(
        self,
        user_id: str,
        email: str,
        plan_tier: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session for subscription signup.
        """
        tier = plan_tier.lower()
        if tier not in PLAN_PRICING:
            tier = "growth"

        plan_meta = self.get_price_for_tier(tier)
        s_url = success_url or f"{settings.FRONTEND_URL}/dashboard?checkout=success&plan={tier}"
        c_url = cancel_url or f"{settings.FRONTEND_URL}/#pricing"

        if self.secret_key:
            try:
                # Direct Stripe API call via HTTPX
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        "https://api.stripe.com/v1/checkout/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data={
                            "mode": "subscription",
                            "payment_method_types[0]": "card",
                            "customer_email": email,
                            "client_reference_id": user_id,
                            "metadata[user_id]": user_id,
                            "metadata[plan_tier]": tier,
                            "success_url": s_url,
                            "cancel_url": c_url,
                            "line_items[0][price_data][currency]": plan_meta["currency"],
                            "line_items[0][price_data][product_data][name]": f"InboundCheck {plan_meta['name']}",
                            "line_items[0][price_data][unit_amount]": plan_meta["amount"],
                            "line_items[0][price_data][recurring][interval]": plan_meta["interval"],
                            "line_items[0][quantity]": 1,
                        }
                    )
                    if res.status_code == 200:
                        data = res.json()
                        return {
                            "session_id": data.get("id"),
                            "checkout_url": data.get("url"),
                            "plan_tier": tier,
                            "amount": plan_meta["amount"] / 100
                        }
            except Exception as e:
                logger.error(f"Stripe API error: {e}")

        # Local development / fallback simulation
        mock_id = f"cs_test_{int(time.time())}_{user_id[:8]}"
        return {
            "session_id": mock_id,
            "checkout_url": s_url,
            "plan_tier": tier,
            "amount": plan_meta["amount"] / 100,
            "mode": "simulation"
        }

    async def create_customer_portal_session(
        self,
        user_id: str,
        customer_id: Optional[str] = None,
        return_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a Stripe Customer Portal Session for billing and invoice management.
        """
        r_url = return_url or f"{settings.FRONTEND_URL}/dashboard/settings"

        if self.secret_key and customer_id:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        "https://api.stripe.com/v1/billing_portal/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data={"customer": customer_id, "return_url": r_url}
                    )
                    if res.status_code == 200:
                        return {"portal_url": res.json().get("url")}
            except Exception as e:
                logger.error(f"Stripe Portal error: {e}")

        return {"portal_url": r_url}

    def verify_webhook_signature(self, payload: bytes, sig_header: str, tolerance_seconds: int = 300) -> bool:
        """
        Verify Stripe signature header using timestamped HMAC-SHA256.
        Enforces strict timestamp tolerance (300s) and fail-closed verification in production.
        """
        if not sig_header:
            if not self.webhook_secret and settings.ENVIRONMENT == "development":
                return True
            return False

        try:
            sig_dict = {}
            for item in sig_header.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    sig_dict[k.strip()] = v.strip()

            t = sig_dict.get("t")
            v1 = sig_dict.get("v1")

            if not t or not v1:
                return False

            # Enforce drift tolerance window (±300 seconds default)
            timestamp = int(t)
            current_time = int(time.time())
            if abs(current_time - timestamp) > tolerance_seconds:
                logger.warning(
                    f"Stripe webhook timestamp {timestamp} outside ±{tolerance_seconds}s tolerance (current: {current_time})"
                )
                return False

            if not self.webhook_secret:
                if settings.ENVIRONMENT == "development":
                    logger.warning("STRIPE_WEBHOOK_SECRET is not configured - allowing valid timestamp in development mode.")
                    return True
                logger.error("Stripe webhook verification failed: STRIPE_WEBHOOK_SECRET not configured in production.")
                return False

            signed_payload = f"{t}.".encode("utf-8") + payload
            computed = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(v1, computed)
        except Exception as e:
            logger.error(f"Stripe signature verification failed: {e}")
            return False

    def process_webhook_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reconcile Stripe event and update user subscription tier in database with idempotency protection.
        """
        event_id = event.get("id")
        if event_id and self.is_event_processed(event_id):
            logger.info(f"Stripe webhook {event_id} already processed; skipping duplicate delivery.")
            return {"status": "already_processed", "idempotent": True, "event_id": event_id}

        event_type = event.get("type")
        data_object = event.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            user_id = data_object.get("client_reference_id") or data_object.get("metadata", {}).get("user_id")
            plan_tier = data_object.get("metadata", {}).get("plan_tier", "growth")

            if user_id:
                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("profiles").update({
                            "plan_tier": plan_tier,
                            "updated_at": "now()"
                        }).eq("id", user_id).execute()
                    except Exception as e:
                        logger.error(f"Failed to update profile subscription in Supabase: {e}")

                if event_id:
                    self.mark_event_processed(event_id)

                return {"status": "success", "action": "subscription_activated", "user_id": user_id, "tier": plan_tier}

        elif event_type in ["customer.subscription.deleted", "customer.subscription.updated"]:
            status = data_object.get("status")
            user_id = data_object.get("metadata", {}).get("user_id")

            if user_id and status == "canceled":
                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("profiles").update({
                            "plan_tier": "starter"
                        }).eq("id", user_id).execute()
                    except Exception as e:
                        logger.error(f"Failed to downgrade profile: {e}")

                if event_id:
                    self.mark_event_processed(event_id)

                return {"status": "success", "action": "subscription_downgraded", "user_id": user_id}

        if event_id:
            self.mark_event_processed(event_id)

        return {"status": "ignored", "event_type": event_type}


billing_service = BillingService()
