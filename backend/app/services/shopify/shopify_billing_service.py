"""
InboundCheck - Shopify GraphQL Recurring Billing Service
=========================================================
Implements the Shopify App Store Billing API via GraphQL appSubscriptionCreate mutation.
Enforces 30-day recurring interval, standardized pricing tiers, confirmationUrl extraction,
and charge activation verification for Shopify App Store compliance.
"""

import httpx
import logging
from typing import Dict, Any, Optional
from decimal import Decimal, InvalidOperation
from app.core.config import settings

logger = logging.getLogger("ShopifyBillingService")

# Standardized subscription pricing matching InboundCheck public tiers
SHOPIFY_PLAN_PRICING = {
    "starter": 9.0,
    "growth": 29.0,
    "agency": 79.0,
}

SHOPIFY_BILLING_CURRENCY = "USD"
SHOPIFY_BILLING_INTERVAL = "EVERY_30_DAYS"

# Route registered in app/api/v1/shopify.py (router prefix "/shopify") under API_V1_STR.
SHOPIFY_BILLING_CALLBACK_PATH = "/shopify/billing/callback"

# Shopify AppSubscriptionStatus -> profiles.subscription_status. The DB CHECK only
# allows ('trialing','active','past_due','canceled','expired'); never emit anything else.
# None means "no entitlement change" (PENDING / unknown).
_SHOPIFY_TO_APP_STATUS = {
    "ACTIVE": "active",
    "ACCEPTED": "active",      # legacy pre-activation state, treated as active by Shopify
    "PENDING": None,           # merchant has not approved yet: never upgrade or downgrade
    "DECLINED": "canceled",    # merchant declined the charge
    "CANCELLED": "canceled",
    "CANCELED": "canceled",
    "EXPIRED": "expired",      # not accepted within the approval window
    "FROZEN": "past_due",      # store billing frozen: Shopify says shut off access only now
    "PAUSED": "past_due",      # legacy/on-hold synonym, never persisted as 'paused'
}


def map_shopify_subscription_status(shopify_status: Optional[str]) -> Optional[str]:
    """Single source of truth for Shopify -> app subscription status mapping."""
    if not shopify_status or not isinstance(shopify_status, str):
        return None
    return _SHOPIFY_TO_APP_STATUS.get(shopify_status.strip().upper())


def build_billing_return_url(
    shop_domain: str,
    user_id: Optional[str] = None,
    plan_tier: Optional[str] = None,
) -> str:
    """Build the appSubscriptionCreate returnUrl pointing at the BACKEND callback route.

    The callback is served by FastAPI, not the Next.js frontend. Fails closed in
    production when BACKEND_PUBLIC_URL is missing or not HTTPS.
    """
    from urllib.parse import urlencode

    base = (settings.BACKEND_PUBLIC_URL or "").strip().rstrip("/")
    if not base:
        if settings.is_production:
            raise RuntimeError(
                "BACKEND_PUBLIC_URL must be configured in production to build the Shopify billing return URL"
            )
        base = "http://localhost:8000"
    if settings.is_production and not base.lower().startswith("https://"):
        raise RuntimeError("BACKEND_PUBLIC_URL must use https in production")

    params = {"shop": shop_domain}
    if user_id:
        params["user_id"] = user_id
    if plan_tier:
        params["plan_tier"] = plan_tier
    return f"{base}{settings.API_V1_STR}{SHOPIFY_BILLING_CALLBACK_PATH}?{urlencode(params)}"


