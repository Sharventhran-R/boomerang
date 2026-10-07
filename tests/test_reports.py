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
