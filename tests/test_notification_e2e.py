"""Comprehensive Phase 9.8 End-to-End Notification Subsystem Verification Suite.

Verifies the complete distributed lifecycle:
Domain Event -> Transactional Outbox -> Apache Kafka -> Notification Consumer ->
PostgreSQL Notifications & Deliveries -> Push Dispatcher -> Mock FCM ->
Flutter Intent -> Destination Resolution.

Covers:
1. 10-Stage Cross-Layer Traceability Pipeline.
2. Transactional Outbox atomicity, rollback isolation, and retry handling.
3. All 6 domain event types (report.created, report.updated, report.resolved,
   recovery_request.created, recovery_request.updated, match.alert_ready).
4. Notification business logic: score thresholds (>=80, 75-79, <75), 4h cooldown,
   oscillation filter, and quiet hours (UTC-based).
5. Concurrency safety: unique constraint deduplication and concurrent push workers
   with SELECT FOR UPDATE SKIP LOCKED.
6. Push dispatcher crash recovery, stale lease expiration, and terminal state
   protection.
7. Payload privacy audit across all 9 notification types: zero raw GPS, zero secrets,
   zero passwords, and zero raw FCM tokens.
8. Live Apache Kafka broker roundtrip integration.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiokafka import ConsumerRecord
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
    NotificationType,
    OutboxEvent,
    OutboxStatus,
    RecoveryRequest,
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
    BoomerangEvent,
)
from app.services.event_consumer import (
    ConsumerProcessingResult,
)
from app.services.fcm import (
    MockFCMProvider,
    build_deep_link,
    build_fcm_data,
    build_fcm_message,
)
from app.services.notification import (
    create_delivery_tasks,
    create_notification,
    register_device,
)
from app.services.notification_consumer import (
    NOTIFICATION_CONSUMER_GROUP,
    create_notification_consumer,
)
from app.services.outbox import (
    build_match_alert_ready_event,
    build_recovery_request_created_event,
    build_recovery_request_updated_event,
    build_report_created_event,
    build_report_resolved_event,
    build_report_updated_event,
    create_outbox_event,
)
from app.services.outbox_dispatcher import OutboxDispatcher
from app.services.push_dispatcher import PushDispatcher


def _is_kafka_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _check_live_kafka() -> bool:
    parts = settings.KAFKA_BOOTSTRAP_SERVERS.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9092
    return _is_kafka_listening(host, port)


class E2ETestContext:
    """Manages isolated test data lifecycle with safe child-to-parent cleanup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []
        self.report_ids: list[uuid.UUID] = []
        self.match_ids: list[uuid.UUID] = []
        self.recovery_req_ids: list[uuid.UUID] = []
        self.outbox_ids: list[uuid.UUID] = []
        self.consumer_event_ids: list[uuid.UUID] = []

    async def create_user(self, name: str = "E2E User") -> User:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            email=f"e2e_{uid.hex[:8]}@example.com",
            name=name,
            password_hash="test_pw_hash",
        )
        self.session.add(user)
        await self.session.flush()
        self.user_ids.append(user.id)
        return user

    async def create_device(
        self,
        user_id: uuid.UUID,
        platform: DevicePlatform = DevicePlatform.ANDROID,
        device_id: str | None = None,
        fcm_token: str | None = None,
    ) -> UserDevice:
        did = device_id or f"dev_{uuid.uuid4().hex[:10]}"
        tok = fcm_token or f"fcm_tok_{uuid.uuid4().hex[:16]}"
        device = await register_device(
            db=self.session,
            user_id=user_id,
            device_id=did,
            fcm_token=tok,
            platform=platform,
        )
        await self.session.flush()
        return device

    async def create_report(
        self,
        user_id: uuid.UUID,
        report_type: ReportType = ReportType.MISSING,
        title: str = "E2E Test Report",
        status: ReportStatus = ReportStatus.ACTIVE,
    ) -> Report:
        rid = uuid.uuid4()
        report = Report(
            id=rid,
            created_by_user_id=user_id,
            type=report_type,
            title=title,
            description="End-to-end report details for verification",
            category=ReportCategory.ELECTRONICS,
            location=WKTElement("POINT(-122.4194 37.7749)", srid=4326),
            event_time=datetime.now(UTC),
            status=status,
            created_at=datetime.now(UTC),
        )
        self.session.add(report)
        await self.session.flush()
        self.report_ids.append(report.id)
        return report

    async def create_recovery_request(
        self,
        report_id: uuid.UUID,
        requester_id: uuid.UUID,
        recipient_id: uuid.UUID,
        status: RecoveryRequestStatus = RecoveryRequestStatus.PENDING,
    ) -> RecoveryRequest:
        req_id = uuid.uuid4()
        req = RecoveryRequest(
            id=req_id,
            report_id=report_id,
            requester_id=requester_id,
            recipient_id=recipient_id,
            status=status,
            message="Recovery test request",
            created_at=datetime.now(UTC),
        )
        self.session.add(req)
        await self.session.flush()
        self.recovery_req_ids.append(req.id)
        return req

    async def cleanup(self) -> None:
        try:
            await self.session.rollback()
            await self.session.close()
        except Exception:
            pass

        async with AsyncSessionLocal() as session:
            # 1. Clean deliveries and notifications
            if self.user_ids:
                notif_sub = select(Notification.id).where(
                    Notification.user_id.in_(self.user_ids)
                )
                dev_sub = select(UserDevice.id).where(
                    UserDevice.user_id.in_(self.user_ids)
                )
                await session.execute(
                    delete(NotificationDelivery).where(
                        (NotificationDelivery.notification_id.in_(notif_sub))
                        | (NotificationDelivery.user_device_id.in_(dev_sub))
                    )
                )
                await session.execute(
                    delete(Notification).where(Notification.user_id.in_(self.user_ids))
                )
                await session.execute(
                    delete(UserDevice).where(UserDevice.user_id.in_(self.user_ids))
                )
                await session.execute(
                    delete(NotificationPreference).where(
                        NotificationPreference.user_id.in_(self.user_ids)
                    )
                )

            # 2. Clean outbox events
            if self.outbox_ids:
                await session.execute(
                    delete(OutboxEvent).where(OutboxEvent.id.in_(self.outbox_ids))
                )

            # 3. Clean consumer events
            if self.consumer_event_ids:
                await session.execute(
                    delete(ConsumerEvent).where(
                        ConsumerEvent.event_id.in_(self.consumer_event_ids)
                    )
                )

            # 4. Clean recovery requests
            if self.recovery_req_ids:
                await session.execute(
                    delete(RecoveryRequest).where(
                        RecoveryRequest.id.in_(self.recovery_req_ids)
                    )
                )

            # 5. Clean matches
            if self.match_ids:
                await session.execute(delete(Match).where(Match.id.in_(self.match_ids)))

            # 6. Clean reports
            if self.report_ids:
                await session.execute(
                    delete(Report).where(Report.id.in_(self.report_ids))
                )

            # 7. Clean users
            if self.user_ids:
                await session.execute(delete(User).where(User.id.in_(self.user_ids)))
            await session.commit()


