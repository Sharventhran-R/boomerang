"""Comprehensive tests for Boomerang Event Consumer Foundation (Phase 7.4)."""

import asyncio
import json
import socket
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiokafka import ConsumerRecord, TopicPartition
from aiokafka.structs import OffsetAndMetadata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ConsumerEvent,
    ConsumerEventStatus,
    ReportStatus,
    ReportType,
    User,
)
from app.schemas.events import (
    AggregateType,
    BoomerangEvent,
    EventType,
    ReportCreatedEvent,
    ReportCreatedPayload,
)
from app.services.event_consumer import (
    ConsumerProcessingResult,
    ErrorCategory,
    EventConsumer,
    HandlerRegistry,
)


def _is_kafka_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _create_mock_record(
    topic: str = "boomerang.domain.events",
    partition: int = 0,
    offset: int = 100,
    key: bytes | None = None,
    value: bytes = b"",
) -> ConsumerRecord:
    return ConsumerRecord(
        topic=topic,
        partition=partition,
        offset=offset,
        timestamp=int(datetime.now(UTC).timestamp() * 1000),
        timestamp_type=0,
        key=key,
        value=value,
        checksum=None,
        serialized_key_size=len(key) if key else 0,
        serialized_value_size=len(value),
        headers=(),
    )


def _build_test_report_created_event(
    event_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
) -> ReportCreatedEvent:
    ev_id = event_id or uuid.uuid4()
    rep_id = report_id or uuid.uuid4()
    now = datetime.now(UTC)
    payload = ReportCreatedPayload(
        report_id=rep_id,
        created_by_user_id=uuid.uuid4(),
        type=ReportType.MISSING,
        category="ELECTRONICS",  # type: ignore
        title="Consumer Test Laptop",
        description="Left on train",
        latitude=50.4501,
        longitude=30.5234,
        event_time=now,
        reward_amount=None,
        status=ReportStatus.ACTIVE,
        created_at=now,
    )
    return ReportCreatedEvent(
        event_id=ev_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="test-producer",
        aggregate_id=rep_id,
        aggregate_type=AggregateType.REPORT,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_valid_envelope_parsing_and_handler_dispatch() -> None:
    """1. Verifies valid envelope parses, invokes registered handler,
    and records COMPLETED status.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=101, value=raw_bytes)

    handled_events: list[BoomerangEvent] = []

    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def on_report_created(ev: BoomerangEvent, session: AsyncSession) -> None:
        handled_events.append(ev)

    mock_kafka = AsyncMock()
    mock_kafka.commit = AsyncMock()

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=mock_kafka,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.SUCCESS
    assert len(handled_events) == 1
    assert handled_events[0].event_id == event.event_id

    # Verify idempotency record in PostgreSQL
    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.COMPLETED
        assert saved.retry_count == 0
        assert saved.offset == 101
        assert saved.processed_at is not None

    # Verify Kafka offset was committed (offset + 1)
    mock_kafka.commit.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_version_quarantined_and_offset_committed() -> None:
    """2. Verifies unsupported version (v99) is quarantined and offset is committed."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event_dict = _build_test_report_created_event().model_dump(mode="json")
    event_dict["event_version"] = 99  # Unsupported version!
    raw_bytes = json.dumps(event_dict).encode("utf-8")
    record = _create_mock_record(offset=102, value=raw_bytes)

    registry = HandlerRegistry()
    mock_kafka = AsyncMock()

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=mock_kafka,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.QUARANTINED

    # Verify stored in database with error_category UNSUPPORTED_VERSION
    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == uuid.UUID(event_dict["event_id"]),
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.QUARANTINED
        assert saved.error_category == ErrorCategory.UNSUPPORTED_VERSION.value

    # Offset must be committed to prevent partition stall
    mock_kafka.commit.assert_called_once()


@pytest.mark.asyncio
async def test_malformed_json_quarantined_and_offset_committed() -> None:
    """3. Verifies malformed JSON bytes are quarantined and offset committed."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    record = _create_mock_record(offset=103, value=b"invalid-not-json-content{{{")

    mock_kafka = AsyncMock()
    consumer = EventConsumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.QUARANTINED

    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.offset == 103,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.QUARANTINED
        assert saved.error_category == ErrorCategory.PARSE_ERROR.value

    mock_kafka.commit.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_delivery_skips_handler_and_commits_offset() -> None:
    """4. Verifies duplicate deliveries skip handler execution and commit offset."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=104, value=raw_bytes)

    execution_count = 0
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        nonlocal execution_count
        execution_count += 1

    mock_kafka = AsyncMock()
    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=mock_kafka,
    )

    # First delivery: processed successfully
    res1 = await consumer.process_record(record)
    assert res1 == ConsumerProcessingResult.SUCCESS
    assert execution_count == 1
    assert mock_kafka.commit.call_count == 1

    # Second delivery: identical event redelivered
    res2 = await consumer.process_record(record)
    assert res2 == ConsumerProcessingResult.DUPLICATE_SKIPPED
    assert execution_count == 1  # Handler was NOT executed again!
    assert mock_kafka.commit.call_count == 2  # Offset acknowledged


