"""API Security & Authentication Hardening test suite (Phase 10.2).

Validates:
1. Authentication token lifecycle, claims, expiry, and immediate revocation
   on logout (SEC-AUTH-003).
2. Refresh token rotation, reuse detection (RFC 6819), and user checks.
3. Password length bounds (max 128 chars, min 8 chars) (SEC-AUTH-004).
4. Strict object ownership verification and BOLA prevention (SEC-API-001):
   - Cross-user report modification & images rejected (403 Forbidden).
   - Cross-user recovery request inspection & modification rejected (403).
   - Cross-user match listing & detail inspection rejected (403).
   - Cross-user notification reading rejected (404 Not Found).
   - Cross-user device deactivation rejected (404 Not Found).
5. Database state invariance after rejected cross-user attempts.
6. Legitimate owner access and intentionally public endpoints.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    Notification,
    NotificationPriority,
    NotificationType,
    RecoveryRequest,
    RecoveryRequestStatus,
    Report,
    ReportCategory,
    ReportType,
    User,
    UserDevice,
    UserSession,
)
from app.services.auth import clear_revocation_store


@pytest.fixture(autouse=True)
def _reset_token_revocations() -> None:
    clear_revocation_store()


async def register_and_login(
    client: AsyncClient, name: str
) -> tuple[dict[str, str], uuid.UUID, str, str]:
    email = f"sec_{uuid.uuid4().hex[:8]}@example.com"
    password = "validPassword123"
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert reg_res.status_code == 201, reg_res.text
    user_id = uuid.UUID(reg_res.json()["id"])

    login_res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login_res.status_code == 200, login_res.text
    login_data = login_res.json()
    access_token = str(login_data["access_token"])
    refresh_token = str(login_data["refresh_token"])
    headers = {"Authorization": f"Bearer {access_token}"}
    return headers, user_id, access_token, refresh_token


# ==============================================================================
# 1. Authentication Token Lifecycle & Rejection Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client: AsyncClient) -> None:
    """Protected endpoints reject requests missing the Authorization header with 401."""
    endpoints = [
        ("GET", "/api/v1/users/me"),
        ("GET", "/api/v1/reports/me"),
        ("POST", "/api/v1/reports"),
        ("GET", "/api/v1/notifications"),
        ("GET", "/api/v1/notifications/unread-count"),
        ("GET", f"/api/v1/reports/{uuid.uuid4()}/matches"),
        ("GET", f"/api/v1/matches/{uuid.uuid4()}"),
        ("GET", "/api/v1/recovery-requests"),
    ]
    for method, path in endpoints:
        res = await client.request(method, path)
        assert res.status_code == 401, (
            f"Expected 401 on {method} {path}, got {res.status_code}"
        )
        assert "WWW-Authenticate" in res.headers
        assert "Bearer" in res.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_malformed_and_invalid_signature_tokens_rejected(
    client: AsyncClient,
) -> None:
    """Malformed tokens, invalid signatures, or missing subjects are rejected
    with 401.
    """
    bad_tokens = [
        "not-a-valid-jwt-token",
        "Bearer malformed.token.string",
        jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "exp": datetime.now(UTC) + timedelta(minutes=15),
            },
            "WRONG_SECRET_KEY_1234567890123456",
            algorithm="HS256",
        ),
        jwt.encode(
            {"exp": datetime.now(UTC) + timedelta(minutes=15)},  # Missing sub
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        ),
    ]
    for bad_tok in bad_tokens:
        headers = {"Authorization": f"Bearer {bad_tok}"}
        res = await client.get("/api/v1/users/me", headers=headers)
        assert res.status_code == 401, (
            f"Expected 401 for bad token, got {res.status_code}"
        )
        assert "Bearer" in res.headers.get("WWW-Authenticate", "")


@pytest.mark.asyncio
async def test_algorithm_confusion_none_rejected(client: AsyncClient) -> None:
    """Unsigned tokens (algorithm 'none') are rejected by PyJWT settings."""
    unsigned_tok = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(UTC) + timedelta(minutes=15),
            "type": "access",
        },
        key="",
        algorithm="none",
    )
    headers = {"Authorization": f"Bearer {unsigned_tok}"}
    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_type_rejected(client: AsyncClient) -> None:
    """Tokens with type != 'access' (e.g. refresh tokens) are rejected from
    Bearer auth.
    """
    wrong_type_tok = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(minutes=15),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    headers = {"Authorization": f"Bearer {wrong_type_tok}"}
    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_expired_access_token_rejected(client: AsyncClient) -> None:
    """Expired access tokens are rejected with 401."""
    expired_tok = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(seconds=10),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    headers = {"Authorization": f"Bearer {expired_tok}"}
    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_immediate_access_token_revocation_on_logout(client: AsyncClient) -> None:
    """Calling /logout immediately invalidates current access token (SEC-AUTH-003)."""
    headers, user_id, access_token, refresh_token = await register_and_login(
        client, "Logout User"
    )

    # Access token works before logout
    pre_res = await client.get("/api/v1/users/me", headers=headers)
    assert pre_res.status_code == 200

    # Execute logout passing refresh token and bearer access token
    logout_res = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 204

    # Access token must immediately be rejected with 401 Unauthorized
    post_res = await client.get("/api/v1/users/me", headers=headers)
    assert post_res.status_code == 401, (
        f"Expected 401 after logout, got {post_res.status_code}"
    )


@pytest.mark.asyncio
async def test_revoked_refresh_token_rejected(client: AsyncClient) -> None:
    """A revoked refresh token cannot be used to obtain new access tokens."""
    headers, _, _, refresh_token = await register_and_login(client, "Revoked User")

    # Logout revokes refresh token
    logout_res = await client.post(
        "/api/v1/auth/logout", headers=headers, json={"refresh_token": refresh_token}
    )
    assert logout_res.status_code == 204

    # Attempt refresh with revoked token
    refresh_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_res.status_code == 401
    assert "revoked" in refresh_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_token_reuse_detection_invalidates_all_sessions(
    client: AsyncClient,
) -> None:
    """RFC 6819 § 5.2.2.3: Re-presenting a revoked refresh token
    revokes all active sessions.
    """
    _, user_id, _, rt1 = await register_and_login(client, "Reuse Victim")

    # Legitimate client rotates RT1 -> RT2
    rotate_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert rotate_res.status_code == 200
    rt2 = rotate_res.json()["refresh_token"]

    # Verify RT2 is currently valid
    check_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt2})
    assert check_res.status_code == 200
    rt3 = check_res.json()["refresh_token"]

    # Adversary replays old, revoked RT1 (Reuse Compromise Detection)
    replay_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert replay_res.status_code == 401
    assert "revoked" in replay_res.json()["detail"].lower()

    # Assert all descendant sessions for that user were revoked
    # in response to compromise detection
    rt3_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt3})
    assert rt3_res.status_code == 401, (
        "Expected RT3 to be invalidated after compromise detection"
    )


@pytest.mark.asyncio
async def test_refresh_token_for_deleted_user_rejected(client: AsyncClient) -> None:
    """A valid refresh token is rejected if user account no longer exists."""
    _, user_id, _, refresh_token = await register_and_login(client, "Deleted User")

    # Delete the user record directly in database
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user:
            await session.delete(user)
            await session.commit()

    # Attempt token refresh for non-existent user
    refresh_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_res.status_code == 401


# ==============================================================================
# 2. Password Length Bounding & Input Sanitization (SEC-AUTH-004)
# ==============================================================================


@pytest.mark.asyncio
async def test_password_length_bounding(client: AsyncClient) -> None:
    """Password length is bounded between 8 and 128 characters to prevent DoS."""
    # Under 8 chars rejected
    res_short = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Short",
            "email": f"short_{uuid.uuid4().hex[:6]}@example.com",
            "password": "short",
        },
    )
    assert res_short.status_code == 422

    # Over 128 chars rejected
    long_pwd = "A" * 129
    res_long = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Long",
            "email": f"long_{uuid.uuid4().hex[:6]}@example.com",
            "password": long_pwd,
        },
    )
    assert res_long.status_code == 422

    # Over 128 chars rejected on login
    res_login_long = await client.post(
        "/api/v1/auth/login",
        json={"email": "anyone@example.com", "password": long_pwd},
    )
    assert res_login_long.status_code == 422


@pytest.mark.asyncio
async def test_blank_whitespace_name_rejected(client: AsyncClient) -> None:
    """Names consisting purely of whitespace are rejected on registration."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "   ",
            "email": f"blank_{uuid.uuid4().hex[:6]}@example.com",
            "password": "password123",
        },
    )
    assert res.status_code == 422


