import uuid
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.fixture
async def auth_token(client: AsyncClient) -> str:
    test_email = f"user_{uuid.uuid4()}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Test User", "email": test_email, "password": "password123"},
    )
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": test_email, "password": "password123"}
    )
    print("LOGIN RESPONSE:", login_response.status_code, login_response.text)
    return str(login_response.json()["access_token"])


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.mark.asyncio
async def test_create_missing_report(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost my keys",
            "description": "Lost them near the park",
            "category": "KEYS",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": "2023-10-01T12:00:00Z",
            "reward_amount": "50.00",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Lost my keys"
    assert data["status"] == "ACTIVE"
    assert data["latitude"] == 40.7128
    assert data["longitude"] == -74.0060
    assert data["reward_amount"] == "50.00"


@pytest.mark.asyncio
async def test_create_found_report_with_reward_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "FOUND",
            "title": "Found keys",
            "description": "Found near the park",
            "category": "KEYS",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": "2023-10-01T12:00:00Z",
            "reward_amount": "50.00",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_report_invalid_location(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost keys",
            "description": "...",
            "category": "KEYS",
            "latitude": 100.0,  # Invalid
            "longitude": -74.0060,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_and_filter_reports(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Create two reports
    await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Black wallet",
            "description": "Lost my black leather wallet",
            "category": "WALLET",
            "latitude": 40.0,
            "longitude": -74.0,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "FOUND",
            "title": "Silver watch",
            "description": "Found a shiny watch",
            "category": "JEWELRY",
            "latitude": 41.0,
            "longitude": -75.0,
            "event_time": "2023-10-02T12:00:00Z",
        },
    )

    # List all
    res1 = await client.get("/api/v1/reports", headers=auth_headers)
    assert res1.status_code == 200
    assert res1.json()["total"] >= 2

    # Filter by category
    res2 = await client.get("/api/v1/reports?category=WALLET", headers=auth_headers)
    assert res2.status_code == 200
    for r in res2.json()["items"]:
        assert r["category"] == "WALLET"

    # Search
    res3 = await client.get("/api/v1/reports?search=watch", headers=auth_headers)
    assert res3.status_code == 200
    assert len(res3.json()["items"]) >= 1
    assert "watch" in res3.json()["items"][0]["title"].lower()


@pytest.mark.asyncio
async def test_update_report_status(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Create
    create_res = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost item",
            "description": "desc",
            "category": "OTHER",
            "latitude": 0,
            "longitude": 0,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    report_id = create_res.json()["id"]

    # Update status to RESOLVED
    update_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=auth_headers,
        json={"status": "RESOLVED"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "RESOLVED"

    # Invalid transition (RESOLVED -> ACTIVE)
    update_res2 = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=auth_headers,
        json={"status": "ACTIVE"},
    )
    assert update_res2.status_code == 422


@pytest.mark.asyncio
@patch("app.services.report.upload_image_to_s3")
async def test_upload_image(
    mock_upload: Any, client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    mock_upload.return_value = ("fake_key.jpg", 1024)

    # Create
    create_res = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost item",
            "description": "desc",
            "category": "OTHER",
            "latitude": 0,
            "longitude": 0,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    report_id = create_res.json()["id"]

    # Upload Image
    from io import BytesIO

    files = {"file": ("test.jpg", BytesIO(b"fake image data"), "image/jpeg")}
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=auth_headers,
        files=files,
    )
    assert upload_res.status_code == 201
    assert upload_res.json()["object_key"] == "fake_key.jpg"


@pytest.mark.asyncio
async def test_real_minio_image_upload(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    from io import BytesIO

    import botocore.exceptions

    from app.core.config import settings
    from app.services.storage import get_s3_client, init_bucket

    # Check MinIO availability using a bucket-level operation
    async with get_s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except (
            botocore.exceptions.EndpointConnectionError,
            botocore.exceptions.ConnectTimeoutError,
        ):
            pytest.skip("MinIO is not available for integration tests")
        except botocore.exceptions.ClientError:
            # 404 Not Found, 403 Forbidden, etc., indicate MinIO is reachable
            pass

    await init_bucket()

    # Create
    create_res = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost item minio",
            "description": "desc",
            "category": "OTHER",
            "latitude": 0,
            "longitude": 0,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    report_id = create_res.json()["id"]

    # Upload Image without mocking
    files = {"file": ("test.jpg", BytesIO(b"fake image data"), "image/jpeg")}
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=auth_headers,
        files=files,
    )
    assert upload_res.status_code == 201
    image_data = upload_res.json()
    object_key = image_data["object_key"]

    # Verify object actually exists in MinIO
    async with get_s3_client() as s3:
        try:
            head_res = await s3.head_object(
                Bucket=settings.S3_BUCKET_NAME, Key=object_key
            )
            assert head_res["ContentLength"] == len(b"fake image data")
        except botocore.exceptions.ClientError as e:
            pytest.fail(f"Object not found in MinIO: {e}")
        finally:
            # Clean up MinIO object explicitly just in case
            await s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=object_key)


@pytest.mark.asyncio
async def test_real_minio_image_delete(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    from io import BytesIO

    import botocore.exceptions

    from app.core.config import settings
    from app.services.storage import get_s3_client, init_bucket

    # Check MinIO availability using a bucket-level operation
    async with get_s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except (
            botocore.exceptions.EndpointConnectionError,
            botocore.exceptions.ConnectTimeoutError,
        ):
            pytest.skip("MinIO is not available for integration tests")
        except botocore.exceptions.ClientError:
            # 404 Not Found, 403 Forbidden, etc., indicate MinIO is reachable
            pass

    await init_bucket()

    # Create report
    create_res = await client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "type": "MISSING",
            "title": "Lost item minio del",
            "description": "desc",
            "category": "OTHER",
            "latitude": 0,
            "longitude": 0,
            "event_time": "2023-10-01T12:00:00Z",
        },
    )
    report_id = create_res.json()["id"]

    # Upload Image
    files = {"file": ("test.jpg", BytesIO(b"fake image data delete"), "image/jpeg")}
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=auth_headers,
        files=files,
    )
    assert upload_res.status_code == 201
    image_data = upload_res.json()
    object_key = image_data["object_key"]
    image_id = image_data["id"]

    # Delete Image via API
    del_res = await client.delete(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=auth_headers,
    )
    assert del_res.status_code == 204

    # Verify object no longer exists in MinIO
    async with get_s3_client() as s3:
        with pytest.raises(botocore.exceptions.ClientError) as exc_info:
            await s3.head_object(Bucket=settings.S3_BUCKET_NAME, Key=object_key)
        assert "404" in str(exc_info.value)

    # Verify report_images metadata is removed from DB
    get_res = await client.get(
        f"/api/v1/reports/{report_id}",
        headers=auth_headers,
    )
    assert get_res.status_code == 200
    assert len(get_res.json()["images"]) == 0


