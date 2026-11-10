"""Asynchronous Push Notification Dispatcher for Firebase Cloud Messaging (FCM).

Guarantees reliable, at-least-once push delivery by claiming committed delivery tasks
with SELECT ... FOR UPDATE SKIP LOCKED, releasing database transactions before
initiating external network calls to FCM HTTP/v1, and persisting status with
bounded exponential backoff and jitter.

Enforces In-App Independence: Network errors, rate limits, and token invalidations
never alter, roll back, or invalidate authoritative in-app notification records.

At-Least-Once Delivery Semantics & Process Crash Limitation:
Mobile push delivery across external gateways (FCM/APNs) operates under at-least-once
semantics. If the dispatcher successfully delivers a push message to FCM but terminates
abruptly before committing DeliveryStatus.SENT to PostgreSQL, the delivery lease will
remain in PROCESSING until reclaimed by another worker after the stale timeout (300s).
Duplicate push messages in this rare crash edge-case are an unavoidable property of
distributed push networks without distributed transaction coordination (2PC).
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    DeliveryStatus,
    NotificationDelivery,
    UserDevice,
)
from app.services.fcm import FCMProvider, FirebaseAdminFCMProvider

logger = logging.getLogger(__name__)


def calculate_backoff(
    attempt: int,
    initial_delay: float = 2.0,
    max_delay: float = 300.0,
    multiplier: float = 2.0,
    random_fn: Callable[[], float] | None = None,
) -> float:
    """Calculates exponential backoff with bounded full jitter in seconds.

    Guarantees:
    - Strictly bounded: min(0.1, initial_delay) <= delay <= max_delay.
    - Zero probability of negative delay (attempt < 1 clamped to 0 exponent).
    - Deterministic verification supported via optional random_fn.
    """
    if max_delay <= 0:
        raise ValueError("max_delay must be positive")
    if initial_delay <= 0:
        raise ValueError("initial_delay must be positive")
    if multiplier < 1.0:
        raise ValueError("multiplier must be >= 1.0")

    exponent = max(0, attempt - 1)
    capped_delay = min(max_delay, initial_delay * (multiplier**exponent))

    rand_val = random_fn() if random_fn is not None else random.random()
    rand_val = max(0.0, min(1.0, rand_val))
    jittered = 0.5 * capped_delay + (0.5 * capped_delay * rand_val)

    clamped = max(min(0.1, initial_delay), min(max_delay, jittered))
    return round(clamped, 3)


@dataclass
class PushDispatcherMetrics:
    """Cumulative counters for push delivery operations."""

    attempts: int = 0
    successes: int = 0
    retries: int = 0
    failures: int = 0
    permanently_failed: int = 0
    expired: int = 0
    skipped: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "retries": self.retries,
            "failures": self.failures,
            "permanently_failed": self.permanently_failed,
            "expired": self.expired,
            "skipped": self.skipped,
        }


class PushDispatcher:
    """Worker engine that claims, delivers, and retries pending push tasks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        fcm_provider: FCMProvider | None = None,
    ) -> None:
        self.session_factory = session_factory or AsyncSessionLocal
        self.fcm_provider = fcm_provider or FirebaseAdminFCMProvider()
        self.metrics = PushDispatcherMetrics()
        self._running = False

    async def claim_batch(self, batch_size: int | None = None) -> list[uuid.UUID]:
        """Claims eligible delivery tasks using SELECT ... FOR UPDATE SKIP LOCKED.

        Keeps database locks short: transitions claimed rows to PROCESSING and commits
        immediately, releasing table row locks before FCM network dispatch begins.
        """
        # If FCM provider lacks credentials, defer tasks so they remain PENDING
        if not self.fcm_provider.is_configured():
            logger.warning(
                "PushDispatcher cannot claim tasks: FCM provider is unconfigured. "
                "Pending deliveries remain preserved in database."
            )
            return []

        limit = batch_size or settings.PUSH_DISPATCHER_BATCH_SIZE
        now = datetime.now(UTC)
        stale_cutoff = now - timedelta(
            seconds=settings.PUSH_DISPATCHER_STALE_PROCESSING_SECONDS
        )

        async with self.session_factory() as session:
            # Query eligible deliveries:
            # 1. PENDING deliveries whose next_retry_at is <= now
            # 2. FAILED deliveries eligible for retry whose next_retry_at is <= now
            # 3. PROCESSING deliveries past stale lease timeout (crash recovery)
            stmt = (
                select(NotificationDelivery)
                .where(
                    or_(
                        (
                            (NotificationDelivery.status == DeliveryStatus.PENDING)
                            & (NotificationDelivery.next_retry_at <= now)
                        ),
                        (
                            (NotificationDelivery.status == DeliveryStatus.FAILED)
                            & (
                                NotificationDelivery.retry_count
                                < NotificationDelivery.max_retries
                            )
                            & (NotificationDelivery.next_retry_at <= now)
                        ),
                        (
                            (NotificationDelivery.status == DeliveryStatus.PROCESSING)
                            & (NotificationDelivery.updated_at <= stale_cutoff)
                        ),
                    )
                )
                .order_by(NotificationDelivery.next_retry_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(stmt)
            claimed = list(result.scalars().all())

            if not claimed:
                return []

            claimed_ids: list[uuid.UUID] = []
            for delivery in claimed:
                if delivery.status == DeliveryStatus.PROCESSING:
                    # Worker crashed or lease expired during previous dispatch
                    delivery.retry_count += 1
                    delivery.last_error = (
                        f"Reclaimed after stale processing timeout "
                        f"({settings.PUSH_DISPATCHER_STALE_PROCESSING_SECONDS}s)"
                    )
                    if delivery.retry_count >= delivery.max_retries:
                        delivery.status = DeliveryStatus.PERMANENTLY_FAILED
                        delivery.updated_at = now
                        self.metrics.permanently_failed += 1
                        logger.error(
                            "Stale push delivery %s exceeded max retries (%d). "
                            "Marked PERMANENTLY_FAILED.",
                            delivery.id,
                            delivery.retry_count,
                        )
                        continue

                delivery.status = DeliveryStatus.PROCESSING
                delivery.updated_at = now
                claimed_ids.append(delivery.id)

            await session.commit()
            return claimed_ids

    async def dispatch_delivery(self, delivery_id: uuid.UUID) -> DeliveryStatus | None:
        """Dispatches a single claimed push delivery task to FCM.

        Network call to FCM occurs completely outside the database transaction.
        """
        now = datetime.now(UTC)

        # 1. Load delivery context (notification + device) in short read transaction
        async with self.session_factory() as session:
            stmt = (
                select(NotificationDelivery)
                .options(
                    joinedload(NotificationDelivery.notification),
                    joinedload(NotificationDelivery.device),
                )
                .where(NotificationDelivery.id == delivery_id)
            )
            res = await session.execute(stmt)
            delivery = res.scalar_one_or_none()
            if not delivery:
                return None

            notification = delivery.notification
            device = delivery.device

            # Check if device was deactivated before dispatch
            if not device.is_active:
                delivery.status = DeliveryStatus.PERMANENTLY_FAILED
                delivery.last_error = "Device was deactivated prior to push delivery"
                delivery.updated_at = now
                await session.commit()
                self.metrics.skipped += 1
                return DeliveryStatus.PERMANENTLY_FAILED

            # Check if parent notification has expired
            if notification.expires_at <= now:
                delivery.status = DeliveryStatus.EXPIRED
                delivery.last_error = "Notification expired before push delivery"
                delivery.updated_at = now
                await session.commit()
                self.metrics.expired += 1
                return DeliveryStatus.EXPIRED

        # Check if FCM provider is configured
        if not self.fcm_provider.is_configured():
            logger.warning(
                "FCM provider unconfigured; preserving delivery %s in PENDING state.",
                delivery_id,
            )
            async with self.session_factory() as session:
                deliv = await session.get(NotificationDelivery, delivery_id)
                if deliv and deliv.status == DeliveryStatus.PROCESSING:
                    deliv.status = DeliveryStatus.PENDING
                    deliv.last_error = (
                        "Firebase Admin SDK unconfigured. Delivery postponed."
                    )
                    deliv.updated_at = now
                    await session.commit()
            return DeliveryStatus.PENDING

        # 2. Execute FCM dispatch outside the database transaction
        self.metrics.attempts += 1
        result = await self.fcm_provider.send_message(notification, device)

        # 3. Persist delivery outcome in a short transaction
        async with self.session_factory() as session:
            stmt = (
                select(NotificationDelivery)
                .where(NotificationDelivery.id == delivery_id)
                .with_for_update()
            )
            delivery_record = (await session.execute(stmt)).scalar_one_or_none()
            if not delivery_record:
                return None

            # Race protection: if another worker completed the task (SENT / EXPIRED),
            # never overwrite terminal state!
            if delivery_record.status in (
                DeliveryStatus.SENT,
                DeliveryStatus.EXPIRED,
            ):
                logger.info(
                    "Push delivery %s is already terminal (%s); skipping overwrite.",
                    delivery_record.id,
                    delivery_record.status,
                )
                return delivery_record.status

            commit_now = datetime.now(UTC)
            delivery_record.updated_at = commit_now

            if result.success:
                delivery_record.status = DeliveryStatus.SENT
                delivery_record.fcm_message_id = result.message_id
                delivery_record.sent_at = commit_now
                delivery_record.last_error = None
                self.metrics.successes += 1
                logger.info(
                    "Push delivery %s SENT via FCM (message_id=%s)",
                    delivery_record.id,
                    result.message_id,
                )
                await session.commit()
                return DeliveryStatus.SENT

            elif result.is_unregistered:
                # Device token is expired or app uninstalled
                delivery_record.status = DeliveryStatus.PERMANENTLY_FAILED
                delivery_record.last_error = (
                    f"Device token unregistered: {result.error_message}"
                )
                self.metrics.permanently_failed += 1

                # Deactivate the device token so no further tasks are queued
                dev_stmt = select(UserDevice).where(UserDevice.id == device.id)
                target_device = (await session.execute(dev_stmt)).scalar_one_or_none()
                if target_device:
                    target_device.is_active = False
                    target_device.updated_at = commit_now
                    logger.warning(
                        "Deactivated device %s (user %s): unregistered FCM token",
                        device.id,
                        device.user_id,
                    )

                await session.commit()
                return DeliveryStatus.PERMANENTLY_FAILED

            elif result.is_config_error:
                # Infrastructure / Project misconfiguration (e.g. SenderIdMismatchError)
                # DO NOT deactivate the device token!
                delivery_record.status = DeliveryStatus.PERMANENTLY_FAILED
                delivery_record.last_error = (
                    f"FCM configuration error: {result.error_message}"
                )
                self.metrics.permanently_failed += 1
                logger.error(
                    "Delivery %s configuration error: %s. Device %s preserved active.",
                    delivery_record.id,
                    result.error_message,
                    device.id,
                )
                await session.commit()
                return DeliveryStatus.PERMANENTLY_FAILED

            elif result.is_retryable:
                delivery_record.retry_count += 1
                if delivery_record.retry_count >= delivery_record.max_retries:
                    delivery_record.status = DeliveryStatus.FAILED
                    delivery_record.last_error = (
                        f"Max retries ({delivery_record.max_retries}) exceeded: "
                        f"{result.error_message}"
                    )
                    self.metrics.failures += 1
                    logger.error(
                        "Push delivery %s exceeded max retries (%d). Marked FAILED: %s",
                        delivery_record.id,
                        delivery_record.retry_count,
                        delivery_record.last_error,
                    )
                else:
                    delivery_record.status = DeliveryStatus.FAILED
                    self.metrics.retries += 1
                    delay = calculate_backoff(
                        attempt=delivery_record.retry_count,
                        initial_delay=settings.PUSH_DISPATCHER_INITIAL_RETRY_DELAY_SECONDS,
                        max_delay=settings.PUSH_DISPATCHER_MAX_RETRY_DELAY_SECONDS,
                        multiplier=settings.PUSH_DISPATCHER_BACKOFF_MULTIPLIER,
                    )
                    delivery_record.next_retry_at = commit_now + timedelta(
                        seconds=delay
                    )
                    delivery_record.last_error = result.error_message
                    logger.warning(
                        "Push delivery %s transient failure (attempt %d/%d), "
                        "retry in %.2fs: %s",
                        delivery_record.id,
                        delivery_record.retry_count,
                        delivery_record.max_retries,
                        delay,
                        result.error_message,
                    )

                await session.commit()
                return delivery_record.status

            else:
                # Permanent non-retryable error
                delivery_record.status = DeliveryStatus.PERMANENTLY_FAILED
                delivery_record.last_error = (
                    f"Non-retryable FCM error: {result.error_message}"
                )
                self.metrics.permanently_failed += 1
                logger.error(
                    "Push delivery %s PERMANENTLY_FAILED: %s",
                    delivery_record.id,
                    delivery_record.last_error,
                )
                await session.commit()
                return DeliveryStatus.PERMANENTLY_FAILED

    async def process_batch(self, batch_size: int | None = None) -> int:
        """Claims and dispatches a single batch of eligible delivery tasks.

        Returns the number of tasks claimed and processed.
        """
        claimed_ids = await self.claim_batch(batch_size=batch_size)
        if not claimed_ids:
            return 0

        for delivery_id in claimed_ids:
            try:
                await self.dispatch_delivery(delivery_id)
            except Exception as exc:
                logger.exception(
                    "Unhandled exception during push dispatch of %s: %s",
                    delivery_id,
                    exc,
                )

        return len(claimed_ids)

    async def get_backlog_counts(self) -> dict[str, int]:
        """Returns row counts grouped by DeliveryStatus for operations monitoring."""
        async with self.session_factory() as session:
            stmt = select(
                NotificationDelivery.status,
                func.count(NotificationDelivery.id),
            ).group_by(NotificationDelivery.status)
            result = await session.execute(stmt)
            counts = {status.value: 0 for status in DeliveryStatus}
            for row in result.all():
                status_val, count = row[0], row[1]
                counts[status_val] = count
            return counts

    async def replay_failed_deliveries(
        self, delivery_ids: list[uuid.UUID] | None = None
    ) -> int:
        """Re-enqueues failed or permanently failed deliveries for manual retry."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            query = select(NotificationDelivery).where(
                NotificationDelivery.status.in_(
                    [DeliveryStatus.FAILED, DeliveryStatus.PERMANENTLY_FAILED]
                )
            )
            if delivery_ids:
                query = query.where(NotificationDelivery.id.in_(delivery_ids))

            result = await session.execute(query)
            deliveries = list(result.scalars().all())

            for d in deliveries:
                d.status = DeliveryStatus.PENDING
                d.retry_count = 0
                d.next_retry_at = now
                d.last_error = None
                d.updated_at = now

            await session.commit()
            return len(deliveries)

    async def run_loop(
        self,
        poll_interval: float | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuous execution loop polling for and dispatching push deliveries."""
        interval = (
            poll_interval
            if poll_interval is not None
            else settings.PUSH_DISPATCHER_POLL_INTERVAL_SECONDS
        )
        self._running = True
        logger.info(
            "PushDispatcher loop started (poll_interval=%.2fs)...",
            interval,
        )

        try:
            while self._running:
                if stop_event and stop_event.is_set():
                    break

                try:
                    processed = await self.process_batch()
                    if processed == 0:
                        if stop_event:
                            try:
                                await asyncio.wait_for(
                                    stop_event.wait(), timeout=interval
                                )
                                break
                            except TimeoutError:
                                pass
                        else:
                            await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("Unexpected error in push dispatcher loop: %s", exc)
                    if stop_event:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=interval)
                            break
                        except TimeoutError:
                            pass
                    else:
                        await asyncio.sleep(interval)
        finally:
            self._running = False
            logger.info("PushDispatcher loop exited.")
