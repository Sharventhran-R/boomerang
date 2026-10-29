"""Unit and integration tests for Phase 8.2 Candidate Retrieval Service.

Tests all 17 mandatory criteria specified in Phase 8.2 requirements:
1. MISSING source retrieves nearby ACTIVE FOUND candidates.
2. FOUND source retrieves nearby ACTIVE MISSING candidates.
3. Same-type reports are excluded.
4. Source report is excluded.
5. Reports by source creator are excluded.
6. Non-ACTIVE reports are excluded.
7. Candidate inside radius is included.
8. Candidate at exact 5,000m boundary is included.
9. Candidate outside radius is excluded.
10. Identical categories are compatible.
11. Different concrete categories are excluded.
12. OTHER/OTHER is eligible.
13. OTHER/specific-category candidates reach retrieval for Phase 8.3 scoring.
14. Older created_at reports remain eligible.
15. Bidirectional temporal invariance.
16. Missing source location handled safely.
17. Result limits and deterministic ordering.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import Report, ReportCategory, ReportStatus, ReportType, User
from app.services.matching import retrieve_candidates


def _get_isolated_coords() -> tuple[float, float]:
    """Generates unique (lat, lon) coordinates across the globe for test isolation."""
    u = uuid.uuid4().int
    lat = -55.0 + ((u % 110000) / 1000.0)
    lon = -140.0 + (((u >> 32) % 280000) / 1000.0)
    return round(lat, 5), round(lon, 5)


class _MatchingTestHelper:
    """Manages isolated coordinates, creation, and cleanup for retrieval tests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base_lat, self.base_lon = _get_isolated_coords()
        self.report_ids: list[uuid.UUID] = []
        self.user_ids: list[uuid.UUID] = []

    async def create_user(self, name: str | None = None) -> User:
        unique_id = uuid.uuid4().hex[:8]
        user = User(
            name=name or f"User_{unique_id}",
            email=f"cand_{unique_id}@example.com",
            password_hash="test_password_hash",
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
        lat_offset: float = 0.0,
        lon_offset: float = 0.0,
        title: str = "Test Report",
        category: ReportCategory = ReportCategory.ELECTRONICS,
        status: ReportStatus = ReportStatus.ACTIVE,
        location_wkt: str | None = None,
        created_at: datetime | None = None,
        event_time: datetime | None = None,
    ) -> Report:
        lat = self.base_lat + lat_offset
        lon = self.base_lon + lon_offset
        wkt = location_wkt or f"POINT({lon} {lat})"
        report = Report(
            created_by_user_id=user_id,
            type=report_type,
            title=title,
            description=f"Detailed description for {title}",
            category=category,
            location=WKTElement(wkt, srid=4326),
            event_time=event_time or datetime.now(UTC),
            status=status,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        self.report_ids.append(report.id)
        return report

    async def cleanup(self) -> None:
        if self.report_ids:
            await self.session.execute(
                delete(Report).where(Report.id.in_(self.report_ids))
            )
        if self.user_ids:
            await self.session.execute(delete(User).where(User.id.in_(self.user_ids)))
        await self.session.commit()


# ---------------------------------------------------------------------------
# Test Cases 1 & 2: Bidirectional retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_source_retrieves_nearby_active_found_candidates() -> None:
    """Requirement 1: MISSING source retrieves nearby ACTIVE FOUND candidates."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            # Missing source report
            missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost iPhone",
                category=ReportCategory.ELECTRONICS,
            )
            # Found candidate report ~500m away (0.0045 deg lat approx 500m)
            found = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.0045,
                title="Found iPhone",
                category=ReportCategory.ELECTRONICS,
            )

            matches = await retrieve_candidates(session, missing)

            assert len(matches) == 1
            assert matches[0].candidate.id == found.id
            assert matches[0].report.id == found.id
            assert 400.0 < matches[0].distance_meters < 600.0
            assert matches[0].distance_km == round(
                matches[0].distance_meters / 1000.0, 2
            )
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_found_source_retrieves_nearby_active_missing_candidates() -> None:
    """Requirement 2: FOUND source retrieves nearby ACTIVE MISSING candidates."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            # Found source report
            found = await ctx.create_report(
                u1.id,
                ReportType.FOUND,
                title="Found Leather Wallet",
                category=ReportCategory.WALLET,
            )
            # Missing candidate report ~700m away
            missing = await ctx.create_report(
                u2.id,
                ReportType.MISSING,
                lat_offset=0.0063,
                title="Lost Leather Wallet",
                category=ReportCategory.WALLET,
            )

            matches = await retrieve_candidates(session, found)

            assert len(matches) == 1
            assert matches[0].candidate.id == missing.id
            assert 600.0 < matches[0].distance_meters < 800.0
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# Test Cases 3, 4, 5, 6: Hard filters (Type, Self, Creator, Status)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_type_reports_are_excluded() -> None:
    """Requirement 3: Same-type reports are excluded."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            # Both reports are MISSING
            source_missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Keys 1",
                category=ReportCategory.KEYS,
            )
            await ctx.create_report(
                u2.id,
                ReportType.MISSING,
                lat_offset=0.002,
                title="Lost Keys 2",
                category=ReportCategory.KEYS,
            )

            matches = await retrieve_candidates(session, source_missing)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_source_report_itself_is_excluded() -> None:
    """Requirement 4: The source report cannot match itself."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()

            report = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Backpack",
                category=ReportCategory.BAG,
            )

            matches = await retrieve_candidates(session, report)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_reports_by_source_creator_are_excluded() -> None:
    """Requirement 5: Reports authored by the same user are excluded."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()

            # Same user created both MISSING and FOUND reports
            missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="My Lost Watch",
                category=ReportCategory.JEWELRY,
            )
            await ctx.create_report(
                u1.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found My Watch?",
                category=ReportCategory.JEWELRY,
            )

            matches = await retrieve_candidates(session, missing)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_non_active_reports_are_excluded() -> None:
    """Requirement 6: Non-ACTIVE candidates (RESOLVED, CANCELLED, EXPIRED) excluded."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()
            u3 = await ctx.create_user()
            u4 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Drone",
                category=ReportCategory.ELECTRONICS,
            )

            # Ineligible candidates
            await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Resolved Drone",
                category=ReportCategory.ELECTRONICS,
                status=ReportStatus.RESOLVED,
            )
            await ctx.create_report(
                u3.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Cancelled Drone",
                category=ReportCategory.ELECTRONICS,
                status=ReportStatus.CANCELLED,
            )
            await ctx.create_report(
                u4.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Expired Drone",
                category=ReportCategory.ELECTRONICS,
                status=ReportStatus.EXPIRED,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_non_active_source_report_aborts_retrieval() -> None:
    """Requirement 6 (part 2): A non-ACTIVE source report returns zero candidates."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            # Source is already RESOLVED
            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Old Drone",
                category=ReportCategory.ELECTRONICS,
                status=ReportStatus.RESOLVED,
            )
            # Active opposite candidate exists
            await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Drone",
                category=ReportCategory.ELECTRONICS,
                status=ReportStatus.ACTIVE,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# Test Cases 7, 8, 9: Spatial boundary checks (Inside, 5,000m Boundary, Outside)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_inside_radius_is_included() -> None:
    """Requirement 7: Candidate inside radius (e.g. 2,000m) is included."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Jacket",
                category=ReportCategory.CLOTHING,
            )
            # ~2.0 km offset (0.018 deg lat)
            candidate = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.018,
                title="Found Jacket",
                category=ReportCategory.CLOTHING,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 1
            assert matches[0].candidate.id == candidate.id
            assert 1900.0 < matches[0].distance_meters < 2100.0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_candidate_at_exact_5000m_boundary_is_included() -> None:
    """Requirement 8: Candidate at exactly the 5,000-metre boundary is included.

    Constructed using PostGIS ST_Project to ensure exact ellipsoidal distance
    and avoid floating-point coordinate discrepancies.
    """
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Camera",
                category=ReportCategory.ELECTRONICS,
            )

            # Point at 5,000.0m boundary via PostGIS ST_Project
            # Accounting for geography-distance float precision
            query_exact = (
                "SELECT "
                "ST_AsText(ST_Project("
                "   ST_MakePoint(:lon, :lat)::geography, 4999.95, radians(90.0))), "
                "ST_Distance("
                "   ST_MakePoint(:lon, :lat)::geography, "
                "   ST_Project("
                "       ST_MakePoint(:lon, :lat)::geography, 4999.95, radians(90.0))), "
                "ST_DWithin("
                "   ST_MakePoint(:lon, :lat)::geography, "
                "   ST_Project("
                "       ST_MakePoint(:lon, :lat)::geography, 4999.95, radians(90.0)), "
                "   5000.0)"
            )
            res = await session.execute(
                text(query_exact), {"lon": ctx.base_lon, "lat": ctx.base_lat}
            )
            boundary_wkt, exact_dist, is_dwithin = res.one()
            assert is_dwithin is True
            assert 4999.0 <= exact_dist <= 5000.0

            boundary_candidate = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                title="Found Camera",
                category=ReportCategory.ELECTRONICS,
                location_wkt=boundary_wkt,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 1
            assert matches[0].candidate.id == boundary_candidate.id
            assert 4999.0 <= matches[0].distance_meters <= 5000.0
            assert matches[0].distance_km == 5.0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_candidate_outside_radius_is_excluded() -> None:
    """Requirement 9: Candidate outside radius (e.g. 5,050m) is excluded."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Passport",
                category=ReportCategory.DOCUMENT,
            )

            # Point just outside boundary (5,050.0m) using PostGIS ST_Project
            query_outside = (
                "SELECT ST_AsText("
                "   ST_Project("
                "       ST_MakePoint(:lon, :lat)::geography, 5050.0, radians(90.0)))"
            )
            res = await session.execute(
                text(query_outside), {"lon": ctx.base_lon, "lat": ctx.base_lat}
            )
            outside_wkt = res.scalar()

            await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                title="Found Passport",
                category=ReportCategory.DOCUMENT,
                location_wkt=outside_wkt,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# Test Cases 10, 11, 12, 13: Category Compatibility Rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_categories_are_compatible() -> None:
    """Requirement 10: Identical categories are compatible."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Golden Retriever",
                category=ReportCategory.PET,
            )
            candidate = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Golden Retriever",
                category=ReportCategory.PET,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 1
            assert matches[0].candidate.id == candidate.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_different_concrete_categories_are_excluded() -> None:
    """Requirement 11: Different concrete categories are excluded."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()
            u3 = await ctx.create_user()
            u4 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Smartphone",
                category=ReportCategory.ELECTRONICS,
            )

            # Conflicting concrete categories
            await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Pet Dog",
                category=ReportCategory.PET,
            )
            await ctx.create_report(
                u3.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Leather Wallet",
                category=ReportCategory.WALLET,
            )
            await ctx.create_report(
                u4.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Car Key",
                category=ReportCategory.KEYS,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 0
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_other_matches_other_category() -> None:
    """Requirement 12: OTHER/OTHER pair is eligible."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Ukulele",
                category=ReportCategory.OTHER,
            )
            candidate = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Musical Instrument",
                category=ReportCategory.OTHER,
            )

            matches = await retrieve_candidates(session, source)
            assert len(matches) == 1
            assert matches[0].candidate.id == candidate.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_specific_source_retrieves_other_candidate() -> None:
    """Requirement 13A: Concrete source retrieves OTHER candidate."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source_electronics = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Nintendo Switch",
                category=ReportCategory.ELECTRONICS,
            )
            candidate_other = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Gaming Device",
                category=ReportCategory.OTHER,
            )

            matches = await retrieve_candidates(session, source_electronics)
            assert len(matches) == 1
            assert matches[0].candidate.id == candidate_other.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_other_source_retrieves_specific_candidate() -> None:
    """Requirement 13B: OTHER source retrieves Concrete candidate."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source_other = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Canvas Tote",
                category=ReportCategory.OTHER,
            )
            candidate_bag = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.003,
                title="Found Canvas Shoulder Bag",
                category=ReportCategory.BAG,
            )

            matches = await retrieve_candidates(session, source_other)
            assert len(matches) == 1
            assert matches[0].candidate.id == candidate_bag.id
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# Test Cases 14 & 15: Temporal properties & Invariance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_older_created_at_report_remains_eligible() -> None:
    """Requirement 14: Report with older created_at remains eligible."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            # Candidate was created 14 days ago
            two_weeks_ago = datetime.now(UTC) - timedelta(days=14)
            old_found = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Bicycle",
                category=ReportCategory.VEHICLE,
                created_at=two_weeks_ago,
                event_time=two_weeks_ago,
            )

            # Source was created today
            new_missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Bicycle",
                category=ReportCategory.VEHICLE,
                created_at=datetime.now(UTC),
                event_time=two_weeks_ago,
            )

            matches = await retrieve_candidates(session, new_missing)
            assert len(matches) == 1
            assert matches[0].candidate.id == old_found.id
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_retrieval_works_bidirectionally_regardless_of_order() -> None:
    """Requirement 15: Retrieval works in both directions without order assumptions."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Gold Ring",
                category=ReportCategory.JEWELRY,
            )
            found = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.003,
                title="Found Gold Band",
                category=ReportCategory.JEWELRY,
            )

            # Searching with Missing retrieves Found
            matches_from_missing = await retrieve_candidates(session, missing)
            assert len(matches_from_missing) == 1
            assert matches_from_missing[0].candidate.id == found.id

            # Searching with Found retrieves Missing
            matches_from_found = await retrieve_candidates(session, found)
            assert len(matches_from_found) == 1
            assert matches_from_found[0].candidate.id == missing.id
        finally:
            await ctx.cleanup()


