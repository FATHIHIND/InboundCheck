"""
InboundCheck - Telegram Real-Time Alert & Incident Engine
=========================================================
Handles instant Telegram Bot alerts and incident dispatches when email deliverability telemetry
flags spam folder routing, hard bounces, RBL blacklists, or broken DMARC policies.
"""

import re
import uuid
from typing import Dict, Any, List, Optional, Literal, Union
from urllib.parse import quote_plus
import httpx
import logging
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("TelegramAlertEngine")


class TelegramIncidentContext(BaseModel):
    delivery_failure_event_id: str
    user_id: str
    order_id: Optional[str] = None
    domain_name: Optional[str] = None
    store_name: Optional[str] = None
    esp_provider: str
    failure_type: str
    failure_reason: Optional[str] = None
    recommended_dns_action: str = "Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan."
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TelegramDispatchResult(BaseModel):
    success: bool
    provider: Literal["telegram"] = "telegram"
    provider_status: Literal["delivered", "failed"]
    telegram_message_id: Optional[str] = None
    target_chat_id: Optional[str] = None
    error_message: Optional[str] = None

    # Dict-like compatibility for callers expecting dict or .get("status")
    def __getitem__(self, item: str) -> Any:
        if item == "status":
            return self.provider_status
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        if item == "status":
            return self.provider_status
        return getattr(self, item, default)


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
        "provider": "telegram",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
        "store_name": "BrandShop DTC"
    }
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
            "provider": "telegram",
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
        _mock_failover_configs[user_id]["provider"] = "telegram"
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

        bot_token = config.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN
        chat_id = config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID

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

        dispatch_status = "delivered" if dispatch_res.get("success") else "failed"

        # Persist to database via repository
        from app.services.supabase_client import supabase_service
        log_record = supabase_service.persist_failover_log(
            user_id=user_id,
            order_id=order_id,
            channel="telegram",
            provider="telegram",
            status=dispatch_status,
            domain_name=domain_name,
            store_name=store_name,
            triggered_reason=trigger_reason,
            target_chat_id=chat_id,
            customer_email=customer_email,
            customer_phone=customer_phone,
            dispatch_payload=dispatch_res,
            error_message=dispatch_res.get("error") if not dispatch_res.get("success") else None,
        )

        return {
            "dispatched": True,
            "channel": "telegram",
            "target_chat_id": chat_id,
            "dispatch_res": dispatch_res,
            "log": log_record
        }

    async def dispatch_alert(
        self,
        incident: Union[TelegramIncidentContext, Dict[str, Any], None] = None,
        **kwargs
    ) -> TelegramDispatchResult:
        """
        Dispatches an actionable delivery incident alert to the merchant's connected Telegram bot/channel.
        Guarantees zero-PII: customer phone, email, and raw payloads are never included.
        """
        if isinstance(incident, TelegramIncidentContext):
            ctx = incident
        elif isinstance(incident, dict):
            ctx = TelegramIncidentContext(**incident)
        elif kwargs:
            uid = kwargs.get("user_id", "demo-user-123")
            ctx = TelegramIncidentContext(
                delivery_failure_event_id=kwargs.get("delivery_failure_event_id") or str(uuid.uuid4()),
                user_id=uid,
                order_id=kwargs.get("order_id"),
                domain_name=kwargs.get("domain_name"),
                store_name=kwargs.get("store_name"),
                esp_provider=kwargs.get("esp_provider") or kwargs.get("channel", "unknown"),
                failure_type=kwargs.get("failure_type") or kwargs.get("reason", "delivery_failure"),
                failure_reason=kwargs.get("failure_reason") or kwargs.get("bounce_reason") or kwargs.get("reason"),
                recommended_dns_action=kwargs.get("recommended_action") or "Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan.",
                occurred_at=datetime.now(timezone.utc),
            )
        else:
            raise ValueError("dispatch_alert requires either an incident context or kwargs")

        config = self.get_config(ctx.user_id)
        if not config.get("is_enabled", True):
            logger.info(f"Telegram alert engine disabled for user {ctx.user_id}")
            return TelegramDispatchResult(
                success=False,
                provider="telegram",
                provider_status="failed",
                telegram_message_id=None,
                target_chat_id=None,
                error_message="Telegram alert engine is disabled in user settings",
            )

        bot_token = config.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN or "7198234891:AAH8Fj90qWz1x9_example"
        chat_id = config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID or "@inboundcheck_alerts"

        if not bot_token or not chat_id:
            logger.warning(f"Telegram credentials unconfigured for user {ctx.user_id}; alert skipped.")
            return TelegramDispatchResult(
                success=False,
                provider="telegram",
                provider_status="failed",
                telegram_message_id=None,
                target_chat_id=None,
                error_message="Telegram Bot Token and Chat ID must be configured in settings",
            )

        store_str = ctx.store_name or "Shopify Store"
        domain_str = ctx.domain_name or "store.com"
        order_str = ctx.order_id or "N/A"
        esp_str = ctx.esp_provider.upper()
        failure_str = ctx.failure_type.upper()
        reason_str = ctx.failure_reason or "Permanent delivery rejection"
        encoded_domain = quote_plus(domain_str)

        alert_text = (
            "🚨 *INBOUNDCHECK DELIVERY INCIDENT*\n\n"
            f"Store: {store_str}\n"
            f"Domain: `{domain_str}`\n"
            f"Order: `{order_str}`\n"
            f"ESP: {esp_str}\n"
            f"Failure: {failure_str}\n"
            f"Reason: {reason_str}\n"
            f"Recommended action: {ctx.recommended_dns_action}\n\n"
            f"[Open DNS Inspector](/dashboard/inspector?domain={encoded_domain})"
        )

        send_res = await self.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text=alert_text,
        )

        if send_res.get("success"):
            data = send_res.get("data", {})
            tg_msg_id = str(data.get("result", {}).get("message_id") or data.get("message_id") or "")
            return TelegramDispatchResult(
                success=True,
                provider="telegram",
                provider_status="delivered",
                telegram_message_id=tg_msg_id or None,
                target_chat_id=chat_id,
                error_message=None,
            )
        else:
            return TelegramDispatchResult(
                success=False,
                provider="telegram",
                provider_status="failed",
                telegram_message_id=None,
                target_chat_id=chat_id,
                error_message=send_res.get("error") or "Failed to deliver Telegram alert",
            )

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

    def get_logs(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch Telegram alert dispatch logs from database/repository."""
        from app.services.supabase_client import supabase_service
        logs = supabase_service.get_failover_logs(user_id=user_id, limit=limit, offset=offset)
        return logs


omnichannel_service = TelegramAlertService()
telegram_alert_service = omnichannel_service