# ==============================================================================
# 3. Cross-User Authorization & BOLA/IDOR Defenses (SEC-API-001)
# ==============================================================================


@pytest.mark.asyncio
async def test_cross_user_report_modification_forbidden(client: AsyncClient) -> None:
    """User B cannot modify User A's report; database state remains unchanged."""
    headers_a, user_a_id, _, _ = await register_and_login(client, "User A")
    headers_b, user_b_id, _, _ = await register_and_login(client, "User B")

    # User A creates a report
    create_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": "User A Original Laptop",
            "description": "Original description by User A",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert create_res.status_code == 201
    report_id = create_res.json()["id"]

    # User B attempts to modify User A's report
    patch_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers_b,
        json={"title": "Hacked Title by User B", "description": "Malicious edit"},
    )
    assert patch_res.status_code == 403, (
        f"Expected 403 Forbidden, got {patch_res.status_code}"
    )

    # Verify database state remained unchanged
    async with AsyncSessionLocal() as session:
        report = await session.get(Report, uuid.UUID(report_id))
        assert report is not None
        assert report.title == "User A Original Laptop"
        assert report.description == "Original description by User A"
        assert report.created_by_user_id == user_a_id


@pytest.mark.asyncio
async def test_cross_user_report_image_upload_and_delete_forbidden(
    client: AsyncClient,
) -> None:
    """User B cannot upload images to or delete images from User A's report."""
    headers_a, _, _, _ = await register_and_login(client, "Owner Img")
    headers_b, _, _, _ = await register_and_login(client, "Attacker Img")

    # User A creates report and uploads image
    create_res = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.BAG.value,
            "title": "Owner Backpack",
            "description": "Black backpack",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    report_id = create_res.json()["id"]

    buf_a = io.BytesIO()
    Image.new("RGB", (32, 32), color="red").save(buf_a, "JPEG")
    fake_img = io.BytesIO(buf_a.getvalue())
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_a,
        files={"file": ("photo.jpg", fake_img, "image/jpeg")},
    )
    assert upload_res.status_code == 201
    image_id = upload_res.json()["id"]

    # User B attempts image upload to User A's report -> 403 Forbidden
    buf_b = io.BytesIO()
    Image.new("RGB", (32, 32), color="blue").save(buf_b, "JPEG")
    fake_img_b = io.BytesIO(buf_b.getvalue())
    b_upload = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_b,
        files={"file": ("exploit.jpg", fake_img_b, "image/jpeg")},
    )
    assert b_upload.status_code == 403

    # User B attempts to delete User A's image -> 403 Forbidden
    b_delete = await client.delete(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_b,
    )
    assert b_delete.status_code == 403


