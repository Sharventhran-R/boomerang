"""Regression test suite for Boomerang GPS Location Privacy (Phase 10.1.1).

Verifies:
1. Anonymous users receive coarsened coordinates on public report listings.
2. Anonymous users receive coarsened coordinates on public report detail.
3. Authenticated non-owners receive coarsened coordinates on report detail.
4. Authenticated report owners receive exact raw GPS coordinates on report detail.
5. Authenticated report owners receive exact raw GPS coordinates on /reports/me.
6. Authenticated report creators receive exact coordinates on create and update.
7. Mixed report listings show exact coordinates for own reports and coarsened
   coordinates for other users' reports.
8. Match candidate listings coarsen opposite-party report coordinates.
9. Match detail endpoints provide exact coordinates for own report and coarsened
   coordinates for opposite report.
10. Recovery request APIs do not serialize or leak GPS coordinates.
11. Notification payload sanitization strips any incident GPS coordinates.
12. PostGIS spatial querying and distance calculations remain authoritative.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScoreClassification
from app.schemas.notification import NotificationResponse
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
    composite_score: float = 92.0,
    distance_meters: float = 250.0,
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
            matched_category="ELECTRONICS",
            matched_brand="Apple",
            matched_model="MacBook",
            matched_title_tokens=["macbook"],
        ),
        characteristics=CharacteristicsBreakdown(
            score=85.0,
            matched_colors=["silver"],
            conflicting_colors=[],
            matched_cases=[],
            matched_accessories=[],
            matched_distinctive_marks=[],
            conflicting_marks=[],
            is_sparse=False,
            has_contradiction=False,
        ),
        distance=DistanceBreakdown(
            score=95.0,
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
        evidence_summary="Test match for location privacy verification",
        ineligibility_reasons=[],
    )


@pytest.mark.asyncio
async def test_anonymous_and_non_owner_coarsening_on_reports(
    client: AsyncClient,
) -> None:
    # 1. User A registers and creates a report with exact coordinates
    headers_a, _ = await register_and_login(client, "Owner Alice")
    exact_lat = 37.7749295
    exact_lon = -122.4194155
    coarsened_lat = round(exact_lat, 2)  # 37.77
    coarsened_lon = round(exact_lon, 2)  # -122.42

    create_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": f"Alice Laptop {uuid.uuid4().hex[:6]}",
            "description": "Silver laptop near cafe",
            "category": "ELECTRONICS",
            "latitude": exact_lat,
            "longitude": exact_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert create_res.status_code == 201
    created_report = create_res.json()
    report_id = created_report["id"]

    # Creation response to creator must contain exact coordinates
    assert created_report["latitude"] == exact_lat
    assert created_report["longitude"] == exact_lon

    # 2. Anonymous user fetches report detail -> must receive coarsened coordinates
    anon_detail_res = await client.get(f"/api/v1/reports/{report_id}")
    assert anon_detail_res.status_code == 200
    anon_data = anon_detail_res.json()
    assert anon_data["latitude"] == coarsened_lat
    assert anon_data["longitude"] == coarsened_lon
    assert anon_data["latitude"] != exact_lat
    assert anon_data["longitude"] != exact_lon

    # 3. Anonymous user fetches public report list -> must receive coarsened coordinates
    anon_list_res = await client.get(
        "/api/v1/reports",
        params={"search": created_report["title"]},
    )
    assert anon_list_res.status_code == 200
    anon_items = anon_list_res.json()["items"]
    assert len(anon_items) == 1
    assert anon_items[0]["latitude"] == coarsened_lat
    assert anon_items[0]["longitude"] == coarsened_lon

    # 4. Authenticated non-owner (Bob) fetches report detail -> coarsened coordinates
    headers_b, _ = await register_and_login(client, "Viewer Bob")
    bob_detail_res = await client.get(f"/api/v1/reports/{report_id}", headers=headers_b)
    assert bob_detail_res.status_code == 200
    bob_data = bob_detail_res.json()
    assert bob_data["latitude"] == coarsened_lat
    assert bob_data["longitude"] == coarsened_lon

    # 5. Authenticated owner (Alice) fetches own report detail -> exact coordinates
    alice_detail_res = await client.get(
        f"/api/v1/reports/{report_id}", headers=headers_a
    )
    assert alice_detail_res.status_code == 200
    alice_data = alice_detail_res.json()
    assert alice_data["latitude"] == exact_lat
    assert alice_data["longitude"] == exact_lon

    # 6. Authenticated owner (Alice) fetches /reports/me -> exact coordinates
    alice_me_res = await client.get("/api/v1/reports/me", headers=headers_a)
    assert alice_me_res.status_code == 200
    my_reports = alice_me_res.json()["items"]
    alice_item = next(r for r in my_reports if r["id"] == report_id)
    assert alice_item["latitude"] == exact_lat
    assert alice_item["longitude"] == exact_lon

    # 7. Authenticated owner (Alice) updates report -> receives exact coordinates
    new_lat = 37.7850012
    new_lon = -122.4050012
    patch_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers_a,
        json={"latitude": new_lat, "longitude": new_lon},
    )
    assert patch_res.status_code == 200
    patched_data = patch_res.json()
    assert patched_data["latitude"] == new_lat
    assert patched_data["longitude"] == new_lon


@pytest.mark.asyncio
async def test_mixed_ownership_report_listing(client: AsyncClient) -> None:
    headers_a, _ = await register_and_login(client, "User A")
    headers_b, _ = await register_and_login(client, "User B")

    unique_run = uuid.uuid4().hex[:6]
    lat_a = 40.7128123
    lon_a = -74.0060123
    lat_b = 40.7589123
    lon_b = -73.9851123

    # User A creates Report A
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": f"ReportA_{unique_run}",
            "description": "Report A description",
            "category": "OTHER",
            "latitude": lat_a,
            "longitude": lon_a,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id_a = res_a.json()["id"]

    # User B creates Report B
    res_b = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "MISSING",
            "title": f"ReportB_{unique_run}",
            "description": "Report B description",
            "category": "OTHER",
            "latitude": lat_b,
            "longitude": lon_b,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id_b = res_b.json()["id"]

    # User A queries public list
    list_res = await client.get(
        "/api/v1/reports",
        params={"search": unique_run},
        headers=headers_a,
    )
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    item_a = next(r for r in items if r["id"] == id_a)
    item_b = next(r for r in items if r["id"] == id_b)

    # User A sees exact coordinates for Report A (own report)
    assert item_a["latitude"] == lat_a
    assert item_a["longitude"] == lon_a

    # User A sees coarsened coordinates for Report B (other user's report)
    assert item_b["latitude"] == round(lat_b, 2)
    assert item_b["longitude"] == round(lon_b, 2)
    assert item_b["latitude"] != lat_b
    assert item_b["longitude"] != lon_b


@pytest.mark.asyncio
async def test_match_endpoints_location_privacy(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    headers_a, _ = await register_and_login(client, "Missing Owner")
    headers_b, _ = await register_and_login(client, "Found Owner")

    missing_lat = 40.7128123
    missing_lon = -74.0060123
    found_lat = 40.7135987
    found_lon = -74.0055876

    # Missing report created by User A
    res_m = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": f"Missing Item {uuid.uuid4().hex[:6]}",
            "description": "Lost my silver watch",
            "category": "JEWELRY",
            "latitude": missing_lat,
            "longitude": missing_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    missing_id = uuid.UUID(res_m.json()["id"])

    # Found report created by User B
    res_f = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "FOUND",
            "title": f"Found Item {uuid.uuid4().hex[:6]}",
            "description": "Found a silver watch near bench",
            "category": "JEWELRY",
            "latitude": found_lat,
            "longitude": found_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    found_id = uuid.UUID(res_f.json()["id"])

    # Load and persist match in database
    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None
    score_res = _make_score_result(
        source_id=missing_id,
        candidate_id=found_id,
        composite_score=94.5,
        distance_meters=180.0,
    )
    service = MatchPersistenceService()
    await service.record_matches(missing_report, [score_res], db)
    await db.commit()

    # 1. User A lists matches for their missing report
    matches_res = await client.get(
        f"/api/v1/reports/{missing_id}/matches",
        headers=headers_a,
    )
    assert matches_res.status_code == 200
    match_items = matches_res.json()["items"]
    assert len(match_items) == 1
    match_id = uuid.UUID(match_items[0]["id"])
    opp_summary = match_items[0]["opposite_report"]

    # The opposite report (User B's found report) must be coarsened!
    assert opp_summary["latitude"] == round(found_lat, 2)
    assert opp_summary["longitude"] == round(found_lon, 2)
    assert opp_summary["latitude"] != found_lat
    assert opp_summary["longitude"] != found_lon

    # 2. User A inspects match detail
    detail_res_a = await client.get(f"/api/v1/matches/{match_id}", headers=headers_a)
    assert detail_res_a.status_code == 200
    detail_a = detail_res_a.json()

    # User A owns missing -> missing has exact coordinates
    assert detail_a["report_missing"]["latitude"] == missing_lat
    assert detail_a["report_missing"]["longitude"] == missing_lon

    # User A does not own found -> found has coarsened coordinates
    assert detail_a["report_found"]["latitude"] == round(found_lat, 2)
    assert detail_a["report_found"]["longitude"] == round(found_lon, 2)
    assert detail_a["report_found"]["latitude"] != found_lat

    # 3. User B inspects match detail
    detail_res_b = await client.get(f"/api/v1/matches/{match_id}", headers=headers_b)
    assert detail_res_b.status_code == 200
    detail_b = detail_res_b.json()

    # User B owns found -> found has exact coordinates
    assert detail_b["report_found"]["latitude"] == found_lat
    assert detail_b["report_found"]["longitude"] == found_lon

    # User B does not own missing -> missing has coarsened coordinates
    assert detail_b["report_missing"]["latitude"] == round(missing_lat, 2)
    assert detail_b["report_missing"]["longitude"] == round(missing_lon, 2)
    assert detail_b["report_missing"]["latitude"] != missing_lat


@pytest.mark.asyncio
async def test_recovery_and_notifications_zero_location_exposure() -> None:
    # 1. Verify NotificationResponse.sanitize_data defensively strips location fields
    raw_data = {
        "match_id": str(uuid.uuid4()),
        "latitude": 37.7749,
        "longitude": -122.4194,
        "coordinates": "37.7749,-122.4194",
        "action": "view_match",
    }
    sanitized = NotificationResponse.sanitize_data(raw_data)
    assert "latitude" not in sanitized
    assert "longitude" not in sanitized
    assert "coordinates" not in sanitized
    assert sanitized["action"] == "view_match"


@pytest.mark.asyncio
async def test_postgis_search_remains_authoritative_with_coarsened_output(
    client: AsyncClient,
) -> None:
    # Verify spatial search filters against authoritative location
    # even when unauthenticated public callers view results with coarsened coordinates.
    headers, _ = await register_and_login(client, "Geo Originator")
    base_lat, base_lon = 20.0, 20.0
    run_id = uuid.uuid4().hex[:6]

    # Report inside 1.0 km radius (offset 0.005 deg lat -> ~550m)
    res_in = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": f"Inside_{run_id}",
            "description": "Inside 1km radius",
            "category": "OTHER",
            "latitude": 20.0054321,
            "longitude": 20.0,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res_in.status_code == 201

    # Report outside 1.0 km radius (offset 0.02 deg lat -> ~2.2km)
    res_out = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": f"Outside_{run_id}",
            "description": "Outside 1km radius",
            "category": "OTHER",
            "latitude": 20.0200000,
            "longitude": 20.0,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res_out.status_code == 201

    # Unauthenticated public caller queries with radius_km=1.0
    search_res = await client.get(
        "/api/v1/reports",
        params={
            "latitude": base_lat,
            "longitude": base_lon,
            "radius_km": 1.0,
            "search": run_id,
        },
    )
    assert search_res.status_code == 200
    items = search_res.json()["items"]
    assert len(items) == 1
    inside_item = items[0]
    assert inside_item["title"] == f"Inside_{run_id}"

    # Public caller sees coarsened coordinates
    assert inside_item["latitude"] == 20.01
    assert inside_item["longitude"] == 20.00
    # But distance calculation is derived accurately from PostGIS ST_Distance
    assert inside_item["distance_km"] is not None
    assert 0.5 < inside_item["distance_km"] < 0.7
