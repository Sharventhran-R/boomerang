"""Integration and unit tests for Phase 9.2: Notification Database Models & Repository.

Verifies:
- Notification model fields, defaults, 90-day retention, and custom expiration.
- Database unique constraint on (user_id, deduplication_key) and service-level
  idempotency.
- In-app notification retrieval, user isolation, and multi-field filtering.
- Unread count calculation excluding expired notifications.
- Single and bulk read status marking with ownership validation.
- UserDevice registration, token rotation across users, and logout deactivation.
- Multiple active devices per user.
- NotificationPreference default values, update methods, and check constraints
  (0.0 <= score <= 100.0).
- NotificationDelivery task creation for active devices, duplicate prevention, and
  pending task queue queries.
- ON DELETE RESTRICT protection preventing accidental destruction of
  notification and delivery history.
- Device deactivation preserving delivery history and device records on logout.
- Explicit account deletion policy with child-to-parent record lifecycle
  management.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    DeliveryStatus,
    DevicePlatform,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationPriority,
    NotificationType,
    User,
    UserDevice,
)
from app.services.notification import (
    create_delivery_tasks,
    create_notification,
    deactivate_device,
    get_or_create_preferences,
    get_pending_deliveries,
    get_unread_count,
    get_user_notifications,
    mark_all_as_read,
    mark_as_read,
    register_device,
    update_preferences,
)


class NotificationTestContext:
    """Manages test user lifecycle and isolated session cleanup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []

    async def create_user(self, name: str = "Test User") -> User:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            email=f"user_{uid}@example.com",
            name=name,
            password_hash="hashed_pw_test",
        )
        self.session.add(user)
        await self.session.flush()
        self.user_ids.append(user.id)
        return user

    async def cleanup(self) -> None:
        try:
            await self.session.rollback()
        except Exception:
            pass

        if self.user_ids:
            async with AsyncSessionLocal() as cleanup_session:
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
                await cleanup_session.execute(
                    delete(User).where(User.id.in_(self.user_ids))
                )
                await cleanup_session.commit()


@pytest.fixture
async def nctx() -> AsyncGenerator[NotificationTestContext, None]:
    async with AsyncSessionLocal() as session:
        ctx = NotificationTestContext(session)
        try:
            yield ctx
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_notification_creation_and_defaults(
    nctx: NotificationTestContext,
) -> None:
    """Verifies default values and 90-day retention on notification creation."""
    user = await nctx.create_user()
    now = datetime.now(UTC)

    notification = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="High Priority Match Found",
        body="A 92% match was discovered for your missing Golden Retriever.",
        data={"match_id": str(uuid.uuid4()), "score": 92.5},
        priority=NotificationPriority.HIGH,
    )
    await nctx.session.commit()

    assert notification.id is not None
    assert notification.user_id == user.id
    assert notification.type == NotificationType.MATCH_DETECTED
    assert notification.title == "High Priority Match Found"
    assert (
        notification.body
        == "A 92% match was discovered for your missing Golden Retriever."
    )
    assert notification.data["score"] == 92.5
    assert notification.priority == NotificationPriority.HIGH
    assert notification.is_read is False
    assert notification.read_at is None
    assert notification.deduplication_key is None
    assert notification.created_at is not None

    # Retention should default to ~90 days
    delta_days = (notification.expires_at - now).total_seconds() / 86400
    assert 89.0 <= delta_days <= 91.0


@pytest.mark.asyncio
async def test_notification_custom_expiration(
    nctx: NotificationTestContext,
) -> None:
    """Verifies explicit expires_at parameter is persisted."""
    user = await nctx.create_user()
    custom_expiry = datetime.now(UTC) + timedelta(days=7)

    notification = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.REPORT_EXPIRING,
        title="Report Expiring Soon",
        body="Your report will expire in 7 days.",
        expires_at=custom_expiry,
    )
    await nctx.session.commit()

    assert abs((notification.expires_at - custom_expiry).total_seconds()) < 1.0


