"""Geographic and spatial privacy utilities for Boomerang."""

from __future__ import annotations

# Precision of 2 decimal places provides ~1.1 km resolution, preventing
# meter-level incident identification or home triangulation while preserving
# neighborhood-level context on maps.
COARSENED_PRECISION_DECIMALS: int = 2


def coarsen_coordinate(
    lat: float, lon: float, precision_decimals: int = COARSENED_PRECISION_DECIMALS
) -> tuple[float, float]:
    """Coarsen latitude and longitude to protect exact incident location privacy.

    Non-owners and unauthenticated callers receive deterministic coarsened
    coordinates snapped to a ~1.1 km grid.
    """
    return round(float(lat), precision_decimals), round(float(lon), precision_decimals)
