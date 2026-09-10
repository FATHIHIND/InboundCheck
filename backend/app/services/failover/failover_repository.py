"""
InboundCheck - Failover & Delivery Failure Repository (Phase 4 Step 5)
======================================================================
Database access layer for claiming delivery failure events, updating state transitions,
looking up transactional message registry records, and creating idempotent Telegram incident logs.
"""

from typing import List, Dict, Any, Optional
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
    ) -> List[Dict[str, Any]]:
        """
        Atomically claim received delivery failure events using claim_pending_delivery_failure_events RPC.
        Transitions received -> queued using FOR UPDATE SKIP LOCKED.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        if self.supabase._client:
            try:
                res = self.supabase._client.rpc(
                    "claim_pending_delivery_failure_events",
                    {
                        "p_worker_id": worker_id,
                        "p_limit": limit
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
                    return res.data
            except Exception as e:
                logger.warning(f"Could not execute claim_pending_delivery_failure_events RPC: {e}")

        # In-memory fallback for local development and testing
        return self.supabase.claim_pending_delivery_failure_events(worker_id=worker_id, limit=limit)

    claim_received_delivery_failure_events = claim_pending_delivery_failure_events

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
    ) -> Dict[str, Any]:
        """
        Record a Telegram incident alert in public.failover_logs.
        Enforces idempotency index idx_failover_logs_one_telegram_incident_per_event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        return self.supabase.persist_failover_log(
            user_id=user_id,
            order_id=order_id or "unknown",
            channel="telegram",
            fallback_channel="telegram",
            provider="telegram",
            status=provider_status,
            provider_status=provider_status,
            domain_name=domain_name or "unknown",
            store_name=store_name or "unknown",
            triggered_reason=triggered_reason or "unknown",
            target_chat_id=target_chat_id,
            delivery_failure_event_id=delivery_failure_event_id,
            provider_sid=provider_message_id,
            attempted_at=now_iso,
            delivered_at=now_iso if provider_status == "delivered" else None,
        )

    def get_transactional_message(
        self,
        esp_provider: str,
        provider_message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch matching transactional message registry entry."""
        return self.supabase.get_transactional_message(esp_provider, provider_message_id)

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
repository = failure_event_repository
