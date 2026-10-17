import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import RecoveryRequestStatus, User
from app.schemas.recovery import (
    CreateRecoveryRequest,
    RecoveryRequestListResponse,
    RecoveryRequestResponse,
    UpdateRecoveryRequestStatus,
)
from app.services import recovery as recovery_service

recovery_router = APIRouter()


@recovery_router.post(
    "",
    response_model=RecoveryRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recovery_request(
    request_in: CreateRecoveryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Initiate a new recovery request on a report."""
    return await recovery_service.create_recovery_request(
        db, current_user.id, request_in
    )


@recovery_router.get("", response_model=RecoveryRequestListResponse)
async def list_recovery_requests(
    type: str | None = Query(
        None,
        description="Filter by type: 'received', 'sent', or 'all'",
        pattern="^(received|sent|all)$",
    ),
    status: RecoveryRequestStatus | None = Query(None, description="Filter by status"),
    report_id: uuid.UUID | None = Query(
        None, description="Filter by associated report"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """List recovery requests involving the authenticated user."""
    return await recovery_service.list_recovery_requests(
        db=db,
        user_id=current_user.id,
        filter_type=type,
        req_status=status,
        report_id=report_id,
        page=page,
        page_size=page_size,
    )


@recovery_router.get(
    "/{request_id}",
    response_model=RecoveryRequestResponse,
)
async def get_recovery_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Get recovery request details by ID."""
    recovery_req = await recovery_service.get_recovery_request_by_id(db, request_id)
    if not recovery_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recovery request not found",
        )

    if current_user.id not in (
        recovery_req.requester_id,
        recovery_req.recipient_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this recovery request",
        )

    return recovery_req


@recovery_router.patch(
    "/{request_id}",
    response_model=RecoveryRequestResponse,
)
async def update_recovery_request(
    request_id: uuid.UUID,
    update_in: UpdateRecoveryRequestStatus,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Update status or verification response of a recovery request."""
    recovery_req = await recovery_service.get_recovery_request_by_id(db, request_id)
    if not recovery_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recovery request not found",
        )

    return await recovery_service.update_recovery_request_status(
        db=db,
        recovery_req=recovery_req,
        current_user=current_user,
        update_in=update_in,
    )
