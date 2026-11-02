"""Comprehensive tests for Boomerang Kafka Notification Consumer (Phase 9.3).

Verifies:
- 'match.alert_ready' event schema validation, payload rules, and envelope parser.
- Transactional outbox event emission in MatchPersistenceService during match recording.
- Notification consumer group 'boomerang.notification_engine.group' handler dispatch.
- Match alert recipient routing:
  - High Priority (S >= 80): notifies both report authors.
  - Possible Match (75 <= S < 80): notifies source_owner_id only.
  - S < 75 or alert_eligible=False: suppressed.
- Rescored match update notification rules:
  - Significant improvement (score_delta >= 10.0) or transition to High Priority.
  - Micro-fluctuation filter (score_delta < 5.0) suppressed.
  - 4-hour cooldown per recipient on match updates.
- Recovery request lifecycle alerts:
  - Created: recipient notified, zero verification secret leaks.
  - Updated: ACCEPTED -> requester, REJECTED -> requester, COMPLETED -> both parties.
- Report status lifecycle alerts:
  - Resolved: report author notified.
  - Updated: non-ACTIVE status transitions notify author; routine edits ignored.
- User preference evaluation:
  - Global channels (push_enabled, in_app_enabled).
  - Match filters (match_alerts_enabled, match_min_score, match_high_priority_only).
- Push delivery task creation and quiet-hours delivery buffering.
- ConsumerEvent idempotency barrier: duplicate event delivery skips re-processing.
- Unrelated domain event handling (safely recorded as IGNORED).
- Atomic transaction guarantees across ConsumerEvent, Notification, and delivery tasks.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest
from aiokafka import ConsumerRecord
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    ConsumerEvent,
    ConsumerEventStatus,
    DeliveryStatus,
    DevicePlatform,
    Match,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationPriority,
    NotificationType,
    OutboxEvent,
    RecoveryRequestStatus,
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
    ScoreClassification,
    User,
    UserDevice,
)
from app.schemas.events import (
    AggregateType,
    BoomerangEvent,
    EventType,
    MatchAlertReadyEvent,
    MatchAlertReadyPayload,
    RecoveryRequestCreatedEvent,
    RecoveryRequestCreatedPayload,
    RecoveryRequestUpdatedEvent,
    RecoveryRequestUpdatedPayload,
    ReportCreatedEvent,
    ReportCreatedPayload,
    ReportResolvedEvent,
    ReportResolvedPayload,
    ReportUpdatedEvent,
    ReportUpdatedPayload,
)
from app.services.event_consumer import (
    ConsumerProcessingResult,
    EventConsumer,
)
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    TimeBreakdown,
)
from app.services.matching.persistence import MatchPersistenceService
from app.services.notification import (
    compute_next_delivery_time,
    create_notification,
    register_device,
    update_preferences,
)
from app.services.notification_consumer import (
    NOTIFICATION_CONSUMER_GROUP,
    NotificationEventHandler,
    create_notification_consumer,
)


def _create_mock_consumer_record(
    event_payload_bytes: bytes,
    topic: str = "boomerang.domain.events",
    partition: int = 0,
    offset: int = 1,
) -> ConsumerRecord:
    """Builds an aiokafka ConsumerRecord for testing event processing."""
    return ConsumerRecord(
        topic=topic,
        partition=partition,
        offset=offset,
        timestamp=int(datetime.now(UTC).timestamp() * 1000),
        timestamp_type=0,
        key=None,
        value=event_payload_bytes,
        checksum=None,
        serialized_key_size=0,
        serialized_value_size=len(event_payload_bytes),
        headers=(),
    )


class NotificationConsumerTestContext:
    """Isolates test data lifecycle with safe child-to-parent cleanup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []
        self.report_ids: list[uuid.UUID] = []
        self.match_ids: list[uuid.UUID] = []
        self.consumer_names: list[str] = []

    async def create_user(self, name: str = "User") -> User:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            email=f"user_{uid.hex[:8]}@example.com",
            name=name,
            password_hash="test_hash_pw",
        )
        self.session.add(user)
        await self.session.flush()
        self.user_ids.append(user.id)
        return user

    async def create_report(
        self,
        user_id: uuid.UUID,
        report_type: ReportType = ReportType.MISSING,
        status: ReportStatus = ReportStatus.ACTIVE,
        category: ReportCategory = ReportCategory.ELECTRONICS,
        title: str = "Test Item",
    ) -> Report:
        rid = uuid.uuid4()
        report = Report(
            id=rid,
            created_by_user_id=user_id,
            type=report_type,
            title=title,
            description="Item details for notification consumer test",
            category=category,
            location=WKTElement("POINT(-122.4194 37.7749)", srid=4326),
            event_time=datetime.now(UTC),
            status=status,
            created_at=datetime.now(UTC),
        )
        self.session.add(report)
        await self.session.flush()
        self.report_ids.append(report.id)
        return report

    async def cleanup(self) -> None:
        try:
            await self.session.rollback()
            await self.session.close()
        except Exception:
            pass

        async with AsyncSessionLocal() as cleanup_session:
            # 1. Clean up NotificationDeliveries and Notifications
            if self.user_ids:
                notif_subquery = select(Notification.id).where(
                    Notification.user_id.in_(self.user_ids)
                )
                device_subquery = select(UserDevice.id).where(
                    UserDevice.user_id.in_(self.user_ids)
                )
                await cleanup_session.execute(
                    delete(NotificationDelivery).where(
                        (NotificationDelivery.notification_id.in_(notif_subquery))
                        | (NotificationDelivery.user_device_id.in_(device_subquery))
                    )
                )
                await cleanup_session.execute(
                    delete(Notification).where(Notification.user_id.in_(self.user_ids))
                )
                await cleanup_session.execute(
                    delete(UserDevice).where(UserDevice.user_id.in_(self.user_ids))
                )
                await cleanup_session.execute(
                    delete(NotificationPreference).where(
                        NotificationPreference.user_id.in_(self.user_ids)
                    )
                )

            # 2. Clean up Matches and Reports
            if self.report_ids:
                await cleanup_session.execute(
                    delete(Match).where(
                        (Match.report_missing_id.in_(self.report_ids))
                        | (Match.report_found_id.in_(self.report_ids))
                    )
                )
                await cleanup_session.execute(
                    delete(Report).where(Report.id.in_(self.report_ids))
                )

            # 3. Clean up OutboxEvents
            target_outbox_ids = list(set(self.report_ids + self.match_ids))
            if target_outbox_ids:
                await cleanup_session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.aggregate_id.in_(target_outbox_ids)
                    )
                )
            await cleanup_session.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.event_type == EventType.MATCH_ALERT_READY.value
                )
            )

            # 4. Clean up ConsumerEvents
            if self.consumer_names:
                await cleanup_session.execute(
                    delete(ConsumerEvent).where(
                        ConsumerEvent.consumer_name.in_(self.consumer_names)
                    )
                )

            # 5. Clean up Users
            if self.user_ids:
                await cleanup_session.execute(
                    delete(User).where(User.id.in_(self.user_ids))
                )

            await cleanup_session.commit()