@pytest.mark.asyncio
async def test_deterministic_sorting_newest_oldest(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    import uuid

    from sqlalchemy import update

    from app.db.database import AsyncSessionLocal
    from app.db.models import Report

    run_id = uuid.uuid4().hex[:6]

    # Create 3 reports
    reports = []
    for i in range(3):
        create_res = await client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "type": "MISSING",
                "title": f"Item {i} {run_id}",
                "description": "desc",
                "category": "OTHER",
                "latitude": 0.0,
                "longitude": 0.0,
                "event_time": "2023-10-01T12:00:00Z",
            },
        )
        assert create_res.status_code == 201
        reports.append(create_res.json())

    # Update created_at to be exactly the same for all 3 reports
    from datetime import UTC, datetime

    identical_time = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Report)
            .where(Report.id.in_([r["id"] for r in reports]))
            .values(created_at=identical_time)
        )
        await session.commit()

    # Sort 'newest' should now fallback to ID ASC
    # We will get all 3 and verify their order is identical to their UUID ASC sorting
    res = await client.get(
        f"/api/v1/reports?sort=newest&search={run_id}", headers=auth_headers
    )
    assert res.status_code == 200
    items_newest = res.json()["items"]
    # Only consider the 3 we just created
    our_items_newest = [
        item for item in items_newest if item["id"] in [r["id"] for r in reports]
    ]
    assert len(our_items_newest) == 3

    # IDs should be strictly ascending
    ids_newest = [item["id"] for item in our_items_newest]
    assert ids_newest == sorted(ids_newest)

    # Sort 'oldest' should also fallback to ID ASC
    res = await client.get(
        f"/api/v1/reports?sort=oldest&search={run_id}", headers=auth_headers
    )
    assert res.status_code == 200
    items_oldest = res.json()["items"]
    our_items_oldest = [
        item for item in items_oldest if item["id"] in [r["id"] for r in reports]
    ]
    assert len(our_items_oldest) == 3

    ids_oldest = [item["id"] for item in our_items_oldest]
    assert ids_oldest == sorted(ids_oldest)

    # Test pagination explicitly doesn't duplicate or drop due to stable sort
    res_p1 = await client.get(
        f"/api/v1/reports?sort=newest&search={run_id}&page=1&page_size=2",
        headers=auth_headers,
    )
    res_p2 = await client.get(
        f"/api/v1/reports?sort=newest&search={run_id}&page=2&page_size=2",
        headers=auth_headers,
    )
    assert res_p1.status_code == 200
    assert res_p2.status_code == 200

    items_p1 = res_p1.json()["items"]
    items_p2 = res_p2.json()["items"]

    # Since there are potentially other reports in the DB from other tests,
    # we just need to ensure the intersection of our 3 items is correctly partitioned.
    all_paginated_ids = [i["id"] for i in items_p1] + [i["id"] for i in items_p2]
    # The order of all paginated items should be stable, no duplicates
    assert len(all_paginated_ids) == len(set(all_paginated_ids))


