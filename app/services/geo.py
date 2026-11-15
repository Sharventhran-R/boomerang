"""Geographic and spatial privacy utilities for Boomerang."""

from __future__ import annotations

# Precision of 2 decimal places provides ~1.1 km resolution, preventing
# meter-level incident identification or home triangulation while preserving
# neighborhood-level context on maps.
COARSENED_PRECISION_DECIMALS: int = 2

# Distance quantization step in kilometers for public/non-owner distance disclosure.
# Snaps distance_km to multiples of 0.5 km (0.0, 0.5, 1.0, 1.5, ...),
# preventing distance-based multilateration / trilateration attacks.
DISTANCE_QUANTIZATION_STEP_KM: float = 0.5


def coarsen_coordinate(
    lat: float, lon: float, precision_decimals: int = COARSENED_PRECISION_DECIMALS
) -> tuple[float, float]:
    """Coarsen latitude and longitude to protect exact incident location privacy.

    Non-owners and unauthenticated callers receive deterministic coarsened
    coordinates snapped to a ~1.1 km grid.
    """
    return round(float(lat), precision_decimals), round(float(lon), precision_decimals)


def coarsen_distance(
    distance_km: float,
    step_km: float = DISTANCE_QUANTIZATION_STEP_KM,
) -> float:
    """Quantize distance in kilometers to mitigate trilateration attacks.

    Non-owners and public callers receive distances snapped to the nearest 0.5 km
    boundary (e.g., 0.23 km -> 0.0 km, 0.35 km -> 0.5 km, 1.15 km -> 1.0 km).
    Multiples of 0.5 km have at most 1 decimal place, preventing floating-point
    representation artifacts in JSON responses.
    """
    if step_km <= 0:
        return distance_km
    quantized = round(float(distance_km) / step_km) * step_km
    return round(quantized, 1)


# Search origin grid snapping precision (Phase 10.1.3).
# Snaps public and non-owner discovery query coordinates to 2 decimal places (~1.1 km),
# eliminating continuous sub-meter micro-stepping bisection attacks on ST_DWithin.
SEARCH_ORIGIN_GRID_DECIMALS: int = 2

# Distance bucket size in meters for public / non-owner result sorting (Phase 10.1.3).
# Groups discovery results into 500-meter bands. Ties within each bucket are
# broken by non-geographic fields (created_at DESC, id ASC), preventing
# perpendicular-bisector ordering attacks.
DISTANCE_BUCKET_SIZE_METERS: float = 500.0


def snap_search_origin(
    lat: float, lon: float, precision_decimals: int = SEARCH_ORIGIN_GRID_DECIMALS
) -> tuple[float, float]:
    """Snap search origin coordinates to a deterministic coarse grid.

    Rounds latitude and longitude to 2 decimal places (~1.1 km grid) for public
    and non-owner geographic discovery queries. This converts continuous probe
    movement into discrete grid steps, neutralizing binary search boundary
    probing while preserving neighborhood discovery.
    """
    return round(float(lat), precision_decimals), round(float(lon), precision_decimals)