@pytest.fixture
async def nctx() -> AsyncGenerator[NotificationConsumerTestContext, None]:
    async with AsyncSessionLocal() as session:
        ctx = NotificationConsumerTestContext(session)
        try:
            yield ctx
        finally:
            await ctx.cleanup()


def _make_match_alert_event(
    match_id: uuid.UUID | None = None,
    report_missing_id: uuid.UUID | None = None,
    report_found_id: uuid.UUID | None = None,
    missing_owner_id: uuid.UUID | None = None,
    found_owner_id: uuid.UUID | None = None,
    source_report_id: uuid.UUID | None = None,
    source_owner_id: uuid.UUID | None = None,
    composite_score: float = 85.0,
    classification: ScoreClassification = ScoreClassification.HIGH_PRIORITY,
    alert_eligible: bool = True,
    is_update: bool = False,
    previous_score: float | None = None,
    score_delta: float | None = None,
    event_id: uuid.UUID | None = None,
) -> MatchAlertReadyEvent:
    m_id = match_id or uuid.uuid4()
    rep_m = report_missing_id or uuid.uuid4()
    rep_f = report_found_id or uuid.uuid4()
    own_m = missing_owner_id or uuid.uuid4()
    own_f = found_owner_id or uuid.uuid4()
    src_rep = source_report_id or rep_m
    src_own = source_owner_id or (own_m if src_rep == rep_m else own_f)
    now = datetime.now(UTC)

    payload = MatchAlertReadyPayload(
        match_id=m_id,
        report_missing_id=rep_m,
        report_found_id=rep_f,
        missing_owner_id=own_m,
        found_owner_id=own_f,
        source_report_id=src_rep,
        source_owner_id=src_own,
        composite_score=composite_score,
        classification=classification,
        alert_eligible=alert_eligible,
        is_update=is_update,
        previous_score=previous_score,
        score_delta=score_delta,
        evidence_summary="Strong brand and location match",
        distance_meters=150.0,
        matched_category="ELECTRONICS",
    )
    return MatchAlertReadyEvent(
        event_id=event_id or uuid.uuid4(),
        event_type=EventType.MATCH_ALERT_READY,
        event_version=1,
        occurred_at=now,
        producer="matching_worker",
        aggregate_id=m_id,
        aggregate_type=AggregateType.MATCH,
        payload=payload,
    )