@pytest.mark.asyncio
async def test_notification_deduplication_key_uniqueness_db_constraint(
    nctx: NotificationTestContext,
) -> None:
    """Verifies database-level unique constraint on (user_id, deduplication_key)."""
    user = await nctx.create_user()
    dedup_key = f"match_alert:{uuid.uuid4()}:{uuid.uuid4()}"
    expiry = datetime.now(UTC) + timedelta(days=90)

    n1 = Notification(
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Match 1",
        body="Body 1",
        data={},
        priority=NotificationPriority.DEFAULT,
        deduplication_key=dedup_key,
        expires_at=expiry,
    )
    nctx.session.add(n1)
    await nctx.session.flush()

    n2 = Notification(
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Match 2",
        body="Body 2",
        data={},
        priority=NotificationPriority.DEFAULT,
        deduplication_key=dedup_key,
        expires_at=expiry,
    )
    nctx.session.add(n2)

    with pytest.raises(IntegrityError):
        await nctx.session.flush()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_create_notification_deduplication_service_behavior(
    nctx: NotificationTestContext,
) -> None:
    """Verifies service deduplication: returning existing record on duplicate key."""
    user = await nctx.create_user()
    dedup_key = f"match_alert:{uuid.uuid4()}"

    n1 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="First Alert",
        body="Body 1",
        deduplication_key=dedup_key,
    )
    await nctx.session.commit()

    n2 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Duplicate Attempt",
        body="Body 2",
        deduplication_key=dedup_key,
    )
    await nctx.session.commit()

    assert n1.id == n2.id
    assert n2.title == "First Alert"


@pytest.mark.asyncio
async def test_notification_null_deduplication_key_allowed_multiple(
    nctx: NotificationTestContext,
) -> None:
    """Verifies multiple notifications with deduplication_key=None are allowed."""
    user = await nctx.create_user()

    n1 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.REPORT_STATUS_CHANGED,
        title="Status 1",
        body="Status updated 1",
        deduplication_key=None,
    )
    n2 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.REPORT_STATUS_CHANGED,
        title="Status 2",
        body="Status updated 2",
        deduplication_key=None,
    )
    await nctx.session.commit()

    assert n1.id != n2.id


@pytest.mark.asyncio
async def test_get_user_notifications_user_isolation(
    nctx: NotificationTestContext,
) -> None:
    """Verifies notifications are strictly scoped by user_id."""
    user_a = await nctx.create_user(name="User A")
    user_b = await nctx.create_user(name="User B")

    await create_notification(
        db=nctx.session,
        user_id=user_a.id,
        type=NotificationType.MATCH_DETECTED,
        title="Alert for A",
        body="A's body",
    )
    await create_notification(
        db=nctx.session,
        user_id=user_b.id,
        type=NotificationType.RECOVERY_REQUEST_RECEIVED,
        title="Alert for B",
        body="B's body",
    )
    await nctx.session.commit()

    items_a, total_a, pages_a = await get_user_notifications(
        db=nctx.session, user_id=user_a.id
    )
    items_b, total_b, pages_b = await get_user_notifications(
        db=nctx.session, user_id=user_b.id
    )
    await nctx.session.commit()

    assert total_a == 1
    assert items_a[0].title == "Alert for A"
    assert total_b == 1
    assert items_b[0].title == "Alert for B"


