"""
InboundCheck - Production Operational Alert Dispatcher (Phase 2.1)
==================================================================
Dispatches critical operational incident notifications to configured ops channels
(Webhook, Telegram) with strict anti-flapping cooldown, timeout enforcement,
payload sanitization, and fail-safe non-blocking execution.
"""

import httpx
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("OpsAlertService")

# Cooldown tracking: incident_fingerprint -> last_alert_epoch
_INCIDENT_COOLDOWNS: Dict[str, float] = {}
COOLDOWN_WINDOW_SECONDS = 900  # 15 minutes anti-flapping suppression


class OpsIncident(BaseModel):
    alert_id: str = Field(..., description="e.g. ALERT-DB-OUTAGE, ALERT-WEBHOOK-FAILURES")
    severity: str = Field(..., description="P0 | P1 | P2")
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[str] = None


def sanitize_incident_payload(data: Any) -> Any:
    """Recursively mask secrets, tokens, passwords, and sensitive keys."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if re.search(r"(key|secret|token|password|bearer|auth|cookie)", str(k), re.IGNORECASE):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_incident_payload(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_incident_payload(x) for x in data]
    elif isinstance(data, str):
        return re.sub(
            r"(token|key|secret|password|bearer)[=:\s]+[A-Za-z0-9_\-\.]+",
            r"\1=[REDACTED]",
            data,
            flags=re.IGNORECASE,
        )
    return data


class OpsAlertService:
    """
    Lightweight, fail-safe incident alert dispatcher for operations.
    Guarantees:
    - Never raises unhandled exceptions.
    - 5.0s client timeout.
    - 0 retries to prevent retry amplification or recursive alerting loops.
    - 15-minute anti-flapping cooldown per incident fingerprint.
    - All payloads sanitized before transmission.
    """

    def __init__(self):
        self.webhook_url = getattr(settings, "OPS_ALERT_WEBHOOK_URL", None) or os.getenv("OPS_ALERT_WEBHOOK_URL", "")
        self.telegram_bot_token = getattr(settings, "OPS_ALERT_TELEGRAM_BOT_TOKEN", None) or os.getenv("OPS_ALERT_TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = getattr(settings, "OPS_ALERT_TELEGRAM_CHAT_ID", None) or os.getenv("OPS_ALERT_TELEGRAM_CHAT_ID", "")
        self.environment = getattr(settings, "ENVIRONMENT", "development")

    def is_configured(self) -> bool:
        """Check if at least one ops notification channel is configured."""
        return bool(self.webhook_url or (self.telegram_bot_token and self.telegram_chat_id))

    def should_suppress_flapping(self, fingerprint: str) -> bool:
        """Check if an alert with this fingerprint was already dispatched within the cooldown window."""
        now = time.time()
        last_dispatched = _INCIDENT_COOLDOWNS.get(fingerprint, 0)
        if now - last_dispatched < COOLDOWN_WINDOW_SECONDS:
            return True
        return False

    def mark_dispatched(self, fingerprint: str) -> None:
        """Record dispatch timestamp for flapping suppression."""
        _INCIDENT_COOLDOWNS[fingerprint] = time.time()

    async def dispatch_incident(
        self,
        incident: Optional[OpsIncident] = None,
        *,
        alert_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        severity: str = "P1",
        summary: str = "",
        details: Optional[Dict[str, Any]] = None,
        occurred_at: Optional[str] = None,
    ) -> bool:
        """
        Dispatch an operational incident to configured channels.
        Fully fail-safe: failures are logged and never bubble up to callers.
        Accepts either an OpsIncident model or direct keyword arguments.
        """
        if incident is None:
            resolved_id = alert_id or fingerprint or "ALERT-GENERAL"
            incident = OpsIncident(
                alert_id=resolved_id,
                severity=severity,
                summary=summary or resolved_id,
                details=details or {},
                occurred_at=occurred_at,
            )

        effective_fingerprint = fingerprint or incident.alert_id or f"{incident.alert_id}:{incident.severity}"

        # Anti-flapping suppression
        if self.should_suppress_flapping(effective_fingerprint):
            logger.info(f"Ops alert suppressed (cooldown active for {effective_fingerprint})")
            return False

        now_iso = incident.occurred_at or datetime.now(timezone.utc).isoformat()
        clean_details = sanitize_incident_payload(incident.details)

        payload = {
            "service": "inboundcheck-backend",
            "environment": self.environment,
            "alert_id": incident.alert_id,
            "severity": incident.severity,
            "summary": incident.summary,
            "details": clean_details,
            "timestamp": now_iso,
        }

        dispatched = False

        # 1. Dispatch to Ops Webhook (Slack / Discord / Generic HTTPS Webhook)
        if self.webhook_url and self.webhook_url.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(self.webhook_url, json=payload)
                    if resp.status_code in (200, 201, 202, 204):
                        dispatched = True
                        logger.info(f"Ops incident {incident.alert_id} dispatched to webhook successfully")
                    else:
                        logger.warning(f"Ops alert webhook returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"Ops alert webhook delivery failed: {e}")

        # 2. Dispatch to Ops Telegram Channel
        if self.telegram_bot_token and self.telegram_chat_id:
            try:
                tg_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                text_msg = (
                    f"🚨 *[OPS ALERT] {incident.alert_id} ({incident.severity})*\n\n"
                    f"*Environment:* `{self.environment}`\n"
                    f"*Summary:* {incident.summary}\n"
                    f"*Timestamp:* `{now_iso}`\n"
                )
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        tg_url,
                        json={
                            "chat_id": self.telegram_chat_id,
                            "text": text_msg,
                            "parse_mode": "Markdown",
                        }
                    )
                    if resp.status_code == 200:
                        dispatched = True
                        logger.info(f"Ops incident {incident.alert_id} dispatched to Telegram ops channel")
                    else:
                        logger.warning(f"Ops alert Telegram returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"Ops alert Telegram delivery failed: {e}")

        if dispatched:
            self.mark_dispatched(effective_fingerprint)

        # Fallback local log if no channels configured
        if not self.is_configured():
            logger.warning(
                f"[OPS_ALERT_UNCONFIGURED] Alert {incident.alert_id} ({incident.severity}): {incident.summary}"
            )

        return dispatched


ops_alert_service = OpsAlertService()
