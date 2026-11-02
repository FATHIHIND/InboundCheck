"""
InboundCheck - Telegram Real-Time Alert & Incident Engine
=========================================================
Handles instant Telegram Bot alerts and incident dispatches when email deliverability telemetry
flags spam folder routing, hard bounces, RBL blacklists, or broken DMARC policies.
"""

import os
import re
import uuid
import random
import asyncio
from typing import Dict, Any, List, Optional, Literal, Union
from urllib.parse import quote_plus
import httpx
import logging
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.env_guard import check_is_placeholder
from app.core.encryption import (
    encrypt_credential,
    mask_credential,
    safe_decrypt_credential,
)

logger = logging.getLogger("TelegramAlertEngine")

# Retry & rate limiting configuration for Telegram Bot API outbound dispatches (Group 45B.3A)
MAX_TELEGRAM_ATTEMPTS: int = 3
PER_REQUEST_TIMEOUT_SECONDS: float = 6.0
MAX_SYNCHRONOUS_RETRY_DELAY_SECONDS: float = 5.0
MAX_TOTAL_RETRY_BUDGET_SECONDS: float = 10.0
BASE_BACKOFF_SECONDS: float = 0.5
MAX_BACKOFF_SECONDS: float = 4.0
TRANSIENT_HTTP_STATUS_CODES: set = {500, 502, 503, 504}


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
    message_type: Optional[str] = None
    is_ambiguous: bool = False


class TelegramDispatchResult(BaseModel):
    success: bool
    provider: Literal["telegram"] = "telegram"
    provider_status: Literal["delivered", "failed", "simulated"]
    telegram_message_id: Optional[str] = None
    target_chat_id: Optional[str] = None
    error_message: Optional[str] = None
    simulated: bool = False

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
_mock_failover_configs: Dict[str, Dict[str, Any]] = {}


