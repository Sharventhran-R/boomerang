"""Kafka-driven Notification Consumer for Boomerang (Phase 9.3).

Subscribes to domain events under consumer group `boomerang.notification_engine.group`.
Evaluates authoritative recipient preferences, quiet hours, anti-spam oscillation
guards, and canonical deduplication keys to materialize persistent in-app notifications
and push delivery queue records atomically.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    Notification,
    NotificationPriority,
    NotificationType,
    RecoveryRequestStatus,
    Report,
    ReportStatus,
)
from app.schemas.events import (
    BoomerangEvent,
    EventType,
    MatchAlertReadyEvent,
    RecoveryRequestCreatedEvent,
    RecoveryRequestUpdatedEvent,
    ReportResolvedEvent,
    ReportUpdatedEvent,
)
from app.services.event_consumer import EventConsumer, HandlerRegistry
from app.services.notification import (
    compute_next_delivery_time,
    create_delivery_tasks,
    create_notification,
    get_or_create_preferences,
)

logger = logging.getLogger(__name__)

NOTIFICATION_CONSUMER_GROUP: str = "boomerang.notification_engine.group"
MATCH_COOLDOWN_HOURS: int = 4
MICRO_FLUCTUATION_THRESHOLD: float = 5.0
SIGNIFICANT_IMPROVEMENT_THRESHOLD: float = 10.0
HIGH_PRIORITY_SCORE_THRESHOLD: float = 80.0
MINIMUM_ALERT_SCORE_THRESHOLD: float = 75.0


class NotificationEventHandler:
    """Handles domain events and materializes in-app notifications and push tasks."""

    def __init__(self) -> None:
        self._event_types: Sequence[EventType] = (
            EventType.MATCH_ALERT_READY,
            EventType.RECOVERY_REQUEST_CREATED,
            EventType.RECOVERY_REQUEST_UPDATED,
            EventType.REPORT_RESOLVED,
            EventType.REPORT_UPDATED,
        )

    @property
    def event_types(self) -> Sequence[EventType]:
        return self._event_types

    async def handle(self, event: BoomerangEvent, session: AsyncSession) -> None:
        """Dispatches validated domain events to specialized notification handlers."""
        match event.event_type:
            case EventType.MATCH_ALERT_READY:
                await self._handle_match_alert_ready(
                    cast(MatchAlertReadyEvent, event), session
                )
            case EventType.RECOVERY_REQUEST_CREATED:
                await self._handle_recovery_request_created(
                    cast(RecoveryRequestCreatedEvent, event), session
                )
            case EventType.RECOVERY_REQUEST_UPDATED:
                await self._handle_recovery_request_updated(
                    cast(RecoveryRequestUpdatedEvent, event), session
                )
            case EventType.REPORT_RESOLVED:
                await self._handle_report_resolved(
                    cast(ReportResolvedEvent, event), session
                )
            case EventType.REPORT_UPDATED:
                await self._handle_report_updated(
                    cast(ReportUpdatedEvent, event), session
                )
            case _:
                logger.debug(
                    "Ignoring event '%s' with no notification subscriber",
                    event.event_type,
                )

    async def _handle_match_alert_ready(
        self, event: MatchAlertReadyEvent, session: AsyncSession
    ) -> None:
        """Processes match.alert_ready events and generates match notifications."""
        payload = event.payload
        if (
            not payload.alert_eligible
            or payload.composite_score < MINIMUM_ALERT_SCORE_THRESHOLD
        ):
            return

        now = datetime.now(UTC)
        score = payload.composite_score
        score_int = int(round(score))
        min_id = min(payload.report_missing_id, payload.report_found_id)
        max_id = max(payload.report_missing_id, payload.report_found_id)

        recipients: list[
            tuple[Any, NotificationType, NotificationPriority, str, str, str]
        ] = []

        if not payload.is_update:
            # Initial match detection alert
            dedup_key = f"match:initial:{min_id}:{max_id}"
            if score >= HIGH_PRIORITY_SCORE_THRESHOLD:
                # High priority: notify both report owners
                n_type = NotificationType.MATCH_HIGH_PRIORITY
                n_prio = NotificationPriority.HIGH
                title = f"High Priority Match Found ({score_int}%)"
                body = f"A potential match was discovered with {score_int}% confidence."
                owner_ids = list(
                    dict.fromkeys([payload.missing_owner_id, payload.found_owner_id])
                )
                for oid in owner_ids:
                    recipients.append((oid, n_type, n_prio, title, body, dedup_key))
            else:
                # Possible match (75.0 <= S < 80.0): notify newly reporting user ONLY
                n_type = NotificationType.MATCH_DETECTED
                n_prio = NotificationPriority.DEFAULT
                title = f"Potential Match Detected ({score_int}%)"
                body = f"A possible match was detected for your report ({score_int}%)."
                recipients.append(
                    (payload.source_owner_id, n_type, n_prio, title, body, dedup_key)
                )
        else:
            # Rescored match update
            # Micro-fluctuation filter
            if (
                payload.score_delta is not None
                and payload.score_delta < MICRO_FLUCTUATION_THRESHOLD
            ):
                return

            prev = payload.previous_score or 0.0
            transitions_high = (
                prev < HIGH_PRIORITY_SCORE_THRESHOLD
                and score >= HIGH_PRIORITY_SCORE_THRESHOLD
            )
            improves_significant = (
                payload.score_delta is not None
                and payload.score_delta >= SIGNIFICANT_IMPROVEMENT_THRESHOLD
            )

            if not (transitions_high or improves_significant):
                return

            dedup_key = f"match:update:{min_id}:{max_id}:{event.event_id}"
            n_type = NotificationType.MATCH_UPDATED
            n_prio = (
                NotificationPriority.HIGH
                if score >= HIGH_PRIORITY_SCORE_THRESHOLD
                else NotificationPriority.DEFAULT
            )
            title = f"Match Score Updated ({score_int}%)"
            body = f"A match for your report was updated to {score_int}% confidence."

            candidate_recipients = (
                list(dict.fromkeys([payload.missing_owner_id, payload.found_owner_id]))
                if score >= HIGH_PRIORITY_SCORE_THRESHOLD
                else [payload.source_owner_id]
            )

            for oid in candidate_recipients:
                # 4-hour cooldown check for this recipient on this match
                cooldown_cutoff = now - timedelta(hours=MATCH_COOLDOWN_HOURS)
                recent_stmt = (
                    select(Notification.id)
                    .where(
                        Notification.user_id == oid,
                        Notification.type.in_(
                            [
                                NotificationType.MATCH_DETECTED,
                                NotificationType.MATCH_HIGH_PRIORITY,
                                NotificationType.MATCH_UPDATED,
                            ]
                        ),
                        Notification.data["match_id"].astext == str(payload.match_id),
                        Notification.created_at >= cooldown_cutoff,
                    )
                    .limit(1)
                )
                recent_res = await session.execute(recent_stmt)
                if recent_res.scalar_one_or_none() is not None:
                    continue
                recipients.append((oid, n_type, n_prio, title, body, dedup_key))

        # Deliver to eligible recipients evaluating preferences
        for user_id, notif_type, notif_prio, title, body, d_key in recipients:
            pref = await get_or_create_preferences(session, user_id)

            if not pref.match_alerts_enabled:
                continue
            if score < pref.match_min_score:
                continue
            if pref.match_high_priority_only and score < HIGH_PRIORITY_SCORE_THRESHOLD:
                continue

            notif: Notification | None = None
            if pref.in_app_enabled:
                notif = await create_notification(
                    db=session,
                    user_id=user_id,
                    type=notif_type,
                    title=title,
                    body=body,
                    data={
                        "match_id": str(payload.match_id),
                        "report_missing_id": str(payload.report_missing_id),
                        "report_found_id": str(payload.report_found_id),
                        "score": payload.composite_score,
                        "entity_type": "match",
                        "deep_link": f"boomerang://matches/{payload.match_id}",
                    },
                    priority=notif_prio,
                    deduplication_key=d_key,
                )

            if pref.push_enabled and notif is not None:
                next_retry = compute_next_delivery_time(pref, now)
                await create_delivery_tasks(
                    db=session,
                    notification=notif,
                    next_retry_at=next_retry,
                )

    async def _handle_recovery_request_created(
        self, event: RecoveryRequestCreatedEvent, session: AsyncSession
    ) -> None:
        """Processes recovery_request.created events (mandatory claim notification)."""
        payload = event.payload
        user_id = payload.recipient_id
        pref = await get_or_create_preferences(session, user_id)

        title = "New Recovery Request Received"
        body = "Someone sent a recovery request regarding your report."
        data = {
            "recovery_request_id": str(payload.recovery_request_id),
            "report_id": str(payload.report_id),
            "entity_type": "recovery_request",
            "deep_link": (
                f"boomerang://recovery-requests?tab=received&id={payload.recovery_request_id}"
            ),
        }
        dedup_key = f"recovery_request:created:{payload.recovery_request_id}"

        # Mandatory claim notification: always persist in-app notification record
        notif = await create_notification(
            db=session,
            user_id=user_id,
            type=NotificationType.RECOVERY_REQUEST_RECEIVED,
            title=title,
            body=body,
            data=data,
            priority=NotificationPriority.HIGH,
            deduplication_key=dedup_key,
        )

        if pref.push_enabled:
            now = datetime.now(UTC)
            next_retry = compute_next_delivery_time(pref, now)
            await create_delivery_tasks(
                db=session,
                notification=notif,
                next_retry_at=next_retry,
            )

    async def _handle_recovery_request_updated(
        self, event: RecoveryRequestUpdatedEvent, session: AsyncSession
    ) -> None:
        """Processes recovery_request.updated for ACCEPTED, REJECTED, COMPLETED."""
        payload = event.payload
        new_status = payload.new_status
        req_id = payload.recovery_request_id

        recipients: list[
            tuple[Any, NotificationType, NotificationPriority, str, str, str]
        ] = []

        if new_status == RecoveryRequestStatus.ACCEPTED:
            recipients.append(
                (
                    payload.requester_id,
                    NotificationType.RECOVERY_REQUEST_ACCEPTED,
                    NotificationPriority.HIGH,
                    "Recovery Request Accepted",
                    "Your recovery request was accepted by the report owner.",
                    f"recovery_request:status:ACCEPTED:{req_id}",
                )
            )
        elif new_status == RecoveryRequestStatus.REJECTED:
            recipients.append(
                (
                    payload.requester_id,
                    NotificationType.RECOVERY_REQUEST_REJECTED,
                    NotificationPriority.DEFAULT,
                    "Recovery Request Declined",
                    "Your recovery request was declined.",
                    f"recovery_request:status:REJECTED:{req_id}",
                )
            )
        elif new_status == RecoveryRequestStatus.COMPLETED:
            for uid in dict.fromkeys([payload.requester_id, payload.recipient_id]):
                recipients.append(
                    (
                        uid,
                        NotificationType.RECOVERY_REQUEST_COMPLETED,
                        NotificationPriority.HIGH,
                        "Item Recovery Completed",
                        "The recovery process has been finalized successfully.",
                        f"recovery_request:status:COMPLETED:{req_id}",
                    )
                )
        else:
            return

        now = datetime.now(UTC)
        for uid, n_type, n_prio, title, body, d_key in recipients:
            pref = await get_or_create_preferences(session, uid)
            if not pref.recovery_updates_enabled:
                continue

            notif: Notification | None = None
            deep_link = (
                f"boomerang://reports/{payload.report_id}"
                if new_status == RecoveryRequestStatus.COMPLETED
                else f"boomerang://recovery-requests?tab=sent&id={req_id}"
            )
            if pref.in_app_enabled:
                notif = await create_notification(
                    db=session,
                    user_id=uid,
                    type=n_type,
                    title=title,
                    body=body,
                    data={
                        "recovery_request_id": str(req_id),
                        "report_id": str(payload.report_id),
                        "entity_type": (
                            "recovery_request"
                            if new_status != RecoveryRequestStatus.COMPLETED
                            else "report"
                        ),
                        "deep_link": deep_link,
                    },
                    priority=n_prio,
                    deduplication_key=d_key,
                )

            if pref.push_enabled and notif is not None:
                next_retry = compute_next_delivery_time(pref, now)
                await create_delivery_tasks(
                    db=session,
                    notification=notif,
                    next_retry_at=next_retry,
                )

    async def _handle_report_resolved(
        self, event: ReportResolvedEvent, session: AsyncSession
    ) -> None:
        """Processes report.resolved events notifying report author."""
        payload = event.payload
        report = await session.get(Report, payload.report_id)
        if report is None:
            return

        author_id = report.created_by_user_id
        pref = await get_or_create_preferences(session, author_id)
        if not pref.report_status_enabled:
            return

        title = "Report Marked as Resolved"
        body = "Your report has been marked as resolved."
        data = {
            "report_id": str(payload.report_id),
            "status": "RESOLVED",
            "entity_type": "report",
            "deep_link": f"boomerang://reports/{payload.report_id}",
        }
        dedup_key = f"report:status:RESOLVED:{payload.report_id}"

        notif: Notification | None = None
        if pref.in_app_enabled:
            notif = await create_notification(
                db=session,
                user_id=author_id,
                type=NotificationType.REPORT_STATUS_CHANGED,
                title=title,
                body=body,
                data=data,
                priority=NotificationPriority.DEFAULT,
                deduplication_key=dedup_key,
            )

        if pref.push_enabled and notif is not None:
            now = datetime.now(UTC)
            next_retry = compute_next_delivery_time(pref, now)
            await create_delivery_tasks(
                db=session,
                notification=notif,
                next_retry_at=next_retry,
            )

    async def _handle_report_updated(
        self, event: ReportUpdatedEvent, session: AsyncSession
    ) -> None:
        """Processes report.updated for meaningful non-ACTIVE status transitions."""
        payload = event.payload
        if "status" not in payload.updated_fields or payload.status is None:
            return

        # Routine edits to title, description, reward, etc. are ignored.
        if payload.status == ReportStatus.ACTIVE:
            return

        report = await session.get(Report, payload.report_id)
        if report is None:
            return

        author_id = report.created_by_user_id
        pref = await get_or_create_preferences(session, author_id)
        if not pref.report_status_enabled:
            return

        title = f"Report Status Updated to {payload.status.value}"
        body = f"Your report status has changed to {payload.status.value}."
        data = {
            "report_id": str(payload.report_id),
            "status": payload.status.value,
            "entity_type": "report",
            "deep_link": f"boomerang://reports/{payload.report_id}",
        }
        dedup_key = f"report:status:{payload.status.value}:{payload.report_id}"

        notif: Notification | None = None
        if pref.in_app_enabled:
            notif = await create_notification(
                db=session,
                user_id=author_id,
                type=NotificationType.REPORT_STATUS_CHANGED,
                title=title,
                body=body,
                data=data,
                priority=NotificationPriority.DEFAULT,
                deduplication_key=dedup_key,
            )

        if pref.push_enabled and notif is not None:
            now = datetime.now(UTC)
            next_retry = compute_next_delivery_time(pref, now)
            await create_delivery_tasks(
                db=session,
                notification=notif,
                next_retry_at=next_retry,
            )


def create_notification_consumer(
    consumer_name: str = "notification_engine",
    group_id: str = NOTIFICATION_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    bootstrap_servers: str | None = None,
    max_retries: int | None = None,
    initial_retry_delay: float | None = None,
    max_retry_delay: float | None = None,
    backoff_multiplier: float | None = None,
    auto_offset_reset: str = "earliest",
) -> EventConsumer:
    """Creates a configured EventConsumer wired to the NotificationEventHandler."""
    registry = HandlerRegistry()
    handler = NotificationEventHandler()
    registry.register(handler)

    return EventConsumer(
        consumer_name=consumer_name,
        group_id=group_id,
        topics=topics or [settings.KAFKA_DOMAIN_EVENTS_TOPIC],
        registry=registry,
        session_factory=session_factory or AsyncSessionLocal,
        consumer=consumer,
        bootstrap_servers=bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS,
        max_retries=max_retries,
        initial_retry_delay=initial_retry_delay,
        max_retry_delay=max_retry_delay,
        backoff_multiplier=backoff_multiplier,
        auto_offset_reset=auto_offset_reset,
    )


async def run_notification_consumer(
    stop_event: asyncio.Event | None = None,
    max_messages: int | None = None,
    poll_timeout_ms: int = 1000,
    consumer_name: str = "notification_engine",
    group_id: str = NOTIFICATION_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    bootstrap_servers: str | None = None,
) -> int:
    """Runs the notification consumer loop until stopped or max_messages reached."""
    event_consumer = create_notification_consumer(
        consumer_name=consumer_name,
        group_id=group_id,
        topics=topics,
        session_factory=session_factory,
        consumer=consumer,
        bootstrap_servers=bootstrap_servers,
    )
    return await event_consumer.run_loop(
        stop_event=stop_event,
        max_messages=max_messages,
        poll_timeout_ms=poll_timeout_ms,
    )
