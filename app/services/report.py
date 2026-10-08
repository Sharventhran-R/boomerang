import uuid
from typing import Any, cast

from fastapi import UploadFile
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import asc, desc, func, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Report, ReportCategory, ReportImage, ReportStatus, ReportType
from app.schemas.geo import GeoSearchParams
from app.schemas.report import CreateReportRequest, UpdateReportRequest
from app.services.storage import delete_image_from_s3, upload_image_to_s3


async def create_report(
    db: AsyncSession, user_id: uuid.UUID, report_in: CreateReportRequest
) -> Report:
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
    if report_in.title is not None:
        report.title = report_in.title
    if report_in.description is not None:
        report.description = report_in.description
    if report_in.category is not None:
        report.category = report_in.category
    if report_in.event_time is not None:
        report.event_time = report_in.event_time
    if report_in.reward_amount is not None:
        report.reward_amount = report_in.reward_amount
    if report_in.status is not None:
        report.status = report_in.status
    if report_in.latitude is not None and report_in.longitude is not None:
        report.location = WKTElement(
            f"POINT({report_in.longitude} {report_in.latitude})", srid=4326
        )
        report.latitude = report_in.latitude  # type: ignore
        report.longitude = report_in.longitude  # type: ignore
    elif report_in.latitude is not None or report_in.longitude is not None:
        # If only one is provided, we need the other.
        # We already have them on the report object.
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
        report.location = WKTElement(f"POINT({lon} {lat})", srid=4326)
        report.latitude = lat  # type: ignore
        report.longitude = lon  # type: ignore

    db.add(report)
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
) -> dict[str, Any]:
    count_query = select(func.count(Report.id))

    filters = []
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

    distance_col = null().label("distance")
    if (
        geo
        and geo.latitude is not None
        and geo.longitude is not None
        and geo.radius_km is not None
    ):
        radius_meters = float(geo.radius_km) * 1000.0
        search_point = WKTElement(f"POINT({geo.longitude} {geo.latitude})", srid=4326)
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
        query = query.order_by(
            asc(distance_col), desc(Report.created_at), asc(Report.id)
        )
    elif sort == "newest":
        query = query.order_by(desc(Report.created_at))
    else:
        query = query.order_by(asc(Report.created_at))

    query = query.offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    items_result = await db.execute(query)
    rows = items_result.all()

    items = []
    for r, lat, lon, dist in rows:
        r.latitude = lat
        r.longitude = lon
        if dist is not None:
            r.distance_km = round(dist / 1000.0, 2)
        items.append(r)

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


async def upload_report_image(
    db: AsyncSession, report: Report, file: UploadFile
) -> ReportImage:
    # report must be already loaded and authorized
    if len(report.images) >= 5:
        raise ValueError("Maximum 5 images allowed per report")

    object_key, file_size = await upload_image_to_s3(report.id, file)

    image = ReportImage(
        report_id=report.id,
        object_key=object_key,
        content_type=file.content_type,
        file_size=file_size,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def delete_report_image(db: AsyncSession, image: ReportImage) -> None:
    await delete_image_from_s3(image.object_key)
    await db.delete(image)
    await db.commit()