class TelegramAlertService:
    """
    Dedicated Service for instant Telegram Bot Alert Dispatches.
    """

    def __init__(self):
        self._mock_mode: bool = False
        self._mock_dispatcher: Optional[Any] = None

    def enable_mock_mode(self, custom_dispatcher: Optional[Any] = None) -> None:
        """Enable deterministic mock dispatch for offline testing / staging. Strictly rejected in Production."""
        import os
        from app.core.config import settings
        env = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT or "").strip().lower()
        if env in ("production", "prod"):
            raise RuntimeError("Mock Telegram dispatch is forbidden in Production environment.")
        self._mock_mode = True
        self._mock_dispatcher = custom_dispatcher

    def disable_mock_mode(self) -> None:
        """Disable mock dispatch and restore real delivery semantics."""
        self._mock_mode = False
        self._mock_dispatcher = None

    @property
    def is_mock_mode(self) -> bool:
        return self._mock_mode

    def get_config(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch user Telegram alert configuration without multi-tenant bleed.
        Never falls back to global TELEGRAM_BOT_TOKEN for tenant-specific configs.
        In production/staging, fails closed if database is unavailable.
        """
        from app.services.supabase_client import supabase_service, DatabaseUnavailableError

        # 1. Check database if available
        db_alert = None
        db_failover = None
        try:
            db_alert = supabase_service.get_alert_config(user_id)
            db_failover = supabase_service.get_failover_config(user_id)
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error(f"Error querying configuration from database for user {user_id}: {e}")
            if not supabase_service._allow_in_memory_fallback():
                raise DatabaseUnavailableError(f"Database error fetching config for {user_id}: {e}")

        # 2. If records exist in DB, synthesize tenant config
        if db_alert or db_failover:
            res_config = {
                "is_enabled": (db_failover.get("is_enabled") if db_failover else True),
                "primary_channel": (db_failover.get("primary_channel") if db_failover else "telegram"),
                "provider": (db_failover.get("provider") if db_failover else "telegram_bot_api"),
                "telegram_bot_token": (db_alert.get("telegram_bot_token") if db_alert else None),
                "telegram_chat_id": (db_alert.get("telegram_chat_id") if db_alert else None),
                "trigger_events": (db_failover.get("trigger_events") if db_failover else ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"]),
                "store_name": "BrandShop DTC",
            }
            _mock_failover_configs[user_id] = res_config
            return res_config

        if not supabase_service._allow_in_memory_fallback():
            # In production or staging, default clean unconfigured config for this tenant (NO global credential bleed)
            return {
                "is_enabled": True,
                "primary_channel": "telegram",
                "provider": "telegram",
                "telegram_bot_token": None,
                "telegram_chat_id": None,
                "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
                "store_name": "BrandShop DTC",
            }

        # Development / test in-memory fallback
        if user_id in _mock_failover_configs:
            return _mock_failover_configs[user_id]

        default_dev = {
            "is_enabled": True,
            "primary_channel": "telegram",
            "provider": "telegram",
            "telegram_bot_token": None,
            "telegram_chat_id": None,
            "trigger_events": ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"],
            "store_name": "BrandShop DTC",
        }
        _mock_failover_configs[user_id] = default_dev
        return default_dev

    def get_decrypted_token(self, user_id: str) -> Optional[str]:
        """Retrieve and decrypt user's Telegram bot token in transient memory."""
        config = self.get_config(user_id)
        raw_token = config.get("telegram_bot_token")
        if not raw_token:
            return None
        return safe_decrypt_credential(raw_token)

    def format_config_for_client(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format failover/alert configuration for client API responses.
        Ensures sensitive tokens are masked and never exposed in plaintext.
        """
        client_config = dict(config)
        raw_token = client_config.get("telegram_bot_token")
        if raw_token:
            decrypted = safe_decrypt_credential(raw_token)
            if decrypted:
                client_config["telegram_bot_token"] = mask_credential(decrypted)
                client_config["telegram_bot_token_configured"] = True
            else:
                client_config["telegram_bot_token"] = "••••••••••••"
                client_config["telegram_bot_token_configured"] = True
        else:
            client_config["telegram_bot_token"] = None
            client_config["telegram_bot_token_configured"] = False
        return client_config

    def update_config(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save or update Telegram alert configuration with credential preservation and encryption."""
        from app.services.supabase_client import supabase_service, DatabaseUnavailableError

        # Load existing config to preserve credentials if omitted or masked
        existing = {}
        try:
            existing = self.get_config(user_id) or {}
        except Exception:
            existing = _mock_failover_configs.get(user_id, {})

        data = dict(payload)
        new_token = data.get("telegram_bot_token")
        if new_token is not None and str(new_token).strip() != "" and not str(new_token).strip().startswith("•"):
            # Plaintext token provided - encrypt before persisting
            data["telegram_bot_token"] = encrypt_credential(str(new_token).strip())
        else:
            # Preserve existing token
            data["telegram_bot_token"] = existing.get("telegram_bot_token")

        data["primary_channel"] = "telegram"
        data["provider"] = "telegram"

        # Persist to database if connected or required in non-development environments
        if not supabase_service._allow_in_memory_fallback() or supabase_service.is_connected:
            try:
                # Update failover config
                supabase_service.save_failover_config(user_id, {
                    "is_enabled": data.get("is_enabled", True),
                    "primary_channel": "telegram",
                    "provider": "telegram_bot_api",
                    "trigger_events": data.get("trigger_events", ["email_spam", "hard_bounce", "rbl_listed", "dmarc_broken"]),
                })
                # If bot token or chat ID is present, update alert_configs
                if data.get("telegram_bot_token") or data.get("telegram_chat_id"):
                    existing_alert = supabase_service.get_alert_config(user_id) or {}
                    alert_update = dict(existing_alert)
                    alert_update["telegram_bot_token"] = data.get("telegram_bot_token")
                    alert_update["telegram_chat_id"] = data.get("telegram_chat_id")
                    supabase_service.save_alert_config(user_id, alert_update)
            except DatabaseUnavailableError:
                raise
            except Exception as e:
                logger.error(f"Error persisting failover config for user {user_id}: {e}")
                if not supabase_service._allow_in_memory_fallback():
                    raise DatabaseUnavailableError(f"Database error saving failover config: {e}")

        if user_id not in _mock_failover_configs:
            _mock_failover_configs[user_id] = {}
        _mock_failover_configs[user_id].update(data)
        return _mock_failover_configs[user_id]

    async def send_telegram_alert(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        text: str = ""
    ) -> Dict[str, Any]:
        """
        Directly post message payload to Telegram Bot API with bounded retries and rate limiting.
        Fails closed: returns {"success": False, "error": ...} on HTTP errors or network exceptions.
        Guarantees strict tenant credential isolation: NEVER falls back to global platform credentials.
        Sanitizes all sensitive bot tokens from logs and error messages.
        """
        # Mock / Simulation mode handling (strictly rejected in Production)
        if self._mock_mode:
            env = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT or "").strip().lower()
            if env in ("production", "prod"):
                raise RuntimeError("Mock Telegram dispatch is forbidden in Production environment.")

            if self._mock_dispatcher is not None:
                if asyncio.iscoroutinefunction(self._mock_dispatcher):
                    return await self._mock_dispatcher(bot_token=bot_token, chat_id=chat_id, text=text)
                return self._mock_dispatcher(bot_token=bot_token, chat_id=chat_id, text=text)

            logger.info(f"[SIMULATED] Mock Telegram dispatch to chat {chat_id or 'mock_chat'} (zero external network)")
            return {
                "success": True,
                "simulated": True,
                "data": {
                    "result": {
                        "message_id": f"mock_tg_{uuid.uuid4().hex[:8]}",
                        "simulated": True,
                    }
                }
            }

        # Strict Tenant Credential Isolation: Require explicit tenant credentials, fail closed.
        clean_token = (bot_token or "").strip()
        clean_chat_id = (chat_id or "").strip()

        if (
            not clean_token
            or check_is_placeholder(clean_token)
            or not clean_chat_id
            or check_is_placeholder(clean_chat_id)
        ):
            logger.warning("Telegram credentials unconfigured or placeholder; dispatch rejected.")
            return {
                "success": False,
                "simulated": False,
                "error": "Telegram Bot Token and Chat ID must be explicitly configured and cannot be placeholder values."
            }

        url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
        total_slept: float = 0.0
        last_error: Optional[str] = None
        last_status_code: Optional[int] = None

        for attempt in range(1, MAX_TELEGRAM_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=PER_REQUEST_TIMEOUT_SECONDS) as client:
                    res = await client.post(
                        url,
                        json={
                            "chat_id": clean_chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                        },
                    )

                if res.status_code == 200:
                    try:
                        resp_json = res.json()
                    except Exception:
                        resp_json = {}
                    return {"success": True, "simulated": False, "data": resp_json}

                # Handle HTTP 429 Too Many Requests
                if res.status_code == 429:
                    last_status_code = 429
                    retry_after_val: Optional[int] = None
                    try:
                        err_payload = res.json()
                        params = err_payload.get("parameters") if isinstance(err_payload, dict) else {}
                        if isinstance(params, dict) and "retry_after" in params:
                            raw_ra = params["retry_after"]
                            if isinstance(raw_ra, (int, float)) and raw_ra >= 0:
                                retry_after_val = int(raw_ra)
                    except Exception:
                        pass

                    delay = float(retry_after_val) if retry_after_val is not None else BASE_BACKOFF_SECONDS
                    safe_delay_int = int(delay)

                    # Bounded synchronous budget check
                    if delay > MAX_SYNCHRONOUS_RETRY_DELAY_SECONDS or (total_slept + delay) > MAX_TOTAL_RETRY_BUDGET_SECONDS:
                        logger.warning(
                            f"Telegram rate limit (HTTP 429) retry_after={safe_delay_int}s exceeds synchronous budget "
                            f"(delay={delay:.1f}s, budget={MAX_SYNCHRONOUS_RETRY_DELAY_SECONDS}s)."
                        )
                        return {
                            "success": False,
                            "simulated": False,
                            "status_code": 429,
                            "error": f"Telegram rate limit exceeded (HTTP 429). Retry after {safe_delay_int}s exceeds synchronous retry budget.",
                            "retry_after": safe_delay_int,
                            "retryable": True,
                        }

                    if attempt < MAX_TELEGRAM_ATTEMPTS:
                        logger.info(
                            f"Telegram HTTP 429 rate limit received. Retrying in {delay:.2f}s "
                            f"(attempt {attempt}/{MAX_TELEGRAM_ATTEMPTS})."
                        )
                        total_slept += delay
                        await asyncio.sleep(delay)
                        continue
                    else:
                        return {
                            "success": False,
                            "simulated": False,
                            "status_code": 429,
                            "error": f"Telegram rate limit exceeded (HTTP 429) after {MAX_TELEGRAM_ATTEMPTS} attempts.",
                            "retry_after": safe_delay_int,
                            "retryable": True,
                        }

                # Handle Transient Server Errors (500, 502, 503, 504)
                if res.status_code in TRANSIENT_HTTP_STATUS_CODES:
                    last_status_code = res.status_code
                    safe_text = sanitize_log_message(res.text[:300], clean_token)
                    last_error = f"Telegram server error ({res.status_code}): {safe_text}"
                    logger.warning(
                        f"Telegram API transient error {res.status_code} (attempt {attempt}/{MAX_TELEGRAM_ATTEMPTS}): {safe_text}"
                    )
                    if attempt < MAX_TELEGRAM_ATTEMPTS:
                        exp_delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                        jitter = random.uniform(0.0, 0.25 * exp_delay)
                        backoff_delay = min(MAX_BACKOFF_SECONDS, exp_delay + jitter)
                        if (total_slept + backoff_delay) <= MAX_TOTAL_RETRY_BUDGET_SECONDS:
                            total_slept += backoff_delay
                            await asyncio.sleep(backoff_delay)
                            continue
                    return {
                        "success": False,
                        "simulated": False,
                        "status_code": res.status_code,
                        "error": last_error,
                        "retryable": True,
                    }

                # Permanent Client Errors (400, 401, 403, 404, etc.) - DO NOT RETRY
                safe_text = sanitize_log_message(res.text[:300], clean_token)
                logger.warning(f"Telegram API permanent client error ({res.status_code}): {safe_text}")
                return {
                    "success": False,
                    "simulated": False,
                    "status_code": res.status_code,
                    "error": f"Telegram API error ({res.status_code}): {safe_text}",
                    "retryable": False,
                }

            except asyncio.CancelledError:
                logger.info("Telegram dispatch cancelled by caller or runtime.")
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                safe_net_err = sanitize_log_message(str(net_err), clean_token)
                last_error = f"Telegram network error ({type(net_err).__name__}): {safe_net_err}"
                logger.warning(
                    f"Telegram network failure on attempt {attempt}/{MAX_TELEGRAM_ATTEMPTS}: {last_error}"
                )
                if attempt < MAX_TELEGRAM_ATTEMPTS:
                    exp_delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                    jitter = random.uniform(0.0, 0.25 * exp_delay)
                    backoff_delay = min(MAX_BACKOFF_SECONDS, exp_delay + jitter)
                    if (total_slept + backoff_delay) <= MAX_TOTAL_RETRY_BUDGET_SECONDS:
                        total_slept += backoff_delay
                        await asyncio.sleep(backoff_delay)
                        continue
                return {
                    "success": False,
                    "simulated": False,
                    "error": last_error,
                    "retryable": True,
                }
            except Exception as e:
                safe_err = sanitize_log_message(str(e), clean_token)
                logger.error(f"Unexpected error calling Telegram API: {safe_err}")
                return {
                    "success": False,
                    "simulated": False,
                    "error": safe_err,
                    "retryable": False,
                }

        # If loop exhausts
        return {
            "success": False,
            "simulated": False,
            "status_code": last_status_code,
            "error": last_error or "Telegram dispatch exhausted retry budget",
            "retryable": True,
        }

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
        Enforces Zero-PII: customer email and phone are completely omitted from the alert text
        and never persisted in failover logs.
        """
        config = self.get_config(user_id)
        if not config.get("is_enabled", True):
            return {
                "dispatched": False,
                "reason": "Telegram alert engine is disabled in user settings"
            }

        bot_token = (self.get_decrypted_token(user_id) or "").strip()
        chat_id = (config.get("telegram_chat_id") or "").strip()

        if self._mock_mode:
            bot_token = bot_token or "mock_bot_token"
            chat_id = chat_id or "@mock_chat"
        elif (
            not bot_token
            or check_is_placeholder(bot_token)
            or not chat_id
            or check_is_placeholder(chat_id)
        ):
            err_msg = "Telegram Bot Token and Chat ID must be explicitly configured and cannot be placeholder values."
            logger.warning(f"Telegram dispatch rejected for user {user_id}: {err_msg}")
            from app.services.supabase_client import supabase_service
            log_record = supabase_service.persist_failover_log(
                user_id=user_id,
                order_id=order_id or "unknown",
                channel="telegram",
                provider="telegram",
                status="failed",
                provider_status="failed",
                domain_name=domain_name or "unknown",
                store_name=store_name or "unknown",
                triggered_reason=trigger_reason or "unknown",
                target_chat_id=chat_id or None,
                customer_email=None,
                customer_phone=None,
                dispatch_payload={"success": False, "simulated": False, "error": err_msg},
                error_message=err_msg,
                is_simulated=False,
            )
            return {
                "dispatched": False,
                "channel": "telegram",
                "target_chat_id": chat_id or None,
                "error": err_msg,
                "dispatch_res": {"success": False, "simulated": False, "error": err_msg},
                "log": log_record,
            }

        # Build Rich Actionable Telegram Alert Message (Strict Zero-PII)
        clean_store = sanitize_log_message(str(store_name or "Shopify Store").strip())
        clean_domain = sanitize_log_message(str(domain_name or "store.com").strip().lower())
        clean_order = sanitize_log_message(str(order_id or "N/A").strip())
        clean_reason = sanitize_log_message(str(trigger_reason or "email_spam_detected").strip())
        encoded_domain = quote_plus(clean_domain)

        alert_text = (
            f"🚨 *INBOUNDCHECK INCIDENT ALERT*\n\n"
            f"🏬 *Store:* {clean_store}\n"
            f"🌐 *Domain:* `{clean_domain}`\n"
            f"📦 *Order Ref:* `{clean_order}`\n"
            f"⚠️ *Incident Type:* `{clean_reason}`\n"
            f"⏰ *Timestamp:* `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
            f"🔍 *Action Required:* Inspect diagnostic records & RBL posture\n"
            f"👉 [Open InboundCheck Inspector]({settings.FRONTEND_URL}/dashboard/inspector?domain={encoded_domain})"
        )

        dispatch_res = await self.send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            text=alert_text
        )

        is_sim = bool(dispatch_res.get("simulated", False))
        is_success = bool(dispatch_res.get("success", False))
        dispatch_status = "dispatched" if is_sim else ("delivered" if is_success else "failed")
        p_status = "simulated" if is_sim else dispatch_status

        # Persist to database via repository (Strict Zero-PII: customer_email & customer_phone are None)
        from app.services.supabase_client import supabase_service
        log_record = supabase_service.persist_failover_log(
            user_id=user_id,
            order_id=clean_order,
            channel="telegram",
            provider="telegram",
            status=dispatch_status,
            provider_status=p_status,
            domain_name=clean_domain,
            store_name=clean_store,
            triggered_reason=clean_reason,
            target_chat_id=chat_id,
            customer_email=None,
            customer_phone=None,
            dispatch_payload=dispatch_res,
            error_message=dispatch_res.get("error") if not is_success else None,
            is_simulated=is_sim,
        )

        return {
            "dispatched": is_success or is_sim,
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

        bot_token = (self.get_decrypted_token(ctx.user_id) or "").strip()
        chat_id = (config.get("telegram_chat_id") or "").strip()

        # In mock mode, allow synthetic identifiers if unconfigured
        if self._mock_mode:
            bot_token = bot_token or "mock_bot_token"
            chat_id = chat_id or "@mock_chat"
        elif (
            not bot_token
            or check_is_placeholder(bot_token)
            or not chat_id
            or check_is_placeholder(chat_id)
        ):
            logger.warning(f"Telegram alert skipped for user {ctx.user_id}: credentials not configured or placeholder.")
            return TelegramDispatchResult(
                success=False,
                provider="telegram",
                provider_status="failed",
                telegram_message_id=None,
                target_chat_id=chat_id or None,
                error_message="Telegram Bot Token and Chat ID must be explicitly configured and cannot be placeholder values.",
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

        is_sim = bool(send_res.get("simulated", False))
        if send_res.get("success"):
            data = send_res.get("data", {})
            tg_msg_id = str(data.get("result", {}).get("message_id") or data.get("message_id") or "")
            return TelegramDispatchResult(
                success=True,
                provider="telegram",
                provider_status="simulated" if is_sim else "delivered",
                telegram_message_id=tg_msg_id or None,
                target_chat_id=chat_id,
                error_message=None,
                simulated=is_sim,
            )
        else:
            return TelegramDispatchResult(
                success=False,
                provider="telegram",
                provider_status="failed",
                telegram_message_id=None,
                target_chat_id=chat_id,
                error_message=send_res.get("error") or "Failed to deliver Telegram alert",
                simulated=is_sim,
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
