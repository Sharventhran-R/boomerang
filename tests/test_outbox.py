"""Tests for Transactional Outbox and Reliable Event Publishing (Phase 7.3)."""

import socket
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    OutboxEvent,
    OutboxStatus,
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
    User,
)
from app.schemas.events import ReportCreatedPayload, parse_event
from app.services.outbox import (
    build_report_created_event,
    create_outbox_event,
)
from app.services.outbox_dispatcher import OutboxDispatcher


def _is_kafka_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


async def register_user(client: AsyncClient, name: str) -> dict[str, str]:
    email = f"outbox_{uuid.uuid4()}@example.com"
    pwd = "password123"
    await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": pwd},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
    )
    token = str(login_res.json()["access_token"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_outbox_event_creation_and_serialization(
    client: AsyncClient,
) -> None:
    """1. Verifies report creation persists outbox row with serialized envelope."""
    headers = await register_user(client, "Outbox User 1")
    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": "Outbox Laptop",
            "description": "MacBook Pro left at cafe",
            "category": "ELECTRONICS",
            "latitude": 37.7749,
            "longitude": -122.4194,
            "event_time": "2026-10-18T10:00:00Z",
            "reward_amount": "100.00",
        },
    )
    assert res.status_code == 201
    report_id = uuid.UUID(res.json()["id"])

    async with AsyncSessionLocal() as session:
        stmt = select(OutboxEvent).where(OutboxEvent.aggregate_id == report_id)
        result = await session.execute(stmt)
        outbox_row = result.scalar_one_or_none()
        assert outbox_row is not None
        assert outbox_row.event_type == "report.created"
        assert outbox_row.aggregate_type == "report"
        assert outbox_row.aggregate_id == report_id
        assert outbox_row.status == OutboxStatus.PENDING
        assert outbox_row.retry_count == 0
        assert outbox_row.topic == settings.KAFKA_DOMAIN_EVENTS_TOPIC

        # Payload must be valid JSON matching the event contract
        parsed = parse_event(outbox_row.payload)
        assert parsed.event_id == outbox_row.event_id
        assert isinstance(parsed.payload, ReportCreatedPayload)
        assert parsed.payload.title == "Outbox Laptop"
        assert parsed.payload.latitude == 37.7749