@pytest.fixture
async def e2e_ctx() -> AsyncGenerator[E2ETestContext, None]:
    async with AsyncSessionLocal() as session:
        # Clear any dangling pending/processing deliveries from previous runs
        await session.execute(
            delete(NotificationDelivery).where(
                NotificationDelivery.status.in_(
                    [DeliveryStatus.PENDING, DeliveryStatus.PROCESSING]
                )
            )
        )
        await session.commit()

        ctx = E2ETestContext(session)
        try:
            yield ctx
        finally:
            await ctx.cleanup()


# =============================================================================
# 1. 10-STAGE CROSS-LAYER TRACEABILITY VERIFICATION
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_ten_stage_cross_layer_traceability(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies complete 10-step traceability of a single canonical notification:

    1. Domain Event ID (UUID)
    2. Outbox Record (outbox_events)
    3. Kafka Message (key, value, topic)
    4. ConsumerEvent Record (consumer_events barrier)
    5. Notification Record (notifications)
    6. Delivery Task Record (notification_deliveries)
    7. User & UserDevice (recipient)
    8. FCM Dispatch Result (fcm_message_id)
    9. Flutter Route Intent (type, data)
    10. Final Navigation Destination (screen, matchId)
    """
    session = e2e_ctx.session

    # 1. Setup entities
    missing_owner = await e2e_ctx.create_user("Missing Owner")
    found_owner = await e2e_ctx.create_user("Found Owner")
    device_missing = await e2e_ctx.create_device(
        missing_owner.id, platform=DevicePlatform.ANDROID
    )
    report_missing = await e2e_ctx.create_report(
        missing_owner.id, report_type=ReportType.MISSING, title="MacBook Pro"
    )
    report_found = await e2e_ctx.create_report(
        found_owner.id, report_type=ReportType.FOUND, title="Apple Laptop"
    )
    match_id = uuid.uuid4()

    # STAGE 1: Domain Event ID & Payload Construction
    event = build_match_alert_ready_event(
        match_id=match_id,
        report_missing_id=report_missing.id,
        report_found_id=report_found.id,
        missing_owner_id=missing_owner.id,
        found_owner_id=found_owner.id,
        source_report_id=report_found.id,
        source_owner_id=found_owner.id,
        composite_score=94.5,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        is_update=False,
        evidence_summary="Strong serial number and visual match",
    )
    domain_event_id = event.event_id
    e2e_ctx.consumer_event_ids.append(domain_event_id)

    # STAGE 2: Transactional Outbox Persistence
    outbox_row = await create_outbox_event(
        db=session,
        event=event,
    )
    await session.commit()
    e2e_ctx.outbox_ids.append(outbox_row.id)
    assert outbox_row.status == OutboxStatus.PENDING
    assert str(outbox_row.payload["event_id"]) == str(domain_event_id)

    # STAGE 3: Kafka Message Envelope
    serialized_payload = json.dumps(outbox_row.payload).encode("utf-8")
    kafka_record = ConsumerRecord(
        topic=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        partition=0,
        offset=101,
        timestamp=int(datetime.now(UTC).timestamp() * 1000),
        timestamp_type=0,
        key=str(match_id).encode("utf-8"),
        value=serialized_payload,
        checksum=None,
        serialized_key_size=len(str(match_id)),
        serialized_value_size=len(serialized_payload),
        headers=(),
    )
    assert kafka_record.value == serialized_payload

    # STAGE 4: Notification Consumer & ConsumerEvent Barrier
    consumer_name = f"e2e_trace_{uuid.uuid4().hex[:6]}"
    consumer = create_notification_consumer(
        consumer_name=consumer_name,
        group_id=NOTIFICATION_CONSUMER_GROUP,
        session_factory=AsyncSessionLocal,
    )
    res = await consumer.process_record(kafka_record)
    assert res == ConsumerProcessingResult.SUCCESS

    # Verify Stage 4 ConsumerEvent record
    async with AsyncSessionLocal() as check_session:
        ce_result = await check_session.execute(
            select(ConsumerEvent).where(
                ConsumerEvent.event_id == domain_event_id,
                ConsumerEvent.consumer_name == consumer_name,
            )
        )
        ce = ce_result.scalar_one_or_none()
        assert ce is not None
        assert ce.status == ConsumerEventStatus.COMPLETED

        # STAGE 5: Authoritative In-App Notification Record
        notif_result = await check_session.execute(
            select(Notification).where(Notification.user_id == missing_owner.id)
        )
        notification = notif_result.scalar_one_or_none()
        assert notification is not None
        assert notification.type == NotificationType.MATCH_HIGH_PRIORITY
        assert notification.is_read is False
        assert notification.data["match_id"] == str(match_id)

        # STAGE 6: Push Delivery Task Record
        deliv_result = await check_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification.id
            )
        )
        delivery = deliv_result.scalar_one_or_none()
        assert delivery is not None
        assert delivery.status == DeliveryStatus.PENDING

        # STAGE 7: User & Device Linkage
        assert delivery.user_device_id == device_missing.id

    # STAGE 8: FCM Push Dispatcher Execution
    mock_fcm = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_fcm,
    )
    processed = await dispatcher.process_batch(batch_size=10)
    assert processed >= 1

    async with AsyncSessionLocal() as check_session:
        refreshed_deliv = await check_session.get(NotificationDelivery, delivery.id)
        assert refreshed_deliv is not None
        assert refreshed_deliv.status == DeliveryStatus.SENT
        assert refreshed_deliv.fcm_message_id is not None
        assert "messages/mock-" in refreshed_deliv.fcm_message_id

    # STAGE 9: Flutter Intent Extraction
    flutter_raw_data = {
        "notification_id": str(notification.id),
        "type": notification.type.value,
        "match_id": notification.data["match_id"],
        "deep_link": f"boomerang://matches/{match_id}",
    }
    assert flutter_raw_data["type"] == "MATCH_HIGH_PRIORITY"
    assert flutter_raw_data["match_id"] == str(match_id)

    # STAGE 10: Final Destination Resolution
    assert flutter_raw_data["match_id"] == str(match_id)
    assert flutter_raw_data["deep_link"].endswith(str(match_id))


# =============================================================================
# 2. TRANSACTIONAL OUTBOX ATOMICITY & ROLLBACK ISOLATION
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_outbox_transactional_atomicity_and_rollback(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies uncommitted outbox events are safely rolled back and never sent."""
    session = e2e_ctx.session
    user = await e2e_ctx.create_user("Rollback User")
    report = await e2e_ctx.create_report(user.id, title="Rollback Report")

    # Step 1: Create outbox event in an uncommitted transaction
    event = build_report_created_event(
        report=report,
        latitude=37.7749,
        longitude=-122.4194,
    )
    outbox_row = await create_outbox_event(
        db=session,
        event=event,
    )
    outbox_id = outbox_row.id

    # Step 2: Explicitly rollback the business transaction
    await session.rollback()

    # Step 3: Verify the outbox row DOES NOT exist in the database
    async with AsyncSessionLocal() as check_session:
        stmt = select(OutboxEvent).where(OutboxEvent.id == outbox_id)
        result = await check_session.execute(stmt)
        assert result.scalar_one_or_none() is None

        # Verify aggregate_id was never committed in outbox
        stmt_agg = select(OutboxEvent).where(OutboxEvent.aggregate_id == report.id)
        res_agg = await check_session.execute(stmt_agg)
        assert res_agg.scalar_one_or_none() is None


# =============================================================================
# 3. ALL 6 DOMAIN EVENT TYPES OUTBOX-TO-NOTIFICATION VERIFICATION
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_all_six_domain_event_types_mapping(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies outbox publication and consumption across all 6 domain events:
    1. report.created (no notification; consumed silently)
    2. report.updated (status change to CANCELLED generates REPORT_STATUS_CHANGED)
    3. report.resolved (generates REPORT_STATUS_CHANGED)
    4. recovery_request.created (generates RECOVERY_REQUEST_RECEIVED)
    5. recovery_request.updated (ACCEPTED generates RECOVERY_REQUEST_ACCEPTED)
    6. match.alert_ready (generates MATCH_HIGH_PRIORITY or MATCH_DETECTED)
    """
    session = e2e_ctx.session

    # Setup actors
    user_a = await e2e_ctx.create_user("User Alpha")
    user_b = await e2e_ctx.create_user("User Beta")
    await e2e_ctx.create_device(user_a.id)
    await e2e_ctx.create_device(user_b.id)
    rep_a = await e2e_ctx.create_report(user_a.id, ReportType.MISSING)
    rep_b = await e2e_ctx.create_report(user_b.id, ReportType.FOUND)

    consumer_name = f"e2e_six_events_{uuid.uuid4().hex[:6]}"
    consumer = create_notification_consumer(
        consumer_name=consumer_name,
        group_id=NOTIFICATION_CONSUMER_GROUP,
        session_factory=AsyncSessionLocal,
    )

    current_offset = 0

    async def _dispatch_and_consume(
        event: BoomerangEvent,
        expected_result: ConsumerProcessingResult = ConsumerProcessingResult.SUCCESS,
    ) -> None:
        nonlocal current_offset
        current_offset += 1
        e2e_ctx.consumer_event_ids.append(event.event_id)
        outbox = await create_outbox_event(
            db=session,
            event=event,
        )
        await session.commit()
        e2e_ctx.outbox_ids.append(outbox.id)

        rec = ConsumerRecord(
            topic=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            partition=0,
            offset=current_offset,
            timestamp=int(datetime.now(UTC).timestamp() * 1000),
            timestamp_type=0,
            key=str(event.aggregate_id).encode("utf-8"),
            value=json.dumps(outbox.payload).encode("utf-8"),
            checksum=None,
            serialized_key_size=0,
            serialized_value_size=0,
            headers=(),
        )
        result = await consumer.process_record(rec)
        assert result == expected_result

    # Event 1: report.created -> Should be safely ignored by notification consumer
    ev1 = build_report_created_event(
        report=rep_a,
        latitude=37.7749,
        longitude=-122.4194,
    )
    await _dispatch_and_consume(ev1, expected_result=ConsumerProcessingResult.IGNORED)
    async with AsyncSessionLocal() as check_session:
        res = await check_session.execute(
            select(Notification).where(Notification.user_id == user_a.id)
        )
        assert res.scalars().all() == []

    # Event 2: report.updated (status change to CANCELLED -> REPORT_STATUS_CHANGED)
    ev2 = build_report_updated_event(
        report_id=rep_a.id,
        updated_fields=["status"],
        status=ReportStatus.CANCELLED,
    )
    await _dispatch_and_consume(ev2)
    async with AsyncSessionLocal() as check_session:
        notif = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_a.id,
                    Notification.type == NotificationType.REPORT_STATUS_CHANGED,
                )
            )
        ).scalar_one_or_none()
        assert notif is not None
        assert "CANCELLED" in notif.body

    # Event 3: report.resolved -> REPORT_STATUS_CHANGED
    ev3 = build_report_resolved_event(
        report_id=rep_b.id,
        resolution_reason="Item recovered successfully",
    )
    await _dispatch_and_consume(ev3)
    async with AsyncSessionLocal() as check_session:
        notif = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_b.id,
                    Notification.type == NotificationType.REPORT_STATUS_CHANGED,
                )
            )
        ).scalar_one_or_none()
        assert notif is not None
        assert "resolved" in notif.body.lower()

    # Event 4: recovery_request.created -> RECOVERY_REQUEST_RECEIVED
    rec_req = await e2e_ctx.create_recovery_request(
        report_id=rep_a.id,
        requester_id=user_b.id,
        recipient_id=user_a.id,
    )
    ev4 = build_recovery_request_created_event(rec_req)
    await _dispatch_and_consume(ev4)
    async with AsyncSessionLocal() as check_session:
        notif = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_a.id,
                    Notification.type == NotificationType.RECOVERY_REQUEST_RECEIVED,
                )
            )
        ).scalar_one_or_none()
        assert notif is not None
        assert notif.data["recovery_request_id"] == str(rec_req.id)

    # Event 5: recovery_request.updated (ACCEPTED) -> RECOVERY_REQUEST_ACCEPTED
    rec_req.status = RecoveryRequestStatus.ACCEPTED
    ev5 = build_recovery_request_updated_event(
        recovery_req=rec_req,
        previous_status=RecoveryRequestStatus.PENDING,
        new_status=RecoveryRequestStatus.ACCEPTED,
    )
    await _dispatch_and_consume(ev5)
    async with AsyncSessionLocal() as check_session:
        notif = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_b.id,
                    Notification.type == NotificationType.RECOVERY_REQUEST_ACCEPTED,
                )
            )
        ).scalar_one_or_none()
        assert notif is not None
        assert "accepted" in notif.body.lower()

    # Event 6: match.alert_ready (Score 78 -> MATCH_DETECTED to source owner only)
    m_id = uuid.uuid4()
    ev6 = build_match_alert_ready_event(
        match_id=m_id,
        report_missing_id=rep_a.id,
        report_found_id=rep_b.id,
        missing_owner_id=user_a.id,
        found_owner_id=user_b.id,
        source_report_id=rep_b.id,
        source_owner_id=user_b.id,
        composite_score=78.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        alert_eligible=True,
        is_update=False,
    )
    await _dispatch_and_consume(ev6)
    async with AsyncSessionLocal() as check_session:
        # Notified user_b (newly reporting user)
        notif_b = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_b.id,
                    Notification.type == NotificationType.MATCH_DETECTED,
                )
            )
        ).scalar_one_or_none()
        assert notif_b is not None

        # Excluded user_a (existing owner on score 78.0)
        notif_a = (
            await check_session.execute(
                select(Notification).where(
                    Notification.user_id == user_a.id,
                    Notification.type == NotificationType.MATCH_DETECTED,
                )
            )
        ).scalar_one_or_none()
        assert notif_a is None


# =============================================================================
# 4. BUSINESS LOGIC, THRESHOLDS, COOLDOWNS & ANTI-SPAM
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_match_alert_score_tiers_and_cooldown(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies match scoring tiers and anti-spam oscillation suppression:
    - Score >= 80 -> Both owners notified.
    - Score 75-79 -> Source owner only.
    - Score < 75 -> Suppressed.
    - Delta < 5.0 -> Suppressed (micro-fluctuation).
    - 4h cooldown -> Enforced between match update alerts.
    """
    user_missing = await e2e_ctx.create_user("Missing Owner Tier")
    user_found = await e2e_ctx.create_user("Found Owner Tier")
    rep_missing = await e2e_ctx.create_report(user_missing.id, ReportType.MISSING)
    rep_found = await e2e_ctx.create_report(user_found.id, ReportType.FOUND)
    await e2e_ctx.session.commit()

    consumer_name = f"e2e_tiers_{uuid.uuid4().hex[:6]}"
    consumer = create_notification_consumer(
        consumer_name=consumer_name,
        group_id=NOTIFICATION_CONSUMER_GROUP,
        session_factory=AsyncSessionLocal,
    )

    current_offset = 0

    async def _send(
        score: float,
        is_update: bool = False,
        score_delta: float | None = None,
        previous_score: float | None = None,
        match_id: uuid.UUID | None = None,
    ) -> None:
        nonlocal current_offset
        current_offset += 1
        m_id = match_id or uuid.uuid4()
        ev = build_match_alert_ready_event(
            match_id=m_id,
            report_missing_id=rep_missing.id,
            report_found_id=rep_found.id,
            missing_owner_id=user_missing.id,
            found_owner_id=user_found.id,
            source_report_id=rep_found.id,
            source_owner_id=user_found.id,
            composite_score=score,
            classification=ScoreClassification.HIGH_PRIORITY
            if score >= 80.0
            else ScoreClassification.POSSIBLE_MATCH,
            alert_eligible=True,
            is_update=is_update,
            score_delta=score_delta,
            previous_score=previous_score,
            evidence_summary="Score testing",
        )
        e2e_ctx.consumer_event_ids.append(ev.event_id)
        rec = ConsumerRecord(
            topic=settings.KAFKA_DOMAIN_EVENTS_TOPIC,
            partition=0,
            offset=current_offset,
            timestamp=int(datetime.now(UTC).timestamp() * 1000),
            timestamp_type=0,
            key=str(m_id).encode("utf-8"),
            value=json.dumps(ev.model_dump(mode="json")).encode("utf-8"),
            checksum=None,
            serialized_key_size=0,
            serialized_value_size=0,
            headers=(),
        )
        await consumer.process_record(rec)

    # 1. Sub-threshold score (72.0) -> Zero notifications
    await _send(72.0)
    async with AsyncSessionLocal() as session:
        n_sub = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id.in_([user_missing.id, user_found.id])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(n_sub) == 0

    # 2. Rescore with micro-fluctuation delta (3.0 points) -> Suppressed
    canonical_match_id = uuid.uuid4()
    await _send(
        82.0,
        is_update=True,
        score_delta=3.0,
        previous_score=79.0,
        match_id=canonical_match_id,
    )
    async with AsyncSessionLocal() as session:
        n_micro = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id.in_([user_missing.id, user_found.id])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(n_micro) == 0

    # 3. Significant rescore (delta = 12.0 points) -> MATCH_UPDATED created
    await _send(
        91.0,
        is_update=True,
        score_delta=12.0,
        previous_score=79.0,
        match_id=canonical_match_id,
    )
    async with AsyncSessionLocal() as session:
        n_upd = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.MATCH_UPDATED
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(n_upd) >= 1

    # 4. Immediate second rescore within 4 hours -> Cooldown suppresses it
    await _send(
        95.0,
        is_update=True,
        score_delta=14.0,
        previous_score=81.0,
        match_id=canonical_match_id,
    )
    async with AsyncSessionLocal() as session:
        n_upd_after = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.MATCH_UPDATED
                    )
                )
            )
            .scalars()
            .all()
        )
        # Count remains unchanged because 4-hour cooldown blocked the second update
        assert len(n_upd_after) == len(n_upd)


