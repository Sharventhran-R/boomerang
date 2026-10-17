import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    RecoveryRequestStatus,
    ReportCategory,
    ReportStatus,
    ReportType,
)


class CreateRecoveryRequest(BaseModel):
    report_id: uuid.UUID
    message: str | None = Field(default=None, max_length=2000)


class UpdateRecoveryRequestStatus(BaseModel):
    status: RecoveryRequestStatus
    verification_response: str | None = Field(default=None, max_length=2000)


class RecoveryRequestUserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class RecoveryRequestReportResponse(BaseModel):
    id: uuid.UUID
    title: str
    type: ReportType
    category: ReportCategory
    status: ReportStatus

    model_config = ConfigDict(from_attributes=True)


class RecoveryRequestResponse(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    requester_id: uuid.UUID
    recipient_id: uuid.UUID
    status: RecoveryRequestStatus
    message: str | None = None
    verification_response: str | None = None
    created_at: datetime
    updated_at: datetime
    report: RecoveryRequestReportResponse | None = None
    requester: RecoveryRequestUserResponse | None = None
    recipient: RecoveryRequestUserResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class RecoveryRequestListResponse(BaseModel):
    items: list[RecoveryRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