@pytest.mark.asyncio
async def test_atomic_rollback_leaves_neither_persisted() -> None:
    """2. Verifies atomicity: aborted transaction leaves neither model nor outbox."""
    user_id = uuid.uuid4()
    report_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # Create user first outside the aborted transaction
        user = User(
            id=user_id,
            name="Rollback Test User",
            email=f"rollback_{user_id}@example.com",
            password_hash="fakehash",
        )
        session.add(user)
        await session.commit()

    async with AsyncSessionLocal() as session:
        # Begin transaction with domain model and outbox row
        report = Report(
            id=report_id,
            created_by_user_id=user_id,
            type=ReportType.MISSING,
            title="Atomic Wallet",
            description="Testing rollback atomicity",
            category=ReportCategory.WALLET,
            location="POINT(-73.9851 40.7488)",
            event_time=datetime.now(UTC),
            status=ReportStatus.ACTIVE,
        )
        session.add(report)

        event = build_report_created_event(
            report=report, latitude=40.7488, longitude=-73.9851
        )
        await create_outbox_event(session, event)

        # Force a rollback
        await session.rollback()

    # Verify neither exists in database
    async with AsyncSessionLocal() as session:
        rep = await session.get(Report, report_id)
        assert rep is None

        outbox_res = await session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == report_id)
        )
        assert outbox_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_integrated_operations_emit_correct_events(
    client: AsyncClient,
) -> None:
    """3. Verifies all 5 event types are emitted across the domain lifecycle."""
    headers_owner = await register_user(client, "Owner Lifecycle")
    headers_finder = await register_user(client, "Finder Lifecycle")

    # A. Create report -> report.created
    rep_res = await client.post(
        "/api/v1/reports",
        headers=headers_owner,
        json={
            "type": "MISSING",
            "title": "Camera in park",
            "description": "Black DSLR",
            "category": "ELECTRONICS",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": "2026-10-18T12:00:00Z",
            "reward_amount": "50.00",
        },
    )
    assert rep_res.status_code == 201
    report_id = uuid.UUID(rep_res.json()["id"])

    # B. Update report -> report.updated
    patch_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers_owner,
        json={"title": "Canon DSLR in park"},
    )
    assert patch_res.status_code == 200

    # C. Create recovery request -> recovery_request.created
    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_finder,
        json={
            "report_id": str(report_id),
            "message": "Found your camera by the bench",
        },
    )
    assert rec_res.status_code == 201
    recovery_id = uuid.UUID(rec_res.json()["id"])

    # D. Accept recovery request -> recovery_request.updated
    accept_res = await client.patch(
        f"/api/v1/recovery-requests/{recovery_id}",
        headers=headers_owner,
        json={"status": "ACCEPTED"},
    )
    assert accept_res.status_code == 200

    # E. Complete recovery request -> recovery_request.updated AND report.resolved
    complete_res = await client.patch(
        f"/api/v1/recovery-requests/{recovery_id}",
        headers=headers_owner,
        json={"status": "COMPLETED"},
    )
    assert complete_res.status_code == 200

    # Verify all expected outbox events were recorded
    async with AsyncSessionLocal() as session:
        # Check report events
        rep_events = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == report_id)
                    .order_by(OutboxEvent.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rep_events) == 3
        assert rep_events[0].event_type == "report.created"
        assert rep_events[1].event_type == "report.updated"
        assert "title" in rep_events[1].payload["payload"]["updated_fields"]
        assert rep_events[2].event_type == "report.resolved"
        assert (
            rep_events[2].payload["payload"]["resolution_reason"]
            == "recovery_completed"
        )
        assert rep_events[2].payload["payload"][
            "associated_recovery_request_id"
        ] == str(recovery_id)

        # Check recovery events
        rec_events = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == recovery_id)
                    .order_by(OutboxEvent.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rec_events) == 3
        assert rec_events[0].event_type == "recovery_request.created"
        assert rec_events[1].event_type == "recovery_request.updated"
        assert rec_events[1].payload["payload"]["new_status"] == "ACCEPTED"
        assert rec_events[2].event_type == "recovery_request.updated"
        assert rec_events[2].payload["payload"]["new_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_failed_mutations_and_noops_emit_no_event(
    client: AsyncClient,
) -> None:
    """4. Verifies failed API requests and no-op updates emit zero outbox events."""
    headers = await register_user(client, "Noop User")

    # A. Invalid creation: latitude out of range -> 422
    fail_res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": "Invalid Lat",
            "description": "Invalid coordinates",
            "category": "OTHER",
            "latitude": 999.0,
            "longitude": 0.0,
            "event_time": "2026-10-18T12:00:00Z",
        },
    )
    assert fail_res.status_code == 422

    # B. Self-recovery request -> 400
    valid_rep = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": "Valid Report",
            "description": "Description",
            "category": "OTHER",
            "latitude": 10.0,
            "longitude": 20.0,
            "event_time": "2026-10-18T12:00:00Z",
        },
    )
    assert valid_rep.status_code == 201
    rep_id = valid_rep.json()["id"]

    # Attempt self-recovery
    self_rec = await client.post(
        "/api/v1/recovery-requests",
        headers=headers,
        json={"report_id": rep_id, "message": "Self recovery"},
    )
    assert self_rec.status_code == 400

    # C. No-op update: patch with identical title
    noop_patch = await client.patch(
        f"/api/v1/reports/{rep_id}",
        headers=headers,
        json={"title": "Valid Report"},
    )
    assert noop_patch.status_code == 200

    # Verify only the 1 valid report creation emitted an outbox event
    async with AsyncSessionLocal() as session:
        events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == uuid.UUID(rep_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "report.created"


@pytest.mark.asyncio
async def test_dispatcher_kafka_success_marks_published() -> None:
    """5. Verifies successful Kafka send marks outbox status as PUBLISHED."""
    event_id = uuid.uuid4()
    agg_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        outbox = OutboxEvent(
            event_id=event_id,
            event_type="report.created",
            event_version=1,
            aggregate_type="report",
            aggregate_id=agg_id,
            topic="test.events",
            payload={"test": "payload"},
            status=OutboxStatus.PENDING,
            occurred_at=datetime.now(UTC),
        )
        session.add(outbox)
        await session.commit()
        db_id = outbox.id

    mock_producer = AsyncMock()
    mock_producer.send_and_wait = AsyncMock(return_value=None)

    dispatcher = OutboxDispatcher(producer=mock_producer)
    for _ in range(10):
        processed = await dispatcher.process_batch(batch_size=20)
        async with AsyncSessionLocal() as session:
            ev = await session.get(OutboxEvent, db_id)
            if ev and ev.status == OutboxStatus.PUBLISHED:
                break
        if processed == 0:
            break

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, db_id)
        assert ev is not None
        assert ev.status == OutboxStatus.PUBLISHED
        assert ev.published_at is not None
        assert ev.last_error is None


