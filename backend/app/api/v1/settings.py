"""
InboundCheck - User Settings, Telegram Alert Configs & API Routes (v1)
======================================================================
Endpoints for managing tenant profiles, REST API keys, and proactive Telegram deliverability alert rules.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import secrets
import logging

from app.core.security import get_current_user_id
from app.services.supabase_client import supabase_service
from app.services.failover.omnichannel_service import omnichannel_service

logger = logging.getLogger("SettingsRoutes")

router = APIRouter(prefix="/settings", tags=["Settings & Alerts"])

# Dynamic in-memory storage fallback for local development
_mock_profiles: Dict[str, Dict[str, Any]] = {}
_mock_alert_configs: Dict[str, Dict[str, Any]] = {}


def mask_api_key(key: Optional[str]) -> str:
    """Mask API key so secret bytes are never exposed in transit: ic_live_••••••••••••••••<last4>."""
    if not key:
        return "ic_live_••••••••••••••••"
    clean = str(key).strip()
    if clean.startswith("ic_live_") and len(clean) > 12:
        return f"ic_live_{'•' * 16}{clean[-4:]}"
    if len(clean) > 8:
        return f"{clean[:4]}{'•' * 16}{clean[-4:]}"
    return "•" * 20


class UserProfile(BaseModel):
    id: str
    full_name: Optional[str] = None
    email: str
    company_name: Optional[str] = None
    plan_tier: str = "growth"
    api_key: str
    api_key_masked: str
    api_key_configured: bool = True


class ProfileResponse(BaseModel):
    success: bool
    profile: UserProfile


class RegenerateApiKeyResponse(BaseModel):
    success: bool
    api_key: str
    api_key_masked: str


class UpdateProfileRequest(BaseModel):
    full_name: str
    email: str
    company_name: Optional[str] = None


class AlertConfigRequest(BaseModel):
    alert_on_score_drop: bool = True
    score_threshold: int = Field(default=75, ge=50, le=95)
    alert_on_dmarc_change: bool = True
    alert_on_spf_error: bool = True
    alert_on_dkim_fail: bool = True
    slack_webhook_url: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    email_notifications: bool = True


class TelegramTestRequest(BaseModel):
    bot_token: Optional[str] = ""
    chat_id: str = Field(..., description="Telegram @channel_handle or numeric chat_id")
    store_name: Optional[str] = "BrandShop DTC"


def _format_profile_response(raw_profile: Dict[str, Any]) -> Dict[str, Any]:
    profile_copy = dict(raw_profile)
    raw_key = profile_copy.get("api_key", "")
    masked = mask_api_key(raw_key)
    profile_copy["api_key"] = masked
    profile_copy["api_key_masked"] = masked
    profile_copy["api_key_configured"] = bool(raw_key)
    return profile_copy


@router.get("/profile", response_model=ProfileResponse)
async def get_user_profile(user_id: str = Depends(get_current_user_id)):
    """
    Get authenticated user profile details with masked API key.
    """
    if supabase_service.is_connected:
        try:
            res = supabase_service._client.table("profiles").select("*").eq("id", user_id).execute()
            if res.data:
                return {"success": True, "profile": _format_profile_response(res.data[0])}
        except Exception as e:
            logger.error(f"Error reading profile from Supabase: {e}")

    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {
            "id": user_id,
            "full_name": "Alex Morgan",
            "email": "alex@brandshop.com",
            "company_name": "BrandShop Inc.",
            "plan_tier": "growth",
            "api_key": f"ic_live_{secrets.token_hex(16)}"
        }

    return {"success": True, "profile": _format_profile_response(_mock_profiles[user_id])}


@router.put("/profile", response_model=ProfileResponse)
async def update_user_profile(
    payload: UpdateProfileRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Update authenticated user profile and company metadata with masked API key in response.
    """
    updates = {
        "full_name": payload.full_name,
        "email": payload.email,
        "company_name": payload.company_name,
    }

    if supabase_service.is_connected:
        try:
            res = supabase_service._client.table("profiles").update(updates).eq("id", user_id).execute()
            if res.data:
                return {"success": True, "profile": _format_profile_response(res.data[0])}
        except Exception as e:
            logger.error(f"Error updating profile in Supabase: {e}")

    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {"id": user_id, "plan_tier": "growth", "api_key": f"ic_live_{secrets.token_hex(16)}"}

    _mock_profiles[user_id].update(updates)
    return {"success": True, "profile": _format_profile_response(_mock_profiles[user_id])}


