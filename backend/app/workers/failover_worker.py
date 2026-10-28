"""
InboundCheck - Dedicated Telegram Incident Alert Worker (Phase 4 Step 5)
========================================================================
Autonomous background worker daemon that claims received delivery failure events
using atomic FOR UPDATE SKIP LOCKED database RPCs, evaluates eligibility,
correlates tenant order context, and dispatches real-time merchant incident alerts via Telegram.
"""

import asyncio
import logging
import signal
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

from app.core.config import settings

# Strict failover eligibility for Telegram incident alerts:
# Permanent delivery failures (hard bounces, drop blocks, rejections) are alerted.
def canonicalize_event_type(event_type: Any) -> str:
    """
    Canonicalizes delivery failure event types to standard internal identifiers.
    Maps: hard_bounce, hardbounce, hard-bounce, hard bounce -> 'hard_bounce'
          bounce -> 'bounce'
          dropped -> 'dropped'
          rejected -> 'rejected'
          other types -> lowercase with spaces/hyphens replaced by underscores
    """
    if not event_type:
        return "unknown"
    clean = str(event_type).strip().lower().replace("-", "_").replace(" ", "_")
    if clean in {"hard_bounce", "hardbounce"}:
        return "hard_bounce"
    return clean


TELEGRAM_INCIDENT_ELIGIBLE_EVENTS = {
    "bounce",
    "hard_bounce",
    "dropped",
    "rejected",
}

ALLOW_DELAYED_RETRY_DEFAULT = getattr(settings, "FAILOVER_ALLOW_DELAYED_RETRY", False)
DEFAULT_MAX_RETRIES = getattr(settings, "FAILOVER_CORRELATION_MAX_RETRIES", 3)


