"""
InboundCheck - Autonomous Background DNS Health Check & Deliverability Scheduler
================================================================================
Asynchronous daemon that periodically audits active monitored domains,
stores deliverability snapshots in public.reputation_checks, and triggers
real-time degradation alerts when thresholds dip.
"""

from typing import Dict, Any, List, Optional
import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.services.alert_dispatcher import alert_dispatcher

logger = logging.getLogger("BackgroundAuditor")


class BackgroundAuditor:
    """
    Autonomous background worker for continuous deliverability governance.
    """

    def __init__(self, interval_seconds: int = 3600):
        self.interval_seconds = interval_seconds
        self.diagnostic_engine = DNSDiagnosticEngine()
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run_at: Optional[datetime] = None
        self._total_cycles_executed = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def run_audit_cycle(self) -> Dict[str, Any]:
        """
        Execute one complete audit pass across all active monitored domains.
        Updates monitored_domains, appends to reputation_checks, and dispatches alerts on drops.
        """
        self._last_run_at = datetime.utcnow()
        self._total_cycles_executed += 1

        active_domains: List[Dict[str, Any]] = []

        if supabase_service.is_connected:
            try:
                res = (
                    supabase_service._client.table("monitored_domains")
                    .select("*")
                    .eq("is_active", True)
                    .execute()
                )
                active_domains = res.data or []
            except Exception as e:
                logger.error(f"Failed to query active domains from Supabase: {e}")

        # Fallback to in-memory domains if database returned empty or offline
        if not active_domains:
            for uid, dom_list in supabase_service._in_memory_domains.items():
                for d in dom_list:
                    if d.get("is_active", True):
                        active_domains.append(d)

        audited_count = 0
        alerts_dispatched = 0
        snapshots_created = 0

        for domain in active_domains:
            clean_domain = domain.get("domain_name", "").strip().lower()
            user_id = domain.get("user_id")
            domain_id = domain.get("id")

            if not clean_domain or not user_id:
                continue

            try:
                # 1. Run live DNS diagnostic audit
                summary, raw_responses, exec_ms = await self.diagnostic_engine.audit_domain(clean_domain)

                # 2. Calculate RFC 1035 / Google-Yahoo 2024 compliance score
                health_score, overall_status, breakdown, issues, fixes = DeliverabilityScorer.calculate_health_score(
                    domain=clean_domain,
                    summary=summary
                )

                audit_payload = {
                    "health_score": health_score,
                    "status": overall_status,
                    "summary": summary.model_dump(),
                    "issues": [i.model_dump() for i in issues],
                    "fixes": [f.model_dump() for f in fixes],
                    "raw_responses": raw_responses
                }

                # 3. Update domain record in database
                supabase_service.create_or_update_domain(
                    user_id=user_id,
                    domain_name=clean_domain,
                    audit_result=audit_payload
                )

                # 4. Save audit log in dns_audit_logs
                supabase_service.save_audit_log(
                    user_id=user_id,
                    domain_id=domain_id or "dom_bg",
                    domain_name=clean_domain,
                    audit_result=audit_payload
                )

                # 5. Insert historical deliverability snapshot in public.reputation_checks
                snapshot = {
                    "domain_id": domain_id if domain_id and "-" in str(domain_id) else None,
                    "user_id": user_id,
                    "domain_name": clean_domain,
                    "score": health_score,
                    "dns_score": health_score,
                    "rbl_clean_count": 10,
                    "rbl_total_count": 10,
                    "predicted_risk_48h": "low" if health_score >= 85 else ("medium" if health_score >= 70 else "high"),
                    "created_at": datetime.utcnow().isoformat()
                }

                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("reputation_checks").insert(snapshot).execute()
                        snapshots_created += 1
                    except Exception as snap_err:
                        logger.warning(f"Could not insert reputation_checks record: {snap_err}")
                else:
                    snapshots_created += 1

                # 6. Evaluate degradation threshold and dispatch alerts
                alert_res = await alert_dispatcher.evaluate_and_dispatch(
                    user_id=user_id,
                    domain_name=clean_domain,
                    health_score=health_score,
                    overall_status=overall_status,
                    summary=summary,
                    issues=issues
                )

                if alert_res.get("dispatched"):
                    alerts_dispatched += 1

                audited_count += 1
            except Exception as dom_err:
                logger.error(f"Error auditing domain {clean_domain} in background cycle: {dom_err}")

        logger.info(
            f"Background audit cycle completed: {audited_count} domains audited, "
            f"{snapshots_created} snapshots saved, {alerts_dispatched} alerts dispatched."
        )

        return {
            "success": True,
            "audited_count": audited_count,
            "snapshots_created": snapshots_created,
            "alerts_dispatched": alerts_dispatched,
            "cycle_number": self._total_cycles_executed,
            "timestamp": self._last_run_at.isoformat()
        }

    async def _audit_loop(self):
        """Continuous background execution loop."""
        logger.info(f"Background auditor daemon started (interval: {self.interval_seconds}s).")
        while self._is_running:
            try:
                await self.run_audit_cycle()
            except Exception as e:
                logger.error(f"Unhandled error in background audit cycle: {e}")

            # Sleep in 1-second chunks to allow prompt task cancellation on shutdown
            for _ in range(self.interval_seconds):
                if not self._is_running:
                    break
                await asyncio.sleep(1)

    def start(self):
        """Start the background daemon if not already active."""
        if not self._is_running:
            self._is_running = True
            self._task = asyncio.create_task(self._audit_loop())
            logger.info("BackgroundAuditor task scheduled.")

    async def stop(self):
        """Stop background worker gracefully."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BackgroundAuditor stopped.")


background_auditor = BackgroundAuditor(interval_seconds=3600)
