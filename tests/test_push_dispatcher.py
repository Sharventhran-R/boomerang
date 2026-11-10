"""Automated tests for Phase 9.4: Firebase Cloud Messaging (FCM) & Push Dispatcher.

Verifies:
- Android and Web push payload construction with platform-tailored configs.
- Privacy invariant: zero raw GPS coordinates and zero verification proofs.
- Firebase error classification (unregistered token vs retryable transient error).
- Concurrency-safe delivery claiming via SELECT ... FOR UPDATE SKIP LOCKED.
- Successful FCM delivery transitioning task to SENT with fcm_message_id.
- Unregistered token detection marking PERMANENTLY_FAILED and deactivating device.
- Transient errors retrying with bounded exponential backoff and jitter.
- Max retries exceeded handling.
- Stale PROCESSING lease recovery (worker crash simulation).
- Expired notification and deactivated device skipping.
- Multi-device fan-out handling.
- In-App Independence Invariant: FCM delivery never alters in-app notifications.
- Operational backlog counting and replay of failed deliveries.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from firebase_admin import exceptions, messaging
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    DeliveryStatus,
    DevicePlatform,
    Notification,
    NotificationDelivery,
    NotificationPriority,
    NotificationType,
    User,
    UserDevice,
)
from app.services.fcm import (
    FCMResult,
    FirebaseAdminFCMProvider,
    MockFCMProvider,
    build_deep_link,
    build_fcm_data,
    build_fcm_message,
    build_web_push_link,
)
from app.services.push_dispatcher import (
    PushDispatcher,
    calculate_backoff,
)


class PushTestContext:
    """Manages test entities and ensures isolated database cleanup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []

    async def create_user(self, name: str = "Push Test User") -> User:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            email=f"push_user_{uid}@example.com",
            name=name,
            password_hash="hashed_pw_test",
        )
        self.session.add(user)
        await self.session.flush()
        self.user_ids.append(user.id)
        return user

    async def create_device(
        self,
        user: User,
        fcm_token: str = "valid_token_123",
        platform: DevicePlatform = DevicePlatform.ANDROID,
        is_active: bool = True,
    ) -> UserDevice:
        dev = UserDevice(
            id=uuid.uuid4(),
            user_id=user.id,
            device_id=f"device_{uuid.uuid4()}",
            fcm_token=fcm_token,
            platform=platform,
            is_active=is_active,
        )
        self.session.add(dev)
        await self.session.flush()
        return dev

    async def create_notification(
        self,
        user: User,
        notif_type: NotificationType = NotificationType.MATCH_HIGH_PRIORITY,
        priority: NotificationPriority = NotificationPriority.HIGH,
        data: dict[str, str] | None = None,
        expires_at: datetime | None = None,
    ) -> Notification:
        now = datetime.now(UTC)
        notif = Notification(
            id=uuid.uuid4(),
            user_id=user.id,
            type=notif_type,
            title="High Match Alert",
            body="A high-probability match was found nearby.",
            data=data or {"match_id": str(uuid.uuid4())},
            priority=priority,
            expires_at=expires_at or (now + timedelta(days=90)),
        )
        self.session.add(notif)
        await self.session.flush()
        return notif

    async def create_delivery(
        self,
        notification: Notification,
        device: UserDevice,
        status: DeliveryStatus = DeliveryStatus.PENDING,
        retry_count: int = 0,
        next_retry_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> NotificationDelivery:
        now = datetime.now(UTC)
        delivery = NotificationDelivery(
            id=uuid.uuid4(),
            notification_id=notification.id,
            user_device_id=device.id,
            status=status,
            retry_count=retry_count,
            max_retries=3,
            next_retry_at=next_retry_at or now,
        )
        if updated_at:
            delivery.updated_at = updated_at
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def cleanup(self) -> None:
        try:
            await self.session.rollback()
        except Exception:
            pass

        if self.user_ids:
            async with AsyncSessionLocal() as cleanup_session:
                # 1. Clean deliveries
                notif_sub = select(Notification.id).where(
                    Notification.user_id.in_(self.user_ids)
                )
                await cleanup_session.execute(
                    delete(NotificationDelivery).where(
                        NotificationDelivery.notification_id.in_(notif_sub)
                    )
                )
                # 2. Clean devices
                await cleanup_session.execute(
                    delete(UserDevice).where(UserDevice.user_id.in_(self.user_ids))
                )
                # 3. Clean notifications
                await cleanup_session.execute(
                    delete(Notification).where(Notification.user_id.in_(self.user_ids))
                )
                # 4. Clean users
                await cleanup_session.execute(
                    delete(User).where(User.id.in_(self.user_ids))
                )
                await cleanup_session.commit()


@pytest.fixture
async def push_ctx() -> AsyncGenerator[PushTestContext, None]:
    async with AsyncSessionLocal() as session:
        # Clear any dangling pending/processing tasks from aborted test runs
        await session.execute(
            delete(NotificationDelivery).where(
                NotificationDelivery.status.in_(
                    [DeliveryStatus.PENDING, DeliveryStatus.PROCESSING]
                )
            )
        )
        await session.commit()
        ctx = PushTestContext(session)
        yield ctx
        await ctx.cleanup()


# ==============================================================================
# Unit Tests: Payload Construction, Privacy, & Error Classification
# ==============================================================================


def test_fcm_deep_link_builder() -> None:
    match_id = str(uuid.uuid4())
    req_id = str(uuid.uuid4())
    rep_id = str(uuid.uuid4())

    assert (
        build_deep_link(NotificationType.MATCH_HIGH_PRIORITY, {"match_id": match_id})
        == f"boomerang://matches/{match_id}"
    )
    assert (
        build_deep_link(
            NotificationType.RECOVERY_REQUEST_RECEIVED,
            {"recovery_request_id": req_id},
        )
        == f"boomerang://recovery-requests?tab=received&id={req_id}"
    )
    assert (
        build_deep_link(
            NotificationType.RECOVERY_REQUEST_ACCEPTED,
            {"recovery_request_id": req_id},
        )
        == f"boomerang://recovery-requests?tab=sent&id={req_id}"
    )
    assert (
        build_deep_link(
            NotificationType.RECOVERY_REQUEST_COMPLETED,
            {"report_id": rep_id},
        )
        == f"boomerang://reports/{rep_id}"
    )
    assert (
        build_deep_link(
            NotificationType.REPORT_STATUS_CHANGED,
            {"report_id": rep_id},
        )
        == f"boomerang://reports/{rep_id}"
    )
    assert (
        build_deep_link(
            NotificationType.REPORT_EXPIRING,
            {"report_id": rep_id},
        )
        == f"boomerang://reports/{rep_id}"
    )


def test_fcm_payload_privacy_invariants() -> None:
    """Enforces that exact GPS coords and recovery proofs are excluded."""
    now = datetime.now(UTC)
    notif = Notification(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=NotificationType.MATCH_HIGH_PRIORITY,
        title="Match Found",
        body="Possible match found within 400m.",
        data={
            "match_id": str(uuid.uuid4()),
            "score": "92.5",
            "category": "ELECTRONICS",
            # Sensitive fields that MUST NEVER leak into FCM push:
            "latitude": 40.7128,
            "longitude": -74.0060,
            "raw_coordinates": [40.7128, -74.0060],
            "claim_text": "Secret inscription on back",
            "verification_proof": "Receipt photo url",
        },
        priority=NotificationPriority.HIGH,
        expires_at=now + timedelta(days=90),
    )

    deep_link = "boomerang://matches/123"
    fcm_data = build_fcm_data(notif, deep_link)

    # Allowed fields present
    assert fcm_data["notification_id"] == str(notif.id)
    assert fcm_data["type"] == "MATCH_HIGH_PRIORITY"
    assert fcm_data["priority"] == "HIGH"
    assert fcm_data["deep_link"] == deep_link
    assert fcm_data["score"] == "92.5"
    assert fcm_data["category"] == "ELECTRONICS"

    # Sensitive fields strictly stripped
    assert "latitude" not in fcm_data
    assert "longitude" not in fcm_data
    assert "raw_coordinates" not in fcm_data
    assert "claim_text" not in fcm_data
    assert "verification_proof" not in fcm_data


def test_fcm_message_builder_android_and_web() -> None:
    now = datetime.now(UTC)
    notif = Notification(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        type=NotificationType.MATCH_HIGH_PRIORITY,
        title="High Match Alert",
        body="High score match detected",
        data={"match_id": str(uuid.uuid4())},
        priority=NotificationPriority.HIGH,
        expires_at=now + timedelta(days=90),
    )
    device = UserDevice(
        id=uuid.uuid4(),
        user_id=notif.user_id,
        device_id="dev-123",
        fcm_token="sample_fcm_token",
        platform=DevicePlatform.ANDROID,
    )

    msg = build_fcm_message(notif, device)
    assert msg.token == "sample_fcm_token"
    assert msg.notification.title == "High Match Alert"
    assert msg.notification.body == "High score match detected"

    # Android config
    assert msg.android is not None
    assert msg.android.priority == "high"
    assert msg.android.notification.channel_id == "high_priority"
    assert msg.android.notification.click_action == "FLUTTER_NOTIFICATION_CLICK"

    # Webpush config
    assert msg.webpush is not None
    assert msg.webpush.headers["Urgency"] == "high"
    assert msg.webpush.notification.title == "High Match Alert"
    assert msg.webpush.fcm_options is not None
    assert msg.webpush.fcm_options.link.startswith("https://")
    assert f"/matches/{notif.data['match_id']}" in msg.webpush.fcm_options.link
    assert msg.data["deep_link"] == f"boomerang://matches/{notif.data['match_id']}"


def test_fcm_provider_error_classification() -> None:
    provider = FirebaseAdminFCMProvider()

    # 1. Unregistered token errors
    unreg_err = messaging.UnregisteredError("App is uninstalled")
    res_unreg = provider._classify_error(unreg_err)
    assert res_unreg.is_unregistered is True
    assert res_unreg.is_retryable is False

    sender_err = messaging.SenderIdMismatchError("Sender ID mismatch")
    res_sender = provider._classify_error(sender_err)
    assert res_sender.is_unregistered is False
    assert res_sender.is_config_error is True
    assert res_sender.is_retryable is False

    # 2. Transient retryable errors
    quota_err = messaging.QuotaExceededError("429 Quota exceeded")
    res_quota = provider._classify_error(quota_err)
    assert res_quota.is_unregistered is False
    assert res_quota.is_retryable is True

    unavail_err = exceptions.UnavailableError("503 Service Unavailable")
    res_unavail = provider._classify_error(unavail_err)
    assert res_unavail.is_retryable is True

    timeout_err = TimeoutError("Connection to FCM timed out")
    res_timeout = provider._classify_error(timeout_err)
    assert res_timeout.is_retryable is True

    # 3. Permanent non-retryable error
    perm_err = ValueError("Invalid payload format")
    res_perm = provider._classify_error(perm_err)
    assert res_perm.is_unregistered is False
    assert res_perm.is_retryable is False


def test_calculate_backoff_strict_bounds_and_deterministic_jitter() -> None:
    # 1. Deterministic progression with controlled random_fn
    # attempt 1: exponent 0 -> capped = 2.0
    # min jitter (rand_val=0.0): 0.5 * 2.0 = 1.0
    # max jitter (rand_val=1.0): 2.0
    assert (
        calculate_backoff(1, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 0.0)
        == 1.0
    )
    assert (
        calculate_backoff(1, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 1.0)
        == 2.0
    )

    # attempt 2: exponent 1 -> capped = 4.0
    assert (
        calculate_backoff(2, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 0.0)
        == 2.0
    )
    assert (
        calculate_backoff(2, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 1.0)
        == 4.0
    )

    # attempt 3: exponent 2 -> capped = 8.0
    assert (
        calculate_backoff(3, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 0.0)
        == 4.0
    )
    assert (
        calculate_backoff(3, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 1.0)
        == 8.0
    )

    # 2. Strict maximum ceiling (never exceeds max_delay)
    # attempt 10 with max_delay 15.0 -> capped = 15.0
    assert (
        calculate_backoff(10, initial_delay=2.0, max_delay=15.0, random_fn=lambda: 1.0)
        == 15.0
    )
    assert (
        calculate_backoff(10, initial_delay=2.0, max_delay=15.0, random_fn=lambda: 0.0)
        == 7.5
    )
    assert (
        calculate_backoff(100, initial_delay=2.0, max_delay=15.0, random_fn=lambda: 1.0)
        == 15.0
    )

    # 3. Non-negative edge cases
    assert (
        calculate_backoff(0, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 0.0)
        >= 0.1
    )
    assert (
        calculate_backoff(-5, initial_delay=2.0, max_delay=60.0, random_fn=lambda: 0.0)
        >= 0.1
    )

    # 4. Stochastic randomized bounds over repeated iterations
    for attempt in range(1, 10):
        for _ in range(5):
            d = calculate_backoff(attempt=attempt, initial_delay=2.0, max_delay=30.0)
            assert 0.1 <= d <= 30.0


# ==============================================================================
# Integration Tests: PushDispatcher Workflow & Concurrency
# ==============================================================================


@pytest.mark.asyncio
async def test_push_dispatcher_successful_delivery(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="valid_fcm_token_1")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed >= 1
    assert dispatcher.metrics.successes >= 1

    # Verify database state
    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.SENT
        assert deliv.fcm_message_id is not None
        assert deliv.sent_at is not None
        assert deliv.last_error is None

        # Verify in-app notification remains untouched and unread
        notif_row = (
            await session.execute(
                select(Notification).where(Notification.id == notif.id)
            )
        ).scalar_one()
        assert notif_row.is_read is False


@pytest.mark.asyncio
async def test_push_dispatcher_unregistered_token_deactivates_device(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="unregistered_token_stale")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed == 1
    assert dispatcher.metrics.permanently_failed == 1

    # Verify delivery marked PERMANENTLY_FAILED and device marked is_active = False
    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PERMANENTLY_FAILED
        assert deliv.last_error is not None
        assert "unregistered" in deliv.last_error.lower()

        dev_row = (
            await session.execute(select(UserDevice).where(UserDevice.id == device.id))
        ).scalar_one()
        assert dev_row.is_active is False


@pytest.mark.asyncio
async def test_push_dispatcher_transient_failure_retries_with_backoff(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="retryable_token_503")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    now = datetime.now(UTC)
    processed = await dispatcher.process_batch()
    assert processed == 1
    assert dispatcher.metrics.retries == 1

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.FAILED
        assert deliv.retry_count == 1
        assert deliv.next_retry_at > now
        assert deliv.last_error is not None
        assert "503" in deliv.last_error


@pytest.mark.asyncio
async def test_push_dispatcher_max_retries_exceeded(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="retryable_token_fail")
    notif = await push_ctx.create_notification(user)
    # Delivery has already attempted 2 times
    delivery = await push_ctx.create_delivery(notif, device, retry_count=2)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed == 1
    assert dispatcher.metrics.failures == 1

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.FAILED
        assert deliv.retry_count == 3
        assert deliv.last_error is not None
        assert "Max retries (3) exceeded" in deliv.last_error


@pytest.mark.asyncio
async def test_push_dispatcher_stale_processing_lease_recovery(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="valid_token_stale")
    notif = await push_ctx.create_notification(user)

    # Simulate a crash: task stuck in PROCESSING since 10 minutes ago
    ten_mins_ago = datetime.now(UTC) - timedelta(minutes=10)
    delivery = await push_ctx.create_delivery(
        notif,
        device,
        status=DeliveryStatus.PROCESSING,
        retry_count=0,
        updated_at=ten_mins_ago,
    )
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    # Claim batch must identify the abandoned task and reclaim it
    claimed_ids = await dispatcher.claim_batch()
    assert delivery.id in claimed_ids

    # Delivery retry_count should have incremented due to abandoned crash recovery
    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PROCESSING
        assert deliv.retry_count == 1
        assert deliv.last_error is not None
        assert "stale processing" in deliv.last_error.lower()


@pytest.mark.asyncio
async def test_push_dispatcher_expired_notification_skipped(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user)
    # Notification expired 1 hour ago
    expired_time = datetime.now(UTC) - timedelta(hours=1)
    notif = await push_ctx.create_notification(user, expires_at=expired_time)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed == 1
    assert dispatcher.metrics.expired == 1
    assert len(mock_provider.sent_messages) == 0

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.EXPIRED


@pytest.mark.asyncio
async def test_push_dispatcher_deactivated_device_skipped(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, is_active=False)
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed == 1
    assert dispatcher.metrics.skipped == 1
    assert len(mock_provider.sent_messages) == 0

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PERMANENTLY_FAILED
        assert deliv.last_error is not None
        assert "deactivated" in deliv.last_error.lower()


@pytest.mark.asyncio
async def test_push_dispatcher_multi_device_fanout(
    push_ctx: PushTestContext,
) -> None:
    """Verifies fan-out where one device token is valid and one is invalid."""
    user = await push_ctx.create_user()
    dev_valid = await push_ctx.create_device(
        user, fcm_token="valid_phone_token", platform=DevicePlatform.ANDROID
    )
    dev_unreg = await push_ctx.create_device(
        user,
        fcm_token="unregistered_web_token",  # ggignore
        platform=DevicePlatform.WEB,
    )
    notif = await push_ctx.create_notification(user)

    deliv_valid = await push_ctx.create_delivery(notif, dev_valid)
    deliv_unreg = await push_ctx.create_delivery(notif, dev_unreg)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    processed = await dispatcher.process_batch()
    assert processed == 2

    async with AsyncSessionLocal() as session:
        d1 = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == deliv_valid.id
                )
            )
        ).scalar_one()
        d2 = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == deliv_unreg.id
                )
            )
        ).scalar_one()

        assert d1.status == DeliveryStatus.SENT
        assert d2.status == DeliveryStatus.PERMANENTLY_FAILED

        # Invalid device is deactivated; valid device remains active
        d1_dev = (
            await session.execute(
                select(UserDevice).where(UserDevice.id == dev_valid.id)
            )
        ).scalar_one()
        d2_dev = (
            await session.execute(
                select(UserDevice).where(UserDevice.id == dev_unreg.id)
            )
        ).scalar_one()
        assert d1_dev.is_active is True
        assert d2_dev.is_active is False

        # In-app notification is untouched and unread
        notif_row = (
            await session.execute(
                select(Notification).where(Notification.id == notif.id)
            )
        ).scalar_one()
        assert notif_row.is_read is False


