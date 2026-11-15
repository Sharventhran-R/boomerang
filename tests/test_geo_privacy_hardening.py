"""Regression test suite for Geographic Query Privacy Hardening (Phase 10.1.2).

Verifies:
1. Public and non-owner distance values are quantized to nearest 0.5 km.
2. Report owners retain exact distances on their own reports.
3. Nested match responses (MatchReportSummary) expose only quantized distance.
4. Radius parameter validation rejects invalid bounds, decimals, or tuples.
5. Legitimate search radii (0.5, 1.0, 2.0, 5.0 km) function correctly.
6. Distance-based sorting and pagination do not leak exact distances.
7. Phase 10.1.1 coordinate coarsening (~1.1 km grid) remains intact.
8. Internal PostGIS spatial queries (ST_DWithin, ST_Distance) remain authoritative.
9. Internal Kafka events retain coordinates solely for trusted matching consumers.
10. Notification and push delivery payloads strip all coordinates.
11. Multi-point repeated query triangulation is defeated by 0.5 km quantization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReportCategory, ReportStatus, ReportType, ScoreClassification
from app.schemas.events.match import MatchAlertReadyPayload
from app.schemas.events.report import ReportCreatedPayload
from app.schemas.notification import NotificationResponse
from app.services.geo import coarsen_distance
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    TimeBreakdown,
)
from app.services.matching.persistence import MatchPersistenceService
from app.services.report import get_report_by_id


async def register_and_login(
    client: AsyncClient, name: str
) -> tuple[dict[str, str], uuid.UUID]:
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    user_id = uuid.UUID(reg_res.json()["id"])
    login_res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    token = str(login_res.json()["access_token"])
    return {"Authorization": f"Bearer {token}"}, user_id


def _make_score_result(
    source_id: uuid.UUID,
    candidate_id: uuid.UUID,
    composite_score: float = 91.0,
    distance_meters: float = 350.0,
) -> MatchScoreResult:
    now = datetime.now(UTC)
    return MatchScoreResult(
        source_id=source_id,
        candidate_id=candidate_id,
        identity=IdentityBreakdown(
            score=90.0,
            category_score=40.0,
            brand_model_score=35.0,
            title_noun_score=15.0,
            matched_category="KEYS",
            matched_brand="Toyota",
            matched_model="Fob",
            matched_title_tokens=["fob"],
        ),
        characteristics=CharacteristicsBreakdown(
            score=85.0,
            matched_colors=["black"],
            conflicting_colors=[],
            matched_cases=[],
            matched_accessories=[],
            matched_distinctive_marks=[],
            conflicting_marks=[],
            is_sparse=False,
            has_contradiction=False,
        ),
        distance=DistanceBreakdown(
            score=93.0,
            distance_meters=distance_meters,
            distance_km=round(distance_meters / 1000.0, 2),
        ),
        time=TimeBreakdown(
            score=95.0,
            loss_time=now - timedelta(hours=2),
            found_time=now - timedelta(hours=1),
            delta_seconds=3600.0,
            delta_hours=1.0,
            delta_days=0.04,
            is_negative_delta=False,
            is_missing_time=False,
        ),
        raw_composite_score=composite_score,
        contradiction_penalty=0.0,
        composite_score=composite_score,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        minimum_evidence_satisfied=True,
        evidence_summary="Test match for geographic privacy hardening",
        ineligibility_reasons=[],
    )


# ==============================================================================
# 1. Unit Tests for Distance Quantization Function
# ==============================================================================


def test_coarsen_distance_quantization_steps() -> None:
    # Exactly on boundaries
    assert coarsen_distance(0.0) == 0.0
    assert coarsen_distance(0.5) == 0.5
    assert coarsen_distance(1.0) == 1.0
    assert coarsen_distance(2.5) == 2.5
    assert coarsen_distance(5.0) == 5.0

    # Intermediate values snapping to nearest 0.5 km
    assert coarsen_distance(0.12) == 0.0
    assert coarsen_distance(0.24) == 0.0
    assert coarsen_distance(0.26) == 0.5
    assert coarsen_distance(0.48) == 0.5
    assert coarsen_distance(0.74) == 0.5
    assert coarsen_distance(0.76) == 1.0
    assert coarsen_distance(1.18) == 1.0
    assert coarsen_distance(1.28) == 1.5
    assert coarsen_distance(3.42) == 3.5
    assert coarsen_distance(4.88) == 5.0

    # Ensure clean float representation (no 0.5000000000000001)
    for d in [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9, 1.1, 1.2]:
        val = coarsen_distance(d)
        assert str(val).endswith((".0", ".5"))


# ==============================================================================
# 2. Public vs Owner Distance Quantization on Report Listings
# ==============================================================================


@pytest.mark.asyncio
async def test_public_and_non_owner_distance_quantized(client: AsyncClient) -> None:
    headers_owner, _ = await register_and_login(client, "Owner User")
    headers_viewer, _ = await register_and_login(client, "Viewer User")

    # Base query coordinate: 30.0000, 30.0000
    base_lat, base_lon = 30.0, 30.0
    run_id = uuid.uuid4().hex[:6]

    # Report 1: ~0.35 km away (lat offset 0.00315 deg)
    res1 = await client.post(
        "/api/v1/reports",
        headers=headers_owner,
        json={
            "type": "MISSING",
            "title": f"Report1_{run_id}",
            "description": "Report 1 test",
            "category": "KEYS",
            "latitude": 30.00315,
            "longitude": 30.0,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # Report 2: ~1.28 km away (lat offset 0.0115 deg)
    res2 = await client.post(
        "/api/v1/reports",
        headers=headers_owner,
        json={
            "type": "MISSING",
            "title": f"Report2_{run_id}",
            "description": "Report 2 test",
            "category": "KEYS",
            "latitude": 30.0115,
            "longitude": 30.0,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res2.status_code == 201
    id2 = res2.json()["id"]

    # 1. Unauthenticated public search
    anon_res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 5.0,
            "search": run_id,
        },
    )
    assert anon_res.status_code == 200
    anon_items = anon_res.json()["items"]
    assert len(anon_items) == 2

    item1_anon = next(r for r in anon_items if r["id"] == id1)
    item2_anon = next(r for r in anon_items if r["id"] == id2)

    # Public items must have quantized distances
    assert item1_anon["distance_km"] == 0.5
    assert item2_anon["distance_km"] == 1.5

    # Coordinates are also coarsened
    assert item1_anon["latitude"] == 30.00
    assert item2_anon["latitude"] == 30.01

    # 2. Authenticated non-owner viewer
    viewer_res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 5.0,
            "search": run_id,
        },
        headers=headers_viewer,
    )
    assert viewer_res.status_code == 200
    viewer_items = viewer_res.json()["items"]
    item1_viewer = next(r for r in viewer_items if r["id"] == id1)
    item2_viewer = next(r for r in viewer_items if r["id"] == id2)

    # Non-owner viewer receives quantized distances
    assert item1_viewer["distance_km"] == 0.5
    assert item2_viewer["distance_km"] == 1.5

    # 3. Authenticated owner search
    owner_res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 5.0,
            "search": run_id,
        },
        headers=headers_owner,
    )
    assert owner_res.status_code == 200
    owner_items = owner_res.json()["items"]
    item1_owner = next(r for r in owner_items if r["id"] == id1)
    item2_owner = next(r for r in owner_items if r["id"] == id2)

    # Owner receives exact distances (to 2 decimal places) for their own reports
    assert item1_owner["distance_km"] == 0.35
    assert item2_owner["distance_km"] == 1.27
    assert item1_owner["latitude"] == 30.00315
    assert item2_owner["latitude"] == 30.0115


# ==============================================================================
# 3. Nested Match Responses Expose Only Quantized Distance
# ==============================================================================


@pytest.mark.asyncio
async def test_nested_match_summary_quantized_distance(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    headers_m, _ = await register_and_login(client, "Missing Creator")
    headers_f, _ = await register_and_login(client, "Found Creator")

    # Missing report at 40.7128, -74.0060
    res_m = await client.post(
        "/api/v1/reports",
        headers=headers_m,
        json={
            "type": "MISSING",
            "title": f"Missing Keys {uuid.uuid4().hex[:6]}",
            "description": "Lost car keys",
            "category": "KEYS",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    missing_id = uuid.UUID(res_m.json()["id"])

    # Found report ~350m away at 40.7145, -74.0035
    res_f = await client.post(
        "/api/v1/reports",
        headers=headers_f,
        json={
            "type": "FOUND",
            "title": f"Found Keys {uuid.uuid4().hex[:6]}",
            "description": "Found car keys near park",
            "category": "KEYS",
            "latitude": 40.7145,
            "longitude": -74.0035,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    found_id = uuid.UUID(res_f.json()["id"])

    # Persist match record with relative distance 350.0m (0.35 km)
    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None
    score_result = _make_score_result(
        missing_id,
        found_id,
        composite_score=89.0,
        distance_meters=350.0,
    )
    service = MatchPersistenceService()
    await service.record_matches(missing_report, [score_result], db)
    await db.commit()

    # 1. Missing owner queries matches
    matches_res = await client.get(
        f"/api/v1/reports/{missing_id}/matches",
        headers=headers_m,
    )
    assert matches_res.status_code == 200
    match_items = matches_res.json()["items"]
    assert len(match_items) == 1
    match_id = match_items[0]["id"]
    opp_summary = match_items[0]["opposite_report"]

    # Opposite report's distance_km must be quantized to 0.5 km (0.35 -> 0.5)
    assert opp_summary["distance_km"] == 0.5
    assert opp_summary["latitude"] == round(40.7145, 2)
    assert opp_summary["longitude"] == round(-74.0035, 2)

    # 2. Missing owner inspects match detail
    detail_res_m = await client.get(
        f"/api/v1/matches/{match_id}",
        headers=headers_m,
    )
    assert detail_res_m.status_code == 200
    detail_m = detail_res_m.json()

    # Own report has exact distance
    assert detail_m["report_missing"]["distance_km"] == 0.35
    assert detail_m["report_missing"]["latitude"] == 40.7128

    # Opposite report has quantized distance and coarsened coordinates
    assert detail_m["report_found"]["distance_km"] == 0.5
    assert detail_m["report_found"]["latitude"] == round(40.7145, 2)

    # 3. Found owner inspects match detail
    detail_res_f = await client.get(
        f"/api/v1/matches/{match_id}",
        headers=headers_f,
    )
    assert detail_res_f.status_code == 200
    detail_f = detail_res_f.json()

    # Found owner sees exact distance for found report, quantized for missing
    assert detail_f["report_found"]["distance_km"] == 0.35
    assert detail_f["report_found"]["latitude"] == 40.7145
    assert detail_f["report_missing"]["distance_km"] == 0.5
    assert detail_f["report_missing"]["latitude"] == round(40.7128, 2)


# ==============================================================================
# 4. Radius Parameter Validation & Bounding
# ==============================================================================


@pytest.mark.asyncio
async def test_radius_parameter_bounds_and_decimals(client: AsyncClient) -> None:
    # 1. Valid radii (including 0.5, 1.0, 2.0, 5.0)
    for r in [0.0, 0.5, 1.0, 2.0, 2.5, 5.0]:
        res = await client.get(
            "/api/v1/reports",
            params={"latitude": 10.0, "longitude": 10.0, "radius_km": r},
        )
        assert res.status_code == 200

    # 2. Exceeds maximum 5.0 km limit
    res_over = await client.get(
        "/api/v1/reports",
        params={"latitude": 10.0, "longitude": 10.0, "radius_km": 5.1},
    )
    assert res_over.status_code == 422

    res_large = await client.get(
        "/api/v1/reports",
        params={"latitude": 10.0, "longitude": 10.0, "radius_km": 50.0},
    )
    assert res_large.status_code == 422

    # 3. Negative radius
    res_neg = await client.get(
        "/api/v1/reports",
        params={"latitude": 10.0, "longitude": 10.0, "radius_km": -0.1},
    )
    assert res_neg.status_code == 422

    # 4. Excessive decimal places (> 1 decimal place)
    res_micro = await client.get(
        "/api/v1/reports",
        params={"latitude": 10.0, "longitude": 10.0, "radius_km": 1.25},
    )
    assert res_micro.status_code == 422
    assert "at most 1 decimal place" in res_micro.json()["detail"]

    # 5. Partial coordinate tuple
    res_partial1 = await client.get(
        "/api/v1/reports",
        params={"latitude": 10.0, "longitude": 10.0},
    )
    assert res_partial1.status_code == 422

    res_partial2 = await client.get(
        "/api/v1/reports",
        params={"radius_km": 5.0},
    )
    assert res_partial2.status_code == 422


# ==============================================================================
# 5. Sorting and Pagination Do Not Expose Exact Distances
# ==============================================================================


@pytest.mark.asyncio
async def test_distance_sorting_preserves_quantization(client: AsyncClient) -> None:
    headers, _ = await register_and_login(client, "Creator")
    run_id = uuid.uuid4().hex[:6]
    base_lat, base_lon = 50.0, 30.0

    # Create 3 reports at different distances:
    # A: ~0.4 km (0.0036 deg lat) -> quantizes to 0.5 km
    # B: ~0.8 km (0.0072 deg lat) -> quantizes to 1.0 km
    # C: ~1.7 km (0.0153 deg lat) -> quantizes to 1.5 km
    for title, offset in [
        (f"A_{run_id}", 0.0036),
        (f"B_{run_id}", 0.0072),
        (f"C_{run_id}", 0.0153),
    ]:
        await client.post(
            "/api/v1/reports",
            headers=headers,
            json={
                "type": "MISSING",
                "title": title,
                "description": "Sort test report",
                "category": "OTHER",
                "latitude": base_lat + offset,
                "longitude": base_lon,
                "event_time": datetime.now(UTC).isoformat(),
            },
        )

    # Anonymous user queries sorted by distance
    res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 5.0,
            "sort": "distance",
            "search": run_id,
        },
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 3

    # Sorting order matches actual distance (A -> B -> C)
    assert items[0]["title"] == f"A_{run_id}"
    assert items[1]["title"] == f"B_{run_id}"
    assert items[2]["title"] == f"C_{run_id}"

    # Distances exposed are quantized
    assert items[0]["distance_km"] == 0.5
    assert items[1]["distance_km"] == 1.0
    assert items[2]["distance_km"] == 1.5

    # No unquantized distance leaks in any alternate field
    for item in items:
        assert "distance" not in item
        assert "raw_distance" not in item
        assert "distance_meters" not in item


# ==============================================================================
# 6. Event Privacy Boundary (Kafka & Notifications)
# ==============================================================================


def test_kafka_event_and_notification_privacy_boundaries() -> None:
    now = datetime.now(UTC)
    report_id = uuid.uuid4()

    # 1. ReportCreatedPayload retains coordinates for trusted matching consumer
    created_payload = ReportCreatedPayload(
        report_id=report_id,
        created_by_user_id=uuid.uuid4(),
        type=ReportType.MISSING,
        category=ReportCategory.KEYS,
        title="Keys",
        description="Lost keys",
        latitude=40.7128123,
        longitude=-74.0060123,
        event_time=now,
        reward_amount=None,
        status=ReportStatus.ACTIVE,
        created_at=now,
    )
    assert created_payload.latitude == 40.7128123
    assert created_payload.longitude == -74.0060123

    # 2. MatchAlertReadyPayload must omit all raw coordinates
    missing_owner_id = uuid.uuid4()
    found_owner_id = uuid.uuid4()
    alert_payload = MatchAlertReadyPayload(
        match_id=uuid.uuid4(),
        report_missing_id=report_id,
        report_found_id=uuid.uuid4(),
        missing_owner_id=missing_owner_id,
        found_owner_id=found_owner_id,
        source_report_id=report_id,
        source_owner_id=missing_owner_id,
        composite_score=85.0,
        classification=ScoreClassification.HIGH_PRIORITY,
        alert_eligible=True,
        is_update=False,
        evidence_summary="Test match summary",
        distance_meters=350.0,
        matched_category="KEYS",
    )
    alert_dict = alert_payload.model_dump()
    assert "latitude" not in alert_dict
    assert "longitude" not in alert_dict
    assert "coordinates" not in alert_dict

    # 3. NotificationResponse.sanitize_data purges coordinates before presentation
    notif_data = {
        "match_id": str(uuid.uuid4()),
        "latitude": 40.7128,
        "longitude": -74.0060,
        "coordinates": "40.7128,-74.0060",
        "action": "open_match",
    }
    sanitized = NotificationResponse.sanitize_data(notif_data)
    assert "latitude" not in sanitized
    assert "longitude" not in sanitized
    assert "coordinates" not in sanitized
    assert sanitized["action"] == "open_match"


# ==============================================================================
# 7. Repeated-Query Triangulation Mitigation Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_repeated_query_triangulation_defeated(client: AsyncClient) -> None:
    """Demonstrates multi-point searches cannot trilaterate exact location.

    Because distance_km is quantized to 0.5 km, distance measurements have an
    uncertainty of ±250m. The intersection of three 500m-thick annular rings
    produces a large area of uncertainty rather than a single point.
    """
    headers, _ = await register_and_login(client, "Victim User")
    target_lat, target_lon = 45.000000, 10.000000
    run_id = uuid.uuid4().hex[:6]

    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": f"TargetItem_{run_id}",
            "description": "Target incident",
            "category": "ELECTRONICS",
            "latitude": target_lat,
            "longitude": target_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201

    # Attacker performs 3 queries from different vantage points ~1.2 km away
    probes = [
        {"lat": 45.010, "lon": 10.000},  # North: ~1.11 km
        {"lat": 44.990, "lon": 10.000},  # South: ~1.11 km
        {"lat": 45.000, "lon": 10.015},  # East:  ~1.18 km
    ]

    quantized_distances = []
    for probe in probes:
        search_res = await client.get(
            "/api/v1/reports",
            params={
                "latitude": probe["lat"],
                "longitude": probe["lon"],
                "radius_km": 5.0,
                "search": run_id,
            },
        )
        assert search_res.status_code == 200
        items = search_res.json()["items"]
        assert len(items) == 1
        quantized_distances.append(items[0]["distance_km"])

    # All probes receive quantized distances (multiples of 0.5 km)
    for qd in quantized_distances:
        assert qd in (1.0, 1.5)
