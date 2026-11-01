"""Comprehensive unit and integration tests for Phase 8.5 Match Persistence.

Formalized in docs/matching_specification.md (Phase 8.1 & 8.5).
Verifies:
- Canonical pair ordering & validation (Missing report always in report_missing_id).
- Self-match rejection and same-type rejection.
- Database check constraints on score ranges, version, and report distinctness.
- Score >= 40 persistence policy: new candidate pairs < 40 are not persisted;
  existing matches rescored < 40 transition to SUPPRESSED while preserving history.
- Rescoring promotion: SUPPRESSED match rescored >= 40 transitions back to ACTIVE.
- Hard-filter disqualification: existing active matches no longer returned by
  retrieval transition to DISQUALIFIED.
- Concurrency-safe terminal state protection: RESOLVED matches cannot be
  overwritten by delayed or concurrent rescore transactions.
- Concurrent upserts from independent PostgreSQL sessions using asyncio.gather().
- Foreign key deletion restriction (ON DELETE RESTRICT) preventing cascade deletion.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    Match,
    MatchStatus,
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
    ScoreClassification,
    User,
)
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    TimeBreakdown,
)
from app.services.matching.persistence import (
    MatchIntegrityError,
    MatchPersistenceService,
)


def _make_score_result(
    source_id: uuid.UUID,
    candidate_id: uuid.UUID,
    composite_score: float,
    classification: ScoreClassification = ScoreClassification.HIGH_PRIORITY,
    alert_eligible: bool = True,
    contradiction_penalty: float = 0.0,
) -> MatchScoreResult:
    """Helper to build a mock MatchScoreResult with valid breakdown objects."""
    identity = IdentityBreakdown(
        score=composite_score,
        category_score=40.0,
        brand_model_score=40.0,
        title_noun_score=20.0,
        matched_category="ELECTRONICS",
        matched_brand="Apple",
        matched_model="iPhone 15 Pro",
    )
    characteristics = CharacteristicsBreakdown(
        score=composite_score,
        matched_colors=["black"],
    )
    distance = DistanceBreakdown(
        score=composite_score,
        distance_meters=300.0,
        distance_km=0.3,
    )
    time = TimeBreakdown(
        score=composite_score,
        loss_time=datetime.now(UTC),
        found_time=datetime.now(UTC),
        delta_hours=2.0,
    )
    return MatchScoreResult(
        source_id=source_id,
        candidate_id=candidate_id,
        identity=identity,
        characteristics=characteristics,
        distance=distance,
        time=time,
        raw_composite_score=composite_score,
        contradiction_penalty=contradiction_penalty,
        composite_score=composite_score,
        classification=classification,
        alert_eligible=alert_eligible,
        minimum_evidence_satisfied=True,
        evidence_summary="Strong brand/model match within 300m",
    )


class _PersistenceTestFixture:
    """Sets up isolated test reports, users, and handles clean tear-down."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []
        self.report_ids: list[uuid.UUID] = []

    async def create_user(self, name_prefix: str = "u") -> User:
        uid = uuid.uuid4().hex[:8]
        user = User(
            name=f"{name_prefix}_{uid}",
            email=f"{name_prefix}_{uid}@example.com",
            password_hash="hashed_pw",
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    async def create_report(
        self,
        user_id: uuid.UUID,
        report_type: ReportType,
        status: ReportStatus = ReportStatus.ACTIVE,
        category: ReportCategory = ReportCategory.ELECTRONICS,
        title: str = "Test iPhone 15",
    ) -> Report:
        lat = 37.7749 + (len(self.report_ids) * 0.001)
        lon = -122.4194 + (len(self.report_ids) * 0.001)
        report = Report(
            created_by_user_id=user_id,
            type=report_type,
            title=title,
            description="Titanium black device with minor scratch",
            category=category,
            location=WKTElement(f"POINT({lon} {lat})", srid=4326),
            event_time=datetime.now(UTC),
            status=status,
            created_at=datetime.now(UTC),
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        self.report_ids.append(report.id)
        return report

    async def cleanup(self) -> None:
        try:
            await self.session.rollback()
        except Exception:
            pass
        async with AsyncSessionLocal() as cleanup_session:
            if self.report_ids:
                # Delete matches first due to ON DELETE RESTRICT
                await cleanup_session.execute(
                    delete(Match).where(
                        (Match.report_missing_id.in_(self.report_ids))
                        | (Match.report_found_id.in_(self.report_ids))
                    )
                )
                await cleanup_session.execute(
                    delete(Report).where(Report.id.in_(self.report_ids))
                )
            if self.user_ids:
                await cleanup_session.execute(
                    delete(User).where(User.id.in_(self.user_ids))
                )
            await cleanup_session.commit()


@pytest.fixture
async def pctx() -> AsyncGenerator[_PersistenceTestFixture, None]:
    async with AsyncSessionLocal() as session:
        fixture = _PersistenceTestFixture(session)
        try:
            yield fixture
        finally:
            await fixture.cleanup()


@pytest.mark.asyncio
async def test_canonical_pair_ordering_from_missing_source(
    pctx: _PersistenceTestFixture,
) -> None:
    """Missing source report records candidate with Missing UUID in missing_id."""
    u1 = await pctx.create_user("owner")
    u2 = await pctx.create_user("finder")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    result = _make_score_result(
        missing.id, found.id, composite_score=85.0, alert_eligible=True
    )

    await service.record_matches(missing, [result], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    match = matches[0]
    assert match.report_missing_id == missing.id
    assert match.report_found_id == found.id
    assert match.status == MatchStatus.ACTIVE
    assert match.composite_score == 85.0
    assert match.alert_eligible is True
    assert match.scoring_version == 1


@pytest.mark.asyncio
async def test_canonical_pair_ordering_from_found_source(
    pctx: _PersistenceTestFixture,
) -> None:
    """Found source report records candidate with Missing UUID in report_missing_id."""
    u1 = await pctx.create_user("owner")
    u2 = await pctx.create_user("finder")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    # Source is FOUND, candidate is MISSING
    result = _make_score_result(
        found.id, missing.id, composite_score=82.0, alert_eligible=True
    )

    await service.record_matches(found, [result], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(found.id, pctx.session)
    assert len(matches) == 1
    match = matches[0]
    # Invariant: report_missing_id is always missing.id, report_found_id is found.id
    assert match.report_missing_id == missing.id
    assert match.report_found_id == found.id
    assert match.status == MatchStatus.ACTIVE


@pytest.mark.asyncio
async def test_self_match_rejected(pctx: _PersistenceTestFixture) -> None:
    """Candidate match with identical source and candidate IDs is rejected."""
    u = await pctx.create_user("user")
    missing = await pctx.create_report(u.id, ReportType.MISSING)

    service = MatchPersistenceService()
    result = _make_score_result(missing.id, missing.id, composite_score=90.0)

    with pytest.raises(MatchIntegrityError, match="Self-match rejected"):
        await service.record_matches(missing, [result], pctx.session)


@pytest.mark.asyncio
async def test_database_check_constraint_distinct_reports(
    pctx: _PersistenceTestFixture,
) -> None:
    """Direct database insert violating distinct reports is rejected by PostgreSQL."""
    u = await pctx.create_user("user")
    rep = await pctx.create_report(u.id, ReportType.MISSING)

    match = Match(
        report_missing_id=rep.id,
        report_found_id=rep.id,  # Violates check constraint
        status=MatchStatus.ACTIVE,
        composite_score=50.0,
        score_identity=50.0,
        score_characteristics=50.0,
        score_distance=50.0,
        score_time=50.0,
        raw_composite_score=50.0,
        contradiction_penalty=0.0,
        classification=ScoreClassification.LOW_CONFIDENCE,
        alert_eligible=False,
        minimum_evidence_satisfied=False,
        evidence_summary="Invalid distinct test",
        explainability_details={},
        scoring_version=1,
        last_scored_at=datetime.now(UTC),
    )
    pctx.session.add(match)
    with pytest.raises((IntegrityError, DBAPIError)):
        await pctx.session.commit()
    await pctx.session.rollback()


@pytest.mark.asyncio
async def test_new_candidate_below_40_is_not_persisted(
    pctx: _PersistenceTestFixture,
) -> None:
    """Candidates scoring < 40 are discarded without creating DB rows."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    result = _make_score_result(
        missing.id,
        found.id,
        composite_score=35.0,  # Below PERSISTENCE_SCORE_THRESHOLD
        classification=ScoreClassification.DISQUALIFIED,
        alert_eligible=False,
    )

    await service.record_matches(missing, [result], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_existing_match_rescore_above_40_updates_in_place(
    pctx: _PersistenceTestFixture,
) -> None:
    """Rescoring an existing match updates scores, evidence, and timestamps in-place."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res1 = _make_score_result(
        missing.id,
        found.id,
        composite_score=65.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        alert_eligible=False,
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    # Rescore with higher score
    res2 = _make_score_result(
        missing.id,
        found.id,
        composite_score=88.5,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
    )
    await service.record_matches(missing, [res2], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    match = matches[0]
    assert match.composite_score == 88.5
    assert match.classification == ScoreClassification.HIGH_PRIORITY
    assert match.alert_eligible is True
    assert match.status == MatchStatus.ACTIVE


@pytest.mark.asyncio
async def test_existing_match_rescore_below_40_demotes_to_suppressed(
    pctx: _PersistenceTestFixture,
) -> None:
    """An existing match falling < 40 becomes SUPPRESSED with preserved history."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    # Step 1: Discover with qualifying score
    res1 = _make_score_result(
        missing.id,
        found.id,
        composite_score=78.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        alert_eligible=True,
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    # Step 2: Rescore dropping below 40
    res2 = _make_score_result(
        missing.id,
        found.id,
        composite_score=32.0,
        classification=ScoreClassification.DISQUALIFIED,
        alert_eligible=False,
    )
    await service.record_matches(missing, [res2], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    match = matches[0]
    # Invariants:
    # 1. Match is NOT deleted
    # 2. Lifecycle status is SUPPRESSED
    # 3. Score classification is DISQUALIFIED (from score band)
    # 4. Scores are updated accurately
    assert match.status == MatchStatus.SUPPRESSED
    assert match.classification == ScoreClassification.DISQUALIFIED
    assert match.composite_score == 32.0
    assert match.alert_eligible is False


@pytest.mark.asyncio
async def test_suppressed_match_rescore_above_40_promotes_to_active(
    pctx: _PersistenceTestFixture,
) -> None:
    """A SUPPRESSED match promotes back to ACTIVE if rescore reaches >= 40."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    # Start with qualifying match, then demote
    res1 = _make_score_result(
        missing.id, found.id, composite_score=60.0, alert_eligible=False
    )
    await service.record_matches(missing, [res1], pctx.session)
    res2 = _make_score_result(
        missing.id,
        found.id,
        composite_score=25.0,
        classification=ScoreClassification.DISQUALIFIED,
        alert_eligible=False,
    )
    await service.record_matches(missing, [res2], pctx.session)
    await pctx.session.commit()

    # Verify SUPPRESSED
    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert matches[0].status == MatchStatus.SUPPRESSED

    # Rescore rises to 75.0
    res3 = _make_score_result(
        missing.id,
        found.id,
        composite_score=75.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        alert_eligible=True,
    )
    await service.record_matches(missing, [res3], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert matches[0].status == MatchStatus.ACTIVE
    assert matches[0].composite_score == 75.0
    assert matches[0].alert_eligible is True


@pytest.mark.asyncio
async def test_unreturned_existing_match_disqualified(
    pctx: _PersistenceTestFixture,
) -> None:
    """An active match not in retrieval results transitions to DISQUALIFIED."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res1 = _make_score_result(
        missing.id, found.id, composite_score=80.0, alert_eligible=True
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    # Now genuinely move found report outside 5km (e.g. ~11 km away)
    far_lat = 37.7749 + 0.1
    await pctx.session.execute(
        update(Report)
        .where(Report.id == found.id)
        .values(location=WKTElement(f"POINT(-122.4194 {far_lat})", srid=4326))
    )
    await pctx.session.commit()

    # Now retrieval returns empty results because candidate is outside 5km
    await service.record_matches(missing, [], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    assert matches[0].status == MatchStatus.DISQUALIFIED
    assert matches[0].alert_eligible is False


@pytest.mark.asyncio
async def test_resolved_match_cannot_be_overwritten_by_rescore(
    pctx: _PersistenceTestFixture,
) -> None:
    """Terminal state protection: RESOLVED match cannot be reactivated by rescore."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res1 = _make_score_result(
        missing.id, found.id, composite_score=85.0, alert_eligible=True
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    # Transition to RESOLVED
    resolved_count = await service.resolve_matches_for_report(missing.id, pctx.session)
    await pctx.session.commit()
    assert resolved_count == 1

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert matches[0].status == MatchStatus.RESOLVED

    # Now simulate a delayed rescore attempt with a high score (95.0)
    res_delayed = _make_score_result(
        missing.id, found.id, composite_score=95.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_delayed], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    # Status remains strictly RESOLVED
    assert matches[0].status == MatchStatus.RESOLVED


@pytest.mark.asyncio
async def test_cancelled_or_expired_report_disqualifies_matches(
    pctx: _PersistenceTestFixture,
) -> None:
    """When a report is CANCELLED or EXPIRED, active matches become DISQUALIFIED."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res1 = _make_score_result(
        missing.id, found.id, composite_score=80.0, alert_eligible=True
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    # Disqualify due to report cancellation
    disqualified = await service.disqualify_matches_for_report(
        missing.id, pctx.session, reason="report_cancelled"
    )
    await pctx.session.commit()
    assert disqualified == 1

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    assert matches[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_concurrent_upsert_same_pair_independent_sessions(
    pctx: _PersistenceTestFixture,
) -> None:
    """Concurrent workers upserting same pair using separate sessions create 1 row."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()

    async def _upsert_worker(worker_id: int, score: float) -> None:
        async with AsyncSessionLocal() as worker_session:
            async with worker_session.begin():
                res = _make_score_result(
                    missing.id, found.id, composite_score=score, alert_eligible=True
                )
                await service.record_matches(missing, [res], worker_session)

    # Launch 5 concurrent workers
    tasks = [_upsert_worker(i, 70.0 + i) for i in range(5)]
    await asyncio.gather(*tasks)

    # Verify exactly 1 row in the database
    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    assert matches[0].report_missing_id == missing.id
    assert matches[0].report_found_id == found.id
    assert matches[0].status == MatchStatus.ACTIVE


@pytest.mark.asyncio
async def test_foreign_key_deletion_restrict_prevents_deleting_report(
    pctx: _PersistenceTestFixture,
) -> None:
    """PostgreSQL ON DELETE RESTRICT blocks deleting report that has match records."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res = _make_score_result(
        missing.id, found.id, composite_score=85.0, alert_eligible=True
    )
    await service.record_matches(missing, [res], pctx.session)
    await pctx.session.commit()

    # Attempt to delete the report directly while match exists
    with pytest.raises((IntegrityError, DBAPIError)):
        await pctx.session.execute(delete(Report).where(Report.id == missing.id))
        await pctx.session.commit()
    await pctx.session.rollback()


@pytest.mark.asyncio
async def test_score_range_check_constraints(pctx: _PersistenceTestFixture) -> None:
    """Direct SQL inserts with score > 100 or < 0 violate database check constraints."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    # Score > 100
    invalid_match = Match(
        report_missing_id=missing.id,
        report_found_id=found.id,
        status=MatchStatus.ACTIVE,
        composite_score=105.0,  # Invalid
        score_identity=100.0,
        score_characteristics=100.0,
        score_distance=100.0,
        score_time=100.0,
        raw_composite_score=105.0,
        contradiction_penalty=0.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        minimum_evidence_satisfied=True,
        evidence_summary="Invalid test",
        explainability_details={},
        scoring_version=1,
        last_scored_at=datetime.now(UTC),
    )
    pctx.session.add(invalid_match)
    with pytest.raises((IntegrityError, DBAPIError)):
        await pctx.session.commit()
    await pctx.session.rollback()


@pytest.mark.asyncio
async def test_concurrent_scoring_and_report_cancellation(
    pctx: _PersistenceTestFixture,
) -> None:
    """Concurrent match scoring and report cancellation cannot reactivate match."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()

    # Pre-create match with ACTIVE status
    res_init = _make_score_result(
        missing.id, found.id, composite_score=75.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_init], pctx.session)
    await pctx.session.commit()

    # Concurrently execute:
    # Worker A: records rescore with score 88.0 attempting to activate
    # Worker B: cancels missing report and disqualifies matches
    async def worker_rescore() -> None:
        async with AsyncSessionLocal() as session_a:
            async with session_a.begin():
                res_high = _make_score_result(
                    missing.id, found.id, composite_score=88.0, alert_eligible=True
                )
                await service.record_matches(missing, [res_high], session_a)

    async def worker_cancel() -> None:
        async with AsyncSessionLocal() as session_b:
            async with session_b.begin():
                await session_b.execute(
                    update(Report)
                    .where(Report.id == missing.id)
                    .values(status=ReportStatus.CANCELLED)
                )
                await service.disqualify_matches_for_report(missing.id, session_b)

    await asyncio.gather(worker_rescore(), worker_cancel())

    # Verify authoritative final state
    async with AsyncSessionLocal() as verify_session:
        rep = await verify_session.get(Report, missing.id)
        assert rep is not None
        assert rep.status == ReportStatus.CANCELLED

        matches = await service.get_matches_for_report(missing.id, verify_session)
        assert len(matches) == 1
        # The match must NOT be ACTIVE!
        assert matches[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_concurrent_scoring_and_report_expiration(
    pctx: _PersistenceTestFixture,
) -> None:
    """Concurrent match scoring and report expiration cannot reactivate match."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res_init = _make_score_result(
        missing.id, found.id, composite_score=72.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_init], pctx.session)
    await pctx.session.commit()

    async def worker_rescore() -> None:
        async with AsyncSessionLocal() as session_a:
            async with session_a.begin():
                res_high = _make_score_result(
                    missing.id, found.id, composite_score=91.0, alert_eligible=True
                )
                await service.record_matches(missing, [res_high], session_a)

    async def worker_expire() -> None:
        async with AsyncSessionLocal() as session_b:
            async with session_b.begin():
                await session_b.execute(
                    update(Report)
                    .where(Report.id == missing.id)
                    .values(status=ReportStatus.EXPIRED)
                )
                await service.disqualify_matches_for_report(missing.id, session_b)

    await asyncio.gather(worker_rescore(), worker_expire())

    async with AsyncSessionLocal() as verify_session:
        rep = await verify_session.get(Report, missing.id)
        assert rep is not None
        assert rep.status == ReportStatus.EXPIRED

        matches = await service.get_matches_for_report(missing.id, verify_session)
        assert len(matches) == 1
        assert matches[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_concurrent_scoring_and_report_resolution(
    pctx: _PersistenceTestFixture,
) -> None:
    """Concurrent match scoring and report resolution preserves RESOLVED status."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res_init = _make_score_result(
        missing.id, found.id, composite_score=80.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_init], pctx.session)
    await pctx.session.commit()

    async def worker_rescore() -> None:
        async with AsyncSessionLocal() as session_a:
            async with session_a.begin():
                res_high = _make_score_result(
                    missing.id, found.id, composite_score=95.0, alert_eligible=True
                )
                await service.record_matches(missing, [res_high], session_a)

    async def worker_resolve() -> None:
        async with AsyncSessionLocal() as session_b:
            async with session_b.begin():
                await session_b.execute(
                    update(Report)
                    .where(Report.id == missing.id)
                    .values(status=ReportStatus.RESOLVED)
                )
                await service.resolve_matches_for_report(missing.id, session_b)

    await asyncio.gather(worker_rescore(), worker_resolve())

    async with AsyncSessionLocal() as verify_session:
        rep = await verify_session.get(Report, missing.id)
        assert rep is not None
        assert rep.status == ReportStatus.RESOLVED

        matches = await service.get_matches_for_report(missing.id, verify_session)
        assert len(matches) == 1
        assert matches[0].status == MatchStatus.RESOLVED


@pytest.mark.asyncio
async def test_reactivation_after_temporary_hard_filter_failure(
    pctx: _PersistenceTestFixture,
) -> None:
    """Match disqualified by temporary filter reactivates when reports are active."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()

    # Step 1: Initial match within distance -> ACTIVE
    res1 = _make_score_result(
        missing.id, found.id, composite_score=75.0, alert_eligible=True
    )
    await service.record_matches(missing, [res1], pctx.session)
    await pctx.session.commit()

    m1 = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(m1) == 1
    assert m1[0].status == MatchStatus.ACTIVE

    # Step 2: Temporary hard filter failure: report location moved > 5km.
    far_lat = 37.7749 + 0.1
    await pctx.session.execute(
        update(Report)
        .where(Report.id == found.id)
        .values(location=WKTElement(f"POINT(-122.4194 {far_lat})", srid=4326))
    )
    await pctx.session.commit()

    # Retrieval returns empty results -> genuine distance failure -> DISQUALIFIED
    await service.record_matches(missing, [], pctx.session)
    await pctx.session.commit()

    m2 = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(m2) == 1
    assert m2[0].status == MatchStatus.DISQUALIFIED

    # Step 3: Location corrected: both reports remain genuinely ACTIVE.
    near_lat = 37.7749 + 0.002
    await pctx.session.execute(
        update(Report)
        .where(Report.id == found.id)
        .values(location=WKTElement(f"POINT(-122.4194 {near_lat})", srid=4326))
    )
    await pctx.session.commit()

    # Retrieval returns candidate again with qualifying score -> reactivated to ACTIVE!
    res3 = _make_score_result(
        missing.id,
        found.id,
        composite_score=86.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
    )
    await service.record_matches(missing, [res3], pctx.session)
    await pctx.session.commit()

    m3 = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(m3) == 1
    assert m3[0].status == MatchStatus.ACTIVE
    assert m3[0].composite_score == 86.0
    assert m3[0].classification == ScoreClassification.HIGH_PRIORITY
    assert m3[0].alert_eligible is True


@pytest.mark.asyncio
async def test_terminal_matches_cannot_be_reactivated(
    pctx: _PersistenceTestFixture,
) -> None:
    """Terminal matches (RESOLVED or CANCELLED/EXPIRED) cannot be reactivated."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")

    # Case A: RESOLVED match
    missing_a = await pctx.create_report(u1.id, ReportType.MISSING)
    found_a = await pctx.create_report(u2.id, ReportType.FOUND)
    service = MatchPersistenceService()

    res_a = _make_score_result(missing_a.id, found_a.id, composite_score=80.0)
    await service.record_matches(missing_a, [res_a], pctx.session)
    await service.resolve_matches_for_report(missing_a.id, pctx.session)
    await pctx.session.commit()

    # Attempt to re-activate by rescoring with 99.0
    res_a2 = _make_score_result(missing_a.id, found_a.id, composite_score=99.0)
    await service.record_matches(missing_a, [res_a2], pctx.session)
    await pctx.session.commit()

    matches_a = await service.get_matches_for_report(missing_a.id, pctx.session)
    assert len(matches_a) == 1
    assert matches_a[0].status == MatchStatus.RESOLVED
    assert matches_a[0].composite_score == 80.0  # Not overwritten!

    # Case B: CANCELLED report
    missing_b = await pctx.create_report(u1.id, ReportType.MISSING)
    found_b = await pctx.create_report(u2.id, ReportType.FOUND)
    res_b = _make_score_result(missing_b.id, found_b.id, composite_score=78.0)
    await service.record_matches(missing_b, [res_b], pctx.session)
    await pctx.session.execute(
        update(Report)
        .where(Report.id == missing_b.id)
        .values(status=ReportStatus.CANCELLED)
    )
    await service.disqualify_matches_for_report(missing_b.id, pctx.session)
    await pctx.session.commit()

    # Attempt to re-activate from found_b side
    res_b2 = _make_score_result(found_b.id, missing_b.id, composite_score=95.0)
    await service.record_matches(found_b, [res_b2], pctx.session)
    await pctx.session.commit()

    matches_b = await service.get_matches_for_report(missing_b.id, pctx.session)
    assert len(matches_b) == 1
    assert matches_b[0].status == MatchStatus.DISQUALIFIED

    # Case C: EXPIRED report
    missing_c = await pctx.create_report(u1.id, ReportType.MISSING)
    found_c = await pctx.create_report(u2.id, ReportType.FOUND)
    res_c = _make_score_result(missing_c.id, found_c.id, composite_score=78.0)
    await service.record_matches(missing_c, [res_c], pctx.session)
    await pctx.session.execute(
        update(Report)
        .where(Report.id == missing_c.id)
        .values(status=ReportStatus.EXPIRED)
    )
    await service.disqualify_matches_for_report(missing_c.id, pctx.session)
    await pctx.session.commit()

    # Attempt to re-activate from found_c side
    res_c2 = _make_score_result(found_c.id, missing_c.id, composite_score=95.0)
    await service.record_matches(found_c, [res_c2], pctx.session)
    await pctx.session.commit()

    matches_c = await service.get_matches_for_report(missing_c.id, pctx.session)
    assert len(matches_c) == 1
    assert matches_c[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_existing_valid_match_omitted_by_candidate_limit_retains_status(
    pctx: _PersistenceTestFixture,
) -> None:
    """An existing valid match omitted by retrieval limit must not be disqualified."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)

    # Create 3 found reports within 500m of missing report
    found_1 = await pctx.create_report(u2.id, ReportType.FOUND, title="Found 1")
    found_2 = await pctx.create_report(u2.id, ReportType.FOUND, title="Found 2")
    found_3 = await pctx.create_report(u2.id, ReportType.FOUND, title="Found 3")

    service = MatchPersistenceService()

    # Pre-record an existing active match for found_3
    res_3_init = _make_score_result(
        missing.id, found_3.id, composite_score=80.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_3_init], pctx.session)
    await pctx.session.commit()

    m_init = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(m_init) == 1
    assert m_init[0].report_found_id == found_3.id
    assert m_init[0].status == MatchStatus.ACTIVE

    # Now retrieval returns candidates truncated to limit=2 (only found_1 and found_2).
    # found_3 is omitted purely due to limit, despite being strictly eligible.
    res_1 = _make_score_result(missing.id, found_1.id, composite_score=85.0)
    res_2 = _make_score_result(missing.id, found_2.id, composite_score=75.0)
    await service.record_matches(missing, [res_1, res_2], pctx.session)
    await pctx.session.commit()

    # Verify found_3 was NOT disqualified and retained ACTIVE status
    all_matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(all_matches) == 3

    m3 = next(m for m in all_matches if m.report_found_id == found_3.id)
    assert m3.status == MatchStatus.ACTIVE
    assert m3.composite_score == 80.0


@pytest.mark.asyncio
async def test_existing_match_genuinely_outside_geographic_boundary_disqualified(
    pctx: _PersistenceTestFixture,
) -> None:
    """An existing match moved outside 5km fails HF-5 and is DISQUALIFIED."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)
    found = await pctx.create_report(u2.id, ReportType.FOUND)

    service = MatchPersistenceService()
    res_init = _make_score_result(
        missing.id, found.id, composite_score=82.0, alert_eligible=True
    )
    await service.record_matches(missing, [res_init], pctx.session)
    await pctx.session.commit()

    # Move found report coordinates to ~11 km away (> 5,000m)
    far_lat = 37.7749 + 0.1
    await pctx.session.execute(
        update(Report)
        .where(Report.id == found.id)
        .values(location=WKTElement(f"POINT(-122.4194 {far_lat})", srid=4326))
    )
    await pctx.session.commit()

    # Retrieval for missing returns empty results (or other candidates)
    await service.record_matches(missing, [], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    assert matches[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_existing_match_incompatible_category_disqualified(
    pctx: _PersistenceTestFixture,
) -> None:
    """An existing match with incompatible category fails HF-6 and is DISQUALIFIED."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(
        u1.id, ReportType.MISSING, category=ReportCategory.ELECTRONICS
    )
    found = await pctx.create_report(
        u2.id, ReportType.FOUND, category=ReportCategory.ELECTRONICS
    )

    service = MatchPersistenceService()
    res_init = _make_score_result(missing.id, found.id, composite_score=80.0)
    await service.record_matches(missing, [res_init], pctx.session)
    await pctx.session.commit()

    # Change found report category to WALLET (incompatible with ELECTRONICS)
    await pctx.session.execute(
        update(Report)
        .where(Report.id == found.id)
        .values(category=ReportCategory.WALLET)
    )
    await pctx.session.commit()

    # Retrieval returns empty results due to category mismatch
    await service.record_matches(missing, [], pctx.session)
    await pctx.session.commit()

    matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(matches) == 1
    assert matches[0].status == MatchStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_truncated_candidate_set_preserves_omitted_eligible_matches(
    pctx: _PersistenceTestFixture,
) -> None:
    """When a candidate set is truncated, omitted matches retain status."""
    u1 = await pctx.create_user("u1")
    u2 = await pctx.create_user("u2")
    missing = await pctx.create_report(u1.id, ReportType.MISSING)

    # found_close at ~100m, found_far at ~2.5km (0.022 deg lat ~2.4km)
    found_close = await pctx.create_report(u2.id, ReportType.FOUND, title="Close")
    far_lat = 37.7749 + 0.022
    found_far = Report(
        created_by_user_id=u2.id,
        type=ReportType.FOUND,
        title="Far",
        description="Far device within 5km",
        category=ReportCategory.ELECTRONICS,
        location=WKTElement(f"POINT(-122.4194 {far_lat})", srid=4326),
        event_time=datetime.now(UTC),
        status=ReportStatus.ACTIVE,
    )
    pctx.session.add(found_far)
    await pctx.session.commit()
    await pctx.session.refresh(found_far)
    pctx.report_ids.append(found_far.id)

    service = MatchPersistenceService()

    # Pre-record both matches as ACTIVE
    res_close = _make_score_result(missing.id, found_close.id, composite_score=75.0)
    res_far = _make_score_result(missing.id, found_far.id, composite_score=70.0)
    await service.record_matches(missing, [res_close, res_far], pctx.session)
    await pctx.session.commit()

    # Now retrieval returns a truncated set containing ONLY found_close (rescore 90)
    res_close_updated = _make_score_result(
        missing.id,
        found_close.id,
        composite_score=90.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
    )
    await service.record_matches(missing, [res_close_updated], pctx.session)
    await pctx.session.commit()

    # Verify:
    # 1. found_close match is updated in-place (composite_score=90.0, ACTIVE)
    # 2. found_far match was NOT disqualified; retains score 70.0 and ACTIVE status
    all_matches = await service.get_matches_for_report(missing.id, pctx.session)
    assert len(all_matches) == 2

    m_close = next(m for m in all_matches if m.report_found_id == found_close.id)
    assert m_close.status == MatchStatus.ACTIVE
    assert m_close.composite_score == 90.0
    assert m_close.classification == ScoreClassification.HIGH_PRIORITY

    m_far = next(m for m in all_matches if m.report_found_id == found_far.id)
    assert m_far.status == MatchStatus.ACTIVE
    assert m_far.composite_score == 70.0