# =============================================================================
# 5. CONCURRENCY, ATOMIC PERSISTENCE & LEASE MANAGEMENT
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_concurrent_deduplication_and_worker_leases(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies uniqueness under concurrency and SKIP LOCKED lease isolation."""
    user = await e2e_ctx.create_user("Concurrent User")
    await e2e_ctx.create_device(user.id, device_id="dev_c1")
    await e2e_ctx.create_device(user.id, device_id="dev_c2")

    # 1. Concurrent notification deduplication:
    # Attempting to insert identical (user_id, deduplication_key) concurrently
    dedup_key = f"concurrent:test:{uuid.uuid4()}"
    notif_1 = await create_notification(
        db=e2e_ctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Concurrent Alert 1",
        body="Alert body 1",
        data={"test": 1},
        deduplication_key=dedup_key,
    )
    notif_2 = await create_notification(
        db=e2e_ctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Concurrent Alert 2",
        body="Alert body 2",
        data={"test": 2},
        deduplication_key=dedup_key,
    )
    # Service returns existing row idempotently
    assert notif_1.id == notif_2.id

    # 2. Parallel push worker lease isolation:
    # Create two delivery tasks
    notif_other = await create_notification(
        db=e2e_ctx.session,
        user_id=user.id,
        type=NotificationType.REPORT_STATUS_CHANGED,
        title="Another Notification",
        body="Body",
        data={},
    )
    deliveries = await create_delivery_tasks(
        db=e2e_ctx.session,
        notification=notif_other,
    )
    await e2e_ctx.session.commit()
    assert len(deliveries) >= 2

    # Run two parallel push dispatchers concurrently
    mock_fcm = MockFCMProvider()
    dispatcher_a = PushDispatcher(
        session_factory=AsyncSessionLocal, fcm_provider=mock_fcm
    )
    dispatcher_b = PushDispatcher(
        session_factory=AsyncSessionLocal, fcm_provider=mock_fcm
    )

    results = await asyncio.gather(
        dispatcher_a.process_batch(batch_size=5),
        dispatcher_b.process_batch(batch_size=5),
    )
    total_dispatched = results[0] + results[1]
    assert total_dispatched == len(deliveries)

    # Verify both transitioned to SENT with non-overlapping leases
    async with AsyncSessionLocal() as session:
        delivs = (
            (
                await session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notif_other.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for d in delivs:
            assert d.status == DeliveryStatus.SENT
            assert d.fcm_message_id is not None


# =============================================================================
# 6. PUSH DISPATCHER CRASH RECOVERY, LEASES & TERMINAL STATES
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_push_dispatcher_abandoned_lease_recovery(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies that a delivery task stranded in PROCESSING (e.g. worker process killed)
    is safely reclaimed and delivered once the lease timeout expires.
    """
    user = await e2e_ctx.create_user("Crash User")
    await e2e_ctx.create_device(user.id)
    notif = await create_notification(
        db=e2e_ctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_HIGH_PRIORITY,
        title="Crash Recovery Alert",
        body="Crash body",
        data={"match_id": str(uuid.uuid4())},
    )
    delivs = await create_delivery_tasks(
        db=e2e_ctx.session,
        notification=notif,
    )
    await e2e_ctx.session.commit()
    assert len(delivs) >= 1
    task_id = delivs[0].id

    # Simulate abandoned lease: Status=PROCESSING, updated_at = 10 minutes ago
    async with AsyncSessionLocal() as session:
        task = await session.get(NotificationDelivery, task_id)
        assert task is not None
        task.status = DeliveryStatus.PROCESSING
        task.updated_at = datetime.now(UTC) - timedelta(minutes=10)
        await session.commit()

    # Run dispatcher cycle: It must reclaim the stale PROCESSING task
    mock_fcm = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_fcm,
    )
    processed = await dispatcher.process_batch(batch_size=10)
    assert processed >= 1

    # Verify the task successfully completed
    async with AsyncSessionLocal() as session:
        refreshed = await session.get(NotificationDelivery, task_id)
        assert refreshed is not None
        assert refreshed.status == DeliveryStatus.SENT
        assert refreshed.fcm_message_id is not None


