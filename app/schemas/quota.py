from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import UserTrustTier


class MissingReportsQuota(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    daily_limit: int
    daily_consumed: int
    daily_remaining: int
    active_limit: int
    active_count: int
    active_remaining: int


class FoundReportsQuota(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    daily_limit: int
    daily_consumed: int
    daily_remaining: int


class QuotaStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    trust_tier: UserTrustTier
    missing_reports: MissingReportsQuota
    found_reports: FoundReportsQuota
    resets_at: datetime
