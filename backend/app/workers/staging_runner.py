"""
InboundCheck - Dedicated Staging Background Workers Runner (Phase 18A.6B)
=======================================================================
Fail-closed entrypoint for launching background workers in isolated staging.

Guarantees:
1. Bootstraps staging environment via app.core.staging_guard BEFORE any
   worker, settings, or Supabase client modules are loaded.
2. Rejects production project reference 'tbjcldcoozvuvyipeonh' immediately.
3. Validates that SUPABASE_URL exactly matches the expected staging ref.
4. Injects validated staging variables into os.environ, overriding any .env file.
5. Launches the requested worker process cleanly without side-effects.
"""

import sys
import asyncio
import logging

from app.core.staging_guard import bootstrap_staging_environment, StagingIsolationError

logger = logging.getLogger("StagingWorkerRunner")

EXPECTED_STAGING_REF = "wymgyqnqwlliotkxamtd"


def init_staging_isolation(
    expected_staging_ref: str = EXPECTED_STAGING_REF,
    custom_env_path: str = None
) -> None:
    """Validate and bootstrap staging environment before importing any worker modules."""
    bootstrap_staging_environment(
        expected_staging_ref=expected_staging_ref,
        custom_env_path=custom_env_path
    )


async def main(
    worker_type: str = "audit",
    expected_staging_ref: str = EXPECTED_STAGING_REF,
    custom_env_path: str = None,
    once: bool = False,
    limit: int = 25,
    mock_rbl: bool = False,
    mock_telegram: bool = False,
):
    # 1. Fail-closed bootstrap before any worker or client import
    init_staging_isolation(expected_staging_ref=expected_staging_ref, custom_env_path=custom_env_path)

    # 2. Inject synthetic RBL mock if requested for zero-network testing
    if mock_rbl:
        from app.services.dns import rbl_scanner as rbl_mod
        from app.services.dns.rbl_scanner import RBLScanResult
        from datetime import datetime, timezone

        async def _mock_scan_domain(domain: str, **kwargs):
            return RBLScanResult(
                domain=domain,
                resolved_ips=["93.184.216.34"],
                results=[],
                rbl_clean_count=10,
                rbl_listed_count=0,
                rbl_unknown_count=0,
                rbl_error_count=0,
                rbl_total_count=10,
                overall_status="clean",
                highest_severity="none",
                execution_time_ms=0.1,
                scanned_at=datetime.now(timezone.utc),
            )

        rbl_mod.rbl_scanner.scan_domain = _mock_scan_domain
        logger.info("Staging worker: RBL scanner mocked with zero-network synthetic provider.")

    # 3. Inject synthetic Telegram mock if requested for zero-network testing
    if mock_telegram:
        import os
        from app.core.config import settings
        env = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT or "").strip().lower()
        if env in ("production", "prod"):
            raise RuntimeError("Mock Telegram dispatch is forbidden in Production environment.")

        from app.services.failover.omnichannel_service import telegram_alert_service
        telegram_alert_service.enable_mock_mode()
        logger.info("Staging worker: Telegram dispatch mocked with zero-network synthetic provider.")

    # 4. Lazy import of runner main to execute under verified staging configuration
    from app.workers.runner import main as run_worker_main
    await run_worker_main(
        worker_type=worker_type,
        is_staging_authorized=True,
        once=once,
        limit=limit,
    )


if __name__ == "__main__":
    target = "audit"
    staging_ref = EXPECTED_STAGING_REF
    once = "--once" in sys.argv
    mock_rbl = "--mock-rbl" in sys.argv or "--skip-rbl" in sys.argv
    mock_telegram = "--mock-telegram" in sys.argv or "--skip-telegram" in sys.argv
    limit = 1 if once else 25

    # Parse arguments: target worker and optional flags
    args = sys.argv[1:]
    clean_args = []
    for arg in args:
        if arg.startswith("--staging-ref="):
            staging_ref = arg.split("=", 1)[1].strip()
        elif arg.startswith("--limit="):
            try:
                limit = int(arg.split("=", 1)[1])
            except ValueError:
                pass
        elif arg in ("--staging-ref", "--once", "--mock-rbl", "--skip-rbl", "--mock-telegram", "--skip-telegram"):
            pass
        elif arg.startswith("--"):
            pass
        else:
            clean_args.append(arg)

    if clean_args:
        target = clean_args[0]

    try:
        asyncio.run(
            main(
                worker_type=target,
                expected_staging_ref=staging_ref,
                once=once,
                limit=limit,
                mock_rbl=mock_rbl,
                mock_telegram=mock_telegram,
            )
        )
    except StagingIsolationError as sie:
        logger.critical(f"FATAL: Staging isolation guard triggered: {sie}")
        sys.exit(2)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Staging worker terminated.")
