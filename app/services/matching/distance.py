"""Geographic distance scoring for Boomerang Matching Engine (Phase 8.3).

Formalized in docs/matching_specification.md (Phase 8.1, Section 4.1).
Computes Signal D using the linear decay formula across the 5.0 km radius.
"""

from __future__ import annotations

from app.services.matching.models import DistanceBreakdown

MAX_RADIUS_KM: float = 5.0


def compute_distance_score(distance_meters: float) -> DistanceBreakdown:
    """Computes geographic proximity score D using linear decay within 5.0 km.

    Formula:
        D = max(0.0, min(100.0, 100.0 * (1.0 - distance_km / 5.0)))

    Benchmarks:
        0.0 km -> 100.0
        0.5 km -> 90.0
        1.0 km -> 80.0
        2.5 km -> 50.0
        5.0 km -> 0.0
        > 5.0 km -> 0.0

    Args:
        distance_meters: Accurate distance in metres (from PostGIS ST_Distance).

    Returns:
        DistanceBreakdown with bounded score in [0.0, 100.0], distance_meters,
        and distance_km.
    """
    if distance_meters < 0.0:
        # Gracefully handle unexpected negative distances by clamping to zero distance
        clamped_meters = 0.0
        dist_km = 0.0
        score = 100.0
    else:
        clamped_meters = distance_meters
        dist_km = distance_meters / 1000.0
        raw_score = 100.0 * (1.0 - dist_km / MAX_RADIUS_KM)
        score = max(0.0, min(100.0, raw_score))

    return DistanceBreakdown(
        score=score,
        distance_meters=clamped_meters,
        distance_km=round(dist_km, 2),
    )