@pytest.mark.asyncio
async def test_dispatcher_kafka_failure_schedules_retry() -> None:
    """6. Verifies Kafka failure marks outbox as FAILED and schedules retry."""
    event_id = uuid.uuid4()
    agg_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        outbox = OutboxEvent(
            event_id=event_id,
            event_type="report.created",
            event_version=1,
            aggregate_type="report",
            aggregate_id=agg_id,
            topic="test.events",
            payload={"test": "payload"},
            status=OutboxStatus.PENDING,
            occurred_at=datetime.now(UTC),
        )
        session.add(outbox)
        await session.commit()
        db_id = outbox.id

    mock_producer = AsyncMock()
    mock_producer.send_and_wait = AsyncMock(
        side_effect=ConnectionError("Kafka broker unreachable")
    )

    dispatcher = OutboxDispatcher(producer=mock_producer)
    for _ in range(10):
        processed = await dispatcher.process_batch(batch_size=20)
        async with AsyncSessionLocal() as session:
            ev = await session.get(OutboxEvent, db_id)
            if ev and ev.status == OutboxStatus.FAILED:
                break
        if processed == 0:
            break

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, db_id)
        assert ev is not None
        assert ev.status == OutboxStatus.FAILED
        assert ev.retry_count == 1
        assert "ConnectionError" in (ev.last_error or "")
        assert ev.next_retry_at > ev.created_at


@pytest.mark.asyncio
async def test_dispatcher_retry_limit_moves_to_dead_letter() -> None:
    """7. Verifies event exceeding max_retries transitions to DEAD_LETTER status."""
    event_id = uuid.uuid4()
    agg_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # Pre-set retry_count to max_retries - 1
        outbox = OutboxEvent(
            event_id=event_id,
            event_type="report.created",
            event_version=1,
            aggregate_type="report",
            aggregate_id=agg_id,
            topic="test.events",
            payload={"test": "poison"},
            status=OutboxStatus.PENDING,
            retry_count=4,
            max_retries=5,
            occurred_at=datetime.now(UTC),
        )
        session.add(outbox)
        await session.commit()
        db_id = outbox.id

    mock_producer = AsyncMock()
    mock_producer.send_and_wait = AsyncMock(
        side_effect=ValueError("Poison message deserialization error")
    )

    dispatcher = OutboxDispatcher(producer=mock_producer)
    for _ in range(10):
        processed = await dispatcher.process_batch(batch_size=20)
        async with AsyncSessionLocal() as session:
            ev = await session.get(OutboxEvent, db_id)
            if ev and ev.status == OutboxStatus.DEAD_LETTER:
                break
        if processed == 0:
            break

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, db_id)
        assert ev is not None
        assert ev.status == OutboxStatus.DEAD_LETTER
        assert ev.retry_count == 5
        assert "ValueError" in (ev.last_error or "")


@pytest.mark.asyncio
async def test_replay_dead_letter_events() -> None:
    """8. Verifies dead-letter events can be replayed, resetting to PENDING."""
    event_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        outbox = OutboxEvent(
            event_id=event_id,
            event_type="report.created",
            event_version=1,
            aggregate_type="report",
            aggregate_id=uuid.uuid4(),
            topic="test.events",
            payload={"test": "replay"},
            status=OutboxStatus.DEAD_LETTER,
            retry_count=5,
            last_error="Simulated error",
            occurred_at=datetime.now(UTC),
        )
        session.add(outbox)
        await session.commit()
        db_id = outbox.id

    dispatcher = OutboxDispatcher(producer=AsyncMock())
    replayed = await dispatcher.replay_dead_letter_events([event_id])
    assert replayed == 1

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, db_id)
        assert ev is not None
        assert ev.status == OutboxStatus.PENDING
        assert ev.retry_count == 0
        assert ev.last_error is None
        # Must retain original event_id for deduplication
        assert ev.event_id == event_id


@pytest.mark.asyncio
async def test_concurrent_worker_claiming_skip_locked() -> None:
    """9. Verifies concurrent workers claim distinct batches via SKIP LOCKED."""
    ids = [uuid.uuid4() for _ in range(4)]
    async with AsyncSessionLocal() as session:
        for ev_id in ids:
            session.add(
                OutboxEvent(
                    event_id=ev_id,
                    event_type="report.created",
                    event_version=1,
                    aggregate_type="report",
                    aggregate_id=uuid.uuid4(),
                    topic="test.events",
                    payload={"idx": str(ev_id)},
                    status=OutboxStatus.PENDING,
                    occurred_at=datetime.now(UTC),
                )
            )
        await session.commit()

    dispatcher = OutboxDispatcher(producer=AsyncMock())

    # Claim batch of 2 from worker 1
    batch_1 = await dispatcher.claim_batch(batch_size=2)
    # Claim batch of 2 from worker 2
    batch_2 = await dispatcher.claim_batch(batch_size=2)

    ids_1 = {e.event_id for e in batch_1}
    ids_2 = {e.event_id for e in batch_2}

    # Zero overlap between claimed sets
    assert ids_1.isdisjoint(ids_2)


