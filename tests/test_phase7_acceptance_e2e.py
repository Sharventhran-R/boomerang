"""Comprehensive Phase 7 End-to-End Acceptance Tests (Phase 7.5).

Verifies the complete distributed pipeline:
API/Domain Mutation -> PostgreSQL Transaction + Outbox -> OutboxDispatcher
-> Apache Kafka Broker -> EventConsumer -> Idempotent Commitment & Offset Commit.
Drives all 5 domain event contracts through real PostgreSQL and real Apache Kafka.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ConsumerEvent,
    ConsumerEventStatus,
    OutboxEvent,
    OutboxStatus,
    ReportCategory,
    ReportStatus,
    ReportType,
)
from app.schemas.events import (
    BoomerangEvent,
    EventType,
)
from app.services.event_consumer import (
    ErrorCategory,
    EventConsumer,
    HandlerRegistry,
)
from app.services.outbox_dispatcher import OutboxDispatcher


def _is_kafka_online() -> bool:
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


async def _register_auth_user(client: AsyncClient, name: str) -> dict[str, str]:
    email = f"e2e_{uuid.uuid4().hex[:10]}@example.com"
    pwd = "SecurePassword123!"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": pwd},
    )
    assert reg.status_code == 201
    log = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
    )
    assert log.status_code == 200
    token = str(log.json()["access_token"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_e2e_all_five_event_types_pipeline(client: AsyncClient) -> None:
    """Exercises all 5 event types across the full live distributed pipeline:
    1. report.created
    2. report.updated
    3. recovery_request.created
    4. recovery_request.updated
    5. report.resolved

    Pipeline: API -> DB & Outbox -> Dispatcher -> Kafka -> Consumer -> DB Verification.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline, skipping live E2E pipeline test")

    consumer_name = f"e2e_consumer_{uuid.uuid4().hex[:8]}"
    group_id = f"e2e_group_{uuid.uuid4().hex[:8]}"

    target_ids: dict[str, uuid.UUID] = {}
    received_events: dict[str, BoomerangEvent] = {}
    consumer_completion_events: dict[str, asyncio.Event] = {
        EventType.REPORT_CREATED.value: asyncio.Event(),
        EventType.REPORT_UPDATED.value: asyncio.Event(),
        EventType.RECOVERY_REQUEST_CREATED.value: asyncio.Event(),
        EventType.RECOVERY_REQUEST_UPDATED.value: asyncio.Event(),
        EventType.REPORT_RESOLVED.value: asyncio.Event(),
    }

    registry = HandlerRegistry()

    @registry.register_func(
        [
            EventType.REPORT_CREATED,
            EventType.REPORT_UPDATED,
            EventType.RECOVERY_REQUEST_CREATED,
            EventType.RECOVERY_REQUEST_UPDATED,
            EventType.REPORT_RESOLVED,
        ]
    )
    async def global_e2e_handler(event: BoomerangEvent, session: AsyncSession) -> None:
        ev_type = event.event_type.value
        expected_id = target_ids.get(ev_type)
        if expected_id is not None and event.aggregate_id == expected_id:
            received_events[ev_type] = event
            consumer_completion_events[ev_type].set()

    # Initialize live consumer
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

    # Initialize live dispatcher
    dispatcher = OutboxDispatcher(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    await dispatcher.start()

    async def flush_dispatcher() -> None:
        for _ in range(20):
            p = await dispatcher.process_batch(batch_size=50)
            if p == 0:
                break

    # Drain existing backlog before running scenario
    await flush_dispatcher()

    stop_consumer = asyncio.Event()
    consumer_task = asyncio.create_task(
        consumer.run_loop(stop_event=stop_consumer, poll_timeout_ms=500)
    )

    try:
        headers_owner = await _register_auth_user(client, "Owner E2E")
        headers_finder = await _register_auth_user(client, "Finder E2E")

        # -----------------------------------------------------------------
        # 1. API: Create Report -> report.created
        # -----------------------------------------------------------------
        rep_res = await client.post(
            "/api/v1/reports",
            headers=headers_owner,
            json={
                "type": "MISSING",
                "title": "E2E Missing Drone",
                "description": "Black DJI Mavic 3",
                "category": "ELECTRONICS",
                "latitude": 50.4501,
                "longitude": 30.5234,
                "event_time": datetime.now(UTC).isoformat(),
                "reward_amount": "200.00",
            },
        )
        assert rep_res.status_code == 201
        report_id = uuid.UUID(rep_res.json()["id"])
        target_ids[EventType.REPORT_CREATED.value] = report_id
        target_ids[EventType.REPORT_UPDATED.value] = report_id
        target_ids[EventType.REPORT_RESOLVED.value] = report_id

        # Dispatch outbox to Kafka
        await flush_dispatcher()

        # Await consumer receipt
        await asyncio.wait_for(
            consumer_completion_events[EventType.REPORT_CREATED.value].wait(),
            timeout=10.0,
        )
        ev1 = received_events[EventType.REPORT_CREATED.value]
        assert ev1.aggregate_id == report_id
        assert ev1.event_type == EventType.REPORT_CREATED

        # -----------------------------------------------------------------
        # 2. API: Update Report -> report.updated
        # -----------------------------------------------------------------
        patch_res = await client.patch(
            f"/api/v1/reports/{report_id}",
            headers=headers_owner,
            json={"title": "E2E Missing Drone (Reward Increased)"},
        )
        assert patch_res.status_code == 200

        await flush_dispatcher()

        await asyncio.wait_for(
            consumer_completion_events[EventType.REPORT_UPDATED.value].wait(),
            timeout=10.0,
        )
        ev2 = received_events[EventType.REPORT_UPDATED.value]
        assert ev2.aggregate_id == report_id
        assert ev2.event_type == EventType.REPORT_UPDATED

        # -----------------------------------------------------------------
        # 3. API: Create Recovery Request -> recovery_request.created
        # -----------------------------------------------------------------
        rec_res = await client.post(
            "/api/v1/recovery-requests",
            headers=headers_finder,
            json={
                "report_id": str(report_id),
                "message": "I found the drone near the pine tree.",
            },
        )
        assert rec_res.status_code == 201
        recovery_id = uuid.UUID(rec_res.json()["id"])
        target_ids[EventType.RECOVERY_REQUEST_CREATED.value] = recovery_id
        target_ids[EventType.RECOVERY_REQUEST_UPDATED.value] = recovery_id

        await flush_dispatcher()

        await asyncio.wait_for(
            consumer_completion_events[EventType.RECOVERY_REQUEST_CREATED.value].wait(),
            timeout=10.0,
        )
        ev3 = received_events[EventType.RECOVERY_REQUEST_CREATED.value]
        assert ev3.aggregate_id == recovery_id
        assert ev3.event_type == EventType.RECOVERY_REQUEST_CREATED

        # -----------------------------------------------------------------
        # 4. API: Accept Recovery Request -> recovery_request.updated
        # -----------------------------------------------------------------
        accept_res = await client.patch(
            f"/api/v1/recovery-requests/{recovery_id}",
            headers=headers_owner,
            json={"status": "ACCEPTED"},
        )
        assert accept_res.status_code == 200

        await flush_dispatcher()

        await asyncio.wait_for(
            consumer_completion_events[EventType.RECOVERY_REQUEST_UPDATED.value].wait(),
            timeout=10.0,
        )
        ev4 = received_events[EventType.RECOVERY_REQUEST_UPDATED.value]
        assert ev4.aggregate_id == recovery_id
        assert ev4.event_type == EventType.RECOVERY_REQUEST_UPDATED

        # -----------------------------------------------------------------
        # 5. API: Complete Recovery Request -> report.resolved
        # -----------------------------------------------------------------
        complete_res = await client.patch(
            f"/api/v1/recovery-requests/{recovery_id}",
            headers=headers_owner,
            json={"status": "COMPLETED"},
        )
        assert complete_res.status_code == 200

        await flush_dispatcher()

        await asyncio.wait_for(
            consumer_completion_events[EventType.REPORT_RESOLVED.value].wait(),
            timeout=10.0,
        )
        ev5 = received_events[EventType.REPORT_RESOLVED.value]
        assert ev5.aggregate_id == report_id
        assert ev5.event_type == EventType.REPORT_RESOLVED

        # -----------------------------------------------------------------
        # 6. Verify Durable Database State across all 5 events
        # -----------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            all_event_ids = [ev.event_id for ev in (ev1, ev2, ev3, ev4, ev5)]
            rows: list[ConsumerEvent] = []
            for _ in range(50):
                stmt = select(ConsumerEvent).where(
                    ConsumerEvent.consumer_name == consumer_name,
                    ConsumerEvent.event_id.in_(all_event_ids),
                )
                rows = list((await session.execute(stmt)).scalars().all())
                if len(rows) == 5:
                    break
                await asyncio.sleep(0.1)

            assert len(rows) == 5
            for r in rows:
                assert r.status == ConsumerEventStatus.COMPLETED
                assert r.retry_count == 0
                assert r.processed_at is not None
                assert r.last_error is None

    finally:
        stop_consumer.set()
        await dispatcher.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer.stop()


@pytest.mark.asyncio
async def test_e2e_duplicate_delivery_and_idempotency_barrier() -> None:
    """Verifies that re-delivering an already-processed event through real Kafka
    triggers the idempotency barrier, increments duplicates_skipped, commits the offset,
    and does NOT invoke handlers a second time.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline")

    from aiokafka import AIOKafkaProducer

    from app.schemas.events import (
        AggregateType,
        ReportCreatedEvent,
        ReportCreatedPayload,
    )

    consumer_name = f"e2e_idemp_{uuid.uuid4().hex[:8]}"
    group_id = f"e2e_idemp_group_{uuid.uuid4().hex[:8]}"

    handler_calls = 0
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def counting_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        nonlocal handler_calls
        handler_calls += 1

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

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        consumer.run_loop(stop_event=stop_event, poll_timeout_ms=500)
    )

    now = datetime.now(UTC)
    rep_id = uuid.uuid4()
    event = ReportCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="e2e-test",
        aggregate_id=rep_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.KEYS,
            title="Duplicate E2E Keys",
            description="Testing duplicate delivery",
            latitude=40.0,
            longitude=-70.0,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")

    try:
        # First publication
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw_bytes,
            key=str(rep_id).encode("utf-8"),
        )

        # Wait until handler has executed once
        for _ in range(50):
            if handler_calls >= 1:
                break
            await asyncio.sleep(0.1)
        assert handler_calls == 1

        # Second publication (Exact same event_id redelivered via Kafka)
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw_bytes,
            key=str(rep_id).encode("utf-8"),
        )

        # Allow consumer to process duplicate
        for _ in range(50):
            if consumer.metrics.duplicates_skipped >= 1:
                break
            await asyncio.sleep(0.1)

        # Handler must NOT be called again
        assert handler_calls == 1
        assert consumer.metrics.duplicates_skipped == 1

    finally:
        stop_event.set()
        await producer.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer.stop()


@pytest.mark.asyncio
async def test_e2e_malformed_and_poison_quarantine_pipeline() -> None:
    """Verifies that malformed JSON, unsupported versions, and non-object
    JSON payloads are quarantined with correct categories and safe offset commits.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline")

    from aiokafka import AIOKafkaProducer

    consumer_name = f"e2e_poison_{uuid.uuid4().hex[:8]}"
    group_id = f"e2e_poison_group_{uuid.uuid4().hex[:8]}"

    consumer = EventConsumer(
        consumer_name=consumer_name,
        group_id=group_id,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
    )
    await consumer.start()
    if consumer.consumer:
        await consumer.consumer.getmany(timeout_ms=1000)

    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        consumer.run_loop(stop_event=stop_event, poll_timeout_ms=500)
    )

    try:
        # 1. Non-dict JSON payload (JSON array)
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            b"[100, 200, 300]",
            key=b"array-key",
        )

        # 2. Malformed JSON syntax
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            b"{{{not-valid-json",
            key=b"malformed-key",
        )

        # 3. Unsupported version
        unsupported_ver_payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "report.created",
            "event_version": 999,
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "e2e-tester",
            "aggregate_id": str(uuid.uuid4()),
            "aggregate_type": "report",
            "payload": {},
        }
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            json.dumps(unsupported_ver_payload).encode("utf-8"),
            key=b"unsupported-ver-key",
        )

        # Wait until consumer has quarantined 3 messages
        for _ in range(50):
            if consumer.metrics.quarantined >= 3:
                break
            await asyncio.sleep(0.1)

        assert consumer.metrics.quarantined == 3

        # Verify database quarantine records
        async with AsyncSessionLocal() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.status == ConsumerEventStatus.QUARANTINED,
            )
            records = list((await session.execute(stmt)).scalars().all())
            assert len(records) == 3

            categories = {r.error_category for r in records}
            assert ErrorCategory.PARSE_ERROR.value in categories
            assert ErrorCategory.UNSUPPORTED_VERSION.value in categories

    finally:
        stop_event.set()
        await producer.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer.stop()