# ==============================================================================
# 1. Match Alert Notification Scenarios
# ==============================================================================


@pytest.mark.asyncio
async def test_match_alert_ready_high_priority_notifies_both_owners(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies score >= 80 generates MATCH_HIGH_PRIORITY for both report owners."""
    owner_missing = await nctx.create_user(name="Missing Author")
    owner_found = await nctx.create_user(name="Found Author")
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner_missing.id,
        found_owner_id=owner_found.id,
        composite_score=85.0,
        classification=ScoreClassification.HIGH_PRIORITY,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # Query created notifications
    stmt = (
        select(Notification)
        .where(Notification.user_id.in_([owner_missing.id, owner_found.id]))
        .order_by(Notification.created_at)
    )
    res = await nctx.session.execute(stmt)
    notifications = list(res.scalars().all())

    assert len(notifications) == 2
    for notif in notifications:
        assert notif.type == NotificationType.MATCH_HIGH_PRIORITY
        assert notif.priority == NotificationPriority.HIGH
        assert "85%" in notif.title
        assert notif.data["match_id"] == str(event.payload.match_id)
        assert (
            notif.data["deep_link"] == f"boomerang://matches/{event.payload.match_id}"
        )
        min_id = min(event.payload.report_missing_id, event.payload.report_found_id)
        max_id = max(event.payload.report_missing_id, event.payload.report_found_id)
        assert notif.deduplication_key == f"match:initial:{min_id}:{max_id}"


@pytest.mark.asyncio
async def test_match_alert_ready_possible_match_notifies_source_owner_only(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies score between 75 and 80 notifies newly reporting user only."""
    owner_missing = await nctx.create_user(name="Existing Missing Author")
    owner_found = await nctx.create_user(name="New Found Author")
    rep_missing_id = uuid.uuid4()
    rep_found_id = uuid.uuid4()
    await nctx.session.commit()

    # Found report was just created and triggered matching
    event = _make_match_alert_event(
        report_missing_id=rep_missing_id,
        report_found_id=rep_found_id,
        missing_owner_id=owner_missing.id,
        found_owner_id=owner_found.id,
        source_report_id=rep_found_id,
        source_owner_id=owner_found.id,
        composite_score=77.5,
        classification=ScoreClassification.POSSIBLE_MATCH,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # Found author receives notification
    res_found = await nctx.session.execute(
        select(Notification).where(Notification.user_id == owner_found.id)
    )
    found_notifs = list(res_found.scalars().all())
    assert len(found_notifs) == 1
    assert found_notifs[0].type == NotificationType.MATCH_DETECTED
    assert found_notifs[0].priority == NotificationPriority.DEFAULT
    assert "78%" in found_notifs[0].title

    # Missing author receives zero notifications
    res_missing = await nctx.session.execute(
        select(Notification).where(Notification.user_id == owner_missing.id)
    )
    missing_notifs = list(res_missing.scalars().all())
    assert len(missing_notifs) == 0


@pytest.mark.asyncio
async def test_match_alert_ready_below_75_is_suppressed(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies score < 75 is suppressed and produces zero notifications."""
    owner = await nctx.create_user()
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner.id,
        found_owner_id=owner.id,
        composite_score=72.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == owner.id)
    )
    assert len(list(res.scalars().all())) == 0


@pytest.mark.asyncio
async def test_match_alert_ready_update_significant_improvement(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies score_delta >= 10.0 generates MATCH_UPDATED notification."""
    owner = await nctx.create_user()
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner.id,
        found_owner_id=owner.id,
        composite_score=78.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        is_update=True,
        previous_score=64.0,
        score_delta=14.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == owner.id)
    )
    notifs = list(res.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].type == NotificationType.MATCH_UPDATED
    assert "78%" in notifs[0].title
    assert f":{event.event_id}" in (notifs[0].deduplication_key or "")


@pytest.mark.asyncio
async def test_match_alert_ready_update_transitions_high_priority(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies threshold transition (< 80 to >= 80) notifies both owners."""
    owner_m = await nctx.create_user(name="Owner M")
    owner_f = await nctx.create_user(name="Owner F")
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner_m.id,
        found_owner_id=owner_f.id,
        composite_score=82.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        is_update=True,
        previous_score=76.0,
        score_delta=6.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id.in_([owner_m.id, owner_f.id]))
    )
    notifs = list(res.scalars().all())
    assert len(notifs) == 2
    for n in notifs:
        assert n.type == NotificationType.MATCH_UPDATED
        assert n.priority == NotificationPriority.HIGH


@pytest.mark.asyncio
async def test_match_alert_ready_update_micro_fluctuation_suppressed(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies score_delta < 5.0 is suppressed as a micro-fluctuation."""
    owner = await nctx.create_user()
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner.id,
        found_owner_id=owner.id,
        composite_score=77.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        is_update=True,
        previous_score=75.0,
        score_delta=2.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == owner.id)
    )
    assert len(list(res.scalars().all())) == 0


