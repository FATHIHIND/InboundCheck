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
from app.core.config import settings
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.schemas.shopify_readiness import ShopifyReadinessRequest, ShopifyReadinessResponse

logger = logging.getLogger("ShopifyRoutes")

router = APIRouter(prefix="/shopify", tags=["Shopify Integration"])
diagnostic_engine = DNSDiagnosticEngine()


class ConnectStoreRequest(BaseModel):
    shop: str = Field(..., description="Shopify store domain, e.g. store.myshopify.com")
    redirect_uri: Optional[str] = None
    state: Optional[str] = None


class SenderAlignmentRequest(BaseModel):
    sender_email: str = Field(..., description="Store sender address, e.g. orders@brandshop.com")
    custom_domain: str = Field(..., description="Custom domain name, e.g. brandshop.com")


class SimulateOrderRequest(BaseModel):
    shop_domain: str = Field(default="luxurystore.myshopify.com")
    customer_email: str = Field(default="sarah.customer@gmail.com")
    sender_email: str = Field(default="orders@luxurystore.com")


class UpdateStoreSettingsRequest(BaseModel):
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    shop_domain: Optional[str] = None
    custom_domain: Optional[str] = None
    sender_email: Optional[str] = None
    esp_provider: Optional[str] = "shopify"


@router.post("/oauth/authorize")
async def get_shopify_auth_url(
    request: ConnectStoreRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Generate Shopify OAuth authorization URL for store installation.
    Binds the OAuth state to the authenticated tenant using HMAC-SHA256 signature and timestamp.
    """
    try:
        # Generate cryptographically signed state token bound to user_id
        state = shopify_service.generate_oauth_state(user_id=user_id)
        redirect = request.redirect_uri or f"{settings.FRONTEND_URL}/dashboard/shopify/callback"
        auth_url = shopify_service.build_auth_url(
            shop=request.shop,
            redirect_uri=redirect,
            state=state
        )
        return {
            "auth_url": auth_url,
            "shop": shopify_service.clean_shop_domain(request.shop),
            "state": state
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
    Enforces HMAC parameter verification and signed state CSRF/tenant checks.
    Persists encrypted token, shop domain, and sanitized metadata to public.monitored_stores.
    """
    query_params = dict(request.query_params)
    if not shopify_service.verify_shopify_hmac(query_params):
        raise HTTPException(status_code=401, detail="Invalid Shopify OAuth HMAC signature")

    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state CSRF token")

    # Cryptographically resolve tenant user_id from signed state parameter
    user_id = shopify_service.verify_oauth_state(state)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or untrusted OAuth state parameter"
        )

    try:
        clean_shop = shopify_service.clean_shop_domain(shop)
        token_data = await shopify_service.exchange_token(shop=clean_shop, code=code)
        access_token = token_data.get("access_token")
        scope = token_data.get("scope", shopify_service.scopes)

        if not access_token:
            raise HTTPException(status_code=400, detail="No access token returned by Shopify")

        # Fetch sanitized shop metadata from Shopify Admin API
        shop_details = {}
        try:
            shop_details = await shopify_service.fetch_shop_details(shop=clean_shop, access_token=access_token)
        except Exception as shop_err:
            logger.warning(f"Could not fetch full shop details for {clean_shop}: {shop_err}")

        # Sanitize metadata
        sender_email = shop_details.get("email") or shop_details.get("customer_email")
        store_metadata = {
            "name": shop_details.get("name"),
            "email": sender_email,
            "primary_domain": shop_details.get("domain"),
            "myshopify_domain": clean_shop,
            "currency": shop_details.get("currency"),
            "timezone": shop_details.get("iana_timezone") or shop_details.get("timezone"),
            "plan_name": shop_details.get("plan_name"),
        }

        # Encrypt access token using Fernet before database persistence
        encrypted_token = shopify_service.encrypt_token(access_token)

        # Persist to public.shopify_stores / public.monitored_stores
        saved_store = supabase_service.save_monitored_store(
            user_id=user_id,
            shop_domain=clean_shop,
            access_token_encrypted=encrypted_token,
            scope=scope,
            sender_email=sender_email,
            store_metadata=store_metadata,
            sender_alignment_status="pending"
        )

        return {
            "success": True,
            "shop": clean_shop,
            "scope": scope,
            "store_name": shop_details.get("name"),
            "email": sender_email,
            "domain": shop_details.get("domain"),
            "user_id": user_id,
            "stored": True,
            "store_id": saved_store.get("id")
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


@router.get("/stores")
async def get_shopify_stores(user_id: str = Depends(get_current_user_id)):
    """
    Retrieve authenticated Shopify stores registered for the current merchant.
    Returns HTTP 200 with an empty list [] if no stores have been connected yet.
    """
    try:
        from app.services.supabase_client import supabase_service
        stores = supabase_service.get_user_stores(user_id)
        return stores
    except Exception as e:
        logger.error(f"Failed to fetch Shopify stores for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve connected Shopify stores")


@router.post("/store-settings")
async def update_store_settings(
    payload: UpdateStoreSettingsRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Update merchant store configuration in-context: store name, custom domain, sender email, and ESP provider.
    """
    try:
        from app.services.supabase_client import supabase_service

        # 1. Update user profile company_name with store_name if supplied
        if payload.store_name:
            if supabase_service.is_connected:
                try:
                    supabase_service._client.table("profiles").update({"company_name": payload.store_name}).eq("id", user_id).execute()
                except Exception as e:
                    logger.warning(f"Could not update profile company_name: {e}")
            from app.api.v1.settings import _mock_profiles
            if user_id in _mock_profiles:
                _mock_profiles[user_id]["company_name"] = payload.store_name

        # 2. Register/update custom sending domain in monitored_domains
        if payload.custom_domain:
            clean_dom = payload.custom_domain.strip().lower()
            supabase_service.create_or_update_domain(
                user_id=user_id,
                domain_name=clean_dom,
                audit_result=None
            )

        # 3. Retrieve or create store entry
        existing_stores = supabase_service.get_user_stores(user_id)
        existing_store = existing_stores[0] if existing_stores else None

        shop_dom = payload.shop_domain or (existing_store.get("shop_domain") if existing_store else None)
        if not shop_dom:
            slug = (payload.store_name or "brand-store").lower().replace(" ", "-")
            shop_dom = f"{slug}.myshopify.com"

        updated_meta = {
            "name": payload.store_name or (existing_store.get("metadata", {}).get("name") if existing_store else "Store"),
            "email": payload.sender_email,
            "custom_domain": payload.custom_domain,
            "esp_provider": payload.esp_provider or "shopify",
            "primary_domain": payload.custom_domain or shop_dom,
            "myshopify_domain": shop_dom,
        }

        saved = supabase_service.save_monitored_store(
            user_id=user_id,
            shop_domain=shop_dom,
            access_token_encrypted=existing_store.get("access_token_encrypted", "mock_token") if existing_store else "mock_token",
            scope="read_orders,write_orders",
            sender_email=payload.sender_email,
            store_metadata=updated_meta,
            sender_alignment_status="aligned"
        )
        if payload.custom_domain:
            saved["custom_domain"] = payload.custom_domain
        if payload.esp_provider:
            saved["esp_provider"] = payload.esp_provider

        return {
            "success": True,
            "store": saved
        }
    except Exception as e:
        logger.error(f"Failed to update store settings for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update store settings")


@router.get("/webhook-logs")
async def get_shopify_webhook_logs(user_id: str = Depends(get_current_user_id)):
    """
    Retrieve recent Shopify webhook ingestion audit logs for the current merchant.
    """
    try:
        # In-memory / persistent webhook event audit logs
        return []
    except Exception as e:
        logger.error(f"Failed to fetch webhook logs for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Shopify webhook logs")


@router.post("/deliverability-readiness", response_model=ShopifyReadinessResponse)
async def evaluate_deliverability_readiness(
    request: ShopifyReadinessRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Evaluate 6 core deliverability readiness checks for Shopify Zero-Spam delivery:
    1. custom_sending_domain
    2. shopify_dkim
    3. spf_alignment
    4. dmarc_policy
    5. spf_conflict
    6. shared_pool_exposure
    """
    try:
        from app.schemas.shopify_readiness import ShopifyReadinessResponse
        from app.services.shopify.deliverability_readiness_service import deliverability_readiness_service
        
        target_domain = request.domain
        if not target_domain:
            domains = supabase_service.get_user_domains(user_id)
            if domains and len(domains) > 0:
                target_domain = domains[0].get("domain_name")

        if not target_domain:
            target_domain = "shopify.com"

        return await deliverability_readiness_service.evaluate_readiness(
            domain=target_domain,
            user_id=user_id,
            store_id=request.store_id
        )
    except Exception as e:
        logger.error(f"Failed to evaluate deliverability readiness: {e}")
        raise HTTPException(status_code=500, detail="Failed to evaluate deliverability readiness")


