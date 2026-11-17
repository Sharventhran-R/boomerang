import logging
import uuid
from typing import Any, cast

from fastapi import HTTPException, UploadFile, status
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import asc, desc, func, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import Report, ReportCategory, ReportImage, ReportStatus, ReportType
from app.schemas.geo import GeoSearchParams
from app.schemas.report import CreateReportRequest, UpdateReportRequest
from app.services.geo import (
    DISTANCE_BUCKET_SIZE_METERS,
    coarsen_coordinate,
    coarsen_distance,
    snap_search_origin,
)
from app.services.outbox import (
    build_report_created_event,
    build_report_resolved_event,
    build_report_updated_event,
    create_outbox_event,
)
from app.services.quota import check_and_consume_report_quota
from app.services.storage import delete_image_from_s3, upload_image_to_s3


async def create_report(
    db: AsyncSession, user_id: uuid.UUID, report_in: CreateReportRequest
) -> Report:
    await check_and_consume_report_quota(
        db, user_id=user_id, report_type=report_in.type
    )

    report = Report(
        created_by_user_id=user_id,
        type=report_in.type,
        title=report_in.title,
        description=report_in.description,
        category=report_in.category,
        location=WKTElement(
            f"POINT({report_in.longitude} {report_in.latitude})", srid=4326
        ),
        event_time=report_in.event_time,
        reward_amount=report_in.reward_amount,
        status=ReportStatus.ACTIVE,
    )
    db.add(report)
    await db.flush()

    # Enqueue report.created in the exact same database transaction
    event = build_report_created_event(
        report=report,
        latitude=report_in.latitude,
        longitude=report_in.longitude,
    )
    await create_outbox_event(db, event)

    await db.commit()
    # Explicitly query it back to have coordinates and relationships
    report_returned = await get_report_by_id(db, report.id)
    assert report_returned is not None
    return report_returned


