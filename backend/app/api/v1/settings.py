"""
InboundCheck - User Settings, Telegram Alert Configs & API Routes (v1)
======================================================================
Endpoints for managing tenant profiles, REST API keys, and proactive Telegram deliverability alert rules.
Enforces fail-closed database reliability, Fernet credential encryption, and zero plaintext secret exposure.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import secrets
import logging

from app.core.security import get_current_user_id
from app.core.encryption import (
    encrypt_credential,
    mask_credential,
    safe_decrypt_credential,
)
from app.core.env_guard import sanitize_exception
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.failover.omnichannel_service import omnichannel_service

logger = logging.getLogger("SettingsRoutes")

router = APIRouter(prefix="/settings", tags=["Settings & Alerts"])

# In-memory storage fallback strictly for local development and automated testing
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
    if "plan_tier" not in profile_copy:
        profile_copy["plan_tier"] = (
            profile_copy.get("subscription_tier")
            or profile_copy.get("tier")
            or "growth"
        )
    return profile_copy


def _format_alert_config_response(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format alert configuration for client API response.
    Never exposes raw ciphertext or plaintext secrets.
    Replaces credentials with masked indicators and boolean configured flags.
    """
    config = dict(raw_config)

    # 1. Telegram Bot Token Masking
    raw_tg = config.get("telegram_bot_token")
    if raw_tg:
        decrypted_tg = safe_decrypt_credential(raw_tg)
        if decrypted_tg:
            config["telegram_bot_token"] = mask_credential(decrypted_tg)
            config["telegram_bot_token_configured"] = True
        else:
            config["telegram_bot_token"] = "••••••••••••"
            config["telegram_bot_token_configured"] = True
    else:
        config["telegram_bot_token"] = None
        config["telegram_bot_token_configured"] = False

    # 2. Slack Webhook URL Masking
    raw_slack = config.get("slack_webhook_url")
    if raw_slack:
        decrypted_slack = safe_decrypt_credential(raw_slack)
        if decrypted_slack:
            config["slack_webhook_url"] = mask_credential(decrypted_slack)
            config["slack_webhook_url_configured"] = True
        else:
            config["slack_webhook_url"] = "••••••••••••"
            config["slack_webhook_url_configured"] = True
    else:
        config["slack_webhook_url"] = None
        config["slack_webhook_url_configured"] = False

    return config


def _default_alert_config(user_id: str) -> Dict[str, Any]:
    """Clean, unconfigured default alert configuration without mock credentials."""
    return {
        "user_id": user_id,
        "alert_on_score_drop": True,
        "score_threshold": 75,
        "alert_on_dmarc_change": True,
        "alert_on_spf_error": True,
        "alert_on_dkim_fail": True,
        "slack_webhook_url": None,
        "slack_webhook_url_configured": False,
        "telegram_bot_token": None,
        "telegram_bot_token_configured": False,
        "telegram_chat_id": None,
        "email_notifications": True,
    }


@router.get("/profile", response_model=ProfileResponse)
async def get_user_profile(user_id: str = Depends(get_current_user_id)):
    """
    Get authenticated user profile details with masked API key.
    Fails closed with HTTP 503 on database unavailability in production or staging.
    """
    is_fallback_allowed = supabase_service._allow_in_memory_fallback()

    try:
        profile = supabase_service.get_user_profile(user_id)
        if profile:
            return {"success": True, "profile": _format_profile_response(profile)}
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found",
            )
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading profile from Supabase: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )

    # Local development fallback
    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {
            "id": user_id,
            "full_name": "Dev User",
            "email": f"{user_id}@store.com",
            "company_name": "Development Brand",
            "plan_tier": "growth",
            "api_key": f"ic_live_{secrets.token_hex(16)}",
        }

    return {"success": True, "profile": _format_profile_response(_mock_profiles[user_id])}


