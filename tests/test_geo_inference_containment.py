"""Comprehensive verification suite for Geographic Inference Containment (Phase 10.1.3).

Verifies all 13 Stage G security scenarios:
1. Distance ordering no longer reveals exact perpendicular-bisector boundaries.
2. Pagination cannot recover authoritative proximity ranks.
3. Search-origin micro-stepping is constrained for public/non-owner queries.
4. Radius membership behavior is consistent with the selected grid policy.
5. Quantization transition probing cannot recover unnecessary precision.
6. Repeated identical queries return stable results.
7. Changing page offsets does not expose hidden distance ordering.
8. Existing valid discovery searches still work (Chennai & Kyiv scenarios).
9. Owner authorization behavior remains intact.
10. Internal matching and PostGIS spatial calculations remain authoritative.
11. Match summaries do not expose exact opposite-party distance or location.
12. Phase 10.1.1 coordinate coarsening remains intact.
13. Phase 10.1.2 distance quantization remains compatible with the new policy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.database import AsyncSessionLocal
from app.db.models import ReportCategory, ReportType, ScoreClassification
from app.services.geo import (
    DISTANCE_BUCKET_SIZE_METERS,
    coarsen_coordinate,
    coarsen_distance,
    snap_search_origin,
)
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    TimeBreakdown,
)
from app.services.matching.persistence import MatchPersistenceService
from app.services.matching.retrieval import retrieve_candidates
from app.services.report import get_report_by_id


async def register_and_login(
    client: AsyncClient, name: str
) -> tuple[dict[str, str], uuid.UUID]:
    email = f"cont_{uuid.uuid4().hex[:8]}@example.com"
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


# ==============================================================================
# Scenario 1 & 2: Distance Ordering & Pagination Rank Containment
# ==============================================================================


@pytest.mark.asyncio
async def test_distance_ordering_bisector_containment(client: AsyncClient) -> None:
    """Scenario 1: Distance ordering no longer reveals bisector boundaries."""
    headers, _ = await register_and_login(client, "Bisector User")
    run_id = uuid.uuid4().hex[:6]

    # Two items in same 500m bucket
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Item A {run_id}",
            "description": "Item A",
            "latitude": 40.0000,
            "longitude": 40.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id_a = res_a.json()["id"]

    res_b = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Item B {run_id}",
            "description": "Item B",
            "latitude": 40.0010,
            "longitude": 40.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id_b = res_b.json()["id"]

    # Queries from South and North return identical order (Item B before Item A)
    r_south = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 39.9980,
            "longitude": 40.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
        },
    )
    r_north = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 40.0030,
            "longitude": 40.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
        },
    )
    items_s = r_south.json()["items"]
    items_n = r_north.json()["items"]

    assert items_s[0]["id"] == id_b
    assert items_s[1]["id"] == id_a
    assert items_n[0]["id"] == id_b
    assert items_n[1]["id"] == id_a


@pytest.mark.asyncio
async def test_pagination_rank_order_stability(client: AsyncClient) -> None:
    """Scenario 2 & 7: Pagination cannot recover authoritative proximity ranks."""
    headers, _ = await register_and_login(client, "Page Rank User")
    run_id = uuid.uuid4().hex[:6]

    res1 = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.BAG.value,
            "title": f"P1_{run_id}",
            "description": "P1",
            "latitude": 41.0000,
            "longitude": 41.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id1 = res1.json()["id"]

    res2 = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.BAG.value,
            "title": f"P2_{run_id}",
            "description": "P2",
            "latitude": 41.0012,
            "longitude": 41.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id2 = res2.json()["id"]

    # Probe 1: Page 1 has id2, Page 2 has id1
    r_p1 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 40.9985,
            "longitude": 41.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 1,
            "page_size": 1,
        },
    )
    assert r_p1.json()["items"][0]["id"] == id2

    r_p1_page2 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 40.9985,
            "longitude": 41.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 2,
            "page_size": 1,
        },
    )
    assert r_p1_page2.json()["items"][0]["id"] == id1

    # Probe 2 (different coordinate): Page 1 STILL has id2!
    r_p2 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 41.0025,
            "longitude": 41.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 1,
            "page_size": 1,
        },
    )
    assert r_p2.json()["items"][0]["id"] == id2


# ==============================================================================
# Scenario 3, 4, 5: Grid Snapping, Radius Membership, Transition Probing
# ==============================================================================


@pytest.mark.asyncio
async def test_search_origin_micro_stepping_constrained(client: AsyncClient) -> None:
    """Scenario 3: Search-origin micro-stepping is constrained for public discovery."""
    headers, _ = await register_and_login(client, "Micro Step User")
    run_id = uuid.uuid4().hex[:6]

    await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.OTHER.value,
            "title": f"Micro_{run_id}",
            "description": "Micro test item",
            "latitude": 42.0000,
            "longitude": 42.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )

    # 4 distinct sub-meter coordinates in same grid cell (42.00)
    probes = [42.0011, 42.0022, 42.0033, 42.0044]
    responses = []
    for p in probes:
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": p,
                "longitude": 42.0000,
                "radius_km": 1.0,
                "search": run_id,
            },
        )
        assert r.status_code == 200
        responses.append(r.json()["items"][0]["distance_km"])

    # All return the exact same quantized distance
    assert len(set(responses)) == 1


@pytest.mark.asyncio
async def test_radius_membership_grid_policy(client: AsyncClient) -> None:
    """Scenario 4: Radius membership is consistent with grid policy."""
    headers, _ = await register_and_login(client, "Radius User")
    run_id = uuid.uuid4().hex[:6]

    # Item at 43.00, 43.00
    await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.KEYS.value,
            "title": f"Radius_{run_id}",
            "description": "Radius test",
            "latitude": 43.0000,
            "longitude": 43.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )

    # Query from 43.00 at standard radii: 0.5, 1.0, 2.0, 5.0 km
    for radius in [0.5, 1.0, 2.0, 5.0]:
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": 43.00,
                "longitude": 43.00,
                "radius_km": radius,
                "search": run_id,
            },
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_quantization_transition_precision_containment(
    client: AsyncClient,
) -> None:
    """Scenario 5: Quantization transition probing cannot recover precision."""
    headers, _ = await register_and_login(client, "Transition User")
    run_id = uuid.uuid4().hex[:6]

    await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Trans_{run_id}",
            "description": "Transition test",
            "latitude": 44.0000,
            "longitude": 44.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )

    # Attempt bisection between 43.991 and 43.994
    probes = [43.9910, 43.9920, 43.9930, 43.9940]
    distances = []
    for p in probes:
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": p,
                "longitude": 44.0000,
                "radius_km": 2.0,
                "search": run_id,
            },
        )
        assert r.status_code == 200
        distances.append(r.json()["items"][0]["distance_km"])

    # Discrete step: all probes snap to 43.99 and yield the same value
    assert len(set(distances)) == 1


# ==============================================================================
# Scenario 6 & 8: Repeated Identical Query Stability & Discovery Compatibility
# ==============================================================================


@pytest.mark.asyncio
async def test_repeated_identical_queries_deterministic_stability(
    client: AsyncClient,
) -> None:
    """Scenario 6: Repeated identical queries return 100% deterministic results."""
    headers, _ = await register_and_login(client, "Stable User")
    run_id = uuid.uuid4().hex[:6]

    for i in range(3):
        await client.post(
            "/api/v1/reports",
            headers=headers,
            json={
                "type": ReportType.MISSING.value,
                "category": ReportCategory.OTHER.value,
                "title": f"Stable_{i}_{run_id}",
                "description": f"Stable {i}",
                "latitude": 45.0000 + (i * 0.002),
                "longitude": 45.0000,
                "event_time": datetime.now(UTC).isoformat(),
            },
        )

    # Execute identical query 5 times
    id_sequences = []
    for _ in range(5):
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": 45.00,
                "longitude": 45.00,
                "radius_km": 2.0,
                "sort": "distance",
                "search": run_id,
            },
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        id_sequences.append(ids)

    # All 5 sequences are identical
    for seq in id_sequences[1:]:
        assert seq == id_sequences[0]


@pytest.mark.asyncio
async def test_existing_valid_discovery_searches_work(client: AsyncClient) -> None:
    """Scenario 8: Existing valid discovery searches scale correctly."""
    headers, _ = await register_and_login(client, "Metro User")
    run_id = uuid.uuid4().hex[:6]

    # Chennai Central: 13.0827, 80.2707
    await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.BAG.value,
            "title": f"Chennai_{run_id}",
            "description": "Bag found at Chennai Central",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )

    # Kyiv Maidan: 50.4501, 30.5234
    await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.KEYS.value,
            "title": f"Kyiv_{run_id}",
            "description": "Keys lost near Maidan",
            "latitude": 50.4501,
            "longitude": 30.5234,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )

    # Chennai discovery query
    r_chennai = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 13.08,
            "longitude": 80.27,
            "radius_km": 2.0,
            "search": run_id,
        },
    )
    assert r_chennai.status_code == 200
    assert len(r_chennai.json()["items"]) == 1
    assert r_chennai.json()["items"][0]["title"] == f"Chennai_{run_id}"

    # Kyiv discovery query
    r_kyiv = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 50.45,
            "longitude": 30.52,
            "radius_km": 2.0,
            "search": run_id,
        },
    )
    assert r_kyiv.status_code == 200
    assert len(r_kyiv.json()["items"]) == 1
    assert r_kyiv.json()["items"][0]["title"] == f"Kyiv_{run_id}"


# ==============================================================================
# Scenario 9 & 10: Owner Exemption & Authoritative PostGIS Matching
# ==============================================================================


@pytest.mark.asyncio
async def test_owner_authorization_behavior_intact(client: AsyncClient) -> None:
    """Scenario 9: Owner authorization remains intact with un-snapped coordinates."""
    headers_owner, owner_id = await register_and_login(client, "True Owner")
    run_id = uuid.uuid4().hex[:6]
    raw_lat, raw_lon = 46.123456, 46.654321

    res = await client.post(
        "/api/v1/reports",
        headers=headers_owner,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"OwnerItem_{run_id}",
            "description": "Owner item",
            "latitude": raw_lat,
            "longitude": raw_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201

    # Owner querying own reports via user_id filter receives exact coordinates
    res_owner = await client.get(
        "/api/v1/reports",
        headers=headers_owner,
        params={"user_id": str(owner_id), "search": run_id},
    )
    assert res_owner.status_code == 200
    owner_item = res_owner.json()["items"][0]
    assert owner_item["latitude"] == raw_lat
    assert owner_item["longitude"] == raw_lon


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


@pytest.mark.asyncio
async def test_internal_matching_and_postgis_remain_authoritative(
    client: AsyncClient,
) -> None:
    """Scenario 10: Internal matching retrieval uses exact PostGIS ST_DWithin."""
    headers_miss, _ = await register_and_login(client, "Matcher Miss")
    headers_found, _ = await register_and_login(client, "Matcher Found")
    run_id = uuid.uuid4().hex[:6]

    res_missing = await client.post(
        "/api/v1/reports",
        headers=headers_miss,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"MatchMiss_{run_id}",
            "description": "Missing laptop",
            "latitude": 47.123456,
            "longitude": 47.654321,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    missing_id = uuid.UUID(res_missing.json()["id"])

    # Create found item 350m away (uncoarsened) by different user
    res_found = await client.post(
        "/api/v1/reports",
        headers=headers_found,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"MatchFound_{run_id}",
            "description": "Found laptop",
            "latitude": 47.126500,
            "longitude": 47.654321,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    found_id = uuid.UUID(res_found.json()["id"])

    # Retrieve candidate using authoritative spatial retrieval
    async with AsyncSessionLocal() as session:
        missing_report = await get_report_by_id(session, missing_id)
        assert missing_report is not None
        candidates = await retrieve_candidates(session, missing_report)

        candidate_ids = [c.candidate.id for c in candidates]
        assert found_id in candidate_ids
        # PostGIS calculates authoritative distance (not quantized to 0.5 km)
        cand = next(c for c in candidates if c.candidate.id == found_id)
        assert 300.0 < cand.distance_meters < 400.0
        assert cand.distance_km == round(cand.distance_meters / 1000.0, 2)


# ==============================================================================
# Scenario 11, 12, 13: Match Summaries, Coordinate Coarsening, Quantization
# ==============================================================================


@pytest.mark.asyncio
async def test_match_summaries_coarsened_opposite_distance_and_location(
    client: AsyncClient,
) -> None:
    """Scenario 11: Match summaries do not expose exact opposite distance."""
    headers_miss, _ = await register_and_login(client, "Miss Owner")
    headers_found, _ = await register_and_login(client, "Found Owner")
    run_id = uuid.uuid4().hex[:6]

    res_m = await client.post(
        "/api/v1/reports",
        headers=headers_miss,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"MissSum_{run_id}",
            "description": "Missing",
            "latitude": 48.123456,
            "longitude": 48.654321,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    m_id = uuid.UUID(res_m.json()["id"])

    res_f = await client.post(
        "/api/v1/reports",
        headers=headers_found,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"FoundSum_{run_id}",
            "description": "Found",
            "latitude": 48.126500,
            "longitude": 48.654321,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    f_id = uuid.UUID(res_f.json()["id"])

    # Persist match
    persistence = MatchPersistenceService()
    score_result = _make_score_result(
        source_id=m_id,
        candidate_id=f_id,
        composite_score=88.5,
        distance_meters=340.0,
    )
    async with AsyncSessionLocal() as session:
        missing_report = await get_report_by_id(session, m_id)
        assert missing_report is not None
        await persistence.record_matches(missing_report, [score_result], session)
        await session.commit()

    # Missing owner queries matches listing
    matches_res = await client.get(
        f"/api/v1/reports/{m_id}/matches",
        headers=headers_miss,
    )
    assert matches_res.status_code == 200
    match_items = matches_res.json()["items"]
    assert len(match_items) == 1
    match_id = match_items[0]["id"]

    # Missing owner checks match detail: opposite report is coarsened and quantized
    res_detail = await client.get(f"/api/v1/matches/{match_id}", headers=headers_miss)
    assert res_detail.status_code == 200
    found_summary = res_detail.json()["report_found"]
    # Coarsened to 2 decimal places
    assert found_summary["latitude"] == 48.13
    assert found_summary["longitude"] == 48.65
    # Quantized distance (0.34 km -> 0.5 km)
    assert found_summary["distance_km"] == 0.5


def test_phase_10_1_1_and_10_1_2_helpers_remain_compatible() -> None:
    """Scenario 12 & 13: Phase 10.1.1 coarsening and 10.1.2 quantization are intact."""
    # 10.1.1 Coordinate coarsening
    c_lat, c_lon = coarsen_coordinate(49.123456, 49.654321)
    assert c_lat == 49.12
    assert c_lon == 49.65

    # 10.1.2 Distance quantization
    assert coarsen_distance(0.23) == 0.0
    assert coarsen_distance(0.35) == 0.5
    assert coarsen_distance(0.85) == 1.0
    assert coarsen_distance(1.24) == 1.0
    assert coarsen_distance(1.26) == 1.5

    # 10.1.3 Search origin grid snapping
    s_lat, s_lon = snap_search_origin(49.123456, 49.654321)
    assert s_lat == 49.12
    assert s_lon == 49.65
    assert DISTANCE_BUCKET_SIZE_METERS == 500.0
