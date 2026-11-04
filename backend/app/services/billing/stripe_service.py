"""
InboundCheck - Stripe Billing & Subscription Service
====================================================
Production Stripe checkout session generation, customer billing portal,
customer creation/retrieval, and webhook lifecycle reconciliation.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import os
import hmac
import hashlib
import time
import logging
import httpx

try:
    import stripe
except ImportError:
    stripe = None

from app.core.config import settings
from app.core.env_guard import check_is_placeholder
from app.services.supabase_client import supabase_service

logger = logging.getLogger("StripeService")


def is_test_bypass_allowed() -> bool:
    """
    Return True ONLY when:
    1. settings.ENVIRONMENT is strictly 'development' or 'test'
    2. STAGING_MODE is False (checked on both settings and os.environ)
    """
    env = (getattr(settings, "ENVIRONMENT", "") or "").strip().lower()
    if env not in ("development", "test"):
        return False

    staging_attr = getattr(settings, "STAGING_MODE", False)
    staging_env = (os.getenv("STAGING_MODE") or "").strip().lower()
    if (
        staging_attr is True
        or str(staging_attr).strip().lower() in ("true", "1", "yes")
        or staging_env in ("true", "1", "yes")
    ):
        return False

    return True

TIER_LIMITS = {
    "starter": 1,
    "growth": 3,
    "agency": 20,
}

PLAN_PRICING: Dict[str, Dict[str, Any]] = {
    "starter": {
        "id": "starter",
        "name": "Starter Plan",
        "price": 9,
        "amount": 900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 1,
        "features": [
            "1 Monitored Domain",
            "24/7 Continuous DNS & 10-RBL Blacklist Radar",
            "Instant Telegram Failure Alerts",
            "3-Day Free Trial",
        ],
    },
    "growth": {
        "id": "growth",
        "name": "Growth Plan",
        "price": 29,
        "amount": 2900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 3,
        "is_popular": True,
        "features": [
            "Up to 3 Monitored Domains",
            "Shopify Store OAuth Sync & Alignment",
            "1-Click DNS Auto-Remediation (Cloudflare & GoDaddy APIs)",
            "Revenue & Dispute Risk Analytics (Protected GMV / At-Risk GMV)",
            "3-Day Free Trial",
        ],
    },
    "agency": {
        "id": "agency",
        "name": "Agency Plan",
        "price": 79,
        "amount": 7900,
        "currency": "usd",
        "interval": "month",
        "domain_limit": 20,
        "features": [
            "Up to 20 Monitored Domains",
            "Multi-Store Management",
            "Priority Audit Queue & White-Label Reporting Exports",
            "3-Day Free Trial",
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

    @property
    def prices(self) -> Dict[str, str]:
        """
        Server-authoritative mapping of tier -> configured Stripe Price ID.
        """
        agency_price = getattr(settings, "STRIPE_PRICE_AGENCY", "price_agency_monthly")
        return {
            "starter": settings.STRIPE_PRICE_STARTER,
            "growth": settings.STRIPE_PRICE_GROWTH,
            "agency": agency_price,
            "enterprise": agency_price,
        }

    def resolve_tier(self, price_or_tier: str) -> str:
        """
        Normalize tier identifier from price_id or tier name string.
        3-Tier Model: starter | growth | agency.
        Legacy transition: existing Enterprise price or tier string resolves to agency.
        """
        raw = (price_or_tier or "growth").strip().lower()
        if raw == (getattr(settings, "STRIPE_PRICE_AGENCY", "price_agency_monthly") or "").lower() or "agency" in raw:
            return "agency"
        if raw == (settings.STRIPE_PRICE_STARTER or "").lower() or "starter" in raw:
            return "starter"
        if raw == (settings.STRIPE_PRICE_GROWTH or "").lower() or "growth" in raw:
            return "growth"
        # Legacy Enterprise transition: Map legacy Stripe price or 'enterprise' string safely to 'agency'
        ent_price = (getattr(settings, "STRIPE_PRICE_ENTERPRISE", None) or "").lower()
        if (ent_price and raw == ent_price) or "enterprise" in raw:
            logger.info(f"Legacy enterprise Stripe price/tier '{raw}' resolved safely to 'agency'.")
            return "agency"
        return "growth"

    def _offline_customer_mode(self) -> bool:
        return is_test_bypass_allowed() and (
            not self.secret_key or self.secret_key.startswith("mock_")
        )

    async def _verify_customer_ownership(self, user_id: str, customer_id: str) -> str:
        """Stored mappings are not authority: require Stripe's immutable tenant metadata."""
        if not self.secret_key or customer_id.startswith("cus_mock_"):
            raise RuntimeError("A verified Stripe customer is required")
        from urllib.parse import quote
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.stripe.com/v1/customers/{quote(customer_id, safe='')}",
                headers={"Authorization": f"Bearer {self.secret_key}"},
            )
        if response.status_code != 200:
            raise RuntimeError("Unable to verify Stripe customer ownership")
        customer = response.json()
        if (
            customer.get("deleted")
            or customer.get("id") != customer_id
            or (customer.get("metadata") or {}).get("user_id") != user_id
        ):
            raise ValueError("Stripe customer does not belong to authenticated user")
        return customer_id

    def _persist_customer(self, user_id: str, customer_id: str) -> str:
        # Never hide persistence/uniqueness failures behind a simulated customer.
        profile = supabase_service.update_user_profile(
            user_id, {"stripe_customer_id": customer_id}
        )
        if not profile or profile.get("stripe_customer_id") != customer_id:
            raise RuntimeError("Stripe customer ownership could not be persisted")
        return customer_id

    async def get_or_create_customer(self, user_id: str, email: Optional[str] = None) -> Optional[str]:
        """Create by tenant idempotency key; never adopt a customer using email alone."""
        profile = supabase_service.get_user_profile(user_id) or {}
        existing = profile.get("stripe_customer_id")
        if self._offline_customer_mode():
            if existing and not existing.startswith("cus_mock_"):
                raise RuntimeError("Cannot use a real Stripe customer in offline mode")
            return existing or self._persist_customer(user_id, f"cus_mock_{user_id}")
        if existing:
            return await self._verify_customer_ownership(user_id, existing)
        if not self.secret_key:
            raise RuntimeError("Stripe customer creation is not configured")

        # Email is contact information only, not an ownership credential.
        user_email = email or profile.get("email")
        data = {"metadata[user_id]": user_id, "description": f"InboundCheck Customer {user_id}"}
        if user_email:
            data["email"] = user_email
        tenant_key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.stripe.com/v1/customers",
                headers={
                    "Authorization": f"Bearer {self.secret_key}",
                    "Idempotency-Key": f"inboundcheck-customer-v1-{tenant_key}",
                },
                data=data,
            )
        if response.status_code != 200:
            raise RuntimeError("Stripe customer creation failed")
        customer = response.json()
        customer_id = customer.get("id")
        if not customer_id or (customer.get("metadata") or {}).get("user_id") != user_id:
            raise RuntimeError("Stripe customer creation returned invalid ownership")
        return self._persist_customer(user_id, customer_id)

    async def create_checkout_session(
        self,
        user_id: str,
        plan_tier: Optional[str] = None,
        return_url: Optional[str] = None,
        email: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        price_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session for subscription upgrade supporting:
        - Starter: $9/mo (1 Domain cap)
        - Growth: $29/mo (3 Domains cap)
        - Agency: $79/mo (20 Domains cap)

        The client NEVER determines the Stripe Price ID. The server derives pricing
        strictly from server-authoritative configuration. Any mismatching client price_id
        is rejected with a ValueError.
        """
        # Resolve tier strictly from server logic (normalizing enterprise -> agency)
        tier = self.resolve_tier(plan_tier or (price_id if price_id and not price_id.startswith("price_") else None) or "growth")
        plan_meta = PLAN_PRICING.get(tier, PLAN_PRICING["growth"])

        # Validate that client cannot supply a mismatching or arbitrary price_id
        configured_price_id = self.prices.get(tier)
        if price_id is not None and str(price_id).strip() != "":
            raw_p = str(price_id).strip()
            allowed_identifiers = {tier, (plan_tier or "").strip().lower()}
            if configured_price_id:
                allowed_identifiers.add(configured_price_id)
            if tier == "agency":
                ent_p = getattr(settings, "STRIPE_PRICE_ENTERPRISE", None)
                if ent_p:
                    allowed_identifiers.add(ent_p)
                allowed_identifiers.add("enterprise")

            if raw_p not in allowed_identifiers:
                logger.warning(
                    f"Price mismatch rejected in stripe_service: user={user_id}, plan_tier={tier}, "
                    f"supplied_price_id={raw_p}, expected={configured_price_id}"
                )
                raise ValueError(
                    f"Price mismatch: client-provided price_id '{raw_p}' does not match server-resolved plan tier '{tier}'"
                )

        s_url = success_url or return_url or f"{settings.FRONTEND_URL}/dashboard/billing?checkout=success&plan={tier}"
        c_url = cancel_url or return_url or f"{settings.FRONTEND_URL}/dashboard/billing?checkout=cancelled"

        customer_id = await self.get_or_create_customer(user_id=user_id, email=email)

        if self.secret_key:
            try:
                # Derive Stripe Price ID strictly from server configuration
                server_price_id = configured_price_id
                if server_price_id and (not server_price_id.startswith("price_") or server_price_id.endswith("_monthly")):
                    server_price_id = None

                req_data: Dict[str, Any] = {
                    "mode": "subscription",
                    "payment_method_types[0]": "card",
                    "client_reference_id": user_id,
                    "metadata[user_id]": user_id,
                    "metadata[plan_tier]": tier,
                    "metadata[subscription_tier]": tier,
                    "success_url": s_url,
                    "cancel_url": c_url,
                    "line_items[0][quantity]": 1,
                }
                if server_price_id:
                    req_data["line_items[0][price]"] = server_price_id
                else:
                    req_data["line_items[0][price_data][currency]"] = plan_meta["currency"]
                    req_data["line_items[0][price_data][product_data][name]"] = f"InboundCheck {plan_meta['name']}"
                    req_data["line_items[0][price_data][unit_amount]"] = plan_meta["amount"]
                    req_data["line_items[0][price_data][recurring][interval]"] = plan_meta["interval"]
                if customer_id and not customer_id.startswith("cus_mock_"):
                    req_data["customer"] = customer_id
                elif email:
                    req_data["customer_email"] = email

                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        "https://api.stripe.com/v1/checkout/sessions",
                        headers={"Authorization": f"Bearer {self.secret_key}"},
                        data=req_data,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        raw_url = data.get("url")
                        logger.info(f"Stripe checkout session successfully created: {data.get('id')} -> {raw_url}")
                        return {
                            "session_id": data.get("id"),
                            "checkout_url": raw_url,
                            "url": raw_url,
                            "plan_tier": tier,
                            "subscription_tier": tier,
                            "amount": plan_meta["amount"] / 100,
                            "customer_id": customer_id,
                        }
                    else:
                        error_body = res.text
                        logger.error(f"Stripe checkout session error {res.status_code}: {error_body}")
                        # In production or when keys are configured, do NOT silently fall back to mock checkout!
                        if settings.ENVIRONMENT.lower() in ("production", "prod") or (self.secret_key and not self.secret_key.startswith("mock_")):
                            raise RuntimeError(f"Stripe Checkout API rejected request ({res.status_code}): {error_body}")
            except Exception as e:
                logger.error(f"Stripe API error: {e}")
                if settings.ENVIRONMENT.lower() in ("production", "prod") or (self.secret_key and not self.secret_key.startswith("mock_")):
                    raise

        # Local simulation / offline fallback (ONLY permitted in test/development when secret key is missing or mock)
        is_prod = settings.ENVIRONMENT.lower() in ("production", "prod")
        if is_prod:
            raise RuntimeError("STRIPE_SECRET_KEY is missing or invalid in production environment. Offline fallback disabled.")

        mock_id = f"cs_test_{int(time.time())}_{user_id[:8]}"
        simulated_s_url = s_url.replace("{CHECKOUT_SESSION_ID}", mock_id).replace("%7BCHECKOUT_SESSION_ID%7D", mock_id)
        logger.warning(f"Using OFFLINE_FALLBACK simulation mode for checkout session: {mock_id}")
        return {
            "session_id": mock_id,
            "checkout_url": simulated_s_url,
            "url": simulated_s_url,
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
        Enforces tenant boundary: client-supplied customer_id must match authenticated profile.
        """
        r_url = return_url or f"{settings.FRONTEND_URL}/dashboard/billing"

        profile = supabase_service.get_user_profile(user_id) or {}
        owner_customer = profile.get("stripe_customer_id")

        supplied_customer = customer_id.strip() if customer_id and customer_id.strip() else None
        if supplied_customer and (not owner_customer or supplied_customer != owner_customer):
            raise ValueError(f"Unauthorized customer ID for authenticated user {user_id}")

        resolved_customer = owner_customer
        if resolved_customer and not self._offline_customer_mode():
            await self._verify_customer_ownership(user_id, resolved_customer)

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
                logger.error("Stripe Portal request failed")
                raise RuntimeError("Stripe portal creation failed") from e
            raise RuntimeError("Stripe portal creation failed")

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
        """Fetch invoices for the user with tenant boundary validation."""
        profile = supabase_service.get_user_profile(user_id) or {}
        owner_customer = profile.get("stripe_customer_id")

        supplied_customer = customer_id.strip() if customer_id and customer_id.strip() else None
        if supplied_customer and (not owner_customer or supplied_customer != owner_customer):
            raise ValueError(f"Unauthorized customer ID for authenticated user {user_id}")

        resolved_customer = owner_customer
        if resolved_customer and not self._offline_customer_mode():
            await self._verify_customer_ownership(user_id, resolved_customer)

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
        """
        Verify Stripe webhook signature header using timestamped HMAC-SHA256.
        Enforces fail-closed security for production and staging environments:
        - If STRIPE_WEBHOOK_SECRET is missing, empty, or placeholder, rejects verification.
        - If Stripe-Signature header is missing or empty, rejects verification.
        - Replay attacks outside ±tolerance_seconds (default 300s) are rejected.
        - Mock/test signatures are strictly rejected in production and staging.
        - Test bypasses are ONLY permitted when ENVIRONMENT is development/test AND STAGING_MODE is False.
        """
        test_bypass = is_test_bypass_allowed()

        # Step 1: In production or staging, secret MUST be configured and not a placeholder
        webhook_secret = (self.webhook_secret or "").strip()
        if not test_bypass:
            if not webhook_secret or check_is_placeholder(webhook_secret):
                logger.error("Stripe webhook rejected: STRIPE_WEBHOOK_SECRET is missing or empty in non-development environment.")
                return False

        # Step 2: Signature header MUST be provided
        if not sig_header or not str(sig_header).strip():
            if test_bypass and not webhook_secret:
                # Local development/testing without configured webhook secret
                return True
            logger.warning("Stripe webhook rejected: Stripe-Signature header is missing.")
            return False

        try:
            # Step 3: Parse Stripe-Signature header (format: t=timestamp,v1=signature[,v0=signature])
            sig_dict: Dict[str, str] = {}
            for item in sig_header.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    sig_dict[k.strip()] = v.strip()

            t = sig_dict.get("t")
            v1 = sig_dict.get("v1")

            if not t or not v1:
                logger.warning("Stripe webhook rejected: Malformed signature header (missing t or v1).")
                return False

            # Step 4: Verify timestamp tolerance (anti-replay guard)
            timestamp = int(t)
            current_time = int(time.time())
            if abs(current_time - timestamp) > tolerance_seconds:
                logger.warning(
                    f"Stripe webhook timestamp {timestamp} outside ±{tolerance_seconds}s tolerance (delta: {abs(current_time - timestamp)}s)"
                )
                return False

            # Step 5: Test bypass validation
            if test_bypass:
                # If signature is a mock/dummy signature in development/test
                if v1.startswith("mock_") or v1.startswith("dummy_"):
                    return True
                # If no webhook secret is configured in development/test
                if not webhook_secret or check_is_placeholder(webhook_secret):
                    return True

            # In production or staging, or when real verification is required in test:
            # Reject any mock or dummy signature tokens immediately
            if v1.startswith("mock_") or v1.startswith("dummy_"):
                logger.warning("Stripe webhook rejected: Mock signature disallowed in non-test mode.")
                return False

            if not webhook_secret:
                logger.error("Stripe webhook rejected: Cannot verify signature without STRIPE_WEBHOOK_SECRET.")
                return False

            # Step 6: Official Stripe SDK verification if available
            if stripe is not None:
                try:
                    payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
                    stripe.WebhookSignature.verify_header(
                        payload_str,
                        sig_header,
                        webhook_secret,
                        tolerance=tolerance_seconds,
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Stripe SDK signature verification failed: {e}")
                    return False

            # Step 7: Cryptographic HMAC-SHA256 verification (standard Stripe protocol)
            signed_payload = f"{t}.".encode("utf-8") + (payload if isinstance(payload, bytes) else str(payload).encode("utf-8"))
            computed = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(v1, computed)

        except Exception as e:
            logger.error(f"Stripe signature verification failed with error: {e}")
            return False

    def process_webhook_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Claim, update entitlements and complete in one database transaction.

        Requires the reviewed atomic-webhook migration before this code is deployed.
        Never acknowledge a persistence failure or fall back to process-local state.
        """
        from app.services.billing.stripe_event_repository import process_atomic_stripe_event
        return process_atomic_stripe_event(event, supabase_service, self.prices)


stripe_service = StripeService()