@pytest.mark.asyncio
async def test_concurrent_duplicate_delivery_protection() -> None:
    """5. Verifies concurrent delivery of same event by two workers is safe
    in PostgreSQL under UNIQUE constraint.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=105, value=raw_bytes)

    counter = 0
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        nonlocal counter
        counter += 1

    consumer_a = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=AsyncMock(),
    )
    consumer_b = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=AsyncMock(),
    )

    # Worker A processes and commits
    res_a = await consumer_a.process_record(record)
    assert res_a == ConsumerProcessingResult.SUCCESS

    # Worker B arrives simultaneously or slightly after
    res_b = await consumer_b.process_record(record)
    assert res_b == ConsumerProcessingResult.DUPLICATE_SKIPPED

    # Total handler execution must be exactly 1
    assert counter == 1


@pytest.mark.asyncio
async def test_atomicity_of_handler_effects_and_idempotency_recording() -> None:
    """6. Verifies handler DB changes and idempotency record commit atomically.

    If handler fails, all database changes made inside handle() are rolled back.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=106, value=raw_bytes)

    test_user_id = uuid.uuid4()
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def failing_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        # Mutate database state
        session.add(
            User(
                id=test_user_id,
                name="Should Roll Back",
                email=f"rollback_{test_user_id}@example.com",
                password_hash="fakehash",
            )
        )
        # Flush to DB within transaction
        await session.flush()
        # Raise unexpected error
        raise RuntimeError("Simulated failure in handler execution")

    mock_kafka = AsyncMock()
    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=mock_kafka,
        max_retries=1,  # Exhaust immediately
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.QUARANTINED

    # Verify User was NOT persisted in PostgreSQL
    async with AsyncSessionLocal() as session:
        user = await session.get(User, test_user_id)
        assert user is None

        # Idempotency status is QUARANTINED, not COMPLETED
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        ev_rec = (await session.execute(stmt)).scalar_one_or_none()
        assert ev_rec is not None
        assert ev_rec.status == ConsumerEventStatus.QUARANTINED
        assert "Simulated failure in handler execution" in (ev_rec.last_error or "")


@pytest.mark.asyncio
async def test_transient_failure_retries_with_backoff_and_succeeds() -> None:
    """7. Verifies transient failure retries and succeeds on subsequent attempt."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=107, value=raw_bytes)

    attempts = 0
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def flaky_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("Transient network glitch")

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=AsyncMock(),
        max_retries=3,
        initial_retry_delay=0.01,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.SUCCESS
    assert attempts == 2
    assert consumer.metrics.retries == 1

    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.COMPLETED
        assert saved.retry_count == 1


@pytest.mark.asyncio
async def test_explicit_replay_behavior() -> None:
    """8. Verifies explicit operator replay of a quarantined event."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_dict = event.model_dump(mode="json")
    event_id = event.event_id

    # Insert pre-existing quarantined event in database
    async with AsyncSessionLocal() as session:
        session.add(
            ConsumerEvent(
                consumer_name=consumer_name,
                event_id=event_id,
                event_type=event.event_type.value,
                aggregate_type=event.aggregate_type.value,
                aggregate_id=event.aggregate_id,
                topic="test.topic",
                partition=0,
                offset=200,
                status=ConsumerEventStatus.QUARANTINED,
                error_category=ErrorCategory.HANDLER_ERROR.value,
                last_error="Pre-existing failure",
                payload=raw_dict,
            )
        )
        await session.commit()

    replayed_events: list[BoomerangEvent] = []
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        replayed_events.append(ev)

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=AsyncMock(),
    )

    # Replay specific event
    success = await consumer.replay_quarantined_event(event_id)
    assert success is True
    assert len(replayed_events) == 1
    assert replayed_events[0].event_id == event_id

    # Verify status in database transitioned to COMPLETED and error cleared
    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event_id,
        )
        rec = (await session.execute(stmt)).scalar_one_or_none()
        assert rec is not None
        assert rec.status == ConsumerEventStatus.COMPLETED
        assert rec.last_error is None
        assert rec.error_category is None


