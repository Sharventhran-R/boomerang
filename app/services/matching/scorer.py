"""Composite scoring engine for Boomerang Matching Engine (Phase 8.3).

Formalized in docs/matching_specification.md (Phase 8.1, Section 4 & 6).
Computes the multi-signal composite ranking score:
    S = 0.30 * I + 0.30 * C + 0.25 * D + 0.15 * T

Enforces:
- 25-point contradiction deductions
- OTHER category confidence guard (I >= 60 for cross-category pairs)
- Anti-sparse description caps (C <= 20)
- Identity guard (I >= 50 required for alerts)
- Minimum evidence barrier for automated alerts
- Score classification bands (High Priority, Possible Match, Low Confidence)
"""

from __future__ import annotations

import math
from typing import Final

from app.db.models import Report
from app.services.matching.characteristics import compute_characteristics_score
from app.services.matching.distance import compute_distance_score
from app.services.matching.identity import compute_identity_score
from app.services.matching.models import (
    MatchScoreResult,
    ScoreClassification,
)
from app.services.matching.retrieval import CandidateMatch
from app.services.matching.time import compute_time_score

WEIGHT_IDENTITY: Final[float] = 0.30
WEIGHT_CHARACTERISTICS: Final[float] = 0.30
WEIGHT_DISTANCE: Final[float] = 0.25
WEIGHT_TIME: Final[float] = 0.15