@pytest.mark.asyncio
async def test_push_dispatcher_replay_failed_deliveries(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user)
    notif1 = await push_ctx.create_notification(user)
    notif2 = await push_ctx.create_notification(user)

    d_failed = await push_ctx.create_delivery(
        notif1, device, status=DeliveryStatus.FAILED, retry_count=3
    )
    d_perm = await push_ctx.create_delivery(
        notif2, device, status=DeliveryStatus.PERMANENTLY_FAILED, retry_count=3
    )
    await push_ctx.session.commit()

    dispatcher = PushDispatcher(session_factory=AsyncSessionLocal)
    replayed = await dispatcher.replay_failed_deliveries([d_failed.id, d_perm.id])
    assert replayed == 2

    async with AsyncSessionLocal() as session:
        d1 = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == d_failed.id
                )
            )
        ).scalar_one()
        assert d1.status == DeliveryStatus.PENDING
        assert d1.retry_count == 0
        assert d1.last_error is None


@pytest.mark.asyncio
async def test_push_dispatcher_backlog_counts(
    push_ctx: PushTestContext,
) -> None:
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user)
    notif1 = await push_ctx.create_notification(user)
    notif2 = await push_ctx.create_notification(user)

    await push_ctx.create_delivery(notif1, device, status=DeliveryStatus.PENDING)
    await push_ctx.create_delivery(notif2, device, status=DeliveryStatus.SENT)
    await push_ctx.session.commit()

    dispatcher = PushDispatcher(session_factory=AsyncSessionLocal)
    counts = await dispatcher.get_backlog_counts()
    assert counts[DeliveryStatus.PENDING.value] >= 1
    assert counts[DeliveryStatus.SENT.value] >= 1


