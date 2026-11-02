"""Integration tests for Boomerang Matching API endpoints (Phase 8.6).

Verifies:
- Authenticated match listing for MISSING reports.
- Authenticated match listing for FOUND reports.
- Opposite report safe public fields and distance presentation.
- Exclusion of non-ACTIVE (SUPPRESSED, DISQUALIFIED, RESOLVED) matches from normal feed.
- Score classification query filtering.
- Deterministic ordering by composite_score DESC, created_at DESC, id ASC.
- Pagination semantics (page, page_size, total, total_pages).
- Unauthenticated access rejection (401).
- Unauthorized access rejection for report matches (403).
- Nonexistent report handling (404).
- Match detail endpoint with explainability breakdown for missing/found owners.
- Match detail rejection for third-party users (403).
- Match detail nonexistent handling (404).
- Invalid UUID validation (422).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Match,
    MatchStatus,
    ScoreClassification,
)
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    TimeBreakdown,
)
from app.services.matching.persistence import (
    MatchPersistenceService,
    serialize_explainability,
)
from app.services.report import get_report_by_id


async def register_and_login(client: AsyncClient, name: str) -> dict[str, str]:
    email = f"user_{uuid.uuid4()}@example.com"
    password = "password123"
    await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    login_res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    token = str(login_res.json()["access_token"])
    return {"Authorization": f"Bearer {token}"}


def _make_score_result(
    source_id: uuid.UUID,
    candidate_id: uuid.UUID,
    composite_score: float,
    classification: ScoreClassification = ScoreClassification.HIGH_PRIORITY,
    alert_eligible: bool = True,
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
            matched_category="ELECTRONICS",
            matched_brand="Apple",
            matched_model="iPhone 15",
            matched_title_tokens=["iphone"],
        ),
        characteristics=CharacteristicsBreakdown(
            score=85.0,
            matched_colors=["black"],
            conflicting_colors=[],
            matched_cases=["silicone"],
            matched_accessories=[],
            matched_distinctive_marks=["corner scratch"],
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
            loss_time=now - timedelta(hours=3),
            found_time=now - timedelta(hours=1),
            delta_seconds=7200.0,
            delta_hours=2.0,
            delta_days=0.08,
            is_negative_delta=False,
            is_missing_time=False,
        ),
        raw_composite_score=composite_score,
        contradiction_penalty=0.0,
        composite_score=composite_score,
        classification=classification,
        alert_eligible=alert_eligible,
        minimum_evidence_satisfied=True,
        evidence_summary=(
            "Strong match across brand, model, and physical case within 350m."
        ),
        ineligibility_reasons=[],
    )


@pytest.mark.asyncio
async def test_list_matches_for_missing_report(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    # 1. User A creates MISSING report
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Space Black iPhone",
            "description": "Black silicone case with corner scratch",
            "category": "ELECTRONICS",
            "latitude": 40.785091,
            "longitude": -73.968285,
            "event_time": "2026-10-14T10:00:00Z",
            "reward_amount": "150.00",
        },
    )
    assert res_a.status_code == 201
    missing_id = uuid.UUID(res_a.json()["id"])

    # 2. User B creates FOUND report
    headers_b = await register_and_login(client, "Finder B")
    res_b = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "FOUND",
            "title": "Found iPhone in Central Park",
            "description": "Black phone found near bench with clear silicone case",
            "category": "ELECTRONICS",
            "latitude": 40.786000,
            "longitude": -73.967000,
            "event_time": "2026-10-14T12:00:00Z",
        },
    )
    assert res_b.status_code == 201
    found_id = uuid.UUID(res_b.json()["id"])

    # 3. Persist match
    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None
    score_result = _make_score_result(
        missing_id,
        found_id,
        composite_score=88.5,
        classification=ScoreClassification.HIGH_PRIORITY,
    )
    service = MatchPersistenceService()
    await service.record_matches(missing_report, [score_result], db)
    await db.commit()

    # 4. User A queries matches for their MISSING report
    list_res = await client.get(
        f"/api/v1/reports/{missing_id}/matches",
        headers=headers_a,
    )
    assert list_res.status_code == 200
    data = list_res.json()

    assert data["total"] == 1
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["total_pages"] == 1
    assert len(data["items"]) == 1

    match_item = data["items"][0]
    assert match_item["report_missing_id"] == str(missing_id)
    assert match_item["report_found_id"] == str(found_id)
    assert match_item["composite_score"] == 88.5
    assert match_item["classification"] == "HIGH_PRIORITY"
    assert match_item["alert_eligible"] is True
    assert "evidence_summary" in match_item

    # Opposite report is FOUND
    opp = match_item["opposite_report"]
    assert opp["id"] == str(found_id)
    assert opp["type"] == "FOUND"
    assert opp["title"] == "Found iPhone in Central Park"
    assert opp["category"] == "ELECTRONICS"
    assert opp["latitude"] is not None
    assert opp["longitude"] is not None
    assert opp["distance_km"] == 0.35
    assert "created_by_user_id" not in opp  # Zero private leak


@pytest.mark.asyncio
async def test_list_matches_for_found_report(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    # User A creates MISSING report
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Wallet",
            "description": "Brown leather wallet",
            "category": "WALLET",
            "latitude": 40.7580,
            "longitude": -73.9855,
            "event_time": "2026-10-15T09:00:00Z",
        },
    )
    assert res_a.status_code == 201
    missing_id = uuid.UUID(res_a.json()["id"])

    # User B creates FOUND report
    headers_b = await register_and_login(client, "Finder B")
    res_b = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "FOUND",
            "title": "Found Brown Wallet",
            "description": "Leather wallet found on subway bench",
            "category": "WALLET",
            "latitude": 40.7590,
            "longitude": -73.9845,
            "event_time": "2026-10-15T11:00:00Z",
        },
    )
    assert res_b.status_code == 201
    found_id = uuid.UUID(res_b.json()["id"])

    # Persist match
    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None
    score_result = _make_score_result(
        missing_id,
        found_id,
        composite_score=76.0,
        classification=ScoreClassification.POSSIBLE_MATCH,
        alert_eligible=False,
    )
    await MatchPersistenceService().record_matches(missing_report, [score_result], db)
    await db.commit()

    # User B queries matches for their FOUND report
    list_res = await client.get(
        f"/api/v1/reports/{found_id}/matches",
        headers=headers_b,
    )
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    # Opposite report is MISSING
    opp = data["items"][0]["opposite_report"]
    assert opp["id"] == str(missing_id)
    assert opp["type"] == "MISSING"
    assert opp["title"] == "Lost Wallet"


@pytest.mark.asyncio
async def test_list_matches_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    res = await client.get(f"/api/v1/reports/{uuid.uuid4()}/matches")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_list_matches_unauthorized_user_returns_403(
    client: AsyncClient,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Private Missing",
            "description": "Private description",
            "category": "KEYS",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    report_id = res_a.json()["id"]

    # User C tries to list matches for User A's report
    headers_c = await register_and_login(client, "Intruder C")
    res_c = await client.get(
        f"/api/v1/reports/{report_id}/matches",
        headers=headers_c,
    )
    assert res_c.status_code == 403
    assert "Not authorized" in res_c.json()["detail"]


@pytest.mark.asyncio
async def test_list_matches_nonexistent_report_returns_404(
    client: AsyncClient,
) -> None:
    headers = await register_and_login(client, "Legitimate User")
    res = await client.get(
        f"/api/v1/reports/{uuid.uuid4()}/matches",
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Report not found"


@pytest.mark.asyncio
async def test_list_matches_excludes_non_active_matches(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Backpack",
            "description": "Blue canvas bag",
            "category": "BAG",
            "latitude": 40.7200,
            "longitude": -73.9900,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    missing_id = uuid.UUID(res_a.json()["id"])

    # Create 3 found reports
    headers_b = await register_and_login(client, "Finder B")
    f_ids: list[uuid.UUID] = []
    for i in range(3):
        res_f = await client.post(
            "/api/v1/reports",
            headers=headers_b,
            json={
                "type": "FOUND",
                "title": f"Found Bag {i}",
                "description": f"Bag candidate {i}",
                "category": "BAG",
                "latitude": 40.7205 + (i * 0.001),
                "longitude": -73.9905,
                "event_time": "2026-10-14T12:00:00Z",
            },
        )
        f_ids.append(uuid.UUID(res_f.json()["id"]))

    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None

    # Persist one active match
    res_active = _make_score_result(
        missing_id,
        f_ids[0],
        composite_score=82.0,
        classification=ScoreClassification.HIGH_PRIORITY,
    )
    await MatchPersistenceService().record_matches(missing_report, [res_active], db)

    # Directly insert one SUPPRESSED match and one DISQUALIFIED match into DB
    res_supp = _make_score_result(
        missing_id,
        f_ids[1],
        composite_score=38.0,
        classification=ScoreClassification.DISQUALIFIED,
    )
    db.add(
        Match(
            report_missing_id=missing_id,
            report_found_id=f_ids[1],
            status=MatchStatus.SUPPRESSED,
            composite_score=38.0,
            score_identity=res_supp.identity.score,
            score_characteristics=res_supp.characteristics.score,
            score_distance=res_supp.distance.score,
            score_time=res_supp.time.score,
            raw_composite_score=38.0,
            contradiction_penalty=0.0,
            classification=ScoreClassification.DISQUALIFIED,
            alert_eligible=False,
            minimum_evidence_satisfied=False,
            evidence_summary="Suppressed test match",
            explainability_details=serialize_explainability(res_supp),
            scoring_version=1,
            last_scored_at=datetime.now(UTC),
        )
    )
    db.add(
        Match(
            report_missing_id=missing_id,
            report_found_id=f_ids[2],
            status=MatchStatus.DISQUALIFIED,
            composite_score=20.0,
            score_identity=10.0,
            score_characteristics=10.0,
            score_distance=10.0,
            score_time=10.0,
            raw_composite_score=20.0,
            contradiction_penalty=0.0,
            classification=ScoreClassification.DISQUALIFIED,
            alert_eligible=False,
            minimum_evidence_satisfied=False,
            evidence_summary="Disqualified test match",
            explainability_details={},
            scoring_version=1,
            last_scored_at=datetime.now(UTC),
        )
    )
    await db.commit()

    # Query active feed
    res = await client.get(
        f"/api/v1/reports/{missing_id}/matches",
        headers=headers_a,
    )
    assert res.status_code == 200
    feed = res.json()
    assert feed["total"] == 1
    assert feed["items"][0]["report_found_id"] == str(f_ids[0])
    assert feed["items"][0]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_list_matches_classification_filter_and_pagination(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Keys",
            "description": "Keychain with 3 brass keys",
            "category": "KEYS",
            "latitude": 40.7300,
            "longitude": -73.9950,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    missing_id = uuid.UUID(res_a.json()["id"])
    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None

    headers_b = await register_and_login(client, "Finder B")
    f_ids: list[uuid.UUID] = []
    # Create 3 found reports
    for i in range(3):
        res_f = await client.post(
            "/api/v1/reports",
            headers=headers_b,
            json={
                "type": "FOUND",
                "title": f"Found Keys {i}",
                "description": f"Found keys on ground {i}",
                "category": "KEYS",
                "latitude": 40.7302 + (i * 0.001),
                "longitude": -73.9952,
                "event_time": "2026-10-14T12:00:00Z",
            },
        )
        f_ids.append(uuid.UUID(res_f.json()["id"]))

    scores = [
        (f_ids[0], 92.0, ScoreClassification.HIGH_PRIORITY),
        (f_ids[1], 84.0, ScoreClassification.HIGH_PRIORITY),
        (f_ids[2], 68.0, ScoreClassification.POSSIBLE_MATCH),
    ]
    for fid, score, classification in scores:
        sr = _make_score_result(
            missing_id,
            fid,
            composite_score=score,
            classification=classification,
        )
        await MatchPersistenceService().record_matches(missing_report, [sr], db)
    await db.commit()

    # 1. Filter by HIGH_PRIORITY
    res_filter = await client.get(
        f"/api/v1/reports/{missing_id}/matches?classification=HIGH_PRIORITY",
        headers=headers_a,
    )
    assert res_filter.status_code == 200
    filtered_data = res_filter.json()
    assert filtered_data["total"] == 2
    assert all(
        item["classification"] == "HIGH_PRIORITY" for item in filtered_data["items"]
    )

    # 2. Filter by POSSIBLE_MATCH
    res_pm = await client.get(
        f"/api/v1/reports/{missing_id}/matches?classification=POSSIBLE_MATCH",
        headers=headers_a,
    )
    assert res_pm.status_code == 200
    pm_data = res_pm.json()
    assert pm_data["total"] == 1
    assert pm_data["items"][0]["composite_score"] == 68.0

    # 3. Pagination & Deterministic Ordering (descending score: 92.0, 84.0, 68.0)
    page1 = await client.get(
        f"/api/v1/reports/{missing_id}/matches?page=1&page_size=2",
        headers=headers_a,
    )
    assert page1.status_code == 200
    d1 = page1.json()
    assert d1["total"] == 3
    assert d1["total_pages"] == 2
    assert len(d1["items"]) == 2
    assert d1["items"][0]["composite_score"] == 92.0
    assert d1["items"][1]["composite_score"] == 84.0

    page2 = await client.get(
        f"/api/v1/reports/{missing_id}/matches?page=2&page_size=2",
        headers=headers_a,
    )
    assert page2.status_code == 200
    d2 = page2.json()
    assert len(d2["items"]) == 1
    assert d2["items"][0]["composite_score"] == 68.0


@pytest.mark.asyncio
async def test_get_match_detail_authorized_owner_roles(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    res_a = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Rolex Submariner",
            "description": "Steel bracelet, black ceramic bezel",
            "category": "JEWELRY",
            "latitude": 40.7500,
            "longitude": -73.9800,
            "event_time": "2026-10-14T10:00:00Z",
            "reward_amount": "500.00",
        },
    )
    missing_id = uuid.UUID(res_a.json()["id"])

    headers_b = await register_and_login(client, "Finder B")
    res_b = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "FOUND",
            "title": "Found Luxury Diver Watch",
            "description": "Heavy diver watch in stainless steel",
            "category": "JEWELRY",
            "latitude": 40.7510,
            "longitude": -73.9810,
            "event_time": "2026-10-14T14:00:00Z",
        },
    )
    found_id = uuid.UUID(res_b.json()["id"])

    missing_report = await get_report_by_id(db, missing_id)
    assert missing_report is not None
    sr = _make_score_result(
        missing_id,
        found_id,
        composite_score=91.5,
        classification=ScoreClassification.HIGH_PRIORITY,
        distance_meters=220.0,
    )
    await MatchPersistenceService().record_matches(missing_report, [sr], db)
    await db.commit()

    # Get match ID from missing listing
    matches_res = await client.get(
        f"/api/v1/reports/{missing_id}/matches",
        headers=headers_a,
    )
    match_id = matches_res.json()["items"][0]["id"]

    # 1. Missing report owner inspects detail
    detail_a = await client.get(
        f"/api/v1/matches/{match_id}",
        headers=headers_a,
    )
    assert detail_a.status_code == 200
    da = detail_a.json()
    assert da["id"] == match_id
    assert da["user_role"] == "MISSING"
    assert da["composite_score"] == 91.5
    assert da["score_identity"] == 90.0
    assert da["score_characteristics"] == 85.0
    assert da["score_distance"] == 93.0
    assert da["score_time"] == 95.0
    assert da["classification"] == "HIGH_PRIORITY"
    assert da["alert_eligible"] is True
    assert da["scoring_version"] == 1
    assert "explainability_details" in da
    assert da["explainability_details"]["distance"]["distance_meters"] == 220.0
    assert da["report_missing"]["title"] == "Lost Rolex Submariner"
    assert da["report_found"]["title"] == "Found Luxury Diver Watch"
    assert da["report_missing"]["latitude"] is not None
    assert da["report_found"]["latitude"] is not None

    # 2. Found report owner inspects detail
    detail_b = await client.get(
        f"/api/v1/matches/{match_id}",
        headers=headers_b,
    )
    assert detail_b.status_code == 200
    db_json = detail_b.json()
    assert db_json["user_role"] == "FOUND"

    # 3. Unauthorized third party receives 403
    headers_c = await register_and_login(client, "Intruder C")
    detail_c = await client.get(
        f"/api/v1/matches/{match_id}",
        headers=headers_c,
    )
    assert detail_c.status_code == 403
    assert detail_c.json()["detail"] == "Not authorized to access this match"


@pytest.mark.asyncio
async def test_get_match_detail_nonexistent_returns_404(
    client: AsyncClient,
) -> None:
    headers = await register_and_login(client, "User Any")
    res = await client.get(
        f"/api/v1/matches/{uuid.uuid4()}",
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Match not found"


@pytest.mark.asyncio
async def test_invalid_uuid_returns_422(
    client: AsyncClient,
) -> None:
    headers = await register_and_login(client, "User Any")
    res1 = await client.get("/api/v1/matches/not-a-uuid", headers=headers)
    assert res1.status_code == 422

    res2 = await client.get("/api/v1/reports/not-a-uuid/matches", headers=headers)
    assert res2.status_code == 422
