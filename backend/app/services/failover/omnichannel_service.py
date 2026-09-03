"""
InboundCheck - Telegram Real-Time Alert & Incident Engine
=========================================================
Handles instant Telegram Bot alerts and incident dispatches when email deliverability telemetry
flags spam folder routing, hard bounces, RBL blacklists, or broken DMARC policies.
"""

import re
from typing import Dict, Any, List, Optional
import httpx
import logging
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger("TelegramAlertEngine")


def sanitize_log_message(message: str, token: Optional[str] = None) -> str:
    """Strip Telegram bot tokens, webhook secrets, and authentication credentials from log strings."""
    if not message:
        return ""
    sanitized = str(message)
    # Redact Telegram bot URL token syntax: bot<digits>:<token>
    sanitized = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED_TOKEN]", sanitized)
    # Redact Stripe webhook secrets
    sanitized = re.sub(r"whsec_[A-Za-z0-9]+", "whsec_[REDACTED]", sanitized)
    # Redact Shopify private access tokens
    sanitized = re.sub(r"shpat_[A-Za-z0-9]+", "shpat_[REDACTED]", sanitized)
    # Redact HTTP Authorization Bearer tokens
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", sanitized)
    if token and len(token) > 4:
        sanitized = sanitized.replace(token, "[REDACTED_TOKEN]")
    return sanitized


# In-memory storage fallbacks
_mock_failover_configs: Dict[str, Dict[str, Any]] = {
    "demo-user-123": {
        "is_enabled": True,
        "primary_channel": "telegram",
        "provider": "telegram_bot_api",
        "telegram_bot_token": "7198234891:AAH8Fj90qWz1x9_example",
        "telegram_chat_id": "@inboundcheck_alerts",
        "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
        "store_name": "BrandShop DTC"
    }
}

_mock_failover_logs: Dict[str, List[Dict[str, Any]]] = {
    "demo-user-123": [
        {
            "id": "tg_901",
            "order_id": "#10488",
            "store_name": "BrandShop DTC",
            "target_chat_id": "@inboundcheck_alerts",
            "channel": "telegram",
            "provider": "telegram_bot_api",
            "status": "delivered",
            "triggered_reason": "email_spam_detected",
            "domain_name": "brandshop.com",
            "timestamp": "12 mins ago"
        },
        {
            "id": "tg_902",
            "order_id": "#10482",
            "store_name": "BrandShop DTC",
            "target_chat_id": "@inboundcheck_alerts",
            "channel": "telegram",
            "provider": "telegram_bot_api",
            "status": "delivered",
            "triggered_reason": "hard_bounce",
            "domain_name": "brandshop.com",
            "timestamp": "1 hour ago"
        }
    ]
}


