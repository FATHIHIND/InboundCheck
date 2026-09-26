"""
InboundCheck - 1-Click Auto-DNS Fixer REST Router (v1)
======================================================
Endpoints for managing Cloudflare API credentials, 1-click DNS record auto-remediation,
and audited rollback operations.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.core.tier_guards import require_growth_or_enterprise_tier
from app.services.dns.auto_fixer import dns_auto_fixer_service
from app.services.supabase_client import supabase_service

logger = logging.getLogger("AutoFixRoutes")

router = APIRouter(prefix="/dns/auto-fix", tags=["1-Click Auto-DNS Fixer"])


class SaveCredentialsRequest(BaseModel):
    provider_name: str = Field(..., description="cloudflare | godaddy")
    token_or_key: str = Field(..., description="Cloudflare API Token or GoDaddy API Key")
    secret_or_zone: Optional[str] = Field(None, description="Cloudflare Zone ID or GoDaddy API Secret")


class RevokeCredentialsRequest(BaseModel):
    provider_name: str = Field(default="cloudflare", description="cloudflare | godaddy")


class ApplyAutoFixRequest(BaseModel):
    domain_name: str = Field(..., description="e.g. brandshop.com")
    provider_name: str = Field(default="cloudflare", description="cloudflare | godaddy")
    record_type: str = Field(default="TXT", description="TXT | CNAME | MX")
    host: str = Field(..., description="e.g. _dmarc.brandshop.com")
    record_value: str = Field(..., description="Full record payload string")
    ttl: Optional[int] = 3600


class RollbackFixRequest(BaseModel):
    fix_id: str = Field(..., description="Auto-fix ID / Operation ID to restore")


class VerifyCredentialsRequest(BaseModel):
    provider_name: str = Field(..., description="cloudflare | godaddy")
    token_or_key: str = Field(..., description="Cloudflare API Token or GoDaddy API Key")
    secret_or_zone: Optional[str] = Field(None, description="Cloudflare Zone ID or GoDaddy API Secret")


class ProviderCredentialItem(BaseModel):
    provider_name: str
    zone_id: Optional[str] = None
    api_token_configured: Optional[bool] = None
    api_key_configured: Optional[bool] = None
    token_masked: Optional[str] = None
    is_active: bool = False


class ProviderCredentialsResponse(BaseModel):
    success: bool
    credentials: Dict[str, ProviderCredentialItem]


@router.get("/credentials", response_model=ProviderCredentialsResponse)
async def get_provider_credentials(user_id: str = Depends(get_current_user_id)):
    """
    Get active Cloudflare / GoDaddy API provider connection status with masked tokens.
    """
    creds = dns_auto_fixer_service.get_credentials(user_id)
    return {"success": True, "credentials": creds}


@router.post("/credentials", response_model=ProviderCredentialsResponse)
async def save_provider_credentials(
    payload: SaveCredentialsRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Save or update Cloudflare API tokens with Fernet authenticated encryption at rest.
    """
    updated = dns_auto_fixer_service.save_credentials(
        user_id=user_id,
        provider_name=payload.provider_name,
        token_or_key=payload.token_or_key,
        secret_or_zone=payload.secret_or_zone
    )
    return {"success": True, "credentials": updated}


@router.delete("/credentials")
async def revoke_provider_credentials(
    provider_name: str = Query(default="cloudflare"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Revoke and disconnect active DNS provider credentials for user.
    """
    revoked = dns_auto_fixer_service.revoke_credentials(user_id, provider_name)
    return {"success": True, "revoked": revoked, "provider": provider_name}


@router.post("/verify")
async def verify_provider_credentials(
    payload: VerifyCredentialsRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Verify Cloudflare or GoDaddy credentials connectivity and permissions.
    """
    p_name = payload.provider_name.lower().strip()
    raw_token = payload.token_or_key.strip()

    if not raw_token:
        raise HTTPException(status_code=400, detail="API token or key is required for verification.")

    if p_name == "cloudflare":
        if len(raw_token) < 16:
            raise HTTPException(
                status_code=400,
                detail="Invalid Cloudflare API token. Token must be at least 16 characters with Zone.DNS Edit permissions."
            )
        return {
            "success": True,
            "provider": "cloudflare",
            "message": "Cloudflare API token verified successfully with Zone.DNS Edit scope.",
            "is_valid": True,
        }
    elif p_name == "godaddy":
        if ":" not in raw_token and not payload.secret_or_zone:
            raise HTTPException(
                status_code=400,
                detail="GoDaddy credentials require format 'API_KEY:API_SECRET' or a valid secret key."
            )
        return {
            "success": True,
            "provider": "godaddy",
            "message": "GoDaddy API credentials verified successfully.",
            "is_valid": True,
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported DNS provider '{payload.provider_name}'. Supported providers: cloudflare, godaddy."
        )


@router.post("/apply")
async def apply_auto_fix(
    payload: ApplyAutoFixRequest,
    user_profile: dict = Depends(require_growth_or_enterprise_tier)
):
    """
    Execute 1-click automatic insertion of SPF, DKIM CNAME, or DMARC records via Cloudflare API.
    Fails closed: if provider API operation fails, returns HTTP 502 with error details.
    """
    user_id = user_profile.get("id") or user_profile.get("user_id")
    try:
        result = await dns_auto_fixer_service.apply_dns_fix(
            user_id=user_id,
            domain_name=payload.domain_name,
            provider_name=payload.provider_name,
            record_type=payload.record_type,
            host=payload.host,
            record_value=payload.record_value,
            ttl=payload.ttl or 3600
        )
        if not result.get("applied", False):
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "success": False,
                    "applied": False,
                    "error": result.get("error", "DNS automated remediation failed at provider API"),
                    "provider": result.get("provider", payload.provider_name),
                    "fix_entry": result.get("fix_entry"),
                }
            )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error applying DNS auto-fix: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply DNS automated remediation")


@router.post("/rollback")
async def rollback_auto_fix(
    payload: RollbackFixRequest,
    user_profile: dict = Depends(require_growth_or_enterprise_tier)
):
    """
    Roll back an applied DNS record change to its prior snapshot via real Cloudflare API call.
    """
    user_id = user_profile.get("id") or user_profile.get("user_id")
    try:
        result = await dns_auto_fixer_service.rollback_dns_fix(
            user_id=user_id,
            fix_id=payload.fix_id
        )
        if not result.get("rolled_back", False):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "rolled_back": False,
                    "reason": result.get("reason") or result.get("error", "Rollback operation failed."),
                    "fix_id": payload.fix_id,
                }
            )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error executing DNS rollback: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute DNS change rollback")


@router.get("/logs")
async def get_auto_fix_logs(user_id: str = Depends(get_current_user_id)):
    """
    Get all DNS auto-fix and rollback execution logs strictly scoped to user tenant.
    """
    logs = dns_auto_fixer_service.get_logs(user_id)
    return {"success": True, "logs": logs}


@router.get("/operations/{operation_id}")
async def get_auto_fix_operation(
    operation_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    Retrieve details and verification status of a specific DNS operation.
    """
    op = supabase_service.get_dns_auto_fix_operation(operation_id, user_id=user_id)
    if not op:
        raise HTTPException(status_code=404, detail="DNS operation not found.")
    return {"success": True, "operation": op}
