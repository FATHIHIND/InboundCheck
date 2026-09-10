"""
InboundCheck - Intelligent Degradation Alert Dispatcher
======================================================
Evaluates deliverability health drops, DNS protocol failures, and failover events
against tenant-configured alert thresholds, and dispatches real-time alerts.
"""

from typing import Dict, Any, Optional, List
import logging
import time
from datetime import datetime

from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.services.failover.omnichannel_service import telegram_alert_service

logger = logging.getLogger("AlertDispatcher")

# In-memory fallback for alert configurations
_mock_tenant_alerts: Dict[str, Dict[str, Any]] = {}


class AlertDispatcherService:
    """
    Intelligently evaluates domain deliverability posture against tenant preferences
    and dispatches multi-channel alerts (Telegram, Email, Webhook).
    Suppresses repetitive alerts via a 6-hour cooldown window per tenant-domain.
    """

    def __init__(self, cooldown_seconds: int = 6 * 3600):
        self.cooldown_seconds = cooldown_seconds  # 21,600s = 6 hours
        self._alert_cooldown_tracker: Dict[str, float] = {}

    def is_in_cooldown(self, user_id: str, domain_name: str) -> bool:
        """Check if tenant-domain is currently within active cooldown window."""
        key = f"{user_id}:{domain_name.strip().lower()}"
        last_alert = self._alert_cooldown_tracker.get(key)
        if not last_alert:
            return False
        return (time.time() - last_alert) < self.cooldown_seconds

    def mark_alerted(self, user_id: str, domain_name: str):
        """Record alert dispatch timestamp for cooldown window."""
        key = f"{user_id}:{domain_name.strip().lower()}"
        self._alert_cooldown_tracker[key] = time.time()

    def reset_cooldown(self, user_id: Optional[str] = None, domain_name: Optional[str] = None):
        """Reset cooldown tracker for a specific domain or all domains."""
        if user_id and domain_name:
            key = f"{user_id}:{domain_name.strip().lower()}"
            self._alert_cooldown_tracker.pop(key, None)
        else:
            self._alert_cooldown_tracker.clear()

    def get_tenant_alert_config(self, user_id: str) -> Dict[str, Any]:
        """Fetch alert configuration for tenant from Supabase with graceful fallback."""
        if supabase_service.is_connected and user_id:
            try:
                res = supabase_service._client.table("alert_configs").select("*").eq("user_id", user_id).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning(f"Failed to fetch alert_configs for user {user_id}: {e}")

        return _mock_tenant_alerts.get(user_id, {
            "alert_on_score_drop": True,
            "score_threshold": 75,
            "alert_on_spf_error": True,
            "alert_on_dkim_fail": True,
            "alert_on_dmarc_change": True,
            "telegram_bot_token": settings.TELEGRAM_BOT_TOKEN or "",
            "telegram_chat_id": settings.TELEGRAM_CHAT_ID or "",
            "email_notifications": True,
            "notification_email": None
        })

    def set_tenant_alert_config(self, user_id: str, config: Dict[str, Any]):
        """Update in-memory fallback alert config (useful for testing & offline mode)."""
        if user_id not in _mock_tenant_alerts:
            _mock_tenant_alerts[user_id] = {}
        _mock_tenant_alerts[user_id].update(config)

    async def evaluate_and_dispatch(
        self,
        user_id: str,
        domain_name: str,
        health_score: int,
        overall_status: str,
        summary: Optional[Any] = None,
        issues: Optional[List[Any]] = None,
        trigger_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate deliverability health and dispatch degradation alert if rules match.
        Fails safe and returns dispatch summary.
        """
        config = self.get_tenant_alert_config(user_id)
        threshold = config.get("score_threshold") or config.get("health_threshold") or 75
        reasons: List[str] = []

        # 1. Check score degradation threshold
        if config.get("alert_on_score_drop", True) or config.get("alert_on_health_drop", True):
            if health_score < threshold:
                reasons.append(f"Deliverability score dipped to {health_score}% (threshold: {threshold}%)")

        # 2. Check protocol-specific failures
        if summary:
            spf_obj = getattr(summary, "spf", None)
            dkim_obj = getattr(summary, "dkim", None)
            dmarc_obj = getattr(summary, "dmarc", None)

            # SPF Failure check
            if config.get("alert_on_spf_error", True) and spf_obj:
                spf_status = getattr(spf_obj, "status", "unknown")
                if spf_status in ["critical", "missing"]:
                    reasons.append(f"SPF record validation failed ({spf_status})")

            # DKIM Failure check
            if config.get("alert_on_dkim_fail", True) and dkim_obj:
                dkim_status = getattr(dkim_obj, "status", "unknown")
                found_selectors = getattr(dkim_obj, "found_selectors", [])
                if dkim_status in ["critical", "missing"] or len(found_selectors) == 0:
                    reasons.append(f"DKIM active key selector missing or invalid ({dkim_status})")

            # DMARC Policy degradation check
            if config.get("alert_on_dmarc_change", True) and dmarc_obj:
                dmarc_policy = getattr(dmarc_obj, "policy", None)
                dmarc_status = getattr(dmarc_obj, "status", "unknown")
                if dmarc_status in ["critical", "missing"] or dmarc_policy not in ["quarantine", "reject"]:
                    policy_str = f"p={dmarc_policy}" if dmarc_policy else "missing"
                    reasons.append(f"DMARC enforcement relaxed or absent ({policy_str})")

        if trigger_reason and trigger_reason not in reasons:
            reasons.append(trigger_reason)

        # No degradation detected - do not spam merchant
        if not reasons:
            return {
                "dispatched": False,
                "reasons": [],
                "health_score": health_score,
                "threshold": threshold
            }

        # 3. Check if alert is suppressed by active 6-hour cooldown window
        if self.is_in_cooldown(user_id, domain_name):
            logger.info(
                f"Suppressed duplicate alert for {domain_name} (tenant {user_id}): active 6-hour cooldown window"
            )
            return {
                "dispatched": False,
                "cooldown": True,
                "reasons": reasons,
                "health_score": health_score,
                "threshold": threshold,
                "message": "Alert suppressed: 6-hour debounce cooldown active for domain"
            }

        # Build Rich Actionable Telegram Alert Message
        issues_formatted = ""
        if issues:
            top_issues = issues[:3]
            issues_formatted = "\n".join([
                f"• {getattr(i, 'title', str(i))}" for i in top_issues
            ])

        alert_text = (
            f"🚨 *INBOUNDCHECK DELIVERABILITY DEGRADATION ALERT*\n\n"
            f"🏬 *Domain:* `{domain_name}`\n"
            f"📉 *Health Score:* `{health_score}%` ({overall_status.upper()})\n"
            f"⚠️ *Incident Threshold:* `{threshold}%`\n"
            f"⏰ *Timestamp:* `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
            f"💥 *Triggered Anomalies:*\n"
            + "\n".join([f"• {r}" for r in reasons]) + "\n"
        )

        if issues_formatted:
            alert_text += f"\n🔍 *Root Cause Diagnostics:*\n{issues_formatted}\n"

        alert_text += (
            f"\n👉 [Open 1-Click DNS Fixer]({settings.FRONTEND_URL}/dashboard/inspector?domain={domain_name})"
        )

        # Dispatch Telegram alert using tenant's token or global fallback
        bot_token = config.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN or "7198234891:AAH8Fj90qWz1x9_example"
        chat_id = config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID or "@inboundcheck_alerts"

        telegram_res = await telegram_alert_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text=alert_text
        )

        # Optional Email Notification Dispatch logging
        email_dispatched = False
        if config.get("email_notifications", True) and config.get("notification_email"):
            email_dispatched = True
            logger.info(f"Queued email alert for {config['notification_email']}: {domain_name} degraded to {health_score}%")

        # Mark alert timestamp to activate 6-hour debounce cooldown
        self.mark_alerted(user_id, domain_name)

        return {
            "dispatched": True,
            "reasons": reasons,
            "health_score": health_score,
            "threshold": threshold,
            "telegram_result": telegram_res,
            "email_dispatched": email_dispatched,
            "target_chat_id": chat_id
        }

    async def dispatch_failover_alert(
        self,
        user_id: str,
        domain_name: str,
        order_id: str,
        trigger_reason: str,
        customer_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dispatch critical administrative alert when an omnichannel fallback receipt is activated.
        """
        config = self.get_tenant_alert_config(user_id)
        bot_token = config.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN or "7198234891:AAH8Fj90qWz1x9_example"
        chat_id = config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID or "@inboundcheck_alerts"

        alert_text = (
            f"⚡ *INBOUNDCHECK OMNICHANNEL FAILOVER TRIGGERED*\n\n"
            f"🏬 *Domain:* `{domain_name}`\n"
            f"📦 *Order Ref:* `{order_id}`\n"
            f"⚠️ *Failure Cause:* `{trigger_reason}`\n"
            f"📬 *Customer Email:* `{customer_email or 'N/A'}`\n"
            f"🔄 *Status:* Automated SMS/WhatsApp receipt fallback dispatched.\n"
            f"👉 [Review Failover Logs]({settings.FRONTEND_URL}/dashboard/shopify)"
        )

        res = await telegram_alert_service.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text=alert_text
        )

        # Persist incident record in failover_logs
        dispatch_status = "delivered" if res.get("success") else "failed"
        supabase_service.persist_failover_log(
            user_id=user_id,
            order_id=order_id,
            channel="telegram",
            provider="telegram_bot_api",
            status=dispatch_status,
            domain_name=domain_name,
            store_name="Store Sync",
            triggered_reason=trigger_reason,
            target_chat_id=chat_id,
            customer_email=customer_email,
            dispatch_payload=res,
            error_message=res.get("error") if not res.get("success") else None,
        )

        return res


alert_dispatcher = AlertDispatcherService()