class TelegramAlertService:
    """
    Dedicated Service for instant Telegram Bot Alert Dispatches.
    """

    def get_config(self, user_id: str) -> Dict[str, Any]:
        """Fetch user Telegram alert configuration without multi-tenant bleed."""
        if user_id in _mock_failover_configs:
            return _mock_failover_configs[user_id]
        return {
            "is_enabled": True,
            "primary_channel": "telegram",
            "provider": "telegram_bot_api",
            "telegram_bot_token": settings.TELEGRAM_BOT_TOKEN or "",
            "telegram_chat_id": settings.TELEGRAM_CHAT_ID or "",
            "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
            "store_name": "BrandShop DTC"
        }

    def update_config(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save or update Telegram alert configuration."""
        if user_id not in _mock_failover_configs:
            _mock_failover_configs[user_id] = {}
        _mock_failover_configs[user_id].update(payload)
        _mock_failover_configs[user_id]["primary_channel"] = "telegram"
        _mock_failover_configs[user_id]["provider"] = "telegram_bot_api"
        return _mock_failover_configs[user_id]

    async def send_telegram_alert(
        self,
        bot_token: str,
        chat_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        Directly post message payload to Telegram Bot API.
        Fails closed: returns {"success": False, "error": ...} on HTTP errors or network exceptions.
        Sanitizes all sensitive bot tokens from logs and error messages.
        """
        clean_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        clean_chat_id = chat_id or settings.TELEGRAM_CHAT_ID

        if not clean_token or not clean_chat_id:
            logger.warning("Telegram credentials empty; dispatch rejected.")
            return {"success": False, "simulated": False, "error": "Telegram Bot Token and Chat ID must be configured."}

        try:
            url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(
                    url,
                    json={
                        "chat_id": clean_chat_id,
                        "text": text,
                        "parse_mode": "Markdown"
                    }
                )
                if res.status_code == 200:
                    return {"success": True, "simulated": False, "data": res.json()}
                else:
                    safe_res_text = sanitize_log_message(res.text, clean_token)
                    logger.warning(f"Telegram API responded with {res.status_code}: {safe_res_text}")
                    return {"success": False, "simulated": False, "error": f"Telegram API error ({res.status_code}): {safe_res_text}"}
        except Exception as e:
            safe_err = sanitize_log_message(str(e), clean_token)
            logger.error(f"Error calling Telegram API: {safe_err}")
            return {"success": False, "simulated": False, "error": safe_err}

    async def trigger_failover_dispatch(
        self,
        user_id: str,
        order_id: str,
        customer_phone: Optional[str] = None,
        customer_email: Optional[str] = None,
        trigger_reason: str = "email_spam_detected",
        domain_name: str = "brandshop.com",
        store_name: str = "BrandShop DTC"
    ) -> Dict[str, Any]:
        """
        Trigger instant rich Telegram alert when email delivery or spam routing occurs.
        """
        config = self.get_config(user_id)
        if not config.get("is_enabled", True):
            return {
                "dispatched": False,
                "reason": "Telegram alert engine is disabled in user settings"
            }

        bot_token = config.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN or "7198234891:AAH8Fj90qWz1x9_example"
        chat_id = config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID or "@inboundcheck_alerts"

        # Build Rich Actionable Telegram Alert Message
        alert_text = (
            f"🚨 *INBOUNDCHECK INCIDENT ALERT*\n\n"
            f"🏬 *Store:* {store_name} (`{domain_name}`)\n"
            f"📦 *Order Ref:* `{order_id}`\n"
            f"⚠️ *Incident Type:* `{trigger_reason}`\n"
            f"📬 *Customer Email:* `{customer_email or 'N/A'}`\n"
            f"⏰ *Timestamp:* `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
            f"🔍 *Action Required:* Inspect diagnostic records & RBL posture\n"
            f"👉 [Open InboundCheck Inspector](http://localhost:3000/dashboard/inspector?domain={domain_name})"
        )

        dispatch_res = await self.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text=alert_text
        )

        log_entry = {
            "id": f"tg_{len(_mock_failover_logs.get(user_id, [])) + 900}",
            "order_id": order_id,
            "store_name": store_name,
            "target_chat_id": chat_id,
            "customer_phone": customer_phone or chat_id,
            "customer_email": customer_email or "admin@store.com",
            "channel": "telegram",
            "provider": "telegram_bot_api",
            "status": "delivered",
            "triggered_reason": trigger_reason,
            "domain_name": domain_name,
            "timestamp": "Just now"
        }

        if user_id not in _mock_failover_logs:
            _mock_failover_logs[user_id] = []
        _mock_failover_logs[user_id].insert(0, log_entry)

        return {
            "dispatched": True,
            "channel": "telegram",
            "target_chat_id": chat_id,
            "dispatch_res": dispatch_res,
            "log": log_entry
        }

    async def send_test_ping(
        self,
        bot_token: str,
        chat_id: str,
        store_name: str = "BrandShop DTC"
    ) -> Dict[str, Any]:
        """
        Send an interactive verification ping message to Telegram chat/channel.
        """
        text = (
            f"⚡ *InboundCheck Telegram Alert Engine — Connection Verified*\n\n"
            f"✅ Store: *{store_name}*\n"
            f"📡 Status: *Live Surveillance Active*\n"
            f"🛡️ Trigger Rules: `email_spam` | `hard_bounce` | `rbl_listed` | `dmarc_broken`\n\n"
            f"You will receive instant alerts here whenever deliverability anomalies are detected."
        )
        return await self.send_telegram_alert(bot_token=bot_token, chat_id=chat_id, text=text)

    def get_logs(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch Telegram alert dispatch logs."""
        return _mock_failover_logs.get(user_id, _mock_failover_logs["demo-user-123"])


omnichannel_service = TelegramAlertService()
telegram_alert_service = omnichannel_service
