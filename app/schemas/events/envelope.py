import enum
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.events.common import UtcDatetime


class AggregateType(enum.StrEnum):
    """Aggregate entity types supported in Boomerang domain events."""

    REPORT = "report"
    RECOVERY_REQUEST = "recovery_request"


class EventType(enum.StrEnum):
    """Namespaced event types defined in Boomerang Phase 7.1."""

    REPORT_CREATED = "report.created"
    REPORT_UPDATED = "report.updated"
    REPORT_RESOLVED = "report.resolved"
    RECOVERY_REQUEST_CREATED = "recovery_request.created"
    RECOVERY_REQUEST_UPDATED = "recovery_request.updated"


class EventEnvelope[PayloadT: BaseModel](BaseModel):
    """Standardized, immutable envelope for all Boomerang domain events.

    Provides core routing metadata, traceability, and schema versioning
    while holding a strongly-typed, validated event payload.
    """

    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Globally unique UUID identifying this specific event occurrence.",
    )
    event_type: EventType = Field(
        ...,
        description="Namespaced string identifying the business event type.",
    )
    event_version: int = Field(
        default=1,
        ge=1,
        description="Positive integer schema version for the event type.",
    )
    occurred_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware UTC timestamp when event occurred in producer.",
    )
    producer: str = Field(
        ...,
        min_length=1,
        description="Identifier of the service or subsystem producing the event.",
    )
    aggregate_id: uuid.UUID = Field(
        ...,
        description=(
            "Unique identifier of aggregate root entity (report or recovery request)."
        ),
    )
    aggregate_type: AggregateType = Field(
        ...,
        description="Category of the aggregate root entity.",
    )
    correlation_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional correlation identifier for distributed tracing/correlation."
        ),
    )
    payload: PayloadT = Field(
        ...,
        description="Strongly-typed, validated business payload.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @field_validator("producer")
    @classmethod
    def validate_producer(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("producer must not be empty or blank")
        return cleaned

    @model_validator(mode="after")
    def validate_envelope_consistency(self) -> "EventEnvelope[PayloadT]":
        # 1. Verify aggregate_type matches event_type prefix namespace
        if self.event_type.startswith("report."):
            if self.aggregate_type != AggregateType.REPORT:
                raise ValueError(
                    f"event_type '{self.event_type}' requires aggregate_type "
                    f"'{AggregateType.REPORT.value}', got '{self.aggregate_type.value}'"
                )
        elif self.event_type.startswith("recovery_request."):
            if self.aggregate_type != AggregateType.RECOVERY_REQUEST:
                req_val = AggregateType.RECOVERY_REQUEST.value
                raise ValueError(
                    f"event_type '{self.event_type}' requires aggregate_type "
                    f"'{req_val}', got '{self.aggregate_type.value}'"
                )

        # 2. Verify aggregate_id matches entity ID in payload based on aggregate_type
        payload = self.payload
        payload_entity_id = None
        if self.aggregate_type == AggregateType.REPORT:
            payload_entity_id = getattr(payload, "report_id", None)
        elif self.aggregate_type == AggregateType.RECOVERY_REQUEST:
            payload_entity_id = getattr(payload, "recovery_request_id", None)

        if payload_entity_id is not None and payload_entity_id != self.aggregate_id:
            raise ValueError(
                f"aggregate_id '{self.aggregate_id}' does not match payload entity ID "
                f"'{payload_entity_id}'"
            )

        return self