@pytest.mark.asyncio
async def test_get_user_notifications_filtering(
    nctx: NotificationTestContext,
) -> None:
    """Verifies filtering by is_read and notification type."""
    user = await nctx.create_user()

    n1 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Unread Match",
        body="Match unread",
    )
    n2 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Read Match",
        body="Match read",
    )
    n3 = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.RECOVERY_REQUEST_RECEIVED,
        title="Unread Recovery",
        body="Recovery unread",
    )
    await nctx.session.commit()

    # Mark n2 as read
    await mark_as_read(db=nctx.session, user_id=user.id, notification_id=n2.id)
    await nctx.session.commit()

    # Filter unread
    unread_items, total_unread, _ = await get_user_notifications(
        db=nctx.session, user_id=user.id, is_read=False
    )
    await nctx.session.commit()

    unread_ids = [item.id for item in unread_items]
    assert n1.id in unread_ids
    assert n3.id in unread_ids
    assert n2.id not in unread_ids

    # Filter by type MATCH_DETECTED
    match_items, total_matches, _ = await get_user_notifications(
        db=nctx.session, user_id=user.id, type=NotificationType.MATCH_DETECTED
    )
    await nctx.session.commit()

    assert total_matches == 2
    match_ids = [m.id for m in match_items]
    assert n1.id in match_ids
    assert n2.id in match_ids
    assert n3.id not in match_ids


@pytest.mark.asyncio
async def test_get_user_notifications_expiration_filtering(
    nctx: NotificationTestContext,
) -> None:
    """Verifies expired notifications are filtered out."""
    user = await nctx.create_user()
    now = datetime.now(UTC)

    # Past notification
    await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Old Alert",
        body="Expired",
        expires_at=now - timedelta(days=2),
    )
    # Active notification
    active = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Active Alert",
        body="Still valid",
        expires_at=now + timedelta(days=30),
    )
    await nctx.session.commit()

    items, total, _ = await get_user_notifications(db=nctx.session, user_id=user.id)
    assert total == 1
    assert items[0].id == active.id

    unread_count = await get_unread_count(db=nctx.session, user_id=user.id)
    await nctx.session.commit()
    assert unread_count == 1


@pytest.mark.asyncio
async def test_mark_as_read_ownership_and_timestamps(
    nctx: NotificationTestContext,
) -> None:
    """Verifies mark_as_read enforces ownership and sets read_at."""
    user_a = await nctx.create_user(name="Owner")
    user_b = await nctx.create_user(name="Attacker")

    notif = await create_notification(
        db=nctx.session,
        user_id=user_a.id,
        type=NotificationType.MATCH_DETECTED,
        title="Owner Notification",
        body="Confidential",
    )
    await nctx.session.commit()

    # User B tries to mark User A's notification as read
    unauthorized_res = await mark_as_read(
        db=nctx.session, user_id=user_b.id, notification_id=notif.id
    )
    await nctx.session.commit()
    assert unauthorized_res is None

    # Verify notification remains unread
    assert notif.is_read is False
    assert notif.read_at is None

    # User A marks as read
    read_res = await mark_as_read(
        db=nctx.session, user_id=user_a.id, notification_id=notif.id
    )
    await nctx.session.commit()
    assert read_res is not None
    assert read_res.is_read is True
    assert read_res.read_at is not None

    # Subsequent call on already read item is idempotent
    second_res = await mark_as_read(
        db=nctx.session, user_id=user_a.id, notification_id=notif.id
    )
    await nctx.session.commit()
    assert second_res is not None
    assert second_res.is_read is True


@pytest.mark.asyncio
async def test_mark_all_as_read(nctx: NotificationTestContext) -> None:
    """Verifies bulk mark_all_as_read marks only target user's unread notifications."""
    user_a = await nctx.create_user(name="User A")
    user_b = await nctx.create_user(name="User B")

    await create_notification(
        db=nctx.session,
        user_id=user_a.id,
        type=NotificationType.MATCH_DETECTED,
        title="A1",
        body="B1",
    )
    await create_notification(
        db=nctx.session,
        user_id=user_a.id,
        type=NotificationType.MATCH_DETECTED,
        title="A2",
        body="B2",
    )
    await create_notification(
        db=nctx.session,
        user_id=user_b.id,
        type=NotificationType.MATCH_DETECTED,
        title="B1",
        body="B1",
    )
    await nctx.session.commit()

    count_marked = await mark_all_as_read(db=nctx.session, user_id=user_a.id)
    await nctx.session.commit()

    assert count_marked == 2
    assert await get_unread_count(db=nctx.session, user_id=user_a.id) == 0
    assert await get_unread_count(db=nctx.session, user_id=user_b.id) == 1
    await nctx.session.commit()


