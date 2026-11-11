"""FastAPI endpoints for Boomerang User Device management (Phase 9.5).

Provides authenticated device registration and deactivation endpoints for
push notification delivery tokens (Android, iOS, Web).

Enforces strict ownership authorization, token rotation safety, and complete
redaction of raw FCM registration tokens from responses and logs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import User, UserDevice
from app.schemas.notification import DeviceRegisterRequest, DeviceResponse
from app.services import notification as notification_repo

devices_router = APIRouter()


@devices_router.post(
    "/register",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Register or rotate FCM device token",
)
async def register_device(
    payload: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeviceResponse:
    """Register or rotate an FCM push notification token for the authenticated user.

    Idempotently updates existing device records or creates new ones.
    Prevents token contamination across users by deactivating any stale records
    sharing this token. Never returns or logs the raw FCM registration token.
    """
    device = await notification_repo.register_device(
        db=db,
        user_id=current_user.id,
        device_id=payload.device_id,
        fcm_token=payload.fcm_token,
        platform=payload.platform,
        device_model=payload.device_model,
        app_version=payload.app_version,
    )
    await db.commit()
    await db.refresh(device)
    return DeviceResponse.model_validate(device)


@devices_router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user device on logout",
)
async def deactivate_device(
    device_id: str = Path(
        ...,
        min_length=1,
        max_length=100,
        description="Client device identifier to deactivate",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Deactivate an active device token upon user logout or app unregistration.

    Enforces that only the device owner can deactivate it.
    Preserves historical notification deliveries intact.
    Does not leak device existence across users.
    """
    stmt = select(UserDevice).where(
        UserDevice.user_id == current_user.id,
        UserDevice.device_id == device_id,
    )
    res = await db.execute(stmt)
    device = res.scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    await notification_repo.deactivate_device(
        db=db,
        user_id=current_user.id,
        device_id=device_id,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
