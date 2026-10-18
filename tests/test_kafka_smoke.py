"""Development-only Kafka smoke test for local infrastructure."""

import socket

import pytest

from app.core.config import settings
from scripts.kafka_smoke_test import run_smoke_test


def _is_kafka_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_kafka_infrastructure_smoke() -> None:
    """Verifies single-node Kafka KRaft broker connectivity and message roundtrip."""
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092

    if not _is_kafka_listening(host, port):
        pytest.skip(f"Kafka broker not reachable at {host}:{port}")

    result = await run_smoke_test(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        timeout_seconds=10.0,
        verbose=False,
    )

    assert result["status"] == "success"
    assert result["topic"] == settings.KAFKA_DOMAIN_EVENTS_TOPIC
    assert isinstance(result["partition"], int)
    assert isinstance(result["offset"], int)
    assert result["latency_ms"] >= 0
    assert result["payload"]["is_synthetic"] is True
    assert result["payload"]["purpose"] == "Local Kafka infrastructure verification"