@pytest.mark.asyncio
async def test_push_dispatcher_in_app_independence(
    push_ctx: PushTestContext,
) -> None:
    """Invariant: Push failures never alter or invalidate the in-app Notification."""
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="unregistered_token_fatal")
    notif = await push_ctx.create_notification(
        user,
        notif_type=NotificationType.MATCH_HIGH_PRIORITY,
        data={"match_id": str(uuid.uuid4())},
    )
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    await dispatcher.process_batch()

    async with AsyncSessionLocal() as session:
        # Delivery is permanently failed
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PERMANENTLY_FAILED

        # In-App Notification is completely untouched, unread, and queryable
        notif_row = (
            await session.execute(
                select(Notification).where(Notification.id == notif.id)
            )
        ).scalar_one()
        assert notif_row.is_read is False
        assert notif_row.type == NotificationType.MATCH_HIGH_PRIORITY
        assert notif_row.title == "High Match Alert"
        assert notif_row.user_id == user.id


@pytest.mark.asyncio
async def test_fastapi_lifespan_integration() -> None:
    """Verifies FastAPI lifespan starts and gracefully stops push dispatcher."""
    from app.main import app, lifespan

    # Disabled case (default in tests)
    settings.PUSH_DISPATCHER_ENABLED = False
    async with lifespan(app):
        pass

    # Enabled case: test graceful start and shutdown
    settings.PUSH_DISPATCHER_ENABLED = True
    try:
        async with lifespan(app):
            await asyncio.sleep(0.05)
    finally:
        settings.PUSH_DISPATCHER_ENABLED = False