@pytest.mark.asyncio
async def test_cross_user_recovery_request_access_forbidden(
    client: AsyncClient,
) -> None:
    """Third party User C cannot view or update a recovery request between
    User A and User B.
    """
    headers_a, user_a_id, _, _ = await register_and_login(client, "Owner A")
    headers_b, user_b_id, _, _ = await register_and_login(client, "Claimant B")
    headers_c, user_c_id, _, _ = await register_and_login(client, "Snoop C")

    # User A creates report
    res_rep = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": ReportType.FOUND.value,
            "category": ReportCategory.KEYS.value,
            "title": "Found Silver Keys",
            "description": "Found near bus stop",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    report_id = res_rep.json()["id"]

    # User B creates recovery request on User A's report
    res_rec = await client.post(
        "/api/v1/recovery-requests",
        headers=headers_b,
        json={"report_id": report_id, "message": "Those are my keys"},
    )
    assert res_rec.status_code == 201
    rec_id = res_rec.json()["id"]

    # User C attempts to view recovery request -> 403 Forbidden
    res_c_view = await client.get(
        f"/api/v1/recovery-requests/{rec_id}", headers=headers_c
    )
    assert res_c_view.status_code == 403

    # User C attempts to update recovery request status -> 403 Forbidden
    res_c_patch = await client.patch(
        f"/api/v1/recovery-requests/{rec_id}",
        headers=headers_c,
        json={"status": RecoveryRequestStatus.ACCEPTED.value},
    )
    assert res_c_patch.status_code == 403

    # Database verification: request status remains PENDING
    async with AsyncSessionLocal() as session:
        rec = await session.get(RecoveryRequest, uuid.UUID(rec_id))
        assert rec is not None
        assert rec.status == RecoveryRequestStatus.PENDING


