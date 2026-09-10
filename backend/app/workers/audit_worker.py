"""
InboundCheck - Dedicated Distributed Audit Worker (Phase 4)
============================================================
Autonomous worker daemon that claims due domains using database-level
leases (FOR UPDATE SKIP LOCKED), executes concurrent multi-resolver DNS
and RBL blacklists audits, and releases leases upon completion or failure.
"""

import asyncio
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.services.supabase_client import supabase_service
from app.services.dns.diagnostic_engine import DNSDiagnosticEngine
from app.services.dns.scorer import DeliverabilityScorer
from app.services.dns.rbl_scanner import rbl_scanner
from app.services.alert_dispatcher import alert_dispatcher

logger = logging.getLogger("AuditWorker")

diagnostic_engine = DNSDiagnosticEngine()


def sanitize_error(exc: Exception) -> str:
    """
    Sanitize exception message to prevent storing raw credentials, API tokens,
    or verbose third-party payload dumps in the database.
    """
    msg = str(exc).strip()
    # Mask common sensitive patterns
    msg = re.sub(r"(token|key|secret|password|bearer)[=:\s]+[A-Za-z0-9_\-\.]+", r"\1=[REDACTED]", msg, flags=re.IGNORECASE)
    # Truncate to compact length
    return msg[:500] if len(msg) > 500 else (msg or "Unknown audit execution failure")


async def audit_claimed_domain(domain: Dict[str, Any], worker_id: str) -> None:
    """
    Execute live DNS and RBL audits for a leased domain, persist telemetry,
    and release the lease upon completion or failure.
    """
    clean_domain = domain.get("domain_name", "").strip().lower()
    user_id = domain.get("user_id")
    domain_id = domain.get("id")

    if not clean_domain or not user_id or not domain_id:
        logger.warning(f"Skipping invalid domain record: {domain}")
        return

    try:
        # 1. Execute live DNS diagnostics and RBL scan concurrently
        dns_task = diagnostic_engine.audit_domain(clean_domain)
        rbl_task = rbl_scanner.scan_domain(clean_domain)

        results = await asyncio.gather(dns_task, rbl_task, return_exceptions=True)

        if isinstance(results[0], Exception):
            raise results[0]
        summary, raw_responses, exec_ms = results[0]

        rbl_clean = 0
        rbl_total = len(rbl_scanner.registry)
        rbl_listed = 0
        rbl_unknown = len(rbl_scanner.registry)
        rbl_overall = "unavailable"

        if isinstance(results[1], Exception):
            logger.warning(f"RBL scan warning for {clean_domain}: {results[1]}")
        else:
            rbl_result = results[1]
            rbl_clean = rbl_result.rbl_clean_count
            rbl_total = rbl_result.rbl_total_count
            rbl_listed = rbl_result.rbl_listed_count
            rbl_unknown = rbl_result.rbl_unknown_count
            rbl_overall = rbl_result.overall_status

            # Persist RBL scan snapshot
            try:
                supabase_service.persist_rbl_scan(
                    user_id=user_id,
                    domain_name=clean_domain,
                    scan=rbl_result,
                    domain_id=domain_id if domain_id and "-" in str(domain_id) else None
                )
            except Exception as persist_err:
                logger.warning(f"Failed to persist RBL scan results for {clean_domain}: {persist_err}")

        # 2. Compute Google-Yahoo 2024 compliance score
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

        # 3. Update domain record and save audit log
        supabase_service.create_or_update_domain(
            user_id=user_id,
            domain_name=clean_domain,
            audit_result=audit_payload
        )
        supabase_service.save_audit_log(
            user_id=user_id,
            domain_id=domain_id,
            domain_name=clean_domain,
            audit_result=audit_payload
        )

        # 4. Save reputation checks snapshot
        if rbl_listed > 0:
            predicted_risk = "critical" if rbl_listed >= 2 else "high"
        elif health_score < 70 or rbl_unknown > 3:
            predicted_risk = "medium"
        else:
            predicted_risk = "low"

        now_iso = datetime.now(timezone.utc).isoformat()
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
            except Exception as snap_err:
                logger.warning(f"Could not insert reputation_checks record: {snap_err}")
        else:
            if user_id not in supabase_service._in_memory_reputation:
                supabase_service._in_memory_reputation[user_id] = []
            supabase_service._in_memory_reputation[user_id].append(snapshot)

        # 5. Evaluate degradation thresholds and dispatch merchant alerts
        try:
            await alert_dispatcher.evaluate_and_dispatch(
                user_id=user_id,
                domain_name=clean_domain,
                health_score=health_score,
                overall_status=overall_status,
                summary=summary,
                issues=issues
            )
        except Exception as alert_err:
            logger.warning(f"Alert evaluation failed for {clean_domain}: {alert_err}")

        # 6. Complete domain audit and release lease
        completed = supabase_service.complete_domain_audit(
            domain_id=domain_id,
            worker_id=worker_id
        )

        if not completed:
            logger.warning(f"Lease lost before audit completion for domain {clean_domain} ({domain_id})")
        else:
            logger.info(f"Audit completed successfully for {clean_domain} (score: {health_score})")

    except Exception as exc:
        sanitized = sanitize_error(exc)
        logger.error(f"Audit failed for domain {clean_domain}: {sanitized}")
        supabase_service.fail_domain_audit(
            domain_id=domain_id,
            worker_id=worker_id,
            error=sanitized
        )


async def run_audit_worker(
    stop_event: Optional[asyncio.Event] = None,
    limit: int = 25,
    interval_seconds: int = 3600,
    lease_seconds: int = 900,
    idle_sleep_seconds: int = 30
) -> None:
    """
    Continuous audit worker loop claiming due domains atomically.
    Supports graceful termination via stop_event.
    """
    worker_id = str(uuid.uuid4())
    logger.info(f"Audit worker started [Worker ID: {worker_id}] (interval: {interval_seconds}s, lease: {lease_seconds}s)")

    while stop_event is None or not stop_event.is_set():
        try:
            # Atomically claim due domains using database lease (SKIP LOCKED)
            domains = supabase_service.claim_due_domain_audits(
                worker_id=worker_id,
                limit=limit,
                interval_seconds=interval_seconds,
                lease_seconds=lease_seconds
            )

            if not domains:
                logger.debug("No domains due for audit. Sleeping...")
                # Interruptible sleep
                for _ in range(idle_sleep_seconds):
                    if stop_event and stop_event.is_set():
                        break
                    await asyncio.sleep(1)
                continue

            logger.info(f"Worker {worker_id} claimed {len(domains)} due domain(s). Executing audits...")

            # Concurrently process claimed domains with TaskGroup
            async with asyncio.TaskGroup() as group:
                for domain in domains:
                    group.create_task(audit_claimed_domain(domain, worker_id))

        except Exception as e:
            logger.error(f"Unexpected error in audit worker loop: {e}", exc_info=True)
            await asyncio.sleep(5)

    logger.info(f"Audit worker {worker_id} stopped cleanly.")