@router.put("/profile", response_model=ProfileResponse)
async def update_user_profile(
    payload: UpdateProfileRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Update authenticated user profile and company metadata with masked API key in response.
    Fails closed with HTTP 503 on database failure in production or staging.
    """
    is_fallback_allowed = supabase_service._allow_in_memory_fallback()
    updates = {
        "full_name": payload.full_name,
        "email": payload.email,
        "company_name": payload.company_name,
    }

    try:
        updated = supabase_service.update_user_profile(user_id, updates)
        if updated:
            return {"success": True, "profile": _format_profile_response(updated)}
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile in Supabase: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )

    # Local development fallback
    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {
            "id": user_id,
            "plan_tier": "growth",
            "api_key": f"ic_live_{secrets.token_hex(16)}",
        }
    _mock_profiles[user_id].update(updates)
    return {"success": True, "profile": _format_profile_response(_mock_profiles[user_id])}


@router.post("/api-key/regenerate", response_model=RegenerateApiKeyResponse)
@router.post("/regenerate-key", response_model=RegenerateApiKeyResponse)
async def regenerate_api_key(user_id: str = Depends(get_current_user_id)):
    """
    Generate and persist a new 48-character REST API key, returning masked key.
    Fails closed with HTTP 503 on database failure in production or staging.
    """
    is_fallback_allowed = supabase_service._allow_in_memory_fallback()
    new_key = f"ic_live_{secrets.token_hex(16)}"
    masked_key = mask_api_key(new_key)

    try:
        updated = supabase_service.update_user_profile(user_id, {"api_key": new_key})
        if updated:
            return {"success": True, "api_key": masked_key, "api_key_masked": masked_key}
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating api_key in Supabase: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )

    # Local development fallback
    if user_id not in _mock_profiles:
        _mock_profiles[user_id] = {"id": user_id, "plan_tier": "growth"}
    _mock_profiles[user_id]["api_key"] = new_key
    return {"success": True, "api_key": masked_key, "api_key_masked": masked_key}


@router.get("/alerts")
async def get_alert_config(user_id: str = Depends(get_current_user_id)):
    """
    Get deliverability notification rules and alert threshold settings with masked credentials.
    Fails closed with HTTP 503 on database failure in production or staging.
    """
    is_fallback_allowed = supabase_service._allow_in_memory_fallback()

    try:
        config = supabase_service.get_alert_config(user_id)
        if config:
            return {"success": True, "config": _format_alert_config_response(config)}
        if not is_fallback_allowed:
            # User has no custom config yet: return clean tenant default
            return {"success": True, "config": _format_alert_config_response(_default_alert_config(user_id))}
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching alert configs from Supabase: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )

    # Local development fallback
    if user_id not in _mock_alert_configs:
        _mock_alert_configs[user_id] = _default_alert_config(user_id)

    return {"success": True, "config": _format_alert_config_response(_mock_alert_configs[user_id])}


@router.post("/alerts")
@router.put("/alerts")
async def save_alert_config(
    payload: AlertConfigRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Save or update deliverability notification rules, encrypting tokens at rest and masking in responses.
    Preserves existing credentials when omitted or unchanged.
    Fails closed with HTTP 503 on database failure in production or staging.
    """
    is_fallback_allowed = supabase_service._allow_in_memory_fallback()

    # 1. Fetch existing config to preserve credentials if omitted or masked
    existing_config = None
    try:
        existing_config = supabase_service.get_alert_config(user_id)
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except Exception as e:
        logger.error(f"Error reading existing alert config: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )

    if not existing_config and is_fallback_allowed:
        existing_config = _mock_alert_configs.get(user_id)

    # 2. Process payload and encrypt new credentials
    data = payload.model_dump()
    data["user_id"] = user_id

    # Handle telegram_bot_token: encrypt if new plaintext; preserve if omitted or masked
    new_tg = payload.telegram_bot_token
    if new_tg is not None and str(new_tg).strip() != "" and not str(new_tg).strip().startswith("•"):
        data["telegram_bot_token"] = encrypt_credential(str(new_tg).strip())
    else:
        data["telegram_bot_token"] = existing_config.get("telegram_bot_token") if existing_config else None

    # Handle slack_webhook_url: encrypt if new plaintext; preserve if omitted or masked
    new_slack = payload.slack_webhook_url
    if new_slack is not None and str(new_slack).strip() != "" and not str(new_slack).strip().startswith("•"):
        data["slack_webhook_url"] = encrypt_credential(str(new_slack).strip())
    else:
        data["slack_webhook_url"] = existing_config.get("slack_webhook_url") if existing_config else None

    # 3. Save to database or in-memory repository
    saved_config = None
    try:
        saved_config = supabase_service.save_alert_config(user_id, data)
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except Exception as e:
        logger.error(f"Error saving alert config in Supabase: {e}")
        if not is_fallback_allowed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )
        _mock_alert_configs[user_id] = data
        saved_config = data

    if not saved_config:
        _mock_alert_configs[user_id] = data
        saved_config = data

    # 4. Synchronize with failover engine
    omnichannel_service.update_config(user_id, {
        "telegram_bot_token": saved_config.get("telegram_bot_token"),
        "telegram_chat_id": payload.telegram_chat_id,
        "is_enabled": True,
    })

    return {"success": True, "config": _format_alert_config_response(saved_config)}


@router.post("/telegram/test")
async def send_test_telegram_alert(
    payload: TelegramTestRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Send a live rich Markdown test alert ping to the configured Telegram chat/channel.
    Uses stored decrypted token if token is omitted or masked in request.
    """
    raw_token = (payload.bot_token or "").strip()
    if not raw_token or raw_token.startswith("•"):
        decrypted_token = omnichannel_service.get_decrypted_token(user_id)
        if not decrypted_token:
            return {
                "success": False,
                "error": "Telegram Bot Token is not configured. Please configure your bot token in alert settings first.",
                "telegram_response": {},
            }
        token_to_use = decrypted_token
    else:
        token_to_use = raw_token

    try:
        res = await omnichannel_service.send_test_ping(
            bot_token=token_to_use,
            chat_id=payload.chat_id,
            store_name=payload.store_name or "BrandShop DTC",
        )
        if not res.get("success", False):
            return {
                "success": False,
                "error": res.get("error", "Telegram test dispatch failed"),
                "telegram_response": res,
            }
        return {
            "success": True,
            "message": "Test alert sent to Telegram chat",
            "telegram_response": res,
        }
    except Exception as e:
        safe_err = sanitize_exception(e)
        logger.error(f"Telegram test ping error: {safe_err}")
        return {
            "success": False,
            "error": "Telegram test dispatch failed",
            "telegram_response": {},
        }