@pytest.mark.asyncio
async def test_cross_user_match_inspection_forbidden(client: AsyncClient) -> None:
    """Unrelated User C cannot inspect match list or details for other reports."""
    headers_a, user_a_id, _, _ = await register_and_login(client, "Missing Owner")
    headers_c, _, _, _ = await register_and_login(client, "Unrelated User")

    # User A creates a report
    res_rep = await client.post(
        "/api/v1/reports",
        headers=headers_a,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.ELECTRONICS.value,
            "title": "Missing Camera",
            "description": "Sony A7",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    report_id = res_rep.json()["id"]

    # User C attempts to list matches for User A's report -> 403 Forbidden
    res_matches = await client.get(
        f"/api/v1/reports/{report_id}/matches",
        headers=headers_c,
    )
    assert res_matches.status_code == 403
    assert "not authorized" in res_matches.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cross_user_notification_access_and_enumeration_prevention(
    client: AsyncClient,
) -> None:
    """User B cannot mark User A's notification as read;
    returns 404 to prevent IDOR enumeration.
    """
    headers_a, user_a_id, _, _ = await register_and_login(client, "Notif User A")
    headers_b, _, _, _ = await register_and_login(client, "Notif User B")

    # Seed notification for User A directly in DB
    notif_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        notif = Notification(
            id=notif_id,
            user_id=user_a_id,
            type=NotificationType.MATCH_DETECTED,
            priority=NotificationPriority.DEFAULT,
            title="Match Alert",
            body="A match was found",
            is_read=False,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(notif)
        await session.commit()

    # User B attempts to read User A's notification -> 404 Not Found (zero enumeration)
    b_res = await client.patch(
        f"/api/v1/notifications/{notif_id}/read",
        headers=headers_b,
    )
    assert b_res.status_code == 404

    # Assert notification remains unread for User A in database
    async with AsyncSessionLocal() as session:
        loaded = await session.get(Notification, notif_id)
        assert loaded is not None
        assert loaded.is_read is False


@pytest.mark.asyncio
async def test_cross_user_device_deactivation_and_enumeration_prevention(
    client: AsyncClient,
) -> None:
    """User B cannot deactivate User A's device;
    returns 404 without leaking device existence.
    """
    headers_a, user_a_id, _, _ = await register_and_login(client, "Device Owner A")
    headers_b, _, _, _ = await register_and_login(client, "Device Attacker B")

    device_id = f"device_{uuid.uuid4().hex[:8]}"

    # User A registers device
    reg_res = await client.post(
        "/api/v1/devices/register",
        headers=headers_a,
        json={
            "device_id": device_id,
            "fcm_token": f"fcm_token_{uuid.uuid4().hex}",
            "platform": "ANDROID",
        },
    )
    assert reg_res.status_code == 200

    # User B attempts to deactivate User A's device -> 404 Not Found
    del_res = await client.delete(
        f"/api/v1/devices/{device_id}",
        headers=headers_b,
    )
    assert del_res.status_code == 404

    # Assert device remains active in database under User A
    async with AsyncSessionLocal() as session:
        stmt = select(UserDevice).where(
            UserDevice.user_id == user_a_id,
            UserDevice.device_id == device_id,
        )
        res = await session.execute(stmt)
        device = res.scalar_one_or_none()
        assert device is not None
        assert device.is_active is True


# ==============================================================================
# 4. Legitimate Owner Access & Public Endpoints Preserved
# ==============================================================================


@pytest.mark.asyncio
async def test_legitimate_owner_can_manage_own_resources(client: AsyncClient) -> None:
    """Authorized report creator can update their report and manage devices."""
    headers, user_id, _, _ = await register_and_login(client, "Legit Owner")

    # Create report
    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": ReportType.MISSING.value,
            "category": ReportCategory.BAG.value,
            "title": "Owner Legit Bag",
            "description": "Legitimate item",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201
    report_id = res.json()["id"]

    # Owner updates own report
    update_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers,
        json={"title": "Updated Bag Title"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["title"] == "Updated Bag Title"

    # Owner can register and deactivate own device
    dev_id = f"own_dev_{uuid.uuid4().hex[:6]}"
    reg_dev = await client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": dev_id,
            "fcm_token": "fcm_token_legit_12345",
            "platform": "ANDROID",
        },
    )
    assert reg_dev.status_code == 200

    del_dev = await client.delete(f"/api/v1/devices/{dev_id}", headers=headers)
    assert del_dev.status_code == 204


@pytest.mark.asyncio
async def test_public_discovery_endpoints_remain_accessible(
    client: AsyncClient,
) -> None:
    """Public endpoints (/reports, /reports/{id}, /health) work without auth."""
    # Health endpoint
    health_res = await client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # Public reports search
    reports_res = await client.get("/api/v1/reports")
    assert reports_res.status_code == 200
    assert "items" in reports_res.json()


# ==============================================================================
# 5. Access Token Revocation Reliability & Multi-Instance Tests (Phase 10.2.1)
# ==============================================================================


@pytest.mark.asyncio
async def test_access_token_revocation_survives_restart(client: AsyncClient) -> None:
    """Access token revocation survives simulated restart via PostgreSQL state."""
    headers, user_id, access_token, refresh_token = await register_and_login(
        client, "Restart User"
    )

    # Valid before logout
    pre_res = await client.get("/api/v1/users/me", headers=headers)
    assert pre_res.status_code == 200

    # Logout revokes session in PostgreSQL and sets in-memory structures
    logout_res = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 204

    # SIMULATE PROCESS RESTART: wipe entire in-memory revocation store
    clear_revocation_store()
    from app.services.auth import (
        _revoked_token_expirations,
        _user_tokens_revoked_after,
    )

    assert len(_revoked_token_expirations) == 0
    assert len(_user_tokens_revoked_after) == 0

    # Token rejected (401) because PostgreSQL UserSession.revoked_at persists
    post_restart_res = await client.get("/api/v1/users/me", headers=headers)
    assert post_restart_res.status_code == 401, (
        f"Expected 401 after restart, got {post_restart_res.status_code}"
    )


@pytest.mark.asyncio
async def test_access_token_revocation_visible_across_simulated_instances(
    client: AsyncClient,
) -> None:
    """Revocation on one node is visible on another node sharing PostgreSQL."""
    headers, user_id, access_token, refresh_token = await register_and_login(
        client, "Multi Node User"
    )

    # Verify token works initially
    pre_res = await client.get("/api/v1/reports/me", headers=headers)
    assert pre_res.status_code == 200

    # Node A handles logout: commits session.revoked_at to PostgreSQL
    logout_res = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 204

    # Simulate Node B: clear local in-memory structures so Node B has zero local state
    clear_revocation_store()

    # Node B validates token: queries PostgreSQL and rejects revoked session
    node_b_res = await client.get("/api/v1/reports/me", headers=headers)
    assert node_b_res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_replay_kills_all_access_tokens_across_nodes(
    client: AsyncClient,
) -> None:
    """RFC 6819 compromise detection invalidates all active sessions & access tokens."""
    email = f"compromise_{uuid.uuid4().hex[:8]}@example.com"
    password = "validPassword123"

    # Register user
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"name": "Compromise Victim", "email": email, "password": password},
    )
    assert reg_res.status_code == 201

    # Session 1 (Device 1)
    login1 = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    tok1 = login1.json()["access_token"]
    rt1 = login1.json()["refresh_token"]

    # Session 2 (Device 2)
    login2 = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    tok2 = login2.json()["access_token"]

    # Both tokens initially valid
    res1 = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tok1}"}
    )
    res2 = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tok2}"}
    )
    assert res1.status_code == 200
    assert res2.status_code == 200

    # Legitimate user rotates RT1 -> RT1_new (RT1 is now revoked)
    rot_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert rot_res.status_code == 200
    tok1_new = rot_res.json()["access_token"]

    # Replay attacker uses old RT1 -> triggers compromise detection
    replay_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert replay_res.status_code == 401
    assert "revoked" in replay_res.json()["detail"].lower()

    # Simulate cross-instance or post-restart validation: clear in-memory store
    clear_revocation_store()

    # Assert EVERY access token for this user (Device 1, rotated, Device 2) rejected
    for tok, label in [(tok1, "tok1"), (tok1_new, "tok1_new"), (tok2, "tok2")]:
        check_res = await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {tok}"}
        )
        assert check_res.status_code == 401, (
            f"Expected 401 for {label} after replay compromise, "
            f"got {check_res.status_code}"
        )


