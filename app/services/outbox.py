"""Transactional Outbox service for recording domain events atomically."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    OutboxEvent,
    OutboxStatus,
    RecoveryRequest,
    RecoveryRequestStatus,
    Report,
    ReportCategory,
    ReportStatus,
)
from app.schemas.events import (
    AggregateType,
    BoomerangEvent,
    EventType,
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

PRODUCER_NAME: str = "boomerang-backend"


def build_report_created_event(
    report: Report,
    latitude: float,
    longitude: float,
    correlation_id: uuid.UUID | None = None,
) -> ReportCreatedEvent:
    now = datetime.now(UTC)
    payload = ReportCreatedPayload(
        report_id=report.id,
        created_by_user_id=report.created_by_user_id,
        type=report.type,
        category=report.category,
        title=report.title,
        description=report.description,
        latitude=latitude,
        longitude=longitude,
        event_time=report.event_time,
        reward_amount=report.reward_amount,
        status=ReportStatus.ACTIVE,
        created_at=report.created_at or now,
    )
    return ReportCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_CREATED,
        event_version=1,
        occurred_at=now,
        producer=PRODUCER_NAME,
        aggregate_id=report.id,
        aggregate_type=AggregateType.REPORT,
        correlation_id=correlation_id,
        payload=payload,
    )


def build_report_updated_event(
    report_id: uuid.UUID,
    updated_fields: list[str],
    title: str | None = None,
    description: str | None = None,
    category: ReportCategory | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    event_time: datetime | None = None,
    reward_amount: Decimal | None = None,
    status: ReportStatus | None = None,
    correlation_id: uuid.UUID | None = None,
) -> ReportUpdatedEvent:
    now = datetime.now(UTC)
    payload = ReportUpdatedPayload(
        report_id=report_id,
        updated_fields=updated_fields,
        title=title if "title" in updated_fields else None,
        description=description if "description" in updated_fields else None,
        category=category if "category" in updated_fields else None,
        latitude=latitude if "latitude" in updated_fields else None,
        longitude=longitude if "longitude" in updated_fields else None,
        event_time=event_time if "event_time" in updated_fields else None,
        reward_amount=reward_amount if "reward_amount" in updated_fields else None,
        status=status if "status" in updated_fields else None,
        updated_at=now,
    )
    return ReportUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_UPDATED,
        event_version=1,
        occurred_at=now,
        producer=PRODUCER_NAME,
        aggregate_id=report_id,
        aggregate_type=AggregateType.REPORT,
        correlation_id=correlation_id,
        payload=payload,
    )


def build_report_resolved_event(
    report_id: uuid.UUID,
    resolution_reason: str | None = None,
    associated_recovery_request_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> ReportResolvedEvent:
    now = datetime.now(UTC)
    payload = ReportResolvedPayload(
        report_id=report_id,
        status=ReportStatus.RESOLVED,
        resolved_at=now,
        resolution_reason=resolution_reason,
        associated_recovery_request_id=associated_recovery_request_id,
    )
    return ReportResolvedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REPORT_RESOLVED,
        event_version=1,
        occurred_at=now,
        producer=PRODUCER_NAME,
        aggregate_id=report_id,
        aggregate_type=AggregateType.REPORT,
        correlation_id=correlation_id,
        payload=payload,
    )


def build_recovery_request_created_event(
    recovery_req: RecoveryRequest,
    correlation_id: uuid.UUID | None = None,
) -> RecoveryRequestCreatedEvent:
    now = datetime.now(UTC)
    payload = RecoveryRequestCreatedPayload(
        recovery_request_id=recovery_req.id,
        report_id=recovery_req.report_id,
        requester_id=recovery_req.requester_id,
        recipient_id=recovery_req.recipient_id,
        status=RecoveryRequestStatus.PENDING,
        message=recovery_req.message,
        created_at=recovery_req.created_at or now,
    )
    return RecoveryRequestCreatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_CREATED,
        event_version=1,
        occurred_at=now,
        producer=PRODUCER_NAME,
        aggregate_id=recovery_req.id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        correlation_id=correlation_id,
        payload=payload,
    )


def build_recovery_request_updated_event(
    recovery_req: RecoveryRequest,
    previous_status: RecoveryRequestStatus,
    new_status: RecoveryRequestStatus,
    correlation_id: uuid.UUID | None = None,
) -> RecoveryRequestUpdatedEvent:
    now = datetime.now(UTC)
    payload = RecoveryRequestUpdatedPayload(
        recovery_request_id=recovery_req.id,
        report_id=recovery_req.report_id,
        requester_id=recovery_req.requester_id,
        recipient_id=recovery_req.recipient_id,
        previous_status=previous_status,
        new_status=new_status,
        updated_at=now,
    )
    return RecoveryRequestUpdatedEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.RECOVERY_REQUEST_UPDATED,
        event_version=1,
        occurred_at=now,
        producer=PRODUCER_NAME,
        aggregate_id=recovery_req.id,
        aggregate_type=AggregateType.RECOVERY_REQUEST,
        correlation_id=correlation_id,
        payload=payload,
    )


async def create_outbox_event(
    db: AsyncSession,
    event: BoomerangEvent,
    topic: str | None = None,
) -> OutboxEvent:
    """Enqueues a domain event into the transactional outbox table.

    Must be called within an active database transaction before db.commit().
    """
    serialized: dict[str, Any] = event.model_dump(mode="json")
    outbox_event = OutboxEvent(
        event_id=event.event_id,
        event_type=event.event_type.value,
        event_version=event.event_version,
        aggregate_type=event.aggregate_type.value,
        aggregate_id=event.aggregate_id,
        topic=topic or settings.KAFKA_DOMAIN_EVENTS_TOPIC,
        payload=serialized,
        status=OutboxStatus.PENDING,
        retry_count=0,
        max_retries=settings.OUTBOX_MAX_RETRIES,
        occurred_at=event.occurred_at,
        next_retry_at=datetime.now(UTC),
    )
    db.add(outbox_event)
    return outbox_event