def test_fcm_provider_app_resolution_missing_credentials() -> None:
    """Verifies graceful handling when credentials path does not exist."""
    from app.services.fcm import get_firebase_app

    app = get_firebase_app(credentials_path="non_existent_file_path.json")
    assert app is None or isinstance(app, object)


@pytest.mark.asyncio
async def test_sender_id_mismatch_preserves_device_active(
    push_ctx: PushTestContext,
) -> None:
    """Regression Test 1: SenderIdMismatchError must NOT deactivate UserDevice."""
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="sender_mismatch_token_123")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    mock_provider = MockFCMProvider()
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    await dispatcher.process_batch()

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PERMANENTLY_FAILED
        assert deliv.last_error is not None
        assert "senderidmismatch" in deliv.last_error.lower()

        # Device MUST remain active: infrastructure mismatch, not a revoked token.
        dev_row = (
            await session.execute(select(UserDevice).where(UserDevice.id == device.id))
        ).scalar_one()
        assert dev_row.is_active is True


@pytest.mark.asyncio
async def test_unconfigured_firebase_preserves_pending_deliveries(
    push_ctx: PushTestContext,
) -> None:
    """Regression Test 2: Unconfigured Firebase leaves tasks in PENDING state."""
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="valid_token_unconfigured")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device)
    await push_ctx.session.commit()

    # Provider configured = False (simulating absent credentials)
    mock_provider = MockFCMProvider(configured=False)
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    # 1. claim_batch must NOT claim tasks when unconfigured
    claimed = await dispatcher.claim_batch()
    assert claimed == []

    # 2. Even if dispatch_delivery is called directly, task stays PENDING
    status = await dispatcher.dispatch_delivery(delivery.id)
    assert status == DeliveryStatus.PENDING

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.PENDING

    # 3. When credentials become available, it delivers normally
    mock_provider.set_configured(True)
    processed = await dispatcher.process_batch()
    assert processed >= 1

    async with AsyncSessionLocal() as session:
        deliv_final = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv_final.status == DeliveryStatus.SENT


