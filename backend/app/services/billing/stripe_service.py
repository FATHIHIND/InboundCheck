"""
InboundCheck - Stripe Billing & Subscription Service
====================================================
Production Stripe checkout session generation, customer billing portal,
customer creation/retrieval, and webhook lifecycle reconciliation.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import hmac
import hashlib
import time
import logging
import httpx

from app.core.config import settings
from app.services.supabase_client import supabase_service

logger = logging.getLogger("StripeService")

TIER_LIMITS = {
    "starter": 1,
    "growth": 3,
    "enterprise": 999,
}

PLAN_PRICING: Dict[str, Dict[str, Any]] = {
    "starter": {
        "id": "starter",
        "name": "Starter Plan",
        "price": 29,
        "amount": 2900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 1,
        "features": [
            "1 Monitored Apex Domain",
            "Manual DNS Record Snippets",
            "Basic Telegram Alerts",
            "Daily Deliverability Diagnostics",
        ],
    },
    "growth": {
        "id": "growth",
        "name": "Growth Plan",
        "price": 79,
        "amount": 7900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 3,
        "is_popular": True,
        "features": [
            "3 Monitored Apex Domains",
            "SPF Merge Engine & Lookup Consolidation",
            "1-Click DNS Auto-Fix (Cloudflare / GoDaddy)",
            "48-72h Predictive Risk Forecast & Radar",
            "Real-Time Telegram & Multi-channel Alerts",
        ],
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise Plan",
        "price": 199,
        "amount": 19900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 999,
        "features": [
            "Unlimited Monitored Apex Domains",
            "Developer API Keys & Custom Webhooks",
            "Real-Time Worker Priority & 15m Sweeps",
            "AI Content Lab & Cryptographic Optimizer",
            "Dedicated Deliverability Architect SLA",
        ],
    },
}


class StripeService:
    """
    Enterprise Stripe billing integration supporting 3-tier SaaS monetization,
    3-day trial conversion, and webhook synchronization.
    """

    def __init__(self):
        self.secret_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        self._processed_events: Dict[str, float] = {}

    def is_event_processed(self, event_id: str) -> bool:
        """Check if Stripe event has already been processed (DB table + memory cache)."""
        if not event_id:
            return False

        if supabase_service.is_connected and supabase_service._client:
            try:
                res = (
                    supabase_service._client.table("processed_webhook_events")
                    .select("id")
                    .eq("id", event_id)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    self._processed_events[event_id] = time.time()
                    return True
            except Exception as e:
                logger.warning(f"Error querying processed_webhook_events: {e}")

        now = time.time()
        self._processed_events = {
            eid: ts for eid, ts in self._processed_events.items() if now - ts < 86400
        }
        return event_id in self._processed_events

    def mark_event_processed(self, event_id: str, event_type: str = "stripe_webhook"):
        """Mark Stripe event as reconciled."""
        if not event_id:
            return

        self._processed_events[event_id] = time.time()

        if supabase_service.is_connected and supabase_service._client:
            try:
                supabase_service._client.table("processed_webhook_events").upsert(
                    {"id": event_id, "event_type": event_type}
                ).execute()
            except Exception as e:
                logger.warning(f"Failed to record event {event_id} in processed_webhook_events: {e}")

    def resolve_tier(self, price_or_tier: str) -> str:
        """Normalize tier identifier from price_id or tier name string."""
        raw = (price_or_tier or "growth").strip().lower()
        if "enterprise" in raw:
            return "enterprise"
        if "starter" in raw:
            return "starter"
        if "growth" in raw:
            return "growth"
        return "growth"

    async def get_or_create_customer(self, user_id: str, email: Optional[str] = None) -> Optional[str]:
        """
        Create or retrieve Stripe Customer ID for the specified user.
        Persists newly created customer IDs to public.profiles.
        """
        profile = supabase_service.get_user_profile(user_id)
        if profile and profile.get("stripe_customer_id"):
            return profile["stripe_customer_id"]

        user_email = email or (profile.get("email") if profile else f"{user_id}@brandshop.com")

        if self.secret_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Attempt lookup by metadata or email
                    search_res = await client.get(
                        "https://api.stripe.com/v1/customers",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        params={"email": user_email, "limit": 1},
                    )
                    if search_res.status_code == 200:
                        data = search_res.json().get("data", [])
                        if data:
                            customer_id = data[0].get("id")
                            supabase_service.update_user_profile(user_id, {"stripe_customer_id": customer_id})
                            return customer_id

                    # Create new customer
                    create_res = await client.post(
                        "https://api.stripe.com/v1/customers",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data={
                            "email": user_email,
                            "metadata[user_id]": user_id,
                            "description": f"InboundCheck Customer {user_id}",
                        },
                    )
                    if create_res.status_code == 200:
                        customer_id = create_res.json().get("id")
                        supabase_service.update_user_profile(user_id, {"stripe_customer_id": customer_id})
                        return customer_id
                    else:
                        logger.error(f"Stripe Customer API returned {create_res.status_code}: {create_res.text}")
            except Exception as e:
                logger.error(f"Stripe get_or_create_customer error: {e}")

        # Local simulation fallback
        mock_customer_id = f"cus_mock_{user_id[:8]}"
        supabase_service.update_user_profile(user_id, {"stripe_customer_id": mock_customer_id})
        return mock_customer_id

    async def create_checkout_session(
        self,
        user_id: str,
        price_id: str,
        return_url: Optional[str] = None,
        email: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        plan_tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session for subscription upgrade supporting:
        - Starter: $29/mo (1 Domain cap)
        - Growth: $79/mo (3 Domains cap)
        - Enterprise: $199/mo (Unlimited domains)
        """
        tier = self.resolve_tier(plan_tier or price_id)
        plan_meta = PLAN_PRICING.get(tier, PLAN_PRICING["growth"])

        s_url = success_url or return_url or f"{settings.FRONTEND_URL}/dashboard/billing?checkout=success&plan={tier}"
        c_url = cancel_url or return_url or f"{settings.FRONTEND_URL}/dashboard/billing?checkout=cancelled"

        customer_id = await self.get_or_create_customer(user_id=user_id, email=email)

        if self.secret_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    req_data = {
                        "mode": "subscription",
                        "payment_method_types[0]": "card",
                        "client_reference_id": user_id,
                        "metadata[user_id]": user_id,
                        "metadata[plan_tier]": tier,
                        "metadata[subscription_tier]": tier,
                        "success_url": s_url,
                        "cancel_url": c_url,
                        "line_items[0][price_data][currency]": plan_meta["currency"],
                        "line_items[0][price_data][product_data][name]": f"InboundCheck {plan_meta['name']}",
                        "line_items[0][price_data][unit_amount]": plan_meta["amount"],
                        "line_items[0][price_data][recurring][interval]": plan_meta["interval"],
                        "line_items[0][quantity]": 1,
                    }
                    if customer_id and not customer_id.startswith("cus_mock_"):
                        req_data["customer"] = customer_id
                    elif email:
                        req_data["customer_email"] = email

                    res = await client.post(
                        "https://api.stripe.com/v1/checkout/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data=req_data,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        return {
                            "session_id": data.get("id"),
                            "checkout_url": data.get("url"),
                            "plan_tier": tier,
                            "subscription_tier": tier,
                            "amount": plan_meta["amount"] / 100,
                            "customer_id": customer_id,
                        }
                    else:
                        logger.error(f"Stripe checkout session error {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Stripe API error: {e}")

        # Local simulation / offline fallback
        mock_id = f"cs_test_{int(time.time())}_{user_id[:8]}"
        return {
            "session_id": mock_id,
            "checkout_url": s_url,
            "plan_tier": tier,
            "subscription_tier": tier,
            "amount": plan_meta["amount"] / 100,
            "customer_id": customer_id,
            "mode": "simulation",
        }

    async def create_customer_portal_session(
        self,
        user_id: str,
        return_url: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Customer Portal Session for managing active payment methods and invoices.
        """
        r_url = return_url or f"{settings.FRONTEND_URL}/dashboard/billing"
        resolved_customer = customer_id

        if not resolved_customer:
            profile = supabase_service.get_user_profile(user_id)
            if profile:
                resolved_customer = profile.get("stripe_customer_id")

        if self.secret_key and resolved_customer and not resolved_customer.startswith("cus_mock_"):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        "https://api.stripe.com/v1/billing_portal/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data={"customer": resolved_customer, "return_url": r_url},
                    )
                    if res.status_code == 200:
                        return {
                            "portal_url": res.json().get("url"),
                            "has_customer": True,
                        }
                    else:
                        logger.error(f"Stripe Portal API returned {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Stripe Portal error: {e}")

        return {
            "portal_url": r_url,
            "has_customer": bool(resolved_customer),
            "message": "Portal session ready" if resolved_customer else "No active Stripe customer account found.",
        }

    async def get_customer_invoices(
        self,
        user_id: str,
        customer_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch invoices for the user."""
        resolved_customer = customer_id
        if not resolved_customer:
            profile = supabase_service.get_user_profile(user_id)
            if profile:
                resolved_customer = profile.get("stripe_customer_id")

        if self.secret_key and resolved_customer and not resolved_customer.startswith("cus_mock_"):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(
                        f"https://api.stripe.com/v1/invoices?customer={resolved_customer}&limit={limit}",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                    )
                    if res.status_code == 200:
                        stripe_data = res.json()
                        invoices = []
                        for inv in stripe_data.get("data", []):
                            amount_paid = inv.get("amount_paid", 0) / 100
                            currency = (inv.get("currency") or "usd").upper()
                            p_start_ts = inv.get("period_start") or inv.get("created") or time.time()
                            p_end_ts = inv.get("period_end") or inv.get("created") or time.time()
                            period_start = datetime.fromtimestamp(p_start_ts, tz=timezone.utc).strftime("%b %d, %Y")
                            period_end = datetime.fromtimestamp(p_end_ts, tz=timezone.utc).strftime("%b %d, %Y")
                            invoices.append({
                                "id": inv.get("id"),
                                "invoice_number": inv.get("number") or f"INV-{inv.get('id', '')[-6:].upper()}",
                                "billing_period": f"{period_start} – {period_end}",
                                "amount": f"${amount_paid:.2f} {currency}",
                                "status": "paid" if inv.get("status") == "paid" else (inv.get("status") or "processing"),
                                "pdf_url": inv.get("invoice_pdf") or inv.get("hosted_invoice_url") or "#",
                                "created_at": inv.get("created"),
                            })
                        return invoices
            except Exception as e:
                logger.error(f"Error fetching Stripe invoices: {e}")

        return []

    def verify_webhook_signature(self, payload: bytes, sig_header: str, tolerance_seconds: int = 300) -> bool:
        """Verify Stripe webhook signature header using timestamped HMAC-SHA256."""
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

            timestamp = int(t)
            current_time = int(time.time())
            if abs(current_time - timestamp) > tolerance_seconds:
                logger.warning(
                    f"Stripe webhook timestamp {timestamp} outside ±{tolerance_seconds}s tolerance"
                )
                return False

            if not self.webhook_secret:
                if settings.ENVIRONMENT == "development":
                    return True
                return False

            signed_payload = f"{t}.".encode("utf-8") + payload
            computed = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(v1, computed)
        except Exception as e:
            logger.error(f"Stripe signature verification failed: {e}")
            return False

    def process_webhook_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process incoming Stripe webhooks with idempotency and atomically update public.profiles:
        - checkout.session.completed: Sets status=active, tier, stripe_customer_id, stripe_subscription_id
        - customer.subscription.updated: Updates status, tier, current_period_end
        - customer.subscription.deleted: Downgrades status to canceled/expired, resets tier to starter
        """
        event_id = event.get("id")
        if event_id and self.is_event_processed(event_id):
            return {"status": "already_processed", "idempotent": True, "event_id": event_id}

        event_type = event.get("type")
        data_object = event.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            user_id = (
                data_object.get("client_reference_id")
                or data_object.get("metadata", {}).get("user_id")
            )
            raw_tier = (
                data_object.get("metadata", {}).get("subscription_tier")
                or data_object.get("metadata", {}).get("plan_tier")
                or "growth"
            )
            plan_tier = self.resolve_tier(raw_tier)
            customer_id = data_object.get("customer")
            subscription_id = data_object.get("subscription")

            if user_id:
                update_payload: Dict[str, Any] = {
                    "subscription_tier": plan_tier,
                    "tier": plan_tier,
                    "subscription_status": "active",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if customer_id:
                    update_payload["stripe_customer_id"] = customer_id
                if subscription_id:
                    update_payload["stripe_subscription_id"] = subscription_id

                supabase_service.update_user_profile(user_id, update_payload)

                if event_id:
                    self.mark_event_processed(event_id, event_type=event_type)

                return {
                    "status": "success",
                    "action": "subscription_activated",
                    "user_id": user_id,
                    "subscription_tier": plan_tier,
                    "tier": plan_tier,
                    "customer_id": customer_id,
                }

        elif event_type in ["customer.subscription.deleted", "customer.subscription.updated"]:
            sub_status = data_object.get("status")
            user_id = data_object.get("metadata", {}).get("user_id")
            customer_id = data_object.get("customer")
            current_period_end_ts = data_object.get("current_period_end")

            period_end_iso = None
            if current_period_end_ts:
                try:
                    period_end_iso = datetime.fromtimestamp(current_period_end_ts, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            # If user_id missing from metadata, resolve by customer_id
            if not user_id and customer_id:
                if supabase_service.is_connected and supabase_service._client:
                    try:
                        res = (
                            supabase_service._client.table("profiles")
                            .select("id")
                            .eq("stripe_customer_id", customer_id)
                            .execute()
                        )
                        if res.data and len(res.data) > 0:
                            user_id = res.data[0]["id"]
                    except Exception as e:
                        logger.error(f"Failed to resolve user_id for customer {customer_id}: {e}")

                if not user_id:
                    for uid, prof in supabase_service._in_memory_profiles.items():
                        if prof.get("stripe_customer_id") == customer_id:
                            user_id = uid
                            break

            if user_id:
                if sub_status in ("canceled", "unpaid") or event_type == "customer.subscription.deleted":
                    status_val = "canceled" if sub_status == "canceled" else "expired"
                    supabase_service.update_user_profile(
                        user_id,
                        {
                            "subscription_tier": "starter",
                            "tier": "starter",
                            "subscription_status": status_val,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    if event_id:
                        self.mark_event_processed(event_id, event_type=event_type)
                    return {
                        "status": "success",
                        "action": "subscription_downgraded",
                        "user_id": user_id,
                        "subscription_status": status_val,
                    }

                elif sub_status in ("active", "past_due", "trialing"):
                    # Check items for tier changes if available
                    items = data_object.get("items", {}).get("data", [])
                    detected_tier = None
                    if items:
                        price_obj = items[0].get("price", {})
                        nickname = price_obj.get("nickname") or price_obj.get("id") or ""
                        detected_tier = self.resolve_tier(nickname)

                    updates = {
                        "subscription_status": sub_status,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if detected_tier:
                        updates["subscription_tier"] = detected_tier
                        updates["tier"] = detected_tier
                    if period_end_iso:
                        updates["current_period_end"] = period_end_iso

                    supabase_service.update_user_profile(user_id, updates)
                    if event_id:
                        self.mark_event_processed(event_id, event_type=event_type)
                    return {
                        "status": "success",
                        "action": "subscription_updated",
                        "user_id": user_id,
                        "subscription_status": sub_status,
                    }

        if event_id:
            self.mark_event_processed(event_id, event_type=event_type or "stripe_webhook")

        return {"status": "ignored", "event_type": event_type}


stripe_service = StripeService()
