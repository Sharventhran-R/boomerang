import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from geoalchemy2.elements import WKTElement
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
    User,
    UserDailyQuota,
    UserTrustTier,
)
from app.services.quota import get_daily_reset_window


async def create_authenticated_user(
    client: AsyncClient,
    name: str = "Quota User",
    trust_tier: UserTrustTier = UserTrustTier.NEW,
) -> tuple[dict[str, str], uuid.UUID]:
    """Helper to register and login a test user, optionally configuring trust tier."""
    email = f"quota_{uuid.uuid4()}@example.com"
    pwd = "Password123!"

    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": pwd},
        headers={"X-Forwarded-For": f"10.200.{uuid.uuid4().int % 250}.1"},
    )
    assert reg_res.status_code == 201, reg_res.text
    user_id = uuid.UUID(reg_res.json()["id"])

    if trust_tier != UserTrustTier.NEW:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(trust_tier=trust_tier)
            )
            await session.commit()

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
        headers={"X-Forwarded-For": f"10.200.{uuid.uuid4().int % 250}.2"},
    )
    assert login_res.status_code == 200, login_res.text
    token = login_res.json()["access_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": f"10.200.{uuid.uuid4().int % 250}.3",
    }
    return headers, user_id


def make_report_payload(report_type: str, title: str) -> dict[str, Any]:
    return {
        "type": report_type,
        "title": title,
        "description": "Test item for quota verification",
        "category": "ELECTRONICS",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "event_time": datetime.now(UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_missing_report_daily_limit_enforcement(client: AsyncClient) -> None:
    """1. Verifies a user cannot create more than 5 missing reports per day."""
    headers, _ = await create_authenticated_user(client, "Missing Quota User")

    # Create 5 missing reports (all should succeed)
    for i in range(settings.MISSING_REPORT_DAILY_LIMIT):
        res = await client.post(
            "/api/v1/reports",
            json=make_report_payload("MISSING", f"Missing Laptop {i}"),
            headers=headers,
        )
        assert res.status_code == 201, res.text

    # 6th attempt must be rejected with 429
    res_exceeded = await client.post(
        "/api/v1/reports",
        json=make_report_payload("MISSING", "Missing Laptop 6"),
        headers=headers,
    )
    assert res_exceeded.status_code == 429
    assert res_exceeded.headers.get("Retry-After") is not None
    assert "Daily missing report quota exceeded" in res_exceeded.json()["detail"]


@pytest.mark.asyncio
async def test_missing_report_active_cap_enforcement(client: AsyncClient) -> None:
    """2. Verifies user cannot exceed 10 simultaneously active missing reports."""
    headers, user_id = await create_authenticated_user(client, "Active Cap User")

    # Manually seed 10 active missing reports in DB across past days
    async with AsyncSessionLocal() as session:
        for i in range(settings.MISSING_REPORT_ACTIVE_LIMIT):
            rep = Report(
                created_by_user_id=user_id,
                type=ReportType.MISSING,
                title=f"Old Active Missing {i}",
                description="Past missing report",
                category=ReportCategory.ELECTRONICS,
                location=WKTElement("POINT(77.5946 12.9716)", srid=4326),
                status=ReportStatus.ACTIVE,
                event_time=datetime.now(UTC) - timedelta(days=2),
                created_at=datetime.now(UTC) - timedelta(days=2),
            )
            session.add(rep)
        await session.commit()

    # Even though daily quota for today has 0 consumed, active cap (10) blocks creation
    res = await client.post(
        "/api/v1/reports",
        json=make_report_payload("MISSING", "New Missing Exceeding Active Cap"),
        headers=headers,
    )
    assert res.status_code == 429
    assert "Active missing report limit reached" in res.json()["detail"]


@pytest.mark.asyncio
async def test_quota_consumption_is_non_refundable(client: AsyncClient) -> None:
    """3. Verifies resolving reports does NOT restore consumed daily quota."""
    headers, _ = await create_authenticated_user(client, "Non Refund User")

    # Create 5 missing reports to consume daily limit
    created_ids: list[str] = []
    for i in range(5):
        res = await client.post(
            "/api/v1/reports",
            json=make_report_payload("MISSING", f"Refund Test {i}"),
            headers=headers,
        )
        assert res.status_code == 201
        created_ids.append(res.json()["id"])

    # Resolve one of the reports
    first_id = created_ids[0]
    res_resolve = await client.patch(
        f"/api/v1/reports/{first_id}",
        json={"status": "RESOLVED"},
        headers=headers,
    )
    assert res_resolve.status_code == 200

    # Attempting to create a 6th missing report MUST STILL BE REJECTED
    res_retry = await client.post(
        "/api/v1/reports",
        json=make_report_payload("MISSING", "Refund Attempt"),
        headers=headers,
    )
    assert res_retry.status_code == 429
    assert "Daily missing report quota exceeded" in res_retry.json()["detail"]


@pytest.mark.asyncio
async def test_found_reports_tiered_quotas(client: AsyncClient) -> None:
    """4-6. Verifies found report limits per trust tier: NEW=5, ESTABLISHED=15."""
    # 1. NEW tier user has limit 5
    headers_new, _ = await create_authenticated_user(
        client, "New Tier User", trust_tier=UserTrustTier.NEW
    )
    for i in range(5):
        res = await client.post(
            "/api/v1/reports",
            json=make_report_payload("FOUND", f"Found Keys {i}"),
            headers=headers_new,
        )
        assert res.status_code == 201

    res_new_exceeded = await client.post(
        "/api/v1/reports",
        json=make_report_payload("FOUND", "Found Keys 6"),
        headers=headers_new,
    )
    assert res_new_exceeded.status_code == 429
    assert "NEW tier" in res_new_exceeded.json()["detail"]

    # 2. ESTABLISHED tier user has limit 15
    headers_est, est_uid = await create_authenticated_user(
        client, "Est Tier User", trust_tier=UserTrustTier.ESTABLISHED
    )
    # Directly set daily consumption in DB to 14
    today_date, _, _ = get_daily_reset_window()
    async with AsyncSessionLocal() as session:
        session.add(
            UserDailyQuota(
                user_id=est_uid,
                quota_date=today_date,
                missing_count=0,
                found_count=14,
            )
        )
        await session.commit()

    # 15th found report succeeds
    res_15th = await client.post(
        "/api/v1/reports",
        json=make_report_payload("FOUND", "Found Wallet 15"),
        headers=headers_est,
    )
    assert res_15th.status_code == 201

    # 16th found report rejected with 429
    res_16th = await client.post(
        "/api/v1/reports",
        json=make_report_payload("FOUND", "Found Wallet 16"),
        headers=headers_est,
    )
    assert res_16th.status_code == 429
    assert "ESTABLISHED tier" in res_16th.json()["detail"]


@pytest.mark.asyncio
async def test_concurrent_quota_consumption_safety(client: AsyncClient) -> None:
    """7. Verifies concurrent report creation cannot bypass quotas."""
    headers, _ = await create_authenticated_user(client, "Concurrent User")

    # Fire 10 simultaneous report creation requests when daily limit is 5
    results = await asyncio.gather(
        *(
            client.post(
                "/api/v1/reports",
                json=make_report_payload("MISSING", f"Concurrent Laptop {i}"),
                headers=headers,
            )
            for i in range(10)
        )
    )

    status_codes = [r.status_code for r in results]
    success_count = sum(1 for c in status_codes if c == 201)
    rejected_count = sum(1 for c in status_codes if c == 429)

    assert success_count == settings.MISSING_REPORT_DAILY_LIMIT
    assert rejected_count == 10 - settings.MISSING_REPORT_DAILY_LIMIT


@pytest.mark.asyncio
async def test_get_quota_status_endpoint(client: AsyncClient) -> None:
    """8. Verifies GET /api/v1/reports/quota-status returns complete quota metrics."""
    headers, user_id = await create_authenticated_user(
        client, "Status User", trust_tier=UserTrustTier.NEW
    )

    # Initially empty quotas
    res_init = await client.get("/api/v1/reports/quota-status", headers=headers)
    assert res_init.status_code == 200
    data = res_init.json()

    assert data["user_id"] == str(user_id)
    assert data["trust_tier"] == "NEW"
    assert data["missing_reports"]["daily_limit"] == 5
    assert data["missing_reports"]["daily_consumed"] == 0
    assert data["missing_reports"]["daily_remaining"] == 5
    assert data["missing_reports"]["active_limit"] == 10
    assert data["missing_reports"]["active_count"] == 0
    assert data["missing_reports"]["active_remaining"] == 10
    assert data["found_reports"]["daily_limit"] == 5
    assert data["found_reports"]["daily_consumed"] == 0
    assert data["found_reports"]["daily_remaining"] == 5
    assert "resets_at" in data

    # Create 2 missing reports and 1 found report
    await client.post(
        "/api/v1/reports",
        json=make_report_payload("MISSING", "Missing Item A"),
        headers=headers,
    )
    await client.post(
        "/api/v1/reports",
        json=make_report_payload("MISSING", "Missing Item B"),
        headers=headers,
    )
    await client.post(
        "/api/v1/reports",
        json=make_report_payload("FOUND", "Found Item C"),
        headers=headers,
    )

    # Check updated quotas
    res_updated = await client.get("/api/v1/reports/quota-status", headers=headers)
    assert res_updated.status_code == 200
    data_up = res_updated.json()
    assert data_up["missing_reports"]["daily_consumed"] == 2
    assert data_up["missing_reports"]["daily_remaining"] == 3
    assert data_up["missing_reports"]["active_count"] == 2
    assert data_up["missing_reports"]["active_remaining"] == 8
    assert data_up["found_reports"]["daily_consumed"] == 1
    assert data_up["found_reports"]["daily_remaining"] == 4