@pytest.mark.asyncio
async def test_register_device_new_and_update(
    nctx: NotificationTestContext,
) -> None:
    """Verifies device registration and updates on the same device_id."""
    user = await nctx.create_user()
    dev_id = f"dev_{uuid.uuid4()}"

    # Initial registration
    device = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id=dev_id,
        fcm_token="token_alpha_1",
        platform=DevicePlatform.ANDROID,
        device_model="Pixel 8",
        app_version="1.0.0",
    )
    await nctx.session.commit()

    assert device.id is not None
    assert device.fcm_token == "token_alpha_1"
    assert device.platform == DevicePlatform.ANDROID
    assert device.device_model == "Pixel 8"
    assert device.is_active is True

    # Re-registration with new token and app version
    updated_device = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id=dev_id,
        fcm_token="token_alpha_2",
        platform=DevicePlatform.ANDROID,
        device_model="Pixel 8 Pro",
        app_version="1.0.1",
    )
    await nctx.session.commit()

    assert updated_device.id == device.id
    assert updated_device.fcm_token == "token_alpha_2"
    assert updated_device.device_model == "Pixel 8 Pro"
    assert updated_device.app_version == "1.0.1"
    assert updated_device.is_active is True


@pytest.mark.asyncio
async def test_register_device_cross_user_token_rotation(
    nctx: NotificationTestContext,
) -> None:
    """Verifies that when user B registers a token held by user A,
    user A's device is deactivated.
    """
    user_a = await nctx.create_user(name="User A")
    user_b = await nctx.create_user(name="User B")
    shared_token = f"fcm_token_{uuid.uuid4()}"

    dev_a = await register_device(
        db=nctx.session,
        user_id=user_a.id,
        device_id="device_a",
        fcm_token=shared_token,
        platform=DevicePlatform.IOS,
    )
    await nctx.session.commit()
    assert dev_a.is_active is True

    # User B logs into the same physical phone
    dev_b = await register_device(
        db=nctx.session,
        user_id=user_b.id,
        device_id="device_b",
        fcm_token=shared_token,
        platform=DevicePlatform.IOS,
    )
    await nctx.session.commit()

    await nctx.session.refresh(dev_a)
    assert dev_b.is_active is True
    assert dev_a.is_active is False


@pytest.mark.asyncio
async def test_deactivate_device_on_logout(
    nctx: NotificationTestContext,
) -> None:
    """Verifies device deactivation upon logout."""
    user = await nctx.create_user()
    dev_id = f"dev_{uuid.uuid4()}"

    await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id=dev_id,
        fcm_token="fcm_token_test",
        platform=DevicePlatform.ANDROID,
    )
    await nctx.session.commit()

    deactivated = await deactivate_device(
        db=nctx.session, user_id=user.id, device_id=dev_id
    )
    await nctx.session.commit()
    assert deactivated is True

    # Deactivating again returns False
    deactivated_again = await deactivate_device(
        db=nctx.session, user_id=user.id, device_id=dev_id
    )
    await nctx.session.commit()
    assert deactivated_again is False


@pytest.mark.asyncio
async def test_multiple_devices_per_user(
    nctx: NotificationTestContext,
) -> None:
    """Verifies a user can register multiple distinct active devices."""
    user = await nctx.create_user()

    phone = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="phone_001",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    tablet = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="tablet_001",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.IOS,
    )
    await nctx.session.commit()

    assert phone.id != tablet.id
    assert phone.is_active is True
    assert tablet.is_active is True


