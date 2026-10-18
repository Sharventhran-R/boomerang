"""Development-only Kafka producer/consumer smoke test for Boomerang.

This script sends a harmless, synthetic probe message to the configured Kafka topic
and asserts that a consumer within a unique consumer group receives it.
It verifies:
  1. Network connectivity to the Kafka broker.
  2. Topic existence and partition assignment.
  3. End-to-end publish and consume roundtrip.

Usage:
    .venv/Scripts/python scripts/kafka_smoke_test.py
    .venv/Scripts/python scripts/kafka_smoke_test.py --topic boomerang.domain.events
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when invoked directly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aiokafka import (  # noqa: E402  # type: ignore[import-untyped]
    AIOKafkaConsumer,
    AIOKafkaProducer,
)
from aiokafka.errors import (  # noqa: E402  # type: ignore[import-untyped]
    KafkaError,
)

from app.core.config import settings  # noqa: E402


def generate_probe_payload() -> tuple[str, dict[str, Any]]:
    probe_id = str(uuid.uuid4())
    payload = {
        "probe_id": probe_id,
        "probe_type": "INFRASTRUCTURE_SMOKE_TEST",
        "timestamp": datetime.now(UTC).isoformat(),
        "purpose": "Local Kafka infrastructure verification",
        "is_synthetic": True,
    }
    return probe_id, payload


async def run_smoke_test(
    bootstrap_servers: str,
    topic: str,
    timeout_seconds: float = 15.0,
    verbose: bool = True,
) -> dict[str, Any]:
    probe_id, payload = generate_probe_payload()
    group_id = f"smoke-test-{uuid.uuid4().hex[:8]}"

    if verbose:
        print("=" * 60)
        print("Boomerang Kafka Smoke Test (Phase 7.2)")
        print("=" * 60)
        print(f"Bootstrap Servers : {bootstrap_servers}")
        print(f"Topic             : {topic}")
        print(f"Consumer Group    : {group_id}")
        print(f"Probe ID          : {probe_id}")
        print("-" * 60)

    # Initialize consumer with earliest offset reset and unique group
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    if verbose:
        print("[1/4] Starting Kafka consumer...")
    await consumer.start()

    if verbose:
        print("[2/4] Starting Kafka producer...")
    await producer.start()

    start_time = time.perf_counter()
    try:
        if verbose:
            print(f"[3/4] Publishing synthetic probe message to '{topic}'...")

        # Key partition by probe_id
        record_metadata = await producer.send_and_wait(
            topic,
            payload,
            key=probe_id.encode("utf-8"),
        )
        send_time = time.perf_counter()

        if verbose:
            print(
                f"      Published -> Partition: {record_metadata.partition}, "
                f"Offset: {record_metadata.offset}"
            )
            print(
                f"[4/4] Awaiting consumption of probe '{probe_id}' "
                f"(timeout: {timeout_seconds}s)..."
            )

        async def _consume_loop() -> dict[str, Any]:
            async for msg in consumer:
                val = msg.value
                if isinstance(val, dict) and val.get("probe_id") == probe_id:
                    received_time = time.perf_counter()
                    latency_ms = (received_time - send_time) * 1000.0
                    return {
                        "status": "success",
                        "probe_id": probe_id,
                        "topic": msg.topic,
                        "partition": msg.partition,
                        "offset": msg.offset,
                        "timestamp": msg.timestamp,
                        "latency_ms": round(latency_ms, 2),
                        "payload": val,
                    }
            raise RuntimeError("Consumer stream exited without receiving probe message")

        result = await asyncio.wait_for(_consume_loop(), timeout=timeout_seconds)
        total_duration = time.perf_counter() - start_time
        result["total_duration_s"] = round(total_duration, 2)

        if verbose:
            print("-" * 60)
            print("[PASS] Smoke Test PASSED!")
            print(f"  Received Partition : {result['partition']}")
            print(f"  Received Offset    : {result['offset']}")
            print(f"  Roundtrip Latency  : {result['latency_ms']} ms")
            print("=" * 60)

        return result

    finally:
        if verbose:
            print("Stopping producer and consumer...")
        await producer.stop()
        await consumer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Boomerang Kafka Smoke Test")
    parser.add_argument(
        "--bootstrap-servers",
        default=settings.KAFKA_BOOTSTRAP_SERVERS,
        help="Kafka bootstrap servers (default: from settings)",
    )
    parser.add_argument(
        "--topic",
        default=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        help="Kafka topic to probe (default: from settings)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds (default: 15.0)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode (minimal output)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            run_smoke_test(
                bootstrap_servers=args.bootstrap_servers,
                topic=args.topic,
                timeout_seconds=args.timeout,
                verbose=not args.quiet,
            )
        )
    except (KafkaError, TimeoutError, OSError) as exc:
        print(f"\n[FAIL] Smoke Test FAILED: {exc}", file=sys.stderr)
        print("\nTroubleshooting tips:", file=sys.stderr)
        print("  1. Ensure Kafka is running: docker compose ps", file=sys.stderr)
        print("  2. Check Kafka logs: docker compose logs kafka", file=sys.stderr)
        print(
            "  3. Verify port 9092 is published and not blocked by firewall.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
