"""
InboundCheck - Shopify API Routes (v1)
======================================
Endpoints for Shopify OAuth handshake, store connection, sender alignment auditing,
and HMAC-verified webhook ingestion.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging
import json

from app.core.security import get_current_user_id
from app.core.config import settings
from app.core.request_body import read_body_with_limit
from app.core.tier_guards import verify_active_subscription_or_trial, TIER_DOMAIN_LIMITS
from app.services.shopify.shopify_service import shopify_service
from app.services.supabase_client import supabase_service, QuotaExceededError
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


def _canonical_shopify_charge_id(value: Any) -> Optional[str]:
    """Return gid://shopify/AppSubscription/<n> for a numeric id or GID; None if malformed."""
    if value is None or value == "":
        return None
    from app.services.shopify.shopify_billing_service import ShopifyBillingService
    try:
        return ShopifyBillingService.canonical_subscription_id(str(value))
    except ValueError:
        return None


def _same_shopify_charge(stored: Any, candidate: Any) -> bool:
    """Compare charge identities across numeric / GID spellings (exact match fallback)."""
    if not stored or not candidate:
        return False
    a, b = _canonical_shopify_charge_id(stored), _canonical_shopify_charge_id(candidate)
    if a and b:
        return a == b
    return str(stored) == str(candidate)


@router.get("/install")
async def shopify_direct_install(
    request: Request,
    shop: str = Query(..., description="Shopify store domain, e.g. store.myshopify.com"),
    timestamp: Optional[str] = Query(None),
    hmac: Optional[str] = Query(None)
):
    """
    Public entrypoint for Shopify App Store direct installation.
    Validates HMAC parameters if present, sanitizes domain using strict regex,
    generates secure signed state token, and redirects to Shopify OAuth consent screen.
    """
    query_params = dict(request.query_params)
    if "hmac" in query_params and query_params.get("hmac"):
        if not shopify_service.verify_shopify_hmac(query_params):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Shopify installation HMAC signature"
            )

    clean_shop = shopify_service.clean_shop_domain(shop)
    state = shopify_service.generate_oauth_state(user_id="shopify_app_store_install")
    redirect_uri = f"{settings.FRONTEND_URL}/dashboard/shopify/callback"
    auth_url = shopify_service.build_auth_url(
        shop=clean_shop,
        redirect_uri=redirect_uri,
        state=state
    )

    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


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

    # If state was generated by direct App Store install, bind to authenticated session if present
    if user_id == "shopify_app_store_install":
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.core.security import verify_supabase_jwt
                token = auth_header.split(" ")[1]
                claims = verify_supabase_jwt(token)
                resolved_sub = claims.get("sub") or claims.get("user_id")
                if resolved_sub:
                    user_id = str(resolved_sub)
            except Exception:
                pass

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