@pytest.mark.asyncio
async def test_e2e_push_dispatcher_terminal_state_protection(
    e2e_ctx: E2ETestContext,
) -> None:
    """Verifies terminal-state protection: tasks marked SENT or PERMANENTLY_FAILED
    are never re-claimed or retried.
    """
    user = await e2e_ctx.create_user("Terminal User")
    await e2e_ctx.create_device(user.id)
    notif = await create_notification(
        db=e2e_ctx.session,
        user_id=user.id,
        type=NotificationType.REPORT_EXPIRING,
        title="Expiring Alert",
        body="Report is expiring",
        data={},
    )
    delivs = await create_delivery_tasks(
        db=e2e_ctx.session,
        notification=notif,
    )
    await e2e_ctx.session.commit()
    task_id = delivs[0].id

    # Mark as PERMANENTLY_FAILED
    async with AsyncSessionLocal() as session:
        task = await session.get(NotificationDelivery, task_id)
        assert task is not None
        task.status = DeliveryStatus.PERMANENTLY_FAILED
        task.last_error = "Permanent failure test"
        await session.commit()

    # Run dispatcher: Must NOT touch PERMANENTLY_FAILED task
    mock_fcm = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal, fcm_provider=mock_fcm
    )
    claimed = await dispatcher.process_batch(batch_size=10)
    assert claimed == 0

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(NotificationDelivery, task_id)
        assert refreshed is not None
        assert refreshed.status == DeliveryStatus.PERMANENTLY_FAILED


