"""CLI runner for Boomerang Push Notification Dispatcher.

Usage:
    .venv/Scripts/python scripts/run_push_dispatcher.py
    .venv/Scripts/python scripts/run_push_dispatcher.py --once
    .venv/Scripts/python scripts/run_push_dispatcher.py --status
    .venv/Scripts/python scripts/run_push_dispatcher.py --replay-failed
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when invoked directly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.push_dispatcher import PushDispatcher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("push-dispatcher-runner")


async def async_main(args: argparse.Namespace) -> None:
    dispatcher = PushDispatcher()

    if args.status:
        counts = await dispatcher.get_backlog_counts()
        print("=" * 50)
        print("Boomerang Push Delivery Queue Status")
        print("=" * 50)
        for status_name, count in counts.items():
            print(f"  {status_name:<20}: {count}")
        print("=" * 50)
        return

    if args.replay_failed:
        replayed = await dispatcher.replay_failed_deliveries()
        print(f"Re-enqueued {replayed} failed/permanently failed push deliveries.")
        return

    if args.once:
        logger.info(
            "Processing single push delivery batch (batch_size=%d)...",
            args.batch_size or settings.PUSH_DISPATCHER_BATCH_SIZE,
        )
        processed = await dispatcher.process_batch(batch_size=args.batch_size)
        logger.info(
            "Batch execution complete. Processed %d deliveries. Metrics: %s",
            processed,
            dispatcher.metrics.snapshot(),
        )
        return

    stop_event = asyncio.Event()

    def handle_signal(*_args: Any) -> None:
        logger.info("Shutdown signal received. Stopping push dispatcher...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)
    else:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Starting continuous push dispatcher loop...")
    await dispatcher.run_loop(
        poll_interval=args.poll_interval,
        stop_event=stop_event,
    )
    logger.info("Final PushDispatcher metrics: %s", dispatcher.metrics.snapshot())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Boomerang Asynchronous Push Notification Dispatcher",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display delivery queue counts by status and exit",
    )
    parser.add_argument(
        "--replay-failed",
        action="store_true",
        help="Replay failed and permanently failed deliveries",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Maximum tasks to claim in a single batch",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Polling interval in seconds between empty sweeps",
    )

    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
