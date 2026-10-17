import uuid

import pytest
from httpx import AsyncClient


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


@pytest.mark.asyncio
async def test_create_recovery_request_on_missing_report(
    client: AsyncClient,
) -> None:
    # User A creates a Missing report
    headers_a = await register_and_login(client, "Owner A")
    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Gold Watch",
            "description": "Lost near central park",
            "category": "JEWELRY",
            "latitude": 40.785091,
            "longitude": -73.968285,
            "event_time": "2026-10-14T10:00:00Z",
            "reward_amount": "200.00",
        },
    )
    assert report_res.status_code == 201
    report_id = report_res.json()["id"]

    # User B creates a recovery request (Finder)
    headers_b = await register_and_login(client, "Finder B")
    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={
            "report_id": report_id,
            "message": "I found your gold watch near the fountain",
        },
    )
    assert rec_res.status_code == 201
    data = rec_res.json()
    assert data["report_id"] == report_id
    assert data["status"] == "PENDING"
    assert data["message"] == "I found your gold watch near the fountain"
    assert data["report"]["title"] == "Lost Gold Watch"
    assert data["requester"]["name"] == "Finder B"
    assert data["recipient"]["name"] == "Owner A"


@pytest.mark.asyncio
async def test_create_recovery_request_on_found_report(
    client: AsyncClient,
) -> None:
    # User B finds an item and reports it
    headers_b = await register_and_login(client, "Finder B")
    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_b,
        json={
            "type": "FOUND",
            "title": "Found Silver Laptop",
            "description": "Found on metro bench",
            "category": "ELECTRONICS",
            "latitude": 50.4501,
            "longitude": 30.5234,
            "event_time": "2026-10-14T11:00:00Z",
        },
    )
    assert report_res.status_code == 201
    report_id = report_res.json()["id"]

    # User A is the owner claiming it (without needing to create a missing report)
    headers_a = await register_and_login(client, "Claimant A")
    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_a,
        json={
            "report_id": report_id,
            "message": "That is my laptop, has serial #SN-998811",
        },
    )
    assert rec_res.status_code == 201
    assert rec_res.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_create_recovery_request_on_own_report_fails(
    client: AsyncClient,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Wallet",
            "description": "Lost wallet",
            "category": "WALLET",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    report_id = report_res.json()["id"]

    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_a,
        json={"report_id": report_id, "message": "My own report"},
    )
    assert rec_res.status_code == 400
    assert "own report" in rec_res.json()["detail"]


@pytest.mark.asyncio
async def test_create_duplicate_recovery_request_fails(
    client: AsyncClient,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Drone",
            "description": "Lost drone",
            "category": "ELECTRONICS",
            "latitude": 50.4501,
            "longitude": 30.5234,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    report_id = report_res.json()["id"]

    headers_b = await register_and_login(client, "Finder B")
    first_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": report_id, "message": "First attempt"},
    )
    assert first_res.status_code == 201

    # Second attempt should return 409 Conflict
    dup_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": report_id, "message": "Duplicate attempt"},
    )
    assert dup_res.status_code == 409


@pytest.mark.asyncio
async def test_list_and_get_recovery_requests_authorization(
    client: AsyncClient,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    headers_b = await register_and_login(client, "Finder B")
    headers_c = await register_and_login(client, "Stranger C")

    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Keys",
            "description": "Set of brass keys",
            "category": "KEYS",
            "latitude": 50.4501,
            "longitude": 30.5234,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    report_id = report_res.json()["id"]

    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": report_id, "message": "I have the keys"},
    )
    req_id = rec_res.json()["id"]

    # User A (recipient) lists received
    list_a = await client.get(
        "/api/v1/recovery-requests?type=received", headers=headers_a
    )
    assert list_a.status_code == 200
    assert any(item["id"] == req_id for item in list_a.json()["items"])

    # User B (requester) lists sent
    list_b = await client.get("/api/v1/recovery-requests?type=sent", headers=headers_b)
    assert list_b.status_code == 200
    assert any(item["id"] == req_id for item in list_b.json()["items"])

    # User C has no requests (isolation)
    list_c = await client.get("/api/v1/recovery-requests", headers=headers_c)
    assert list_c.status_code == 200
    assert not any(item["id"] == req_id for item in list_c.json()["items"])

    # Detail access: A and B can access, C gets 403 Forbidden
    detail_a = await client.get(
        f"/api/v1/recovery-requests/{req_id}", headers=headers_a
    )
    assert detail_a.status_code == 200

    detail_b = await client.get(
        f"/api/v1/recovery-requests/{req_id}", headers=headers_b
    )
    assert detail_b.status_code == 200

    detail_c = await client.get(
        f"/api/v1/recovery-requests/{req_id}", headers=headers_c
    )
    assert detail_c.status_code == 403


@pytest.mark.asyncio
async def test_recovery_lifecycle_and_state_transitions(
    client: AsyncClient,
) -> None:
    headers_a = await register_and_login(client, "Owner A")
    headers_b = await register_and_login(client, "Finder B")
    headers_c = await register_and_login(client, "Stranger C")

    report_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": "MISSING",
            "title": "Lost Backpack",
            "description": "Black Osprey pack",
            "category": "BAG",
            "latitude": 50.4501,
            "longitude": 30.5234,
            "event_time": "2026-10-14T10:00:00Z",
        },
    )
    report_id = report_res.json()["id"]

    rec_res = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": report_id, "message": "Backpack found at gym"},
    )
    req_id = rec_res.json()["id"]

    # 1. Stranger C cannot modify
    patch_c = await client.patch(
        f"/api/v1/recovery-requests/{req_id}",
        headers=headers_c,
        json={"status": "ACCEPTED"},
    )
    assert patch_c.status_code == 403

    # 2. Requester B cannot ACCEPT (only recipient A can accept)
    patch_b_accept = await client.patch(
        f"/api/v1/recovery-requests/{req_id}",
        headers=headers_b,
        json={"status": "ACCEPTED"},
    )
    assert patch_b_accept.status_code == 422

    # 3. Owner A accepts the request
    accept_res = await client.patch(
        f"/api/v1/recovery-requests/{req_id}",
        headers=headers_a,
        json={
            "status": "ACCEPTED",
            "verification_response": "Verified: blue water bottle inside",
        },
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "ACCEPTED"
    assert (
        accept_res.json()["verification_response"]
        == "Verified: blue water bottle inside"
    )

    # 4. Completed: Handover verified, marks underlying report RESOLVED
    complete_res = await client.patch(
        f"/api/v1/recovery-requests/{req_id}",
        headers=headers_a,
        json={"status": "COMPLETED"},
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["status"] == "COMPLETED"

    # Underlying report status should now be RESOLVED
    rep_check = await client.get(f"/api/v1/reports/{report_id}", headers=headers_a)
    assert rep_check.status_code == 200
    assert rep_check.json()["status"] == "RESOLVED"

    # 5. Cannot transition from terminal state COMPLETED
    terminal_res = await client.patch(
        f"/api/v1/recovery-requests/{req_id}",
        headers=headers_a,
        json={"status": "PENDING"},
    )
    assert terminal_res.status_code == 422
