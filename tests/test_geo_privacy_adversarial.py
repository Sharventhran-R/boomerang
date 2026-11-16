"""Adversarial security review test suite for Geographic Query Privacy (Phase 10.1.3).

Demonstrates and verifies containment of all four geographic inference channels:
1. Distance ordering no longer reveals exact perpendicular-bisector boundaries.
   Results are grouped into 500m coarse distance buckets, with ties broken
   by created_at DESC.
2. Radius membership bisection is defeated because search origins snap to a
   2-decimal grid (~1.1 km). Continuous sub-meter micro-stepping produces
   identical grid queries.
3. Quantization transition probing cannot recover exact 750m contours because
   probe coordinates snap to discrete grid cells.
4. Pagination rank order is stable within distance buckets; moving probes
   within a cell does not cause rank swaps across page boundaries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.db.models import ReportCategory, ReportType


async def register_and_login(
    client: AsyncClient, name: str
) -> tuple[dict[str, str], uuid.UUID]:
    email = f"adv_{uuid.uuid4().hex[:8]}@example.com"
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
# 1. Exact-Distance Ordering & Relative Proximity Inversion Defeated
# ==============================================================================


@pytest.mark.asyncio
async def test_adversarial_distance_order_inversion_bisector_recovery(
    client: AsyncClient,
) -> None:
    """Verifies that distance ordering no longer reveals perpendicular bisectors.

    Containment mechanism (Phase 10.1.3):
    - Public discovery groups items into 500-meter coarse distance buckets.
    - Ties within each bucket are broken strictly by created_at DESC, id ASC.
    - Authoritative ST_Distance is NEVER used as an intra-bucket tie-breaker.
    - Probe South and Probe North both return Item B before Item A because B
      was created more recently, completely neutralizing order inversion!
    """
    headers, _ = await register_and_login(client, "Adversary 1")
    run_id = uuid.uuid4().hex[:6]

    # Create Report A (Target) at lat=32.0000, lon=32.0000
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Target Item A {run_id}",
            "description": "High value target item",
            "latitude": 32.0000,
            "longitude": 32.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res_a.status_code == 201
    id_a = res_a.json()["id"]

    # Create Report B (Decoy) at lat=32.0010, lon=32.0000 (~111m north, created after A)
    res_b = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Decoy Item B {run_id}",
            "description": "Decoy item with known coordinates",
            "latitude": 32.0010,
            "longitude": 32.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res_b.status_code == 201
    id_b = res_b.json()["id"]

    # 1. Probe South at lat=31.9980 (both A and B fall into 500m bucket 0)
    res_south = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 31.9980,
            "longitude": 32.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
        },
    )
    assert res_south.status_code == 200
    items_south = res_south.json()["items"]
    assert len(items_south) == 2
    # Item B was created after A, so within bucket 0, B is ordered first
    assert items_south[0]["id"] == id_b
    assert items_south[1]["id"] == id_a

    # 2. Probe North at lat=32.0030 (both A and B still in bucket 0)
    res_north = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 32.0030,
            "longitude": 32.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
        },
    )
    assert res_north.status_code == 200
    items_north = res_north.json()["items"]
    assert len(items_north) == 2
    # Invariant! Item B is STILL ordered first because of created_at DESC
    assert items_north[0]["id"] == id_b
    assert items_north[1]["id"] == id_a

    # 3. Attempt Active Adversarial Bisection:
    # Because relative ordering is invariant to probe movement within the bucket,
    # binary search finds ZERO order flips!
    from app.core.redis import get_redis_client

    r_client = get_redis_client()

    low_lat = 31.9980
    high_lat = 32.0030
    order_inversion_detected = False
    for _ in range(12):
        # Controlled Redis state: reset discovery rate-limit key for test IP
        await r_client.delete("rl:reports:anon:ip:127.0.0.1")
        mid_lat = (low_lat + high_lat) / 2.0
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": round(mid_lat, 6),
                "longitude": 32.0000,
                "radius_km": 1.0,
                "sort": "distance",
                "search": run_id,
            },
        )
        assert r.status_code == 200, r.text
        first_id = r.json()["items"][0]["id"]
        if first_id != id_b:
            order_inversion_detected = True
            break
        low_lat = mid_lat

    # Order inversion is completely defeated: bisector cannot be traced!
    assert not order_inversion_detected


# ==============================================================================
# 2. Radius Membership & Boundary Bisection Attack Defeated
# ==============================================================================


@pytest.mark.asyncio
async def test_adversarial_boundary_membership_bisection_attack(
    client: AsyncClient,
) -> None:
    """Verifies that search-origin grid snapping neutralizes ST_DWithin bisection.

    Containment mechanism (Phase 10.1.3):
    - Public discovery queries snap search origin coordinates to 2 decimal
      places (~1.1 km).
    - An attacker attempting continuous micro-stepping across coordinates
      (e.g., 33.4910, 33.4920) produces the IDENTICAL snapped query point (33.49).
    - Bisection cannot locate continuous sub-meter circle boundaries.
    """
    headers, _ = await register_and_login(client, "Adversary 2")
    run_id = uuid.uuid4().hex[:6]
    target_lat = 33.500000
    target_lon = 33.500000

    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.BAG.value,
            "title": f"Target Backpack {run_id}",
            "description": "Backpack found near fountain",
            "latitude": target_lat,
            "longitude": target_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201
    target_id = res.json()["id"]

    # Probe 5 different micro-stepped coordinates inside the same grid cell:
    # 33.4910, 33.4920, 33.4930, 33.4940, 33.4944 all snap to 33.49
    micro_lats = [33.4910, 33.4920, 33.4930, 33.4940, 33.4944]
    results = []
    for m_lat in micro_lats:
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": m_lat,
                "longitude": target_lon,
                "radius_km": 1.0,
                "search": run_id,
            },
        )
        assert r.status_code == 200
        items = r.json()["items"]
        present = any(item["id"] == target_id for item in items)
        results.append(present)

    # All micro-stepped queries within the grid cell return the identical result!
    # (Continuous bisection is completely impossible within the cell)
    assert len(set(results)) == 1


# ==============================================================================
# 3. Quantization Step Transition Probing Defeated
# ==============================================================================


@pytest.mark.asyncio
async def test_adversarial_quantization_step_transition_attack(
    client: AsyncClient,
) -> None:
    """Verifies that quantization step transition bisection is blocked.

    Because probe coordinates are snapped to a 0.01 degree (~1.1 km) grid,
    an attacker cannot binary search for continuous 750m distance boundaries.
    Sub-grid variations produce identical query origins and discrete outputs.
    """
    headers, _ = await register_and_login(client, "Adversary 3")
    run_id = uuid.uuid4().hex[:6]
    target_lat = 34.000000
    target_lon = 34.000000

    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.JEWELRY.value,
            "title": f"Target Ring {run_id}",
            "description": "Gold ring lost near monument",
            "latitude": target_lat,
            "longitude": target_lon,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201
    target_id = res.json()["id"]

    # Micro-stepped probe queries between 33.991 and 33.994 snap to 33.99
    probe_lats = [33.9910, 33.9920, 33.9930, 33.9940]
    distance_reports = []
    for p_lat in probe_lats:
        r = await client.get(
            "/api/v1/reports",
            params={
                "latitude": p_lat,
                "longitude": target_lon,
                "radius_km": 2.0,
                "search": run_id,
            },
        )
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == target_id
        distance_reports.append(items[0]["distance_km"])

    # All micro-stepped coordinates yield the identical quantized distance
    assert len(set(distance_reports)) == 1
    # Attacker cannot locate intermediate continuous contours
    assert all(d in (1.0, 1.5) for d in distance_reports)


# ==============================================================================
# 4. Pagination Offset & Rank Stability Across Page Boundaries
# ==============================================================================


@pytest.mark.asyncio
async def test_adversarial_pagination_rank_leakage(client: AsyncClient) -> None:
    """Verifies that pagination with sort=distance does not leak proximity ranks.

    Items within the same 500m distance bucket are ordered by created_at DESC.
    Small movements of the probe coordinate within a grid cell do not invert
    ranks or cause items to swap page boundaries.
    """
    headers, _ = await register_and_login(client, "Adversary 4")
    run_id = uuid.uuid4().hex[:6]

    # Item 1 at (35.0000, 35.0000)
    res1 = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Paging Item 1 {run_id}",
            "description": "Rank tracking item 1",
            "latitude": 35.0000,
            "longitude": 35.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id1 = res1.json()["id"]

    # Item 2 at (35.0015, 35.0000) (~166m north, created after Item 1)
    res2 = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": f"Paging Item 2 {run_id}",
            "description": "Rank tracking item 2",
            "latitude": 35.0015,
            "longitude": 35.0000,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    id2 = res2.json()["id"]

    # From South probe (34.9980, 35.0000):
    # Both items are in bucket 0. Item 2 (created after) is Page 1; Item 1 is Page 2.
    r_p1 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 34.9980,
            "longitude": 35.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 1,
            "page_size": 1,
        },
    )
    assert r_p1.json()["items"][0]["id"] == id2

    r_p2 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 34.9980,
            "longitude": 35.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 2,
            "page_size": 1,
        },
    )
    assert r_p2.json()["items"][0]["id"] == id1

    # From North probe (35.0030, 35.0000):
    # Both items are STILL in bucket 0. Item 2 is STILL Page 1; Item 1 is STILL Page 2!
    r_north_p1 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 35.0030,
            "longitude": 35.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 1,
            "page_size": 1,
        },
    )
    assert r_north_p1.json()["items"][0]["id"] == id2

    r_north_p2 = await client.get(
        "/api/v1/reports",
        params={
            "latitude": 35.0030,
            "longitude": 35.0000,
            "radius_km": 1.0,
            "sort": "distance",
            "search": run_id,
            "page": 2,
            "page_size": 1,
        },
    )
    assert r_north_p2.json()["items"][0]["id"] == id1
