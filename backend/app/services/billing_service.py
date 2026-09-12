"""
InboundCheck - Stripe Billing & Subscription Service
====================================================
Maintains backward-compatible exports from app.services.billing.stripe_service.
"""

from app.services.billing.stripe_service import (
    StripeService as BillingService,
    stripe_service as billing_service,
    PLAN_PRICING,
    TIER_LIMITS,
)

__all__ = ["BillingService", "billing_service", "PLAN_PRICING", "TIER_LIMITS"]