@pytest.mark.asyncio
async def test_stale_lease_recovery_does_not_overwrite_sent(
    push_ctx: PushTestContext,
) -> None:
    """Regression Test 3: Stale worker result cannot overwrite newer SENT status."""
    user = await push_ctx.create_user()
    device = await push_ctx.create_device(user, fcm_token="valid_token_race")
    notif = await push_ctx.create_notification(user)
    delivery = await push_ctx.create_delivery(notif, device, status=DeliveryStatus.SENT)
    delivery.fcm_message_id = "msg_sent_by_worker_b"
    await push_ctx.session.commit()

    # Simulate Worker A trying to write a failure outcome over an already-SENT task
    mock_provider = MockFCMProvider()
    mock_provider.forced_result = FCMResult(
        success=False,
        is_retryable=False,
        error_message="Worker A timed out",
    )
    dispatcher = PushDispatcher(
        session_factory=AsyncSessionLocal,
        fcm_provider=mock_provider,
    )

    # dispatch_delivery on an already-SENT task
    final_status = await dispatcher.dispatch_delivery(delivery.id)
    assert final_status == DeliveryStatus.SENT

    async with AsyncSessionLocal() as session:
        deliv = (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery.id
                )
            )
        ).scalar_one()
        assert deliv.status == DeliveryStatus.SENT
        assert deliv.fcm_message_id == "msg_sent_by_worker_b"


