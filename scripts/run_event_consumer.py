"""CLI runner for Boomerang Event Consumer Foundation.

Usage:
    # Run continuous polling loop
    python scripts/run_event_consumer.py --consumer-name matching_engine

    # Run bounded single batch (e.g. 50 messages)
    python scripts/run_event_consumer.py --consumer-name matching_engine --once

    # Display operational status breakdown (COMPLETED, QUARANTINED, etc.)
    python scripts/run_event_consumer.py --consumer-name matching_engine --status

    # Replay all quarantined events for this consumer
    python scripts/run_event_consumer.py --consumer-name matching_engine \\
        --replay-quarantined

    # Replay specific quarantined event by UUID
    python scripts/run_event_consumer.py --consumer-name matching_engine \\
        --replay <event_id>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when invoked directly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.event_consumer import (  # noqa: E402
    EventConsumer,
    HandlerRegistry,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("event-consumer-runner")


async def async_main(args: argparse.Namespace) -> None:
    consumer_name = args.consumer_name
    registry = HandlerRegistry()

    consumer = EventConsumer(
        consumer_name=consumer_name,
        group_id=args.group_id,
        topics=[args.topic],
        registry=registry,
        bootstrap_servers=args.bootstrap_servers,
    )

    if args.status:
        counts = await consumer.get_status_counts()
        print("=" * 55)
        print(f"Boomerang Event Consumer Status: {consumer_name}")
        print("=" * 55)
        for status_name, count in counts.items():
            print(f"  {status_name:<16}: {count}")
        print("=" * 55)
        return

    if args.replay:
        target_id = uuid.UUID(args.replay)
        print(f"[REPLAY] Attempting replay for quarantined event {target_id}...")
        replayed = await consumer.replay_quarantined_event(target_id)
        if replayed:
            print(
                f"[REPLAY] SUCCESS: Event {target_id} reprocessed and marked COMPLETED."
            )
        else:
            print(
                f"[REPLAY] FAILED: Event {target_id} not found in quarantine "
                f"or replay failed."
            )
        return

    if args.replay_quarantined:
        print(f"[REPLAY] Replaying all quarantined events for {consumer_name}...")
        replayed_count = await consumer.replay_all_quarantined()
        print(f"[REPLAY] Replayed {replayed_count} quarantined events.")
        return

    if args.once:
        print(f"[RUN] Running single bounded pass for {consumer_name}...")
        processed = await consumer.run_loop(
            max_messages=args.max_messages or 50,
            poll_timeout_ms=1000,
        )
        print(f"[RUN] Processed {processed} messages.")
        print(f"      Metrics: {consumer.metrics.snapshot()}")
        return

    # Continuous loop mode with graceful signal handling
    stop_event = asyncio.Event()

    def _signal_handler(*_: Any) -> None:
        logger.info("Termination signal received. Shutting down consumer...")
        stop_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    print("=" * 60)
    print("Boomerang Event Consumer Worker")
    print(f"Consumer Name     : {consumer_name}")
    print(f"Consumer Group    : {consumer.group_id}")
    print(f"Topic             : {args.topic}")
    print(f"Bootstrap Servers : {consumer.bootstrap_servers}")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    await consumer.run_loop(stop_event=stop_event)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Boomerang Kafka Event Consumer Runner"
    )
    parser.add_argument(
        "--consumer-name",
        default="boomerang.domain.consumer",
        help="Unique identity of this consumer (e.g. matching_engine)",
    )
    parser.add_argument(
        "--group-id",
        default=None,
        help="Kafka consumer group ID (defaults to <consumer-name>-group)",
    )
    parser.add_argument(
        "--topic",
        default=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        help="Kafka topic to consume from",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=settings.KAFKA_BOOTSTRAP_SERVERS,
        help="Kafka bootstrap servers",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process available messages in a single bounded pass and exit",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Maximum messages to process in --once mode",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display consumer event and quarantine status breakdown and exit",
    )
    parser.add_argument(
        "--replay",
        metavar="EVENT_ID",
        help="Replay a specific quarantined event by UUID",
    )
    parser.add_argument(
        "--replay-quarantined",
        action="store_true",
        help="Replay all quarantined events for this consumer",
    )

    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
