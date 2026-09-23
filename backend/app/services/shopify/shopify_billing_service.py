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
from app.core.config import settings

logger = logging.getLogger("ShopifyBillingService")

# Standardized subscription pricing matching InboundCheck public tiers
SHOPIFY_PLAN_PRICING = {
    "starter": 9.0,
    "growth": 29.0,
    "agency": 79.0,
    "enterprise": 199.0,
}


class ShopifyBillingService:
    """
    Handles Shopify GraphQL AppSubscription billing operations.
    """

    def __init__(self, api_version: str = "2024-04"):
        self.api_version = api_version

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

        resolved_return_url = return_url or (
            f"{settings.FRONTEND_URL}/api/v1/shopify/billing/callback?shop={shop_domain}&plan_tier={clean_tier}"
        )

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
                                "currencyCode": "USD"
                            },
                            "interval": "EVERY_30_DAYS"
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

    async def verify_and_activate_subscription(
        self,
        shop_domain: str,
        access_token: str,
        charge_id: str
    ) -> Dict[str, Any]:
        """
        Query AppSubscription node status via GraphQL node(id: $id).
        """
        gid = charge_id if str(charge_id).startswith("gid://") else f"gid://shopify/AppSubscription/{charge_id}"
        query = """
        query GetAppSubscription($id: ID!) {
          node(id: $id) {
            ... on AppSubscription {
              id
              status
              name
              currentPeriodEnd
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
                raise RuntimeError(f"Failed to query Shopify subscription: HTTP {res.status_code}")

            data = res.json()
            if "errors" in data and data["errors"]:
                logger.error(f"Shopify subscription query GraphQL error: {data['errors']}")
                raise RuntimeError("GraphQL error returned from Shopify subscription query")

            node = data.get("data", {}).get("node")
            if not node:
                raise RuntimeError(f"Subscription {gid} not found in Shopify")

            # Validate that status is in approved active states
            status_val = (node.get("status") or "").upper()
            if status_val not in ["ACTIVE", "ACCEPTED"]:
                raise RuntimeError(f"Shopify subscription {gid} is not active (status: {status_val})")

            return node
        except httpx.RequestError as req_err:
            logger.error(f"Network error querying subscription {gid}: {req_err}")
            raise RuntimeError(f"Network error querying subscription: {req_err}")


shopify_billing_service = ShopifyBillingService()