class IncidentFactory:
    """
    Derives structured TelegramIncidentContext from delivery failure event
    and correlated transactional_message_registry record.
    Guarantees zero-PII extraction: no phone, customer email, or raw payload dumps.
    Enforces strict multi-tenant conflict detection: fails closed if independent tenant
    identities contradict authoritative registry records or each other.
    """

    @staticmethod
    def _create_ambiguous_context(event: Dict[str, Any], esp_provider: str, event_id: str) -> TelegramIncidentContext:
        """Create a sanitized fail-closed context with zero tenant-owned data merged."""
        failure_type = canonicalize_event_type(event.get("event_type"))
        return TelegramIncidentContext(
            delivery_failure_event_id=event_id,
            user_id="",
            order_id=None,
            domain_name=None,
            store_name=None,
            esp_provider=esp_provider,
            failure_type=failure_type,
            failure_reason=None,
            recommended_dns_action="Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan.",
            occurred_at=datetime.now(timezone.utc),
            message_type=None,
            is_ambiguous=True,
        )

    @staticmethod
    def from_event_and_registry(event: Dict[str, Any]) -> TelegramIncidentContext:
        event_id = str(event.get("id") or uuid.uuid4())
        esp_provider = event.get("esp_provider", "unknown")
        provider_message_id = event.get("provider_message_id")
        payload = event.get("event_payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        # 1. Collect all explicit tenant identity candidates from event & payload metadata paths
        metadata = payload.get("metadata") or {}
        custom_args = payload.get("custom_args") or {}
        user_vars_hyphen = payload.get("user-variables") or {}
        user_vars_underscore = payload.get("user_variables") or {}

        candidate_sources = [
            ("event.user_id", event.get("user_id")),
            ("payload.user_id", payload.get("user_id")),
            ("metadata.user_id", metadata.get("user_id") if isinstance(metadata, dict) else None),
            ("custom_args.user_id", custom_args.get("user_id") if isinstance(custom_args, dict) else None),
            ("user-variables.user_id", user_vars_hyphen.get("user_id") if isinstance(user_vars_hyphen, dict) else None),
            ("user_variables.user_id", user_vars_underscore.get("user_id") if isinstance(user_vars_underscore, dict) else None),
        ]

        extracted_uids = set()
        for _, val in candidate_sources:
            if val is not None and str(val).strip():
                extracted_uids.add(str(val).strip())

        # Check for internal conflict among payload metadata sources
        if len(extracted_uids) > 1:
            logger.warning(
                f"Conflicting tenant IDs detected in event {event_id} metadata sources. Failing closed."
            )
            return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)

        claimed_user_id = extracted_uids.pop() if extracted_uids else None

        user_id = claimed_user_id
        order_id = None
        domain_name = None
        store_name = None
        message_type = None

        # 2. Correlate with transactional message registry if provider_message_id exists
        if provider_message_id:
            msg = repository.get_transactional_message(esp_provider, provider_message_id)
            if msg:
                reg_user_id = str(msg.get("user_id") or "").strip() or None
                if claimed_user_id and reg_user_id and claimed_user_id != reg_user_id:
                    # CONFLICT between claimed user_id and authoritative registry record!
                    logger.warning(
                        f"Authoritative registry tenant conflicts with payload tenant for event {event_id}. Failing closed."
                    )
                    return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)

                user_id = reg_user_id or claimed_user_id
                order_id = msg.get("order_id")
                message_type = msg.get("message_type")
                domain_name = msg.get("domain_name")
                store_name = msg.get("store_name")

        # 3. Fallback correlation by order_id + recipient_email_hash (only if not yet correlated)
        if not user_id:
            candidate_order_id = (
                payload.get("order_id")
                or (metadata.get("order_id") if isinstance(metadata, dict) else None)
                or event.get("order_id")
            )
            recipient_hash = (
                event.get("recipient_email_hash")
                or payload.get("recipient_email_hash")
                or (metadata.get("recipient_email_hash") if isinstance(metadata, dict) else None)
            )
            if not recipient_hash:
                raw_recip = (event.get("recipient_email") or payload.get("recipient_email") or "").strip().lower()
                if raw_recip:
                    import hashlib
                    recipient_hash = hashlib.sha256(raw_recip.encode("utf-8")).hexdigest()

            if candidate_order_id and recipient_hash:
                msg, is_order_ambiguous = repository.get_transactional_message_by_order_and_recipient(
                    str(candidate_order_id), str(recipient_hash)
                )
                if is_order_ambiguous:
                    logger.warning(
                        f"Order/recipient match for event {event_id} is ambiguous across multiple tenants. Failing closed."
                    )
                    return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)

                if msg:
                    reg_user_id = str(msg.get("user_id") or "").strip() or None
                    if claimed_user_id and reg_user_id and claimed_user_id != reg_user_id:
                        logger.warning(
                            f"Registry tenant from order match conflicts with payload tenant for event {event_id}. Failing closed."
                        )
                        return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)

                    user_id = reg_user_id or claimed_user_id
                    order_id = msg.get("order_id") or candidate_order_id
                    message_type = msg.get("message_type")
                    domain_name = msg.get("domain_name")
                    store_name = msg.get("store_name")

        # 4. Fallback correlation by unique domain (only if not yet correlated)
        if not user_id:
            candidate_domain = domain_name or payload.get("domain_name") or event.get("domain_name")
            if not candidate_domain:
                sender = (
                    payload.get("sender")
                    or payload.get("from")
                    or (metadata.get("from") if isinstance(metadata, dict) else None)
                    or event.get("sender")
                )
                if sender and "@" in str(sender):
                    candidate_domain = str(sender).split("@")[-1].strip().lower().rstrip(">")

            if candidate_domain:
                candidate_user_ids, ambiguous = repository.get_unique_tenant_for_domain(str(candidate_domain))
                if ambiguous:
                    logger.warning(
                        f"Domain correlation for event {event_id} is ambiguous across multiple tenants. Failing closed."
                    )
                    return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)
                elif candidate_user_ids and len(candidate_user_ids) == 1:
                    dom_uid = candidate_user_ids[0]
                    if claimed_user_id and claimed_user_id != dom_uid:
                        logger.warning(
                            f"Domain owner conflicts with payload tenant for event {event_id}. Failing closed."
                        )
                        return IncidentFactory._create_ambiguous_context(event, esp_provider, event_id)
                    user_id = dom_uid
                    domain_name = candidate_domain

        # 5. Derive tenant defaults from repository
        if user_id:
            defaults = repository.get_tenant_defaults(user_id)
            if not domain_name:
                domain_name = defaults.get("domain_name")
            if not store_name:
                store_name = defaults.get("store_name")

        # 6. Fallback extraction from event payload metadata ONLY if user_id was verified
        if user_id:
            if not order_id:
                order_id = payload.get("order_id") or (metadata.get("order_id") if isinstance(metadata, dict) else None)
            if not domain_name:
                domain_name = payload.get("domain_name")
            if not store_name:
                store_name = payload.get("store_name")
            if not message_type:
                message_type = payload.get("message_type") or (metadata.get("message_type") if isinstance(metadata, dict) else None)

        failure_type = canonicalize_event_type(event.get("event_type"))
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
            delivery_failure_event_id=event_id,
            user_id=user_id or "",
            order_id=order_id,
            domain_name=domain_name,
            store_name=store_name,
            esp_provider=esp_provider,
            failure_type=failure_type,
            failure_reason=str(failure_reason) if failure_reason else None,
            recommended_dns_action="Review SPF, DKIM, DMARC, and the DNS Inspector remediation plan.",
            occurred_at=occurred_at,
            message_type=message_type,
            is_ambiguous=False,
        )