@pytest.mark.asyncio
async def test_match_alert_ready_update_cooldown_enforced(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies 4-hour cooldown per recipient on match updates."""
    owner = await nctx.create_user()
    match_id = uuid.uuid4()
    await nctx.session.commit()

    # Pre-populate a recent notification for this match 1 hour ago
    recent_notif = await create_notification(
        db=nctx.session,
        user_id=owner.id,
        type=NotificationType.MATCH_DETECTED,
        title="Recent Match",
        body="Body",
        data={"match_id": str(match_id)},
    )
    recent_notif.created_at = datetime.now(UTC) - timedelta(hours=1)
    await nctx.session.commit()

    # Rescored update arrives within the 4-hour window
    event = _make_match_alert_event(
        match_id=match_id,
        missing_owner_id=owner.id,
        found_owner_id=owner.id,
        composite_score=85.0,
        is_update=True,
        previous_score=70.0,
        score_delta=15.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # Second notification should have been suppressed by cooldown
    res = await nctx.session.execute(
        select(Notification).where(
            Notification.user_id == owner.id,
            Notification.type == NotificationType.MATCH_UPDATED,
        )
    )
    assert len(list(res.scalars().all())) == 0


# ==============================================================================
# 2. Recovery Request Lifecycle Scenarios
# ==============================================================================


@pytest.mark.asyncio
async def test_recovery_request_created_notification(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies recipient receives request alert with zero secret leaks."""
    requester = await nctx.create_user(name="Claimant")
    recipient = await nctx.create_user(name="Finder")
    report = await nctx.create_report(user_id=recipient.id)
    req_id = uuid.uuid4()
    await nctx.session.commit()

    event = RecoveryRequestCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_CREATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="recovery_service",
        aggregate_id=req_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=RecoveryRequestCreatedPayload(
            recovery_request_id=req_id,
            report_id=report.id,
            requester_id=requester.id,
            recipient_id=recipient.id,
            status=RecoveryRequestStatus.PENDING,
            created_at=datetime.now(UTC),
        ),
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == recipient.id)
    )
    notifs = list(res.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].type == NotificationType.RECOVERY_REQUEST_RECEIVED
    assert notifs[0].priority == NotificationPriority.HIGH
    assert notifs[0].deduplication_key == f"recovery_request:created:{req_id}"
    assert "verification_response" not in notifs[0].data


