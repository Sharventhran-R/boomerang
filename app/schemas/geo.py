from decimal import Decimal

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field


class GeoSearchParams(BaseModel):
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_km: Decimal | None = Field(
        default=None, ge=Decimal("0.0"), le=Decimal("5.0")
    )


def get_geo_params(
    latitude: float | None = Query(None, ge=-90.0, le=90.0),
    longitude: float | None = Query(None, ge=-180.0, le=180.0),
    radius_km: Decimal | None = Query(None, ge=0.0, le=5.0),
) -> GeoSearchParams:
    params = GeoSearchParams(
        latitude=latitude, longitude=longitude, radius_km=radius_km
    )

    provided = sum(
        1
        for p in (params.latitude, params.longitude, params.radius_km)
        if p is not None
    )

    if provided > 0 and provided < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="latitude, longitude, and radius_km must be provided together",
        )

    if params.radius_km is not None:
        exponent = params.radius_km.normalize().as_tuple().exponent
        if isinstance(exponent, int) and abs(exponent) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="radius_km must have at most 1 decimal place",
            )

    return params
