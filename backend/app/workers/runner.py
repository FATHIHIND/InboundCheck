"""
InboundCheck - Dedicated Background Workers CLI Runner (Phase 4)
================================================================
Entrypoint for launching dedicated, distributed background worker processes:
- `python -m app.workers.runner audit`
- `python -m app.workers.runner failover`
- `python -m app.workers.runner all`
"""

import sys
import asyncio
import logging
import signal
from typing import Optional

from app.core.env_guard import validate_worker_runtime_environment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("WorkerRunner")


async def run_audit_worker(*args, **kwargs):
    """Lazy delegation to audit worker preventing module-level client instantiation."""
    from app.workers.audit_worker import run_audit_worker as _impl
    return await _impl(*args, **kwargs)


async def run_failover_worker(*args, **kwargs):
    """Lazy delegation to failover worker preventing module-level client instantiation."""
    from app.workers.failover_worker import run_failover_worker as _impl
    return await _impl(*args, **kwargs)


async def main(
    worker_type: str = "audit",
    is_staging_authorized: bool = False,
    once: bool = False,
    limit: int = 25,
):
    import os

    # Fail closed if staging is requested directly through runner.py
    is_staging_requested = (
        os.environ.get("ENVIRONMENT", "").strip().lower() == "staging"
        or any(arg.startswith("--staging") for arg in sys.argv)
    )

    if is_staging_requested and not is_staging_authorized:
        from app.core.staging_guard import StagingIsolationError
        raise StagingIsolationError(
            "Direct staging worker execution via runner.py is forbidden to guarantee isolated environment bootstrap. "
            "Use dedicated staging runner instead: python -m app.workers.staging_runner [worker_type]"
        )

    # Fail-Fast Runtime Environment Integrity Validation
    validate_worker_runtime_environment()

    stop_event = asyncio.Event()

    # Graceful shutdown handling
    loop = asyncio.get_running_loop()

    def handle_stop_signal():
        logger.info(f"Received termination signal. Requesting graceful worker shutdown...")
        stop_event.set()

    # Register OS signals if supported on current platform
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_stop_signal)
        except (NotImplementedError, RuntimeError):
            # Windows signal handler fallback
            signal.signal(sig, lambda s, f: stop_event.set())

    logger.info(f"Launching InboundCheck worker process [Type: {worker_type}, Once: {once}, Limit: {limit}]...")

    try:
        if worker_type == "audit":
            await run_audit_worker(stop_event=stop_event, limit=limit, once=once)
        elif worker_type == "failover":
            await run_failover_worker(stop_event=stop_event)
        elif worker_type == "all":
            await asyncio.gather(
                run_audit_worker(stop_event=stop_event, limit=limit, once=once),
                run_failover_worker(stop_event=stop_event),
            )
        else:
            logger.error(f"Unknown worker type: '{worker_type}'. Supported: 'audit', 'failover', 'all'.")
            sys.exit(1)
    except asyncio.CancelledError:
        logger.info("Worker runner task cancelled.")
    finally:
        logger.info("Worker runner exited cleanly.")


if __name__ == "__main__":
    target = "audit"
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            target = arg
            break

    # Fail closed immediately if staging is requested via CLI arguments or environment
    if any(arg.startswith("--staging") for arg in sys.argv) or os.environ.get("ENVIRONMENT", "").strip().lower() == "staging":
        logger.critical(
            "Direct staging worker execution via runner.py is forbidden. "
            "Use dedicated staging runner instead: python -m app.workers.staging_runner [worker_type]"
        )
        sys.exit(2)

    try:
        asyncio.run(main(target))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process terminated by user or system.")