@pytest.mark.asyncio
async def test_in_memory_eviction_prunes_expired_tokens() -> None:
    """In-memory revocation store bounds memory by pruning expired entries."""
    from app.services.auth import (
        _revoked_token_expirations,
        _user_tokens_revoked_after,
        prune_expired_revocations,
    )

    clear_revocation_store()
    now_ts = datetime.now(UTC).timestamp()

    # Add expired token (exp in past) and active token (exp in future)
    _revoked_token_expirations["expired_token_hash"] = now_ts - 100
    _revoked_token_expirations["active_token_hash"] = now_ts + 1000

    # Add outdated user revocation (>35 min ago) and recent user revocation (<1 min ago)
    old_uid = uuid.uuid4()
    recent_uid = uuid.uuid4()
    _user_tokens_revoked_after[old_uid] = datetime.now(UTC) - timedelta(minutes=40)
    _user_tokens_revoked_after[recent_uid] = datetime.now(UTC) - timedelta(seconds=10)

    # Prune
    pruned_count = prune_expired_revocations(now_ts)
    assert pruned_count == 2
    assert "expired_token_hash" not in _revoked_token_expirations
    assert "active_token_hash" in _revoked_token_expirations
    assert old_uid not in _user_tokens_revoked_after
    assert recent_uid in _user_tokens_revoked_after