class ShopifyBillingService:
    """
    Handles Shopify GraphQL AppSubscription billing operations.
    """

    def __init__(self, api_version: str = "2024-04"):
        self.api_version = api_version

    @staticmethod
    def resolve_subscription_tier(subscription: Dict[str, Any]) -> str:
        """Bind entitlements to Shopify recurring pricing, never labels or callback input.

        Only the single recurring line item emitted by our checkout is supported.
        Unknown, incomplete, usage-based or ambiguous pricing fails closed.
        """
        line_items = subscription.get("lineItems")
        if not isinstance(line_items, list) or len(line_items) != 1:
            raise ValueError("Unsupported Shopify subscription line items")
        item = line_items[0]
        plan = item.get("plan") if isinstance(item, dict) else None
        details = plan.get("pricingDetails") if isinstance(plan, dict) else None
        if not isinstance(details, dict) or details.get("__typename") != "AppRecurringPricing":
            raise ValueError("Missing Shopify recurring pricing")
        price = details.get("price")
        if (
            details.get("interval") != SHOPIFY_BILLING_INTERVAL
            or not isinstance(price, dict)
            or price.get("currencyCode") != SHOPIFY_BILLING_CURRENCY
        ):
            raise ValueError("Unsupported Shopify subscription currency or interval")
        try:
            amount = Decimal(str(price.get("amount")))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Invalid Shopify recurring amount") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid Shopify recurring amount")
        matches = [
            tier for tier, configured_amount in SHOPIFY_PLAN_PRICING.items()
            if amount == Decimal(str(configured_amount))
        ]
        if len(matches) != 1:
            raise ValueError("Unrecognized Shopify recurring price")
        return matches[0]

    async def create_shopify_recurring_charge(
        self,
        shop_domain: str,
        access_token: str,
        plan_name: str,
        price_usd: Optional[float] = None,
        return_url: Optional[str] = None,
        test: Optional[bool] = None,
    ) -> str:
        """
        Execute appSubscriptionCreate GraphQL mutation against Shopify Admin API.
        Extracts and returns the confirmationUrl for the merchant to approve the charge.
        """
        clean_tier = plan_name.lower().strip()
        final_price = price_usd if price_usd is not None else SHOPIFY_PLAN_PRICING.get(clean_tier, 29.0)
        
        is_test_mode = test if test is not None else (
            settings.ENVIRONMENT.lower() in ["development", "test", "testing"]
        )

        resolved_return_url = return_url or build_billing_return_url(shop_domain, plan_tier=clean_tier)

        mutation = """
        mutation AppSubscriptionCreate(
          $name: String!
          $returnUrl: URL!
          $lineItems: [AppSubscriptionLineItemInput!]!
          $test: Boolean
        ) {
          appSubscriptionCreate(
            name: $name
            returnUrl: $returnUrl
            lineItems: $lineItems
            test: $test
          ) {
            appSubscription {
              id
              status
              name
            }
            confirmationUrl
            userErrors {
              field
              message
            }
          }
        }
        """

        variables = {
            "name": f"InboundCheck {clean_tier.title()} Plan",
            "returnUrl": resolved_return_url,
            "test": is_test_mode,
            "lineItems": [
                {
                    "plan": {
                        "appRecurringPricingDetails": {
                            "price": {
                                "amount": float(final_price),
                                "currencyCode": SHOPIFY_BILLING_CURRENCY
                            },
                            "interval": SHOPIFY_BILLING_INTERVAL
                        }
                    }
                }
            ]
        }

        endpoint = f"https://{shop_domain}/admin/api/{self.api_version}/graphql.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    endpoint,
                    json={"query": mutation, "variables": variables},
                    headers=headers
                )

            if res.status_code != 200:
                logger.error(f"Shopify GraphQL request failed with HTTP {res.status_code}: {res.text}")
                raise RuntimeError(f"Shopify Billing API HTTP {res.status_code}: {res.text}")

            result_data = res.json()
            if "errors" in result_data:
                logger.error(f"Shopify GraphQL top-level errors: {result_data['errors']}")
                raise RuntimeError(f"Shopify GraphQL syntax/execution error: {result_data['errors']}")

            payload = result_data.get("data", {}).get("appSubscriptionCreate", {})
            user_errors = payload.get("userErrors", [])
            if user_errors:
                logger.error(f"Shopify appSubscriptionCreate userErrors: {user_errors}")
                err_msg = "; ".join([f"{e.get('field')}: {e.get('message')}" for e in user_errors])
                raise RuntimeError(f"Shopify Billing User Error: {err_msg}")

            confirmation_url = payload.get("confirmationUrl")
            if not confirmation_url:
                logger.error(f"Shopify response missing confirmationUrl: {result_data}")
                raise RuntimeError("No confirmationUrl returned by Shopify Billing API.")

            logger.info(f"Successfully generated Shopify charge confirmationUrl for shop {shop_domain}")
            return confirmation_url

        except httpx.RequestError as req_err:
            logger.error(f"Network error connecting to Shopify GraphQL Billing: {req_err}")
            raise RuntimeError(f"Network error contacting Shopify Billing API: {req_err}")

    @staticmethod
    def canonical_subscription_id(charge_id: str) -> str:
        import re
        value = str(charge_id)
        if re.fullmatch(r"[0-9]+", value):
            return "gid://shopify/AppSubscription/" + value
        if not re.fullmatch(r"gid://shopify/AppSubscription/[0-9]+", value):
            raise ValueError("Invalid Shopify subscription identity")
        return value

    async def get_app_subscription(
        self,
        shop_domain: str,
        access_token: str,
        charge_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Query AppSubscription node details via GraphQL node(id: $id).
        Returns subscription identity, lifecycle and recurring pricing, or None when Shopify
        answers successfully but the node does not exist.
        REV-1: transport errors, non-200 responses and GraphQL errors RAISE (never None), so
        webhook callers can return 503 and let Shopify retry instead of treating an outage
        as "subscription not found".
        Does not enforce ACTIVE status, allowing full lifecycle status inspection (CANCELLED, EXPIRED, etc.).
        """
        gid = self.canonical_subscription_id(charge_id)
        query = """
        query GetAppSubscription($id: ID!) {
          node(id: $id) {
            ... on AppSubscription {
              id
              status
              name
              currentPeriodEnd
              lineItems {
                plan {
                  pricingDetails {
                    __typename
                    ... on AppRecurringPricing {
                      interval
                      price { amount currencyCode }
                    }
                  }
                }
              }
            }
          }
        }
        """

        endpoint = f"https://{shop_domain}/admin/api/{self.api_version}/graphql.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    endpoint,
                    json={"query": query, "variables": {"id": gid}},
                    headers=headers
                )

            if res.status_code != 200:
                logger.error(f"Shopify subscription query failed: HTTP {res.status_code}")
                raise RuntimeError(f"Shopify subscription query failed: HTTP {res.status_code}")

            data = res.json()
            if "errors" in data and data["errors"]:
                logger.error(f"Shopify subscription query GraphQL error: {data['errors']}")
                raise RuntimeError("Shopify subscription query returned GraphQL errors")

            node = data.get("data", {}).get("node")
            if not node or not isinstance(node, dict):
                return None
            if node.get("id") != gid:
                raise RuntimeError("Shopify returned a different subscription identity")
            return node
        except httpx.RequestError as req_err:
            logger.error(f"Network error querying subscription {gid}: {req_err}")
            raise RuntimeError("Network error querying Shopify subscription") from req_err

    async def verify_and_activate_subscription(
        self,
        shop_domain: str,
        access_token: str,
        charge_id: str
    ) -> Dict[str, Any]:
        """
        Query AppSubscription node status via GraphQL node(id: $id) and enforce active status.
        """
        gid = self.canonical_subscription_id(charge_id)
        node = await self.get_app_subscription(shop_domain, access_token, gid)
        if not node or node.get("id") != gid:
            raise RuntimeError("Shopify subscription identity could not be verified")

        # Validate that status is in approved active states
        status_val = (node.get("status") or "").upper()
        if status_val not in ["ACTIVE", "ACCEPTED"]:
            raise RuntimeError(f"Shopify subscription {gid} is not active (status: {status_val})")

        return node


shopify_billing_service = ShopifyBillingService()