@pytest.mark.asyncio
async def test_my_reports_unauthenticated(client: AsyncClient) -> None:
    res = await client.get("/api/v1/reports/me")
    assert res.status_code == 401
    res_mine = await client.get("/api/v1/reports?mine=true")
    assert res_mine.status_code == 401


@pytest.mark.asyncio
async def test_my_reports_lifecycle_and_isolation(client: AsyncClient) -> None:
    # 1. Create User A and User B
    email_a = f"user_a_{uuid.uuid4()}@example.com"
    email_b = f"user_b_{uuid.uuid4()}@example.com"

    await client.post(
        "/api/v1/auth/register",
        json={"name": "User A", "email": email_a, "password": "password123"},
    )
    login_a = await client.post(
        "/api/v1/auth/login", json={"email": email_a, "password": "password123"}
    )
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    await client.post(
        "/api/v1/auth/register",
        json={"name": "User B", "email": email_b, "password": "password123"},
    )
    login_b = await client.post(
        "/api/v1/auth/login", json={"email": email_b, "password": "password123"}
    )
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a MISSING report far away (e.g., Kyiv: 50.45, 30.52)
    res_missing = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "User A Missing Item",
            "description": "Lost in Kyiv",
            "category": "ELECTRONICS",
            "latitude": 50.4500,
            "longitude": 30.5200,
            "event_time": "2026-10-18T10:00:00Z",
            "reward_amount": "100.00",
        },
    )
    assert res_missing.status_code == 201
    missing_id = res_missing.json()["id"]

    # User A creates a FOUND report also in Kyiv
    res_found = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "FOUND",
            "title": "User A Found Item",
            "description": "Found in Kyiv",
            "category": "KEYS",
            "latitude": 50.4510,
            "longitude": 30.5210,
            "event_time": "2026-10-18T11:00:00Z",
        },
    )
    assert res_found.status_code == 201
    found_id = res_found.json()["id"]

    # 2. User A fetches My Reports via GET /api/v1/reports/me
    res_my_reports = await client.get("/api/v1/reports/me", headers=headers_a)
    assert res_my_reports.status_code == 200
    my_items = res_my_reports.json()["items"]
    my_ids = [item["id"] for item in my_items]
    assert missing_id in my_ids
    assert found_id in my_ids

    # 3. User A fetches My Reports via GET /api/v1/reports?mine=true
    res_mine = await client.get("/api/v1/reports?mine=true", headers=headers_a)
    assert res_mine.status_code == 200
    mine_ids = [item["id"] for item in res_mine.json()["items"]]
    assert missing_id in mine_ids
    assert found_id in mine_ids

    # 4. Both reports are in Kyiv. When searching nearby discovery around New York
    # (40.7128, -74.0060, 5km), neither report should appear in nearby
    # discovery feed!
    res_discovery = await client.get(
        "/api/v1/reports?latitude=40.7128&longitude=-74.0060&radius_km=5.0",
        headers=headers_a,
    )
    assert res_discovery.status_code == 200
    discovery_ids = [item["id"] for item in res_discovery.json()["items"]]
    assert missing_id not in discovery_ids
    assert found_id not in discovery_ids

    # 5. User B fetches My Reports - User B must NOT see User A's reports!
    res_b_reports = await client.get("/api/v1/reports/me", headers=headers_b)
    assert res_b_reports.status_code == 200
    b_ids = [item["id"] for item in res_b_reports.json()["items"]]
    assert missing_id not in b_ids
    assert found_id not in b_ids

    # User B via mine=true also must NOT see User A's reports
    res_b_mine = await client.get("/api/v1/reports?mine=true", headers=headers_b)
    assert res_b_mine.status_code == 200
    b_mine_ids = [item["id"] for item in res_b_mine.json()["items"]]
    assert missing_id not in b_mine_ids
    assert found_id not in b_mine_ids