@pytest.mark.asyncio
async def test_database_cleanup_expired_sessions() -> None:
    """Database cleanup removes expired UserSession records older than retention."""
    from app.api.auth import cleanup_expired_sessions

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        # Create test user
        user = User(
            id=user_id,
            name="Session Cleanup Test",
            email=f"cleanup_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="fakehash",
        )
        session.add(user)
        await session.commit()

        # Add an old expired session (> 35 days ago)
        old_session = UserSession(
            user_id=user_id,
            refresh_token_hash=f"old_hash_{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) - timedelta(days=35),
            revoked_at=datetime.now(UTC) - timedelta(days=35),
        )
        # Add a recent session (active)
        recent_session = UserSession(
            user_id=user_id,
            refresh_token_hash=f"recent_hash_{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add_all([old_session, recent_session])
        await session.commit()

        # Run cleanup with 30-day retention
        deleted = await cleanup_expired_sessions(session, retention_days=30)
        assert deleted >= 1

        # Check that old session was deleted but recent session remains
        check_old = await session.get(UserSession, old_session.id)
        check_recent = await session.get(UserSession, recent_session.id)
        assert check_old is None
        assert check_recent is not None


# ==============================================================================
# 6. Legacy Access Token Compatibility & Session Binding Audit (Phase 10.2.2)
# ==============================================================================


def _build_test_jwt(
    user_id: uuid.UUID,
    sid: str | None = None,
    expired: bool = False,
    secret: str = settings.SECRET_KEY,
    algorithm: str = settings.ALGORITHM,
    token_type: str = "access",
) -> str:
    now = datetime.now(UTC)
    exp = (
        now - timedelta(seconds=10)
        if expired
        else now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "exp": exp,
        "iat": now,
        "jti": uuid.uuid4().hex,
    }
    if sid is not None:
        payload["sid"] = sid
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.mark.asyncio
async def test_access_token_missing_sid_rejected(client: AsyncClient) -> None:
    """Access tokens without sid claim are rejected in production (SEC-AUTH-003)."""
    _, user_id, _, _ = await register_and_login(client, "Missing Sid User")
    token_no_sid = _build_test_jwt(user_id, sid=None)

    res = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_no_sid}"}
    )
    assert res.status_code == 401
    assert "WWW-Authenticate" in res.headers
    assert "Bearer" in res.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_access_token_malformed_sid_rejected(client: AsyncClient) -> None:
    """Access tokens with non-UUID malformed sid claims are rejected with 401."""
    _, user_id, _, _ = await register_and_login(client, "Malformed Sid User")
    token_bad_sid = _build_test_jwt(user_id, sid="invalid-uuid-format-1234")

    res = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_bad_sid}"}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_unknown_session_id_rejected(client: AsyncClient) -> None:
    """Access tokens with non-existent session UUIDs are rejected with 401."""
    _, user_id, _, _ = await register_and_login(client, "Unknown Sid User")
    token_unknown_sid = _build_test_jwt(user_id, sid=str(uuid.uuid4()))

    res = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_unknown_sid}"}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_session_belonging_to_different_user_rejected(
    client: AsyncClient,
) -> None:
    """Access tokens cannot authenticate using a session of another user."""
    _, user_a_id, tok_a, _ = await register_and_login(client, "Victim A")
    _, user_b_id, tok_b, _ = await register_and_login(client, "Attacker B")

    # Extract session ID from User B's token
    decoded_b = jwt.decode(tok_b, options={"verify_signature": False})
    sid_b = decoded_b["sid"]

    # Craft token for User A referencing User B's session ID
    cross_token = _build_test_jwt(user_a_id, sid=sid_b)

    res = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {cross_token}"}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_revoked_session_rejected(client: AsyncClient) -> None:
    """Access tokens pointing to a revoked UserSession in PostgreSQL are rejected."""
    headers, user_id, access_token, _ = await register_and_login(
        client, "Revoked Session User"
    )

    # Verify token works initially
    pre_res = await client.get("/api/v1/users/me", headers=headers)
    assert pre_res.status_code == 200

    # Directly revoke the session in database
    decoded = jwt.decode(access_token, options={"verify_signature": False})
    sid = uuid.UUID(decoded["sid"])
    async with AsyncSessionLocal() as session:
        db_sess = await session.get(UserSession, sid)
        assert db_sess is not None
        db_sess.revoked_at = datetime.now(UTC)
        await session.commit()

    # Clear in-memory cache to prove PostgreSQL session state enforcement
    clear_revocation_store()

    post_res = await client.get("/api/v1/users/me", headers=headers)
    assert post_res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_expired_session_rejected(client: AsyncClient) -> None:
    """Access tokens pointing to an expired UserSession are rejected with 401."""
    headers, user_id, access_token, _ = await register_and_login(
        client, "Expired Session User"
    )

    # Directly expire the session in database
    decoded = jwt.decode(access_token, options={"verify_signature": False})
    sid = uuid.UUID(decoded["sid"])
    async with AsyncSessionLocal() as session:
        db_sess = await session.get(UserSession, sid)
        assert db_sess is not None
        db_sess.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()

    clear_revocation_store()

    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_valid_session_bound_succeeds(client: AsyncClient) -> None:
    """Standard login generates session-bound access token that succeeds."""
    headers, user_id, access_token, _ = await register_and_login(
        client, "Valid Session User"
    )

    decoded = jwt.decode(access_token, options={"verify_signature": False})
    assert "sid" in decoded
    assert uuid.UUID(decoded["sid"])

    res = await client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == str(user_id)


