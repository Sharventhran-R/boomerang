"""Comprehensive integration and security tests for Phase 9.5: Notification REST APIs.

Verifies:
1. In-App Notifications:
   - Pagination bounds, page counts, and page sizing.
   - Deterministic ordering (newest first).
   - Filtering by is_read status and notification type.
   - Exclusion of expired notifications.
   - Fast aggregate unread badge count.
   - Individual read-status updates with ownership enforcement and idempotency.
   - Bulk read-status updates with user isolation and idempotency.
   - Cross-user isolation (IDOR protection, no existence leakage).

2. User Devices:
   - Device registration across Android, iOS, and Web platforms.
   - Complete redaction of raw FCM tokens in responses and logs.
   - Idempotent re-registration and token rotation.
   - Multi-user device handoff / token reassignment safety.
   - Input validation (platform enum, token length, device_id).
   - Device deactivation on logout with idempotency and 204 No Content.
   - Device ownership protection (preventing cross-user deactivation).
   - Preservation of notification delivery history on deactivation.
   - Specification-compatible routing aliases.

3. Notification Preferences:
   - Automatic default preference generation on retrieval.
   - Partial updates preserving omitted fields.
   - Quiet-hours configuration with time objects.
   - Score threshold bounds validation (0.0 - 100.0).
   - Cross-user preference isolation.
   - Specification-compatible PUT alias.

4. Security & Hardening:
   - Unauthenticated rejection across all endpoints (401).
   - Malformed UUID path parameter handling (422).
   - Redaction of sensitive coordinates, secrets, and tokens from notification data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationPriority,
    NotificationType,
    UserDevice,
)
from app.services import notification as notification_repo


async def register_and_login(
    client: AsyncClient, name: str = "Test User"
) -> tuple[dict[str, str], uuid.UUID]:
    """Helper to create an authenticated user and return auth headers and UUID."""
    email = f"user_{uuid.uuid4()}@example.com"
    password = "password123"
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
    token = str(login_res.json()["access_token"])
    return {"Authorization": f"Bearer {token}"}, user_id


# ==============================================================================
# 1. NOTIFICATIONS LISTING, PAGINATION, AND ORDERING
# ==============================================================================


@pytest.mark.asyncio
async def test_notifications_list_pagination_and_ordering(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Pagination User")

    # Create 5 notifications with deterministic timestamps
    base_time = datetime.now(UTC)
    for i in range(5):
        notif = Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title=f"Notification {i}",
            body=f"Body for notification {i}",
            priority=NotificationPriority.DEFAULT,
            is_read=False,
            created_at=base_time + timedelta(minutes=i),
            expires_at=base_time + timedelta(days=90),
        )
        db.add(notif)
    await db.commit()

    # Page 1 with page_size=2
    res1 = await client.get("/api/v1/notifications?page=1&page_size=2", headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 5
    assert data1["total_pages"] == 3
    assert data1["page"] == 1
    assert data1["page_size"] == 2
    assert len(data1["items"]) == 2
    # Verify deterministic newest-first order
    assert data1["items"][0]["title"] == "Notification 4"
    assert data1["items"][1]["title"] == "Notification 3"
    assert data1["unread_count"] == 5

    # Page 2 with page_size=2
    res2 = await client.get("/api/v1/notifications?page=2&page_size=2", headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2["items"]) == 2
    assert data2["items"][0]["title"] == "Notification 2"
    assert data2["items"][1]["title"] == "Notification 1"

    # Page 3 with page_size=2
    res3 = await client.get("/api/v1/notifications?page=3&page_size=2", headers=headers)
    assert res3.status_code == 200
    data3 = res3.json()
    assert len(data3["items"]) == 1
    assert data3["items"][0]["title"] == "Notification 0"

    # Pagination bounds validation
    invalid_page = await client.get(
        "/api/v1/notifications?page=0&page_size=20", headers=headers
    )
    assert invalid_page.status_code == 422

    invalid_size = await client.get(
        "/api/v1/notifications?page=1&page_size=101", headers=headers
    )
    assert invalid_size.status_code == 422


@pytest.mark.asyncio
async def test_notifications_list_filtering(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Filter User")
    now = datetime.now(UTC)

    # 1 unread MATCH_DETECTED
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title="Match Alert",
            body="Match alert body",
            is_read=False,
            created_at=now,
            expires_at=now + timedelta(days=90),
        )
    )
    # 1 read RECOVERY_REQUEST_RECEIVED
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.RECOVERY_REQUEST_RECEIVED,
            title="Recovery Request",
            body="Recovery body",
            is_read=True,
            read_at=now,
            created_at=now + timedelta(minutes=1),
            expires_at=now + timedelta(days=90),
        )
    )
    # 1 expired notification (should never be returned)
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.REPORT_STATUS_CHANGED,
            title="Expired Notif",
            body="Expired body",
            is_read=False,
            created_at=now - timedelta(days=100),
            expires_at=now - timedelta(days=10),
        )
    )
    await db.commit()

    # Filter is_read=false
    res_unread = await client.get(
        "/api/v1/notifications?is_read=false", headers=headers
    )
    assert res_unread.status_code == 200
    data_unread = res_unread.json()
    assert data_unread["total"] == 1
    assert data_unread["items"][0]["title"] == "Match Alert"

    # Filter is_read=true
    res_read = await client.get("/api/v1/notifications?is_read=true", headers=headers)
    assert res_read.status_code == 200
    data_read = res_read.json()
    assert data_read["total"] == 1
    assert data_read["items"][0]["title"] == "Recovery Request"

    # Filter by type
    res_type = await client.get(
        "/api/v1/notifications?type=MATCH_DETECTED", headers=headers
    )
    assert res_type.status_code == 200
    data_type = res_type.json()
    assert data_type["total"] == 1
    assert data_type["items"][0]["title"] == "Match Alert"


# ==============================================================================
# 2. UNREAD COUNT AND READ-STATUS OPERATIONS
# ==============================================================================


@pytest.mark.asyncio
async def test_unread_count_endpoint(client: AsyncClient, db: AsyncSession) -> None:
    headers, user_id = await register_and_login(client, "Count User")
    now = datetime.now(UTC)

    # Initial count should be 0
    res0 = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert res0.status_code == 200
    assert res0.json() == {"unread_count": 0}

    # Add 2 unread, 1 read, 1 expired unread
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title="N1",
            body="B1",
            is_read=False,
            expires_at=now + timedelta(days=30),
        )
    )
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title="N2",
            body="B2",
            is_read=False,
            expires_at=now + timedelta(days=30),
        )
    )
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title="N3",
            body="B3",
            is_read=True,
            expires_at=now + timedelta(days=30),
        )
    )
    db.add(
        Notification(
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title="Expired",
            body="B_exp",
            is_read=False,
            expires_at=now - timedelta(days=1),
        )
    )
    await db.commit()

    res = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"unread_count": 2}


@pytest.mark.asyncio
async def test_mark_individual_notification_as_read(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Single Read User")

    notif = await notification_repo.create_notification(
        db=db,
        user_id=user_id,
        type=NotificationType.MATCH_DETECTED,
        title="Alert to Read",
        body="Alert body",
    )
    await db.commit()
    assert not notif.is_read

    # Mark as read
    res = await client.patch(f"/api/v1/notifications/{notif.id}/read", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(notif.id)
    assert data["is_read"] is True
    assert data["read_at"] is not None

    # Verify idempotency by calling again
    res_repeat = await client.patch(
        f"/api/v1/notifications/{notif.id}/read", headers=headers
    )
    assert res_repeat.status_code == 200
    assert res_repeat.json()["is_read"] is True

    # Verify unread count is now 0
    res_count = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert res_count.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_mark_all_notifications_as_read(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Bulk Read User")

    # Create 3 unread notifications
    for i in range(3):
        await notification_repo.create_notification(
            db=db,
            user_id=user_id,
            type=NotificationType.MATCH_DETECTED,
            title=f"Bulk {i}",
            body="Body",
        )
    await db.commit()

    # Bulk read via PATCH /read-all
    res = await client.patch("/api/v1/notifications/read-all", headers=headers)
    assert res.status_code == 200
    assert res.json()["count"] == 3

    # Repeating should return count=0 (idempotent)
    res_repeat = await client.patch("/api/v1/notifications/read-all", headers=headers)
    assert res_repeat.status_code == 200
    assert res_repeat.json()["count"] == 0

    # Also test specification alias POST /mark-all-read
    await notification_repo.create_notification(
        db=db,
        user_id=user_id,
        type=NotificationType.MATCH_DETECTED,
        title="Alias Test",
        body="Body",
    )
    await db.commit()

    res_alias = await client.post(
        "/api/v1/notifications/mark-all-read", headers=headers
    )
    assert res_alias.status_code == 200
    assert res_alias.json()["count"] == 1


@pytest.mark.asyncio
async def test_notification_cross_user_isolation(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers_a, user_a_id = await register_and_login(client, "User A")
    headers_b, user_b_id = await register_and_login(client, "User B")

    notif_b = await notification_repo.create_notification(
        db=db,
        user_id=user_b_id,
        type=NotificationType.MATCH_DETECTED,
        title="User B Alert",
        body="Private to B",
    )
    await db.commit()

    # User A tries to mark User B's notification as read
    res_cross = await client.patch(
        f"/api/v1/notifications/{notif_b.id}/read", headers=headers_a
    )
    # Must return 404 (preventing record existence leakage)
    assert res_cross.status_code == 404
    assert res_cross.json()["detail"] == "Notification not found"

    # Verify User B's notification remained unread
    stmt = select(Notification).where(Notification.id == notif_b.id)
    fresh_b = (await db.execute(stmt)).scalar_one()
    assert fresh_b.is_read is False

    # User A bulk-read must not affect User B
    await client.patch("/api/v1/notifications/read-all", headers=headers_a)
    fresh_b2 = (await db.execute(stmt)).scalar_one()
    assert fresh_b2.is_read is False
    await db.rollback()

    # User A listing must not see User B's notification
    list_a = await client.get("/api/v1/notifications", headers=headers_a)
    assert list_a.json()["total"] == 0


# ==============================================================================
# 3. DEVICE REGISTRATION, ROTATION, AND DEACTIVATION
# ==============================================================================


@pytest.mark.asyncio
async def test_device_registration_across_platforms(
    client: AsyncClient,
) -> None:
    headers, _ = await register_and_login(client, "Device User")

    # Android Registration
    android_payload = {
        "device_id": "pixel-9-pro-001",
        "fcm_token": "fcm_token_android_synthetic_abcdef123456",
        "platform": "ANDROID",
        "device_model": "Pixel 9 Pro",
        "app_version": "1.0.0",
    }
    res_android = await client.post(
        "/api/v1/devices/register", json=android_payload, headers=headers
    )
    assert res_android.status_code == 200
    data_android = res_android.json()
    assert data_android["device_id"] == "pixel-9-pro-001"
    assert data_android["platform"] == "ANDROID"
    assert data_android["is_active"] is True
    # CRITICAL: Token must never be returned in response
    assert "fcm_token" not in data_android

    # iOS Registration
    ios_payload = {
        "device_id": "iphone-16-pro-001",
        "fcm_token": "fcm_token_ios_synthetic_1234567890abcdef",
        "platform": "IOS",
        "device_model": "iPhone 16 Pro",
        "app_version": "1.0.0",
    }
    res_ios = await client.post(
        "/api/v1/devices/register", json=ios_payload, headers=headers
    )
    assert res_ios.status_code == 200
    assert res_ios.json()["platform"] == "IOS"

    # Web Registration via specification-compatible alias
    web_payload = {
        "device_id": "chrome-windows-001",
        "fcm_token": "fcm_token_web_synthetic_0987654321abcdef",
        "platform": "WEB",
        "device_model": "Chrome 129 / Windows 11",
        "app_version": "1.0.0",
    }
    res_web = await client.post(
        "/api/v1/notifications/devices", json=web_payload, headers=headers
    )
    assert res_web.status_code == 200
    assert res_web.json()["platform"] == "WEB"


@pytest.mark.asyncio
async def test_device_registration_validation(
    client: AsyncClient,
) -> None:
    headers, _ = await register_and_login(client, "Validation User")

    # Invalid platform
    res_platform = await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "dev-val-1",
            "fcm_token": "valid_token_1234567890",
            "platform": "WINDOWS",
        },
        headers=headers,
    )
    assert res_platform.status_code == 422

    # Token too short (< 10 chars)
    res_short = await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "dev-val-2",
            "fcm_token": "short",
            "platform": "ANDROID",
        },
        headers=headers,
    )
    assert res_short.status_code == 422

    # Missing device_id
    res_missing = await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "",
            "fcm_token": "valid_token_1234567890",
            "platform": "ANDROID",
        },
        headers=headers,
    )
    assert res_missing.status_code == 422


@pytest.mark.asyncio
async def test_device_token_rotation_and_idempotency(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Rotation User")

    # Initial registration
    payload = {
        "device_id": "device-rotate-123",
        "fcm_token": "token_initial_1234567890",
        "platform": "ANDROID",
        "device_model": "Galaxy S24",
        "app_version": "1.0.0",
    }
    res1 = await client.post("/api/v1/devices/register", json=payload, headers=headers)
    assert res1.status_code == 200
    dev_id = res1.json()["id"]

    # Re-register same device with rotated token and new app version
    payload["fcm_token"] = "token_rotated_9876543210"
    payload["app_version"] = "1.1.0"
    res2 = await client.post("/api/v1/devices/register", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["id"] == dev_id
    assert res2.json()["app_version"] == "1.1.0"

    # Verify in DB that fcm_token was actually rotated
    stmt = select(UserDevice).where(
        UserDevice.user_id == user_id,
        UserDevice.device_id == "device-rotate-123",
    )
    device = (await db.execute(stmt)).scalar_one()
    assert device.fcm_token == "token_rotated_9876543210"
    await db.rollback()


@pytest.mark.asyncio
async def test_device_token_multi_user_handoff(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers_a, user_a_id = await register_and_login(client, "Device Owner A")
    headers_b, user_b_id = await register_and_login(client, "Device Owner B")

    shared_token = "synthetic_shared_token_handover_12345"

    # User A registers device with shared_token
    await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "device-a",
            "fcm_token": shared_token,
            "platform": "ANDROID",
        },
        headers=headers_a,
    )

    # User B logs in on same physical device and registers with same token
    await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "device-b",
            "fcm_token": shared_token,
            "platform": "ANDROID",
        },
        headers=headers_b,
    )

    # User A's device record must now be deactivated to prevent token leak
    stmt_a = select(UserDevice).where(
        UserDevice.user_id == user_a_id, UserDevice.device_id == "device-a"
    )
    dev_a = (await db.execute(stmt_a)).scalar_one()
    assert dev_a.is_active is False

    # User B's device record must be active
    stmt_b = select(UserDevice).where(
        UserDevice.user_id == user_b_id, UserDevice.device_id == "device-b"
    )
    dev_b = (await db.execute(stmt_b)).scalar_one()
    assert dev_b.is_active is True
    await db.rollback()


@pytest.mark.asyncio
async def test_device_deactivation_and_history_preservation(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Deactivate User")

    # Register device
    reg_res = await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "device-to-deactivate",
            "fcm_token": "token_for_deactivation_test_123",
            "platform": "ANDROID",
        },
        headers=headers,
    )
    assert reg_res.status_code == 200
    user_device_id = uuid.UUID(reg_res.json()["id"])

    # Create notification and delivery record pointing to this device
    notif = await notification_repo.create_notification(
        db=db,
        user_id=user_id,
        type=NotificationType.MATCH_DETECTED,
        title="Delivery Test",
        body="Delivery Body",
    )
    delivery = NotificationDelivery(
        notification_id=notif.id,
        user_device_id=user_device_id,
        status=DeliveryStatus.SENT,
        retry_count=0,
    )
    db.add(delivery)
    await db.commit()

    # Deactivate device
    del_res = await client.delete(
        "/api/v1/devices/device-to-deactivate", headers=headers
    )
    assert del_res.status_code == 204

    # Verify device is deactivated in DB
    dev_stmt = select(UserDevice).where(UserDevice.id == user_device_id)
    dev_record = (await db.execute(dev_stmt)).scalar_one()
    assert dev_record.is_active is False

    # Verify delivery record is preserved intact!
    deliv_stmt = select(NotificationDelivery).where(
        NotificationDelivery.user_device_id == user_device_id
    )
    preserved_deliv = (await db.execute(deliv_stmt)).scalar_one_or_none()
    assert preserved_deliv is not None
    assert preserved_deliv.status == DeliveryStatus.SENT
    await db.rollback()

    # Repeated deactivation is idempotent (returns 204)
    del_repeat = await client.delete(
        "/api/v1/devices/device-to-deactivate", headers=headers
    )
    assert del_repeat.status_code == 204


@pytest.mark.asyncio
async def test_device_deactivation_cross_user_isolation(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers_a, _ = await register_and_login(client, "Owner A")
    headers_b, user_b_id = await register_and_login(client, "Owner B")

    # User B registers a device
    await client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "b-secret-device",
            "fcm_token": "b_token_synthetic_12345",
            "platform": "IOS",
        },
        headers=headers_b,
    )

    # User A tries to deactivate User B's device
    cross_del = await client.delete(
        "/api/v1/devices/b-secret-device", headers=headers_a
    )
    assert cross_del.status_code == 404
    assert cross_del.json()["detail"] == "Device not found"

    # Verify User B's device remains active
    stmt = select(UserDevice).where(
        UserDevice.user_id == user_b_id,
        UserDevice.device_id == "b-secret-device",
    )
    device = (await db.execute(stmt)).scalar_one()
    assert device.is_active is True
    await db.rollback()


# ==============================================================================
# 4. NOTIFICATION PREFERENCES
# ==============================================================================


@pytest.mark.asyncio
async def test_notification_preferences_defaults_and_partial_update(
    client: AsyncClient,
) -> None:
    headers, _ = await register_and_login(client, "Pref User")

    # 1. Retrieve default preferences (initialized automatically)
    get_res = await client.get("/api/v1/notifications/preferences", headers=headers)
    assert get_res.status_code == 200
    pref = get_res.json()
    assert pref["push_enabled"] is True
    assert pref["in_app_enabled"] is True
    assert pref["match_alerts_enabled"] is True
    assert pref["match_min_score"] == 75.0
    assert pref["match_high_priority_only"] is False
    assert pref["quiet_hours_enabled"] is False
    assert pref["quiet_hours_start"] is None
    assert pref["quiet_hours_end"] is None

    # 2. Partial update via PATCH
    update_payload = {
        "match_alerts_enabled": False,
        "match_min_score": 85.0,
        "quiet_hours_enabled": True,
        "quiet_hours_start": "22:00:00",
        "quiet_hours_end": "07:00:00",
    }
    patch_res = await client.patch(
        "/api/v1/notifications/preferences",
        json=update_payload,
        headers=headers,
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["match_alerts_enabled"] is False
    assert updated["match_min_score"] == 85.0
    assert updated["quiet_hours_enabled"] is True
    assert updated["quiet_hours_start"] == "22:00:00"
    assert updated["quiet_hours_end"] == "07:00:00"
    # Preserved omitted fields
    assert updated["push_enabled"] is True
    assert updated["in_app_enabled"] is True

    # 3. Test specification PUT alias
    put_res = await client.put(
        "/api/v1/notifications/preferences",
        json={"push_enabled": False},
        headers=headers,
    )
    assert put_res.status_code == 200
    assert put_res.json()["push_enabled"] is False
    assert put_res.json()["match_min_score"] == 85.0


@pytest.mark.asyncio
async def test_notification_preferences_validation_and_isolation(
    client: AsyncClient,
) -> None:
    headers_a, _ = await register_and_login(client, "Pref A")
    headers_b, _ = await register_and_login(client, "Pref B")

    # Invalid score thresholds (< 0.0 or > 100.0)
    low_res = await client.patch(
        "/api/v1/notifications/preferences",
        json={"match_min_score": -5.0},
        headers=headers_a,
    )
    assert low_res.status_code == 422

    high_res = await client.patch(
        "/api/v1/notifications/preferences",
        json={"match_min_score": 105.0},
        headers=headers_a,
    )
    assert high_res.status_code == 422

    # Cross-user preference isolation
    await client.patch(
        "/api/v1/notifications/preferences",
        json={"match_min_score": 90.0},
        headers=headers_a,
    )
    pref_b = await client.get("/api/v1/notifications/preferences", headers=headers_b)
    # User B must still have default 75.0
    assert pref_b.json()["match_min_score"] == 75.0


# ==============================================================================
# 5. SECURITY, UNTHENTICATED REJECTION, AND DATA SANITIZATION
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client: AsyncClient) -> None:
    dummy_uuid = uuid.uuid4()

    endpoints = [
        ("GET", "/api/v1/notifications"),
        ("GET", "/api/v1/notifications/unread-count"),
        ("PATCH", f"/api/v1/notifications/{dummy_uuid}/read"),
        ("PATCH", "/api/v1/notifications/read-all"),
        ("GET", "/api/v1/notifications/preferences"),
        ("PATCH", "/api/v1/notifications/preferences"),
        ("POST", "/api/v1/devices/register"),
        ("DELETE", "/api/v1/devices/dummy-device"),
    ]

    for method, path in endpoints:
        if method == "GET":
            res = await client.get(path)
        elif method == "POST":
            res = await client.post(path, json={})
        elif method == "PATCH":
            res = await client.patch(path, json={})
        elif method == "DELETE":
            res = await client.delete(path)
        else:
            continue
        assert res.status_code == 401, f"{method} {path} did not return 401"


@pytest.mark.asyncio
async def test_invalid_uuid_handling(client: AsyncClient) -> None:
    headers, _ = await register_and_login(client, "UUID User")
    res = await client.patch(
        "/api/v1/notifications/not-a-valid-uuid/read", headers=headers
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_sensitive_data_sanitization_in_notifications(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, user_id = await register_and_login(client, "Sanitize User")

    # Notification created with malicious/accidental sensitive metadata
    raw_data = {
        "match_id": str(uuid.uuid4()),
        "latitude": 37.7749,
        "longitude": -122.4194,
        "fcm_token": "sensitive_fcm_token_leak",
        "verification_secret": "claim_code_9999",
        "safe_key": "safe_value",
    }
    await notification_repo.create_notification(
        db=db,
        user_id=user_id,
        type=NotificationType.MATCH_DETECTED,
        title="Sanitize Test",
        body="Sanitize Body",
        data=raw_data,
    )
    await db.commit()

    # Retrieve through GET
    res = await client.get("/api/v1/notifications", headers=headers)
    assert res.status_code == 200
    item = res.json()["items"][0]
    data = item["data"]

    # Verify sensitive keys were completely redacted
    assert "safe_key" in data
    assert data["safe_key"] == "safe_value"
    assert "latitude" not in data
    assert "longitude" not in data
    assert "fcm_token" not in data
    assert "verification_secret" not in data
