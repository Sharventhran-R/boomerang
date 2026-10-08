from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError

from app.db.models import ReportCategory, ReportType
from app.schemas.geo import get_geo_params
from app.schemas.report import CreateReportRequest, UpdateReportRequest


def test_geo_search_params_validation() -> None:
    # Valid
    get_geo_params(latitude=13.08, longitude=80.27, radius_km=Decimal("0.5"))
    get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("0.0"))
    get_geo_params(latitude=-90.0, longitude=-180.0, radius_km=Decimal("5.0"))
    get_geo_params(latitude=None, longitude=None, radius_km=None)  # All None is valid

    # Invalid Lat/Lon bounds
    with pytest.raises(ValidationError):
        get_geo_params(latitude=91.0, longitude=180.0, radius_km=Decimal("1.0"))
    with pytest.raises(ValidationError):
        get_geo_params(latitude=-91.0, longitude=180.0, radius_km=Decimal("1.0"))
    with pytest.raises(ValidationError):
        get_geo_params(latitude=90.0, longitude=181.0, radius_km=Decimal("1.0"))
    with pytest.raises(ValidationError):
        get_geo_params(latitude=90.0, longitude=-181.0, radius_km=Decimal("1.0"))

    # Radius bounds
    with pytest.raises(ValidationError):
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("-0.1"))
    with pytest.raises(ValidationError):
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("5.1"))
    with pytest.raises(ValidationError):
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("10.0"))

    # Radius decimal places
    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("0.05"))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=Decimal("1.25"))
    assert exc.value.status_code == 422

    # Consistency
    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=90.0, longitude=180.0, radius_km=None)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=90.0, longitude=None, radius_km=Decimal("1.0"))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=None, longitude=180.0, radius_km=Decimal("1.0"))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        get_geo_params(latitude=90.0, longitude=None, radius_km=None)
    assert exc.value.status_code == 422


def test_report_location_validation() -> None:
    event_time = datetime.now(UTC)
    # Create with location PASS
    CreateReportRequest(
        type=ReportType.MISSING,
        title="Test",
        description="Test desc",
        category=ReportCategory.OTHER,
        latitude=10.0,
        longitude=10.0,
        event_time=event_time,
    )

    # Attempt to create without location fails because fields are required
    with pytest.raises(ValidationError):
        CreateReportRequest(  # type: ignore[call-arg]
            type=ReportType.MISSING,
            title="Test",
            description="Test desc",
            category=ReportCategory.OTHER,
            event_time=event_time,
        )

    # Update report retaining location
    UpdateReportRequest(title="Updated Title")
    UpdateReportRequest(latitude=10.0, longitude=10.0)

    # Attempt to remove location
    with pytest.raises(ValidationError, match="latitude cannot be null"):
        UpdateReportRequest(latitude=None)
    with pytest.raises(ValidationError, match="longitude cannot be null"):
        UpdateReportRequest(longitude=None)
    with pytest.raises(ValidationError, match="latitude cannot be null"):
        UpdateReportRequest(latitude=None, longitude=None)

    # Attempt to update only one
    with pytest.raises(
        ValidationError, match="latitude and longitude must be updated together"
    ):
        UpdateReportRequest(latitude=10.0)
    with pytest.raises(
        ValidationError, match="latitude and longitude must be updated together"
    ):
        UpdateReportRequest(longitude=10.0)