async def get_report_by_id(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
    query = (
        select(
            Report,
            func.ST_Y(Report.location.cast(Geometry)).label("latitude"),
            func.ST_X(Report.location.cast(Geometry)).label("longitude"),
        )
        .options(selectinload(Report.images))
        .where(Report.id == report_id)
    )
    result = await db.execute(query)
    row = result.first()
    if not row:
        return None
    report, lat, lon = row
    report.latitude = lat
    report.longitude = lon
    return cast(Report, report)


async def update_report(
    db: AsyncSession,
    report: Report,  # Must be loaded with coordinates if we return it directly
    report_in: UpdateReportRequest,
) -> Report:
    updated_fields: list[str] = []

    if report_in.title is not None and report_in.title != report.title:
        report.title = report_in.title
        updated_fields.append("title")

    if (
        report_in.description is not None
        and report_in.description != report.description
    ):
        report.description = report_in.description
        updated_fields.append("description")

    if report_in.category is not None and report_in.category != report.category:
        report.category = report_in.category
        updated_fields.append("category")

    if report_in.event_time is not None and report_in.event_time != report.event_time:
        report.event_time = report_in.event_time
        updated_fields.append("event_time")

    if (
        report_in.reward_amount is not None
        and report_in.reward_amount != report.reward_amount
    ):
        report.reward_amount = report_in.reward_amount
        updated_fields.append("reward_amount")

    status_changed_to_resolved = False
    if report_in.status is not None and report_in.status != report.status:
        report.status = report_in.status
        if report_in.status == ReportStatus.RESOLVED:
            status_changed_to_resolved = True
        else:
            updated_fields.append("status")

    new_lat: float | None = None
    new_lon: float | None = None
    old_lat = getattr(report, "latitude", None)
    old_lon = getattr(report, "longitude", None)

    if report_in.latitude is not None and report_in.longitude is not None:
        if report_in.latitude != old_lat or report_in.longitude != old_lon:
            report.location = WKTElement(
                f"POINT({report_in.longitude} {report_in.latitude})", srid=4326
            )
            report.latitude = report_in.latitude  # type: ignore
            report.longitude = report_in.longitude  # type: ignore
            updated_fields.extend(["latitude", "longitude"])
            new_lat = report_in.latitude
            new_lon = report_in.longitude
    elif report_in.latitude is not None or report_in.longitude is not None:
        lat = (
            report_in.latitude
            if report_in.latitude is not None
            else getattr(report, "latitude", 0)
        )
        lon = (
            report_in.longitude
            if report_in.longitude is not None
            else getattr(report, "longitude", 0)
        )
        if lat != old_lat or lon != old_lon:
            report.location = WKTElement(f"POINT({lon} {lat})", srid=4326)
            report.latitude = lat  # type: ignore
            report.longitude = lon  # type: ignore
            updated_fields.extend(["latitude", "longitude"])
            new_lat = lat
            new_lon = lon

    db.add(report)

    # 1. Emit report.updated only for actual attribute changes
    if updated_fields:
        update_event = build_report_updated_event(
            report_id=report.id,
            updated_fields=updated_fields,
            title=report.title,
            description=report.description,
            category=report.category,
            latitude=new_lat,
            longitude=new_lon,
            event_time=report.event_time,
            reward_amount=report.reward_amount,
            status=report.status,
        )
        await create_outbox_event(db, update_event)

    # 2. Emit report.resolved if status transitioned to RESOLVED
    if status_changed_to_resolved:
        resolved_event = build_report_resolved_event(
            report_id=report.id,
            resolution_reason="user_resolved",
        )
        await create_outbox_event(db, resolved_event)

    await db.commit()
    report_returned = await get_report_by_id(db, report.id)
    assert report_returned is not None
    return report_returned


async def list_reports(
    db: AsyncSession,
    type: ReportType | None = None,
    category: ReportCategory | None = None,
    status: ReportStatus | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "newest",
    geo: GeoSearchParams | None = None,
    user_id: uuid.UUID | None = None,
    viewer_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    count_query = select(func.count(Report.id))

    filters = []
    if user_id is not None:
        filters.append(Report.created_by_user_id == user_id)
    if type:
        filters.append(Report.type == type)
    if category:
        filters.append(Report.category == category)
    if status:
        filters.append(Report.status == status)
    if search:
        search_term = f"%{search}%"
        filters.append(
            or_(
                Report.title.ilike(search_term),
                Report.description.ilike(search_term),
            )
        )

    is_pure_owner_query = (
        user_id is not None and viewer_user_id is not None and user_id == viewer_user_id
    )

    distance_col = null().label("distance")
    if (
        geo
        and geo.latitude is not None
        and geo.longitude is not None
        and geo.radius_km is not None
    ):
        if is_pure_owner_query:
            query_lat, query_lon = float(geo.latitude), float(geo.longitude)
        else:
            # Stage C: Snap search origin to 2-decimal grid (~1.1 km) for public
            # discovery queries. Converts continuous probe movement into discrete
            # grid steps, neutralizing sub-meter bisection (ST_DWithin oracle).
            query_lat, query_lon = snap_search_origin(geo.latitude, geo.longitude)

        radius_meters = float(geo.radius_km) * 1000.0
        search_point = WKTElement(f"POINT({query_lon} {query_lat})", srid=4326)
        filters.append(func.ST_DWithin(Report.location, search_point, radius_meters))
        distance_col = func.ST_Distance(Report.location, search_point).label("distance")

    query = select(
        Report,
        func.ST_Y(Report.location.cast(Geometry)).label("latitude"),
        func.ST_X(Report.location.cast(Geometry)).label("longitude"),
        distance_col,
    ).options(selectinload(Report.images))

    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    if sort == "distance":
        if is_pure_owner_query:
            query = query.order_by(
                asc(distance_col), desc(Report.created_at), asc(Report.id)
            )
        else:
            # Stage B: Bucketed distance sorting for public discovery.
            # Groups discovery results into 500-meter coarse distance bands.
            # Ties within each band are broken strictly by creation time (newest first)
            # and unique ID, eliminating perpendicular-bisector ordering attacks.
            distance_bucket = func.floor(distance_col / DISTANCE_BUCKET_SIZE_METERS)
            query = query.order_by(
                asc(distance_bucket), desc(Report.created_at), asc(Report.id)
            )
    elif sort == "newest":
        query = query.order_by(desc(Report.created_at), asc(Report.id))
    else:
        query = query.order_by(asc(Report.created_at), asc(Report.id))

    query = query.offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    items_result = await db.execute(query)
    rows = items_result.all()

    items = []
    for r, lat, lon, dist in rows:
        is_owner = viewer_user_id is not None and r.created_by_user_id == viewer_user_id
        if is_owner:
            r.latitude = lat
            r.longitude = lon
            if dist is not None:
                r.distance_km = round(dist / 1000.0, 2)
        else:
            r.latitude, r.longitude = coarsen_coordinate(lat, lon)
            if dist is not None:
                r.distance_km = coarsen_distance(dist / 1000.0)
        items.append(r)

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


logger = logging.getLogger(__name__)


async def upload_report_image(
    db: AsyncSession, report: Report, file: UploadFile
) -> ReportImage:
    """Validates limits under row lock, uploads sanitized image, and commits record.

    Compensating transaction: If the database commit fails, the uploaded S3 object
    is deleted immediately to eliminate orphaned objects.
    """
    # 1. Lock parent report row to serialize concurrent image uploads for this report
    report_lock_stmt = select(Report).where(Report.id == report.id).with_for_update()
    locked_report_res = await db.execute(report_lock_stmt)
    if locked_report_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )

    # 2. Count existing images under row lock
    count_stmt = select(func.count(ReportImage.id)).where(
        ReportImage.report_id == report.id
    )
    current_count = (await db.execute(count_stmt)).scalar_one()
    if current_count >= settings.IMAGE_MAX_PER_REPORT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Maximum {settings.IMAGE_MAX_PER_REPORT} images allowed per report",
        )

    # 3. Upload sanitized image to S3
    object_key, file_size, content_type = await upload_image_to_s3(report.id, file)

    # 4. Persist database record with compensating cleanup on rollback
    image = ReportImage(
        report_id=report.id,
        object_key=object_key,
        content_type=content_type,
        file_size=file_size,
    )
    db.add(image)
    try:
        await db.commit()
        await db.refresh(image)
        return image
    except Exception as exc:
        await db.rollback()
        # Compensating cleanup: Delete orphaned S3 object
        try:
            await delete_image_from_s3(object_key)
        except Exception as s3_exc:
            logger.error(
                "Failed to clean up orphaned S3 object %s: %s", object_key, s3_exc
            )
        raise exc


async def delete_report_image(db: AsyncSession, image: ReportImage) -> None:
    """Deletes the image record from PostgreSQL and removes the object from S3."""
    object_key = image.object_key
    await db.delete(image)
    await db.commit()
    # Delete from S3 only after database commit succeeds
    try:
        await delete_image_from_s3(object_key)
    except Exception as exc:
        logger.error(
            "Failed to delete S3 object %s after DB commit: %s", object_key, exc
        )
