"""Data models and score breakdowns for Boomerang Matching Engine (Phase 8.3).

Formalized in docs/matching_specification.md (Phase 8.1).
Defines structured, explainable breakdowns for identity, characteristics,
distance, time, and composite ranking scores.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime


class ScoreClassification(enum.StrEnum):
    """Classification bands for composite match score."""

    HIGH_PRIORITY = "HIGH_PRIORITY"  # 80 - 100
    POSSIBLE_MATCH = "POSSIBLE_MATCH"  # 60 - 79
    LOW_CONFIDENCE = "LOW_CONFIDENCE"  # 40 - 59
    DISQUALIFIED = "DISQUALIFIED"  # Below 40 (Suppressed)


@dataclass(frozen=True, slots=True)
class IdentityBreakdown:
    """Component score breakdown for Signal I (Item Identity).

    Attributes:
        score: Total identity similarity score in [0.0, 100.0].
        category_score: Category alignment points (max 40.0).
        brand_model_score: Brand/model overlap points (max 40.0).
        title_noun_score: Core title noun alignment points (max 20.0).
        matched_category: Compatible category name if matched.
        matched_brand: Brand name token identified if matched.
        matched_model: Model name/number token identified if matched.
        matched_title_tokens: Specific title noun tokens matched.
        is_other_cross_category: True if comparing OTHER with a specific category.
        other_confidence_eligible: True if cross-category rule is met (I >= 60).
    """

    score: float
    category_score: float
    brand_model_score: float
    title_noun_score: float
    matched_category: str | None = None
    matched_brand: str | None = None
    matched_model: str | None = None
    matched_title_tokens: list[str] = field(default_factory=list)
    is_other_cross_category: bool = False
    other_confidence_eligible: bool = True


@dataclass(frozen=True, slots=True)
class CharacteristicsBreakdown:
    """Component score breakdown for Signal C (Physical Characteristics).

    Attributes:
        score: Total characteristics similarity score in [0.0, 100.0].
        matched_colors: List of confirmed overlapping color descriptors.
        conflicting_colors: List of conflicting color descriptors.
        matched_cases: List of overlapping case or cover descriptors.
        matched_accessories: List of overlapping accessory tokens.
        matched_distinctive_marks: List of unique markings/scratches matched.
        conflicting_marks: List of conflicting marks or features.
        is_sparse: True if triggered anti-sparse guard (< 15 chars description).
        has_contradiction: True if direct conflicting attributes were detected.
    """

    score: float
    matched_colors: list[str] = field(default_factory=list)
    conflicting_colors: list[str] = field(default_factory=list)
    matched_cases: list[str] = field(default_factory=list)
    matched_accessories: list[str] = field(default_factory=list)
    matched_distinctive_marks: list[str] = field(default_factory=list)
    conflicting_marks: list[str] = field(default_factory=list)
    is_sparse: bool = False
    has_contradiction: bool = False


@dataclass(frozen=True, slots=True)
class DistanceBreakdown:
    """Component score breakdown for Signal D (Geographic Distance).

    Attributes:
        score: Proximity score in [0.0, 100.0] via linear decay rule.
        distance_meters: Accurate distance in metres computed by PostGIS.
        distance_km: Distance in kilometres rounded to 2 decimal places.
    """

    score: float
    distance_meters: float
    distance_km: float


@dataclass(frozen=True, slots=True)
class TimeBreakdown:
    """Component score breakdown for Signal T (Incident-Time Compatibility).

    Attributes:
        score: Temporal compatibility score in [0.0, 100.0].
        loss_time: Loss incident timestamp (from MISSING report).
        found_time: Discovery incident timestamp (from FOUND report).
        delta_seconds: Time delta (found - missing) in elapsed seconds.
        delta_hours: Time delta (found - missing) in hours.
        delta_days: Time delta (found - missing) in days.
        is_negative_delta: True if found timestamp preceded missing timestamp.
        is_missing_time: True if either report lacked an incident timestamp.
    """

    score: float
    loss_time: datetime | None
    found_time: datetime | None
    delta_seconds: float | None = None
    delta_hours: float | None = None
    delta_days: float | None = None
    is_negative_delta: bool = False
    is_missing_time: bool = False


@dataclass(frozen=True, slots=True)
class MatchScoreResult:
    """Structured, explainable evaluation result for a candidate match pair.

    Attributes:
        source_id: UUID of the source report.
        candidate_id: UUID of the candidate report.
        identity: Detailed identity signal breakdown (Signal I).
        characteristics: Detailed physical characteristics breakdown (Signal C).
        distance: Detailed distance signal breakdown (Signal D).
        time: Detailed temporal signal breakdown (Signal T).
        raw_composite_score: Pre-penalty weighted composite score.
        contradiction_penalty: Points deducted due to contradictory attributes.
        composite_score: Final clamped composite score in [0.0, 100.0].
        classification: Ranking band classification.
        alert_eligible: Whether candidate satisfies all rules for user alerting.
        minimum_evidence_satisfied: Whether minimum evidence requirement is met.
        evidence_summary: Human-readable explanation of score and evidence.
        ineligibility_reasons: Detailed list of reasons if candidate is ineligible.
    """

    source_id: uuid.UUID
    candidate_id: uuid.UUID
    identity: IdentityBreakdown
    characteristics: CharacteristicsBreakdown
    distance: DistanceBreakdown
    time: TimeBreakdown
    raw_composite_score: float
    contradiction_penalty: float
    composite_score: float
    classification: ScoreClassification
    alert_eligible: bool
    minimum_evidence_satisfied: bool
    evidence_summary: str
    ineligibility_reasons: list[str] = field(default_factory=list)