@pytest.mark.asyncio
async def test_recovery_request_updated_routing(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies ACCEPTED/REJECTED routes to requester, and COMPLETED routes to both."""
    requester = await nctx.create_user(name="Requester")
    recipient = await nctx.create_user(name="Recipient")
    report = await nctx.create_report(user_id=recipient.id)
    await nctx.session.commit()

    handler = NotificationEventHandler()

    # Case A: ACCEPTED -> requester
    req_a_id = uuid.uuid4()
    event_accepted = RecoveryRequestUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_UPDATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="recovery_service",
        aggregate_id=req_a_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=RecoveryRequestUpdatedPayload(
            recovery_request_id=req_a_id,
            report_id=report.id,
            requester_id=requester.id,
            recipient_id=recipient.id,
            previous_status=RecoveryRequestStatus.PENDING,
            new_status=RecoveryRequestStatus.ACCEPTED,
            updated_at=datetime.now(UTC),
        ),
    )
    await handler.handle(event_accepted, nctx.session)
    await nctx.session.commit()

    res_a = await nctx.session.execute(
        select(Notification).where(
            Notification.user_id == requester.id,
            Notification.type == NotificationType.RECOVERY_REQUEST_ACCEPTED,
        )
    )
    assert len(list(res_a.scalars().all())) == 1

    # Case B: REJECTED -> requester
    req_b_id = uuid.uuid4()
    event_rejected = RecoveryRequestUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_UPDATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="recovery_service",
        aggregate_id=req_b_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=RecoveryRequestUpdatedPayload(
            recovery_request_id=req_b_id,
            report_id=report.id,
            requester_id=requester.id,
            recipient_id=recipient.id,
            previous_status=RecoveryRequestStatus.PENDING,
            new_status=RecoveryRequestStatus.REJECTED,
            updated_at=datetime.now(UTC),
        ),
    )
    await handler.handle(event_rejected, nctx.session)
    await nctx.session.commit()

    res_b = await nctx.session.execute(
        select(Notification).where(
            Notification.user_id == requester.id,
            Notification.type == NotificationType.RECOVERY_REQUEST_REJECTED,
        )
    )
    assert len(list(res_b.scalars().all())) == 1

    # Case C: COMPLETED -> both requester and recipient
    req_c_id = uuid.uuid4()
    event_completed = RecoveryRequestUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_UPDATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="recovery_service",
        aggregate_id=req_c_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=RecoveryRequestUpdatedPayload(
            recovery_request_id=req_c_id,
            report_id=report.id,
            requester_id=requester.id,
            recipient_id=recipient.id,
            previous_status=RecoveryRequestStatus.ACCEPTED,
            new_status=RecoveryRequestStatus.COMPLETED,
            updated_at=datetime.now(UTC),
        ),
    )
    await handler.handle(event_completed, nctx.session)
    await nctx.session.commit()

    res_c = await nctx.session.execute(
        select(Notification).where(
            Notification.type == NotificationType.RECOVERY_REQUEST_COMPLETED,
            Notification.data["recovery_request_id"].astext == str(req_c_id),
        )
    )
    notifs_c = list(res_c.scalars().all())
    assert len(notifs_c) == 2
    uids = {n.user_id for n in notifs_c}
    assert uids == {requester.id, recipient.id}


# ==============================================================================
# 3. Report Lifecycle Scenarios
# ==============================================================================


@pytest.mark.asyncio
async def test_report_resolved_notification(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies report author receives REPORT_STATUS_CHANGED upon resolution."""
    author = await nctx.create_user(name="Report Author")
    report = await nctx.create_report(user_id=author.id)
    await nctx.session.commit()

    event = ReportResolvedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_RESOLVED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="report_service",
        aggregate_id=report.id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportResolvedPayload(
            report_id=report.id,
            resolved_at=datetime.now(UTC),
        ),
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == author.id)
    )
    notifs = list(res.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].type == NotificationType.REPORT_STATUS_CHANGED
    assert notifs[0].data["status"] == "RESOLVED"
    assert notifs[0].deduplication_key == f"report:status:RESOLVED:{report.id}"


@pytest.mark.asyncio
async def test_report_updated_meaningful_status_transition_vs_routine_edit(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies meaningful report updates notify author while routine edits do not."""
    author = await nctx.create_user(name="Report Author")
    report = await nctx.create_report(user_id=author.id)
    await nctx.session.commit()

    handler = NotificationEventHandler()

    # 1. Routine description edit with ACTIVE status (should be ignored)
    routine_event = ReportUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_UPDATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="report_service",
        aggregate_id=report.id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportUpdatedPayload(
            report_id=report.id,
            updated_fields=["description"],
            description="Minor edit to item description",
            status=ReportStatus.ACTIVE,
            updated_at=datetime.now(UTC),
        ),
    )
    await handler.handle(routine_event, nctx.session)
    await nctx.session.commit()

    res_routine = await nctx.session.execute(
        select(Notification).where(Notification.user_id == author.id)
    )
    assert len(list(res_routine.scalars().all())) == 0

    # 2. Meaningful status update to CANCELLED
    cancelled_event = ReportUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_UPDATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="report_service",
        aggregate_id=report.id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportUpdatedPayload(
            report_id=report.id,
            updated_fields=["status"],
            status=ReportStatus.CANCELLED,
            updated_at=datetime.now(UTC),
        ),
    )
    await handler.handle(cancelled_event, nctx.session)
    await nctx.session.commit()

    res_cancelled = await nctx.session.execute(
        select(Notification).where(Notification.user_id == author.id)
    )
    notifs_cancelled = list(res_cancelled.scalars().all())
    assert len(notifs_cancelled) == 1
    assert notifs_cancelled[0].data["status"] == "CANCELLED"
    assert (
        notifs_cancelled[0].deduplication_key == f"report:status:CANCELLED:{report.id}"
    )


# ==============================================================================
# 4. User Preferences & Quiet Hours
# ==============================================================================


@pytest.mark.asyncio
async def test_preference_filters_suppress_matching_alerts(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies match notification preference filters suppress match alerts."""
    user = await nctx.create_user()
    await nctx.session.commit()

    handler = NotificationEventHandler()

    # A. match_alerts_enabled = False
    await update_preferences(nctx.session, user.id, match_alerts_enabled=False)
    await nctx.session.commit()

    event_a = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=95.0,
    )
    await handler.handle(event_a, nctx.session)
    await nctx.session.commit()

    res_a = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    assert len(list(res_a.scalars().all())) == 0

    # B. match_min_score = 90.0
    await update_preferences(
        nctx.session, user.id, match_alerts_enabled=True, match_min_score=90.0
    )
    await nctx.session.commit()

    event_b = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=85.0,
    )
    await handler.handle(event_b, nctx.session)
    await nctx.session.commit()

    res_b = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    assert len(list(res_b.scalars().all())) == 0

    # C. match_high_priority_only = True
    await update_preferences(
        nctx.session,
        user.id,
        match_min_score=75.0,
        match_high_priority_only=True,
    )
    await nctx.session.commit()

    event_c = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=78.0,
    )
    await handler.handle(event_c, nctx.session)
    await nctx.session.commit()

    res_c = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    assert len(list(res_c.scalars().all())) == 0