@pytest.mark.asyncio
async def test_e2e_retry_exhaustion_quarantine_and_operator_replay() -> None:
    """Verifies that an event that persistently fails in handlers is quarantined
    after exhausting retries, commits offset, and can subsequently be safely
    replayed by an operator upon handler resolution.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline")

    from aiokafka import AIOKafkaProducer

    from app.schemas.events import (
        AggregateType,
        ReportCreatedEvent,
        ReportCreatedPayload,
    )

    consumer_name = f"e2e_replay_{uuid.uuid4().hex[:8]}"
    group_id = f"e2e_replay_group_{uuid.uuid4().hex[:8]}"

    should_fail = True
    handler_attempts = 0
    registry = HandlerRegistry()

    @registry.register_func([EventType.REPORT_CREATED])
    async def flappable_handler(ev: BoomerangEvent, session: AsyncSession) -> None:
        nonlocal handler_attempts
        handler_attempts += 1
        if should_fail:
            raise RuntimeError("Downstream service temporarily unreachable")

    consumer = EventConsumer(
        consumer_name=consumer_name,
        group_id=group_id,
        registry=registry,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
        max_retries=2,
        initial_retry_delay=0.05,
    )
    await consumer.start()
    if consumer.consumer:
        await consumer.consumer.getmany(timeout_ms=1000)

    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        consumer.run_loop(stop_event=stop_event, poll_timeout_ms=500)
    )

    now = datetime.now(UTC)
    rep_id = uuid.uuid4()
    target_event_id = uuid.uuid4()
    event = ReportCreatedEvent(
        event_id=target_event_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="e2e-replay-tester",
        aggregate_id=rep_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.OTHER,
            title="Replay Drone",
            description="Testing retry exhaustion and operator replay",
            latitude=12.0,
            longitude=34.0,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")

    try:
        # Publish
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw_bytes,
            key=str(rep_id).encode("utf-8"),
        )

        # Wait until event is quarantined
        for _ in range(50):
            if consumer.metrics.quarantined >= 1:
                break
            await asyncio.sleep(0.1)

        assert consumer.metrics.quarantined == 1
        assert handler_attempts == 2  # max_retries = 2

        # Verify status is QUARANTINED in database
        async with AsyncSessionLocal() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == target_event_id,
            )
            saved = (await session.execute(stmt)).scalar_one_or_none()
            assert saved is not None
            assert saved.status == ConsumerEventStatus.QUARANTINED
            assert saved.error_category == ErrorCategory.HANDLER_ERROR.value

        # -------------------------------------------------------------
        # Operator Intervention: Fix downstream issue and trigger replay
        # -------------------------------------------------------------
        should_fail = False
        replayed = await consumer.replay_quarantined_event(target_event_id)
        assert replayed is True
        assert consumer.metrics.replayed == 1

        # Verify database record is now COMPLETED
        async with AsyncSessionLocal() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == target_event_id,
            )
            saved_after = (await session.execute(stmt)).scalar_one()
            assert saved_after.status == ConsumerEventStatus.COMPLETED
            assert saved_after.last_error is None

    finally:
        stop_event.set()
        await producer.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer.stop()


@pytest.mark.asyncio
async def test_e2e_pending_outbox_across_dispatcher_restart() -> None:
    """Verifies that pending outbox events persist across dispatcher downtime/restarts
    and are cleanly claimed and published by a restarted dispatcher worker.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline")

    from app.services.outbox import create_outbox_event

    now = datetime.now(UTC)
    rep_id = uuid.uuid4()
    ev_id = uuid.uuid4()

    from app.schemas.events import (
        AggregateType,
        ReportCreatedEvent,
        ReportCreatedPayload,
    )

    ev = ReportCreatedEvent(
        event_id=ev_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="restart-test",
        aggregate_id=rep_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.OTHER,
            title="Outbox Restart Report",
            description="Created while dispatcher is offline",
            latitude=15.0,
            longitude=25.0,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )

    # 1. Insert into outbox while dispatcher is NOT running
    async with AsyncSessionLocal() as session:
        await create_outbox_event(session, ev)
        await session.commit()

    # 2. Start a fresh dispatcher instance (simulating restart after downtime)
    dispatcher = OutboxDispatcher(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    await dispatcher.start()
    try:
        # Process pending events
        for _ in range(20):
            p = await dispatcher.process_batch(batch_size=50)
            if p == 0:
                break

        # 3. Verify event is now PUBLISHED in database
        async with AsyncSessionLocal() as session:
            stmt = select(OutboxEvent).where(OutboxEvent.event_id == ev_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            assert row is not None
            assert row.status == OutboxStatus.PUBLISHED
            assert row.published_at is not None

    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_e2e_consumer_restart_resumes_from_committed_offset() -> None:
    """Verifies that when a consumer processes an event, commits offset, and is stopped
    (simulating process restart/crash recovery), a subsequent consumer starting with the
    same group_id resumes strictly from the committed offset without reprocessing.
    """
    if not _is_kafka_online():
        pytest.skip("Kafka broker offline")

    from aiokafka import AIOKafkaProducer

    from app.schemas.events import (
        AggregateType,
        ReportCreatedEvent,
        ReportCreatedPayload,
    )

    shared_group_id = f"e2e_restart_group_{uuid.uuid4().hex[:8]}"
    shared_consumer_name = f"e2e_restart_consumer_{uuid.uuid4().hex[:8]}"

    # Event 1 & Event 2
    now = datetime.now(UTC)
    rep1_id = uuid.uuid4()
    ev1_id = uuid.uuid4()
    ev1 = ReportCreatedEvent(
        event_id=ev1_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="restart-test-1",
        aggregate_id=rep1_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep1_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.KEYS,
            title="Restart Event 1",
            description="First message before restart",
            latitude=10.0,
            longitude=20.0,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )

    ev2_id = uuid.uuid4()
    ev2 = ReportCreatedEvent(
        event_id=ev2_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="restart-test-2",
        aggregate_id=rep1_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep1_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.KEYS,
            title="Restart Event 2",
            description="Second message after restart",
            latitude=10.0,
            longitude=20.0,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )

    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    consumer1_received: list[uuid.UUID] = []
    stop_event_1 = asyncio.Event()
    reg1 = HandlerRegistry()

    @reg1.register_func([EventType.REPORT_CREATED])
    async def handler_1(event: BoomerangEvent, session: AsyncSession) -> None:
        if event.event_id in (ev1_id, ev2_id):
            consumer1_received.append(event.event_id)
            if event.event_id == ev1_id:
                stop_event_1.set()

    consumer_1 = EventConsumer(
        consumer_name=shared_consumer_name,
        group_id=shared_group_id,
        registry=reg1,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
    )
    await consumer_1.start()
    if consumer_1.consumer:
        await consumer_1.consumer.getmany(timeout_ms=1000)

    consumer1_task = asyncio.create_task(
        consumer_1.run_loop(stop_event=stop_event_1, poll_timeout_ms=500)
    )

    try:
        # Publish Event 1
        raw1 = json.dumps(ev1.model_dump(mode="json")).encode("utf-8")
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw1,
            key=str(rep1_id).encode("utf-8"),
        )

        # Wait for consumer 1 to process Event 1, commit offset, and exit
        await asyncio.wait_for(stop_event_1.wait(), timeout=10.0)
        # Give consumer loop a moment to finish commit and exit
        await asyncio.wait_for(consumer1_task, timeout=5.0)

        assert consumer1_received == [ev1_id]

        # Verify Event 1 is COMPLETED in DB
        async with AsyncSessionLocal() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == shared_consumer_name,
                ConsumerEvent.event_id == ev1_id,
            )
            saved1 = (await session.execute(stmt)).scalar_one_or_none()
            assert saved1 is not None
            assert saved1.status == ConsumerEventStatus.COMPLETED

        # -------------------------------------------------------------
        # Publish Event 2 with SAME key while consumer offline
        # -------------------------------------------------------------
        raw2 = json.dumps(ev2.model_dump(mode="json")).encode("utf-8")
        await producer.send_and_wait(
            settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            raw2,
            key=str(rep1_id).encode("utf-8"),
        )

        # -------------------------------------------------------------
        # Start Consumer 2 with the SAME group_id and consumer_name
        # The committed offset on this partition will be honored by Kafka.
        # -------------------------------------------------------------
        consumer2_received: list[uuid.UUID] = []
        stop_event_2 = asyncio.Event()
        reg2 = HandlerRegistry()

        @reg2.register_func([EventType.REPORT_CREATED])
        async def handler_2(event: BoomerangEvent, session: AsyncSession) -> None:
            if event.event_id in (ev1_id, ev2_id):
                consumer2_received.append(event.event_id)
                if event.event_id == ev2_id:
                    stop_event_2.set()

        consumer_2 = EventConsumer(
            consumer_name=shared_consumer_name,
            group_id=shared_group_id,
            registry=reg2,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset="latest",
        )
        await consumer_2.start()

        consumer2_task = asyncio.create_task(
            consumer_2.run_loop(stop_event=stop_event_2, poll_timeout_ms=500)
        )

        try:
            await asyncio.wait_for(stop_event_2.wait(), timeout=10.0)
            stop_event_2.set()
            await asyncio.wait_for(consumer2_task, timeout=5.0)

            # CRITICAL INVARIANT: Consumer 2 must receive Event 2 and NOT Event 1
            assert ev2_id in consumer2_received
            assert ev1_id not in consumer2_received

            # Verify Event 2 is COMPLETED in DB
            async with AsyncSessionLocal() as session:
                stmt = select(ConsumerEvent).where(
                    ConsumerEvent.consumer_name == shared_consumer_name,
                    ConsumerEvent.event_id == ev2_id,
                )
                saved2 = (await session.execute(stmt)).scalar_one_or_none()
                assert saved2 is not None
                assert saved2.status == ConsumerEventStatus.COMPLETED

        finally:
            stop_event_2.set()
            if not consumer2_task.done():
                consumer2_task.cancel()
                try:
                    await consumer2_task
                except (asyncio.CancelledError, Exception):
                    pass
            await consumer_2.stop()

    finally:
        await producer.stop()
        if not consumer1_task.done():
            consumer1_task.cancel()
            try:
                await consumer1_task
            except (asyncio.CancelledError, Exception):
                pass
        await consumer_1.stop()