@pytest.mark.asyncio
async def test_notification_preferences_defaults_and_updates(
    nctx: NotificationTestContext,
) -> None:
    """Verifies default preference values and update methods."""
    user = await nctx.create_user()

    pref = await get_or_create_preferences(db=nctx.session, user_id=user.id)
    await nctx.session.commit()

    assert pref.push_enabled is True
    assert pref.in_app_enabled is True
    assert pref.match_alerts_enabled is True
    assert pref.match_min_score == 75.0
    assert pref.match_high_priority_only is False
    assert pref.recovery_updates_enabled is True
    assert pref.report_status_enabled is True
    assert pref.quiet_hours_enabled is False
    assert pref.quiet_hours_start is None
    assert pref.quiet_hours_end is None

    # Update preferences
    updated = await update_preferences(
        db=nctx.session,
        user_id=user.id,
        match_min_score=85.0,
        quiet_hours_enabled=True,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(7, 0),
    )
    await nctx.session.commit()

    assert updated.match_min_score == 85.0
    assert updated.quiet_hours_enabled is True
    assert updated.quiet_hours_start == time(22, 0)
    assert updated.quiet_hours_end == time(7, 0)


@pytest.mark.asyncio
async def test_notification_preferences_unique_constraint(
    nctx: NotificationTestContext,
) -> None:
    """Verifies one preference record per user unique constraint."""
    user = await nctx.create_user()

    p1 = NotificationPreference(
        user_id=user.id,
        push_enabled=True,
        in_app_enabled=True,
        match_alerts_enabled=True,
        match_min_score=75.0,
        match_high_priority_only=False,
        recovery_updates_enabled=True,
        report_status_enabled=True,
        quiet_hours_enabled=False,
    )
    nctx.session.add(p1)
    await nctx.session.flush()

    p2 = NotificationPreference(
        user_id=user.id,
        push_enabled=False,
        in_app_enabled=False,
        match_alerts_enabled=False,
        match_min_score=50.0,
        match_high_priority_only=False,
        recovery_updates_enabled=False,
        report_status_enabled=False,
        quiet_hours_enabled=False,
    )
    nctx.session.add(p2)

    with pytest.raises(IntegrityError):
        await nctx.session.flush()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_notification_preferences_score_validation(
    nctx: NotificationTestContext,
) -> None:
    """Verifies match_min_score bounds check (0.0 to 100.0)."""
    user = await nctx.create_user()

    # Python-level validation in update_preferences
    with pytest.raises(
        ValueError, match="match_min_score must be between 0.0 and 100.0"
    ):
        await update_preferences(
            db=nctx.session, user_id=user.id, match_min_score=-10.0
        )

    with pytest.raises(
        ValueError, match="match_min_score must be between 0.0 and 100.0"
    ):
        await update_preferences(
            db=nctx.session, user_id=user.id, match_min_score=110.0
        )

    # Database-level check constraint chk_notif_pref_match_min_score
    invalid_pref = NotificationPreference(
        user_id=user.id,
        push_enabled=True,
        in_app_enabled=True,
        match_alerts_enabled=True,
        match_min_score=150.0,
        match_high_priority_only=False,
        recovery_updates_enabled=True,
        report_status_enabled=True,
        quiet_hours_enabled=False,
    )
    nctx.session.add(invalid_pref)
    with pytest.raises((IntegrityError, DBAPIError)):
        await nctx.session.flush()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_create_delivery_tasks_and_deduplication(
    nctx: NotificationTestContext,
) -> None:
    """Verifies push delivery tasks creation for active devices and idempotency."""
    user = await nctx.create_user()

    # 2 active devices, 1 inactive device
    dev1 = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="active_1",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    dev2 = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="active_2",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.IOS,
    )
    dev3 = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="inactive_1",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    await deactivate_device(db=nctx.session, user_id=user.id, device_id="inactive_1")
    await nctx.session.commit()

    notification = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Test Match Alert",
        body="Body",
    )
    await nctx.session.commit()

    tasks = await create_delivery_tasks(db=nctx.session, notification=notification)
    await nctx.session.commit()

    assert len(tasks) == 2
    task_device_ids = {t.user_device_id for t in tasks}
    assert dev1.id in task_device_ids
    assert dev2.id in task_device_ids
    assert dev3.id not in task_device_ids

    for t in tasks:
        assert t.status == DeliveryStatus.PENDING
        assert t.retry_count == 0
        assert t.max_retries == 3

    # Idempotent re-run should create 0 new tasks
    second_tasks = await create_delivery_tasks(
        db=nctx.session, notification=notification
    )
    assert len(second_tasks) == 0


