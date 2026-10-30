"""Incident-time compatibility scoring for Boomerang Matching Engine (Phase 8.3.1).

Formalized in docs/matching_specification.md (Phase 8.3.1 Refinement).
Computes Signal T based on physical causality:
    delta = event_time_FOUND - event_time_MISSING

Rules:
1. delta < -24 hours: T = 0.
2. -24 hours <= delta < 0: linear interpolation from 0 to 100:
       T = 100 * (delta + 24 hours) / 24 hours
3. 0 <= delta <= 7 days: T = 100.
4. 7 days < delta <= 90 days: linear interpolation from 100 to 20:
       T = 100 - 80 * (delta - 7 days) / 83 days
5. 90 days < delta <= 120 days: linear interpolation from 20 to 0:
       T = 20 * (120 days - delta) / 30 days
6. delta > 120 days: T = 0.
7. Missing incident timestamp: T = 50, marked as missing temporal evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from app.db.models import ReportType
from app.services.matching.models import TimeBreakdown

SECONDS_PER_HOUR: Final[float] = 3600.0
SECONDS_PER_DAY: Final[float] = 86400.0

NEG_24H_SECONDS: Final[float] = -86400.0  # -24 hours in seconds
POS_7D_SECONDS: Final[float] = 604800.0  # 7 days in seconds
POS_90D_SECONDS: Final[float] = 7776000.0  # 90 days in seconds
POS_120D_SECONDS: Final[float] = 10368000.0  # 120 days in seconds

RANGE_83D_SECONDS: Final[float] = 7171200.0  # 83 days (90d - 7d) in seconds
RANGE_30D_SECONDS: Final[float] = 2592000.0  # 30 days (120d - 90d) in seconds


def compute_time_score(
    source_event_time: datetime | None,
    candidate_event_time: datetime | None,
    source_type: ReportType,
    candidate_type: ReportType,
) -> TimeBreakdown:
    """Computes incident-time compatibility score T based on physical causality.

    Always computes:
        delta = event_time_FOUND - event_time_MISSING
    irrespective of source/candidate order.

    Rules:
    - delta < -24 hours -> T = 0.0
    - -24h <= delta < 0 -> linear interpolation: 100 * (delta + 24h) / 24h
    - 0 <= delta <= 7d -> T = 100.0
    - 7d < delta <= 90d -> linear interpolation: 100 - 80 * (delta - 7d) / 83d
    - 90d < delta <= 120d -> linear interpolation: 20 * (120d - delta) / 30d
    - delta > 120d -> T = 0.0
    - Missing timestamp -> T = 50.0 with is_missing_time = True

    Timezone Handling:
    - Both timestamps must be timezone-aware. Naive timestamps raise ValueError.

    Args:
        source_event_time: Incident time of source report (or None).
        candidate_event_time: Incident time of candidate report (or None).
        source_type: ReportType of source report.
        candidate_type: ReportType of candidate report.

    Returns:
        TimeBreakdown with clamped score in [0.0, 100.0] and temporal metadata.

    Raises:
        ValueError: If a provided timestamp is timezone-naive.
    """
    # 1. Handle missing temporal evidence
    if source_event_time is None or candidate_event_time is None:
        loss_t = (
            source_event_time
            if source_type == ReportType.MISSING
            else candidate_event_time
        )
        found_t = (
            source_event_time
            if source_type == ReportType.FOUND
            else candidate_event_time
        )
        return TimeBreakdown(
            score=50.0,
            loss_time=loss_t,
            found_time=found_t,
            delta_seconds=None,
            delta_hours=None,
            delta_days=None,
            is_negative_delta=False,
            is_missing_time=True,
        )

    # 2. Strict timezone validation: reject timezone-naive timestamps
    if source_event_time.tzinfo is None:
        raise ValueError(
            "source_event_time must be timezone-aware; received naive timestamp"
        )
    if candidate_event_time.tzinfo is None:
        raise ValueError(
            "candidate_event_time must be timezone-aware; received naive timestamp"
        )

    # 3. Assign loss_time and found_time based on ReportType
    loss_time: datetime
    found_time: datetime
    if source_type == ReportType.MISSING and candidate_type == ReportType.FOUND:
        loss_time = source_event_time
        found_time = candidate_event_time
    elif source_type == ReportType.FOUND and candidate_type == ReportType.MISSING:
        loss_time = candidate_event_time
        found_time = source_event_time
    else:
        # Fallback if both have the same type or unspecified
        loss_time = source_event_time
        found_time = candidate_event_time

    # 4. Compute physical causality delta in elapsed seconds: found - missing
    delta_seconds = (found_time - loss_time).total_seconds()
    delta_hours = delta_seconds / SECONDS_PER_HOUR
    delta_days = delta_seconds / SECONDS_PER_DAY
    is_negative = delta_seconds < 0.0

    # 5. Evaluate refined gradual rules
    score: float
    if delta_seconds < NEG_24H_SECONDS:
        # Rule 1: delta < -24 hours -> T = 0
        score = 0.0
    elif delta_seconds < 0.0:
        # Rule 2: -24 hours <= delta < 0
        # Formula: T = 100 * (delta + 24 hours) / 24 hours
        score = 100.0 * (delta_seconds + 86400.0) / 86400.0
    elif delta_seconds <= POS_7D_SECONDS:
        # Rule 3: 0 <= delta <= 7 days -> T = 100
        score = 100.0
    elif delta_seconds <= POS_90D_SECONDS:
        # Rule 4: 7 days < delta <= 90 days
        # Formula: T = 100 - 80 * (delta - 7 days) / 83 days
        score = 100.0 - 80.0 * (delta_seconds - POS_7D_SECONDS) / RANGE_83D_SECONDS
    elif delta_seconds <= POS_120D_SECONDS:
        # Rule 5: 90 days < delta <= 120 days
        # Formula: T = 20 * (120 days - delta) / 30 days
        score = 20.0 * (POS_120D_SECONDS - delta_seconds) / RANGE_30D_SECONDS
    else:
        # Rule 6: delta > 120 days -> T = 0
        score = 0.0

    # Clamp all outputs to [0.0, 100.0]
    final_score = max(0.0, min(100.0, score))

    return TimeBreakdown(
        score=final_score,
        loss_time=loss_time,
        found_time=found_time,
        delta_seconds=round(delta_seconds, 2),
        delta_hours=round(delta_hours, 2),
        delta_days=round(delta_days, 2),
        is_negative_delta=is_negative,
        is_missing_time=False,
    )
