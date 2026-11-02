"""FastAPI endpoints for Boomerang Match engine (Phase 8.6).

Provides authenticated, paginated match candidate listings and match detail
inspection with full explainability breakdowns and strict ownership authorization.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2 import Geometry
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import (
    Match,
    MatchStatus,
    Report,
    ReportType,
    ScoreClassification,
    User,
)
from app.schemas.match import (
    MatchDetailResponse,
    MatchListItemResponse,
    MatchListResponse,
    MatchReportSummary,
)

matches_router = APIRouter()


@matches_router.get(
    "/reports/{report_id}/matches",
    response_model=MatchListResponse,
    summary="List active matches for a user's report",
)
async def list_report_matches(
    report_id: uuid.UUID,
    classification: ScoreClassification | None = Query(
        None, description="Optional score classification filter"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """List active match candidates for a report owned by the authenticated user.

    Supports both MISSING and FOUND reports. Returns only ACTIVE matches in
    deterministic order (composite_score DESC, created_at DESC, id ASC).
    """
    # 1. Verify report existence and ownership
    report_stmt = select(Report).where(Report.id == report_id)
    report_result = await db.execute(report_stmt)
    report = report_result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access matches for this report",
        )

    # 2. Determine match direction and join opposite report
    OppositeReport = aliased(Report, name="opp_report")

    if report.type == ReportType.MISSING:
        match_filter = Match.report_missing_id == report_id
        join_condition = Match.report_found_id == OppositeReport.id
    else:
        match_filter = Match.report_found_id == report_id
        join_condition = Match.report_missing_id == OppositeReport.id

    conditions = [match_filter, Match.status == MatchStatus.ACTIVE]
    if classification is not None:
        conditions.append(Match.classification == classification)

    # 3. Total count query
    count_stmt = select(func.count(Match.id)).where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # 4. Paginated data query with coordinates and relationships
    data_stmt = (
        select(
            Match,
            func.ST_Y(OppositeReport.location.cast(Geometry)).label("opp_lat"),
            func.ST_X(OppositeReport.location.cast(Geometry)).label("opp_lon"),
        )
        .join(OppositeReport, join_condition)
        .options(
            selectinload(Match.report_missing).selectinload(Report.images),
            selectinload(Match.report_found).selectinload(Report.images),
        )
        .where(*conditions)
        .order_by(
            desc(Match.composite_score),
            desc(Match.created_at),
            asc(Match.id),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items_result = await db.execute(data_stmt)
    rows = items_result.all()

    items: list[MatchListItemResponse] = []
    for match, opp_lat, opp_lon in rows:
        opp_report = (
            match.report_found
            if report.type == ReportType.MISSING
            else match.report_missing
        )

        dist_km: float | None = None
        if isinstance(match.explainability_details, dict):
            dist_data = match.explainability_details.get("distance")
            if isinstance(dist_data, dict):
                dist_km = dist_data.get("distance_km")

        opposite_summary = MatchReportSummary(
            id=opp_report.id,
            type=opp_report.type,
            title=opp_report.title,
            description=opp_report.description,
            category=opp_report.category,
            latitude=float(opp_lat),
            longitude=float(opp_lon),
            event_time=opp_report.event_time,
            reward_amount=opp_report.reward_amount,
            status=opp_report.status,
            created_at=opp_report.created_at,
            distance_km=dist_km,
            images=opp_report.images,
        )

        items.append(
            MatchListItemResponse(
                id=match.id,
                report_missing_id=match.report_missing_id,
                report_found_id=match.report_found_id,
                status=match.status,
                composite_score=match.composite_score,
                score_identity=match.score_identity,
                score_characteristics=match.score_characteristics,
                score_distance=match.score_distance,
                score_time=match.score_time,
                classification=match.classification,
                alert_eligible=match.alert_eligible,
                evidence_summary=match.evidence_summary,
                opposite_report=opposite_summary,
                created_at=match.created_at,
                last_scored_at=match.last_scored_at,
            )
        )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return MatchListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@matches_router.get(
    "/matches/{match_id}",
    response_model=MatchDetailResponse,
    summary="Get match details and explainability breakdown",
)
async def get_match_detail(
    match_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Retrieve full match details with subscore and evidence breakdown.

    Requires the authenticated user to be the creator of either the missing
    or found report in the match.
    """
    ReportMissing = aliased(Report, name="missing_rep")
    ReportFound = aliased(Report, name="found_rep")

    stmt = (
        select(
            Match,
            func.ST_Y(ReportMissing.location.cast(Geometry)).label("missing_lat"),
            func.ST_X(ReportMissing.location.cast(Geometry)).label("missing_lon"),
            func.ST_Y(ReportFound.location.cast(Geometry)).label("found_lat"),
            func.ST_X(ReportFound.location.cast(Geometry)).label("found_lon"),
        )
        .join(ReportMissing, Match.report_missing_id == ReportMissing.id)
        .join(ReportFound, Match.report_found_id == ReportFound.id)
        .options(
            selectinload(Match.report_missing).selectinload(Report.images),
            selectinload(Match.report_found).selectinload(Report.images),
        )
        .where(Match.id == match_id)
    )

    result = await db.execute(stmt)
    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match not found",
        )

    match, missing_lat, missing_lon, found_lat, found_lon = row

    owns_missing = match.report_missing.created_by_user_id == current_user.id
    owns_found = match.report_found.created_by_user_id == current_user.id

    if not owns_missing and not owns_found:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this match",
        )

    user_role = (
        "BOTH"
        if (owns_missing and owns_found)
        else ("MISSING" if owns_missing else "FOUND")
    )

    dist_km: float | None = None
    if isinstance(match.explainability_details, dict):
        dist_data = match.explainability_details.get("distance")
        if isinstance(dist_data, dict):
            dist_km = dist_data.get("distance_km")

    missing_summary = MatchReportSummary(
        id=match.report_missing.id,
        type=match.report_missing.type,
        title=match.report_missing.title,
        description=match.report_missing.description,
        category=match.report_missing.category,
        latitude=float(missing_lat),
        longitude=float(missing_lon),
        event_time=match.report_missing.event_time,
        reward_amount=match.report_missing.reward_amount,
        status=match.report_missing.status,
        created_at=match.report_missing.created_at,
        distance_km=dist_km,
        images=match.report_missing.images,
    )

    found_summary = MatchReportSummary(
        id=match.report_found.id,
        type=match.report_found.type,
        title=match.report_found.title,
        description=match.report_found.description,
        category=match.report_found.category,
        latitude=float(found_lat),
        longitude=float(found_lon),
        event_time=match.report_found.event_time,
        reward_amount=match.report_found.reward_amount,
        status=match.report_found.status,
        created_at=match.report_found.created_at,
        distance_km=dist_km,
        images=match.report_found.images,
    )

    return MatchDetailResponse(
        id=match.id,
        status=match.status,
        composite_score=match.composite_score,
        raw_composite_score=match.raw_composite_score,
        contradiction_penalty=match.contradiction_penalty,
        score_identity=match.score_identity,
        score_characteristics=match.score_characteristics,
        score_distance=match.score_distance,
        score_time=match.score_time,
        classification=match.classification,
        alert_eligible=match.alert_eligible,
        minimum_evidence_satisfied=match.minimum_evidence_satisfied,
        evidence_summary=match.evidence_summary,
        explainability_details=match.explainability_details,
        scoring_version=match.scoring_version,
        last_scored_at=match.last_scored_at,
        created_at=match.created_at,
        updated_at=match.updated_at,
        report_missing=missing_summary,
        report_found=found_summary,
        user_role=user_role,
    )

