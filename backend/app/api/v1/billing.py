"""
InboundCheck - Stripe Billing API Routes (v1)
=============================================
Endpoints for creating Stripe Checkout Sessions, Customer Billing Portals,
and handling Stripe subscription lifecycle webhooks.
"""

from fastapi import APIRouter, HTTPException, Request, Query, status, Depends
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any
import json
import logging

from app.core.security import get_current_user_id
from app.services.billing_service import billing_service, PLAN_PRICING
from app.services.supabase_client import supabase_service

logger = logging.getLogger("BillingRoutes")

router = APIRouter(prefix="/billing", tags=["Stripe Billing & Subscriptions"])

TIER_LIMITS = {
    "starter": 1,
    "growth": 5,
    "enterprise": 999
}


class CreateCheckoutRequest(BaseModel):
    email: Optional[str] = "merchant@brandshop.com"
    plan_tier: str = Field(default="growth", description="starter | growth | enterprise")
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CustomerPortalRequest(BaseModel):
    customer_id: Optional[str] = None
    return_url: Optional[str] = None


@router.get("/subscription")
async def get_user_subscription(user_id: str = Depends(get_current_user_id)):
    """
    Get authenticated user's active subscription tier, status, and domain quota usage.
    """
    profile = supabase_service.get_user_profile(user_id) if supabase_service.is_connected else None
    tier = profile.get("tier", "starter") if profile else "starter"
    status = profile.get("subscription_status", "active") if profile else "active"
    stripe_customer_id = profile.get("stripe_customer_id") if profile else None
    domain_count = supabase_service.get_user_domain_count(user_id)

    return {
        "success": True,
        "tier": tier,
        "subscription_status": status,
        "has_stripe_customer": bool(stripe_customer_id),
        "domain_count": domain_count,
        "domain_limit": TIER_LIMITS.get(tier, 1),
        "current_period_end": profile.get("current_period_end") if profile else None
    }


@router.get("/plans")
async def get_subscription_plans(user_id: str = Depends(get_current_user_id)):
    """
    List active SaaS subscription tiers, features, and price points.
    """
    return {
        "plans": [
            {
                "id": "starter",
                "name": "Starter",
                "price": 29,
                "interval": "month",
                "domain_limit": 1,
                "features": [
                    "1 Monitored Domain",
                    "Real-time DNS Health Scorer",
                    "1-Click DNS Record Fixes",
                    "Weekly Health Digest",
                ]
            },
            {
                "id": "growth",
                "name": "Growth",
                "price": 79,
                "interval": "month",
                "domain_limit": 5,
                "is_popular": True,
                "features": [
                    "5 Monitored Domains",
                    "Shopify Store Integration & Webhooks",
                    "Hourly DNS Monitoring & Alerts",
                    "DMARC XML Aggregate Telemetry",
                    "Slack & Email Alerts",
                ]
            },
            {
                "id": "enterprise",
                "name": "Enterprise",
                "price": 199,
                "interval": "month",
                "domain_limit": 999,
                "features": [
                    "Unlimited Monitored Domains",
                    "Dedicated Deliverability Architect",
                    "Custom API Access & Webhooks",
                    "99.9% SLA & Priority Support",
                ]
            }
        ]
    }


@router.post("/checkout-session")
async def create_checkout_session(
    payload: CreateCheckoutRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Create a Stripe Checkout Session for subscription upgrade.
    """
    try:
        session_data = await billing_service.create_checkout_session(
            user_id=user_id,
            email=payload.email or "merchant@brandshop.com",
            plan_tier=payload.plan_tier,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url
        )
        return {"success": True, **session_data}
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.post("/customer-portal")
async def create_customer_portal(
    payload: CustomerPortalRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Create a Stripe Customer Portal Session for managing active payment methods and invoices.
    """
    try:
        portal_data = await billing_service.create_customer_portal_session(
            user_id=user_id,
            customer_id=payload.customer_id,
            return_url=payload.return_url
        )
        return {"success": True, **portal_data}
    except Exception as e:
        logger.error(f"Error creating customer portal session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create customer portal session")


@router.get("/invoices")
async def get_billing_invoices(
    limit: int = Query(10, ge=1, le=50),
    user_id: str = Depends(get_current_user_id)
):
    """
    Retrieve paid and processing Stripe invoice receipts for the authenticated user.
    """
    try:
        invoices = await billing_service.get_customer_invoices(user_id=user_id, limit=limit)
        return {"success": True, "invoices": invoices, "total": len(invoices)}
    except Exception as e:
        logger.error(f"Error fetching invoices for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve billing invoices")


@router.post("/webhook")
async def stripe_webhook_handler(request: Request):
    """
    Process incoming Stripe webhooks (checkout.session.completed, customer.subscription.deleted).
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
    if not billing_service.verify_webhook_signature(payload_bytes, sig_header):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature or expired timestamp")

    try:
        event = json.loads(payload_bytes.decode("utf-8"))
        result = billing_service.process_webhook_event(event)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=400, detail="Failed to parse Stripe webhook payload")
