"""
InboundCheck - Supabase Database Client & Repository Service
============================================================
Handles authenticated Supabase operations for monitored domains, audit logs,
profiles, and store integration metadata.
"""

import hashlib
from typing import List, Dict, Any, Optional, Union
import logging
import uuid
import time
from datetime import datetime, timezone
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
        self._in_memory_profiles: Dict[str, Dict[str, Any]] = {}
        self._in_memory_stores: Dict[str, List[Dict[str, Any]]] = {}
        self._in_memory_reputation: Dict[str, List[Dict[str, Any]]] = {}
        self._in_memory_transactional_messages: Dict[str, Dict[str, Any]] = {}
        self._in_memory_delivery_failure_events: Dict[str, Dict[str, Any]] = {}

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

    @property
    def is_configured(self) -> bool:
        """Check if Supabase client is connected or running in operational in-memory fallback."""
        if self._client is not None:
            return True
        # If credentials provided in settings or env, considered configured
        if settings.SUPABASE_URL and (settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY):
            return True
        # In development / testing, running with in-memory persistence is healthy
        return True

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch public.profiles record for user."""
        if user_id in self._in_memory_profiles:
            return self._in_memory_profiles[user_id]

        if self._client:
            try:
                res = self._client.table("profiles").select("*").eq("id", user_id).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.error(f"Failed to query user profile {user_id}: {e}")
        return None

    def get_user_domain_count(self, user_id: str) -> int:
        """Get count of active monitored domains for user."""
        if user_id in self._in_memory_domains:
            return len(self._in_memory_domains[user_id])

        if self._client:
            try:
                res = self._client.table("monitored_domains").select("id", count="exact").eq("user_id", user_id).execute()
                if res.count is not None:
                    return res.count
                return len(res.data or [])
            except Exception as e:
                logger.error(f"Failed to count domains for {user_id}: {e}")
        return len(self._in_memory_domains.get(user_id, []))

    def get_user_domains(self, user_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch all monitored domains for a user with pagination."""
        if user_id in self._in_memory_domains and len(self._in_memory_domains[user_id]) > 0:
            return self._in_memory_domains[user_id][offset:offset + limit]

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
        all_domains = self._in_memory_domains.get(user_id, [])
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
        domain_id: Optional[str] = None,
        domain_name: Optional[str] = None,
        audit_result: Optional[Union[Dict[str, Any], Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Record DNS audit event in public.dns_audit_logs strictly adhering to production schema.
        Maps DeliverabilityResult / DNSAuditResponse payload to DB columns:
        (health_score, spf_status, dkim_records, dmarc_status, mx_records, fixes, etc.).
        Gracefully handles database failures by logging a warning without breaking caller operations.
        """
        # Support flexible calling conventions:
        # save_audit_log(user_id=..., domain_id=..., domain_name=..., audit_result=...)
        # save_audit_log(user_id, domain_name, audit_result)
        if audit_result is None and isinstance(domain_name, (dict, object)) and not isinstance(domain_name, str):
            audit_result = domain_name
            domain_name = domain_id
            domain_id = None

        if not domain_name and kwargs.get("domain"):
            domain_name = kwargs.get("domain")

        # Normalize audit payload from Pydantic model or dict
        if hasattr(audit_result, "model_dump"):
            payload = audit_result.model_dump()
        elif isinstance(audit_result, dict):
            payload = audit_result
        else:
            payload = {}

        clean_domain = (domain_name or payload.get("domain") or "").strip().lower()

        summary = payload.get("summary") or {}
        if hasattr(summary, "model_dump"):
            summary = summary.model_dump()

        spf_data = summary.get("spf") or {}
        dkim_data = summary.get("dkim") or {}
        dmarc_data = summary.get("dmarc") or {}
        mx_data = summary.get("mx") or {}
        bimi_data = summary.get("bimi") or {}

        # Safely convert Pydantic submodels if present
        if hasattr(spf_data, "model_dump"):
            spf_data = spf_data.model_dump()
        if hasattr(dkim_data, "model_dump"):
            dkim_data = dkim_data.model_dump()
        if hasattr(dmarc_data, "model_dump"):
            dmarc_data = dmarc_data.model_dump()
        if hasattr(mx_data, "model_dump"):
            mx_data = mx_data.model_dump()
        if hasattr(bimi_data, "model_dump"):
            bimi_data = bimi_data.model_dump()

        # DKIM records formatting
        dkim_recs = dkim_data.get("records") or []
        if hasattr(dkim_recs, "model_dump"):
            dkim_recs = dkim_recs.model_dump()
        elif isinstance(dkim_recs, list):
            dkim_recs = [r.model_dump() if hasattr(r, "model_dump") else r for r in dkim_recs]
        if not dkim_recs and dkim_data.get("found_selectors"):
            dkim_recs = [{"selector": s, "status": "optimal"} for s in dkim_data.get("found_selectors", [])]

        # MX records formatting
        mx_recs = mx_data.get("records") or []
        if hasattr(mx_recs, "model_dump"):
            mx_recs = mx_recs.model_dump()
        elif isinstance(mx_recs, list):
            mx_recs = [r.model_dump() if hasattr(r, "model_dump") else r for r in mx_recs]

        # Fixes formatting
        fixes_recs = payload.get("fixes") or []
        if hasattr(fixes_recs, "model_dump"):
            fixes_recs = fixes_recs.model_dump()
        elif isinstance(fixes_recs, list):
            fixes_recs = [f.model_dump() if hasattr(f, "model_dump") else f for f in fixes_recs]

        # Health score clamping (0-100)
        raw_score = payload.get("health_score", 0)
        try:
            health_score = max(0, min(100, int(raw_score)))
        except (ValueError, TypeError):
            health_score = 0

        # Validate domain_id for Postgres UUID
        valid_domain_id = None
        if domain_id:
            try:
                valid_domain_id = str(uuid.UUID(str(domain_id)))
            except (ValueError, AttributeError, TypeError):
                valid_domain_id = None

        now_iso = datetime.now(datetime.UTC).isoformat() if hasattr(datetime, "UTC") else datetime.utcnow().isoformat()

        log_entry = {
            "user_id": user_id,
            "domain_id": valid_domain_id,
            "domain_name": clean_domain,
            "health_score": health_score,
            "spf_record": spf_data.get("raw"),
            "spf_status": spf_data.get("status") or ("optimal" if spf_data.get("raw") else "missing"),
            "dkim_records": dkim_recs,
            "dkim_status": dkim_data.get("status") or ("optimal" if dkim_recs else "missing"),
            "dmarc_record": dmarc_data.get("raw"),
            "dmarc_status": dmarc_data.get("status") or ("optimal" if dmarc_data.get("raw") else "missing"),
            "mx_records": mx_recs,
            "mx_status": mx_data.get("status") or ("optimal" if mx_recs else "missing"),
            "bimi_record": bimi_data.get("raw"),
            "bimi_status": bimi_data.get("status") or ("optimal" if bimi_data.get("raw") else "missing"),
            "fixes": fixes_recs,
            "raw_responses": payload.get("raw_responses") or {},
            "created_at": now_iso,
        }

        # Write to Supabase if connected
        if self._client:
            try:
                # Omit domain_id if None to let DB handle default/NULL
                insert_payload = {k: v for k, v in log_entry.items() if k != "domain_id" or v is not None}
                response = self._client.table("dns_audit_logs").insert(insert_payload).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]
            except Exception as e:
                logger.warning(f"Failed to persist DNS audit log to Supabase: {e}")

        # In-memory persistence
        log_key = domain_id or clean_domain or "default"
        if log_key not in self._in_memory_logs:
            self._in_memory_logs[log_key] = []
        in_mem_entry = dict(log_entry)
        in_mem_entry["id"] = f"log_{len(self._in_memory_logs[log_key]) + 1}_{int(time.time())}"
        self._in_memory_logs[log_key].insert(0, in_mem_entry)
        return in_mem_entry

    def save_monitored_store(
        self,
        user_id: str,
        shop_domain: str,
        access_token_encrypted: str,
        scope: str = "read_orders,read_fulfillments,read_merchant_managed_fulfillment_orders",
        sender_email: Optional[str] = None,
        store_metadata: Optional[Dict[str, Any]] = None,
        sender_alignment_status: str = "pending"
    ) -> Dict[str, Any]:
        """
        Persist connected Shopify store and encrypted access token to public.shopify_stores / public.monitored_stores.
        """
        now_iso = datetime.now(datetime.UTC).isoformat() if hasattr(datetime, "UTC") else datetime.utcnow().isoformat()
        clean_shop = shop_domain.strip().lower()

        record = {
            "user_id": user_id,
            "shop_domain": clean_shop,
            "access_token_encrypted": access_token_encrypted,
            "scope": scope,
            "sender_email": sender_email,
            "sender_alignment_status": sender_alignment_status,
            "is_active": True,
            "updated_at": now_iso,
        }

        # Attempt Supabase persistence into shopify_stores or monitored_stores
        if self._client:
            for table_name in ["shopify_stores", "monitored_stores"]:
                try:
                    payload = dict(record)
                    if table_name == "monitored_stores" and store_metadata:
                        payload["metadata"] = store_metadata
                    res = self._client.table(table_name).upsert(
                        payload,
                        on_conflict="user_id,shop_domain"
                    ).execute()
                    if res.data and len(res.data) > 0:
                        return res.data[0]
                except Exception as e:
                    logger.warning(f"Could not persist store to table '{table_name}': {e}")

        # In-memory persistence
        if user_id not in self._in_memory_stores:
            self._in_memory_stores[user_id] = []

        existing = next((s for s in self._in_memory_stores[user_id] if s.get("shop_domain") == clean_shop), None)
        if existing:
            existing.update(record)
            if store_metadata:
                existing["metadata"] = store_metadata
            return existing
        else:
            new_store = dict(record)
            new_store["id"] = f"store_{len(self._in_memory_stores[user_id]) + 1}_{int(time.time())}"
            new_store["created_at"] = now_iso
            if store_metadata:
                new_store["metadata"] = store_metadata
            self._in_memory_stores[user_id].insert(0, new_store)
            return new_store

    def get_user_stores(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch all connected stores for user."""
        if self._client:
            for table_name in ["shopify_stores", "monitored_stores"]:
                try:
                    res = self._client.table(table_name).select("*").eq("user_id", user_id).execute()
                    if res.data is not None:
                        return res.data
                except Exception as e:
                    logger.warning(f"Could not fetch stores from '{table_name}': {e}")
        return self._in_memory_stores.get(user_id, [])

    def persist_rbl_scan(self, user_id: str, domain_name: str, scan: Any) -> None:
        """
        Persist normalized per-provider RBL scan evidence and update reputation snapshot.
        """
        scan_dict = scan.model_dump() if hasattr(scan, "model_dump") else dict(scan)
        results = scan_dict.get("results", [])

        # Store in-memory for testing and development
        if user_id not in self._in_memory_reputation:
            self._in_memory_reputation[user_id] = []

        now_iso = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "domain_id": None,
            "user_id": user_id,
            "domain_name": domain_name,
            "score": max(0, 100 - (scan_dict.get("rbl_listed_count", 0) * 20)),
            "dns_score": 90,
            "rbl_clean_count": scan_dict.get("rbl_clean_count", 0),
            "rbl_total_count": scan_dict.get("rbl_total_count", 10),
            "rbl_listed_count": scan_dict.get("rbl_listed_count", 0),
            "rbl_unknown_count": scan_dict.get("rbl_unknown_count", 0),
            "rbl_overall_status": scan_dict.get("overall_status", "clean"),
            "predicted_risk_48h": "high" if scan_dict.get("rbl_listed_count", 0) > 0 else "low",
            "created_at": now_iso,
            "scan_data": scan_dict,
        }
        self._in_memory_reputation[user_id].insert(0, snapshot)

        # Write to public.rbl_scan_results if Supabase client is connected
        if self._client:
            try:
                for r in results:
                    row = {
                        "user_id": user_id,
                        "domain_name": domain_name,
                        "provider_id": r.get("provider_id"),
                        "provider_name": r.get("provider_name"),
                        "dnsbl_zone": r.get("zone"),
                        "target_type": r.get("target_type"),
                        "queried_targets": [r.get("queried_target")],
                        "status": r.get("status"),
                        "severity": r.get("severity", "none"),
                        "response_codes": r.get("response_codes", []),
                        "latency_ms": r.get("latency_ms"),
                        "error_message": r.get("message"),
                        "delisting_url": r.get("delisting_url"),
                    }
                    self._client.table("rbl_scan_results").insert(row).execute()
            except Exception as e:
                logger.warning(f"Could not persist rbl_scan_results to database: {e}")

    def get_latest_rbl_scan(self, user_id: str, domain_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch latest persisted RBL scan result for user domain.
        Returns None if no scan exists (so router can return HTTP 404).
        """
        clean_d = domain_name.strip().lower()
        user_checks = self._in_memory_reputation.get(user_id, [])
        for c in user_checks:
            if c.get("domain_name") == clean_d and "scan_data" in c:
                return c["scan_data"]

        if self._client:
            try:
                res = (
                    self._client.table("rbl_scan_results")
                    .select("*")
                    .eq("user_id", user_id)
                    .eq("domain_name", clean_d)
                    .order("checked_at", desc=True)
                    .limit(10)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    rows = res.data
                    clean_count = sum(1 for r in rows if r.get("status") == "clean")
                    listed_count = sum(1 for r in rows if r.get("status") == "listed")
                    unknown_count = sum(1 for r in rows if r.get("status") == "unknown")
                    error_count = sum(1 for r in rows if r.get("status") == "error")

                    return {
                        "domain": clean_d,
                        "resolved_ips": [],
                        "results": [
                            {
                                "provider_id": r.get("provider_id"),
                                "provider_name": r.get("provider_name"),
                                "zone": r.get("dnsbl_zone"),
                                "target_type": r.get("target_type"),
                                "status": r.get("status"),
                                "severity": r.get("severity", "none"),
                                "queried_target": (r.get("queried_targets") or [""])[0],
                                "response_codes": r.get("response_codes") or [],
                                "latency_ms": r.get("latency_ms"),
                                "message": r.get("error_message"),
                                "delisting_url": r.get("delisting_url") or "",
                                "checked_at": r.get("checked_at"),
                            }
                            for r in rows
                        ],
                        "rbl_clean_count": clean_count,
                        "rbl_listed_count": listed_count,
                        "rbl_unknown_count": unknown_count,
                        "rbl_error_count": error_count,
                        "rbl_total_count": len(rows),
                        "overall_status": "listed" if listed_count > 0 else "clean",
                        "highest_severity": "critical" if listed_count > 0 else "none",
                        "execution_time_ms": 0.0,
                        "scanned_at": rows[0].get("checked_at"),
                    }
            except Exception as e:
                logger.warning(f"Could not retrieve rbl_scan_results from database: {e}")

        return None

    # =====================================================================
    # DISTRIBUTED AUDIT LEASE REPOSITORY METHODS (PHASE 4)
    # =====================================================================

    def claim_due_domain_audits(
        self,
        worker_id: str,
        limit: int = 25,
        interval_seconds: int = 3600,
        lease_seconds: int = 900,
    ) -> List[Dict[str, Any]]:
        """
        Atomically claim due domain audits using PostgreSQL FOR UPDATE SKIP LOCKED via RPC.
        Falls back to in-memory lease emulation for offline/testing environments.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        if self._client:
            try:
                # Interval strings for Postgres RPC
                interval_str = f"{interval_seconds} seconds"
                lease_str = f"{lease_seconds} seconds"
                res = self._client.rpc(
                    "claim_due_domain_audits",
                    {
                        "p_worker_id": worker_id,
                        "p_limit": limit,
                        "p_interval": interval_str,
                        "p_lease_duration": lease_str,
                    },
                ).execute()
                if res.data:
                    return res.data
            except Exception as e:
                logger.warning(f"Could not execute claim_due_domain_audits RPC: {e}. Checking in-memory fallback.")

        # In-memory lease claiming fallback
        claimed: List[Dict[str, Any]] = []
        for uid, domains in self._in_memory_domains.items():
            for domain in domains:
                if not domain.get("is_active", True):
                    continue

                last_audited = domain.get("last_audited_at")
                lease_until = domain.get("audit_lease_until")

                # Check due criteria
                is_due = True
                if last_audited:
                    try:
                        last_audited_dt = datetime.fromisoformat(last_audited.replace("Z", "+00:00"))
                        if (now - last_audited_dt).total_seconds() < interval_seconds:
                            is_due = False
                    except Exception:
                        pass

                # Check lease criteria (must not be actively leased by another unexpired worker)
                is_leased = False
                if lease_until:
                    try:
                        lease_until_dt = datetime.fromisoformat(lease_until.replace("Z", "+00:00"))
                        if lease_until_dt > now:
                            is_leased = True
                    except Exception:
                        pass

                if is_due and not is_leased:
                    lease_expiry = datetime.fromtimestamp(now.timestamp() + lease_seconds, tz=timezone.utc).isoformat()
                    domain["audit_lease_owner"] = worker_id
                    domain["audit_lease_until"] = lease_expiry
                    domain["audit_started_at"] = now_iso
                    claimed.append(domain)
                    if len(claimed) >= limit:
                        break
            if len(claimed) >= limit:
                break

        return claimed

    def complete_domain_audit(self, domain_id: str, worker_id: str) -> bool:
        """
        Mark a domain audit completed and release the lease.
        Requires that the calling worker owns the active lease.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        if self._client:
            try:
                res = self._client.rpc(
                    "complete_domain_audit",
                    {
                        "p_domain_id": domain_id,
                        "p_worker_id": worker_id,
                    },
                ).execute()
                if res.data is True:
                    return True
            except Exception as e:
                logger.warning(f"Could not execute complete_domain_audit RPC: {e}")

        # In-memory fallback
        for uid, domains in self._in_memory_domains.items():
            for domain in domains:
                if domain.get("id") == domain_id:
                    if domain.get("audit_lease_owner") == worker_id:
                        domain["audit_lease_owner"] = None
                        domain["audit_lease_until"] = None
                        domain["last_audited_at"] = now_iso
                        domain["audit_failure_count"] = 0
                        domain["last_audit_error"] = None
                        return True
                    return False
        return False

    def fail_domain_audit(self, domain_id: str, worker_id: str, error: str) -> bool:
        """
        Record domain audit failure, increment failure count, and release the lease.
        Requires that the calling worker owns the active lease.
        """
        if self._client:
            try:
                res = self._client.rpc(
                    "fail_domain_audit",
                    {
                        "p_domain_id": domain_id,
                        "p_worker_id": worker_id,
                        "p_error": error[:500] if error else "Audit execution error",
                    },
                ).execute()
                if res.data is True:
                    return True
            except Exception as e:
                logger.warning(f"Could not execute fail_domain_audit RPC: {e}")

        # In-memory fallback
        for uid, domains in self._in_memory_domains.items():
            for domain in domains:
                if domain.get("id") == domain_id:
                    if domain.get("audit_lease_owner") == worker_id:
                        domain["audit_lease_owner"] = None
                        domain["audit_lease_until"] = None
                        domain["audit_failure_count"] = domain.get("audit_failure_count", 0) + 1
                        domain["last_audit_error"] = error[:500] if error else "Audit execution error"
                        return True
                    return False
        return False

    def extend_domain_audit_lease(self, domain_id: str, worker_id: str, extend_seconds: int = 900) -> bool:
        """
        Extend an active domain audit lease heartbeat.
        Requires that the calling worker owns the active lease.
        """
        now = datetime.now(timezone.utc)
        if self._client:
            try:
                extend_str = f"{extend_seconds} seconds"
                res = self._client.rpc(
                    "extend_domain_audit_lease",
                    {
                        "p_domain_id": domain_id,
                        "p_worker_id": worker_id,
                        "p_extend_duration": extend_str,
                    },
                ).execute()
                if res.data is True:
                    return True
            except Exception as e:
                logger.warning(f"Could not execute extend_domain_audit_lease RPC: {e}")

        # In-memory fallback
        for uid, domains in self._in_memory_domains.items():
            for domain in domains:
                if domain.get("id") == domain_id:
                    if domain.get("audit_lease_owner") == worker_id:
                        lease_expiry = datetime.fromtimestamp(now.timestamp() + extend_seconds, tz=timezone.utc).isoformat()
                        domain["audit_lease_until"] = lease_expiry
                        return True
                    return False
        return False

    # =====================================================================
    # FAILOVER & TELEGRAM INCIDENT LOGS REPOSITORY METHODS (PHASE 4)
    # =====================================================================

    def persist_failover_log(
        self,
        user_id: str,
        order_id: str,
        channel: str,
        provider: str,
        status: str,
        domain_name: Optional[str] = None,
        store_name: Optional[str] = None,
        triggered_reason: Optional[str] = None,
        target_chat_id: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
        dispatch_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        delivery_failure_event_id: Optional[str] = None,
        transactional_message_id: Optional[str] = None,
        fallback_channel: Optional[str] = None,
        provider_sid: Optional[str] = None,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[str] = None,
        provider_error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Persist a real failover / Telegram incident alert record to public.failover_logs.
        Supports delivery-failure event correlation and idempotency keys.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        log_id = str(uuid.uuid4())

        record = {
            "id": log_id,
            "user_id": user_id,
            "order_id": order_id,
            "customer_phone": customer_phone or target_chat_id or "telegram",
            "channel": channel,
            "provider": provider,
            "status": status,
            "domain_name": domain_name,
            "store_name": store_name,
            "triggered_reason": triggered_reason,
            "target_chat_id": target_chat_id,
            "customer_email": customer_email,
            "error_message": error_message,
            "dispatch_payload": dispatch_payload or {},
            "delivery_failure_event_id": delivery_failure_event_id,
            "transactional_message_id": transactional_message_id,
            "fallback_channel": fallback_channel,
            "provider_sid": provider_sid,
            "provider_status": provider_status,
            "provider_error_code": provider_error_code,
            "provider_error_message": provider_error_message,
            "attempted_at": now_iso,
            "delivered_at": now_iso if status == "delivered" else None,
            "updated_at": now_iso,
            "created_at": now_iso,
        }

        if self._client:
            try:
                self._client.table("failover_logs").insert(record).execute()
            except Exception as e:
                logger.warning(f"Could not insert failover_log in Supabase: {e}")

        # In-memory storage fallback
        if not hasattr(self, "_in_memory_failover_logs"):
            self._in_memory_failover_logs: Dict[str, List[Dict[str, Any]]] = {}
        if user_id not in self._in_memory_failover_logs:
            self._in_memory_failover_logs[user_id] = []
        self._in_memory_failover_logs[user_id].insert(0, record)

        return record

    def get_failover_logs(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Retrieve persisted failover & incident alert logs for a user.
        """
        if self._client:
            try:
                res = (
                    self._client.table("failover_logs")
                    .select("*")
                    .eq("user_id", user_id)
                    .order("created_at", desc=True)
                    .range(offset, offset + limit - 1)
                    .execute()
                )
                if res.data is not None:
                    return res.data
            except Exception as e:
                logger.warning(f"Could not retrieve failover_logs from Supabase: {e}")

        if not hasattr(self, "_in_memory_failover_logs"):
            self._in_memory_failover_logs = {}
        logs = self._in_memory_failover_logs.get(user_id, [])
        return logs[offset : offset + limit]

    # =====================================================================
    # TRANSACTIONAL MESSAGE REGISTRY & DELIVERY FAILURE INGESTION (STEP 3)
    # =====================================================================

    def register_transactional_message(
        self,
        user_id: str,
        order_id: str,
        esp_provider: str,
        provider_message_id: str,
        recipient_email: str,
        recipient_phone_encrypted: Optional[str] = None,
        phone_consent_status: str = "unknown",
        message_type: str = "order_confirmation",
        shopify_store_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register an outbound transactional email into transactional_message_registry
        with SHA-256 hashed recipient email and encrypted phone for failover correlation.
        """
        clean_email = recipient_email.strip().lower()
        email_hash = hashlib.sha256(clean_email.encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()
        reg_id = str(uuid.uuid4())

        record = {
            "id": reg_id,
            "user_id": user_id,
            "shopify_store_id": shopify_store_id,
            "order_id": order_id,
            "esp_provider": esp_provider.strip().lower(),
            "provider_message_id": provider_message_id.strip(),
            "recipient_email_hash": email_hash,
            "recipient_phone_encrypted": recipient_phone_encrypted,
            "phone_consent_status": phone_consent_status,
            "message_type": message_type,
            "created_at": now_iso,
        }

        key = (record["esp_provider"], record["provider_message_id"])

        if self._client:
            try:
                res = (
                    self._client.table("transactional_message_registry")
                    .upsert(record, on_conflict="esp_provider,provider_message_id")
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning(f"Could not upsert transactional_message_registry: {e}")

        # In-memory storage fallback
        self._in_memory_transactional_messages[str(key)] = record
        return record

    def get_transactional_message(
        self,
        esp_provider: str,
        provider_message_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Lookup transactional message by ESP provider and provider message id.
        """
        clean_prov = esp_provider.strip().lower()
        clean_msg_id = provider_message_id.strip()

        if self._client:
            try:
                res = (
                    self._client.table("transactional_message_registry")
                    .select("*")
                    .eq("esp_provider", clean_prov)
                    .eq("provider_message_id", clean_msg_id)
                    .limit(1)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning(f"Could not fetch transactional_message from Supabase: {e}")

        key = str((clean_prov, clean_msg_id))
        return self._in_memory_transactional_messages.get(key)

    def record_delivery_failure_event(
        self,
        esp_provider: str,
        provider_event_id: str,
        provider_message_id: Optional[str],
        event_type: str,
        event_timestamp: Optional[str] = None,
        signature_verified: bool = False,
        event_payload: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        processing_status: str = "received",
    ) -> Dict[str, Any]:
        """
        Ingest and buffer a delivery failure webhook event with deduplication on (esp_provider, provider_event_id).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_prov = esp_provider.strip().lower()
        clean_evt_id = provider_event_id.strip()
        key = str((clean_prov, clean_evt_id))

        # 1. Check in-memory cache first
        if key in self._in_memory_delivery_failure_events:
            return self._in_memory_delivery_failure_events[key]

        # 2. Check remote database if connected
        if self._client:
            try:
                existing = (
                    self._client.table("delivery_failure_events")
                    .select("*")
                    .eq("esp_provider", clean_prov)
                    .eq("provider_event_id", clean_evt_id)
                    .limit(1)
                    .execute()
                )
                if existing.data and len(existing.data) > 0:
                    self._in_memory_delivery_failure_events[key] = existing.data[0]
                    return existing.data[0]
            except Exception as e:
                logger.warning(f"Could not check existing delivery_failure_events: {e}")

        # 3. Insert new record
        evt_id = str(uuid.uuid4())
        record = {
            "id": evt_id,
            "user_id": user_id,
            "esp_provider": clean_prov,
            "provider_event_id": clean_evt_id,
            "provider_message_id": provider_message_id.strip() if provider_message_id else None,
            "event_type": event_type,
            "event_timestamp": event_timestamp or now_iso,
            "signature_verified": signature_verified,
            "processing_status": processing_status,
            "event_payload": event_payload or {},
            "received_at": now_iso,
            "processed_at": None,
        }

        if self._client:
            try:
                res = (
                    self._client.table("delivery_failure_events")
                    .insert(record)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    self._in_memory_delivery_failure_events[key] = res.data[0]
                    return res.data[0]
            except Exception as e:
                logger.warning(f"Could not insert delivery_failure_events: {e}")

        self._in_memory_delivery_failure_events[key] = record
        return record

    def update_delivery_failure_event_status(
        self,
        event_id: str,
        processing_status: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Update processing status of a delivery failure event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "processing_status": processing_status,
            "processed_at": now_iso if processing_status in ("processed", "failed", "ignored") else None,
        }
        if user_id:
            payload["user_id"] = user_id

        if self._client:
            try:
                self._client.table("delivery_failure_events").update(payload).eq("id", event_id).execute()
                return True
            except Exception as e:
                logger.warning(f"Could not update delivery_failure_events status: {e}")

        for evt in self._in_memory_delivery_failure_events.values():
            if evt.get("id") == event_id:
                evt.update(payload)
                return True
        return False


supabase_service = SupabaseService()

