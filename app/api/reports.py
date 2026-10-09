import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import ReportCategory, ReportStatus, ReportType, User
from app.schemas.geo import GeoSearchParams, get_geo_params
from app.schemas.report import (
    CreateReportRequest,
    ReportImageResponse,
    ReportListResponse,
    ReportResponse,
    UpdateReportRequest,
)
from app.services import report as report_service

reports_router = APIRouter()


@reports_router.post(
    "", response_model=ReportResponse, status_code=status.HTTP_201_CREATED
)
async def create_report(
    report_in: CreateReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Create a new report.
    """
    try:
        return await report_service.create_report(db, current_user.id, report_in)
    except Exception as e:
        print(f"ERROR IN CREATE REPORT: {e}")
        raise


@reports_router.get("", response_model=ReportListResponse)
async def list_reports(
    type: ReportType | None = None,
    category: ReportCategory | None = None,
    status: ReportStatus | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("newest", pattern="^(newest|oldest|distance)$"),
    geo: GeoSearchParams = Depends(get_geo_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List reports with pagination and filtering.
    """
    if sort == "distance" and (
        geo.latitude is None or geo.longitude is None or geo.radius_km is None
    ):
        raise HTTPException(
            status_code=422,
            detail="sort=distance requires latitude, longitude, and radius_km",
        )

    return await report_service.list_reports(
        db=db,
        type=type,
        category=category,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
        sort=sort,
        geo=geo,
    )


@reports_router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get a specific report by ID.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@reports_router.patch("/{report_id}", response_model=ReportResponse)
async def update_report(
    report_id: uuid.UUID,
    report_in: UpdateReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Update a report. Only the creator can do this.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to update this report"
        )

    # Validate status transitions
    if report_in.status and report_in.status != report.status:
        valid_transitions = {
            ReportStatus.ACTIVE: {ReportStatus.RESOLVED, ReportStatus.CANCELLED},
            ReportStatus.RESOLVED: set(),
            ReportStatus.CANCELLED: set(),
            ReportStatus.EXPIRED: set(),  # Expired is not manually set
        }
        if report_in.status not in valid_transitions.get(report.status, set()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Cannot transition from {report.status} to {report_in.status}",
            )

    return await report_service.update_report(db, report, report_in)


@reports_router.post(
    "/{report_id}/images",
    response_model=ReportImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    report_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Upload an image for a report. Only the creator can do this.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to upload images to this report"
        )

    try:
        return await report_service.upload_report_image(db, report, file)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        )


@reports_router.delete(
    "/{report_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_image(
    report_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete an image from a report. Only the creator can do this.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete images from this report"
        )

    # Find image
    image = next((img for img in report.images if img.id == image_id), None)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    await report_service.delete_report_image(db, image)
