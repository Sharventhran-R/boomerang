import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import ReportCategory, ReportStatus, ReportType
from app.schemas.events.common import UtcDatetime
from app.schemas.events.envelope import EventEnvelope

ALLOWED_REPORT_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "category",
        "latitude",
        "longitude",
        "event_time",
        "reward_amount",
        "status",
    }
)


class ReportCreatedPayload(BaseModel):
    """Payload for 'report.created' event (v1).

    Emitted when a new Missing or Found report is persisted in PostgreSQL.
    Downstream consumers: Matching Engine, Nearby Notification Dispatcher,
    Search Indexer.
    """

    report_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the created report.",
    )
    created_by_user_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the user who authored the report.",
    )
    type: ReportType = Field(
        ...,
        description="Report classification: MISSING or FOUND.",
    )
    category: ReportCategory = Field(
        ...,
        description="Category of the missing or found item.",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Headline summary of the item or asset.",
    )
    description: str = Field(
        ...,
        max_length=2000,
        description="Detailed narrative of the incident or discovery.",
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Incident latitude in WGS84, justified for spatial matching.",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Incident longitude in WGS84, justified for spatial matching.",
    )
    event_time: UtcDatetime = Field(
        ...,
        description="Timezone-aware loss or discovery timestamp for temporal matching.",
    )
    reward_amount: Decimal | None = Field(
        default=None,
        ge=Decimal("0.0"),
        description="Optional reward amount (strictly restricted to MISSING reports).",
    )
    status: ReportStatus = Field(
        default=ReportStatus.ACTIVE,
        description="Initial report lifecycle status; must be ACTIVE.",
    )
    created_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware database creation timestamp.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @field_validator("title")
    @classmethod
    def validate_title_non_whitespace(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("title must not be empty or whitespace only")
        return cleaned

    @model_validator(mode="after")
    def validate_report_creation_rules(self) -> "ReportCreatedPayload":
        if self.type == ReportType.FOUND and self.reward_amount is not None:
            raise ValueError("FOUND reports cannot specify a reward_amount")
        if self.status != ReportStatus.ACTIVE:
            raise ValueError("Initial status for report.created must be ACTIVE")
        return self


class ReportUpdatedPayload(BaseModel):
    """Payload for 'report.updated' event (v1).

    Emitted when an active report's attributes are modified.
    Downstream consumers: Matching Engine (re-evaluation), Search Indexer.
    """

    report_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the updated report.",
    )
    updated_fields: list[str] = Field(
        ...,
        min_length=1,
        description="List of field names modified during this update transaction.",
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Updated headline if modified.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Updated description if modified.",
    )
    category: ReportCategory | None = Field(
        default=None,
        description="Updated category if modified.",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Updated latitude coordinate if modified.",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Updated longitude coordinate if modified.",
    )
    event_time: UtcDatetime | None = Field(
        default=None,
        description="Updated loss or discovery timestamp if modified.",
    )
    reward_amount: Decimal | None = Field(
        default=None,
        ge=Decimal("0.0"),
        description="Updated reward amount if modified.",
    )
    status: ReportStatus | None = Field(
        default=None,
        description="Updated report status if modified.",
    )
    updated_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware timestamp when the update occurred.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @field_validator("updated_fields")
    @classmethod
    def validate_updated_fields_content(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("updated_fields cannot be empty")
        for field_name in v:
            if field_name not in ALLOWED_REPORT_UPDATE_FIELDS:
                raise ValueError(
                    f"Invalid updated field: '{field_name}'. "
                    f"Allowed fields: {sorted(ALLOWED_REPORT_UPDATE_FIELDS)}"
                )
        return v

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> "ReportUpdatedPayload":
        lat_in_list = "latitude" in self.updated_fields
        lon_in_list = "longitude" in self.updated_fields
        lat_val = self.latitude is not None
        lon_val = self.longitude is not None

        if (lat_in_list or lat_val) != (lon_in_list or lon_val):
            raise ValueError(
                "latitude and longitude must be updated together as a coordinate pair"
            )
        return self


class ReportResolvedPayload(BaseModel):
    """Payload for 'report.resolved' event (v1).

    Emitted when a report's lifecycle status transitions to RESOLVED.
    Downstream consumers: Matching Engine (de-listing), Active Alerts Manager.

    Privacy decision: Geographic coordinates are excluded because resolution consumers
    only require aggregate entity identity and resolution context.
    """

    report_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the resolved report.",
    )
    status: ReportStatus = Field(
        default=ReportStatus.RESOLVED,
        description="Report resolution status; must be RESOLVED.",
    )
    resolved_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware timestamp when the report was marked resolved.",
    )
    resolution_reason: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Optional resolution context (e.g. 'recovery_completed', 'user_resolved')."
        ),
    )
    associated_recovery_request_id: uuid.UUID | None = Field(
        default=None,
        description="Identifier of recovery request that led to resolution, if any.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @model_validator(mode="after")
    def validate_resolved_status(self) -> "ReportResolvedPayload":
        if self.status != ReportStatus.RESOLVED:
            raise ValueError("status for report.resolved must be RESOLVED")
        return self


# Concrete Event Type Aliases
ReportCreatedEvent = EventEnvelope[ReportCreatedPayload]
ReportUpdatedEvent = EventEnvelope[ReportUpdatedPayload]
ReportResolvedEvent = EventEnvelope[ReportResolvedPayload]
