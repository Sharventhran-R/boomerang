"""FastAPI endpoints for Boomerang Notification management (Phase 9.5).

Provides authenticated REST APIs for:
- In-app notification listing, filtering, unread counting, and read-status updates.
- User notification preferences inspection and partial updates.
- Specification-compatible device registration and deactivation aliases.

Enforces strict ownership authorization, IDOR protection, input validation,
and defensive redaction of internal tokens, secrets, and coordinates.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.devices import deactivate_device, register_device
from app.db.database import get_db
from app.db.models import NotificationType, User
from app.schemas.notification import (
    BulkActionResponse,
    DeviceRegisterRequest,
    DeviceResponse,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services import notification as notification_repo

notifications_router = APIRouter()


@notifications_router.get(
    "",
    response_model=NotificationListResponse,
    summary="List authenticated user notifications",
)
async def list_notifications(
    is_read: bool | None = Query(
        None, description="Optional filter by read status (true/false)"
    ),
    type: NotificationType | None = Query(
        None, description="Optional filter by notification domain type"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """Retrieve a paginated list of non-expired notifications for the user.

    Returns notifications in deterministic newest-first order with unread badge count.
    Never exposes internal delivery logs, tokens, or coordinates.
    """
    items, total, total_pages = await notification_repo.get_user_notifications(
        db=db,
        user_id=current_user.id,
        is_read=is_read,
        type=type,
        page=page,
        page_size=page_size,
    )
    unread_count = await notification_repo.get_unread_count(
        db=db, user_id=current_user.id
    )

    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        unread_count=unread_count,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@notifications_router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Get count of unread notifications",
)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    """Fast database count of unread notifications for the authenticated user."""
    count = await notification_repo.get_unread_count(db=db, user_id=current_user.id)
    return UnreadCountResponse(unread_count=count)


@notifications_router.patch(
    "/read-all",
    response_model=BulkActionResponse,
    summary="Mark all unread notifications as read",
)
@notifications_router.post(
    "/mark-all-read",
    response_model=BulkActionResponse,
    summary="Mark all unread notifications as read (alias)",
    include_in_schema=False,
)
async def mark_all_notifications_as_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkActionResponse:
    """Mark all unread notifications as read in bulk for the authenticated user."""
    count = await notification_repo.mark_all_as_read(db=db, user_id=current_user.id)
    await db.commit()
    return BulkActionResponse(count=count)


@notifications_router.get(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Retrieve user notification preferences",
)
async def get_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferenceResponse:
    """Retrieve user notification settings, initializing defaults if absent."""
    pref = await notification_repo.get_or_create_preferences(
        db=db, user_id=current_user.id
    )
    await db.commit()
    await db.refresh(pref)
    return NotificationPreferenceResponse.model_validate(pref)


@notifications_router.patch(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Update user notification preferences",
)
@notifications_router.put(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Update user notification preferences (alias)",
    include_in_schema=False,
)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferenceResponse:
    """Update notification settings for the authenticated user.

    Preserves omitted fields. Validates score thresholds (0.0 - 100.0)
    and quiet-hour time structures.
    """
    update_data = payload.model_dump(exclude_unset=True)
    try:
        pref = await notification_repo.update_preferences(
            db=db,
            user_id=current_user.id,
            **update_data,
        )
        await db.commit()
        await db.refresh(pref)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return NotificationPreferenceResponse.model_validate(pref)


# Device management specification-compatible aliases mounted under /notifications
@notifications_router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Register or rotate FCM device token (alias)",
)
async def register_device_alias(
    payload: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeviceResponse:
    """Register or refresh FCM device token under /notifications/devices."""
    return await register_device(
        payload=payload,
        db=db,
        current_user=current_user,
    )


@notifications_router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user device on logout (alias)",
)
async def deactivate_device_alias(
    device_id: str = Path(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Deactivate device token on logout under /notifications/devices/{device_id}."""
    return await deactivate_device(
        device_id=device_id,
        db=db,
        current_user=current_user,
    )


@notifications_router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark single notification as read",
)
async def mark_single_notification_as_read(
    notification_id: uuid.UUID = Path(
        ..., description="Unique notification identifier"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationResponse:
    """Mark an individual notification as read.

    Enforces ownership and returns 404 if not found or owned by another user.
    Idempotent on repeated calls.
    """
    notification = await notification_repo.mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    await db.commit()
    await db.refresh(notification)
    return NotificationResponse.model_validate(notification)