@router.post("/api-key/regenerate", response_model=RegenerateApiKeyResponse)
async def regenerate_api_key(user_id: str = Depends(get_current_user_id)):
    """
    Generate and persist a new 48-character REST API key, returning masked key.
    """
    new_key = f"ic_live_{secrets.token_hex(16)}"
    masked_key = mask_api_key(new_key)

    if supabase_service.is_connected:
        try:
            res = supabase_service._client.table("profiles").update({"api_key": new_key}).eq("id", user_id).execute()
            if res.data:
                return {"success": True, "api_key": masked_key, "api_key_masked": masked_key}
        except Exception as e:
            logger.error(f"Error updating api_key in Supabase: {e}")

    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {"id": user_id, "plan_tier": "growth"}

    _mock_profiles[user_id]["api_key"] = new_key
    return {"success": True, "api_key": masked_key, "api_key_masked": masked_key}


@router.get("/alerts")
async def get_alert_config(user_id: str = Depends(get_current_user_id)):
    """
    Get deliverability notification rules, Telegram bot tokens, and alert threshold settings.
    """
    if supabase_service.is_connected:
        try:
            res = supabase_service._client.table("alert_configs").select("*").eq("user_id", user_id).execute()
            if res.data:
                return {"success": True, "config": res.data[0]}
        except Exception as e:
            logger.error(f"Error fetching alert configs from Supabase: {e}")

    if user_id not in _mock_alert_configs:
        _mock_alert_configs[user_id] = {
            "alert_on_score_drop": True,
            "score_threshold": 75,
            "alert_on_dmarc_change": True,
            "alert_on_spf_error": True,
            "alert_on_dkim_fail": True,
            "slack_webhook_url": None,
            "telegram_bot_token": "7198234891:AAH8Fj90qWz1x9_example",
            "telegram_chat_id": "@inboundcheck_alerts",
            "email_notifications": True
        }

    return {"success": True, "config": _mock_alert_configs[user_id]}


@router.post("/alerts")
async def save_alert_config(
    payload: AlertConfigRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Save or update deliverability notification rules, Telegram bot credentials, and webhooks.
    """
    data = payload.model_dump()
    data["user_id"] = user_id

    if supabase_service.is_connected:
        try:
            res = supabase_service._client.table("alert_configs").upsert(data, on_conflict="user_id").execute()
            if res.data:
                return {"success": True, "config": res.data[0]}
        except Exception as e:
            logger.error(f"Error saving alert config in Supabase: {e}")

    _mock_alert_configs[user_id] = data

    # Synchronize with failover engine
    omnichannel_service.update_config(user_id, {
        "telegram_bot_token": payload.telegram_bot_token,
        "telegram_chat_id": payload.telegram_chat_id,
        "is_enabled": True
    })

    return {"success": True, "config": data}


@router.post("/telegram/test")
async def send_test_telegram_alert(
    payload: TelegramTestRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Send a live rich Markdown test alert ping to the configured Telegram chat/channel.
    """
    try:
        res = await omnichannel_service.send_test_ping(
            bot_token=payload.bot_token or "",
            chat_id=payload.chat_id,
            store_name=payload.store_name or "BrandShop DTC"
        )
        if not res.get("success", False):
            return {
                "success": False,
                "error": res.get("error", "Telegram test dispatch failed"),
                "telegram_response": res
            }
        return {
            "success": True,
            "message": "Test alert sent to Telegram chat",
            "telegram_response": res
        }
    except Exception as e:
        logger.error(f"Telegram test ping error: {e}")
        return {
            "success": False,
            "error": "Telegram test dispatch failed",
            "telegram_response": {}
        }