@pytest.mark.asyncio
async def test_list_reports_geo_parameters(client: AsyncClient) -> None:
    from app.api.deps import get_current_user
    from app.db.database import get_db
    from app.main import app

    # Mock current user and db
    app.dependency_overrides[get_current_user] = lambda: None
    app.dependency_overrides[get_db] = lambda: None

    try:
        # Valid geo params (it might return 500 if it actually hits service,
        # but we just want to bypass 422)
        # Wait, if validation passes, it will hit service and might throw 500.
        # But for 422, it will fail at FastAPI validation layer.

        # Inconsistent geo params (missing radius)
        res = await client.get(
            "/api/v1/reports", params={"latitude": 10.0, "longitude": 10.0}
        )
        assert res.status_code == 422

        # Inconsistent geo params (missing longitude)
        res = await client.get(
            "/api/v1/reports", params={"latitude": 10.0, "radius_km": 1.0}
        )
        assert res.status_code == 422

        # Invalid radius decimal
        res = await client.get(
            "/api/v1/reports",
            params={"latitude": 10.0, "longitude": 10.0, "radius_km": 1.05},
        )
        assert res.status_code == 422

        # distance sort without geo params
        res = await client.get("/api/v1/reports", params={"sort": "distance"})
        assert res.status_code == 422
        assert (
            "distance requires latitude, longitude, and radius_km"
            in res.json()["detail"]
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_radius_filtering(client: AsyncClient) -> None:

    # We will need real DB for this test to evaluate ST_DWithin
    # Clear overrides to use the real database and real endpoints,
    # except we need to authenticate

    import uuid

    user_id = uuid.uuid4().hex[:6]
    test_email = f"geo_test_{user_id}@example.com"

    # Register/login a user to get token
    res = await client.post(
        "/api/v1/auth/register",
        json={"name": "Geo Test", "email": test_email, "password": "password123"},
    )
    # Could be 201 or 400 if already exists
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": test_email, "password": "password123"},
    )
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create some reports at known coordinates
    # Base location: lat=10.0, lon=10.0
    base_lat, base_lon = 10.0, 10.0

    import uuid

    run_id = uuid.uuid4().hex[:6]

    reports_data = [
        # Exactly at base (0.0 km)
        {"lat": 10.0, "lon": 10.0, "title": f"Base_{run_id}"},
        # ~0.55 km away
        {"lat": 10.005, "lon": 10.0, "title": f"Inside1km_{run_id}"},
        # ~1.11 km away
        {"lat": 10.01, "lon": 10.0, "title": f"Outside1km_{run_id}"},
        # ~5.5 km away
        {"lat": 10.05, "lon": 10.0, "title": f"Outside5km_{run_id}"},
    ]

    for rd in reports_data:
        await client.post(
            "/api/v1/reports",
            json={
                "type": "MISSING",
                "title": rd["title"],
                "description": "Geo test report",
                "category": "OTHER",
                "latitude": rd["lat"],
                "longitude": rd["lon"],
                "event_time": datetime.now(UTC).isoformat(),
            },
            headers=headers,
        )

    # Test 1: radius 0.0 km (Should only return Base)
    res = await client.get(
        "/api/v1/reports",
        params={"latitude": base_lat, "longitude": base_lon, "radius_km": 0.0},
        headers=headers,
    )
    assert res.status_code == 200
    titles = [r["title"] for r in res.json()["items"]]
    assert f"Base_{run_id}" in titles
    assert f"Inside1km_{run_id}" not in titles

    # Test 2: radius 1.0 km (Should return Base and Inside1km)
    res = await client.get(
        "/api/v1/reports",
        params={"latitude": base_lat, "longitude": base_lon, "radius_km": 1.0},
        headers=headers,
    )
    assert res.status_code == 200
    titles = [r["title"] for r in res.json()["items"]]
    assert f"Base_{run_id}" in titles
    assert f"Inside1km_{run_id}" in titles
    assert f"Outside1km_{run_id}" not in titles

    # Test 3: radius 5.0 km (Should return Base, Inside1km, Outside1km)
    res = await client.get(
        "/api/v1/reports",
        params={"latitude": base_lat, "longitude": base_lon, "radius_km": 5.0},
        headers=headers,
    )
    assert res.status_code == 200
    titles = [r["title"] for r in res.json()["items"]]
    assert f"Base_{run_id}" in titles
    assert f"Inside1km_{run_id}" in titles
    assert f"Outside1km_{run_id}" in titles
    assert f"Outside5km_{run_id}" not in titles

    # Test 4: Combined with other filters (e.g. text search)
    res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 5.0,
            "search": f"Inside1km_{run_id}",
        },
        headers=headers,
    )
    assert res.status_code == 200
    titles = [r["title"] for r in res.json()["items"]]
    assert titles == [f"Inside1km_{run_id}"]

    # Test 5: Verify request without geographic parameters retains existing
    # search behavior
    res = await client.get(
        "/api/v1/reports", params={"search": f"Outside5km_{run_id}"}, headers=headers
    )
    assert res.status_code == 200
    titles = [r["title"] for r in res.json()["items"]]
    assert f"Outside5km_{run_id}" in titles

    # Note: Boundary inclusion (exactly on radius) is inherently handled by
    # PostGIS ST_DWithin (use_spheroid=True) being inclusive.
    # Radius 0.0 covers this boundary edge case perfectly.
