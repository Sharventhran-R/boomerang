"""Kafka matching worker for Boomerang Missing/Found Matching Engine (Phase 8.4).

Formalized in docs/matching_specification.md (Phase 8.1 & 8.4).
Consumes report domain events from `boomerang.domain.events` under consumer
group `matching_engine`.
Integrates Phase 8.2 Candidate Retrieval and Phase 8.3 Explainable Match Scoring.

In accordance with Phase 8.4 scope:
- Evaluates candidate matches for `report.created` and `report.updated` events.
- Safely acknowledges `report.resolved` events without generating active matches.
- Defers persistent database tables to Phase 8.5 via the typed `MatchResultHandoff`
  boundary.
- Preserves all Phase 7.4 Consumer Reliability Invariants: durable idempotency barrier,
  contiguous offset commits, atomic transactions, bounded retries, and quarantine
  handling.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Protocol, overload, runtime_checkable

from geoalchemy2 import Geometry
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Report, ReportStatus
from app.schemas.events import AggregateType, BoomerangEvent, EventType
from app.services.event_consumer import EventConsumer, HandlerRegistry
from app.services.matching.models import MatchScoreResult
from app.services.matching.persistence import MatchPersistenceService
from app.services.matching.retrieval import CandidateMatch, retrieve_candidates
from app.services.matching.scorer import score_candidates

logger = logging.getLogger(__name__)

MATCHING_CONSUMER_GROUP: str = "matching_engine"


@runtime_checkable
class MatchResultHandoff(Protocol):
    """Typed boundary protocol for passing scored matches to downstream consumers.

    Phase 8.4 provides an in-memory implementation for evaluation and testing.
    Phase 8.5 will substitute a database persistence repository implementing
    this protocol without altering the consumer or event handler logic.
    """

    async def record_matches(
        self,
        source_report: Report,
        results: list[MatchScoreResult],
        session: AsyncSession,
    ) -> None:
        """Records or dispatches scored candidate results for a source report."""
        ...


class InMemoryMatchResultHandoff:
    """Temporary in-memory collector for Phase 8.4 candidate match results.

    LIMITATION & PERSISTENCE NOTICE:
    Match results recorded by this class reside exclusively in process memory.
    They are NOT persistent across consumer restarts or process crashes.
    Upon consumer restart, historical events already committed to Kafka will NOT
    re-populate this in-memory store unless Kafka offsets are reset or events
    are explicitly replayed. Phase 8.5 will introduce durable PostgreSQL persistence.

    TRANSACTION SEMANTICS:
    When invoked within an active database transaction (`session.begin()`),
    candidate match results are staged and committed to in-memory collections
    only upon successful database commit (`after_commit`). If the database
    transaction rolls back, staged results are cleanly discarded (`after_rollback`),
    preventing state leakage from failed attempts and avoiding duplicate entries
    on consumer retry.
    """

    def __init__(self) -> None:
        self._results_by_source: dict[uuid.UUID, list[MatchScoreResult]] = defaultdict(
            list
        )
        self._all_results: list[MatchScoreResult] = []
        self._lock = asyncio.Lock()

    def _apply_staged_matches(
        self, source_report_id: uuid.UUID, results: list[MatchScoreResult]
    ) -> None:
        """Applies staged match results to in-memory collections."""
        self._results_by_source[source_report_id] = list(results)
        self._all_results.extend(results)

    async def record_matches(
        self,
        source_report: Report,
        results: list[MatchScoreResult],
        session: AsyncSession,
    ) -> None:
        """Stages scored results for commit upon successful database transaction."""
        sync_sess = getattr(session, "sync_session", None)
        if sync_sess is not None and hasattr(sync_sess, "dispatch"):
            report_id = source_report.id
            matches = list(results)

            def _on_commit(sess: Session) -> None:
                if event.contains(sync_sess, "after_rollback", _on_rollback):
                    event.remove(sync_sess, "after_rollback", _on_rollback)
                self._apply_staged_matches(report_id, matches)

            def _on_rollback(sess: Session) -> None:
                if event.contains(sync_sess, "after_commit", _on_commit):
                    event.remove(sync_sess, "after_commit", _on_commit)

            event.listen(sync_sess, "after_commit", _on_commit, once=True)
            event.listen(sync_sess, "after_rollback", _on_rollback, once=True)
        else:
            async with self._lock:
                self._apply_staged_matches(source_report.id, results)

    async def get_results_for_report(
        self, report_id: uuid.UUID
    ) -> list[MatchScoreResult]:
        """Retrieves in-memory scored matches for a given source report ID."""
        async with self._lock:
            return list(self._results_by_source.get(report_id, []))

    async def get_all_results(self) -> list[MatchScoreResult]:
        """Retrieves a flat list of all scored results collected so far."""
        async with self._lock:
            return list(self._all_results)

    async def clear(self) -> None:
        """Clears all in-memory scored results."""
        async with self._lock:
            self._results_by_source.clear()
            self._all_results.clear()


class MatchingEventHandler:
    """Event handler integrating Phase 7 Kafka events with Phase 8.2 & 8.3."""

    def __init__(self, handoff: MatchResultHandoff | None = None) -> None:
        self._handoff: MatchResultHandoff = (
            handoff if handoff is not None else MatchPersistenceService()
        )
        self.name = "MatchingEventHandler"

    @property
    def handoff(self) -> MatchResultHandoff:
        """Returns the configured result handoff boundary."""
        return self._handoff

    @property
    def event_types(self) -> Sequence[EventType | str]:
        """Declared event types handled by this matching handler."""
        return (
            EventType.REPORT_CREATED,
            EventType.REPORT_UPDATED,
            EventType.REPORT_RESOLVED,
        )

    async def handle(self, event: BoomerangEvent, session: AsyncSession) -> None:
        """Processes a validated report domain event within a database transaction."""
        if event.aggregate_type != AggregateType.REPORT:
            logger.warning(
                "Skipping non-report aggregate %s for event %s (%s)",
                event.aggregate_type,
                event.event_id,
                event.event_type,
            )
            return

        raw_aggregate_id = event.aggregate_id
        report_id: uuid.UUID
        if isinstance(raw_aggregate_id, uuid.UUID):
            report_id = raw_aggregate_id
        else:
            try:
                report_id = uuid.UUID(str(raw_aggregate_id))
            except (ValueError, TypeError) as exc:
                logger.error(
                    "Invalid report_id format '%s' in event %s: %s",
                    raw_aggregate_id,
                    event.event_id,
                    exc,
                )
                raise

        # 1. Handle report resolution
        if event.event_type == EventType.REPORT_RESOLVED:
            await self._handle_report_resolved(event, report_id, session)
            return

        # 2. Handle report creation and update (both evaluate candidate matches)
        if event.event_type in (EventType.REPORT_CREATED, EventType.REPORT_UPDATED):
            await self._handle_report_matching(event, report_id, session)
            return

        logger.debug(
            "Event %s with type %s not processed by matching handler.",
            event.event_id,
            event.event_type,
        )

    async def _handle_report_resolved(
        self,
        event: BoomerangEvent,
        report_id: uuid.UUID,
        session: AsyncSession,
    ) -> None:
        """Acknowledges report resolution safely and transitions matches to RESOLVED."""
        stmt = select(Report.id, Report.status).where(Report.id == report_id)
        res = await session.execute(stmt)
        row = res.first()
        if not row:
            logger.info(
                "Resolved report %s not found in database for event %s; "
                "acknowledging safely.",
                report_id,
                event.event_id,
            )
            return

        if isinstance(self._handoff, MatchPersistenceService):
            await self._handoff.resolve_matches_for_report(report_id, session)

        logger.info(
            "Acknowledged resolution for report %s (status=%s) from event %s; "
            "matches transitioned to RESOLVED.",
            report_id,
            row.status,
            event.event_id,
        )

    async def _handle_report_matching(
        self,
        event: BoomerangEvent,
        report_id: uuid.UUID,
        session: AsyncSession,
    ) -> None:
        """Fetches fresh PostgreSQL state, retrieves candidates, and scores matches."""
        # Query latest report state from PostgreSQL, projecting coordinates
        # from geometry
        stmt = (
            select(
                Report,
                func.ST_Y(Report.location.cast(Geometry)).label("latitude"),
                func.ST_X(Report.location.cast(Geometry)).label("longitude"),
            )
            .options(selectinload(Report.images))
            .where(Report.id == report_id)
        )
        res = await session.execute(stmt)
        row = res.first()
        if not row:
            logger.info(
                "Skipping matching: report %s not found in database for event %s (%s).",
                report_id,
                event.event_id,
                event.event_type.value,
            )
            return

        report, lat, lon = row
        setattr(report, "latitude", lat)
        setattr(report, "longitude", lon)

        # Enforce ACTIVE lifecycle status
        if report.status != ReportStatus.ACTIVE:
            logger.info(
                "Skipping matching: report %s has non-ACTIVE status %s for event %s.",
                report_id,
                report.status.value,
                event.event_id,
            )
            if isinstance(self._handoff, MatchPersistenceService):
                if report.status in (ReportStatus.CANCELLED, ReportStatus.EXPIRED):
                    await self._handoff.disqualify_matches_for_report(
                        report_id,
                        session,
                        reason=f"report_{report.status.value.lower()}",
                    )
                elif report.status == ReportStatus.RESOLVED:
                    await self._handoff.resolve_matches_for_report(report_id, session)
            return

        start_time = time.perf_counter()

        # Phase 8.2: Retrieve candidates using authoritative PostGIS bounds
        candidates: list[CandidateMatch] = await retrieve_candidates(session, report)

        # Phase 8.3: Compute deterministic, explainable scores
        scored_results: list[MatchScoreResult] = score_candidates(report, candidates)

        # Phase 8.4: Record results through the handoff boundary
        await self._handoff.record_matches(report, scored_results, session)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        alert_eligible_count = sum(1 for r in scored_results if r.alert_eligible)

        logger.info(
            "Matching completed for report %s (%s): %d candidates retrieved, "
            "%d scored, %d alert-eligible in %.2f ms",
            report.id,
            event.event_type.value,
            len(candidates),
            len(scored_results),
            alert_eligible_count,
            duration_ms,
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type.value,
                "report_id": str(report.id),
                "candidates_retrieved": len(candidates),
                "candidates_scored": len(scored_results),
                "alert_eligible_count": alert_eligible_count,
                "duration_ms": round(duration_ms, 2),
            },
        )


@overload
def create_matching_consumer(
    consumer_name: str = MATCHING_CONSUMER_GROUP,
    group_id: str = MATCHING_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    handoff: None = None,
    bootstrap_servers: str | None = None,
    max_retries: int | None = None,
    initial_retry_delay: float | None = None,
    max_retry_delay: float | None = None,
    backoff_multiplier: float | None = None,
    auto_offset_reset: str = "earliest",
) -> tuple[EventConsumer, MatchPersistenceService]: ...


@overload
def create_matching_consumer[HandoffT: MatchResultHandoff](
    consumer_name: str = MATCHING_CONSUMER_GROUP,
    group_id: str = MATCHING_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    handoff: HandoffT = ...,
    bootstrap_servers: str | None = None,
    max_retries: int | None = None,
    initial_retry_delay: float | None = None,
    max_retry_delay: float | None = None,
    backoff_multiplier: float | None = None,
    auto_offset_reset: str = "earliest",
) -> tuple[EventConsumer, HandoffT]: ...


@overload
def create_matching_consumer(
    consumer_name: str = MATCHING_CONSUMER_GROUP,
    group_id: str = MATCHING_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    handoff: MatchResultHandoff | None = None,
    bootstrap_servers: str | None = None,
    max_retries: int | None = None,
    initial_retry_delay: float | None = None,
    max_retry_delay: float | None = None,
    backoff_multiplier: float | None = None,
    auto_offset_reset: str = "earliest",
) -> tuple[EventConsumer, MatchResultHandoff]: ...


def create_matching_consumer(
    consumer_name: str = MATCHING_CONSUMER_GROUP,
    group_id: str = MATCHING_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    handoff: Any | None = None,
    bootstrap_servers: str | None = None,
    max_retries: int | None = None,
    initial_retry_delay: float | None = None,
    max_retry_delay: float | None = None,
    backoff_multiplier: float | None = None,
    auto_offset_reset: str = "earliest",
) -> tuple[EventConsumer, Any]:
    """Factory creating a configured EventConsumer wired to matching engine handler.

    Args:
        consumer_name: Unique consumer identifier used for metrics and idempotency.
        group_id: Kafka consumer group ID (defaults to 'matching_engine').
        topics: Topic names to consume (defaults to [KAFKA_DOMAIN_EVENTS_TOPIC]).
        session_factory: AsyncSession factory for database operations.
        consumer: Underlying Kafka consumer client (useful for unit tests/mocking).
        handoff: MatchResultHandoff implementation (defaults to in-memory).
        bootstrap_servers: Kafka broker addresses.
        max_retries: Maximum handler retries before quarantining an event.
        initial_retry_delay: Initial retry backoff in seconds.
        max_retry_delay: Maximum retry backoff in seconds.
        backoff_multiplier: Exponential multiplier for retries.
        auto_offset_reset: Kafka offset reset strategy.

    Returns:
        Tuple of (EventConsumer, MatchResultHandoff).
    """
    effective_handoff = handoff if handoff is not None else MatchPersistenceService()
    registry = HandlerRegistry()
    handler = MatchingEventHandler(handoff=effective_handoff)
    registry.register(handler)

    consumer_instance = EventConsumer(
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
    return consumer_instance, effective_handoff


async def run_matching_worker(
    stop_event: asyncio.Event | None = None,
    max_messages: int | None = None,
    poll_timeout_ms: int = 1000,
    consumer_name: str = MATCHING_CONSUMER_GROUP,
    group_id: str = MATCHING_CONSUMER_GROUP,
    topics: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumer: Any | None = None,
    handoff: MatchResultHandoff | None = None,
    bootstrap_servers: str | None = None,
) -> int:
    """Runs the matching worker loop until stop_event is set or max_messages reached.

    Returns:
        Total number of processed Kafka records.
    """
    event_consumer, _ = create_matching_consumer(
        consumer_name=consumer_name,
        group_id=group_id,
        topics=topics,
        session_factory=session_factory,
        consumer=consumer,
        handoff=handoff,
        bootstrap_servers=bootstrap_servers,
    )
    return await event_consumer.run_loop(
        stop_event=stop_event,
        max_messages=max_messages,
        poll_timeout_ms=poll_timeout_ms,
    )
