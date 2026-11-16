import uuid
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Report,
    ReportStatus,
    ReportType,
    User,
    UserDailyQuota,
    UserTrustTier,
)
from app.schemas.quota import (
    FoundReportsQuota,
    MissingReportsQuota,
    QuotaStatusResponse,
)


def get_quota_timezone() -> tzinfo:
    """Returns configured timezone, falling back to IST (+05:30) if tzdata missing."""
    try:
        return ZoneInfo(settings.QUOTA_TIMEZONE)
    except Exception:
        from datetime import timezone

        return timezone(timedelta(hours=5, minutes=30))


def get_daily_reset_window() -> tuple[date, datetime, int]:
    """Calculates current quota date, next reset UTC, and remaining seconds.

    All daily quotas reset at midnight Indian Standard Time (Asia/Kolkata).
    """
    tz = get_quota_timezone()
    now_tz = datetime.now(tz)
    today_date = now_tz.date()
    next_midnight_local = datetime.combine(
        today_date + timedelta(days=1), time.min, tzinfo=tz
    )
    next_midnight_utc = next_midnight_local.astimezone(UTC)
    seconds_remaining = max(1, int((next_midnight_local - now_tz).total_seconds()))
    return today_date, next_midnight_utc, seconds_remaining


def get_found_limit_for_tier(tier: UserTrustTier) -> int:
    """Returns the daily found report quota allowed for a given user trust tier."""
    if tier == UserTrustTier.TRUSTED:
        return settings.FOUND_REPORT_DAILY_LIMIT_TRUSTED
    if tier == UserTrustTier.ESTABLISHED:
        return settings.FOUND_REPORT_DAILY_LIMIT_ESTABLISHED
    return settings.FOUND_REPORT_DAILY_LIMIT_NEW


async def check_and_consume_report_quota(
    db: AsyncSession,
    user_id: uuid.UUID,
    report_type: ReportType,
) -> None:
    """Checks and increments report business quotas atomically.

    Concurrency & Invariants:
    1. Locks user row (`SELECT ... FOR UPDATE`) to prevent concurrent quota races.
    2. Active missing reports cap (10) is checked against PostgreSQL state.
    3. Daily missing & found report quotas are tracked in `user_daily_quotas`.
    4. Quota consumption is durable and non-refundable: deleting or resolving
       a report never restores consumed daily creation quota.
    """
    # 1. Lock user row to serialize concurrent creation requests for this user
    user_stmt = select(User).where(User.id == user_id).with_for_update()
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    today_date, _, seconds_to_reset = get_daily_reset_window()

    # 2. Check active missing reports cap
    if report_type == ReportType.MISSING:
        active_stmt = (
            select(func.count())
            .select_from(Report)
            .where(
                Report.created_by_user_id == user_id,
                Report.type == ReportType.MISSING,
                Report.status == ReportStatus.ACTIVE,
            )
        )
        active_count = (await db.execute(active_stmt)).scalar_one()
        if active_count >= settings.MISSING_REPORT_ACTIVE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Active missing report limit reached (maximum "
                    f"{settings.MISSING_REPORT_ACTIVE_LIMIT} active missing reports)."
                ),
                headers={"Retry-After": "3600"},
            )

    # 3. Lock or create user daily quota record for today
    quota_stmt = (
        select(UserDailyQuota)
        .where(
            UserDailyQuota.user_id == user_id,
            UserDailyQuota.quota_date == today_date,
        )
        .with_for_update()
    )
    quota_row = (await db.execute(quota_stmt)).scalar_one_or_none()
    if quota_row is None:
        quota_row = UserDailyQuota(
            user_id=user_id,
            quota_date=today_date,
            missing_count=0,
            found_count=0,
        )
        db.add(quota_row)
        await db.flush()

    # 4. Enforce daily limit and increment
    retry_headers = {"Retry-After": str(seconds_to_reset)}

    if report_type == ReportType.MISSING:
        daily_limit = settings.MISSING_REPORT_DAILY_LIMIT
        if quota_row.missing_count >= daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Daily missing report quota exceeded (maximum {daily_limit} "
                    "per day)."
                ),
                headers=retry_headers,
            )
        quota_row.missing_count += 1
    elif report_type == ReportType.FOUND:
        daily_limit = get_found_limit_for_tier(user.trust_tier)
        if quota_row.found_count >= daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Daily found report quota exceeded (maximum {daily_limit} "
                    f"per day for {user.trust_tier.value} tier)."
                ),
                headers=retry_headers,
            )
        quota_row.found_count += 1


async def get_user_quota_status(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> QuotaStatusResponse:
    """Returns the user's authoritative quota status and remaining allowances."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    today_date, next_midnight_utc, _ = get_daily_reset_window()

    # Query daily consumption
    quota_stmt = select(UserDailyQuota).where(
        UserDailyQuota.user_id == user_id,
        UserDailyQuota.quota_date == today_date,
    )
    quota_row = (await db.execute(quota_stmt)).scalar_one_or_none()
    missing_consumed = quota_row.missing_count if quota_row is not None else 0
    found_consumed = quota_row.found_count if quota_row is not None else 0

    # Query active missing count
    active_stmt = (
        select(func.count())
        .select_from(Report)
        .where(
            Report.created_by_user_id == user_id,
            Report.type == ReportType.MISSING,
            Report.status == ReportStatus.ACTIVE,
        )
    )
    active_missing_count = (await db.execute(active_stmt)).scalar_one()

    # Calculate limits & remaining
    missing_daily_limit = settings.MISSING_REPORT_DAILY_LIMIT
    missing_daily_remaining = max(0, missing_daily_limit - missing_consumed)

    missing_active_limit = settings.MISSING_REPORT_ACTIVE_LIMIT
    missing_active_remaining = max(0, missing_active_limit - active_missing_count)

    found_daily_limit = get_found_limit_for_tier(user.trust_tier)
    found_daily_remaining = max(0, found_daily_limit - found_consumed)

    return QuotaStatusResponse(
        user_id=user_id,
        trust_tier=user.trust_tier,
        missing_reports=MissingReportsQuota(
            daily_limit=missing_daily_limit,
            daily_consumed=missing_consumed,
            daily_remaining=missing_daily_remaining,
            active_limit=missing_active_limit,
            active_count=active_missing_count,
            active_remaining=missing_active_remaining,
        ),
        found_reports=FoundReportsQuota(
            daily_limit=found_daily_limit,
            daily_consumed=found_consumed,
            daily_remaining=found_daily_remaining,
        ),
        resets_at=next_midnight_utc,
    )