CONTRADICTION_PENALTY: Final[float] = 25.0
ALERT_SCORE_THRESHOLD: Final[float] = 75.0
ALERT_IDENTITY_MINIMUM: Final[float] = 50.0
ALERT_BRAND_MODEL_MINIMUM: Final[float] = 70.0
ALERT_TWO_CHARS_MINIMUM: Final[float] = 60.0


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates spherical distance between two points in metres."""
    r = 6371000.0  # Earth's mean radius in metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def score_candidate(
    source_report: Report,
    candidate: Report | CandidateMatch,
) -> MatchScoreResult:
    """Scores a candidate report against a source report with full explainability.

    Formula:
        S_raw = 0.30 * I + 0.30 * C + 0.25 * D + 0.15 * T
        S = max(0.0, min(100.0, S_raw - penalty))

    Args:
        source_report: The source Report instance.
        candidate: Either a CandidateMatch from retrieval or a Report instance.

    Returns:
        Structured MatchScoreResult with sub-scores, classification, and alert status.
    """
    cand_report: Report
    dist_meters: float

    if isinstance(candidate, CandidateMatch):
        cand_report = candidate.candidate
        dist_meters = candidate.distance_meters
    else:
        cand_report = candidate
        c_dist = getattr(candidate, "distance_meters", None)
        if c_dist is not None:
            dist_meters = float(c_dist)
        else:
            s_lat = getattr(source_report, "latitude", None)
            s_lon = getattr(source_report, "longitude", None)
            c_lat = getattr(cand_report, "latitude", None)
            c_lon = getattr(cand_report, "longitude", None)
            if (
                s_lat is not None
                and s_lon is not None
                and c_lat is not None
                and c_lon is not None
            ):
                dist_meters = _haversine_meters(s_lat, s_lon, c_lat, c_lon)
            else:
                dist_meters = 0.0

    # 1. Compute component signals
    identity = compute_identity_score(source_report, cand_report)
    characteristics = compute_characteristics_score(source_report, cand_report)
    distance = compute_distance_score(dist_meters)
    time = compute_time_score(
        source_report.event_time,
        cand_report.event_time,
        source_report.type,
        cand_report.type,
    )

    # 2. Compute raw composite score
    raw_composite = (
        WEIGHT_IDENTITY * identity.score
        + WEIGHT_CHARACTERISTICS * characteristics.score
        + WEIGHT_DISTANCE * distance.score
        + WEIGHT_TIME * time.score
    )

    # 3. Apply contradiction penalty
    contradiction_penalty: float = 0.0
    if characteristics.has_contradiction:
        contradiction_penalty = CONTRADICTION_PENALTY

    final_score = max(0.0, min(100.0, raw_composite - contradiction_penalty))

    # 4. Determine classification band
    classification: ScoreClassification
    if final_score >= 80.0:
        classification = ScoreClassification.HIGH_PRIORITY
    elif final_score >= 60.0:
        classification = ScoreClassification.POSSIBLE_MATCH
    elif final_score >= 40.0:
        classification = ScoreClassification.LOW_CONFIDENCE
    else:
        classification = ScoreClassification.DISQUALIFIED

    # 5. Evaluate alert eligibility & minimum evidence
    ineligibility_reasons: list[str] = []

    # Check minimum evidence requirement:
    # At least ONE of:
    # a. Specific brand or model match with I >= 70.0
    # b. At least two matching physical characteristics with C >= 60.0
    # c. Distinctive unique mark identified in both reports
    has_brand_model_70 = identity.score >= ALERT_BRAND_MODEL_MINIMUM and (
        identity.matched_brand is not None or identity.matched_model is not None
    )
    num_physical_chars = (
        len(characteristics.matched_colors)
        + len(characteristics.matched_cases)
        + len(characteristics.matched_accessories)
    )
    has_two_chars_60 = (
        characteristics.score >= ALERT_TWO_CHARS_MINIMUM and num_physical_chars >= 2
    )
    has_distinctive_mark = len(characteristics.matched_distinctive_marks) >= 1

    min_evidence_satisfied = (
        has_brand_model_70 or has_two_chars_60 or has_distinctive_mark
    )

    if final_score < ALERT_SCORE_THRESHOLD:
        ineligibility_reasons.append(
            f"Composite score {final_score:.1f} below threshold "
            f"{ALERT_SCORE_THRESHOLD:.0f}"
        )
    if characteristics.has_contradiction:
        ineligibility_reasons.append(
            "Disqualifying contradictory characteristics detected"
        )
    if identity.score < ALERT_IDENTITY_MINIMUM:
        ineligibility_reasons.append(
            f"Identity score {identity.score:.1f} below minimum "
            f"{ALERT_IDENTITY_MINIMUM:.0f}"
        )
    if not identity.other_confidence_eligible:
        ineligibility_reasons.append(
            f"Cross-category OTHER requires identity confidence >= 60.0, "
            f"got {identity.score:.1f}"
        )
    if not min_evidence_satisfied:
        ineligibility_reasons.append(
            "Minimum evidence requirement not satisfied (requires brand/model "
            "I>=70, 2+ chars C>=60, or unique mark)"
        )

    alert_eligible = len(ineligibility_reasons) == 0

    # 6. Build evidence summary
    evidence_parts: list[str] = []
    if identity.matched_brand or identity.matched_model:
        bm = f"{identity.matched_brand or ''} {identity.matched_model or ''}".strip()
        evidence_parts.append(f"matched {bm}")
    elif identity.matched_category:
        evidence_parts.append(f"category {identity.matched_category}")

    all_matched_chars = (
        characteristics.matched_colors
        + characteristics.matched_cases
        + characteristics.matched_accessories
        + characteristics.matched_distinctive_marks
    )
    if all_matched_chars:
        evidence_parts.append(f"shared {', '.join(all_matched_chars)}")

    evidence_parts.append(f"within {distance.distance_km:.2f} km")

    if time.delta_hours is not None:
        evidence_parts.append(f"delta {time.delta_hours:.1f}h")

    evidence_summary = (
        "; ".join(evidence_parts).capitalize()
        if evidence_parts
        else "No specific evidence"
    )

    return MatchScoreResult(
        source_id=source_report.id,
        candidate_id=cand_report.id,
        identity=identity,
        characteristics=characteristics,
        distance=distance,
        time=time,
        raw_composite_score=round(raw_composite, 2),
        contradiction_penalty=round(contradiction_penalty, 2),
        composite_score=round(final_score, 2),
        classification=classification,
        alert_eligible=alert_eligible,
        minimum_evidence_satisfied=min_evidence_satisfied,
        evidence_summary=evidence_summary,
        ineligibility_reasons=ineligibility_reasons,
    )


def score_candidates(
    source_report: Report,
    candidates: list[CandidateMatch],
) -> list[MatchScoreResult]:
    """Scores a batch of candidate matches against a source report."""
    return [score_candidate(source_report, cand) for cand in candidates]
