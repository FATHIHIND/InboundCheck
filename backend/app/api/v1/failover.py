"""
InboundCheck - Telegram Alert & Incident Engine REST Router (v1)
================================================================
Endpoints for managing Telegram Bot settings and triggering real-time incident alert dispatches.
Enforces fail-closed database reliability, credential envelope encryption, and masked client responses.
"""

from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.core.env_guard import sanitize_exception
from app.services.supabase_client import supabase_service, DatabaseUnavailableError
from app.services.failover.omnichannel_service import omnichannel_service

logger = logging.getLogger("TelegramRoutes")

router = APIRouter(prefix="/failover", tags=["Telegram Alert Engine"])


class UpdateTelegramConfigRequest(BaseModel):
    is_enabled: bool = True
    primary_channel: str = Field(default="telegram", description="telegram")
    provider: str = Field(default="telegram", description="telegram")
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    trigger_events: List[str] = ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"]
    store_name: Optional[str] = "BrandShop DTC"


class TriggerTelegramAlertRequest(BaseModel):
    order_id: str = Field(..., description="e.g. #10499")
    trigger_reason: Optional[str] = "email_spam_detected"
    domain_name: Optional[str] = "brandshop.com"
    store_name: Optional[str] = "BrandShop DTC"
    idempotency_key: Optional[str] = None


class TelegramTestPingRequest(BaseModel):
    bot_token: Optional[str] = ""
    chat_id: str = Field(..., description="Telegram @channel_handle or numeric chat_id")
    store_name: Optional[str] = "BrandShop DTC"


@router.get("/config")
async def get_failover_config(user_id: str = Depends(get_current_user_id)):
    """
    Get user Telegram alert rules and connected bot settings with masked credentials.
    Fails closed with HTTP 503 on database unavailability in production or staging.
    """
    try:
        config = omnichannel_service.get_config(user_id)
        masked_config = omnichannel_service.format_config_for_client(config)
        return {"success": True, "config": masked_config}
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching failover config: {e}")
        from app.services.supabase_client import supabase_service
        if not supabase_service._allow_in_memory_fallback():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )
        config = omnichannel_service.get_config(user_id)
        return {"success": True, "config": omnichannel_service.format_config_for_client(config)}


@router.post("/config")
async def save_failover_config(
    payload: UpdateTelegramConfigRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Save or update Telegram alert engine configuration with credential encryption and masking.
    Fails closed with HTTP 503 on database unavailability in production or staging.
    """
    data = payload.model_dump()
    data["user_id"] = user_id
    try:
        updated = omnichannel_service.update_config(user_id, data)
        masked = omnichannel_service.format_config_for_client(updated)
        return {"success": True, "config": masked}
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving failover config: {e}")
        from app.services.supabase_client import supabase_service
        if not supabase_service._allow_in_memory_fallback():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service temporarily unavailable",
            )
        updated = omnichannel_service.update_config(user_id, data)
        return {"success": True, "config": omnichannel_service.format_config_for_client(updated)}


@router.post("/dispatch")
async def trigger_failover_dispatch(
    payload: TriggerTelegramAlertRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_header: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """
    Durable Outbox Incident Alert Dispatch:
    Persists incident payload to durable notification_outbox before attempting outbound HTTP.
    Returns HTTP 200/202 with job_id and queued status without synchronous external Telegram dependency.
    """
    raw_key = (idempotency_header or payload.idempotency_key or "").strip()
    if not raw_key:
        clean_ord = str(payload.order_id or "unknown").strip()
        clean_rsn = str(payload.trigger_reason or "email_spam_detected").strip()
        raw_key = f"dispatch_{user_id}_{clean_ord}_{clean_rsn}"

    try:
        sanitized_payload = {
            "order_id": str(payload.order_id or "unknown").strip(),
            "trigger_reason": str(payload.trigger_reason or "email_spam_detected").strip(),
            "domain_name": str(payload.domain_name or "brandshop.com").strip().lower(),
            "store_name": str(payload.store_name or "BrandShop DTC").strip(),
        }

        outbox_record = supabase_service.enqueue_notification_outbox(
            user_id=user_id,
            channel="telegram",
            idempotency_key=raw_key,
            payload=sanitized_payload,
            max_attempts=5,
        )

        return {
            "success": True,
            "status": outbox_record.get("status", "queued"),
            "job_id": str(outbox_record.get("id")),
            "idempotency_key": raw_key,
            "idempotent": bool(outbox_record.get("idempotent", False)),
        }
    except DatabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service temporarily unavailable",
        )
    except Exception as e:
        safe_err = sanitize_exception(e)
        logger.error(f"Error enqueuing notification outbox dispatch: {safe_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue incident alert dispatch",
        )


@router.get("/health")
async def get_failover_health_metrics(
    user_id: str = Depends(get_current_user_id),
):
    """
    Get real-time delivery and notification outbox health telemetry.
    """
    metrics = supabase_service.get_notification_health_metrics()
    return {"success": True, "metrics": metrics}


@router.post("/test-ping")
async def send_test_telegram_ping(
    payload: TelegramTestPingRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Send an immediate test alert to verify Telegram bot connectivity.
    Uses stored decrypted token if omitted or masked.
    """
    raw_token = (payload.bot_token or "").strip()
    if not raw_token or raw_token.startswith("•"):
        decrypted_token = omnichannel_service.get_decrypted_token(user_id)
        if not decrypted_token:
            return {
                "success": False,
                "ping_result": {
                    "success": False,
                    "error": "Telegram Bot Token is not configured. Please configure your bot token first.",
                },
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
        return {"success": True, "ping_result": res}
    except Exception as e:
        safe_err = sanitize_exception(e)
        logger.error(f"Error sending test Telegram alert: {safe_err}")
        return {
            "success": False,
            "ping_result": {
                "success": False,
                "error": "Failed to send test Telegram alert",
            },
        }


@router.get("/logs")
async def get_failover_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """
    Get recent Telegram alert incident audit logs from public.failover_logs.
    """
    logs = omnichannel_service.get_logs(user_id=user_id, limit=limit, offset=offset)
    return {"success": True, "logs": logs}
