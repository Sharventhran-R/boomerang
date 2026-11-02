"""Pydantic schemas for Boomerang Match API endpoints (Phase 8.6).

Exposes match summaries and detailed explainability models for authenticated
report owners, with zero leakage of private user information.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models import (
    MatchStatus,
    ReportCategory,
    ReportStatus,
    ReportType,
    ScoreClassification,
)
from app.schemas.report import ReportImageResponse


class MatchReportSummary(BaseModel):
    """Public summary of a report involved in a match."""

    id: uuid.UUID
    type: ReportType
    title: str
    description: str
    category: ReportCategory
    latitude: float
    longitude: float
    event_time: datetime
    reward_amount: Decimal | None = None
    status: ReportStatus
    created_at: datetime
    distance_km: float | None = None
    images: list[ReportImageResponse] = []

    model_config = ConfigDict(from_attributes=True)


class MatchListItemResponse(BaseModel):
    """Summary item for match candidate listings."""

    id: uuid.UUID
    report_missing_id: uuid.UUID
    report_found_id: uuid.UUID
    status: MatchStatus
    composite_score: float
    score_identity: float
    score_characteristics: float
    score_distance: float
    score_time: float
    classification: ScoreClassification
    alert_eligible: bool
    evidence_summary: str
    opposite_report: MatchReportSummary
    created_at: datetime
    last_scored_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MatchListResponse(BaseModel):
    """Paginated response for match listings."""

    items: list[MatchListItemResponse]
    page: int
    page_size: int
    total: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


class MatchDetailResponse(BaseModel):
    """Comprehensive match detail response including full explainability breakdown."""

    id: uuid.UUID
    status: MatchStatus
    composite_score: float
    raw_composite_score: float
    contradiction_penalty: float
    score_identity: float
    score_characteristics: float
    score_distance: float
    score_time: float
    classification: ScoreClassification
    alert_eligible: bool
    minimum_evidence_satisfied: bool
    evidence_summary: str
    explainability_details: dict[str, Any]
    scoring_version: int
    last_scored_at: datetime
    created_at: datetime
    updated_at: datetime
    report_missing: MatchReportSummary
    report_found: MatchReportSummary
    user_role: str

    model_config = ConfigDict(from_attributes=True)

