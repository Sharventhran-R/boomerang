"""CLI runner for Boomerang Transactional Outbox Dispatcher.

Usage:
    .venv/Scripts/python scripts/run_outbox_dispatcher.py
    .venv/Scripts/python scripts/run_outbox_dispatcher.py --once
    .venv/Scripts/python scripts/run_outbox_dispatcher.py --status
    .venv/Scripts/python scripts/run_outbox_dispatcher.py --replay-dead-letters
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
from app.services.outbox_dispatcher import OutboxDispatcher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("outbox-dispatcher-runner")


async def async_main(args: argparse.Namespace) -> None:
    dispatcher = OutboxDispatcher(
        bootstrap_servers=args.bootstrap_servers,
    )

    if args.status:
        counts = await dispatcher.get_backlog_counts()
        print("=" * 50)
        print("Boomerang Outbox Backlog Status")
        print("=" * 50)
        for status_name, count in counts.items():
            print(f"  {status_name:<15}: {count}")
        print("=" * 50)
        return

    if args.replay_dead_letters:
        replayed = await dispatcher.replay_dead_letter_events()
        print(f"[REPLAY] Re-enqueued {replayed} dead-letter events as PENDING.")
        return

    if args.once:
        print("[RUN] Running single outbox batch...")
        await dispatcher.start()
        try:
            processed = await dispatcher.process_batch(batch_size=args.batch_size)
            print(f"[RUN] Processed {processed} events.")
            print(f"      Metrics: {dispatcher.metrics.snapshot()}")
        finally:
            await dispatcher.stop()
        return

    # Continuous loop mode with signal handling
    stop_event = asyncio.Event()

    def _signal_handler(*_: Any) -> None:
        logger.info("Termination signal received. Shutting down dispatcher...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        # On Windows, register standard signal handler
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    print("=" * 60)
    print("Boomerang Outbox Dispatcher Worker")
    print(f"Bootstrap Servers : {dispatcher.bootstrap_servers}")
    print(f"Topic             : {settings.KAFKA_DOMAIN_EVENTS_TOPIC}")
    print(f"Poll Interval     : {args.poll_interval}s")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    await dispatcher.run_loop(
        poll_interval=args.poll_interval,
        stop_event=stop_event,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Boomerang Transactional Outbox Dispatcher"
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=settings.KAFKA_BOOTSTRAP_SERVERS,
        help="Kafka bootstrap servers",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.OUTBOX_POLL_INTERVAL_SECONDS,
        help="Polling interval in seconds when idle",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.OUTBOX_BATCH_SIZE,
        help="Batch size for event claiming",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display outbox table status breakdown and exit",
    )
    parser.add_argument(
        "--replay-dead-letters",
        action="store_true",
        help="Reset DEAD_LETTER events to PENDING and exit",
    )

    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
