import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi import (
    status as http_status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.database import get_db
from app.db.models import ReportCategory, ReportStatus, ReportType, User
from app.schemas.geo import GeoSearchParams, get_geo_params
from app.schemas.quota import QuotaStatusResponse
from app.schemas.report import (
    CreateReportRequest,
    ReportImageResponse,
    ReportListResponse,
    ReportResponse,
    UpdateReportRequest,
)
from app.services import quota as quota_service
from app.services import report as report_service
from app.services import storage as storage_service
from app.services.geo import coarsen_coordinate
from app.services.rate_limiter import (
    check_image_upload_rate_limits,
    check_reports_discovery_rate_limits,
)

reports_router = APIRouter()


@reports_router.post(
    "", response_model=ReportResponse, status_code=http_status.HTTP_201_CREATED
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


@reports_router.get("/me", response_model=ReportListResponse)
async def list_my_reports(
    type: ReportType | None = None,
    category: ReportCategory | None = None,
    status: ReportStatus | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List reports owned by the authenticated user across all locations and statuses.
    """
    return await report_service.list_reports(
        db=db,
        user_id=current_user.id,
        viewer_user_id=current_user.id,
        type=type,
        category=category,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
        sort=sort,
        geo=None,
    )


@reports_router.get("/quota-status", response_model=QuotaStatusResponse)
async def get_report_quota_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Returns authenticated user's report quotas and remaining allowances."""
    return await quota_service.get_user_quota_status(db, current_user.id)


@reports_router.get("", response_model=ReportListResponse)
async def list_reports(
    request: Request,
    response: Response,
    type: ReportType | None = None,
    category: ReportCategory | None = None,
    status: ReportStatus | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("newest", pattern="^(newest|oldest|distance)$"),
    mine: bool = Query(False),
    geo: GeoSearchParams = Depends(get_geo_params),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> Any:
    """
    List reports with pagination and filtering.
    """
    viewer_id = current_user.id if current_user else None
    await check_reports_discovery_rate_limits(
        request=request,
        user_id=viewer_id,
        response=response,
    )

    if mine:
        if current_user is None:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        has_geo = (
            geo.latitude is not None
            and geo.longitude is not None
            and geo.radius_km is not None
        )
        if sort == "distance" and not has_geo:
            raise HTTPException(
                status_code=422,
                detail="sort=distance requires latitude, longitude, and radius_km",
            )
        return await report_service.list_reports(
            db=db,
            user_id=current_user.id,
            viewer_user_id=current_user.id,
            type=type,
            category=category,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
            sort=sort,
            geo=geo if has_geo else None,
        )

    if sort == "distance" and (
        geo.latitude is None or geo.longitude is None or geo.radius_km is None
    ):
        raise HTTPException(
            status_code=422,
            detail="sort=distance requires latitude, longitude, and radius_km",
        )

    viewer_id = current_user.id if current_user else None
    return await report_service.list_reports(
        db=db,
        viewer_user_id=viewer_id,
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
    current_user: User | None = Depends(get_optional_current_user),
) -> Any:
    """
    Get a specific report by ID.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user is None or report.created_by_user_id != current_user.id:
        coarsened_lat, coarsened_lon = coarsen_coordinate(
            getattr(report, "latitude", 0.0), getattr(report, "longitude", 0.0)
        )
        report.latitude = coarsened_lat  # type: ignore[attr-defined]
        report.longitude = coarsened_lon  # type: ignore[attr-defined]
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
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Cannot transition from {report.status} to {report_in.status}",
            )

    return await report_service.update_report(db, report, report_in)


@reports_router.post(
    "/{report_id}/images",
    response_model=ReportImageResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def upload_image(
    report_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Upload an image for a report.

    Enforces ownership authorization, rate limiting, file signature validation,
    dimension limits, decompression bomb defenses, and EXIF/GPS stripping.
    """
    await check_image_upload_rate_limits(
        request=request, user_id=current_user.id, response=response
    )

    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to upload images to this report"
        )

    return await report_service.upload_report_image(db, report, file)


@reports_router.get(
    "/{report_id}/images/{image_id}",
    response_class=Response,
)
async def get_report_image_content(
    report_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> Response:
    """Retrieves sanitized image content.

    Public discovery allows viewing active report images.
    Non-active (terminal/cancelled) reports require creator authorization.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Authorization: Non-active reports require creator ownership
    if report.status != ReportStatus.ACTIVE:
        if current_user is None or report.created_by_user_id != current_user.id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access images for this report",
            )

    image = next((img for img in report.images if img.id == image_id), None)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    body_bytes, content_type = await storage_service.get_image_from_s3(image.object_key)

    return Response(
        content=body_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@reports_router.delete(
    "/{report_id}/images/{image_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
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