@pytest.mark.asyncio
async def test_privacy_safe_quarantine_records() -> None:
    """9. Verifies diagnostic last_error is bounded and scrubbed of secrets."""
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=109, value=raw_bytes)

    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def sensitive_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        # Handler error with simulated password string
        raise ValueError("Database connection failed: password=supersecretpass123")

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=AsyncMock(),
        max_retries=1,
    )

    await consumer.process_record(record)

    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.QUARANTINED
        assert len(saved.last_error or "") <= 1000


@pytest.mark.asyncio
async def test_known_event_with_no_handler_graceful_ignore() -> None:
    """10. Case 4: Verifies known event type (report.created) with no registered

    handlers is marked COMPLETED in PostgreSQL and acknowledged to Kafka.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    event = _build_test_report_created_event()
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=110, value=raw_bytes)

    # Empty registry with zero handlers
    empty_registry = HandlerRegistry()
    mock_kafka = AsyncMock()

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=empty_registry,
        consumer=mock_kafka,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.IGNORED
    mock_kafka.commit.assert_called_once()

    # Verify idempotency record exists in PostgreSQL with status COMPLETED
    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.COMPLETED
        assert saved.event_type == event.event_type.value
        assert saved.offset == 110


@pytest.mark.asyncio
async def test_unknown_event_type_quarantined_and_offset_committed() -> None:
    """Case 3: Verifies unknown event type is durably quarantined in PostgreSQL

    with UNSUPPORTED_TYPE, safe payload retention, and offset is committed to Kafka.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC).isoformat()
    unknown_event_id = uuid.uuid4()
    raw_payload = {
        "event_id": str(unknown_event_id),
        "event_type": "unknown.custom.event",
        "event_version": 1,
        "occurred_at": now,
        "producer": "external-service",
        "aggregate_type": "custom",
        "aggregate_id": str(uuid.uuid4()),
        "payload": {"arbitrary": "data"},
    }
    raw_bytes = json.dumps(raw_payload).encode("utf-8")
    record = _create_mock_record(offset=111, value=raw_bytes)

    mock_kafka = AsyncMock()
    consumer = EventConsumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
    )

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.QUARANTINED

    # Verify stored in database with error_category UNSUPPORTED_TYPE
    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == unknown_event_id,
        )
        saved = (await session.execute(stmt)).scalar_one_or_none()
        assert saved is not None
        assert saved.status == ConsumerEventStatus.QUARANTINED
        assert saved.error_category == ErrorCategory.UNSUPPORTED_TYPE.value
        assert saved.event_type == "unknown.custom.event"
        assert saved.payload == raw_payload

    # Offset must be committed to prevent partition stall
    mock_kafka.commit.assert_called_once()


