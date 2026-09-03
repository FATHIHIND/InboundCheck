"""
InboundCheck - Telegram Alert Service
=====================================
Direct Telegram Bot API notification engine and failure recovery.
"""
from typing import Dict, Any, Optional, List
import logging
from app.services.failover.omnichannel_service import (
    TelegramAlertService,
    telegram_alert_service,
    omnichannel_service,
)

logger = logging.getLogger("TelegramService")


async def send_telegram_alert(
    bot_token: str,
    chat_id: str,
    text: str
) -> Dict[str, Any]:
    """
    Directly dispatch alert message to Telegram Bot API.
    Fails closed: returns {"success": False, "error": ...} on HTTP errors or network exceptions.
    """
    return await telegram_alert_service.send_telegram_alert(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text
    )


__all__ = [
    "TelegramAlertService",
    "telegram_alert_service",
    "omnichannel_service",
    "send_telegram_alert"
]
