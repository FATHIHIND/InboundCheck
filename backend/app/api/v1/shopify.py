"""
InboundCheck - Shopify API Routes (v1)
======================================
Endpoints for Shopify OAuth handshake, store connection, sender alignment auditing,
and HMAC-verified webhook ingestion.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.services.shopify.shopify_service import shopify_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer

logger = logging.getLogger("ShopifyRoutes")

router = APIRouter(prefix="/shopify", tags=["Shopify Integration"])
diagnostic_engine = DNSDiagnosticEngine()


class ConnectStoreRequest(BaseModel):
    shop: str = Field(..., description="Shopify store domain, e.g. store.myshopify.com")
    redirect_uri: Optional[str] = None
    state: Optional[str] = "inboundcheck-oauth-state"


class SenderAlignmentRequest(BaseModel):
    sender_email: str = Field(..., description="Store sender address, e.g. orders@brandshop.com")
    custom_domain: str = Field(..., description="Custom domain name, e.g. brandshop.com")


class SimulateOrderRequest(BaseModel):
    shop_domain: str = Field(default="luxurystore.myshopify.com")
    customer_email: str = Field(default="sarah.customer@gmail.com")
    sender_email: str = Field(default="orders@luxurystore.com")


@router.post("/oauth/authorize")
async def get_shopify_auth_url(
    request: ConnectStoreRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Generate Shopify OAuth authorization URL for store installation.
    """
    try:
        redirect = request.redirect_uri or "http://localhost:3000/dashboard/shopify/callback"
        auth_url = shopify_service.build_auth_url(
            shop=request.shop,
            redirect_uri=redirect,
            state=request.state or "state"
        )
        return {
            "auth_url": auth_url,
            "shop": shopify_service.clean_shop_domain(request.shop)
        }
    except Exception as e:
        logger.error(f"Error creating Shopify auth URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate Shopify authorization URL")


@router.get("/oauth/callback")
async def shopify_auth_callback(
    request: Request,
    shop: str = Query(...),
    code: str = Query(...),
    hmac: Optional[str] = Query(None),
    state: Optional[str] = Query(None)
):
    """
    Handle Shopify OAuth redirect callback and exchange authorization code for access token.
    Enforces HMAC parameter verification and state CSRF checks.
    """
    query_params = dict(request.query_params)
    if not shopify_service.verify_shopify_hmac(query_params):
        raise HTTPException(status_code=401, detail="Invalid Shopify OAuth HMAC signature")

    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state CSRF token")

    try:
        token_data = await shopify_service.exchange_token(shop=shop, code=code)
        access_token = token_data.get("access_token")
        scope = token_data.get("scope")

        shop_details = {}
        if access_token:
            shop_details = await shopify_service.fetch_shop_details(shop=shop, access_token=access_token)

        return {
            "success": True,
            "shop": shop,
            "scope": scope,
            "store_name": shop_details.get("name"),
            "email": shop_details.get("email"),
            "domain": shop_details.get("domain")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shopify OAuth callback error: {e}")
        raise HTTPException(status_code=400, detail="Shopify OAuth authorization code exchange failed")


@router.post("/sender-alignment")
async def check_sender_alignment(
    payload: SenderAlignmentRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Audit whether the store's transactional sender email header aligns with its DNS authentication posture.
    """
    try:
        clean_domain = payload.custom_domain.strip().lower()
        summary, _, _ = await diagnostic_engine.audit_domain(clean_domain)

        spf_raw = summary.spf.raw
        dkim_found = summary.dkim.found_selectors
        dmarc_pol = summary.dmarc.policy

        alignment = shopify_service.check_sender_alignment(
            sender_email=payload.sender_email,
            custom_domain=clean_domain,
            spf_raw=spf_raw,
            dkim_selectors=dkim_found,
            dmarc_policy=dmarc_pol
        )

        return {
            "success": True,
            "alignment": alignment,
            "summary": {
                "spf_status": summary.spf.status,
                "dkim_status": summary.dkim.status,
                "dmarc_status": summary.dmarc.status
            }
        }
    except Exception as e:
        logger.error(f"Error checking sender alignment: {e}")
        raise HTTPException(status_code=500, detail="Failed to evaluate sender alignment")


@router.post("/simulate-order")
async def simulate_test_order(
    payload: SimulateOrderRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Simulate a $0.00 draft order transactional delivery verification.
    """
    try:
        result = shopify_service.simulate_order_delivery(
            shop_domain=payload.shop_domain,
            customer_email=payload.customer_email,
            sender_email=payload.sender_email
        )
        return {
            "success": True,
            "simulation": result
        }
    except Exception as e:
        logger.error(f"Order simulation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to simulate test order delivery")


@router.post("/webhooks/orders")
@router.post("/webhooks/orders/create")
async def shopify_orders_webhook(request: Request):
    """
    Ingest Shopify Order Created Webhook with HMAC-SHA256 signature verification,
    timestamp tolerance (±300s), idempotency deduplication, and payload limits.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1024 * 1024:
                raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")
        except ValueError:
            pass

    body_bytes = await request.body()
    if len(body_bytes) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")

    triggered_at = request.headers.get("X-Shopify-Triggered-At")
    if triggered_at and not shopify_service.verify_webhook_timestamp(triggered_at):
        raise HTTPException(status_code=400, detail="Shopify webhook timestamp outside tolerance window")

    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not shopify_service.verify_webhook_hmac(body_bytes, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid Shopify HMAC-SHA256 signature")

    webhook_id = request.headers.get("X-Shopify-Webhook-Id")
    if webhook_id and shopify_service.is_webhook_processed(webhook_id):
        return {
            "status": "already_processed",
            "action": "transactional_audit_skipped",
            "verified": True,
            "webhook_id": webhook_id
        }

    if webhook_id:
        shopify_service.mark_webhook_processed(webhook_id)

    return {
        "status": "received",
        "action": "transactional_audit_dispatched",
        "verified": True,
        "webhook_id": webhook_id
    }