@pytest.mark.asyncio
async def test_get_pending_deliveries_query(
    nctx: NotificationTestContext,
) -> None:
    """Verifies get_pending_deliveries retrieves PENDING and eligible retry tasks."""
    user = await nctx.create_user()
    dev = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="dev_queue_test",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    notif = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Alert",
        body="Body",
    )
    await nctx.session.commit()

    now = datetime.now(UTC)

    # 1. PENDING delivery
    deliv_pending = NotificationDelivery(
        notification_id=notif.id,
        user_device_id=dev.id,
        status=DeliveryStatus.PENDING,
        retry_count=0,
        max_retries=3,
        next_retry_at=now,
    )
    nctx.session.add(deliv_pending)
    await nctx.session.commit()

    pending_list = await get_pending_deliveries(db=nctx.session, limit=10)
    pending_ids = [d.id for d in pending_list]
    assert deliv_pending.id in pending_ids

    # 2. Update to FAILED with next_retry_at in the future -> should not appear
    deliv_pending.status = DeliveryStatus.FAILED
    deliv_pending.retry_count = 1
    deliv_pending.next_retry_at = now + timedelta(minutes=10)
    await nctx.session.commit()

    pending_list = await get_pending_deliveries(db=nctx.session, limit=10)
    assert deliv_pending.id not in [d.id for d in pending_list]

    # 3. Update to FAILED with next_retry_at in the past -> should appear
    deliv_pending.next_retry_at = now - timedelta(seconds=5)
    await nctx.session.commit()

    pending_list = await get_pending_deliveries(db=nctx.session, limit=10)
    assert deliv_pending.id in [d.id for d in pending_list]

    # 4. Update to PERMANENTLY_FAILED -> should not appear
    deliv_pending.status = DeliveryStatus.PERMANENTLY_FAILED
    await nctx.session.commit()

    pending_list = await get_pending_deliveries(db=nctx.session, limit=10)
    assert deliv_pending.id not in [d.id for d in pending_list]


@pytest.mark.asyncio
async def test_deleting_device_restricted_when_deliveries_exist(
    nctx: NotificationTestContext,
) -> None:
    """Verifies ON DELETE RESTRICT prevents deleting a device with delivery records."""
    user = await nctx.create_user()
    dev = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="restrict_dev",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    notif = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Delivery Alert",
        body="Body",
    )
    await nctx.session.commit()

    tasks = await create_delivery_tasks(db=nctx.session, notification=notif)
    await nctx.session.commit()
    assert len(tasks) == 1

    # Attempting to delete the device directly must fail due to ON DELETE RESTRICT
    with pytest.raises((IntegrityError, DBAPIError)):
        await nctx.session.execute(delete(UserDevice).where(UserDevice.id == dev.id))
        await nctx.session.commit()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_deleting_notification_restricted_when_deliveries_exist(
    nctx: NotificationTestContext,
) -> None:
    """Verifies ON DELETE RESTRICT prevents deleting a notification with delivery
    records.
    """
    user = await nctx.create_user()
    await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="notif_restrict_dev",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.IOS,
    )
    notif = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Protected Alert",
        body="Body",
    )
    await nctx.session.commit()

    tasks = await create_delivery_tasks(db=nctx.session, notification=notif)
    await nctx.session.commit()
    assert len(tasks) == 1

    # Attempting to delete the notification must fail due to ON DELETE RESTRICT
    with pytest.raises((IntegrityError, DBAPIError)):
        await nctx.session.execute(
            delete(Notification).where(Notification.id == notif.id)
        )
        await nctx.session.commit()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_user_deletion_restricted_when_notifications_or_devices_exist(
    nctx: NotificationTestContext,
) -> None:
    """Verifies ON DELETE RESTRICT prevents deleting a User with history."""
    user = await nctx.create_user()
    await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="User Alert",
        body="Body",
    )
    await nctx.session.commit()

    # Attempting to delete user with notification history fails
    with pytest.raises((IntegrityError, DBAPIError)):
        await nctx.session.execute(delete(User).where(User.id == user.id))
        await nctx.session.commit()

    await nctx.session.rollback()