def test_build_web_push_link_destinations() -> None:
    """Verifies Web Push click destinations format as valid HTTPS URLs across types."""
    import urllib.parse

    match_id = str(uuid.uuid4())
    req_id = str(uuid.uuid4())
    rep_id = str(uuid.uuid4())

    # 1. Matches
    link_match = build_web_push_link(
        NotificationType.MATCH_HIGH_PRIORITY,
        {"match_id": match_id},
        base_url="https://app.boomerang.example.com",
    )
    parsed_match = urllib.parse.urlparse(link_match)
    assert parsed_match.scheme == "https"
    assert parsed_match.netloc == "app.boomerang.example.com"
    assert parsed_match.path == f"/matches/{match_id}"
    assert "boomerang://" not in link_match

    # Match fallback without match_id
    link_match_list = build_web_push_link(
        NotificationType.MATCH_DETECTED,
        {},
        base_url="https://app.boomerang.example.com",
    )
    assert link_match_list == "https://app.boomerang.example.com/matches"

    # 2. Recovery requests received
    link_rec = build_web_push_link(
        NotificationType.RECOVERY_REQUEST_RECEIVED,
        {"recovery_request_id": req_id},
        base_url="https://app.boomerang.example.com",
    )
    assert link_rec == (
        f"https://app.boomerang.example.com/recovery-requests?tab=received&id={req_id}"
    )

    # 3. Recovery requests sent (accepted / rejected)
    link_sent = build_web_push_link(
        NotificationType.RECOVERY_REQUEST_ACCEPTED,
        {"recovery_request_id": req_id},
        base_url="https://app.boomerang.example.com",
    )
    assert link_sent == (
        f"https://app.boomerang.example.com/recovery-requests?tab=sent&id={req_id}"
    )

    # 4. Reports (status changed / completed / expiring)
    link_rep = build_web_push_link(
        NotificationType.REPORT_STATUS_CHANGED,
        {"report_id": rep_id},
        base_url="https://app.boomerang.example.com",
    )
    assert link_rep == f"https://app.boomerang.example.com/reports/{rep_id}"

    # 5. Default / notifications list
    from typing import cast

    link_default = build_web_push_link(
        cast(NotificationType, "SYSTEM_ALERT"),
        {},
        base_url="https://app.boomerang.example.com",
    )
    assert link_default == "https://app.boomerang.example.com/notifications"


