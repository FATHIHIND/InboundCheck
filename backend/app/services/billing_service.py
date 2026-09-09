"""
InboundCheck - Stripe Billing & Subscription Service
====================================================
Handles Stripe Checkout Sessions, Customer Billing Portal, and webhook event processing.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
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
        Automatically resolves stripe_customer_id from user's profile if not supplied.
        """
        r_url = return_url or f"{settings.FRONTEND_URL}/dashboard/billing"
        resolved_customer_id = customer_id

        # Lookup stripe_customer_id from Supabase profile if omitted
        if not resolved_customer_id and supabase_service.is_connected:
            try:
                profile = supabase_service.get_user_profile(user_id)
                if profile:
                    resolved_customer_id = profile.get("stripe_customer_id")
            except Exception as e:
                logger.warning(f"Could not resolve stripe_customer_id for user {user_id}: {e}")

        if self.secret_key and resolved_customer_id:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        "https://api.stripe.com/v1/billing_portal/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data={"customer": resolved_customer_id, "return_url": r_url}
                    )
                    if res.status_code == 200:
                        return {"portal_url": res.json().get("url"), "has_customer": True}
                    else:
                        logger.error(f"Stripe Portal API returned {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Stripe Portal error: {e}")

        return {
            "portal_url": r_url,
            "has_customer": bool(resolved_customer_id),
            "message": "No active Stripe customer account found." if not resolved_customer_id else "Portal session ready"
        }

    async def get_customer_invoices(
        self,
        user_id: str,
        customer_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch paid and processing invoices from Stripe Invoices API for customer.
        """
        resolved_customer_id = customer_id
        if not resolved_customer_id and supabase_service.is_connected:
            try:
                profile = supabase_service.get_user_profile(user_id)
                if profile:
                    resolved_customer_id = profile.get("stripe_customer_id")
            except Exception as e:
                logger.warning(f"Could not resolve stripe_customer_id for user {user_id}: {e}")

        if self.secret_key and resolved_customer_id:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(
                        f"https://api.stripe.com/v1/invoices?customer={resolved_customer_id}&limit={limit}",
                        headers={"Authorization": f"Bearer {self.secret_key}"}
                    )
                    if res.status_code == 200:
                        stripe_data = res.json()
                        invoices = []
                        for inv in stripe_data.get("data", []):
                            amount_paid = inv.get("amount_paid", 0) / 100
                            currency = (inv.get("currency") or "usd").upper()
                            p_start_ts = inv.get("period_start") or inv.get("created") or time.time()
                            p_end_ts = inv.get("period_end") or inv.get("created") or time.time()
                            period_start = datetime.fromtimestamp(p_start_ts).strftime("%b %d, %Y")
                            period_end = datetime.fromtimestamp(p_end_ts).strftime("%b %d, %Y")
                            invoices.append({
                                "id": inv.get("id"),
                                "invoice_number": inv.get("number") or f"INV-{inv.get('id', '')[-6:].upper()}",
                                "billing_period": f"{period_start} – {period_end}",
                                "amount": f"${amount_paid:.2f} {currency}",
                                "status": "paid" if inv.get("status") == "paid" else (inv.get("status") or "processing"),
                                "pdf_url": inv.get("invoice_pdf") or inv.get("hosted_invoice_url") or "#",
                                "created_at": inv.get("created")
                            })
                        return invoices
                    else:
                        logger.warning(f"Stripe invoices API responded with {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Error fetching Stripe invoices: {e}")

        # Return empty list if no customer ID or local simulation
        return []

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
        Persists stripe_customer_id, stripe_subscription_id, and subscription_status.
        """
        event_id = event.get("id")
        if event_id and self.is_event_processed(event_id):
            logger.info(f"Stripe webhook {event_id} already processed; skipping duplicate delivery.")
            return {"status": "already_processed", "idempotent": True, "event_id": event_id}

        event_type = event.get("type")
        data_object = event.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            user_id = data_object.get("client_reference_id") or data_object.get("metadata", {}).get("user_id")
            raw_tier = data_object.get("metadata", {}).get("plan_tier", "growth").lower()
            plan_tier = raw_tier if raw_tier in ["starter", "growth", "enterprise"] else "growth"
            customer_id = data_object.get("customer")
            subscription_id = data_object.get("subscription")

            if user_id:
                if supabase_service.is_connected:
                    try:
                        update_payload: Dict[str, Any] = {
                            "tier": plan_tier,
                            "subscription_status": "active",
                            "updated_at": "now()"
                        }
                        if customer_id:
                            update_payload["stripe_customer_id"] = customer_id
                        if subscription_id:
                            update_payload["stripe_subscription_id"] = subscription_id

                        supabase_service._client.table("profiles").update(update_payload).eq("id", user_id).execute()
                    except Exception as e:
                        logger.error(f"Failed to update profile subscription in Supabase: {e}")

                if event_id:
                    self.mark_event_processed(event_id)

                return {
                    "status": "success",
                    "action": "subscription_activated",
                    "user_id": user_id,
                    "tier": plan_tier,
                    "customer_id": customer_id
                }

        elif event_type in ["customer.subscription.deleted", "customer.subscription.updated"]:
            status = data_object.get("status")
            user_id = data_object.get("metadata", {}).get("user_id")
            customer_id = data_object.get("customer")

            # If user_id missing in metadata, resolve via stripe_customer_id
            if not user_id and customer_id and supabase_service.is_connected:
                try:
                    res = supabase_service._client.table("profiles").select("id").eq("stripe_customer_id", customer_id).execute()
                    if res.data and len(res.data) > 0:
                        user_id = res.data[0]["id"]
                except Exception as e:
                    logger.error(f"Failed to resolve user_id for customer {customer_id}: {e}")

            if user_id and (status == "canceled" or event_type == "customer.subscription.deleted"):
                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("profiles").update({
                            "tier": "starter",
                            "subscription_status": "canceled",
                            "updated_at": "now()"
                        }).eq("id", user_id).execute()
                    except Exception as e:
                        logger.error(f"Failed to downgrade profile: {e}")

                if event_id:
                    self.mark_event_processed(event_id)

                return {"status": "success", "action": "subscription_downgraded", "user_id": user_id}

            elif user_id and status == "active":
                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("profiles").update({
                            "subscription_status": "active",
                            "updated_at": "now()"
                        }).eq("id", user_id).execute()
                    except Exception as e:
                        logger.error(f"Failed to update subscription status: {e}")

                if event_id:
                    self.mark_event_processed(event_id)

                return {"status": "success", "action": "subscription_updated", "user_id": user_id}

        if event_id:
            self.mark_event_processed(event_id)

        return {"status": "ignored", "event_type": event_type}


billing_service = BillingService()
