"""Comprehensive unit and integration tests for Phase 8.4 Kafka Matching Worker.

Formalized in docs/matching_specification.md (Phase 8.1 & 8.4).
Verifies:
- Event consumption for report.created, report.updated, and report.resolved.
- Safe handling of unknown event types, missing reports, and non-ACTIVE reports.
- Integration between Phase 8.2 Candidate Retrieval and Phase 8.3 Scoring.
- Authoritative PostgreSQL state overriding stale event payloads.
- Result handoff boundary behavior and non-persistence documentation invariant.
- Consumer reliability invariants: idempotency barrier, retries, quarantine, offset.
- Graceful shutdown and live Kafka roundtrip.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiokafka import ConsumerRecord, TopicPartition
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ConsumerEvent,
    ConsumerEventStatus,
    RecoveryRequestStatus,
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
    User,
)
from app.schemas.events import (
    AggregateType,
    BoomerangEvent,
    EventType,
    RecoveryRequestCreatedEvent,
    RecoveryRequestCreatedPayload,
    ReportCreatedEvent,
    ReportCreatedPayload,
    ReportResolvedEvent,
    ReportResolvedPayload,
    ReportUpdatedEvent,
    ReportUpdatedPayload,
)
from app.services.event_consumer import (
    ConsumerProcessingResult,
    ErrorCategory,
    EventConsumer,
    HandlerRegistry,
)
from app.services.matching import (
    InMemoryMatchResultHandoff,
    MatchingEventHandler,
    create_matching_consumer,
    run_matching_worker,
)


def _is_kafka_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _get_isolated_coords() -> tuple[float, float]:
    """Generates globally isolated coordinates for spatial test isolation."""
    u = uuid.uuid4().int
    lat = -55.0 + ((u % 110000) / 1000.0)
    lon = -140.0 + (((u >> 32) % 280000) / 1000.0)
    return round(lat, 5), round(lon, 5)


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


class _WorkerTestContext:
    """Manages database setup, reports, users, and cleanup for matching worker tests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base_lat, self.base_lon = _get_isolated_coords()
        self.report_ids: list[uuid.UUID] = []
        self.user_ids: list[uuid.UUID] = []
        self.consumer_names: list[str] = []

    async def create_user(self, name: str | None = None) -> User:
        uid = uuid.uuid4().hex[:8]
        user = User(
            name=name or f"User_{uid}",
            email=f"worker_{uid}@example.com",
            password_hash="test_password_hash",
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    async def create_report(
        self,
        user_id: uuid.UUID,
        report_type: ReportType,
        title: str = "Test Item",
        description: str = "Detailed description",
        category: ReportCategory = ReportCategory.ELECTRONICS,
        status: ReportStatus = ReportStatus.ACTIVE,
        lat_offset: float = 0.0,
        lon_offset: float = 0.0,
        event_time: datetime | None = None,
    ) -> Report:
        lat = self.base_lat + lat_offset
        lon = self.base_lon + lon_offset
        wkt = f"POINT({lon} {lat})"
        report = Report(
            created_by_user_id=user_id,
            type=report_type,
            title=title,
            description=description,
            category=category,
            location=WKTElement(wkt, srid=4326),
            event_time=event_time or datetime.now(UTC),
            status=status,
            created_at=datetime.now(UTC),
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        self.report_ids.append(report.id)
        return report

    async def cleanup(self) -> None:
        if self.consumer_names:
            await self.session.execute(
                delete(ConsumerEvent).where(
                    ConsumerEvent.consumer_name.in_(self.consumer_names)
                )
            )
        if self.report_ids:
            await self.session.execute(
                delete(Report).where(Report.id.in_(self.report_ids))
            )
        if self.user_ids:
            await self.session.execute(delete(User).where(User.id.in_(self.user_ids)))
        await self.session.commit()


def _build_report_created_event(
    report: Report,
    latitude: float,
    longitude: float,
    event_id: uuid.UUID | None = None,
) -> ReportCreatedEvent:
    ev_id = event_id or uuid.uuid4()
    now = datetime.now(UTC)
    payload = ReportCreatedPayload(
        report_id=report.id,
        created_by_user_id=report.created_by_user_id,
        type=report.type,
        category=report.category,
        title=report.title,
        description=report.description or "Default description",
        latitude=latitude,
        longitude=longitude,
        event_time=report.event_time or now,
        reward_amount=None,
        status=ReportStatus.ACTIVE,
        created_at=report.created_at,
    )
    return ReportCreatedEvent(
        event_id=ev_id,
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="boomerang.test",
        aggregate_id=report.id,
        aggregate_type=AggregateType.REPORT,
        payload=payload,
    )


def _build_report_updated_event(
    report_id: uuid.UUID,
    updated_fields: list[str],
    title: str | None = None,
    description: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    event_id: uuid.UUID | None = None,
) -> ReportUpdatedEvent:
    ev_id = event_id or uuid.uuid4()
    now = datetime.now(UTC)
    payload = ReportUpdatedPayload(
        report_id=report_id,
        updated_fields=updated_fields,
        title=title,
        description=description,
        latitude=latitude,
        longitude=longitude,
        updated_at=now,
    )
    return ReportUpdatedEvent(
        event_id=ev_id,
        event_type=EventType.REPORT_UPDATED,
        event_version=1,
        occurred_at=now,
        producer="boomerang.test",
        aggregate_id=report_id,
        aggregate_type=AggregateType.REPORT,
        payload=payload,
    )


def _build_report_resolved_event(
    report_id: uuid.UUID,
    event_id: uuid.UUID | None = None,
) -> ReportResolvedEvent:
    ev_id = event_id or uuid.uuid4()
    now = datetime.now(UTC)
    payload = ReportResolvedPayload(
        report_id=report_id,
        status=ReportStatus.RESOLVED,
        resolved_at=now,
        resolution_reason="user_resolved",
    )
    return ReportResolvedEvent(
        event_id=ev_id,
        event_type=EventType.REPORT_RESOLVED,
        event_version=1,
        occurred_at=now,
        producer="boomerang.test",
        aggregate_id=report_id,
        aggregate_type=AggregateType.REPORT,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# 1. Event Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_worker_report_created_missing_source() -> None:
    """1. Tests report.created for MISSING source retrieves and scores FOUND reports."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Candidate: FOUND iPhone 15 Pro
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found black iPhone 15 Pro",
                description="Found black titanium iPhone 15 Pro on bench in clear case",
                category=ReportCategory.ELECTRONICS,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            # Source: MISSING iPhone 15 Pro
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost iPhone 15 Pro",
                description="Black iPhone 15 Pro in clear silicone case",
                category=ReportCategory.ELECTRONICS,
                lat_offset=0.0,
                lon_offset=0.0,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()
            mock_kafka.commit = AsyncMock()

            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_created_event(missing, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=201, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            # Verify results collected in handoff
            results = await handoff.get_results_for_report(missing.id)
            assert len(results) == 1
            match = results[0]
            assert match.source_id == missing.id
            assert match.candidate_id == found.id
            assert match.composite_score >= 75.0
            assert match.alert_eligible is True

            # Verify Kafka offset committed
            mock_kafka.commit.assert_called_once()

            # Verify idempotency record in DB
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == event.event_id,
            )
            ce = (await session.execute(stmt)).scalar_one_or_none()
            assert ce is not None
            assert ce.status == ConsumerEventStatus.COMPLETED
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_report_created_found_source() -> None:
    """2. Tests report.created for FOUND source retrieves and scores MISSING reports."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Existing MISSING report
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost Golden Retriever",
                description="Golden Retriever with red collar lost in park",
                category=ReportCategory.PET,
                lat_offset=0.002,
                lon_offset=0.002,
            )

            # Newly created FOUND report
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found friendly Golden Retriever",
                description="Golden Retriever with red collar near playground",
                category=ReportCategory.PET,
                lat_offset=0.0,
                lon_offset=0.0,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()

            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_created_event(found, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=202, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(found.id)
            assert len(results) == 1
            assert results[0].source_id == found.id
            assert results[0].candidate_id == missing.id
            assert results[0].composite_score >= 60.0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_report_updated() -> None:
    """3. Tests report.updated triggers re-evaluation against candidate reports."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u1 = await ctx.create_user("User1")
            u2 = await ctx.create_user("User2")

            found = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                title="Found Blue Patagonia Backpack",
                description="Navy blue backpack with laptop inside",
                category=ReportCategory.BAG,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Backpack",
                description="Blue Patagonia daypack",
                category=ReportCategory.BAG,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()

            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_updated_event(
                report_id=missing.id,
                updated_fields=["title", "description"],
                title="Lost Patagonia Backpack Blue",
                description="Navy blue Patagonia backpack with laptop",
            )
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=203, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(missing.id)
            assert len(results) == 1
            assert results[0].candidate_id == found.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_report_resolved() -> None:
    """4. Tests report.resolved acknowledges safely without active matches."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u1 = await ctx.create_user("User1")
            u2 = await ctx.create_user("User2")

            await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                title="Found Keys",
                category=ReportCategory.KEYS,
            )

            resolved_report = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Keys",
                category=ReportCategory.KEYS,
                status=ReportStatus.RESOLVED,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()

            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_resolved_event(resolved_report.id)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=204, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            # Invariant: NO candidate results generated for resolved reports
            results = await handoff.get_results_for_report(resolved_report.id)
            assert len(results) == 0

            # Verified committed
            mock_kafka.commit.assert_called_once()
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_unknown_event_type_safely_ignored() -> None:
    """5. Tests that unrelated event types are safely ignored."""
    consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
    mock_kafka = AsyncMock()
    handoff = InMemoryMatchResultHandoff()

    consumer, _ = create_matching_consumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
        handoff=handoff,
    )

    now = datetime.now(UTC)
    req_id = uuid.uuid4()
    rep_id = uuid.uuid4()
    req_payload = RecoveryRequestCreatedPayload(
        recovery_request_id=req_id,
        report_id=rep_id,
        requester_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        status=RecoveryRequestStatus.PENDING,
        created_at=now,
    )
    event = RecoveryRequestCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_CREATED,
        event_version=1,
        occurred_at=now,
        producer="boomerang.test",
        aggregate_id=req_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=req_payload,
    )
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=205, value=raw_bytes)

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.IGNORED

    # Offset must still be committed to advance consumer partition
    mock_kafka.commit.assert_called_once()
    assert len(await handoff.get_all_results()) == 0

    # Clean up idempotency record
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ConsumerEvent).where(ConsumerEvent.consumer_name == consumer_name)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_matching_worker_missing_report_in_db_skipped() -> None:
    """6. Tests that event referencing non-existent report skips matching."""
    consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
    mock_kafka = AsyncMock()
    handoff = InMemoryMatchResultHandoff()
    consumer, _ = create_matching_consumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
        handoff=handoff,
    )

    non_existent_id = uuid.uuid4()
    now = datetime.now(UTC)
    payload = ReportCreatedPayload(
        report_id=non_existent_id,
        created_by_user_id=uuid.uuid4(),
        type=ReportType.MISSING,
        category=ReportCategory.ELECTRONICS,
        title="Ghost Laptop",
        description="Not in database",
        latitude=40.7128,
        longitude=-74.0060,
        event_time=now,
        status=ReportStatus.ACTIVE,
        created_at=now,
    )
    event = ReportCreatedEvent(
        event_type=EventType.REPORT_CREATED,
        occurred_at=now,
        producer="boomerang.test",
        aggregate_id=non_existent_id,
        aggregate_type=AggregateType.REPORT,
        payload=payload,
    )
    raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
    record = _create_mock_record(offset=206, value=raw_bytes)

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.SUCCESS
    assert len(await handoff.get_results_for_report(non_existent_id)) == 0

    # Clean up
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ConsumerEvent).where(ConsumerEvent.consumer_name == consumer_name)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_matching_worker_inactive_source_report_skipped() -> None:
    """7. Tests that a report whose status is CANCELLED skips candidate matching."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u = await ctx.create_user("User")
            cancelled_report = await ctx.create_report(
                u.id,
                ReportType.MISSING,
                title="Cancelled Report",
                status=ReportStatus.CANCELLED,
            )

            mock_kafka = AsyncMock()
            handoff = InMemoryMatchResultHandoff()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_created_event(
                cancelled_report, ctx.base_lat, ctx.base_lon
            )
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=207, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS
            assert len(await handoff.get_results_for_report(cancelled_report.id)) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_malformed_event_quarantined() -> None:
    """8. Tests that malformed JSON payloads are safely quarantined."""
    consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
    mock_kafka = AsyncMock()
    consumer, _ = create_matching_consumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
    )

    record = _create_mock_record(offset=208, value=b"{corrupted-json-payload-not-valid")

    result = await consumer.process_record(record)
    assert result == ConsumerProcessingResult.QUARANTINED
    mock_kafka.commit.assert_called_once()

    async with AsyncSessionLocal() as session:
        stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.offset == 208,
        )
        ce = (await session.execute(stmt)).scalar_one_or_none()
        assert ce is not None
        assert ce.status == ConsumerEventStatus.QUARANTINED
        assert ce.error_category == ErrorCategory.PARSE_ERROR.value

        await session.execute(
            delete(ConsumerEvent).where(ConsumerEvent.consumer_name == consumer_name)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# 2. Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_worker_latest_db_state_overrides_stale_event_payload() -> None:
    """Integration: Latest PostgreSQL state overrides stale event payload data."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Candidate in DB: FOUND MacBook Pro 16 inch space gray
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found Space Gray MacBook Pro 16",
                description="Found Apple MacBook Pro 16 inch in space gray finish",
                category=ReportCategory.ELECTRONICS,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            # DB has updated fresh report title: "Apple MacBook Pro 16 Space Gray"
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Apple MacBook Pro 16 Space Gray",
                description="Left Apple laptop on desk in library",
                category=ReportCategory.ELECTRONICS,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            # Stale event payload says title was "Old generic bag"
            now = datetime.now(UTC)
            stale_payload = ReportCreatedPayload(
                report_id=missing.id,
                created_by_user_id=missing.created_by_user_id,
                type=ReportType.MISSING,
                category=ReportCategory.ELECTRONICS,
                title="Old generic item description",
                description="Stale description in event payload",
                latitude=ctx.base_lat,
                longitude=ctx.base_lon,
                event_time=now,
                status=ReportStatus.ACTIVE,
                created_at=missing.created_at,
            )
            event = ReportCreatedEvent(
                event_type=EventType.REPORT_CREATED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=missing.id,
                aggregate_type=AggregateType.REPORT,
                payload=stale_payload,
            )

            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=209, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(missing.id)
            assert len(results) == 1
            # Scored against the fresh DB MacBook Pro, not the stale payload
            assert results[0].candidate_id == found.id
            assert results[0].identity.matched_brand == "Apple"
            assert results[0].composite_score >= 70.0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_updated_coordinates_in_db_used_for_retrieval() -> None:
    """Integration: Updated coordinates in PostgreSQL are used for retrieval."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Candidate at base coordinates
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found AirPods Pro",
                description="White AirPods Pro case",
                category=ReportCategory.ELECTRONICS,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            # Source report was saved in DB at base coordinates (within 200m)
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost AirPods Pro",
                description="White AirPods Pro wireless earbuds",
                category=ReportCategory.ELECTRONICS,
                lat_offset=0.0,
                lon_offset=0.0,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            # But the event payload has stale coordinates far away (+1.0 lat = ~111 km)
            now = datetime.now(UTC)
            stale_coords_payload = ReportUpdatedPayload(
                report_id=missing.id,
                updated_fields=["latitude", "longitude"],
                latitude=ctx.base_lat + 1.0,
                longitude=ctx.base_lon + 1.0,
                updated_at=now,
            )
            event = ReportUpdatedEvent(
                event_type=EventType.REPORT_UPDATED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=missing.id,
                aggregate_type=AggregateType.REPORT,
                payload=stale_coords_payload,
            )

            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=210, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(missing.id)
            # Candidate found because DB location was used, not event payload
            assert len(results) == 1
            assert results[0].candidate_id == found.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_empty_candidates_handled_cleanly() -> None:
    """Integration: Report with 0 matching candidates completes successfully."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u = await ctx.create_user("User")
            isolated_missing = await ctx.create_report(
                u.id,
                ReportType.MISSING,
                title="Lost item in isolation",
                category=ReportCategory.JEWELRY,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_created_event(
                isolated_missing, ctx.base_lat, ctx.base_lon
            )
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=211, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(isolated_missing.id)
            assert results == []
            mock_kafka.commit.assert_called_once()
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_non_alert_eligible_candidates_recorded() -> None:
    """Integration: Verifies non-alert-eligible candidates are scored and recorded."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Category OTHER with vague description -> not alert eligible
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found some thing",
                description="Metal thing found on sidewalk",
                category=ReportCategory.OTHER,
                lat_offset=0.005,
                lon_offset=0.005,
            )

            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost unknown object",
                description="Small metal piece",
                category=ReportCategory.OTHER,
            )

            handoff = InMemoryMatchResultHandoff()
            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=handoff,
            )

            event = _build_report_created_event(missing, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=212, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS

            results = await handoff.get_results_for_report(missing.id)
            assert len(results) == 1
            assert results[0].candidate_id == found.id
            assert results[0].alert_eligible is False
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# 3. Reliability Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_worker_duplicate_event_skips_processing() -> None:
    """Reliability: Verifies duplicate event delivery is safely skipped."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u = await ctx.create_user("User")
            report = await ctx.create_report(
                u.id, ReportType.MISSING, title="Duplicate Test Item"
            )

            mock_handoff = AsyncMock()
            mock_handoff.record_matches = AsyncMock()

            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=mock_handoff,
            )

            event = _build_report_created_event(report, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=213, value=raw_bytes)

            # First delivery
            res1 = await consumer.process_record(record)
            assert res1 == ConsumerProcessingResult.SUCCESS
            assert mock_handoff.record_matches.call_count == 1

            # Second delivery (duplicate event)
            record_dup = _create_mock_record(offset=214, value=raw_bytes)
            res2 = await consumer.process_record(record_dup)
            assert res2 == ConsumerProcessingResult.DUPLICATE_SKIPPED

            # Invariant: Handoff was NOT called a second time
            assert mock_handoff.record_matches.call_count == 1
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_retryable_database_failure_recovers() -> None:
    """Reliability: Transient handler failure retries and succeeds on next attempt."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u = await ctx.create_user("User")
            report = await ctx.create_report(
                u.id, ReportType.MISSING, title="Retry Test Item"
            )

            call_count = 0

            class _FlakyHandoff:
                async def record_matches(
                    self,
                    source_report: Report,
                    results: list[Any],
                    session: AsyncSession,
                ) -> None:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        raise RuntimeError("Simulated transient DB connection error")

            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=_FlakyHandoff(),
                max_retries=3,
                initial_retry_delay=0.01,
            )

            event = _build_report_created_event(report, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=215, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS
            assert call_count == 2
            mock_kafka.commit.assert_called_once()
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_scoring_failure_quarantines_after_max_retries() -> None:
    """Reliability: Permanent failure quarantines event and commits offset."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u = await ctx.create_user("User")
            report = await ctx.create_report(
                u.id, ReportType.MISSING, title="Poison Item"
            )

            class _FailingHandoff:
                async def record_matches(
                    self,
                    source_report: Report,
                    results: list[Any],
                    session: AsyncSession,
                ) -> None:
                    raise ValueError("Unrecoverable data corruption in match pipeline")

            mock_kafka = AsyncMock()
            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                consumer=mock_kafka,
                handoff=_FailingHandoff(),
                max_retries=2,
                initial_retry_delay=0.01,
            )

            event = _build_report_created_event(report, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=216, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.QUARANTINED
            mock_kafka.commit.assert_called_once()

            # Verify quarantined state in PostgreSQL
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == consumer_name,
                ConsumerEvent.event_id == event.event_id,
            )
            ce = (await session.execute(stmt)).scalar_one_or_none()
            assert ce is not None
            assert ce.status == ConsumerEventStatus.QUARANTINED
            assert ce.error_category == ErrorCategory.HANDLER_ERROR.value
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_tx_failure_after_handoff_discards_staged() -> None:
    """Reliability: Transaction failure after handoff discards results cleanly."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            # Candidate in DB
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found Black Leather Wallet",
                description="Black leather wallet with cards",
                category=ReportCategory.WALLET,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            # Source in DB
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost Black Leather Wallet",
                description="Black leather bifold wallet",
                category=ReportCategory.WALLET,
            )

            handoff = InMemoryMatchResultHandoff()
            registry = HandlerRegistry()
            matching_handler = MatchingEventHandler(handoff=handoff)
            registry.register(matching_handler)

            attempts = 0

            # Register companion handler running in same tx AFTER matching_handler
            @registry.register_func(
                [EventType.REPORT_CREATED], name="FlakyDownstreamHandler"
            )
            async def downstream_flaky_handler(
                ev: BoomerangEvent, sess: AsyncSession
            ) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    # MatchingEventHandler has run and called record_matches(),
                    # but enclosing DB transaction hasn't committed yet.
                    # Simulate failure (e.g. DB error or downstream constraint):
                    raise RuntimeError(
                        "Simulated transaction failure AFTER in-memory handoff"
                    )

            mock_kafka = AsyncMock()
            consumer = EventConsumer(
                consumer_name=consumer_name,
                registry=registry,
                consumer=mock_kafka,
                max_retries=3,
                initial_retry_delay=0.01,
            )

            event = _build_report_created_event(missing, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=217, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.SUCCESS
            assert attempts == 2

            # Critical assertions:
            # 1. Exactly 1 match result set (no duplicates from failed attempt 1)
            all_results = await handoff.get_all_results()
            assert len(all_results) == 1
            assert all_results[0].candidate_id == found.id

            results_for_report = await handoff.get_results_for_report(missing.id)
            assert len(results_for_report) == 1
            assert results_for_report[0].candidate_id == found.id

            # 2. Offset was committed and ConsumerEvent is COMPLETED
            mock_kafka.commit.assert_called_once()
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_permanent_transaction_failure_leaves_handoff_empty() -> (
    None
):
    """Reliability: Permanent transaction failure leaves handoff empty on quarantine."""
    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("Owner")
            u_finder = await ctx.create_user("Finder")

            await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found Watch",
                category=ReportCategory.JEWELRY,
            )
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost Watch",
                category=ReportCategory.JEWELRY,
            )

            handoff = InMemoryMatchResultHandoff()
            registry = HandlerRegistry()
            matching_handler = MatchingEventHandler(handoff=handoff)
            registry.register(matching_handler)

            # Companion handler that permanently fails on all attempts
            @registry.register_func([EventType.REPORT_CREATED])
            async def always_failing_handler(
                ev: BoomerangEvent, sess: AsyncSession
            ) -> None:
                raise RuntimeError("Permanent failure in transaction")

            mock_kafka = AsyncMock()
            consumer = EventConsumer(
                consumer_name=consumer_name,
                registry=registry,
                consumer=mock_kafka,
                max_retries=2,
                initial_retry_delay=0.01,
            )

            event = _build_report_created_event(missing, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")
            record = _create_mock_record(offset=218, value=raw_bytes)

            result = await consumer.process_record(record)
            assert result == ConsumerProcessingResult.QUARANTINED

            # Critical assertion: quarantined event leaves ZERO staged results
            all_results = await handoff.get_all_results()
            assert len(all_results) == 0
            results_for_report = await handoff.get_results_for_report(missing.id)
            assert len(results_for_report) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_matching_worker_graceful_shutdown() -> None:
    """Reliability: Verifies run_matching_worker shuts down on stop_event."""
    consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
    mock_kafka = AsyncMock()

    stop_event = asyncio.Event()
    polls = 0

    async def _mock_getmany(
        timeout_ms: int = 1000, max_records: int = 100
    ) -> dict[Any, Any]:
        nonlocal polls
        polls += 1
        await asyncio.sleep(0.01)
        if polls >= 2:
            stop_event.set()
        return {}

    mock_kafka.getmany = _mock_getmany

    total_processed = await run_matching_worker(
        stop_event=stop_event,
        poll_timeout_ms=50,
        consumer_name=consumer_name,
        consumer=mock_kafka,
    )

    assert total_processed == 0
    assert polls >= 2


@pytest.mark.asyncio
async def test_matching_worker_rebalance_partition_revocation_safety() -> None:
    """Reliability: Partition revocation commits safe offset and clears tracker."""
    consumer_name = f"test_worker_{uuid.uuid4().hex[:8]}"
    mock_kafka = AsyncMock()
    mock_kafka.commit = AsyncMock()

    consumer, _ = create_matching_consumer(
        consumer_name=consumer_name,
        consumer=mock_kafka,
    )

    topic = settings.KAFKA_DOMAIN_EVENTS_TOPIC
    tp = TopicPartition(topic, 0)

    # Enable partition assignment tracking
    consumer.offset_tracker.enable_assignment_tracking()

    # Simulate partition assignment
    await consumer.handle_partitions_assigned([tp])
    assert await consumer.offset_tracker.is_assigned(topic, 0) is True

    # Mark offset 50 durable
    await consumer.offset_tracker.mark_in_flight(topic, 0, 50)
    await consumer.offset_tracker.mark_durable(topic, 0, 50)

    # Revoke partition -> should commit offset 51 and remove partition assignment
    await consumer.handle_partitions_revoked([tp])
    mock_kafka.commit.assert_called_once()
    assert await consumer.offset_tracker.is_assigned(topic, 0) is False


# ---------------------------------------------------------------------------
# 4. Live Kafka Broker Roundtrip Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_worker_live_kafka_roundtrip() -> None:
    """Live verification: Publishes report.created to Kafka and consumes via worker."""
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092

    if not _is_kafka_listening(host, port):
        pytest.skip(f"Kafka broker not reachable at {host}:{port}")

    from aiokafka import AIOKafkaProducer

    async with AsyncSessionLocal() as session:
        ctx = _WorkerTestContext(session)
        consumer_name = f"test_worker_live_{uuid.uuid4().hex[:8]}"
        ctx.consumer_names.append(consumer_name)
        try:
            u_owner = await ctx.create_user("LiveOwner")
            u_finder = await ctx.create_user("LiveFinder")

            # Existing candidate in DB
            found = await ctx.create_report(
                u_finder.id,
                ReportType.FOUND,
                title="Found Titanium Keys with Blue Lanyard",
                description="Car keys on blue carabiner lanyard",
                category=ReportCategory.KEYS,
                lat_offset=0.001,
                lon_offset=0.001,
            )

            # Source report in DB
            missing = await ctx.create_report(
                u_owner.id,
                ReportType.MISSING,
                title="Lost Car Keys Blue Lanyard",
                description="Car keys on blue carabiner clip",
                category=ReportCategory.KEYS,
            )

            event = _build_report_created_event(missing, ctx.base_lat, ctx.base_lon)
            raw_bytes = json.dumps(event.model_dump(mode="json")).encode("utf-8")

            # Start matching consumer configured with auto_offset_reset="latest"
            handoff = InMemoryMatchResultHandoff()
            stop_event = asyncio.Event()

            consumer, _ = create_matching_consumer(
                consumer_name=consumer_name,
                group_id=f"live_group_{uuid.uuid4().hex[:8]}",
                handoff=handoff,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset="latest",
            )
            await consumer.start()
            if consumer.consumer:
                await consumer.consumer.getmany(timeout_ms=1000)

            worker_task = asyncio.create_task(
                consumer.run_loop(stop_event=stop_event, poll_timeout_ms=500)
            )

            # Produce message to live Kafka topic
            producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
            )
            await producer.start()
            try:
                await producer.send_and_wait(
                    topic=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
                    key=str(missing.id).encode("utf-8"),
                    value=raw_bytes,
                )
            finally:
                await producer.stop()

            # Wait for matching worker to process the message
            results = []
            for _ in range(40):
                results = await handoff.get_results_for_report(missing.id)
                if results:
                    break
                await asyncio.sleep(0.25)

            stop_event.set()
            await worker_task

            assert len(results) >= 1
            assert results[0].candidate_id == found.id
            assert results[0].composite_score >= 60.0
        finally:
            await ctx.cleanup()