@pytest.mark.asyncio
async def test_device_deactivation_preserves_delivery_records(
    nctx: NotificationTestContext,
) -> None:
    """Verifies device deactivation preserves delivery records and device history."""
    user = await nctx.create_user()
    dev = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="deactivate_preserves_dev",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    notif = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Preserve Alert",
        body="Body",
    )
    await nctx.session.commit()

    tasks = await create_delivery_tasks(db=nctx.session, notification=notif)
    await nctx.session.commit()
    assert len(tasks) == 1
    delivery_id = tasks[0].id

    # Deactivate device on logout
    deactivated = await deactivate_device(
        db=nctx.session, user_id=user.id, device_id="deactivate_preserves_dev"
    )
    await nctx.session.commit()
    assert deactivated is True

    # Check delivery record is still present and valid
    deliv_check = await nctx.session.execute(
        select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
    )
    deliv = deliv_check.scalar_one_or_none()
    assert deliv is not None
    assert deliv.user_device_id == dev.id
    assert deliv.status == DeliveryStatus.PENDING

    # Check device is deactivated but not deleted
    dev_check = await nctx.session.execute(
        select(UserDevice).where(UserDevice.id == dev.id)
    )
    loaded_dev = dev_check.scalar_one_or_none()
    assert loaded_dev is not None
    assert loaded_dev.is_active is False


@pytest.mark.asyncio
async def test_explicit_account_deletion_policy(
    nctx: NotificationTestContext,
) -> None:
    """Verifies explicit ordered account deletion succeeds when child records
    are managed.
    """
    user = await nctx.create_user(name="User For Ordered Deletion")
    dev = await register_device(
        db=nctx.session,
        user_id=user.id,
        device_id="ordered_dev",
        fcm_token=f"token_{uuid.uuid4()}",
        platform=DevicePlatform.ANDROID,
    )
    pref = await get_or_create_preferences(db=nctx.session, user_id=user.id)
    notif = await create_notification(
        db=nctx.session,
        user_id=user.id,
        type=NotificationType.MATCH_DETECTED,
        title="Ordered Alert",
        body="Body",
    )
    await nctx.session.commit()

    tasks = await create_delivery_tasks(db=nctx.session, notification=notif)
    await nctx.session.commit()
    assert len(tasks) == 1
    delivery_id = tasks[0].id

    # Explicit child-to-parent deletion pipeline
    # 1. Purge delivery records
    await nctx.session.execute(
        delete(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id
        )
    )
    # 2. Purge notifications
    await nctx.session.execute(delete(Notification).where(Notification.id == notif.id))
    # 3. Purge user devices
    await nctx.session.execute(delete(UserDevice).where(UserDevice.id == dev.id))
    # 4. Delete user (NotificationPreference cascades)
    await nctx.session.execute(delete(User).where(User.id == user.id))
    await nctx.session.commit()

    # Verify all records removed cleanly
    n_check = await nctx.session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    assert n_check.scalar_one_or_none() is None

    d_check = await nctx.session.execute(
        select(UserDevice).where(UserDevice.id == dev.id)
    )
    assert d_check.scalar_one_or_none() is None

    p_check = await nctx.session.execute(
        select(NotificationPreference).where(NotificationPreference.id == pref.id)
    )
    assert p_check.scalar_one_or_none() is None

    deliv_check = await nctx.session.execute(
        select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
    )
    assert deliv_check.scalar_one_or_none() is None
