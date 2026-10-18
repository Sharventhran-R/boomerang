"""Transactional Outbox Dispatcher for reliable Kafka event publishing.

Guarantees at-least-once delivery by claiming committed outbox rows with
SELECT ... FOR UPDATE SKIP LOCKED, publishing to Kafka outside database
transactions, and recording success or bounded backoff retry status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aiokafka import AIOKafkaProducer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)


def calculate_backoff(
    attempt: int,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
) -> float:
    """Calculates exponential backoff with full jitter in seconds."""
    exponent = max(0, attempt - 1)
    raw_delay = min(max_delay, initial_delay * (multiplier**exponent))
    jittered = random.uniform(0.5 * raw_delay, raw_delay)
    return max(0.1, round(jittered, 3))


@dataclass
class DispatcherMetrics:
    """Cumulative counters for outbox dispatcher operations."""

    attempts: int = 0
    successes: int = 0
    failures: int = 0
    dead_letters: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "dead_letters": self.dead_letters,
        }


class OutboxDispatcher:
    """Dispatcher worker that claims, publishes, and retries outbox events."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        producer: Any | None = None,
        bootstrap_servers: str | None = None,
    ) -> None:
        self.session_factory = session_factory or AsyncSessionLocal
        self.producer = producer
        self._owns_producer = producer is None
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self.metrics = DispatcherMetrics()
        self._running = False

    async def start(self) -> None:
        """Starts the underlying Kafka producer if managed internally."""
        if self._owns_producer and self.producer is None:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
            )
            await self.producer.start()
            logger.info(
                "OutboxDispatcher Kafka producer connected to %s",
                self.bootstrap_servers,
            )

    async def stop(self) -> None:
        """Stops the underlying Kafka producer if managed internally."""
        self._running = False
        if self._owns_producer and self.producer is not None:
            await self.producer.stop()
            self.producer = None
            logger.info("OutboxDispatcher Kafka producer stopped.")

    async def claim_batch(self, batch_size: int | None = None) -> list[OutboxEvent]:
        """Claims eligible outbox rows using SELECT ... FOR UPDATE SKIP LOCKED.

        Keeps database locks short: marks claimed rows as PROCESSING and commits
        immediately, releasing row locks before Kafka publishing begins.
        """
        limit = batch_size or settings.OUTBOX_BATCH_SIZE
        now = datetime.now(UTC)
        stale_cutoff = now - timedelta(seconds=settings.OUTBOX_STALE_PROCESSING_SECONDS)

        async with self.session_factory() as session:
            # Query eligible rows:
            # 1. PENDING or FAILED events eligible for retry
            # 2. PROCESSING events that exceeded stale timeout (worker crashed)
            stmt = (
                select(OutboxEvent)
                .where(
                    or_(
                        (
                            OutboxEvent.status.in_(
                                [OutboxStatus.PENDING, OutboxStatus.FAILED]
                            )
                            & (OutboxEvent.next_retry_at <= now)
                            & (OutboxEvent.retry_count < OutboxEvent.max_retries)
                        ),
                        (
                            (OutboxEvent.status == OutboxStatus.PROCESSING)
                            & (OutboxEvent.updated_at <= stale_cutoff)
                            & (OutboxEvent.retry_count < OutboxEvent.max_retries)
                        ),
                    )
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(stmt)
            claimed = list(result.scalars().all())

            if not claimed:
                return []

            active_claimed: list[OutboxEvent] = []
            for event in claimed:
                if event.status == OutboxStatus.PROCESSING:
                    # Worker interrupted or crashed during previous attempt
                    event.retry_count += 1
                    event.last_error = (
                        f"Reclaimed after stale processing timeout "
                        f"({settings.OUTBOX_STALE_PROCESSING_SECONDS}s)"
                    )
                    if event.retry_count >= event.max_retries:
                        event.status = OutboxStatus.DEAD_LETTER
                        event.updated_at = now
                        self.metrics.dead_letters += 1
                        logger.error(
                            "Stale outbox event %s exceeded max retries (%d). "
                            "Marked DEAD_LETTER.",
                            event.event_id,
                            event.retry_count,
                        )
                        continue

                event.status = OutboxStatus.PROCESSING
                event.updated_at = now
                active_claimed.append(event)

            await session.commit()
            return active_claimed

    async def publish_event(self, event: OutboxEvent) -> None:
        """Publishes serialized event envelope to Kafka, keyed by aggregate_id."""
        if self.producer is None:
            raise RuntimeError("Kafka producer is not initialized")

        key = str(event.aggregate_id).encode("utf-8")
        value = json.dumps(event.payload).encode("utf-8")

        await self.producer.send_and_wait(
            event.topic,
            value,
            key=key,
        )

    async def record_success(self, outbox_id: uuid.UUID) -> None:
        """Marks an outbox event as PUBLISHED in a short transaction."""
        async with self.session_factory() as session:
            event = await session.get(OutboxEvent, outbox_id)
            if event:
                event.status = OutboxStatus.PUBLISHED
                event.published_at = datetime.now(UTC)
                event.last_error = None
                await session.commit()
                self.metrics.successes += 1

    async def record_failure(self, outbox_id: uuid.UUID, error: Exception) -> None:
        """Records an attempt failure, scheduling retry or marking DEAD_LETTER."""
        now = datetime.now(UTC)
        error_msg = f"{type(error).__name__}: {error}"[:1000]

        async with self.session_factory() as session:
            event = await session.get(OutboxEvent, outbox_id)
            if not event:
                return

            event.retry_count += 1
            event.last_error = error_msg
            event.updated_at = now

            if event.retry_count >= event.max_retries:
                event.status = OutboxStatus.DEAD_LETTER
                self.metrics.dead_letters += 1
                logger.error(
                    "Outbox event %s exceeded max retries (%d). Marked DEAD_LETTER: %s",
                    event.event_id,
                    event.retry_count,
                    error_msg,
                )
            else:
                event.status = OutboxStatus.FAILED
                self.metrics.failures += 1
                delay = calculate_backoff(
                    attempt=event.retry_count,
                    initial_delay=settings.OUTBOX_INITIAL_RETRY_DELAY_SECONDS,
                    max_delay=settings.OUTBOX_MAX_RETRY_DELAY_SECONDS,
                    multiplier=settings.OUTBOX_BACKOFF_MULTIPLIER,
                )
                event.next_retry_at = now + timedelta(seconds=delay)
                logger.warning(
                    "Outbox event %s failed (attempt %d/%d), retry in %.2fs: %s",
                    event.event_id,
                    event.retry_count,
                    event.max_retries,
                    delay,
                    error_msg,
                )

            await session.commit()

    async def process_batch(self, batch_size: int | None = None) -> int:
        """Claims and processes a single batch of eligible outbox events.

        Returns number of events claimed and processed.
        """
        claimed = await self.claim_batch(batch_size=batch_size)
        if not claimed:
            return 0

        for event in claimed:
            self.metrics.attempts += 1
            try:
                await self.publish_event(event)
                await self.record_success(event.id)
            except Exception as exc:
                logger.warning(
                    "Failed to publish outbox event %s: %s",
                    event.event_id,
                    exc,
                )
                await self.record_failure(event.id, exc)

        return len(claimed)

    async def get_backlog_counts(self) -> dict[str, int]:
        """Returns row counts grouped by OutboxStatus for operational inspection."""
        async with self.session_factory() as session:
            stmt = select(OutboxEvent.status, func.count(OutboxEvent.id)).group_by(
                OutboxEvent.status
            )
            result = await session.execute(stmt)
            counts = {status.value: 0 for status in OutboxStatus}
            for row in result.all():
                status_val, count = row[0], row[1]
                counts[status_val] = count
            return counts

    async def replay_dead_letter_events(
        self, event_ids: list[uuid.UUID] | None = None
    ) -> int:
        """Re-enqueues poison/dead-letter events for retry after manual remediation.

        Resets status to PENDING, retry_count to 0, and next_retry_at to now.
        Returns number of re-enqueued events.
        """
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            query = select(OutboxEvent).where(
                OutboxEvent.status == OutboxStatus.DEAD_LETTER
            )
            if event_ids:
                query = query.where(OutboxEvent.event_id.in_(event_ids))

            result = await session.execute(query)
            dead_letters = list(result.scalars().all())

            for event in dead_letters:
                event.status = OutboxStatus.PENDING
                event.retry_count = 0
                event.next_retry_at = now
                event.last_error = None
                event.updated_at = now

            await session.commit()
            return len(dead_letters)

    async def run_loop(
        self,
        poll_interval: float | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuous execution loop polling for and dispatching outbox rows."""
        interval = (
            poll_interval
            if poll_interval is not None
            else settings.OUTBOX_POLL_INTERVAL_SECONDS
        )
        self._running = True
        logger.info(
            "OutboxDispatcher loop started (poll_interval=%.2fs)...",
            interval,
        )

        await self.start()
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
                    logger.error("Unexpected error in outbox loop: %s", exc)
                    if stop_event:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=interval)
                            break
                        except TimeoutError:
                            pass
                    else:
                        await asyncio.sleep(interval)
        finally:
            await self.stop()
            logger.info("OutboxDispatcher loop exited.")