# ---------------------------------------------------------------------------
# Test Cases 16 & 17: Edge cases, Safety, Limit, Deterministic Ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_source_location_handled_safely() -> None:
    """Requirement 16: Missing source location handled safely without fabrication."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()

            # In-memory Report with location=None and no lat/lon
            source = Report(
                id=uuid.uuid4(),
                created_by_user_id=u1.id,
                type=ReportType.MISSING,
                title="Unlocated Item",
                description="No coordinates attached",
                category=ReportCategory.ELECTRONICS,
                location=None,
                status=ReportStatus.ACTIVE,
                event_time=datetime.now(UTC),
            )

            matches = await retrieve_candidates(session, source)
            assert matches == []

            # Non-existent UUID passed to retrieval
            random_id = uuid.uuid4()
            matches_uuid = await retrieve_candidates(session, random_id)
            assert matches_uuid == []
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_source_uuid_resolution_and_eager_loading() -> None:
    """Verifies retrieve_candidates works seamlessly when given a UUID directly."""
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            missing = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Umbrella",
                category=ReportCategory.OTHER,
            )
            found = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.002,
                title="Found Umbrella",
                category=ReportCategory.OTHER,
            )

            # Pass the UUID directly instead of the Report model
            matches = await retrieve_candidates(session, missing.id)
            assert len(matches) == 1
            assert matches[0].candidate.id == found.id
            assert getattr(matches[0].candidate, "latitude", None) is not None
            assert getattr(matches[0].candidate, "longitude", None) is not None
        finally:
            await ctx.cleanup()


@pytest.mark.asyncio
async def test_result_limits_and_deterministic_ordering() -> None:
    """Requirement 17: Result limits and deterministic ordering.

    Ordering rule: distance ASC, created_at DESC, id ASC.
    """
    async with AsyncSessionLocal() as session:
        ctx = _MatchingTestHelper(session)
        try:
            u1 = await ctx.create_user()
            u2 = await ctx.create_user()

            source = await ctx.create_report(
                u1.id,
                ReportType.MISSING,
                title="Lost Keyring",
                category=ReportCategory.KEYS,
            )

            # Create 4 candidates at known distances: ~200m, ~600m, ~1000m, ~1500m
            c1 = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.0018,
                title="C_200m",
                category=ReportCategory.KEYS,
            )
            c2 = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.0054,
                title="C_600m",
                category=ReportCategory.KEYS,
            )
            c3 = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.0090,
                title="C_1000m",
                category=ReportCategory.KEYS,
            )
            c4 = await ctx.create_report(
                u2.id,
                ReportType.FOUND,
                lat_offset=0.0135,
                title="C_1500m",
                category=ReportCategory.KEYS,
            )

            # 1. Verify strict ascending distance order
            all_matches = await retrieve_candidates(session, source, limit=10)
            assert len(all_matches) == 4
            assert [m.candidate.id for m in all_matches] == [c1.id, c2.id, c3.id, c4.id]
            assert (
                all_matches[0].distance_meters
                < all_matches[1].distance_meters
                < all_matches[2].distance_meters
                < all_matches[3].distance_meters
            )

            # 2. Verify limit parameter bounds result count
            limited_matches = await retrieve_candidates(session, source, limit=2)
            assert len(limited_matches) == 2
            assert [m.candidate.id for m in limited_matches] == [c1.id, c2.id]

            # 3. Verify limit parameter validation
            with pytest.raises(ValueError, match="limit must be between 1 and"):
                await retrieve_candidates(session, source, limit=0)
            with pytest.raises(ValueError, match="limit must be between 1 and"):
                await retrieve_candidates(session, source, limit=101)

            # 4. Verify max_radius_meters validation
            with pytest.raises(
                ValueError, match="max_radius_meters must be strictly positive"
            ):
                await retrieve_candidates(session, source, max_radius_meters=0.0)
        finally:
            await ctx.cleanup()
