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
import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.services.supabase_client import supabase_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.services.dns.rbl_scanner import rbl_scanner
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
        self._worker_id = str(uuid.uuid4())

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def run_audit_cycle(self) -> Dict[str, Any]:
        """
        Execute one complete audit pass across active monitored domains using database leases.
        Claims domains atomically with claim_due_domain_audits to prevent duplicate audits across workers.
        """
        now = datetime.now(timezone.utc)
        self._last_run_at = now
        self._total_cycles_executed += 1

        # Atomically claim due domains for this worker
        active_domains = supabase_service.claim_due_domain_audits(
            worker_id=self._worker_id,
            limit=25,
            interval_seconds=self.interval_seconds,
            lease_seconds=900
        )

        # Fallback to direct query only if claim returned empty but active domains exist (for legacy compat)
        if not active_domains:
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
                # 1. Run live DNS diagnostic audit and RBL scan concurrently with bounded safety
                dns_task = self.diagnostic_engine.audit_domain(clean_domain)
                rbl_task = rbl_scanner.scan_domain(clean_domain)
                
                # Execute concurrently; ensure RBL failure doesn't abort DNS audit
                results = await asyncio.gather(dns_task, rbl_task, return_exceptions=True)
                
                if isinstance(results[0], Exception):
                    raise results[0]
                summary, raw_responses, exec_ms = results[0]

                rbl_clean = 0
                rbl_total = len(rbl_scanner.registry)
                rbl_listed = 0
                rbl_unknown = len(rbl_scanner.registry)
                rbl_overall = "unavailable"
                rbl_result = None

                if isinstance(results[1], Exception):
                    logger.warning(f"Could not run live RBL scan for {clean_domain} in background: {results[1]}")
                else:
                    rbl_result = results[1]
                    rbl_clean = rbl_result.rbl_clean_count
                    rbl_total = rbl_result.rbl_total_count
                    rbl_listed = rbl_result.rbl_listed_count
                    rbl_unknown = rbl_result.rbl_unknown_count
                    rbl_overall = rbl_result.overall_status

                    # Persist RBL scan results to repository for auditability
                    try:
                        supabase_service.persist_rbl_scan(
                            user_id=user_id,
                            domain_name=clean_domain,
                            scan=rbl_result,
                            domain_id=domain_id if domain_id and "-" in str(domain_id) else None
                        )
                    except Exception as persist_err:
                        logger.warning(f"Failed to persist RBL scan results in background: {persist_err}")

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

                # 5. Determine risk based on measured DNS score & RBL results
                if rbl_listed > 0:
                    predicted_risk = "critical" if rbl_listed >= 2 else "high"
                elif health_score < 70 or rbl_unknown > 3:
                    predicted_risk = "medium"
                else:
                    predicted_risk = "low"

                now_iso = datetime.now(datetime.UTC).isoformat() if hasattr(datetime, "UTC") else datetime.utcnow().isoformat()
                snapshot = {
                    "domain_id": domain_id if domain_id and "-" in str(domain_id) else None,
                    "user_id": user_id,
                    "domain_name": clean_domain,
                    "score": health_score,
                    "dns_score": health_score,
                    "rbl_clean_count": rbl_clean,
                    "rbl_total_count": rbl_total,
                    "rbl_listed_count": rbl_listed,
                    "rbl_unknown_count": rbl_unknown,
                    "rbl_overall_status": rbl_overall,
                    "predicted_risk_48h": predicted_risk,
                    "created_at": now_iso
                }

                if supabase_service.is_connected:
                    try:
                        supabase_service._client.table("reputation_checks").insert(snapshot).execute()
                        snapshots_created += 1
                    except Exception as snap_err:
                        logger.warning(f"Could not insert reputation_checks record: {snap_err}")
                else:
                    if user_id not in supabase_service._in_memory_reputation:
                        supabase_service._in_memory_reputation[user_id] = []
                    supabase_service._in_memory_reputation[user_id].append(snapshot)
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

                # 7. Complete domain audit and release lease
                if domain_id:
                    supabase_service.complete_domain_audit(domain_id=domain_id, worker_id=self._worker_id)

                audited_count += 1
            except Exception as dom_err:
                logger.error(f"Error auditing domain {clean_domain} in background cycle: {dom_err}")
                if domain_id:
                    supabase_service.fail_domain_audit(
                        domain_id=domain_id,
                        worker_id=self._worker_id,
                        error=str(dom_err)
                    )

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
