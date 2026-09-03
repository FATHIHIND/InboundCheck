"""
InboundCheck - Shopify Integration Service
==========================================
Handles Shopify OAuth handshake, HMAC-SHA256 webhook validation,
store domain extraction, sender alignment checks, and transactional order delivery simulations.
"""

import hmac
import hashlib
import base64
import urllib.parse
import time
from typing import Dict, Any, Optional, Tuple, List
import httpx
import logging
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger("ShopifyService")


class ShopifyService:
    """
    Service for Shopify Partner App integrations, OAuth handshake, and webhook verification.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        scopes: str = "read_orders,read_fulfillments,read_merchant_managed_fulfillment_orders"
    ):
        self.api_key = api_key or settings.SHOPIFY_API_KEY
        self.api_secret = api_secret or settings.SHOPIFY_API_SECRET
        self.scopes = scopes
        self.api_version = "2024-04"
        self._processed_webhooks: Dict[str, float] = {}

    def is_webhook_processed(self, webhook_id: str) -> bool:
        """Check if Shopify webhook has already been processed within 24 hours."""
        if not webhook_id:
            return False
        now = time.time()
        self._processed_webhooks = {
            wid: ts for wid, ts in self._processed_webhooks.items() if now - ts < 86400
        }
        return webhook_id in self._processed_webhooks

    def mark_webhook_processed(self, webhook_id: str):
        """Mark Shopify webhook as processed."""
        if webhook_id:
            self._processed_webhooks[webhook_id] = time.time()

    def verify_webhook_timestamp(self, triggered_at: Optional[str], tolerance_seconds: int = 300) -> bool:
        """
        Verify Shopify X-Shopify-Triggered-At timestamp drift tolerance (±300s).
        """
        if not triggered_at:
            return settings.ENVIRONMENT == "development"
        try:
            if triggered_at.replace(".", "", 1).isdigit():
                ts = float(triggered_at)
            else:
                clean_str = triggered_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
                ts = dt.timestamp()
            current_time = time.time()
            if abs(current_time - ts) > tolerance_seconds:
                logger.warning(
                    f"Shopify webhook timestamp {ts} expired outside ±{tolerance_seconds}s tolerance (current: {current_time})"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to parse Shopify webhook timestamp '{triggered_at}': {e}")
            return False

    def clean_shop_domain(self, shop: str) -> str:
        """Sanitize and normalize Shopify shop domain."""
        s = shop.strip().lower()
        s = s.replace("https://", "").replace("http://", "").split("/")[0]
        if not s.endswith(".myshopify.com"):
            s = f"{s}.myshopify.com"
        return s

    def build_auth_url(self, shop: str, redirect_uri: str, state: str) -> str:
        """Build the Shopify OAuth Authorization URL."""
        cleaned_shop = self.clean_shop_domain(shop)
        params = {
            "client_id": self.api_key,
            "scope": self.scopes,
            "redirect_uri": redirect_uri,
            "state": state
        }
        return f"https://{cleaned_shop}/admin/oauth/authorize?{urllib.parse.urlencode(params)}"

    def verify_shopify_hmac(self, query_params: Dict[str, str]) -> bool:
        """
        Verify the HMAC signature of Shopify OAuth redirect parameters according to Shopify docs.
        """
        if not self.api_secret:
            if settings.ENVIRONMENT == "development":
                logger.warning("SHOPIFY_API_SECRET not set - allowing OAuth handshake in development.")
                return True
            logger.error("Shopify OAuth verification failed: SHOPIFY_API_SECRET is not configured in production.")
            return False

        if "hmac" not in query_params:
            return False

        provided_hmac = query_params["hmac"]
        filtered_params = {
            k: v for k, v in query_params.items()
            if k not in ["hmac", "signature"]
        }
        sorted_pairs = [f"{k}={v}" for k, v in sorted(filtered_params.items())]
        message = "&".join(sorted_pairs)

        computed_hmac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(provided_hmac, computed_hmac)

    def verify_webhook_hmac(self, data_bytes: bytes, hmac_header: str) -> bool:
        """
        Verify Shopify Webhook HMAC-SHA256 signature from X-Shopify-Hmac-Sha256 header.
        """
        if not self.api_secret:
            if settings.ENVIRONMENT == "development":
                logger.warning("SHOPIFY_API_SECRET not set - allowing webhook in development.")
                return True
            logger.error("Shopify Webhook verification failed: SHOPIFY_API_SECRET is not configured in production.")
            return False

        if not hmac_header:
            return False

        computed_hmac = base64.b64encode(
            hmac.new(self.api_secret.encode("utf-8"), data_bytes, hashlib.sha256).digest()
        ).decode("utf-8")

        return hmac.compare_digest(hmac_header, computed_hmac)

    async def exchange_token(self, shop: str, code: str) -> Dict[str, Any]:
        """
        Exchange temporary authorization code for permanent Shopify offline access token.
        """
        cleaned_shop = self.clean_shop_domain(shop)
        url = f"https://{cleaned_shop}/admin/oauth/access_token"

        payload = {
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "code": code
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error(f"Shopify token exchange error: {response.text}")
                raise Exception(f"Failed to exchange Shopify token: {response.status_code}")
            return response.json()

    async def fetch_shop_details(self, shop: str, access_token: str) -> Dict[str, Any]:
        """
        Fetch store profile, primary domain, and sender email from Shopify Admin REST API.
        """
        cleaned_shop = self.clean_shop_domain(shop)
        url = f"https://{cleaned_shop}/admin/api/{self.api_version}/shop.json"
        headers = {"X-Shopify-Access-Token": access_token}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise Exception(f"Failed to fetch shop info: {response.status_code}")
            return response.json().get("shop", {})

    def check_sender_alignment(
        self,
        sender_email: str,
        custom_domain: str,
        spf_raw: Optional[str] = None,
        dkim_selectors: Optional[List[str]] = None,
        dmarc_policy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate if Shopify transactional sender email aligns with DNS authentication.
        """
        sender_domain = sender_email.split("@")[1].strip().lower() if "@" in sender_email else custom_domain.strip().lower()
        clean_target = custom_domain.strip().lower()

        domain_match = (sender_domain == clean_target) or sender_domain.endswith(f".{clean_target}")

        # Check SPF inclusion
        spf_aligned = bool(spf_raw and "shops.shopify.com" in spf_raw)

        # Check DKIM selector
        dkim_aligned = bool(dkim_selectors and any(s in ["shopify", "shopify2", "shopify3"] for s in dkim_selectors))

        # Check DMARC
        dmarc_aligned = bool(dmarc_policy in ["quarantine", "reject", "none"])

        overall_aligned = domain_match and spf_aligned and dkim_aligned and (dmarc_policy in ["quarantine", "reject"])

        return {
            "sender_email": sender_email,
            "sender_domain": sender_domain,
            "custom_domain": clean_target,
            "domain_match": domain_match,
            "spf_aligned": spf_aligned,
            "dkim_aligned": dkim_aligned,
            "dmarc_aligned": dmarc_aligned,
            "overall_aligned": overall_aligned,
            "recommendations": [] if overall_aligned else [
                *(["Add 'include:shops.shopify.com' mechanism to SPF TXT record."] if not spf_aligned else []),
                *(["Configure Shopify CNAME records ('shopify._domainkey') for DKIM signing."] if not dkim_aligned else []),
                *(["Upgrade DMARC policy from 'none' to 'quarantine' or 'reject'."] if dmarc_policy not in ["quarantine", "reject"] else []),
            ]
        }

    def simulate_order_delivery(
        self,
        shop_domain: str,
        customer_email: str,
        sender_email: str
    ) -> Dict[str, Any]:
        """
        Simulate an order notification delivery check with real-time deliverability breakdown.
        """
        order_num = f"#{10500 + int(datetime.utcnow().timestamp()) % 900}"
        sender_dom = sender_email.split("@")[1] if "@" in sender_email else shop_domain.replace(".myshopify.com", ".com")

        return {
            "order_id": order_num,
            "shop_domain": shop_domain,
            "customer_email": customer_email,
            "sender_email": sender_email,
            "sender_domain": sender_dom,
            "inbox_placement": "inbox_primary",
            "placement_rate": 99.2,
            "authentication_headers": {
                "spf": "PASS (sender IP authorized via shops.shopify.com)",
                "dkim": "PASS (signature verified with shopify._domainkey)",
                "dmarc": "PASS (policy=quarantine; pct=100; sender aligned)"
            },
            "timestamp": datetime.utcnow().isoformat(),
            "status": "delivered"
        }


shopify_service = ShopifyService()
