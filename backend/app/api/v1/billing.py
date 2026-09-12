"""
InboundCheck - Stripe Billing API Routes (v1)
=============================================
Endpoints for creating Stripe Checkout Sessions, Customer Billing Portals,
and handling Stripe subscription lifecycle webhooks with 3-day trial logic.
"""

from fastapi import APIRouter, HTTPException, Request, Query, status, Depends
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json
import logging

from app.core.security import get_current_user_id
from app.services.billing.stripe_service import stripe_service, PLAN_PRICING, TIER_LIMITS
from app.services.supabase_client import supabase_service
from app.core.tier_guards import parse_utc_datetime, is_trial_expired

logger = logging.getLogger("BillingRoutes")

router = APIRouter(prefix="/billing", tags=["Stripe Billing & Subscriptions"])


class CreateCheckoutRequest(BaseModel):
    email: Optional[str] = "merchant@store.com"
    plan_tier: Optional[str] = Field(default=None, description="starter | growth | enterprise")
    price_id: Optional[str] = Field(default=None, description="Stripe Price ID or plan tier")
    return_url: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CustomerPortalRequest(BaseModel):
    customer_id: Optional[str] = None
    return_url: Optional[str] = None


@router.get("/subscription")
async def get_user_subscription(user_id: str = Depends(get_current_user_id)):
    """
    Get authenticated user's active subscription tier, status, trial metadata, and domain quota usage.
    """
    profile = supabase_service.get_user_profile(user_id) or {}
    tier = (profile.get("subscription_tier") or profile.get("tier") or "starter").lower()
    sub_status = (profile.get("subscription_status") or "trialing").lower()
    trial_ends_at_str = profile.get("trial_ends_at")
    stripe_customer_id = profile.get("stripe_customer_id")
    domain_count = supabase_service.get_user_domain_count(user_id)

    # Check trial expiration
    trial_days_remaining = 0
    if sub_status == "trialing":
        if is_trial_expired(profile):
            sub_status = "expired"
            supabase_service.update_user_profile(user_id, {"subscription_status": "expired"})
        elif trial_ends_at_str:
            dt = parse_utc_datetime(trial_ends_at_str)
            if dt:
                diff = dt - datetime.now(timezone.utc)
                trial_days_remaining = max(0, round(diff.total_seconds() / 86400, 1))

    return {
        "success": True,
        "tier": tier,
        "subscription_tier": tier,
        "subscription_status": sub_status,
        "trial_ends_at": trial_ends_at_str,
        "trial_days_remaining": trial_days_remaining,
        "has_stripe_customer": bool(stripe_customer_id),
        "domain_count": domain_count,
        "domain_limit": TIER_LIMITS.get(tier, 1),
        "current_period_end": profile.get("current_period_end"),
    }


@router.get("/plans")
async def get_subscription_plans(user_id: str = Depends(get_current_user_id)):
    """
    List active SaaS subscription tiers, features, and price points.
    """
    return {
        "plans": list(PLAN_PRICING.values())
    }


@router.post("/create-checkout-session")
@router.post("/checkout-session")
async def create_checkout_session(
    payload: CreateCheckoutRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Create a Stripe Checkout Session for subscription upgrade supporting:
    - Starter: $29/mo (1 Domain cap, manual DNS snippets, basic Telegram alerts)
    - Growth: $79/mo (3 Domains cap, SPF Merge Engine, 1-Click DNS Auto-Fix, 48-72h Risk Forecast)
    - Enterprise: $199/mo (Unlimited domains, Developer API keys, real-time worker priority)
    """
    try:
        resolved_price_or_tier = payload.price_id or payload.plan_tier or "growth"
        session_data = await stripe_service.create_checkout_session(
            user_id=user_id,
            price_id=resolved_price_or_tier,
            email=payload.email or "merchant@store.com",
            return_url=payload.return_url,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
            plan_tier=payload.plan_tier,
        )
        return {"success": True, **session_data}
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.post("/customer-portal")
async def create_customer_portal(
    payload: CustomerPortalRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Create a Stripe Customer Portal Session for managing active payment methods and invoices.
    """
    try:
        portal_data = await stripe_service.create_customer_portal_session(
            user_id=user_id,
            customer_id=payload.customer_id,
            return_url=payload.return_url,
        )
        return {"success": True, **portal_data}
    except Exception as e:
        logger.error(f"Error creating customer portal session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create customer portal session")


@router.get("/invoices")
async def get_billing_invoices(
    limit: int = Query(10, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve paid and processing Stripe invoice receipts for the authenticated user.
    """
    try:
        invoices = await stripe_service.get_customer_invoices(user_id=user_id, limit=limit)
        return {"success": True, "invoices": invoices, "total": len(invoices)}
    except Exception as e:
        logger.error(f"Error fetching invoices for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve billing invoices")


@router.post("/webhook")
async def stripe_webhook_handler(request: Request):
    """
    Process incoming Stripe webhooks (checkout.session.completed, customer.subscription.updated, customer.subscription.deleted).
    Enforces payload size cap (1MB), timestamp tolerance (±300s), and idempotency.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1024 * 1024:
                raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")
        except ValueError:
            pass

    payload_bytes = await request.body()
    if len(payload_bytes) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")

    sig_header = request.headers.get("Stripe-Signature", "")
    if not stripe_service.verify_webhook_signature(payload_bytes, sig_header):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature or expired timestamp")

    try:
        event = json.loads(payload_bytes.decode("utf-8"))
        result = stripe_service.process_webhook_event(event)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=400, detail="Failed to parse Stripe webhook payload")