@pytest.mark.asyncio
async def test_preference_in_app_and_push_channels_and_quiet_hours(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies channel disabling and quiet-hours buffering on NotificationDelivery."""
    user = await nctx.create_user()
    await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="device-quiet-test",
        fcm_token="token-quiet-xyz",
        platform=DevicePlatform.ANDROID,
    )
    # Enable quiet hours: 22:00 to 07:00
    await update_preferences(
        db=nctx.session,
        user_id=user.id,
        quiet_hours_enabled=True,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(7, 0),
    )
    await nctx.session.commit()

    handler = NotificationEventHandler()
    event = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=88.0,
    )

    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # Check notification created
    notif_res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    notif = notif_res.scalar_one()

    # Check delivery task created
    deliv_res = await nctx.session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id
        )
    )
    deliveries = list(deliv_res.scalars().all())
    assert len(deliveries) == 1
    assert deliveries[0].status == DeliveryStatus.PENDING

    # Test compute_next_delivery_time directly
    pref_res = await nctx.session.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    pref = pref_res.scalar_one()

    # During overnight quiet hours (e.g., 23:30)
    during_quiet = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)
    buffered = compute_next_delivery_time(pref, during_quiet)
    assert buffered > during_quiet
    assert buffered.hour == 7
    assert buffered.minute == 0
    assert buffered.day == 3  # next day morning

    # Outside quiet hours (e.g., 14:00)
    outside_quiet = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)
    immediate = compute_next_delivery_time(pref, outside_quiet)
    assert immediate == outside_quiet


# ==============================================================================
# 5. Idempotency Barrier, Unrelated Events & Transactional Integrity
# ==============================================================================


@pytest.mark.asyncio
async def test_duplicate_event_delivery_skipped_by_idempotency_barrier(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies consumer skips duplicate delivery without duplicate notifications."""
    owner = await nctx.create_user()
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=owner.id,
        found_owner_id=owner.id,
        composite_score=86.0,
    )
    event_bytes = event.model_dump_json().encode("utf-8")
    record = _create_mock_consumer_record(event_bytes, offset=501)

    mock_kafka = AsyncMock()
    consumer_name = f"test_notification_{uuid.uuid4().hex[:8]}"
    nctx.consumer_names.append(consumer_name)

    consumer = create_notification_consumer(
        consumer_name=consumer_name,
        session_factory=AsyncSessionLocal,
        consumer=mock_kafka,
    )

    # 1. First delivery: successfully processes event
    res1 = await consumer.process_record(record)
    assert res1 == ConsumerProcessingResult.SUCCESS

    async with AsyncSessionLocal() as session:
        notif_cnt = len(
            list(
                (
                    await session.execute(
                        select(Notification).where(Notification.user_id == owner.id)
                    )
                )
                .scalars()
                .all()
            )
        )
        assert notif_cnt == 1

        ce_stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        ce = (await session.execute(ce_stmt)).scalar_one()
        assert ce.status == ConsumerEventStatus.COMPLETED

    # 2. Second delivery (same offset/id): idempotency barrier skips handlers
    res2 = await consumer.process_record(record)
    assert res2 == ConsumerProcessingResult.DUPLICATE_SKIPPED

    async with AsyncSessionLocal() as session:
        notif_cnt_after = len(
            list(
                (
                    await session.execute(
                        select(Notification).where(Notification.user_id == owner.id)
                    )
                )
                .scalars()
                .all()
            )
        )
        assert notif_cnt_after == 1  # No duplicate notification