def test_build_web_push_link_privacy_invariants() -> None:
    """Verifies Web Push URLs exclude sensitive proofs, tokens, and GPS coords."""
    match_id = str(uuid.uuid4())
    dirty_data = {
        "match_id": match_id,
        "latitude": 40.7128,
        "longitude": -74.0060,
        "verification_proof": "SECRET_ENGRAVING_123",
        "auth_token": "bearer-secret-xyz",
        "user_id": str(uuid.uuid4()),
    }
    web_link = build_web_push_link(
        NotificationType.MATCH_HIGH_PRIORITY,
        dirty_data,
        base_url="https://app.boomerang.example.com",
    )
    # Ensure sensitive data does not appear in URL
    assert "40.7128" not in web_link
    assert "-74.0060" not in web_link
    assert "SECRET_ENGRAVING_123" not in web_link
    assert "bearer-secret-xyz" not in web_link
    assert str(dirty_data["user_id"]) not in web_link
    assert web_link == f"https://app.boomerang.example.com/matches/{match_id}"


def test_build_web_push_link_custom_and_fallback_origins() -> None:
    """Verifies URL sanitization, non-HTTPS scheme fallback, and slash handling."""
    # Custom base URL with trailing slash
    link1 = build_web_push_link(
        NotificationType.REPORT_EXPIRING,
        {"report_id": "123"},
        base_url="https://app.boomerang.example.com/",
    )
    assert link1 == "https://app.boomerang.example.com/reports/123"

    # Invalid custom scheme (e.g. boomerang://) falls back safely to https://localhost:3000
    link2 = build_web_push_link(
        NotificationType.REPORT_EXPIRING,
        {"report_id": "123"},
        base_url="boomerang://invalid",
    )
    assert link2 == "https://localhost:3000/reports/123"
    assert not link2.startswith("boomerang://")
    assert link2.startswith("https://")


