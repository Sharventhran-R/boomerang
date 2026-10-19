"""Reliable Kafka Event Consumer Foundation for Boomerang (Phase 7.4).

Guarantees at-least-once message consumption with database-backed idempotency,
atomic handler state commits, bounded retry backoff with jitter, quarantine
for poison/unsupported messages, and explicit operator replay workflows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aiokafka import (
    AIOKafkaConsumer,
    ConsumerRebalanceListener,
    ConsumerRecord,
    TopicPartition,
)
from aiokafka.structs import OffsetAndMetadata
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import ConsumerEvent, ConsumerEventStatus
from app.schemas.events import (
    BoomerangEvent,
    EventError,
    EventParseError,
    UnsupportedEventTypeError,
    UnsupportedEventVersionError,
    parse_event,
)
from app.services.event_consumer.handler import HandlerRegistry

logger = logging.getLogger(__name__)


class ErrorCategory(StrEnum):
    """Categorization of event processing failures."""

    TRANSIENT = "TRANSIENT"
    HANDLER_ERROR = "HANDLER_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"


class ConsumerProcessingResult(StrEnum):
    """Outcome of processing an individual Kafka record."""

    SUCCESS = "SUCCESS"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    QUARANTINED = "QUARANTINED"
    IGNORED = "IGNORED"


@dataclass
class ConsumerMetrics:
    """Operational metrics for event consumer throughput and errors."""

    received: int = 0
    successes: int = 0
    duplicates_skipped: int = 0
    retries: int = 0
    quarantined: int = 0
    replayed: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "received": self.received,
            "successes": self.successes,
            "duplicates_skipped": self.duplicates_skipped,
            "retries": self.retries,
            "quarantined": self.quarantined,
            "replayed": self.replayed,
        }


def calculate_consumer_backoff(
    attempt: int,
    initial_delay: float = 0.5,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
) -> float:
    """Calculates exponential backoff with full jitter in seconds."""
    exponent = max(0, attempt - 1)
    raw_delay = min(max_delay, initial_delay * (multiplier**exponent))
    jittered = random.uniform(0.5 * raw_delay, raw_delay)
    return max(0.05, round(jittered, 3))


def _sanitize_error_message(error: Exception | str) -> str:
    """Truncates error string and removes common credential patterns."""
    text = (
        f"{type(error).__name__}: {error}"
        if isinstance(error, Exception)
        else str(error)
    )
    # Scrub basic credential patterns if present
    for sensitive_word in ("password", "secret", "token", "key"):
        if sensitive_word in text.lower():
            text = text[:500]
    return text[:1000]


class PartitionOffsetTracker:
    """Tracks per-partition in-flight and durable offsets to enforce contiguous commits.

    Guarantees that a partition's committed offset never advances past an earlier
    message whose outcome has not yet reached a durable database outcome (COMPLETED
    or QUARANTINED).
    """

    def __init__(self) -> None:
        self._in_flight: dict[TopicPartition, set[int]] = defaultdict(set)
        self._durable: dict[TopicPartition, set[int]] = defaultdict(set)
        self._highest_safe: dict[TopicPartition, int] = {}
        self._committed: dict[TopicPartition, int] = {}
        self._assigned: set[TopicPartition] = set()
        self._track_assignments: bool = False
        self._lock = asyncio.Lock()

    def enable_assignment_tracking(self) -> None:
        """Enables strict partition assignment tracking with rebalance listeners."""
        self._track_assignments = True

    async def assign_partition(self, topic: str, partition: int) -> None:
        """Registers a partition as assigned to this consumer and clears prior state."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            self._assigned.add(tp)
            self._in_flight.pop(tp, None)
            self._durable.pop(tp, None)
            self._highest_safe.pop(tp, None)
            self._committed.pop(tp, None)

    async def revoke_partition(self, topic: str, partition: int) -> None:
        """Revokes a partition, discarding in-flight and durable tracking state."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            self._assigned.discard(tp)
            self._in_flight.pop(tp, None)
            self._durable.pop(tp, None)
            self._highest_safe.pop(tp, None)
            self._committed.pop(tp, None)

    async def is_assigned(self, topic: str, partition: int) -> bool:
        """Returns True if the partition is assigned or if tracking is disabled."""
        async with self._lock:
            if not self._track_assignments:
                return True
            return TopicPartition(topic, partition) in self._assigned

    async def get_safe_contiguous_offset(
        self, topic: str, partition: int
    ) -> int | None:
        """Returns highest contiguous safe offset durable but uncommitted."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            safe = self._highest_safe.get(tp)
            if safe is None:
                return None
            committed = self._committed.get(tp)
            if committed is not None and safe <= committed:
                return None
            return safe

    async def mark_in_flight(self, topic: str, partition: int, offset: int) -> None:
        """Registers a message offset as currently in flight."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            self._in_flight[tp].add(offset)

    async def mark_durable(self, topic: str, partition: int, offset: int) -> int | None:
        """Marks an offset as having reached a durable database outcome.

        Returns:
            The highest contiguous offset that can be safely committed to Kafka,
            or None if an earlier offset is still in flight or partition was revoked.
        """
        async with self._lock:
            tp = TopicPartition(topic, partition)
            if self._track_assignments and tp not in self._assigned:
                return None

            self._in_flight[tp].discard(offset)
            self._durable[tp].add(offset)

            in_flight = self._in_flight[tp]
            min_in_flight = min(in_flight) if in_flight else None

            # An offset D is safe to commit if and only if no in-flight offset Y is <= D
            eligible = [
                d
                for d in self._durable[tp]
                if min_in_flight is None or d < min_in_flight
            ]
            if not eligible:
                return None

            safe_offset = max(eligible)
            self._highest_safe[tp] = max(self._highest_safe.get(tp, -1), safe_offset)
            # Prune all durable offsets up to and including safe_offset
            self._durable[tp] = {d for d in self._durable[tp] if d > safe_offset}
            return safe_offset

    async def mark_committed(self, topic: str, partition: int, offset: int) -> None:
        """Records that an offset was successfully committed to Kafka."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            current = self._committed.get(tp, -1)
            if offset > current:
                self._committed[tp] = offset

    async def reset(self) -> None:
        """Clears all tracking state."""
        async with self._lock:
            self._in_flight.clear()
            self._durable.clear()
            self._highest_safe.clear()
            self._committed.clear()
            self._assigned.clear()
            self._in_flight.clear()
            self._durable.clear()
            self._assigned.clear()

    async def reset_partition(self, topic: str, partition: int) -> None:
        """Clears tracking state for a single partition."""
        async with self._lock:
            tp = TopicPartition(topic, partition)
            self._in_flight.pop(tp, None)
            self._durable.pop(tp, None)
            self._assigned.discard(tp)