@pytest.mark.asyncio
async def test_unrelated_domain_event_safely_ignored(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies unrelated events (e.g. report.created) are recorded as IGNORED."""
    mock_kafka = AsyncMock()
    consumer_name = f"test_notification_{uuid.uuid4().hex[:8]}"
    nctx.consumer_names.append(consumer_name)

    rep_id = uuid.uuid4()
    now = datetime.now(UTC)
    rep_event = ReportCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer="report_service",
        aggregate_id=rep_id,
        aggregate_type=AggregateType.REPORT,
        payload=ReportCreatedPayload(
            report_id=rep_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.ELECTRONICS,
            title="Ignored Laptop",
            description="Ignored for notification consumer",
            latitude=37.7749,
            longitude=-122.4194,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        ),
    )
    record = _create_mock_consumer_record(
        rep_event.model_dump_json().encode("utf-8"), offset=601
    )

    consumer = create_notification_consumer(
        consumer_name=consumer_name,
        session_factory=AsyncSessionLocal,
        consumer=mock_kafka,
    )

    res = await consumer.process_record(record)
    assert res == ConsumerProcessingResult.IGNORED

    async with AsyncSessionLocal() as session:
        ce_stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == rep_event.event_id,
        )
        ce = (await session.execute(ce_stmt)).scalar_one()
        assert ce.status == ConsumerEventStatus.COMPLETED


# ==============================================================================
# 6. Transactional Outbox Integration in MatchPersistenceService
# ==============================================================================


@pytest.mark.asyncio
async def test_outbox_event_emitted_during_match_persistence(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies record_matches emits 'match.alert_ready' OutboxEvent for score >= 75."""
    user_m = await nctx.create_user(name="User M")
    user_f = await nctx.create_user(name="User F")
    rep_m = await nctx.create_report(user_id=user_m.id, report_type=ReportType.MISSING)
    rep_f = await nctx.create_report(user_id=user_f.id, report_type=ReportType.FOUND)
    await nctx.session.commit()

    service = MatchPersistenceService()

    # 1. Score >= 75 and alert_eligible = True -> OutboxEvent emitted
    score_res = MatchScoreResult(
        source_id=rep_m.id,
        candidate_id=rep_f.id,
        identity=IdentityBreakdown(
            score=82.0,
            category_score=40.0,
            brand_model_score=40.0,
            title_noun_score=2.0,
            matched_category="ELECTRONICS",
        ),
        characteristics=CharacteristicsBreakdown(score=82.0),
        distance=DistanceBreakdown(score=82.0, distance_meters=200.0, distance_km=0.2),
        time=TimeBreakdown(
            score=82.0,
            loss_time=datetime.now(UTC),
            found_time=datetime.now(UTC),
            delta_hours=1.0,
        ),
        raw_composite_score=82.0,
        contradiction_penalty=0.0,
        composite_score=82.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        minimum_evidence_satisfied=True,
        evidence_summary="Test match persistence outbox emission",
    )

    await service.record_matches(
        source_report=rep_m,
        results=[score_res],
        session=nctx.session,
    )
    await nctx.session.commit()

    # Verify OutboxEvent exists
    outbox_stmt = select(OutboxEvent).where(
        OutboxEvent.event_type == EventType.MATCH_ALERT_READY.value,
    )
    outbox_res = await nctx.session.execute(outbox_stmt)
    outbox_events = list(outbox_res.scalars().all())

    # Filter by report IDs
    match_outbox = [
        oe
        for oe in outbox_events
        if oe.payload.get("payload", {}).get("report_missing_id") == str(rep_m.id)
    ]
    assert len(match_outbox) == 1
    inner_payload = match_outbox[0].payload["payload"]
    assert inner_payload["composite_score"] == 82.0
    assert inner_payload["classification"] == "HIGH_PRIORITY"
    assert inner_payload["missing_owner_id"] == str(user_m.id)
    assert inner_payload["found_owner_id"] == str(user_f.id)


@pytest.mark.asyncio
async def test_preference_in_app_disabled_skips_in_app_notification(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies in_app_enabled=False skips Notification creation."""
    user = await nctx.create_user()
    await update_preferences(nctx.session, user.id, in_app_enabled=False)
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=88.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    assert len(list(res.scalars().all())) == 0


@pytest.mark.asyncio
async def test_preference_push_disabled_creates_in_app_only(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies push_enabled=False creates in-app notification but no delivery tasks."""
    user = await nctx.create_user()
    await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="device-push-off",
        fcm_token="token-push-off",
        platform=DevicePlatform.IOS,
    )
    await update_preferences(
        db=nctx.session,
        user_id=user.id,
        in_app_enabled=True,
        push_enabled=False,
    )
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=85.0,
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # In-app notification created
    notif_res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    notifs = list(notif_res.scalars().all())
    assert len(notifs) == 1

    # Zero push delivery tasks created
    deliv_res = await nctx.session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notifs[0].id
        )
    )
    deliveries = list(deliv_res.scalars().all())
    assert len(deliveries) == 0


