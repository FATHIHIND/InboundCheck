"""
InboundCheck - Supabase Database Client & Repository Service
============================================================
Handles authenticated Supabase operations for monitored domains, audit logs,
profiles, and store integration metadata.
"""

from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
from supabase import create_client, Client

from app.core.config import settings

logger = logging.getLogger("SupabaseService")


class SupabaseService:
    """
    Service wrapper for Supabase database operations and multi-tenant domain persistence.
    """

    def __init__(self):
        self._client: Optional[Client] = None
        self._in_memory_domains: Dict[str, List[Dict[str, Any]]] = {}
        self._in_memory_logs: Dict[str, List[Dict[str, Any]]] = {}

        if settings.SUPABASE_URL and (settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY):
            try:
                key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
                self._client = create_client(settings.SUPABASE_URL, key)
                logger.info("Supabase client successfully initialized.")
            except Exception as e:
                logger.warning(f"Could not connect to Supabase: {e}. Falling back to memory storage.")
        else:
            logger.info("Supabase credentials not configured in env. Running with in-memory persistence.")

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def get_user_domains(self, user_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch all monitored domains for a user with pagination."""
        if self._client:
            try:
                response = (
                    self._client.table("monitored_domains")
                    .select("*")
                    .eq("user_id", user_id)
                    .order("created_at", desc=True)
                    .range(offset, offset + limit - 1)
                    .execute()
                )
                return response.data or []
            except Exception as e:
                logger.error(f"Failed to query user domains from Supabase: {e}")

        # Fallback in-memory
        all_domains = self._in_memory_domains.get(user_id, [
            {
                "id": "dom_1",
                "user_id": user_id,
                "domain_name": "brandshop.com",
                "health_score": 92,
                "spf_status": "optimal",
                "dkim_status": "optimal",
                "dmarc_status": "optimal",
                "mx_status": "optimal",
                "bimi_status": "optimal",
                "is_active": True,
                "last_checked_at": datetime.utcnow().isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            },
            {
                "id": "dom_2",
                "user_id": user_id,
                "domain_name": "checkout-orders.com",
                "health_score": 68,
                "spf_status": "warning",
                "dkim_status": "optimal",
                "dmarc_status": "warning",
                "mx_status": "optimal",
                "bimi_status": "missing",
                "is_active": True,
                "last_checked_at": datetime.utcnow().isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            }
        ])
        return all_domains[offset:offset + limit]

    def create_or_update_domain(
        self,
        user_id: str,
        domain_name: str,
        audit_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Insert or update a monitored domain."""
        domain_clean = domain_name.strip().lower()
        now_str = datetime.utcnow().isoformat()

        record = {
            "user_id": user_id,
            "domain_name": domain_clean,
            "is_active": True,
            "last_checked_at": now_str,
            "updated_at": now_str,
        }

        if audit_result:
            record.update({
                "health_score": audit_result.get("health_score", 0),
                "spf_status": audit_result.get("summary", {}).get("spf", {}).get("status", "missing"),
                "dkim_status": audit_result.get("summary", {}).get("dkim", {}).get("status", "missing"),
                "dmarc_status": audit_result.get("summary", {}).get("dmarc", {}).get("status", "missing"),
                "mx_status": audit_result.get("summary", {}).get("mx", {}).get("status", "missing"),
                "bimi_status": audit_result.get("summary", {}).get("bimi", {}).get("status", "missing"),
            })
        else:
            record.update({
                "health_score": 0,
                "spf_status": "unchecked",
                "dkim_status": "unchecked",
                "dmarc_status": "unchecked",
                "mx_status": "unchecked",
                "bimi_status": "unchecked",
            })

        if self._client:
            try:
                # Upsert into Supabase
                response = (
                    self._client.table("monitored_domains")
                    .upsert(record, on_conflict="user_id,domain_name")
                    .execute()
                )
                if response.data:
                    return response.data[0]
            except Exception as e:
                logger.error(f"Failed to upsert domain in Supabase: {e}")

        # Fallback in-memory
        if user_id not in self._in_memory_domains:
            self._in_memory_domains[user_id] = []

        existing = next((d for d in self._in_memory_domains[user_id] if d["domain_name"] == domain_clean), None)
        if existing:
            existing.update(record)
            return existing
        else:
            record["id"] = f"dom_{len(self._in_memory_domains[user_id]) + 1}_{int(datetime.utcnow().timestamp())}"
            record["created_at"] = now_str
            self._in_memory_domains[user_id].insert(0, record)
            return record

    def delete_domain(self, user_id: str, domain_id: str) -> bool:
        """Delete a monitored domain."""
        if self._client:
            try:
                self._client.table("monitored_domains").delete().eq("id", domain_id).eq("user_id", user_id).execute()
                return True
            except Exception as e:
                logger.error(f"Failed to delete domain in Supabase: {e}")

        if user_id in self._in_memory_domains:
            self._in_memory_domains[user_id] = [d for d in self._in_memory_domains[user_id] if d["id"] != domain_id]
            return True
        return False

    def save_audit_log(
        self,
        user_id: str,
        domain_id: str,
        domain_name: str,
        audit_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Record DNS audit event in public.dns_audit_logs."""
        log_entry = {
            "domain_id": domain_id,
            "user_id": user_id,
            "overall_score": audit_result.get("health_score", 0),
            "spf_record": audit_result.get("summary", {}).get("spf", {}).get("raw"),
            "dkim_record": str(audit_result.get("summary", {}).get("dkim", {}).get("found_selectors")),
            "dmarc_record": audit_result.get("summary", {}).get("dmarc", {}).get("raw"),
            "bimi_record": audit_result.get("summary", {}).get("bimi", {}).get("raw"),
            "mx_records": audit_result.get("summary", {}).get("mx", {}).get("records", []),
            "raw_dns_results": audit_result.get("raw_responses", {}),
            "issues_found": audit_result.get("issues", []),
            "recommendations": audit_result.get("fixes", []),
            "created_at": datetime.utcnow().isoformat(),
        }

        if self._client:
            try:
                response = self._client.table("dns_audit_logs").insert(log_entry).execute()
                if response.data:
                    return response.data[0]
            except Exception as e:
                logger.error(f"Failed to save audit log to Supabase: {e}")

        if domain_id not in self._in_memory_logs:
            self._in_memory_logs[domain_id] = []
        log_entry["id"] = f"log_{len(self._in_memory_logs[domain_id]) + 1}"
        self._in_memory_logs[domain_id].insert(0, log_entry)
        return log_entry


supabase_service = SupabaseService()
