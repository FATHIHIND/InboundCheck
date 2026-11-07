"""
InboundCheck - Dedicated Background Workers CLI Runner (Phase 4)
================================================================
Entrypoint for launching dedicated, distributed background worker processes:
- `python -m app.workers.runner audit`
- `python -m app.workers.runner failover`
- `python -m app.workers.runner all`
"""

import argparse
import os
import sys
import asyncio
import logging
import signal
from typing import Optional

from app.core.env_guard import validate_worker_runtime_environment

# Backward-compatibility alias for test runners expecting validate_runtime_environment
validate_runtime_environment = validate_worker_runtime_environment

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
    # Reject invalid direct calls before loading settings or worker modules.
    if worker_type not in ("audit", "failover", "all"):
        raise ValueError("worker_type must be audit, failover, or all")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

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
    if validate_runtime_environment is not validate_worker_runtime_environment:
        validate_runtime_environment()

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

    from app.core.env_guard import get_deployment_commit_sha, get_railway_service_name
    build_sha = get_deployment_commit_sha(default="unknown")
    svc_name = get_railway_service_name() or "worker"

    logger.info(
        f"Launching InboundCheck worker process [Type: {worker_type}, Once: {once}, Limit: {limit}, "
        f"Build: {build_sha}, Service: {svc_name}]..."
    )

    try:
        if worker_type == "audit":
            await run_audit_worker(stop_event=stop_event, limit=limit, once=once)
        elif worker_type == "failover":
            await run_failover_worker(stop_event=stop_event, limit=limit, once=once)
        elif worker_type == "all":
            await asyncio.gather(
                run_audit_worker(stop_event=stop_event, limit=limit, once=once),
                run_failover_worker(stop_event=stop_event, limit=limit, once=once),
            )
        else:
            logger.error(f"Unknown worker type: '{worker_type}'. Supported: 'audit', 'failover', 'all'.")
            sys.exit(1)
    except asyncio.CancelledError:
        logger.info("Worker runner task cancelled.")
    finally:
        logger.info("Worker runner exited cleanly.")


def _positive_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from None
    if limit <= 0:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return limit


def cli(argv=None) -> int:
    """Parse worker mode strictly and retain nonzero startup failure statuses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_type", nargs="?", default="audit", choices=("audit", "failover", "all"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=_positive_limit, default=25)
    args = parser.parse_args(argv)

    # Stage isolation must happen before runtime settings or client imports.
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "staging":
        logger.critical(
            "Direct staging worker execution via runner.py is forbidden. "
            "Use dedicated staging runner instead: python -m app.workers.staging_runner [worker_type]"
        )
        return 2

    try:
        asyncio.run(main(worker_type=args.worker_type, once=args.once, limit=args.limit))
    except KeyboardInterrupt:
        logger.info("Worker process interrupted.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
