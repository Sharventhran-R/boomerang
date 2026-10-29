"""Candidate retrieval service for Boomerang Missing/Found Matching Engine (Phase 8.2).

Formalized in docs/matching_specification.md (Phase 8.1).
Implements spatial candidate retrieval across opposite report types within 5,000 metres.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Report, ReportCategory, ReportStatus, ReportType

logger = logging.getLogger(__name__)

MATCHING_RADIUS_METERS: float = 5000.0
DEFAULT_CANDIDATE_LIMIT: int = 50
MAX_CANDIDATE_LIMIT: int = 100


@dataclass(frozen=True)
class CandidateMatch:
    """Represents an eligible matching candidate retrieved from the database.

    Attributes:
        report: The candidate Report model instance.
        distance_meters: Accurate distance in metres computed by PostGIS.
    """

    report: Report
    distance_meters: float

    @property
    def candidate(self) -> Report:
        """Alias for report to clarify role in matching pairs."""
        return self.report

    @property
    def distance_km(self) -> float:
        """Distance in kilometres, rounded to 2 decimal places."""
        return round(self.distance_meters / 1000.0, 2)


async def retrieve_candidates(
    db: AsyncSession,
    source: Report | uuid.UUID,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    max_radius_meters: float = MATCHING_RADIUS_METERS,
) -> list[CandidateMatch]:
    """Retrieves eligible candidate reports within the matching radius.

    Enforces all Phase 8.1 candidate eligibility hard filters:
    - HF-1: Opposite report types (MISSING searches FOUND; FOUND searches MISSING).
    - HF-2: Excludes the source report itself and reports authored by the same user.
    - HF-3: Both source and candidate reports must have ACTIVE lifecycle status.
    - HF-4: Uses Report.location as authoritative incident coordinates.
    - HF-5: Enforces inclusive 5,000-metre boundary via PostGIS ST_DWithin.
    - HF-6: Excludes incompatible concrete categories while allowing OTHER
            cross-category pairs through retrieval for later Phase 8.3 scoring.
    - HF-7: Uses only public report fields (no credentials or verification info).

    Args:
        db: Active SQLAlchemy async session.
        source: Source Report model or its UUID.
        limit: Max candidates to retrieve (between 1 and MAX_CANDIDATE_LIMIT).
        max_radius_meters: Inclusive radius threshold in metres (default 5,000.0m).

    Returns:
        List of CandidateMatch instances sorted deterministically by:
        1. Distance ascending (closest first)
        2. Creation time descending (newest first among equal distance)
        3. Report ID ascending (tiebreaker)

    Raises:
        ValueError: If limit is not within [1, MAX_CANDIDATE_LIMIT] or radius <= 0.
    """
    if limit < 1 or limit > MAX_CANDIDATE_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_CANDIDATE_LIMIT}, got {limit}"
        )

    if max_radius_meters <= 0:
        raise ValueError(
            f"max_radius_meters must be strictly positive, got {max_radius_meters}"
        )

    # 1. Resolve source report
    source_report: Report | None
    if isinstance(source, uuid.UUID):
        stmt = (
            select(
                Report,
                func.ST_Y(Report.location.cast(Geometry)).label("latitude"),
                func.ST_X(Report.location.cast(Geometry)).label("longitude"),
            )
            .options(selectinload(Report.images))
            .where(Report.id == source)
        )
        res = await db.execute(stmt)
        row = res.first()
        if not row:
            logger.debug(
                "Candidate retrieval aborted: source report %s not found", source
            )
            return []
        source_report, s_lat, s_lon = row
        setattr(source_report, "latitude", s_lat)
        setattr(source_report, "longitude", s_lon)
    else:
        source_report = source

    # 2. Hard filter: source report must have ACTIVE status
    if source_report.status != ReportStatus.ACTIVE:
        logger.debug(
            "Candidate retrieval skipped: source report %s has non-ACTIVE status %s",
            source_report.id,
            source_report.status,
        )
        return []

    # 3. Hard filter: source report location must be present
    source_location: Any = getattr(source_report, "location", None)
    if source_location is None:
        lat = getattr(source_report, "latitude", None)
        lon = getattr(source_report, "longitude", None)
        if lat is not None and lon is not None:
            source_location = WKTElement(f"POINT({lon} {lat})", srid=4326)
        else:
            logger.warning(
                "Candidate retrieval skipped: source report %s has missing coordinates",
                source_report.id,
            )
            return []

    # 4. Determine target opposite report type
    target_type = (
        ReportType.FOUND
        if source_report.type == ReportType.MISSING
        else ReportType.MISSING
    )

    # 5. Assemble PostGIS filters
    filters = [
        Report.type == target_type,
        Report.status == ReportStatus.ACTIVE,
        func.ST_DWithin(Report.location, source_location, max_radius_meters),
    ]

    # Exclude self and same creator if identifiers are present
    if source_report.id is not None:
        filters.append(Report.id != source_report.id)
    if source_report.created_by_user_id is not None:
        filters.append(Report.created_by_user_id != source_report.created_by_user_id)

    # Category compatibility (HF-6):
    # - If source is OTHER, all candidate categories are eligible for retrieval.
    # - If source is a concrete category, candidate must match source category or OTHER.
    # Phase 8.3 identity scorer enforces the >= 60 confidence threshold on OTHER pairs.
    if source_report.category != ReportCategory.OTHER:
        filters.append(
            Report.category.in_([source_report.category, ReportCategory.OTHER])
        )

    # Distance calculation column (metres on geography)
    distance_col = func.ST_Distance(Report.location, source_location).label(
        "distance_meters"
    )

    # 6. Execute deterministic query
    query = (
        select(
            Report,
            func.ST_Y(Report.location.cast(Geometry)).label("latitude"),
            func.ST_X(Report.location.cast(Geometry)).label("longitude"),
            distance_col,
        )
        .options(selectinload(Report.images))
        .where(*filters)
        .order_by(
            asc(distance_col),
            desc(Report.created_at),
            asc(Report.id),
        )
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    candidates: list[CandidateMatch] = []
    for candidate_report, c_lat, c_lon, dist_m in rows:
        setattr(candidate_report, "latitude", c_lat)
        setattr(candidate_report, "longitude", c_lon)
        dist_val = float(dist_m) if dist_m is not None else 0.0
        setattr(candidate_report, "distance_km", round(dist_val / 1000.0, 2))
        candidates.append(
            CandidateMatch(
                report=candidate_report,
                distance_meters=dist_val,
            )
        )

    return candidates
