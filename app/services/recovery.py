import math
import uuid
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    RecoveryRequest,
    RecoveryRequestStatus,
    Report,
    ReportStatus,
    User,
)
from app.schemas.recovery import (
    CreateRecoveryRequest,
    RecoveryRequestListResponse,
    UpdateRecoveryRequestStatus,
)
from app.services.outbox import (
    build_recovery_request_created_event,
    build_recovery_request_updated_event,
    build_report_resolved_event,
    create_outbox_event,
)


async def get_recovery_request_by_id(
    db: AsyncSession, request_id: uuid.UUID
) -> RecoveryRequest | None:
    query = (
        select(RecoveryRequest)
        .options(
            selectinload(RecoveryRequest.report),
            selectinload(RecoveryRequest.requester),
            selectinload(RecoveryRequest.recipient),
        )
        .where(RecoveryRequest.id == request_id)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_recovery_request(
    db: AsyncSession, requester_id: uuid.UUID, request_in: CreateRecoveryRequest
) -> RecoveryRequest:
    report = await db.get(Report, request_in.report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    if report.created_by_user_id == requester_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot initiate recovery request on your own report",
        )

    if report.status != ReportStatus.ACTIVE:
        rep_status = report.status.value.lower()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot initiate recovery request on {rep_status} report",
        )

    # Check for existing pending or accepted request for this report by this user
    existing_query = select(RecoveryRequest).where(
        RecoveryRequest.report_id == request_in.report_id,
        RecoveryRequest.requester_id == requester_id,
        RecoveryRequest.status.in_(
            [RecoveryRequestStatus.PENDING, RecoveryRequestStatus.ACCEPTED]
        ),
    )
    res = await db.execute(existing_query)
    if res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A pending or accepted recovery request already exists for this report"
            ),
        )

    recovery_req = RecoveryRequest(
        report_id=request_in.report_id,
        requester_id=requester_id,
        recipient_id=report.created_by_user_id,
        status=RecoveryRequestStatus.PENDING,
        message=request_in.message,
    )
    db.add(recovery_req)
    await db.flush()

    # Enqueue recovery_request.created in the exact same database transaction
    event = build_recovery_request_created_event(recovery_req)
    await create_outbox_event(db, event)

    await db.commit()

    loaded = await get_recovery_request_by_id(db, recovery_req.id)
    assert loaded is not None
    return loaded


async def list_recovery_requests(
    db: AsyncSession,
    user_id: uuid.UUID,
    filter_type: str | None = None,
    req_status: RecoveryRequestStatus | None = None,
    report_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> RecoveryRequestListResponse:
    conditions = []

    if filter_type == "received":
        conditions.append(RecoveryRequest.recipient_id == user_id)
    elif filter_type == "sent":
        conditions.append(RecoveryRequest.requester_id == user_id)
    else:
        conditions.append(
            or_(
                RecoveryRequest.recipient_id == user_id,
                RecoveryRequest.requester_id == user_id,
            )
        )

    if req_status:
        conditions.append(RecoveryRequest.status == req_status)

    if report_id:
        conditions.append(RecoveryRequest.report_id == report_id)

    count_query = select(func.count(RecoveryRequest.id)).where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    query = (
        select(RecoveryRequest)
        .options(
            selectinload(RecoveryRequest.report),
            selectinload(RecoveryRequest.requester),
            selectinload(RecoveryRequest.recipient),
        )
        .where(*conditions)
        .order_by(desc(RecoveryRequest.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    return RecoveryRequestListResponse(
        items=cast(list[Any], items),
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def update_recovery_request_status(
    db: AsyncSession,
    recovery_req: RecoveryRequest,
    current_user: User,
    update_in: UpdateRecoveryRequestStatus,
) -> RecoveryRequest:
    if current_user.id not in (recovery_req.requester_id, recovery_req.recipient_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this recovery request",
        )

    current_status = recovery_req.status
    target_status = update_in.status

    if current_status == target_status:
        if update_in.verification_response is not None:
            recovery_req.verification_response = update_in.verification_response
            await db.commit()
            loaded = await get_recovery_request_by_id(db, recovery_req.id)
            assert loaded is not None
            return loaded
        return recovery_req

    terminal_statuses = {
        RecoveryRequestStatus.REJECTED,
        RecoveryRequestStatus.CANCELLED,
        RecoveryRequestStatus.COMPLETED,
    }
    if current_status in terminal_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Cannot transition from terminal status '{current_status.value}'",
        )

    if current_status == RecoveryRequestStatus.PENDING:
        if current_user.id == recovery_req.recipient_id:
            if target_status not in (
                RecoveryRequestStatus.ACCEPTED,
                RecoveryRequestStatus.REJECTED,
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"Recipient cannot transition request from PENDING to "
                        f"'{target_status.value}'"
                    ),
                )
        elif current_user.id == recovery_req.requester_id:
            if target_status != RecoveryRequestStatus.CANCELLED:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"Requester cannot transition request from PENDING to "
                        f"'{target_status.value}'"
                    ),
                )
    elif current_status == RecoveryRequestStatus.ACCEPTED:
        if target_status not in (
            RecoveryRequestStatus.COMPLETED,
            RecoveryRequestStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Cannot transition request from ACCEPTED to "
                    f"'{target_status.value}'"
                ),
            )

    recovery_req.status = target_status
    if update_in.verification_response is not None:
        recovery_req.verification_response = update_in.verification_response

    db.add(recovery_req)

    # 1. Enqueue recovery_request.updated event
    status_updated_event = build_recovery_request_updated_event(
        recovery_req=recovery_req,
        previous_status=current_status,
        new_status=target_status,
    )
    await create_outbox_event(db, status_updated_event)

    # 2. If completed, also resolve the underlying report and enqueue report.resolved
    if target_status == RecoveryRequestStatus.COMPLETED:
        report = await db.get(Report, recovery_req.report_id)
        if report and report.status == ReportStatus.ACTIVE:
            report.status = ReportStatus.RESOLVED
            db.add(report)
            report_resolved_event = build_report_resolved_event(
                report_id=report.id,
                resolution_reason="recovery_completed",
                associated_recovery_request_id=recovery_req.id,
            )
            await create_outbox_event(db, report_resolved_event)

    await db.commit()
    loaded = await get_recovery_request_by_id(db, recovery_req.id)
    assert loaded is not None
    return loaded