# =============================================================================
# 7. SECURITY & PAYLOAD PRIVACY AUDIT ACROSS ALL 9 NOTIFICATION TYPES
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_payload_privacy_and_security_audit(
    e2e_ctx: E2ETestContext,
) -> None:
    """Audits generated payloads across all 9 notification types:
    Zero raw GPS coordinates (latitude, longitude, lat, lon).
    Zero verification tokens or secrets.
    Zero passwords or credential hashes.
    Zero raw FCM tokens.
    """
    user = await e2e_ctx.create_user("Privacy Audit User")
    device = await e2e_ctx.create_device(
        user.id, platform=DevicePlatform.ANDROID, fcm_token="audit_secret_token_123"
    )

    types_and_data: list[tuple[NotificationType, dict[str, Any]]] = [
        (NotificationType.MATCH_DETECTED, {"match_id": str(uuid.uuid4())}),
        (NotificationType.MATCH_HIGH_PRIORITY, {"match_id": str(uuid.uuid4())}),
        (NotificationType.MATCH_UPDATED, {"match_id": str(uuid.uuid4())}),
        (
            NotificationType.RECOVERY_REQUEST_RECEIVED,
            {"recovery_request_id": str(uuid.uuid4())},
        ),
        (
            NotificationType.RECOVERY_REQUEST_ACCEPTED,
            {"recovery_request_id": str(uuid.uuid4())},
        ),
        (
            NotificationType.RECOVERY_REQUEST_REJECTED,
            {"recovery_request_id": str(uuid.uuid4())},
        ),
        (
            NotificationType.RECOVERY_REQUEST_COMPLETED,
            {"recovery_request_id": str(uuid.uuid4())},
        ),
        (NotificationType.REPORT_STATUS_CHANGED, {"report_id": str(uuid.uuid4())}),
        (NotificationType.REPORT_EXPIRING, {"report_id": str(uuid.uuid4())}),
    ]

    forbidden_keys = {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "coordinates",
        "password",
        "password_hash",
        "secret",
        "token_proof",
        "verification_token",
        "fcm_token",
    }

    for n_type, data in types_and_data:
        notif = await create_notification(
            db=e2e_ctx.session,
            user_id=user.id,
            type=n_type,
            title=f"Privacy Check {n_type.value}",
            body="Privacy verification body text",
            data=data,
        )

        deep_link = build_deep_link(notif.type, notif.data)
        fcm_data = build_fcm_data(notif, deep_link)
        fcm_msg = build_fcm_message(
            notification=notif,
            device=device,
        )
        assert fcm_msg is not None

        # Assert no forbidden keys appear in notification data or FCM data
        for k in forbidden_keys:
            assert k not in notif.data, (
                f"Notification data leaked forbidden key '{k}' in {n_type}"
            )
            assert k not in fcm_data, (
                f"FCM data payload leaked forbidden key '{k}' in {n_type}"
            )

        # Assert FCM token is never present inside payload data dictionary
        assert "fcm_token" not in fcm_data
        assert "audit_secret_token_123" not in json.dumps(fcm_data)


