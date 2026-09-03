"""
InboundCheck - 1-Click Auto-DNS Fixer REST Router (v1)
======================================================
Endpoints for managing Cloudflare/GoDaddy API credentials, 1-click DNS record auto-insertion, and rollback operations.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.services.dns.auto_fixer import dns_auto_fixer_service

logger = logging.getLogger("AutoFixRoutes")

router = APIRouter(prefix="/dns/auto-fix", tags=["1-Click Auto-DNS Fixer"])


class SaveCredentialsRequest(BaseModel):
    provider_name: str = Field(..., description="cloudflare | godaddy")
    token_or_key: str = Field(..., description="Cloudflare API Token or GoDaddy API Key")
    secret_or_zone: Optional[str] = Field(None, description="Cloudflare Zone ID or GoDaddy API Secret")


class ApplyAutoFixRequest(BaseModel):
    domain_name: str = Field(..., description="e.g. brandshop.com")
    provider_name: str = Field(default="cloudflare", description="cloudflare | godaddy")
    record_type: str = Field(default="TXT", description="TXT | CNAME")
    host: str = Field(..., description="e.g. _dmarc.brandshop.com")
    record_value: str = Field(..., description="Full record payload string")
    ttl: Optional[int] = 3600


class RollbackFixRequest(BaseModel):
    fix_id: str = Field(..., description="Auto-fix ID to restore")


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
    Save or update Cloudflare API tokens or GoDaddy API keys.
    """
    updated = dns_auto_fixer_service.save_credentials(
        user_id=user_id,
        provider_name=payload.provider_name,
        token_or_key=payload.token_or_key,
        secret_or_zone=payload.secret_or_zone
    )
    return {"success": True, "credentials": updated}


@router.post("/apply")
async def apply_auto_fix(
    payload: ApplyAutoFixRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Execute 1-click automatic insertion of SPF, DKIM CNAME, or DMARC records via provider API.
    """
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
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error applying DNS auto-fix: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply DNS automated remediation")


@router.post("/rollback")
async def rollback_auto_fix(
    payload: RollbackFixRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Roll back an applied DNS record change to its prior snapshot.
    """
    try:
        result = dns_auto_fixer_service.rollback_dns_fix(
            user_id=user_id,
            fix_id=payload.fix_id
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error executing DNS rollback: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute DNS change rollback")


@router.get("/logs")
async def get_auto_fix_logs(user_id: str = Depends(get_current_user_id)):
    """
    Get all DNS auto-fix and rollback execution logs.
    """
    logs = dns_auto_fixer_service.get_logs(user_id)
    return {"success": True, "logs": logs}