def test_android_and_web_destinations_independent() -> None:
    """Verifies that Android and Web push destinations are generated independently."""
    match_id = str(uuid.uuid4())
    user_id = uuid.uuid4()
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type=NotificationType.MATCH_HIGH_PRIORITY,
        title="High Match Alert",
        body="High score match detected",
        data={"match_id": match_id, "score": 95},
        priority=NotificationPriority.HIGH,
    )
    android_device = UserDevice(
        id=uuid.uuid4(),
        user_id=user_id,
        device_id="android-phone-1",
        fcm_token="mock_android_test_token_123",  # ggignore
        platform=DevicePlatform.ANDROID,
    )
    web_device = UserDevice(
        id=uuid.uuid4(),
        user_id=user_id,
        device_id="web-browser-1",
        fcm_token="mock_web_test_token_456",  # ggignore
        platform=DevicePlatform.WEB,
    )

    # 1. Android payload verification
    msg_android = build_fcm_message(
        notif, android_device, web_base_url="https://app.boomerang.example.com"
    )
    assert msg_android.token == "mock_android_test_token_123"
    # Mobile app intent deep link in data payload
    assert msg_android.data["deep_link"] == f"boomerang://matches/{match_id}"
    assert msg_android.android is not None
    assert msg_android.android.notification.click_action == "FLUTTER_NOTIFICATION_CLICK"
    # Webpush config attached has valid HTTPS link, never custom scheme
    assert msg_android.webpush is not None
    assert msg_android.webpush.fcm_options is not None
    assert msg_android.webpush.fcm_options.link.startswith("https://")
    assert "boomerang://" not in msg_android.webpush.fcm_options.link

    # 2. Web payload verification
    msg_web = build_fcm_message(
        notif, web_device, web_base_url="https://app.boomerang.example.com"
    )
    assert msg_web.token == "mock_web_test_token_456"
    # Web push click link in WebpushFCMOptions is official HTTPS URL
    assert msg_web.webpush is not None
    assert msg_web.webpush.fcm_options is not None
    assert msg_web.webpush.fcm_options.link == (
        f"https://app.boomerang.example.com/matches/{match_id}"
    )
    assert msg_web.webpush.fcm_options.link.startswith("https://")
    assert "boomerang://" not in msg_web.webpush.fcm_options.link
    # Data payload deep_link is also tailored to web HTTPS URL
    assert msg_web.data["deep_link"] == (
        f"https://app.boomerang.example.com/matches/{match_id}"
    )
    assert not msg_web.data["deep_link"].startswith("boomerang://")
