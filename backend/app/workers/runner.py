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

from app.workers.audit_worker import run_audit_worker
from app.workers.failover_worker import run_failover_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("WorkerRunner")


async def main(worker_type: str = "audit"):
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

    logger.info(f"Launching InboundCheck worker process [Type: {worker_type}]...")

    try:
        if worker_type == "audit":
            await run_audit_worker(stop_event=stop_event)
        elif worker_type == "failover":
            await run_failover_worker(stop_event=stop_event)
        elif worker_type == "all":
            await asyncio.gather(
                run_audit_worker(stop_event=stop_event),
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
    target = sys.argv[1] if len(sys.argv) > 1 else "audit"
    try:
        asyncio.run(main(target))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process terminated by user or system.")