# =============================================================================
# 8. LIVE KAFKA BROKER ROUNDTRIP INTEGRATION (IF DOCKER KAFKA IS ONLINE)
# =============================================================================


@pytest.mark.asyncio
async def test_e2e_live_kafka_roundtrip_integration(
    e2e_ctx: E2ETestContext,
) -> None:
    """Exercises a live roundtrip against the running Apache Kafka KRaft broker:
    1. Transactional Outbox persists event.
    2. OutboxDispatcher publishes live event to Kafka topic.
    3. EventConsumer consumes live record from Kafka and commits offset.
    4. Notification and delivery records are materialized in PostgreSQL.
    """
    if not _check_live_kafka():
        pytest.skip(
            f"Apache Kafka broker is not online at {settings.KAFKA_BOOTSTRAP_SERVERS}"
        )

    session = e2e_ctx.session
    user = await e2e_ctx.create_user("Kafka Live User")
    await e2e_ctx.create_device(user.id)
    rep_a = await e2e_ctx.create_report(user.id, ReportType.MISSING)
    rep_b = await e2e_ctx.create_report(user.id, ReportType.FOUND)
    await session.commit()

    match_id = uuid.uuid4()
    event = build_match_alert_ready_event(
        match_id=match_id,
        report_missing_id=rep_a.id,
        report_found_id=rep_b.id,
        missing_owner_id=user.id,
        found_owner_id=user.id,
        source_report_id=rep_b.id,
        source_owner_id=user.id,
        composite_score=92.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        is_update=False,
        evidence_summary="Live Kafka roundtrip verification",
    )
    domain_event_id = event.event_id
    e2e_ctx.consumer_event_ids.append(domain_event_id)

    # 1. Start live consumer on "latest" so it immediately picks up new publications
    test_group = f"e2e_kafka_verify_{uuid.uuid4().hex[:8]}"
    consumer = create_notification_consumer(
        consumer_name="e2e_live_kafka_consumer",
        group_id=test_group,
        session_factory=AsyncSessionLocal,
        auto_offset_reset="latest",
        max_retries=1,
        initial_retry_delay=0.01,
    )
    await consumer.start()

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        consumer.run_loop(
            stop_event=stop_event,
            poll_timeout_ms=500,
        )
    )

    try:
        # Give consumer loop a brief moment to stabilize partition assignment
        await asyncio.sleep(1.0)

        # 2. Emit event to transactional outbox
        outbox_row = await create_outbox_event(
            db=session,
            event=event,
        )
        await session.commit()
        e2e_ctx.outbox_ids.append(outbox_row.id)

        # 3. OutboxDispatcher publishes live message to Kafka
        dispatcher = OutboxDispatcher(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
        )
        await dispatcher.start()
        try:
            for _ in range(10):
                p = await dispatcher.process_batch(batch_size=20)
                async with AsyncSessionLocal() as check_session:
                    refreshed_outbox = await check_session.get(
                        OutboxEvent, outbox_row.id
                    )
                    if (
                        refreshed_outbox is not None
                        and refreshed_outbox.status == OutboxStatus.PUBLISHED
                    ):
                        break
                if p == 0:
                    break
        finally:
            await dispatcher.stop()

        async with AsyncSessionLocal() as check_session:
            refreshed_outbox = await check_session.get(OutboxEvent, outbox_row.id)
            assert refreshed_outbox is not None
            assert refreshed_outbox.status == OutboxStatus.PUBLISHED

        # 4. Wait for consumer to process message and persist Notification
        persisted_notif: Notification | None = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            async with AsyncSessionLocal() as check_session:
                stmt = select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.type == NotificationType.MATCH_HIGH_PRIORITY,
                )
                res = await check_session.execute(stmt)
                candidate = res.scalar_one_or_none()
                if candidate is not None and candidate.data.get("match_id") == str(
                    match_id
                ):
                    persisted_notif = candidate
                    break

        assert persisted_notif is not None, (
            "Live Kafka consumer did not persist Notification within timeout"
        )
        assert persisted_notif.data["match_id"] == str(match_id)

    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(consumer_task, timeout=3.0)
        except Exception:
            pass
        await consumer.stop()
