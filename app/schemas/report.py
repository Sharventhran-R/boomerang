import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ReportCategory, ReportStatus, ReportType


class CreateReportRequest(BaseModel):
    type: ReportType
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., max_length=2000)
    category: ReportCategory
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    event_time: datetime
    reward_amount: Decimal | None = Field(default=None, ge=Decimal("0.0"))

    @model_validator(mode="after")
    def validate_reward(self) -> "CreateReportRequest":
        if self.type == ReportType.FOUND and self.reward_amount is not None:
            raise ValueError("FOUND reports cannot have a reward_amount")
        return self


class UpdateReportRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    category: ReportCategory | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    event_time: datetime | None = None
    reward_amount: Decimal | None = Field(default=None, ge=Decimal("0.0"))
    status: ReportStatus | None = None


class ReportImageResponse(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    object_key: str
    content_type: str
    file_size: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportResponse(BaseModel):
    id: uuid.UUID
    created_by_user_id: uuid.UUID
    type: ReportType
    title: str
    description: str
    category: ReportCategory
    latitude: float
    longitude: float
    event_time: datetime
    reward_amount: Decimal | None
    status: ReportStatus
    created_at: datetime
    updated_at: datetime
    images: list[ReportImageResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
