"""Notification database repository and service layer for Boomerang (Phase 9.2).

Provides user-scoped methods for:
- In-app notification creation, retrieval, unread counting, and read-status updates.
- User device token registration, rotation, and deactivation.
- User notification preferences retrieval and updates.
- Push delivery task creation and dispatch queue querying.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    DeliveryStatus,
    DevicePlatform,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationPriority,
    NotificationType,
    UserDevice,
)

DEFAULT_RETENTION_DAYS: int = 90


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    priority: NotificationPriority = NotificationPriority.DEFAULT,
    deduplication_key: str | None = None,
    expires_at: datetime | None = None,
) -> Notification:
    """Creates a new in-app notification for a user.

    If deduplication_key is provided and a record for (user_id, deduplication_key)
    already exists, returns the existing notification without creating a duplicate.
    """
    now = datetime.now(UTC)
    if expires_at is None:
        expires_at = now + timedelta(days=DEFAULT_RETENTION_DAYS)

    if deduplication_key is not None:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.deduplication_key == deduplication_key,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing

    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        data=data or {},
        priority=priority,
        is_read=False,
        read_at=None,
        deduplication_key=deduplication_key,
        expires_at=expires_at,
    )
    db.add(notification)
    await db.flush()
    return notification


async def get_user_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    is_read: bool | None = None,
    type: NotificationType | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Notification], int, int]:
    """Retrieves a paginated list of non-expired notifications for a user."""
    now = datetime.now(UTC)
    conditions = [
        Notification.user_id == user_id,
        Notification.expires_at > now,
    ]

    if is_read is not None:
        conditions.append(Notification.is_read == is_read)
    if type is not None:
        conditions.append(Notification.type == type)

    count_stmt = select(func.count(Notification.id)).where(*conditions)
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    data_stmt = (
        select(Notification)
        .where(*conditions)
        .order_by(desc(Notification.created_at), desc(Notification.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items_res = await db.execute(data_stmt)
    items = list(items_res.scalars().all())

    return items, total, total_pages


async def get_unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Returns the number of unread, non-expired notifications for a user."""
    now = datetime.now(UTC)
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user_id,
        Notification.is_read == False,  # noqa: E712
        Notification.expires_at > now,
    )
    res = await db.execute(stmt)
    return res.scalar() or 0


async def mark_as_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Notification | None:
    """Marks a single user notification as read, enforcing user ownership."""
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    res = await db.execute(stmt)
    notification = res.scalar_one_or_none()
    if notification is None:
        return None

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await db.flush()

    return notification