@pytest.mark.asyncio
async def test_transaction_rollback_consistency_on_handler_failure(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies atomic rollback ensures no orphaned records remain upon failure."""
    user = await nctx.create_user()
    await nctx.session.commit()

    event = _make_match_alert_event(
        missing_owner_id=user.id,
        found_owner_id=user.id,
        composite_score=90.0,
    )
    event_bytes = event.model_dump_json().encode("utf-8")
    record = _create_mock_consumer_record(event_bytes, offset=701)

    mock_kafka = AsyncMock()
    consumer_name = f"test_rollback_{uuid.uuid4().hex[:8]}"
    nctx.consumer_names.append(consumer_name)

    base_handler = NotificationEventHandler()

    class FailingHandler:
        @property
        def event_types(self) -> list[EventType]:
            return [EventType.MATCH_ALERT_READY]

        async def handle(self, evt: BoomerangEvent, session: AsyncSession) -> None:
            await base_handler.handle(evt, session)
            raise RuntimeError("Simulated crash inside handler transaction")

    from app.services.event_consumer import HandlerRegistry

    registry = HandlerRegistry()
    registry.register(FailingHandler())

    consumer = EventConsumer(
        consumer_name=consumer_name,
        group_id=NOTIFICATION_CONSUMER_GROUP,
        topics=["boomerang.domain.events"],
        registry=registry,
        session_factory=AsyncSessionLocal,
        consumer=mock_kafka,
        max_retries=1,
    )

    res = await consumer.process_record(record)
    assert res == ConsumerProcessingResult.QUARANTINED

    # Verify no Notification rows committed
    async with AsyncSessionLocal() as session:
        notif_res = await session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        assert len(list(notif_res.scalars().all())) == 0

        # ConsumerEvent is marked QUARANTINED
        ce_stmt = select(ConsumerEvent).where(
            ConsumerEvent.consumer_name == consumer_name,
            ConsumerEvent.event_id == event.event_id,
        )
        ce = (await session.execute(ce_stmt)).scalar_one()
        assert ce.status == ConsumerEventStatus.QUARANTINED


@pytest.mark.asyncio
async def test_mandatory_recovery_request_not_suppressed_by_in_app_disabled(
    nctx: NotificationConsumerTestContext,
) -> None:
    """Verifies mandatory claim alert created even when in_app_enabled=False."""
    requester = await nctx.create_user(name="Claimant User")
    recipient = await nctx.create_user(name="Finder User")
    report = await nctx.create_report(user_id=recipient.id)
    await register_device(
        db=nctx.session,
        user_id=recipient.id,
        device_id="device-mandatory-claim",
        fcm_token="token-claim-xyz",
        platform=DevicePlatform.ANDROID,
    )
    # User opts out of optional in-app notifications
    await update_preferences(
        db=nctx.session,
        user_id=recipient.id,
        in_app_enabled=False,
        push_enabled=True,
    )
    await nctx.session.commit()

    req_id = uuid.uuid4()
    event = RecoveryRequestCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_CREATED,
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="recovery_service",
        aggregate_id=req_id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        payload=RecoveryRequestCreatedPayload(
            recovery_request_id=req_id,
            report_id=report.id,
            requester_id=requester.id,
            recipient_id=recipient.id,
            status=RecoveryRequestStatus.PENDING,
            created_at=datetime.now(UTC),
        ),
    )

    handler = NotificationEventHandler()
    await handler.handle(event, nctx.session)
    await nctx.session.commit()

    # Mandatory in-app notification MUST be created
    notif_res = await nctx.session.execute(
        select(Notification).where(Notification.user_id == recipient.id)
    )
    notifs = list(notif_res.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].type == NotificationType.RECOVERY_REQUEST_RECEIVED

    # Push delivery task MUST also be created for the active device
    deliv_res = await nctx.session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notifs[0].id
        )
    )
    deliveries = list(deliv_res.scalars().all())
    assert len(deliveries) == 1
    assert deliveries[0].status == DeliveryStatus.PENDING