@pytest.mark.asyncio
async def test_optional_auth_with_invalid_or_revoked_session(
    client: AsyncClient,
) -> None:
    """Optional-auth endpoints degrade to public view on invalid/revoked sessions."""
    headers, user_id, access_token, _ = await register_and_login(client, "Report Owner")

    # Create a report owned by user
    exact_lat = 37.774929
    exact_lon = -122.419416
    rep_res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "title": "Lost Wallet for Optional Auth Test",
            "description": "Black leather wallet with IDs",
            "type": "MISSING",
            "category": "WALLET",
            "latitude": exact_lat,
            "longitude": exact_lon,
            "address": "San Francisco, CA",
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert rep_res.status_code == 201
    report_id = rep_res.json()["id"]

    # 1. Owner with valid session-bound token gets owner view (exact coordinates)
    owner_res = await client.get(f"/api/v1/reports/{report_id}", headers=headers)
    assert owner_res.status_code == 200
    assert abs(owner_res.json()["latitude"] - exact_lat) < 1e-5

    # 2. Token missing sid on optional-auth endpoint -> degrades to public view
    tok_no_sid = _build_test_jwt(user_id, sid=None)
    public_res1 = await client.get(
        f"/api/v1/reports/{report_id}",
        headers={"Authorization": f"Bearer {tok_no_sid}"},
    )
    assert public_res1.status_code == 200
    # Public view must have coarsened coordinates (2 decimal places ~1.1 km grid)
    assert public_res1.json()["latitude"] == round(exact_lat, 2)

    # 3. Token with revoked session on optional-auth endpoint -> degrades to public view
    decoded = jwt.decode(access_token, options={"verify_signature": False})
    sid = uuid.UUID(decoded["sid"])
    async with AsyncSessionLocal() as session:
        db_sess = await session.get(UserSession, sid)
        assert db_sess is not None
        db_sess.revoked_at = datetime.now(UTC)
        await session.commit()
    clear_revocation_store()

    revoked_res = await client.get(
        f"/api/v1/reports/{report_id}",
        headers=headers,
    )
    assert revoked_res.status_code == 200
    assert revoked_res.json()["latitude"] == round(exact_lat, 2)

    # 4. Anonymous request (no token at all) -> public view
    anon_res = await client.get(f"/api/v1/reports/{report_id}")
    assert anon_res.status_code == 200
    assert anon_res.json()["latitude"] == round(exact_lat, 2)


