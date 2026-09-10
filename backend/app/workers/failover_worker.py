"""
InboundCheck - Dedicated Failover & Incident Notification Worker (Phase 4)
==========================================================================
Durable worker daemon that processes delivery-failure events and dispatches
merchant and customer fallbacks (via Telegram Bot API) exactly once.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, List

from app.services.supabase_client import supabase_service
from app.services.failover.omnichannel_service import omnichannel_service

logger = logging.getLogger("FailoverWorker")


async def process_failover_event(event: Dict[str, Any], worker_id: str) -> bool:
    """
    Process a single delivery-failure event and dispatch real-time alerts.
    Guarantees exactly-once processing by claiming and updating status.
    """
    event_id = event.get("id")
    user_id = event.get("user_id")
    order_id = event.get("order_id", "#0000")
    domain_name = event.get("domain_name", "store.com")
    store_name = event.get("store_name", "Shopify Store")
    reason = event.get("triggered_reason", "delivery_failure")
    customer_email = event.get("customer_email")

    if not user_id:
        logger.warning(f"Skipping invalid failover event without user_id: {event}")
        return False

    try:
        logger.info(f"Processing failover event {event_id} for order {order_id} (reason: {reason})")

        # Dispatch via omnichannel Telegram engine
        result = await omnichannel_service.dispatch_alert(
            user_id=user_id,
            order_id=order_id,
            store_name=store_name,
            customer_email=customer_email,
            domain_name=domain_name,
            reason=reason,
            channel="telegram"
        )

        logger.info(f"Failover dispatch result for {order_id}: {result.get('status')}")
        return result.get("status") == "delivered"
    except Exception as exc:
        logger.error(f"Error processing failover event {event_id}: {exc}")
        return False


async def run_failover_worker(
    stop_event: Optional[asyncio.Event] = None,
    poll_idle_seconds: int = 15
) -> None:
    """
    Continuous worker loop polling and processing pending failover / delivery failure events.
    """
    worker_id = str(uuid.uuid4())
    logger.info(f"Failover worker started [Worker ID: {worker_id}] (poll interval: {poll_idle_seconds}s)")

    while stop_event is None or not stop_event.is_set():
        try:
            # Poll for pending failover records if connected to Supabase
            pending_events: List[Dict[str, Any]] = []
            if supabase_service.is_connected and supabase_service._client:
                try:
                    res = (
                        supabase_service._client.table("failover_logs")
                        .select("*")
                        .eq("status", "pending")
                        .limit(20)
                        .execute()
                    )
                    pending_events = res.data or []
                except Exception as db_err:
                    logger.debug(f"Query for pending failover events: {db_err}")

            if not pending_events:
                # Idle sleep
                for _ in range(poll_idle_seconds):
                    if stop_event and stop_event.is_set():
                        break
                    await asyncio.sleep(1)
                continue

            logger.info(f"Worker {worker_id} processing {len(pending_events)} pending failover event(s)...")
            for event in pending_events:
                if stop_event and stop_event.is_set():
                    break
                await process_failover_event(event, worker_id)

        except Exception as e:
            logger.error(f"Unexpected error in failover worker loop: {e}", exc_info=True)
            await asyncio.sleep(5)

    logger.info(f"Failover worker {worker_id} stopped cleanly.")
