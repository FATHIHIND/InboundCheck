"""
InboundCheck - Telegram Alert & Incident Engine REST Router (v1)
================================================================
Endpoints for managing Telegram Bot settings and triggering real-time incident alert dispatches.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.services.failover.omnichannel_service import omnichannel_service

logger = logging.getLogger("TelegramRoutes")

router = APIRouter(prefix="/failover", tags=["Telegram Alert Engine"])


class UpdateTelegramConfigRequest(BaseModel):
    is_enabled: bool = True
    primary_channel: str = Field(default="telegram", description="telegram")
    provider: str = Field(default="telegram_bot_api", description="telegram_bot_api")
    telegram_bot_token: Optional[str] = "7198234891:AAH8Fj90qWz1x9_example"
    telegram_chat_id: Optional[str] = "@inboundcheck_alerts"
    trigger_events: List[str] = ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"]
    store_name: Optional[str] = "BrandShop DTC"


class TriggerTelegramAlertRequest(BaseModel):
    order_id: str = Field(..., description="e.g. #10499")
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = "customer@gmail.com"
    trigger_reason: Optional[str] = "email_spam_detected"
    domain_name: Optional[str] = "brandshop.com"
    store_name: Optional[str] = "BrandShop DTC"


class TelegramTestPingRequest(BaseModel):
    bot_token: Optional[str] = ""
    chat_id: str = Field(..., description="Telegram @channel_handle or numeric chat_id")
    store_name: Optional[str] = "BrandShop DTC"


@router.get("/config")
async def get_failover_config(user_id: str = Depends(get_current_user_id)):
    """
    Get user Telegram alert rules and connected bot settings.
    """
    config = omnichannel_service.get_config(user_id)
    return {"success": True, "config": config}


@router.post("/config")
async def save_failover_config(
    payload: UpdateTelegramConfigRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Save or update Telegram alert engine configuration.
    """
    data = payload.model_dump()
    data["user_id"] = user_id
    updated = omnichannel_service.update_config(user_id, data)
    return {"success": True, "config": updated}


@router.post("/dispatch")
async def trigger_failover_dispatch(
    payload: TriggerTelegramAlertRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Trigger instant rich Telegram alert when an email fails or lands in spam.
    """
    try:
        res = await omnichannel_service.trigger_failover_dispatch(
            user_id=user_id,
            order_id=payload.order_id,
            customer_phone=payload.customer_phone,
            customer_email=payload.customer_email,
            trigger_reason=payload.trigger_reason or "email_spam_detected",
            domain_name=payload.domain_name or "brandshop.com",
            store_name=payload.store_name or "BrandShop DTC"
        )
        return {"success": True, **res}
    except Exception as e:
        logger.error(f"Error executing Telegram dispatch: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute incident alert dispatch")


@router.post("/test-ping")
async def send_test_telegram_ping(
    payload: TelegramTestPingRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Send an immediate test alert to verify Telegram bot connectivity.
    """
    try:
        res = await omnichannel_service.send_test_ping(
            bot_token=payload.bot_token or "",
            chat_id=payload.chat_id,
            store_name=payload.store_name or "BrandShop DTC"
        )
        return {"success": True, "ping_result": res}
    except Exception as e:
        logger.error(f"Error sending test Telegram alert: {e}")
        raise HTTPException(status_code=500, detail="Failed to send test Telegram alert")


@router.get("/logs")
async def get_failover_logs(user_id: str = Depends(get_current_user_id)):
    """
    Get recent Telegram alert incident audit logs.
    """
    logs = omnichannel_service.get_logs(user_id)
    return {"success": True, "logs": logs}