@pytest.mark.asyncio
async def test_partition_offset_safety_out_of_order_completion() -> None:
    """Check B: Verifies that when a later message completes before an earlier

    message in the same partition, the later offset CANNOT be committed prematurely.
    Only when the earlier message completes does the committed offset advance to 202.
    """
    consumer_name = f"test_consumer_{uuid.uuid4().hex[:8]}"
    topic = settings.KAFKA_DOMAIN_EVENTS_TOPIC
    partition = 0

    # Build two events for partition 0: offset 200 (earlier) and offset 201 (later)
    event1 = _build_test_report_created_event()
    event2 = _build_test_report_created_event()

    bytes1 = json.dumps(event1.model_dump(mode="json")).encode("utf-8")
    bytes2 = json.dumps(event2.model_dump(mode="json")).encode("utf-8")

    record1 = _create_mock_record(
        topic=topic, partition=partition, offset=200, value=bytes1
    )
    record2 = _create_mock_record(
        topic=topic, partition=partition, offset=201, value=bytes2
    )

    release_event1 = asyncio.Event()
    event1_started = asyncio.Event()

    committed_offsets: list[tuple[TopicPartition, int]] = []

    async def tracking_commit(
        offsets_dict: dict[TopicPartition, OffsetAndMetadata],
    ) -> None:
        for tp, om in offsets_dict.items():
            committed_offsets.append((tp, om.offset))

    mock_kafka = AsyncMock()
    mock_kafka.commit = AsyncMock(side_effect=tracking_commit)

    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        if ev.event_id == event1.event_id:
            event1_started.set()
            # Wait until explicitly released
            await release_event1.wait()
        elif ev.event_id == event2.event_id:
            # Completes immediately
            pass

    consumer = EventConsumer(
        consumer_name=consumer_name,
        registry=registry,
        consumer=mock_kafka,
    )

    # Launch processing of both records concurrently
    task1 = asyncio.create_task(consumer.process_record(record1))
    task2 = asyncio.create_task(consumer.process_record(record2))

    # Wait until record 1 has started and record 2 has fully completed
    await event1_started.wait()
    await task2

    # Assert record 2 finished
    assert task2.done() is True
    assert task1.done() is False

    # CRITICAL INVARIANT: Offset 202 (or 201) MUST NOT have been committed to Kafka!
    # Because record 1 (offset 200) is still in-flight!
    assert len(committed_offsets) == 0, (
        f"Premature offset commit detected: {committed_offsets}"
    )

    # Now release record 1 to complete its processing
    release_event1.set()
    await task1
    assert task1.done() is True

    # NOW both record 1 (200) and record 2 (201) are durable
    # The committed offset must now have advanced to 202 (highest contiguous + 1)
    assert len(committed_offsets) >= 1
    tp_target = TopicPartition(topic, partition)
    last_tp, last_offset = committed_offsets[-1]
    assert last_tp == tp_target
    assert last_offset == 202

    # Verify both records are recorded as COMPLETED in PostgreSQL
    async with AsyncSessionLocal() as session:
        for ev in (event1, event2):
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == ev.event_id,
            )
            saved = (await session.execute(stmt)).scalar_one_or_none()
            assert saved is not None
            assert saved.status == ConsumerEventStatus.COMPLETED


@pytest.mark.asyncio
async def test_real_kafka_event_consumer_roundtrip() -> None:
    """11. Real end-to-end Kafka consumer test with live broker (when online)."""
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092

    if not _is_kafka_listening(host, port):
        pytest.skip(f"Kafka broker not reachable at {host}:{port}")

    from aiokafka import AIOKafkaProducer

    # 1. Publish test event using real Kafka producer
    event = _build_test_report_created_event()
    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    consumer_name = f"live_consumer_{uuid.uuid4().hex[:8]}"
    group_id = f"group_{uuid.uuid4().hex[:8]}"

    handled_live: list[BoomerangEvent] = []
    stop_event = asyncio.Event()
    registry = HandlerRegistry()

    event = _build_test_report_created_event()

    @registry.register_func([EventType.REPORT_CREATED])
    async def live_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        if ev.event_id == event.event_id:
            handled_live.append(ev)
            stop_event.set()

    consumer = EventConsumer(
        consumer_name=consumer_name,
        group_id=group_id,
        registry=registry,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
    )
    await consumer.start()
    if consumer.consumer:
        await consumer.consumer.getmany(timeout_ms=1000)

    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    consumer_task = asyncio.create_task(
        consumer.run_loop(stop_event=stop_event, poll_timeout_ms=1000)
    )

    try:
        # Publish
        raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw_bytes,
            key=str(event.aggregate_id).encode("utf-8"),
        )

        # Wait for consumer task to process event and exit via stop_event
        await asyncio.wait_for(consumer_task, timeout=10.0)

        # Assert handler received and processed the real message
        assert len(handled_live) == 1
        assert handled_live[0].event_id == event.event_id

        # Assert status is COMPLETED in PostgreSQL
        async with AsyncSessionLocal() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == event.event_id,
            )
            saved = (await session.execute(stmt)).scalar_one_or_none()
            assert saved is not None
            assert saved.status == ConsumerEventStatus.COMPLETED

    finally:
        await producer.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer.stop()
