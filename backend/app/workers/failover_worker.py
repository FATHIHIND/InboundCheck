"""
InboundCheck - Dedicated Telegram Incident Alert Worker (Phase 4 Step 5)
========================================================================
Autonomous background worker daemon that claims received delivery failure events
using atomic FOR UPDATE SKIP LOCKED database RPCs, evaluates eligibility,
correlates tenant order context, and dispatches real-time merchant incident alerts via Telegram.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from app.services.failover.failover_repository import failure_event_repository as repository
from app.services.failover.omnichannel_service import (
    telegram_alert_service,
    TelegramIncidentContext,
    TelegramDispatchResult,
)

omnichannel_service = telegram_alert_service
logger = logging.getLogger("FailoverWorker")

# Strict failover eligibility for Telegram incident alerts:
# Only permanent delivery failures (hard bounces, drop blocks, rejections) are alerted.
TELEGRAM_INCIDENT_ELIGIBLE_EVENTS = {"bounce", "dropped", "rejected"}


class IncidentFactory:
    """
    Derives structured TelegramIncidentContext from delivery failure event
    and correlated transactional_message_registry record.
    Guarantees zero-PII extraction: no phone, customer email, or raw payload dumps.
    """

    @staticmethod
    def from_event_and_registry(event: Dict[str, Any]) -> TelegramIncidentContext:
        esp_provider = event.get("esp_provider", "unknown")
        provider_message_id = event.get("provider_message_id")
        user_id = event.get("user_id")
        order_id = None
        domain_name = None
        store_name = None

        # 1. Correlate with transactional message registry if provider_message_id exists
        if provider_message_id:
            msg = repository.get_transactional_message(esp_provider, provider_message_id)
            if msg:
                if not user_id:
                    user_id = msg.get("user_id")
                order_id = msg.get("order_id")

        # 2. Derive tenant defaults from repository
        if user_id:
            defaults = repository.get_tenant_defaults(user_id)
            domain_name = defaults.get("domain_name")
            store_name = defaults.get("store_name")

        # 3. Fallback extraction from event payload metadata
        payload = event.get("event_payload") or {}
        if not order_id:
            order_id = payload.get("order_id")
        if not domain_name:
            domain_name = payload.get("domain_name")
        if not store_name:
            store_name = payload.get("store_name")

        failure_type = str(event.get("event_type", "bounce")).lower()
        failure_reason = (
            payload.get("reason")
            or payload.get("details")
            or payload.get("delivery_status_message")
            or payload.get("diagnostic_code")
            or event.get("reason_code")
        )

        occurred_at_str = event.get("event_timestamp") or event.get("received_at")
        occurred_at = datetime.now(timezone.utc)
        if occurred_at_str:
            try:
                clean_str = str(occurred_at_str).replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
                occurred_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        return TelegramIncidentContext(
            delivery_failure_event_id=str(event.get("id") or uuid.uuid4()),
            user_id=user_id or "",
            order_id=order_id,
            domain_name=domain_name,
            store_name=store_name,
            esp_provider=esp_provider,
            failure_type=failure_type,
            failure_reason=str(failure_reason) if failure_reason else None,
            recommended_dns_action="Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan.",
            occurred_at=occurred_at,
        )


incident_factory = IncidentFactory()


async def process_delivery_failure_event(event: Dict[str, Any], worker_id: str) -> bool:
    """
    Process a single claimed delivery-failure event.
    - Filters out non-eligible events (deferred, complaints, unsubscribes) with audit logging.
    - Correlates tenant context without accessing customer phone or sensitive PII.
    - Dispatches Telegram incident alert.
    - Atomically updates status to processed or failed.
    """
    event_id = event.get("id")
    if not event_id:
        logger.warning(f"Skipping malformed event without id: {event}")
        return False

    event_type = str(event.get("event_type", "")).strip().lower()

    # 1. Eligibility Check
    if event_type not in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS:
        logger.info(f"Event {event_id} type '{event_type}' is not Telegram-incident eligible. Marking ignored.")
        repository.mark_event_processed(
            event_id=event_id,
            outcome="ignored",
            reason="Event type is not Telegram-incident eligible",
            worker_id=worker_id,
        )
        return False

    # 2. Correlate Incident Context
    incident = incident_factory.from_event_and_registry(event)

    if not incident.user_id:
        logger.warning(f"Unable to correlate delivery failure {event_id} to tenant profile.")
        repository.mark_event_failed(
            event_id=event_id,
            reason="Unable to correlate delivery failure to tenant",
            worker_id=worker_id,
        )
        return False

    # 3. Dispatch Alert via Telegram Alert Engine
    result: TelegramDispatchResult = await telegram_alert_service.dispatch_alert(
        incident=incident,
        channel="telegram",
        esp_provider=incident.esp_provider,
    )

    # 4. Record Incident Log & Finalize Event State
    is_success = getattr(result, "success", None)
    if is_success is None:
        is_success = bool(result.get("status") == "delivered" or result.get("success") or result.get("dispatched"))

    target_chat_id = getattr(result, "target_chat_id", None) or (result.get("target_chat_id") if isinstance(result, dict) else None)
    provider_msg_id = getattr(result, "telegram_message_id", None) or (result.get("telegram_message_id") or result.get("log_id") if isinstance(result, dict) else None)
    err_msg = getattr(result, "error_message", None) or (result.get("error_message") or result.get("error") if isinstance(result, dict) else None)

    if is_success:
        repository.create_telegram_incident_log(
            delivery_failure_event_id=event_id,
            user_id=incident.user_id,
            order_id=incident.order_id or "unknown",
            domain_name=incident.domain_name or "unknown",
            store_name=incident.store_name or "unknown",
            triggered_reason=incident.failure_reason or incident.failure_type or "unknown",
            target_chat_id=target_chat_id,
            provider_status="delivered",
            provider_message_id=provider_msg_id,
        )
        repository.mark_event_processed(
            event_id=event_id,
            outcome="processed",
            worker_id=worker_id,
        )
        logger.info(f"Successfully processed delivery failure incident {event_id} for order {incident.order_id}")
        return True
    else:
        logger.warning(f"Telegram dispatch failed for event {event_id}: {err_msg}")
        repository.mark_event_failed(
            event_id=event_id,
            reason=err_msg or "Failed to deliver Telegram alert",
            worker_id=worker_id,
        )
        return False


# Compatibility alias for earlier callers / tests
process_failover_event = process_delivery_failure_event


async def run_failover_worker(
    stop_event: Optional[asyncio.Event] = None,
    poll_idle_seconds: int = 15,
) -> None:
    """
    Continuous worker loop polling and claiming delivery failure events atomically.
    Transitions events: received -> queued -> processed / failed / ignored.
    """
    worker_id = str(uuid.uuid4())
    logger.info(f"Failover worker started [Worker ID: {worker_id}] (poll interval: {poll_idle_seconds}s)")

    while stop_event is None or not stop_event.is_set():
        try:
            # Atomically claim received delivery failure events (FOR UPDATE SKIP LOCKED)
            events = repository.claim_received_delivery_failure_events(
                worker_id=worker_id,
                limit=20,
            )

            if not events:
                # Interruptible sleep
                for _ in range(poll_idle_seconds):
                    if stop_event and stop_event.is_set():
                        break
                    await asyncio.sleep(1)
                continue

            logger.info(f"Worker {worker_id} claimed {len(events)} delivery failure event(s). Processing...")
            for event in events:
                if stop_event and stop_event.is_set():
                    break
                await process_delivery_failure_event(event, worker_id)

        except Exception as exc:
            logger.error(f"Error in failover worker loop: {exc}", exc_info=True)
            await asyncio.sleep(5)

    logger.info(f"Failover worker {worker_id} stopped cleanly.")