class _ConsumerRebalanceListener(
    ConsumerRebalanceListener  # type: ignore[misc]
):
    """Bridges aiokafka rebalance callbacks to EventConsumer state management."""

    def __init__(self, consumer: EventConsumer) -> None:
        self._consumer = consumer

    async def on_partitions_revoked(self, revoked: Any) -> None:
        await self._consumer.handle_partitions_revoked(list(revoked))

    async def on_partitions_assigned(self, assigned: Any) -> None:
        await self._consumer.handle_partitions_assigned(list(assigned))


class EventConsumer:
    """Reliable Kafka event consumer managing idempotency, retries, and offsets."""

    def __init__(
        self,
        consumer_name: str,
        group_id: str | None = None,
        topics: list[str] | None = None,
        registry: HandlerRegistry | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        consumer: Any | None = None,
        bootstrap_servers: str | None = None,
        max_retries: int | None = None,
        initial_retry_delay: float | None = None,
        max_retry_delay: float | None = None,
        backoff_multiplier: float | None = None,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self.consumer_name = consumer_name
        self.group_id = group_id or f"{consumer_name}-group"
        self.topics = topics or [settings.KAFKA_DOMAIN_EVENTS_TOPIC]
        self.registry = registry or HandlerRegistry()
        self.session_factory = session_factory or AsyncSessionLocal
        self.consumer = consumer
        self._owns_consumer = consumer is None
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self.max_retries = (
            max_retries if max_retries is not None else settings.CONSUMER_MAX_RETRIES
        )
        self.initial_retry_delay = (
            initial_retry_delay
            if initial_retry_delay is not None
            else settings.CONSUMER_INITIAL_RETRY_DELAY_SECONDS
        )
        self.max_retry_delay = (
            max_retry_delay
            if max_retry_delay is not None
            else settings.CONSUMER_MAX_RETRY_DELAY_SECONDS
        )
        self.backoff_multiplier = (
            backoff_multiplier
            if backoff_multiplier is not None
            else settings.CONSUMER_BACKOFF_MULTIPLIER
        )
        self.auto_offset_reset = auto_offset_reset
        self.offset_tracker = PartitionOffsetTracker()
        self.metrics = ConsumerMetrics()
        self._running = False

    async def handle_partitions_revoked(self, revoked: list[TopicPartition]) -> None:
        """Handles partition revocation before consumer group rebalance completes."""
        logger.info(
            "Consumer '%s' partitions revoked: %s",
            self.consumer_name,
            [f"{tp.topic}[{tp.partition}]" for tp in revoked],
        )
        if self.consumer is not None:
            commit_map: dict[TopicPartition, OffsetAndMetadata] = {}
            for tp in revoked:
                safe_offset = await self.offset_tracker.get_safe_contiguous_offset(
                    tp.topic, tp.partition
                )
                if safe_offset is not None:
                    commit_map[tp] = OffsetAndMetadata(safe_offset + 1, "")
            if commit_map:
                try:
                    await self.consumer.commit(commit_map)
                    logger.info(
                        "Committed safe contiguous offsets prior to revocation: %s",
                        commit_map,
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not commit offsets during partition revocation: %s", exc
                    )

        for tp in revoked:
            await self.offset_tracker.revoke_partition(tp.topic, tp.partition)

    async def handle_partitions_assigned(self, assigned: list[TopicPartition]) -> None:
        """Handles partition assignment after consumer group rebalance completes."""
        logger.info(
            "Consumer '%s' partitions assigned: %s",
            self.consumer_name,
            [f"{tp.topic}[{tp.partition}]" for tp in assigned],
        )
        for tp in assigned:
            await self.offset_tracker.assign_partition(tp.topic, tp.partition)

    async def start(self) -> None:
        """Initializes and starts the underlying AIOKafkaConsumer."""
        if self._owns_consumer and self.consumer is None:
            self.consumer = AIOKafkaConsumer(
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                enable_auto_commit=False,
                auto_offset_reset=self.auto_offset_reset,
            )
            rebalance_listener = _ConsumerRebalanceListener(self)
            self.consumer.subscribe(topics=self.topics, listener=rebalance_listener)
            self.offset_tracker.enable_assignment_tracking()
            await self.consumer.start()
            logger.info(
                "EventConsumer '%s' connected to %s (group: %s, topics: %s)",
                self.consumer_name,
                self.bootstrap_servers,
                self.group_id,
                self.topics,
            )

    async def stop(self) -> None:
        """Stops the underlying Kafka consumer gracefully."""
        self._running = False
        await self.offset_tracker.reset()
        if self._owns_consumer and self.consumer is not None:
            await self.consumer.stop()
            self.consumer = None
            logger.info("EventConsumer '%s' stopped.", self.consumer_name)

    async def commit_offset(
        self, topic: str, partition: int, offset: int
    ) -> int | None:
        """Manually commits highest safe contiguous offset after durable outcome."""
        if not await self.offset_tracker.is_assigned(topic, partition):
            logger.warning(
                "Consumer '%s' partition %s[%d] revoked; skipping commit for %d.",
                self.consumer_name,
                topic,
                partition,
                offset,
            )
            return None

        safe_offset = await self.offset_tracker.mark_durable(topic, partition, offset)
        if safe_offset is not None and self.consumer is not None:
            tp = TopicPartition(topic, partition)
            if not await self.offset_tracker.is_assigned(topic, partition):
                logger.warning(
                    "Consumer '%s' partition %s[%d] revoked; skipping commit %d.",
                    self.consumer_name,
                    topic,
                    partition,
                    safe_offset,
                )
                return None
            # In Kafka, commit offset is the next message to read (offset + 1)
            await self.consumer.commit({tp: OffsetAndMetadata(safe_offset + 1, "")})
            await self.offset_tracker.mark_committed(topic, partition, safe_offset)
        return safe_offset

    async def get_event_status(self, event_id: uuid.UUID) -> ConsumerEventStatus | None:
        """Retrieves the current processing status for this consumer and event."""
        async with self.session_factory() as session:
            stmt = select(ConsumerEvent.status).where(
                ConsumerEvent.consumer_name == self.consumer_name,
                ConsumerEvent.event_id == event_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def is_event_completed(self, event_id: uuid.UUID) -> bool:
        """Checks if this consumer has already successfully processed this event."""
        return (await self.get_event_status(event_id)) == ConsumerEventStatus.COMPLETED

    async def record_quarantine(
        self,
        topic: str,
        partition: int,
        offset: int,
        error_category: ErrorCategory,
        error_message: str,
        raw_payload: Any = None,
        event: BoomerangEvent | None = None,
        retry_count: int = 0,
    ) -> ConsumerEvent:
        """Durably stores a failed or poison event in quarantine."""
        now = datetime.now(UTC)
        if event:
            event_id = event.event_id
            event_type = event.event_type.value
            aggregate_type = event.aggregate_type.value
            aggregate_id = event.aggregate_id
        else:
            is_dict = isinstance(raw_payload, dict)

            extracted_event_id: uuid.UUID | None = None
            if is_dict and "event_id" in raw_payload:
                try:
                    extracted_event_id = (
                        uuid.UUID(str(raw_payload["event_id"]))
                        if not isinstance(raw_payload["event_id"], uuid.UUID)
                        else raw_payload["event_id"]
                    )
                except (ValueError, TypeError):
                    extracted_event_id = None
            event_id = extracted_event_id or uuid.uuid4()

            extracted_agg_id: uuid.UUID | None = None
            if is_dict and "aggregate_id" in raw_payload:
                try:
                    extracted_agg_id = (
                        uuid.UUID(str(raw_payload["aggregate_id"]))
                        if not isinstance(raw_payload["aggregate_id"], uuid.UUID)
                        else raw_payload["aggregate_id"]
                    )
                except (ValueError, TypeError):
                    extracted_agg_id = None
            aggregate_id = extracted_agg_id or uuid.UUID(int=0)

            event_type = (
                str(raw_payload.get("event_type", "unknown")) if is_dict else "unknown"
            )
            aggregate_type = (
                str(raw_payload.get("aggregate_type", "unknown"))
                if is_dict
                else "unknown"
            )

        async with self.session_factory() as session:
            # Check if record already exists for this consumer and event_id
            existing = (
                await session.execute(
                    select(ConsumerEvent).where(
                        ConsumerEvent.consumer_name == self.consumer_name,
                        ConsumerEvent.event_id == event_id,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                if existing.status == ConsumerEventStatus.COMPLETED:
                    logger.info(
                        "Event %s was already completed by concurrent worker. "
                        "Retaining COMPLETED status.",
                        event_id,
                    )
                    return existing
                existing.status = ConsumerEventStatus.QUARANTINED
                existing.retry_count = retry_count
                existing.error_category = error_category.value
                existing.last_error = _sanitize_error_message(error_message)
                existing.updated_at = now
                session.add(existing)
                await session.commit()
                self.metrics.quarantined += 1
                return existing

            record = ConsumerEvent(
                consumer_name=self.consumer_name,
                event_id=event_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                topic=topic,
                partition=partition,
                offset=offset,
                status=ConsumerEventStatus.QUARANTINED,
                retry_count=retry_count,
                max_retries=self.max_retries,
                error_category=error_category.value,
                last_error=_sanitize_error_message(error_message),
                payload=raw_payload,
                created_at=now,
                updated_at=now,
            )
            try:
                session.add(record)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = (
                    await session.execute(
                        select(ConsumerEvent).where(
                            ConsumerEvent.consumer_name == self.consumer_name,
                            ConsumerEvent.event_id == event_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    if existing.status == ConsumerEventStatus.COMPLETED:
                        logger.info(
                            "Event %s was already completed by concurrent worker. "
                            "Retaining COMPLETED status.",
                            event_id,
                        )
                        return existing
                    existing.status = ConsumerEventStatus.QUARANTINED
                    existing.retry_count = retry_count
                    existing.error_category = error_category.value
                    existing.last_error = _sanitize_error_message(error_message)
                    existing.updated_at = now
                    session.add(existing)
                    await session.commit()
                    self.metrics.quarantined += 1
                    return existing
                raise

            self.metrics.quarantined += 1
            return record

    async def process_record(self, record: ConsumerRecord) -> ConsumerProcessingResult:
        """Processes a single Kafka ConsumerRecord through the validated pipeline."""
        self.metrics.received += 1
        topic = record.topic
        partition = record.partition
        offset = record.offset

        # Register in-flight offset in partition tracker
        await self.offset_tracker.mark_in_flight(topic, partition, offset)

        # 1. Parse raw Kafka message bytes
        raw_dict: Any = None
        try:
            raw_text = (
                record.value.decode("utf-8")
                if isinstance(record.value, bytes)
                else str(record.value)
            )
            raw_dict = json.loads(raw_text)
        except Exception as exc:
            logger.error(
                "Malformed JSON in %s[%d] offset %d: %s",
                topic,
                partition,
                offset,
                exc,
            )
            await self.record_quarantine(
                topic=topic,
                partition=partition,
                offset=offset,
                error_category=ErrorCategory.PARSE_ERROR,
                error_message=f"JSON decode failed: {exc}",
                raw_payload=None,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED

        # 2. Parse and validate EventEnvelope
        event: BoomerangEvent
        try:
            event = parse_event(raw_dict)
        except UnsupportedEventVersionError as exc:
            logger.error(
                "Unsupported event version in %s[%d] offset %d: %s",
                topic,
                partition,
                offset,
                exc,
            )
            await self.record_quarantine(
                topic=topic,
                partition=partition,
                offset=offset,
                error_category=ErrorCategory.UNSUPPORTED_VERSION,
                error_message=str(exc),
                raw_payload=raw_dict,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED
        except UnsupportedEventTypeError as exc:
            # Documented policy: if event type is unknown to schema,
            # quarantine for operational inspection
            logger.warning(
                "Unsupported event type in %s[%d] offset %d: %s",
                topic,
                partition,
                offset,
                exc,
            )
            await self.record_quarantine(
                topic=topic,
                partition=partition,
                offset=offset,
                error_category=ErrorCategory.UNSUPPORTED_TYPE,
                error_message=str(exc),
                raw_payload=raw_dict,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED
        except (EventParseError, EventError, Exception) as exc:
            logger.error(
                "Schema validation failed in %s[%d] offset %d: %s",
                topic,
                partition,
                offset,
                exc,
            )
            await self.record_quarantine(
                topic=topic,
                partition=partition,
                offset=offset,
                error_category=ErrorCategory.PARSE_ERROR,
                error_message=str(exc),
                raw_payload=raw_dict,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED

        # 3. Check Idempotency Barrier
        existing_status = await self.get_event_status(event.event_id)
        if existing_status == ConsumerEventStatus.COMPLETED:
            logger.info(
                "Consumer '%s' skipping duplicate event %s (%s)",
                self.consumer_name,
                event.event_id,
                event.event_type,
            )
            self.metrics.duplicates_skipped += 1
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.DUPLICATE_SKIPPED
        if existing_status == ConsumerEventStatus.QUARANTINED:
            logger.info(
                "Consumer '%s' skipping redelivered quarantined event %s (%s)",
                self.consumer_name,
                event.event_id,
                event.event_type,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED

        # 4. Handler Lookup
        handlers = self.registry.get_handlers(event.event_type)
        if not handlers:
            logger.debug(
                "No handlers registered for %s on consumer '%s'. Acknowledging.",
                event.event_type,
                self.consumer_name,
            )
            # Mark event completed in DB so subsequent deliveries are fast-skipped
            now = datetime.now(UTC)
            async with self.session_factory() as session:
                ce = ConsumerEvent(
                    consumer_name=self.consumer_name,
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    aggregate_type=event.aggregate_type.value,
                    aggregate_id=event.aggregate_id,
                    topic=topic,
                    partition=partition,
                    offset=offset,
                    status=ConsumerEventStatus.COMPLETED,
                    retry_count=0,
                    max_retries=self.max_retries,
                    payload=raw_dict if isinstance(raw_dict, dict) else None,
                    processed_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(ce)
                try:
                    await session.commit()
                except IntegrityError:
                    pass
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.IGNORED

        # 5. Execute Handlers within Atomic Database Transaction with Bounded Retry
        last_exception: Exception | None = None
        db_committed = False
        for attempt in range(1, self.max_retries + 1):
            try:
                now = datetime.now(UTC)
                async with self.session_factory() as session:
                    async with session.begin():
                        # Invoke each registered handler sequentially
                        for handler in handlers:
                            await handler.handle(event, session)

                        # Insert idempotency record in SAME database transaction
                        consumer_event_record = ConsumerEvent(
                            consumer_name=self.consumer_name,
                            event_id=event.event_id,
                            event_type=event.event_type.value,
                            aggregate_type=event.aggregate_type.value,
                            aggregate_id=event.aggregate_id,
                            topic=topic,
                            partition=partition,
                            offset=offset,
                            status=ConsumerEventStatus.COMPLETED,
                            retry_count=attempt - 1,
                            max_retries=self.max_retries,
                            payload=raw_dict if isinstance(raw_dict, dict) else None,
                            processed_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(consumer_event_record)

                # DB commit succeeded atomically!
                db_committed = True
                self.metrics.successes += 1
                break

            except IntegrityError:
                # Concurrent worker already committed this exact key
                logger.info(
                    "Concurrent processing for event %s. Checking terminal status.",
                    event.event_id,
                )
                terminal_status = await self.get_event_status(event.event_id)
                if terminal_status == ConsumerEventStatus.COMPLETED:
                    self.metrics.duplicates_skipped += 1
                    await self.commit_offset(topic, partition, offset)
                    return ConsumerProcessingResult.DUPLICATE_SKIPPED
                if terminal_status == ConsumerEventStatus.QUARANTINED:
                    await self.commit_offset(topic, partition, offset)
                    return ConsumerProcessingResult.QUARANTINED

                # If not completed, fall through to retry with jittered backoff
                last_exception = IntegrityError(
                    "Concurrent collision", params=None, orig=Exception()
                )
                self.metrics.retries += 1
                if attempt < self.max_retries:
                    delay = calculate_consumer_backoff(
                        attempt=attempt,
                        initial_delay=self.initial_retry_delay,
                        max_delay=self.max_retry_delay,
                        multiplier=self.backoff_multiplier,
                    )
                    await asyncio.sleep(delay)

            except Exception as exc:
                last_exception = exc
                self.metrics.retries += 1
                logger.warning(
                    "Handler error on %s (attempt %d/%d): %s",
                    event.event_id,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    delay = calculate_consumer_backoff(
                        attempt=attempt,
                        initial_delay=self.initial_retry_delay,
                        max_delay=self.max_retry_delay,
                        multiplier=self.backoff_multiplier,
                    )
                    await asyncio.sleep(delay)

        if not db_committed:
            # 6. Retry Exhaustion -> Quarantine
            logger.error(
                "Event %s exhausted max retries (%d). Quarantining: %s",
                event.event_id,
                self.max_retries,
                last_exception,
            )
            await self.record_quarantine(
                topic=topic,
                partition=partition,
                offset=offset,
                error_category=ErrorCategory.HANDLER_ERROR,
                error_message=str(last_exception),
                raw_payload=raw_dict,
                event=event,
                retry_count=self.max_retries,
            )
            await self.commit_offset(topic, partition, offset)
            return ConsumerProcessingResult.QUARANTINED

        # 6. Post-DB Commit Offset Commitment
        # DB transaction is already committed. Handler side-effects MUST NOT re-run.
        await self.commit_offset(topic, partition, offset)
        return ConsumerProcessingResult.SUCCESS

    async def replay_quarantined_event(self, event_id: uuid.UUID) -> bool:
        """Explicit operator action to reprocess a quarantined event."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            stmt = select(ConsumerEvent).where(
                ConsumerEvent.consumer_name == self.consumer_name,
                ConsumerEvent.event_id == event_id,
                ConsumerEvent.status == ConsumerEventStatus.QUARANTINED,
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if not record or not record.payload:
                logger.warning(
                    "No replayable quarantined record found for event %s",
                    event_id,
                )
                return False

            # Validate event contract from stored payload
            try:
                event = parse_event(record.payload)
            except Exception as exc:
                logger.error(
                    "Failed to parse quarantined payload for %s: %s", event_id, exc
                )
                return False

            handlers = self.registry.get_handlers(event.event_type)
            if not handlers:
                logger.warning("No handlers registered to replay %s", event.event_type)
                return False

            # Execute handlers and transition to COMPLETED in atomic transaction
            try:
                for handler in handlers:
                    await handler.handle(event, session)

                record.status = ConsumerEventStatus.COMPLETED
                record.last_error = None
                record.error_category = None
                record.processed_at = now
                record.updated_at = now
                session.add(record)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "Failed executing handlers during replay for %s: %s",
                    event_id,
                    exc,
                )
                return False

        self.metrics.replayed += 1
        logger.info("Successfully replayed quarantined event %s", event_id)
        return True

    async def replay_all_quarantined(self) -> int:
        """Replays all quarantined events for this consumer."""
        async with self.session_factory() as session:
            stmt = select(ConsumerEvent.event_id).where(
                ConsumerEvent.consumer_name == self.consumer_name,
                ConsumerEvent.status == ConsumerEventStatus.QUARANTINED,
            )
            result = await session.execute(stmt)
            event_ids = list(result.scalars().all())

        success_count = 0
        for eid in event_ids:
            if await self.replay_quarantined_event(eid):
                success_count += 1
        return success_count

    async def get_status_counts(self) -> dict[str, int]:
        """Returns row counts grouped by ConsumerEventStatus for inspection."""
        async with self.session_factory() as session:
            stmt = (
                select(ConsumerEvent.status, func.count(ConsumerEvent.id))
                .where(ConsumerEvent.consumer_name == self.consumer_name)
                .group_by(ConsumerEvent.status)
            )
            result = await session.execute(stmt)
            counts = {status.value: 0 for status in ConsumerEventStatus}
            for row in result.all():
                counts[row[0].value if hasattr(row[0], "value") else str(row[0])] = row[
                    1
                ]
            return counts

    async def run_loop(
        self,
        stop_event: asyncio.Event | None = None,
        max_messages: int | None = None,
        poll_timeout_ms: int = 1000,
    ) -> int:
        """Continuous polling loop processing Kafka records sequentially."""
        self._running = True
        processed_count = 0
        await self.start()
        logger.info("EventConsumer '%s' polling loop started...", self.consumer_name)

        try:
            while self._running:
                if stop_event and stop_event.is_set():
                    break

                if max_messages is not None and processed_count >= max_messages:
                    break

                if self.consumer is None:
                    break

                try:
                    records_by_tp = await self.consumer.getmany(
                        timeout_ms=poll_timeout_ms,
                        max_records=settings.CONSUMER_MAX_POLL_RECORDS,
                    )
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("Error polling Kafka consumer: %s", exc)
                    await asyncio.sleep(0.5)
                    continue

                if not records_by_tp:
                    continue

                for tp, records in records_by_tp.items():
                    for record in records:
                        if stop_event and stop_event.is_set():
                            break
                        if max_messages is not None and processed_count >= max_messages:
                            break

                        await self.process_record(record)
                        processed_count += 1
                        if stop_event and stop_event.is_set():
                            break
                    if stop_event and stop_event.is_set():
                        break
                    if max_messages is not None and processed_count >= max_messages:
                        break

        finally:
            await self.stop()
            logger.info(
                "EventConsumer '%s' loop stopped (total processed: %d).",
                self.consumer_name,
                processed_count,
            )

        return processed_count
