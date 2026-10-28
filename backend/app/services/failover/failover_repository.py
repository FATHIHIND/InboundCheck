"""
InboundCheck - Failover & Delivery Failure Repository (Phase 4 Step 5)
======================================================================
Database access layer for claiming delivery failure events, updating state transitions,
looking up transactional message registry records, and creating idempotent Telegram incident logs.
"""

from typing import List, Dict, Any, Optional, Tuple
import logging
import uuid
from datetime import datetime, timezone

from app.services.supabase_client import supabase_service

logger = logging.getLogger("FailoverRepository")


class FailoverRepository:
    """Repository managing delivery-failure lifecycle and Telegram incident logs."""

    def __init__(self):
        self.supabase = supabase_service

    def claim_pending_delivery_failure_events(
        self,
        worker_id: str,
        limit: int = 20,
        lease_seconds: int = 900,
    ) -> List[Dict[str, Any]]:
        """
        Atomically claim received delivery failure events using claim_pending_delivery_failure_events RPC.
        Transitions received -> queued using FOR UPDATE SKIP LOCKED with lease_until and stale recovery.
        """
        lease_str = f"{lease_seconds} seconds"
        if self.supabase._client:
            try:
                res = self.supabase._client.rpc(
                    "claim_pending_delivery_failure_events",
                    {
                        "p_worker_id": worker_id,
                        "p_limit": limit,
                        "p_lease_timeout": lease_str,
                    }
                ).execute()
                if res.data is not None:
                    for row in res.data:
                        evt_id = row.get("id")
                        for m in self.supabase._in_memory_delivery_failure_events.values():
                            if m.get("id") == evt_id:
                                m["processing_status"] = "queued"
                                m["claimed_by"] = worker_id
                                m["claimed_at"] = row.get("claimed_at")
                                m["lease_until"] = row.get("lease_until")
                    return res.data
            except Exception as e:
                logger.warning(f"claim_pending_delivery_failure_events RPC failed: {e}. Trying fallback RPC...")
                try:
                    res = self.supabase._client.rpc(
                        "claim_received_delivery_failure_events",
                        {
                            "p_worker_id": worker_id,
                            "p_limit": limit,
                            "p_lease_timeout": lease_str,
                        }
                    ).execute()
                    if res.data is not None:
                        for row in res.data:
                            evt_id = row.get("id")
                            for m in self.supabase._in_memory_delivery_failure_events.values():
                                if m.get("id") == evt_id:
                                    m["processing_status"] = "queued"
                                    m["claimed_by"] = worker_id
                                    m["claimed_at"] = row.get("claimed_at")
                                    m["lease_until"] = row.get("lease_until")
                        return res.data
                except Exception as fallback_err:
                    logger.warning(f"Could not execute claim RPC fallback: {fallback_err}")
                    if not self.supabase._allow_in_memory_fallback():
                        from app.services.supabase_client import DatabaseUnavailableError
                        from app.core.env_guard import sanitize_exception
                        raise DatabaseUnavailableError(f"Database RPC claim_pending_delivery_failure_events failed in production: {sanitize_exception(fallback_err or e)}") from fallback_err

        # In-memory fallback for local development and testing
        return self.supabase.claim_pending_delivery_failure_events(
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )

    claim_received_delivery_failure_events = claim_pending_delivery_failure_events

    def release_claimed_delivery_failure_event(self, event_id: str, worker_id: str) -> bool:
        """
        Gracefully release a claimed delivery failure event back to 'received' status on worker shutdown.
        Requires that the calling worker owns the active lease.
        """
        try:
            return self.supabase.release_claimed_delivery_failure_event(
                event_id=event_id,
                worker_id=worker_id,
            )
        except Exception as exc:
            logger.error(f"Error releasing claimed event {event_id} for worker {worker_id}: {exc}", exc_info=True)
            return False

    release_claimed_event = release_claimed_delivery_failure_event


    def mark_event_processed(
        self,
        event_id: str,
        outcome: str = "processed",
        reason: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> bool:
        """Atomically transition event to processed or ignored."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Always keep in-memory cache in sync
        for evt in self.supabase._in_memory_delivery_failure_events.values():
            if evt.get("id") == event_id:
                evt["processing_status"] = outcome
                evt["processed_at"] = now_iso
                if reason:
                    evt["processing_error"] = reason

        if self.supabase._client and worker_id:
            try:
                res = self.supabase._client.rpc(
                    "mark_delivery_failure_event_processed",
                    {
                        "p_event_id": event_id,
                        "p_worker_id": worker_id,
                        "p_outcome": outcome,
                        "p_reason": reason
                    }
                ).execute()
                if res.data is True:
                    return True
            except Exception as e:
                logger.warning(f"Could not execute mark_delivery_failure_event_processed RPC: {e}")

        return self.supabase.update_delivery_failure_event_status(
            event_id=event_id,
            processing_status=outcome
        )

    def mark_event_failed(
        self,
        event_id: str,
        reason: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> bool:
        """Atomically transition event to failed with error reason."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Always keep in-memory cache in sync
        for evt in self.supabase._in_memory_delivery_failure_events.values():
            if evt.get("id") == event_id:
                evt["processing_status"] = "failed"
                evt["processed_at"] = now_iso
                evt["processing_error"] = reason

        if self.supabase._client and worker_id:
            try:
                res = self.supabase._client.rpc(
                    "mark_delivery_failure_event_failed",
                    {
                        "p_event_id": event_id,
                        "p_worker_id": worker_id,
                        "p_error": reason or "Unknown processing failure"
                    }
                ).execute()
                if res.data is True:
                    return True
            except Exception as e:
                logger.warning(f"Could not execute mark_delivery_failure_event_failed RPC: {e}")

        return self.supabase.update_delivery_failure_event_status(
            event_id=event_id,
            processing_status="failed"
        )

    def create_telegram_incident_log(
        self,
        delivery_failure_event_id: str,
        user_id: str,
        order_id: Optional[str],
        domain_name: Optional[str],
        store_name: Optional[str],
        triggered_reason: str,
        target_chat_id: Optional[str],
        provider_status: str = "delivered",
        provider_message_id: Optional[str] = None,
        is_simulated: bool = False,
    ) -> Dict[str, Any]:
        """
        Record a Telegram incident alert in public.failover_logs.
        Enforces idempotency index idx_failover_logs_one_telegram_incident_per_event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        sim = is_simulated or provider_status == "simulated"
        db_status = "dispatched" if sim else provider_status
        p_status = "simulated" if sim else provider_status
        delivered_ts = None if sim else (now_iso if provider_status == "delivered" else None)
        payload = {"simulated": True, "provider_status": "simulated", "mock_message_id": provider_message_id} if sim else {}

        return self.supabase.persist_failover_log(
            user_id=user_id,
            order_id=order_id or "unknown",
            channel="telegram",
            fallback_channel="telegram",
            provider="telegram",
            status=db_status,
            provider_status=p_status,
            domain_name=domain_name or "unknown",
            store_name=store_name or "unknown",
            triggered_reason=triggered_reason or "unknown",
            target_chat_id=target_chat_id,
            delivery_failure_event_id=delivery_failure_event_id,
            provider_sid=provider_message_id,
            attempted_at=now_iso,
            delivered_at=delivered_ts,
            dispatch_payload=payload,
            is_simulated=sim,
        )

    def get_transactional_message(
        self,
        esp_provider: str,
        provider_message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch matching transactional message registry entry."""
        return self.supabase.get_transactional_message(esp_provider, provider_message_id)

    def get_transactional_message_by_order_and_recipient(
        self,
        order_id: str,
        recipient_email_hash: str,
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Fetch matching transactional message registry entry by order ID and hashed recipient."""
        res = self.supabase.get_transactional_message_by_order_and_recipient(order_id, recipient_email_hash)
        if isinstance(res, tuple):
            return res
        if res is None:
            return (None, False)
        return (res, False)

    def get_unique_tenant_for_domain(self, domain_name: str) -> tuple[List[str], bool]:
        """Find candidate tenants for a domain name and determine if ambiguous."""
        return self.supabase.get_unique_tenant_for_domain(domain_name)

    def update_event_payload(self, event_id: str, event_payload: Dict[str, Any]) -> bool:
        """Update event payload in repository/database."""
        return self.supabase.update_delivery_failure_event_payload(event_id, event_payload)

    def get_tenant_defaults(self, user_id: str) -> Dict[str, Any]:
        """Fetch default domain and store name for a given user_id."""
        defaults = {"domain_name": "store.com", "store_name": "Shopify Store"}

        # Check monitored domains
        domains = self.supabase.get_user_domains(user_id)
        if domains and len(domains) > 0:
            defaults["domain_name"] = domains[0].get("domain_name", "store.com")

        # Check store profile
        stores = self.supabase.get_user_stores(user_id)
        if stores and len(stores) > 0:
            defaults["store_name"] = stores[0].get("store_name", "Shopify Store")

        return defaults


failure_event_repository = FailoverRepository()
failover_repository = failure_event_repository
failover_repo = failure_event_repository
repository = failure_event_repository