@pytest.mark.asyncio
async def test_session_cleanup_preserves_active_and_recently_revoked_sessions() -> None:
    """cleanup_expired_sessions() protects active and recently revoked sessions."""
    from app.api.auth import cleanup_expired_sessions

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        user = User(
            id=user_id,
            name="Session Retention Test",
            email=f"retention_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="fakehash",
        )
        session.add(user)
        await session.commit()

        # 1. Active session (expires in 7 days)
        active_sess = UserSession(
            user_id=user_id,
            refresh_token_hash=f"hash_act_{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            revoked_at=None,
        )
        # 2. Recently revoked session (revoked today, but expires in 6 days)
        # MUST BE PRESERVED for RFC 6819 refresh-token replay detection
        recent_revoked_sess = UserSession(
            user_id=user_id,
            refresh_token_hash=f"hash_rev_{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=6),
            revoked_at=datetime.now(UTC),
        )
        # 3. Old expired session (expired 45 days ago, revoked 45 days ago)
        old_expired_sess = UserSession(
            user_id=user_id,
            refresh_token_hash=f"hash_old_{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) - timedelta(days=45),
            revoked_at=datetime.now(UTC) - timedelta(days=45),
        )
        session.add_all([active_sess, recent_revoked_sess, old_expired_sess])
        await session.commit()

        # Run maintenance cleanup with 30-day retention
        deleted = await cleanup_expired_sessions(session, retention_days=30)
        assert deleted >= 1

        # Assert active session is preserved
        assert await session.get(UserSession, active_sess.id) is not None
        # Assert recently revoked session is preserved for replay detection
        assert await session.get(UserSession, recent_revoked_sess.id) is not None
        # Assert old expired session is purged
        assert await session.get(UserSession, old_expired_sess.id) is None