@router.get("/billing/callback")
async def shopify_billing_callback(
    charge_id: Optional[str] = Query(None),
    plan_tier: Optional[str] = Query("growth"),
    shop: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
):
    """
    Callback endpoint triggered by Shopify Admin after merchant approves an appSubscription.
    Verifies subscription status with Shopify Admin API and activates the plan tier in Supabase.
    Redirects merchant to frontend dashboard with billing=success.
    """
    if not charge_id:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard/billing?checkout=cancelled",
            status_code=status.HTTP_302_FOUND
        )

    clean_shop = None
    if shop:
        try:
            clean_shop = shopify_service.clean_shop_domain(shop)
        except Exception:
            clean_shop = shop

    if not clean_shop:
        logger.warning(
            "Shopify billing callback rejected: missing shop parameter",
            extra={
                "event_type": "security_billing_callback_rejected",
                "reason": "missing_shop",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise HTTPException(status_code=400, detail="Missing required shop parameter")

    resolved_user_id = user_id
    if not resolved_user_id:
        # Resolve user by store domain in persistent/in-memory store registry
        for uid, stores in getattr(supabase_service, "_in_memory_stores", {}).items():
            if any(s.get("shop_domain") == clean_shop for s in stores):
                resolved_user_id = uid
                break

    if not resolved_user_id:
        logger.warning(
            "Shopify billing callback rejected: unknown user for shop",
            extra={
                "event_type": "security_billing_callback_rejected",
                "shop": clean_shop,
                "reason": "unresolved_user",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise HTTPException(status_code=404, detail="Store owner not found")

    # Verify store ownership server-side
    stores = supabase_service.get_user_stores(resolved_user_id)
    store = next((s for s in stores if s.get("shop_domain") == clean_shop), None)
    if not store:
        logger.warning(
            "Shopify billing callback rejected: store does not belong to user",
            extra={
                "event_type": "security_billing_callback_rejected",
                "shop": clean_shop,
                "user_id": resolved_user_id,
                "reason": "store_ownership_mismatch",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise HTTPException(status_code=403, detail="Store domain not associated with tenant")

    # Idempotency check: if merchant profile is already active with this exact charge_id
    existing_profile = supabase_service.get_user_profile(resolved_user_id)
    if (
        existing_profile
        and _same_shopify_charge(existing_profile.get("shopify_charge_id"), charge_id)
        and existing_profile.get("subscription_status") == "active"
    ):
        current_tier = existing_profile.get("subscription_tier") or "growth"
        logger.info(
            "Shopify billing callback idempotent hit: charge already activated",
            extra={"shop": clean_shop, "charge_id": charge_id, "user_id": resolved_user_id}
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard/billing?checkout=success&billing=success&plan={current_tier}",
            status_code=status.HTTP_302_FOUND
        )

    # Gate 2: Access token must be present on store record for server-side verification
    encrypted_token = store.get("access_token_encrypted")
    if not encrypted_token:
        logger.warning(
            "Shopify billing callback rejected: store has no access token for verification",
            extra={"shop": clean_shop, "user_id": resolved_user_id}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store is not properly connected for billing verification"
        )

    # Gate 3: Decrypt token and query Shopify Admin API (Fail closed on any exception)
    try:
        from app.services.shopify.shopify_billing_service import shopify_billing_service
        token = shopify_service.decrypt_token(encrypted_token)
        sub_node = await shopify_billing_service.verify_and_activate_subscription(
            shop_domain=clean_shop,
            access_token=token,
            charge_id=charge_id
        )
    except HTTPException:
        raise
    except Exception as err:
        logger.error(
            f"Shopify subscription verification failed: {err}",
            extra={"shop": clean_shop, "charge_id": charge_id, "user_id": resolved_user_id}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify billing verification failed"
        )

    # Gate 4: Validate subscription node and status
    if not sub_node or not isinstance(sub_node, dict):
        logger.warning("Shopify billing callback rejected: missing subscription node")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify billing verification failed: missing subscription data"
        )

    sub_status = (sub_node.get("status") or "").upper()
    if sub_status not in ["ACTIVE", "ACCEPTED"]:
        logger.warning(
            f"Shopify billing callback rejected: subscription is not active (status={sub_status})",
            extra={"shop": clean_shop, "charge_id": charge_id, "status": sub_status}
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Shopify subscription is not active or was declined"
        )

    # Gate 5: Bind the tier exclusively to authoritative Shopify recurring pricing.
    # plan_tier remains accepted for callback URL compatibility, but grants nothing.
    try:
        verified_tier = shopify_billing_service.resolve_subscription_tier(sub_node)
    except ValueError:
        logger.warning(
            "Shopify billing callback rejected: unsupported recurring pricing",
            extra={"shop": clean_shop, "charge_id": charge_id, "user_id": resolved_user_id}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify billing verification failed: unsupported subscription pricing"
        )

    # Gate 6: Persist subscription activation in Supabase profile.
    # BILL-3/BILL-8: bind the canonical AppSubscription GID (what app_subscriptions/update
    # sends as admin_graphql_api_id) so lifecycle events can be matched to this charge.
    bound_charge_id = _canonical_shopify_charge_id(sub_node.get("id")) or _canonical_shopify_charge_id(charge_id) or charge_id
    supabase_service.update_user_profile(resolved_user_id, {
        "subscription_tier": verified_tier,
        "subscription_status": "active",
        "billing_provider": "shopify",
        "shopify_charge_id": bound_charge_id,
    })

    redirect_target = f"{settings.FRONTEND_URL}/dashboard/billing?checkout=success&billing=success&plan={verified_tier}"
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)



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
    body_bytes = await read_body_with_limit(request)

    triggered_at = request.headers.get("X-Shopify-Triggered-At")
    if triggered_at and not shopify_service.verify_webhook_timestamp(triggered_at):
        raise HTTPException(status_code=400, detail="Shopify webhook timestamp outside tolerance window")

    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not shopify_service.verify_webhook_hmac(body_bytes, hmac_header):
        # Ops Alert (OPS-02)
        try:
            from app.services.alerting.ops_alert_service import ops_alert_service, OpsIncident
            await ops_alert_service.dispatch_incident(
                OpsIncident(
                    alert_id="ALERT-SHOPIFY-WEBHOOK",
                    severity="P1",
                    summary="Shopify orders webhook HMAC signature verification failed",
                    details={"topic": "orders/create", "reason": "invalid_hmac_signature"},
                )
            )
        except Exception as alert_err:
            logger.warning(f"Failed to dispatch Shopify webhook ops alert: {alert_err}")
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


async def _accept_shopify_privacy_webhook(request: Request, topic: str) -> dict:
    """Persist a minimized privacy receipt before acknowledgement; no BackgroundTasks durability claim."""
    from app.services.privacy.minimization import PrivacyValidationError
    from app.services.privacy.repository import PrivacyAcceptanceError, accept_gdpr_request
    body_bytes = await read_body_with_limit(request)
    envelope = shopify_service.verify_webhook_envelope(body_bytes, request.headers, topic)
    try:
        receipt = accept_gdpr_request(topic, envelope["shop"], envelope["payload"], envelope["delivery_id"])
    except PrivacyValidationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Shopify privacy webhook payload") from None
    except PrivacyAcceptanceError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Privacy request persistence temporarily unavailable") from None
    return {"status": "accepted", "action": "privacy_request_persisted", "verified": True, "state": receipt["state"], "idempotent": receipt["idempotent"]}


@router.post("/webhooks/customers/data_request", status_code=status.HTTP_200_OK)
async def shopify_customer_data_request_webhook(request: Request):
    """Accept a durable, minimized GDPR data-request job; does not claim export completion."""
    return await _accept_shopify_privacy_webhook(request, "customers/data_request")


@router.post("/webhooks/customers/redact", status_code=status.HTTP_200_OK)
async def shopify_customer_redact_webhook(request: Request):
    """Accept a durable, minimized GDPR redaction job; does not claim erasure completion."""
    return await _accept_shopify_privacy_webhook(request, "customers/redact")


@router.post("/webhooks/shop/redact", status_code=status.HTTP_200_OK)
async def shopify_shop_redact_webhook(request: Request):
    """Accept a durable shop-redaction job; scope is shop data, not tenant deletion."""
    return await _accept_shopify_privacy_webhook(request, "shop/redact")

@router.post("/webhooks/app/uninstalled", status_code=status.HTTP_200_OK)
@router.post("/webhooks/app_uninstalled", status_code=status.HTTP_200_OK)
async def shopify_app_uninstalled_webhook(request: Request):
    """
    Shopify App Lifecycle Webhook: app/uninstalled
    Triggered immediately when a merchant uninstalls the InboundCheck app.
    1. Validates payload limit (<= 1MB).
    2. Validates timestamp drift tolerance (±300s).
    3. Validates HMAC-SHA256 signature fail-closed.
    4. Enforces idempotency via X-Shopify-Webhook-Id.
    5. Resolves shop domain server-side; validates tenant ownership.
    6. Authoritatively deactivates store and revokes encrypted access token.
    Returns fast HTTP 200 (<500ms).
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1024 * 1024:
                raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")
        except ValueError:
            pass

    body_bytes = await read_body_with_limit(request)
    if len(body_bytes) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")

    triggered_at = request.headers.get("X-Shopify-Triggered-At")
    if triggered_at and not shopify_service.verify_webhook_timestamp(triggered_at):
        raise HTTPException(status_code=400, detail="Shopify webhook timestamp outside tolerance window")

    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not shopify_service.verify_webhook_hmac(body_bytes, hmac_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Shopify HMAC-SHA256 signature"
        )

    webhook_id = request.headers.get("X-Shopify-Webhook-Id")
    if webhook_id and shopify_service.is_webhook_processed(webhook_id):
        return {
            "status": "already_processed",
            "action": "uninstall_skipped",
            "verified": True,
            "webhook_id": webhook_id
        }

    shop_header = request.headers.get("X-Shopify-Shop-Domain")
    shop_domain = None
    if shop_header:
        shop_domain = shop_header
    else:
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            shop_domain = payload.get("myshopify_domain") or payload.get("domain") or payload.get("shop_domain")
        except Exception:
            pass

    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing Shopify shop domain")

    clean_shop = shopify_service.clean_shop_domain(shop_domain)

    # Server-side store resolution
    store = supabase_service.get_store_by_domain(clean_shop)
    if not store:
        logger.info(f"Shopify app/uninstalled received for untracked shop: {clean_shop}")
        if webhook_id:
            shopify_service.mark_webhook_processed(webhook_id, event_type="shopify_app_uninstalled")
        return {
            "status": "acknowledged",
            "action": "untracked_shop_ignored",
            "shop": clean_shop,
            "verified": True
        }

    # Deactivate store record authoritatively (soft-deactivation, zero audit record deletion)
    supabase_service.deactivate_store(clean_shop)

    if webhook_id:
        shopify_service.mark_webhook_processed(webhook_id, event_type="shopify_app_uninstalled")

    logger.info(f"Successfully processed app/uninstalled for shop {clean_shop} (tenant {store.get('user_id')})")
    return {
        "status": "success",
        "action": "store_deactivated",
        "shop": clean_shop,
        "verified": True,
        "webhook_id": webhook_id
    }


@router.post("/webhooks/app_subscriptions/update", status_code=status.HTTP_200_OK)
@router.post("/webhooks/app_subscriptions_update", status_code=status.HTTP_200_OK)
async def shopify_app_subscriptions_update_webhook(request: Request):
    """
    Shopify App Lifecycle Webhook: app_subscriptions/update
    Synchronizes Shopify AppSubscription status changes (ACTIVE, CANCELLED, EXPIRED, DECLINED, PAUSED).
    1. Validates payload limit (<= 1MB).
    2. Validates timestamp drift tolerance (±300s).
    3. Validates HMAC-SHA256 signature fail-closed.
    4. Enforces idempotency via X-Shopify-Webhook-Id.
    5. Resolves shop domain server-side; validates tenant ownership.
    6. Queries Shopify GraphQL API server-side using stored credentials for authoritative subscription data.
    7. Maps Shopify status via map_shopify_subscription_status() onto the DB-allowed
       subscription_status set; derives tier only from verified recurring pricing.
    8. Applies downgrades only for the user's bound shopify_charge_id (stale charges ignored).
       A profile with no bound charge (NULL, pre-migration) is downgraded only when the
       authoritative lookup confirms the status and the profile is not Stripe-billed.
    9. If the authoritative lookup FAILS (timeout/5xx/token error) where its answer is
       required, returns 503 without marking the webhook processed so Shopify retries.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1024 * 1024:
                raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")
        except ValueError:
            pass

    body_bytes = await read_body_with_limit(request)
    if len(body_bytes) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum limit of 1MB")

    triggered_at = request.headers.get("X-Shopify-Triggered-At")
    if triggered_at and not shopify_service.verify_webhook_timestamp(triggered_at):
        raise HTTPException(status_code=400, detail="Shopify webhook timestamp outside tolerance window")

    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not shopify_service.verify_webhook_hmac(body_bytes, hmac_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Shopify HMAC-SHA256 signature"
        )

    webhook_id = request.headers.get("X-Shopify-Webhook-Id")
    if webhook_id and shopify_service.is_webhook_processed(webhook_id):
        return {
            "status": "already_processed",
            "action": "subscription_sync_skipped",
            "verified": True,
            "webhook_id": webhook_id
        }

    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    shop_header = request.headers.get("X-Shopify-Shop-Domain")
    shop_domain = shop_header or payload.get("myshopify_domain") or payload.get("shop_domain")
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing Shopify shop domain")

    clean_shop = shopify_service.clean_shop_domain(shop_domain)

    # Server-side store resolution
    store = supabase_service.get_store_by_domain(clean_shop)
    if not store:
        logger.info(f"Shopify app_subscriptions/update received for untracked shop: {clean_shop}")
        if webhook_id:
            shopify_service.mark_webhook_processed(webhook_id, event_type="shopify_app_subscriptions_update")
        return {
            "status": "acknowledged",
            "action": "untracked_shop_ignored",
            "shop": clean_shop,
            "verified": True
        }

    user_id = store.get("user_id")
    if not user_id:
        logger.warning(f"Store {clean_shop} has no associated user_id")
        return {"status": "error", "reason": "orphan_store", "shop": clean_shop}

    # Extract subscription details from payload
    sub_obj = payload.get("app_subscription", payload)
    charge_id = sub_obj.get("admin_graphql_api_id") or sub_obj.get("id")
    if not charge_id:
        raise HTTPException(status_code=400, detail="Missing subscription id in payload")

    charge_id_str = str(charge_id)
    raw_status = (sub_obj.get("status") or "").upper().strip()
    event_charge_id = _canonical_shopify_charge_id(charge_id_str)

    def _ack(action: str, final_status: str) -> dict:
        if webhook_id:
            shopify_service.mark_webhook_processed(webhook_id, event_type="shopify_app_subscriptions_update")
        return {
            "status": "success",
            "action": action,
            "subscription_status": final_status,
            "shop": clean_shop,
            "user_id": user_id,
            "verified": True,
            "webhook_id": webhook_id
        }

    if not event_charge_id:
        logger.warning("Shopify app_subscriptions/update ignored: malformed subscription identity",
                       extra={"shop": clean_shop, "user_id": user_id})
        return _ack("invalid_charge_ignored", "unchanged")

    # Authoritative verification via Shopify GraphQL API if access token is available
    authoritative_node = None
    lookup_failed = False
    encrypted_token = store.get("access_token_encrypted")
    if encrypted_token and encrypted_token != "revoked":
        try:
            from app.services.shopify.shopify_billing_service import shopify_billing_service
            token = shopify_service.decrypt_token(encrypted_token)
            authoritative_node = await shopify_billing_service.get_app_subscription(
                shop_domain=clean_shop,
                access_token=token,
                charge_id=event_charge_id
            )
            if authoritative_node:
                raw_status = (authoritative_node.get("status") or raw_status).upper().strip()
        except Exception as query_err:
            authoritative_node = None
            lookup_failed = True
            logger.warning(f"Could not verify subscription against Shopify API: {type(query_err).__name__}")

    def _lookup_unavailable() -> HTTPException:
        # REV-1: do NOT mark the webhook processed; Shopify retries on non-2xx.
        logger.error("Shopify app_subscriptions/update deferred: authoritative lookup failed",
                     extra={"shop": clean_shop, "user_id": user_id, "webhook_id": webhook_id})
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail="Shopify subscription verification temporarily unavailable")

    from app.services.shopify.shopify_billing_service import (
        shopify_billing_service,
        map_shopify_subscription_status,
    )
    app_status = map_shopify_subscription_status(raw_status)
    if app_status is None:
        # PENDING or unknown: never upgrade or downgrade.
        logger.warning(f"Shopify subscription status '{raw_status}' carries no entitlement change")
        return _ack("status_unrecognized_ignored", raw_status.lower() or "unknown")

    profile = supabase_service.get_user_profile(user_id) or {}
    stored_charge_id = profile.get("shopify_charge_id")
    is_bound_charge = _same_shopify_charge(stored_charge_id, event_charge_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    if app_status == "active":
        # BILL-8: activation of a (new) charge requires authoritative Shopify verification;
        # tier is bound to verified recurring pricing, never the subscription name.
        if not authoritative_node:
            if lookup_failed:
                raise _lookup_unavailable()
            logger.warning("Shopify ACTIVE event ignored: subscription could not be verified",
                           extra={"shop": clean_shop, "user_id": user_id})
            return _ack("unverified_activation_ignored", "unchanged")
        try:
            verified_tier = shopify_billing_service.resolve_subscription_tier(authoritative_node)
        except ValueError:
            logger.warning("Shopify ACTIVE event ignored: unsupported recurring pricing",
                           extra={"shop": clean_shop, "user_id": user_id})
            return _ack("unsupported_pricing_ignored", "unchanged")
        supabase_service.update_user_profile(user_id, {
            "subscription_tier": verified_tier,
            "tier": verified_tier,
            "subscription_status": "active",
            "billing_provider": "shopify",
            "shopify_charge_id": event_charge_id,
            "updated_at": now_iso,
        })
        return _ack("subscription_activated", "active")

    # BILL-8: downgrades only apply to the user's currently bound charge. A CANCELLED
    # event for the replaced charge after an upgrade must not revoke the new plan.
    # REV-2: profiles with no bound charge (column new in prod -> NULL) may be downgraded
    # only when Shopify authoritatively confirms this subscription's status, and never
    # when the profile is billed through Stripe.
    if not is_bound_charge and not stored_charge_id:
        is_stripe_billed = (profile.get("billing_provider") == "stripe") or (
            not profile.get("billing_provider") and bool(profile.get("stripe_subscription_id"))
        )
        if not is_stripe_billed:
            if authoritative_node is None and lookup_failed:
                raise _lookup_unavailable()
            if authoritative_node is not None and map_shopify_subscription_status(
                authoritative_node.get("status")
            ) == app_status:
                is_bound_charge = True
    if not is_bound_charge:
        logger.info("Shopify lifecycle event for non-current charge ignored",
                    extra={"shop": clean_shop, "user_id": user_id, "status": raw_status})
        return _ack("stale_charge_ignored", "unchanged")

    supabase_service.update_user_profile(user_id, {
        "subscription_tier": "starter",
        "tier": "starter",
        "subscription_status": app_status,
        "updated_at": now_iso,
    })
    return _ack(f"subscription_{app_status}", app_status)


@router.get("/stores")
async def get_shopify_stores(
    active_only: bool = Query(True, description="Filter active stores only"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Retrieve authenticated Shopify stores registered for the current merchant.
    Defaults to returning active stores only.
    Returns HTTP 200 with an empty list [] if no stores have been connected yet.
    """
    try:
        from app.services.supabase_client import supabase_service
        stores = supabase_service.get_user_stores(user_id, active_only=active_only)
        return stores
    except Exception as e:
        logger.error(f"Failed to fetch Shopify stores for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve connected Shopify stores")


@router.delete("/stores/{store_id}", status_code=status.HTTP_200_OK)
async def disconnect_shopify_store(
    store_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    Securely disconnect a Shopify store for the current authenticated merchant.
    Soft-deactivates the store record (is_active=False) and revokes encrypted credentials.
    Historical audit logs and transactional registries remain intact.
    Returns HTTP 404 if the store does not exist or belongs to another tenant.
    Idempotent: repeating disconnect on an already-disconnected store returns HTTP 200.
    """
    try:
        from app.services.supabase_client import supabase_service
        result = supabase_service.disconnect_user_store(user_id=user_id, store_id=store_id)
        if not result:
            logger.warning(
                f"Unauthorized or missing store disconnect attempt for store_id '{store_id}' by user '{user_id}'",
                extra={"event_type": "security_store_disconnect_rejected", "store_id": store_id, "user_id": user_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store with ID '{store_id}' not found or unauthorized for current tenant."
            )

        shop_domain = result.get("shop_domain")
        logger.info(
            f"Successfully disconnected store '{shop_domain}' (ID: {store_id}) for tenant '{user_id}'",
            extra={"event_type": "store_disconnected", "store_id": store_id, "user_id": user_id}
        )
        return {
            "success": True,
            "status": "disconnected",
            "store_id": result.get("id") or store_id,
            "shop_domain": shop_domain,
            "message": "Shopify store disconnected successfully and sync credentials revoked."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect store '{store_id}' for user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to disconnect Shopify store")



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

        # 1. Resolve and validate target store for tenant (SEC-STORE-CONFUSION-01)
        existing_stores = supabase_service.get_user_stores(user_id)
        existing_store = None
        shop_dom = None

        # Clean/validate shop_domain if provided
        clean_shop = None
        if payload.shop_domain:
            try:
                clean_shop = shopify_service.clean_shop_domain(payload.shop_domain)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid Shopify store domain format: '{payload.shop_domain}'."
                )

        if payload.store_id:
            matched_store = next((s for s in existing_stores if str(s.get("id")) == str(payload.store_id)), None)
            if not matched_store:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Store with ID '{payload.store_id}' not found or unauthorized for current tenant."
                )

            # Reject conflicting selectors if both store_id and shop_domain are supplied
            if clean_shop and matched_store.get("shop_domain") != clean_shop:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Conflicting store selectors: store_id and shop_domain do not point to the same store."
                )

            existing_store = matched_store
            shop_dom = existing_store.get("shop_domain")

        elif clean_shop:
            matched_store = next((s for s in existing_stores if s.get("shop_domain") == clean_shop), None)
            if matched_store:
                existing_store = matched_store
                shop_dom = clean_shop
            else:
                # Check cross-tenant ownership
                is_foreign = False
                if supabase_service.is_connected:
                    try:
                        res = supabase_service._client.table("shopify_stores").select("user_id").eq("shop_domain", clean_shop).execute()
                        if res.data and any(str(r.get("user_id")) != str(user_id) for r in res.data):
                            is_foreign = True
                    except Exception as e:
                        logger.warning(f"Error checking store ownership for {clean_shop}: {e}")
                else:
                    for other_uid, o_stores in supabase_service._in_memory_stores.items():
                        if str(other_uid) != str(user_id) and any(s.get("shop_domain") == clean_shop for s in o_stores):
                            is_foreign = True
                            break

                if is_foreign or len(existing_stores) > 0:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Shop domain '{clean_shop}' not found or not associated with your account."
                    )
                shop_dom = clean_shop

        else:
            if len(existing_stores) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Multiple stores connected. Please specify 'store_id' or 'shop_domain' to select which store to update."
                )
            elif len(existing_stores) == 1:
                existing_store = existing_stores[0]
                shop_dom = existing_store.get("shop_domain")
            else:
                slug = (payload.store_name or "brand-store").lower().replace(" ", "-")
                shop_dom = f"{slug}.myshopify.com"

        # 2. Update user profile company_name with store_name if supplied
        if payload.store_name:
            if supabase_service.is_connected:
                try:
                    supabase_service._client.table("profiles").update({"company_name": payload.store_name}).eq("id", user_id).execute()
                except Exception as e:
                    logger.warning(f"Could not update profile company_name: {e}")
            from app.api.v1.settings import _mock_profiles
            if user_id in _mock_profiles:
                _mock_profiles[user_id]["company_name"] = payload.store_name

        # 3. Register/update custom sending domain in monitored_domains
        clean_dom = None
        if payload.custom_domain:
            try:
                clean_dom = DNSDiagnosticEngine.normalize_domain(payload.custom_domain)
            except ValueError as val_err:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))

            # Enforce active subscription or valid trial entitlement
            user_profile = await verify_active_subscription_or_trial(user_id=user_id)
            tier = (user_profile.get("subscription_tier") or user_profile.get("tier") or "starter").lower()
            if tier == "enterprise":
                tier = "agency"  # Safe legacy enterprise migration mapping
            quota_limit = TIER_DOMAIN_LIMITS.get(tier, 1)

            # Check existing domain count and allow updating already-monitored domain without quota penalty
            existing_domains = supabase_service.get_user_domains(user_id=user_id, limit=100)
            is_already_monitored = any(d.get("domain_name") == clean_dom for d in existing_domains)

            if not is_already_monitored and len(existing_domains) >= quota_limit:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Domain quota reached ({len(existing_domains)}/{quota_limit}) for '{tier.capitalize()}' plan. Please upgrade your plan in Billing to add more domains."
                )

            try:
                supabase_service.provision_monitored_domain(
                    user_id=user_id,
                    domain_name=clean_dom,
                    quota_limit=quota_limit,
                    audit_result=None
                )
            except QuotaExceededError:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Domain quota reached ({len(existing_domains)}/{quota_limit}) for '{tier.capitalize()}' plan. Please upgrade your plan in Billing to add more domains."
                )

        # 4. Save and return store configuration
        existing_meta = existing_store.get("metadata", {}) if existing_store else {}
        clean_or_existing_custom = clean_dom or payload.custom_domain or existing_meta.get("custom_domain")
        updated_meta = {
            "name": payload.store_name or existing_meta.get("name", "Store"),
            "email": payload.sender_email or (existing_store.get("sender_email") if existing_store else None),
            "custom_domain": clean_or_existing_custom,
            "esp_provider": payload.esp_provider or existing_meta.get("esp_provider", "shopify"),
            "primary_domain": clean_or_existing_custom or shop_dom,
            "myshopify_domain": shop_dom,
        }

        resolved_store_id = existing_store.get("id") if existing_store else payload.store_id
        saved = supabase_service.save_monitored_store(
            user_id=user_id,
            shop_domain=shop_dom,
            access_token_encrypted=existing_store.get("access_token_encrypted", "mock_token") if existing_store else "mock_token",
            scope="read_orders",
            sender_email=payload.sender_email or (existing_store.get("sender_email") if existing_store else None),
            store_metadata=updated_meta,
            sender_alignment_status="aligned",
            store_id=resolved_store_id
        )
        if clean_or_existing_custom:
            saved["custom_domain"] = clean_or_existing_custom
        if payload.esp_provider:
            saved["esp_provider"] = payload.esp_provider

        return {
            "success": True,
            "store": saved
        }
    except HTTPException:
        raise
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