@pytest.mark.asyncio
async def test_outbox_payload_privacy_safety(client: AsyncClient) -> None:
    """10. Verifies outbox events strictly exclude sensitive credentials."""
    headers_a = await register_user(client, "Privacy User A")
    headers_b = await register_user(client, "Privacy User B")

    # Create report
    rep = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Secret Item",
            "description": "Sensitive item test",
            "category": "DOCUMENT",
            "latitude": 12.34,
            "longitude": 56.78,
            "event_time": "2026-10-18T10:00:00Z",
        },
    )
    rep_id = uuid.UUID(rep.json()["id"])

    # Create recovery request with private verification response update
    rec = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": str(rep_id), "message": "I have it"},
    )
    rec_id = uuid.UUID(rec.json()["id"])

    # Add private verification response
    await client.patch(
        f"/api/v1/recovery-requests/{rec_id}",
        headers=headers_b,
        json={
            "status": "PENDING",
            "verification_response": "CONFIDENTIAL_PASSPHRASE_12345",
        },
    )

    async with AsyncSessionLocal() as session:
        events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id.in_([rep_id, rec_id])
                    )
                )
            )
            .scalars()
            .all()
        )

        for event in events:
            raw_json = str(event.payload)
            # Must never contain sensitive password hashes
            # or confidential verification response
            assert "CONFIDENTIAL_PASSPHRASE" not in raw_json
            assert "password" not in raw_json
            assert "refresh_token" not in raw_json

            # Every outbox payload must parse into a valid BoomerangEvent
            validated_event = parse_event(event.payload)
            assert validated_event.event_id == event.event_id


@pytest.mark.asyncio
async def test_existing_api_behavior_unchanged(client: AsyncClient) -> None:
    """11. Verifies reports and recovery API contracts remain fully functional."""
    headers = await register_user(client, "API Contract User")

    # List reports
    list_res = await client.get("/api/v1/reports")
    assert list_res.status_code == 200
    assert "items" in list_res.json()

    # Create report
    create_res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "FOUND",
            "title": "Keys on sidewalk",
            "description": "Brass keys with blue ring",
            "category": "KEYS",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "event_time": "2026-10-18T08:00:00Z",
        },
    )
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["title"] == "Keys on sidewalk"
    assert created["type"] == "FOUND"
    assert created["status"] == "ACTIVE"
    assert created["latitude"] == 51.5074
    assert created["longitude"] == -0.1278


@pytest.mark.asyncio
async def test_real_kafka_outbox_dispatch(client: AsyncClient) -> None:
    """Real end-to-end Kafka outbox integration test (when Kafka broker is online)."""
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092

    if not _is_kafka_listening(host, port):
        pytest.skip(f"Kafka broker not reachable at {host}:{port}")

    from aiokafka import AIOKafkaConsumer

    headers = await register_user(client, "Kafka Live User")
    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": "Live Kafka Report",
            "description": "End-to-end dispatch test",
            "category": "OTHER",
            "latitude": 10.0,
            "longitude": 20.0,
            "event_time": "2026-10-18T12:00:00Z",
        },
    )
    assert res.status_code == 201
    report_id = uuid.UUID(res.json()["id"])

    # Locate outbox event
    async with AsyncSessionLocal() as session:
        ev = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == report_id)
            )
        ).scalar_one()
        target_event_id = ev.event_id

    # Subscribe consumer to topic
    group_id = f"outbox-test-{uuid.uuid4().hex[:8]}"
    consumer = AIOKafkaConsumer(
        settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="earliest",
    )
    await consumer.start()

    dispatcher = OutboxDispatcher(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await dispatcher.start()

    try:
        # Process the batch with real Kafka producer
        processed = await dispatcher.process_batch(batch_size=10)
        assert processed >= 1

        # Assert outbox row is now PUBLISHED in database
        async with AsyncSessionLocal() as session:
            updated_ev = await session.get(OutboxEvent, ev.id)
            assert updated_ev is not None
            assert updated_ev.status == OutboxStatus.PUBLISHED
            assert updated_ev.published_at is not None

        # Verify consumer receives the event envelope
        found = False
        async for msg in consumer:
            import json

            payload = json.loads(msg.value.decode("utf-8"))
            if payload.get("event_id") == str(target_event_id):
                assert payload["event_type"] == "report.created"
                assert payload["aggregate_id"] == str(report_id)
                found = True
                break
        assert found is True

    finally:
        await dispatcher.stop()
        await consumer.stop()