incident_factory = IncidentFactory()


def _register_shutdown_signals(stop_event: asyncio.Event) -> None:
    """Register SIGINT/SIGTERM handlers to trigger stop_event cleanly across platforms."""
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                # Fallback on Windows or when signal handlers cannot be added to event loop
                try:
                    import threading
                    if threading.current_thread() is threading.main_thread():
                        signal.signal(sig, lambda s, f: stop_event.set())
                except Exception:
                    pass
    except Exception:
        pass


async def process_delivery_failure_event(event: Dict[str, Any], worker_id: str) -> bool:
    """
    Process a single claimed delivery-failure event.
    - Filters out non-eligible events (deferred, complaints, unsubscribes) with audit logging.
    - Correlates tenant context without accessing customer phone or sensitive PII.
    - Dispatches Telegram incident alert.
    - Atomically updates status to processed or failed.
    - On unexpected exception, releases lease back to 'received' and propagates.
    """
    event_id = event.get("id")
    if not event_id:
        logger.warning(f"Skipping malformed event without id: {event}")
        return False

    try:
        # 1. Eligibility Check (Event Type Canonicalization)
        canonical_event = canonicalize_event_type(event.get("event_type"))
        if canonical_event not in TELEGRAM_INCIDENT_ELIGIBLE_EVENTS:
            logger.info(f"Event {event_id} type '{event.get('event_type')}' is not Telegram-incident eligible. Marking ignored.")
            repository.mark_event_processed(
                event_id=event_id,
                outcome="ignored",
                reason="Event type is not Telegram-incident eligible",
                worker_id=worker_id,
            )
            return False

        # 2. Correlate Incident Context
        incident = incident_factory.from_event_and_registry(event)

        # Message type eligibility check (e.g. promotional or marketing ignored)
        if incident.message_type and str(incident.message_type).strip().lower() in {"marketing", "promotional", "newsletter"}:
            logger.info(f"Event {event_id} message_type '{incident.message_type}' is not Telegram-incident eligible. Marking ignored.")
            repository.mark_event_processed(
                event_id=event_id,
                outcome="ignored",
                reason="Message type is not Telegram-incident eligible",
                worker_id=worker_id,
            )
            return False

        # Multi-tenant ambiguity guard: strict isolation, fail closed
        if incident.is_ambiguous:
            logger.warning(
                f"Delivery failure {event_id} has ambiguous tenant correlation across multiple candidate profiles. "
                f"Failing closed for strict tenant isolation."
            )
            repository.mark_event_failed(
                event_id=event_id,
                reason="Ambiguous tenant correlation: conflicting or multiple candidate profiles",
                worker_id=worker_id,
            )
            return False

        # Uncorrelated tenant resolution & bounded retry policy
        if not incident.user_id:
            payload = event.get("event_payload") or {}
            if not isinstance(payload, dict):
                payload = {}

            # Server-side bounded retry policy
            server_max = min(max(int(DEFAULT_MAX_RETRIES), 1), 5)
            allow_retry = bool(
                ALLOW_DELAYED_RETRY_DEFAULT
                or payload.get("allow_delayed_retry")
                or int(payload.get("max_correlation_attempts", 0)) > 1
            )
            max_retries = server_max
            current_attempts = int(payload.get("correlation_attempts", 0)) + 1

            if allow_retry and current_attempts < max_retries:
                payload["correlation_attempts"] = current_attempts
                # Exponential backoff delay
                backoff_seconds = min(15 * (2 ** (current_attempts - 1)), 180)
                payload["correlation_next_retry_at"] = datetime.now(timezone.utc).timestamp() + backoff_seconds

                persisted = repository.update_event_payload(event_id, payload)
                if not persisted:
                    logger.error(
                        f"Failed to persist retry attempt {current_attempts} for event {event_id}. Failing closed."
                    )
                    repository.mark_event_failed(
                        event_id=event_id,
                        reason="Failed to persist retry payload update",
                        worker_id=worker_id,
                    )
                    return False

                logger.warning(
                    f"Unable to correlate delivery failure {event_id} to tenant profile (attempt {current_attempts}/{max_retries}). "
                    f"Releasing lease for retry."
                )
                repository.release_claimed_delivery_failure_event(event_id, worker_id)
                return False
            else:
                reason = "Unable to correlate delivery failure to tenant"
                if current_attempts > 1:
                    reason += " (retries exhausted)"
                logger.warning(f"{reason} for event {event_id}.")
                repository.mark_event_failed(
                    event_id=event_id,
                    reason=reason,
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
        is_simulated = getattr(result, "simulated", False) or (result.get("simulated") if isinstance(result, dict) else False)
        provider_status = getattr(result, "provider_status", None) or (result.get("provider_status") if isinstance(result, dict) else None)
        if not provider_status:
            provider_status = "simulated" if is_simulated else "delivered"

        if is_success:
            repository.create_telegram_incident_log(
                delivery_failure_event_id=event_id,
                user_id=incident.user_id,
                order_id=incident.order_id or "unknown",
                domain_name=incident.domain_name or "unknown",
                store_name=incident.store_name or "unknown",
                triggered_reason=incident.failure_reason or incident.failure_type or "unknown",
                target_chat_id=target_chat_id,
                provider_status=provider_status,
                provider_message_id=provider_msg_id,
                is_simulated=is_simulated,
            )
            repository.mark_event_processed(
                event_id=event_id,
                outcome="processed",
                worker_id=worker_id,
            )
            if is_simulated:
                logger.info(f"[SIMULATED] Successfully processed delivery failure incident {event_id} for order {incident.order_id}")
            else:
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
    except Exception as exc:
        logger.error(f"Unexpected exception processing event {event_id}: {exc}", exc_info=True)
        try:
            repository.release_claimed_delivery_failure_event(event_id, worker_id)
        except Exception as rel_err:
            logger.warning(f"Could not release event {event_id} after processing exception: {rel_err}")
        raise


# Compatibility alias for earlier callers / tests
process_failover_event = process_delivery_failure_event


async def run_failover_worker(
    stop_event: Optional[asyncio.Event] = None,
    poll_idle_seconds: int = 15,
    lease_seconds: int = 900,
    limit: int = 20,
    once: bool = False,
) -> None:
    """
    Worker loop polling and claiming delivery failure events atomically.
    Transitions events: received -> queued -> processed / failed / ignored.
    Supports continuous daemon operation and single-cycle bounded execution via once=True.
    Recovers stale leases if prior workers crashed, and gracefully releases in-flight events on SIGTERM/SIGINT.
    """
    if stop_event is None:
        stop_event = asyncio.Event()

    _register_shutdown_signals(stop_event)

    worker_id = str(uuid.uuid4())
    from app.core.env_guard import get_deployment_commit_sha
    build_sha = get_deployment_commit_sha(default="unknown")
    logger.info(
        f"Failover worker started [Worker ID: {worker_id}, Build: {build_sha}] "
        f"(poll interval: {poll_idle_seconds}s, lease: {lease_seconds}s, limit: {limit}, once: {once})"
    )

    # Track claimed events that are currently in-flight
    in_flight_events: Dict[str, Dict[str, Any]] = {}

    try:
        while not stop_event.is_set():
            try:
                # Atomically claim received delivery failure events (FOR UPDATE SKIP LOCKED with lease expiry)
                events = repository.claim_pending_delivery_failure_events(
                    worker_id=worker_id,
                    limit=limit,
                    lease_seconds=lease_seconds,
                )

                if not events:
                    if once:
                        logger.info("Single-cycle failover mode: zero events claimed. Exiting.")
                        break
                    # Interruptible sleep
                    for _ in range(poll_idle_seconds):
                        if stop_event.is_set():
                            break
                        await asyncio.sleep(1)
                    continue

                for e in events:
                    e_id = e.get("id")
                    if e_id:
                        in_flight_events[str(e_id)] = e

                logger.info(f"Worker {worker_id} claimed {len(events)} delivery failure event(s). Processing...")
                for event in events:
                    if stop_event.is_set():
                        logger.info(f"Worker {worker_id} received stop signal; aborting batch.")
                        break

                    evt_id = str(event.get("id"))
                    payload = event.get("event_payload") or {}
                    if isinstance(payload, dict):
                        next_retry_at = payload.get("correlation_next_retry_at")
                        if next_retry_at:
                            try:
                                if datetime.now(timezone.utc).timestamp() < float(next_retry_at):
                                    # Still within backoff delay cooldown; release lease back to queue
                                    repository.release_claimed_delivery_failure_event(evt_id, worker_id)
                                    in_flight_events.pop(evt_id, None)
                                    continue
                            except (ValueError, TypeError):
                                pass

                    try:
                        await process_delivery_failure_event(event, worker_id)
                    finally:
                        in_flight_events.pop(evt_id, None)

                if once:
                    logger.info(f"Single-cycle failover mode: batch of {len(events)} event(s) processed. Exiting cleanly.")
                    break

            except Exception as exc:
                logger.error(f"Error in failover worker loop: {exc}", exc_info=True)
                # Dispatch Ops Alert (OPS-02)
                try:
                    from app.services.alerting.ops_alert_service import ops_alert_service, OpsIncident
                    await ops_alert_service.dispatch_incident(
                        OpsIncident(
                            alert_id="ALERT-WORKER-FAILOVER",
                            severity="P1",
                            summary=f"Failover worker loop crashed: {exc}",
                            details={"worker_id": worker_id, "error": str(exc)[:200]},
                        )
                    )
                except Exception as alert_err:
                    logger.warning(f"Failed to dispatch failover worker ops alert: {alert_err}")

                # Release remaining in-flight events after error
                if in_flight_events:
                    logger.info(f"Worker {worker_id} releasing {len(in_flight_events)} in-flight events after loop error...")
                    for rem_id in list(in_flight_events.keys()):
                        try:
                            repository.release_claimed_delivery_failure_event(rem_id, worker_id)
                        except Exception as rel_err:
                            logger.warning(f"Failed to release event {rem_id}: {rel_err}")
                        in_flight_events.pop(rem_id, None)

                if once:
                    logger.info("Single-cycle failover mode: loop exception encountered. Exiting cleanly.")
                    break

                await asyncio.sleep(5)

            # If stopped during batch processing, release remaining in-flight events
            if stop_event.is_set() and in_flight_events:
                logger.info(f"Worker {worker_id} releasing {len(in_flight_events)} unprocessed events on stop signal...")
                for rem_id in list(in_flight_events.keys()):
                    try:
                        repository.release_claimed_delivery_failure_event(rem_id, worker_id)
                    except Exception as rel_err:
                        logger.warning(f"Failed to release event {rem_id} on stop: {rel_err}")
                    in_flight_events.pop(rem_id, None)

    finally:
        # Final cleanup for any unhandled cancellations or terminations
        if in_flight_events:
            logger.info(f"Worker {worker_id} releasing {len(in_flight_events)} remaining in-flight events on shutdown...")
            for rem_id in list(in_flight_events.keys()):
                try:
                    repository.release_claimed_delivery_failure_event(rem_id, worker_id)
                except Exception as rel_err:
                    logger.warning(f"Failed to release event {rem_id} on final shutdown: {rel_err}")
                in_flight_events.pop(rem_id, None)

        logger.info(f"Failover worker {worker_id} stopped cleanly.")