async def mark_all_as_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Marks all unread notifications for a user as read.

    Returns the number of notifications marked as read.
    """
    now = datetime.now(UTC)
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True, read_at=now)
    )
    res = await db.execute(stmt)
    await db.flush()
    return int(res.rowcount)  # type: ignore[attr-defined]


async def register_device(
    db: AsyncSession,
    user_id: uuid.UUID,
    device_id: str,
    fcm_token: str,
    platform: DevicePlatform,
    device_model: str | None = None,
    app_version: str | None = None,
) -> UserDevice:
    """Registers or updates a user device FCM registration token.

    If the same token was previously assigned to a different user's device,
    deactivates the stale record to prevent cross-user token contamination.
    """
    now = datetime.now(UTC)

    # Deactivate any other user's active device sharing this identical token
    stale_stmt = (
        update(UserDevice)
        .where(
            UserDevice.fcm_token == fcm_token,
            UserDevice.user_id != user_id,
            UserDevice.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )
    await db.execute(stale_stmt)

    stmt = select(UserDevice).where(
        UserDevice.user_id == user_id,
        UserDevice.device_id == device_id,
    )
    res = await db.execute(stmt)
    device = res.scalar_one_or_none()

    if device is not None:
        device.fcm_token = fcm_token
        device.platform = platform
        device.device_model = device_model
        device.app_version = app_version
        device.is_active = True
        device.last_active_at = now
    else:
        device = UserDevice(
            user_id=user_id,
            device_id=device_id,
            fcm_token=fcm_token,
            platform=platform,
            device_model=device_model,
            app_version=app_version,
            is_active=True,
            last_active_at=now,
        )
        db.add(device)

    await db.flush()
    return device


async def deactivate_device(
    db: AsyncSession,
    user_id: uuid.UUID,
    device_id: str,
) -> bool:
    """Deactivates a user device token upon logout or app unregistration."""
    stmt = (
        update(UserDevice)
        .where(
            UserDevice.user_id == user_id,
            UserDevice.device_id == device_id,
            UserDevice.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )
    res = await db.execute(stmt)
    await db.flush()
    return bool(res.rowcount > 0)  # type: ignore[attr-defined]


async def get_or_create_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> NotificationPreference:
    """Retrieves or creates default notification preferences for a user."""
    stmt = select(NotificationPreference).where(
        NotificationPreference.user_id == user_id
    )
    res = await db.execute(stmt)
    pref = res.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            push_enabled=True,
            in_app_enabled=True,
            match_alerts_enabled=True,
            match_min_score=75.0,
            match_high_priority_only=False,
            recovery_updates_enabled=True,
            report_status_enabled=True,
            quiet_hours_enabled=False,
            quiet_hours_start=None,
            quiet_hours_end=None,
        )
        db.add(pref)
        await db.flush()

    return pref


async def update_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    push_enabled: bool | None = None,
    in_app_enabled: bool | None = None,
    match_alerts_enabled: bool | None = None,
    match_min_score: float | None = None,
    match_high_priority_only: bool | None = None,
    recovery_updates_enabled: bool | None = None,
    report_status_enabled: bool | None = None,
    quiet_hours_enabled: bool | None = None,
    quiet_hours_start: time | None = None,
    quiet_hours_end: time | None = None,
) -> NotificationPreference:
    """Updates user notification preferences."""
    pref = await get_or_create_preferences(db, user_id)

    if push_enabled is not None:
        pref.push_enabled = push_enabled
    if in_app_enabled is not None:
        pref.in_app_enabled = in_app_enabled
    if match_alerts_enabled is not None:
        pref.match_alerts_enabled = match_alerts_enabled
    if match_min_score is not None:
        if not (0.0 <= match_min_score <= 100.0):
            raise ValueError("match_min_score must be between 0.0 and 100.0")
        pref.match_min_score = match_min_score
    if match_high_priority_only is not None:
        pref.match_high_priority_only = match_high_priority_only
    if recovery_updates_enabled is not None:
        pref.recovery_updates_enabled = recovery_updates_enabled
    if report_status_enabled is not None:
        pref.report_status_enabled = report_status_enabled
    if quiet_hours_enabled is not None:
        pref.quiet_hours_enabled = quiet_hours_enabled
    if quiet_hours_start is not None:
        pref.quiet_hours_start = quiet_hours_start
    if quiet_hours_end is not None:
        pref.quiet_hours_end = quiet_hours_end

    await db.flush()
    return pref


def compute_next_delivery_time(pref: NotificationPreference, now: datetime) -> datetime:
    """Calculates next_retry_at for push delivery respecting quiet hours.

    If quiet hours are enabled and current time falls inside the configured
    window, returns the future datetime when quiet hours end. Otherwise returns now.
    """
    if (
        not pref.quiet_hours_enabled
        or pref.quiet_hours_start is None
        or pref.quiet_hours_end is None
    ):
        return now

    start_t = pref.quiet_hours_start
    end_t = pref.quiet_hours_end
    current_t = now.time()

    if start_t < end_t:
        # Same-day window, e.g. 13:00 to 15:00
        if start_t <= current_t < end_t:
            return datetime.combine(now.date(), end_t, tzinfo=now.tzinfo)
    else:
        # Overnight window, e.g. 22:00 to 07:00
        if current_t >= start_t:
            tomorrow = now.date() + timedelta(days=1)
            return datetime.combine(tomorrow, end_t, tzinfo=now.tzinfo)
        elif current_t < end_t:
            return datetime.combine(now.date(), end_t, tzinfo=now.tzinfo)

    return now


async def create_delivery_tasks(
    db: AsyncSession,
    notification: Notification,
    next_retry_at: datetime | None = None,
) -> list[NotificationDelivery]:
    """Creates pending push delivery tasks for all active devices of the user."""
    device_stmt = select(UserDevice).where(
        UserDevice.user_id == notification.user_id,
        UserDevice.is_active == True,  # noqa: E712
    )
    device_res = await db.execute(device_stmt)
    devices = list(device_res.scalars().all())

    tasks: list[NotificationDelivery] = []
    now = datetime.now(UTC)
    effective_next_retry = next_retry_at if next_retry_at is not None else now

    for dev in devices:
        check_stmt = select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notification.id,
            NotificationDelivery.user_device_id == dev.id,
        )
        existing = (await db.execute(check_stmt)).scalar_one_or_none()
        if existing is not None:
            continue

        delivery = NotificationDelivery(
            notification_id=notification.id,
            user_device_id=dev.id,
            status=DeliveryStatus.PENDING,
            retry_count=0,
            max_retries=3,
            next_retry_at=effective_next_retry,
        )
        db.add(delivery)
        tasks.append(delivery)

    if tasks:
        await db.flush()

    return tasks


async def get_pending_deliveries(
    db: AsyncSession,
    limit: int = 50,
) -> list[NotificationDelivery]:
    """Retrieves pending or retry-ready push delivery tasks."""
    now = datetime.now(UTC)
    stmt = (
        select(NotificationDelivery)
        .options(
            selectinload(NotificationDelivery.notification),
            selectinload(NotificationDelivery.device),
        )
        .where(
            or_(
                NotificationDelivery.status == DeliveryStatus.PENDING,
                NotificationDelivery.status == DeliveryStatus.PROCESSING,
                (
                    (NotificationDelivery.status == DeliveryStatus.FAILED)
                    & (
                        NotificationDelivery.retry_count
                        < NotificationDelivery.max_retries
                    )
                    & (NotificationDelivery.next_retry_at <= now)
                ),
            )
        )
        .order_by(NotificationDelivery.next_retry_at.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())
