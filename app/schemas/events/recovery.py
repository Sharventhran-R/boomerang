import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import RecoveryRequestStatus
from app.schemas.events.common import UtcDatetime
from app.schemas.events.envelope import EventEnvelope

TERMINAL_RECOVERY_STATUSES: frozenset[RecoveryRequestStatus] = frozenset(
    {
        RecoveryRequestStatus.REJECTED,
        RecoveryRequestStatus.CANCELLED,
        RecoveryRequestStatus.COMPLETED,
    }
)


class RecoveryRequestCreatedPayload(BaseModel):
    """Payload for 'recovery_request.created' event (v1).

    Emitted when a user initiates a contact/handover request on an active report.
    Downstream consumers: Notification Dispatcher, Audit Logger.

    Privacy decision: Omits private user email, phone, and verification response
    secrets. Recipients are addressed strictly by user ID for downstream routing.
    """

    recovery_request_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the created recovery request.",
    )
    report_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the target report.",
    )
    requester_id: uuid.UUID = Field(
        ...,
        description="User ID of the operator initiating the recovery request.",
    )
    recipient_id: uuid.UUID = Field(
        ...,
        description="User ID of the report author receiving the request.",
    )
    status: RecoveryRequestStatus = Field(
        default=RecoveryRequestStatus.PENDING,
        description="Initial lifecycle status; must be PENDING.",
    )
    message: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional introductory message from the requester.",
    )
    created_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware database creation timestamp.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @model_validator(mode="after")
    def validate_request_creation_rules(self) -> "RecoveryRequestCreatedPayload":
        if self.requester_id == self.recipient_id:
            raise ValueError("requester_id and recipient_id cannot be identical")
        if self.status != RecoveryRequestStatus.PENDING:
            raise ValueError(
                "Initial status for recovery_request.created must be PENDING"
            )
        return self


class RecoveryRequestUpdatedPayload(BaseModel):
    """Payload for 'recovery_request.updated' event (v1).

    Emitted when a recovery request transitions lifecycle state.
    Downstream consumers: Notification Dispatcher, Report Service, Audit Logger.

    Privacy decision: Sensitive verification answers or proof attachments
    ('verification_response') are strictly excluded to protect private claim
    evidence from event brokers and public consumers.
    """

    recovery_request_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the recovery request.",
    )
    report_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the target report.",
    )
    requester_id: uuid.UUID = Field(
        ...,
        description="User ID of the operator who initiated the recovery request.",
    )
    recipient_id: uuid.UUID = Field(
        ...,
        description="User ID of the report author receiving the request.",
    )
    previous_status: RecoveryRequestStatus = Field(
        ...,
        description="Status of the request immediately before this transition.",
    )
    new_status: RecoveryRequestStatus = Field(
        ...,
        description="New lifecycle status of the recovery request.",
    )
    updated_at: UtcDatetime = Field(
        ...,
        description="Timezone-aware timestamp when status transition was recorded.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @model_validator(mode="after")
    def validate_status_transition(self) -> "RecoveryRequestUpdatedPayload":
        if self.previous_status == self.new_status:
            raise ValueError(
                f"previous_status and new_status cannot both be "
                f"'{self.new_status.value}'"
            )

        if self.previous_status in TERMINAL_RECOVERY_STATUSES:
            raise ValueError(
                f"Cannot transition from terminal recovery status "
                f"'{self.previous_status.value}'"
            )

        if self.previous_status == RecoveryRequestStatus.PENDING:
            if self.new_status not in (
                RecoveryRequestStatus.ACCEPTED,
                RecoveryRequestStatus.REJECTED,
                RecoveryRequestStatus.CANCELLED,
            ):
                raise ValueError(
                    f"Invalid transition from PENDING to '{self.new_status.value}'"
                )
        elif self.previous_status == RecoveryRequestStatus.ACCEPTED:
            if self.new_status not in (
                RecoveryRequestStatus.COMPLETED,
                RecoveryRequestStatus.CANCELLED,
            ):
                raise ValueError(
                    f"Invalid transition from ACCEPTED to '{self.new_status.value}'"
                )

        return self


# Concrete Event Type Aliases
RecoveryRequestCreatedEvent = EventEnvelope[RecoveryRequestCreatedPayload]
RecoveryRequestUpdatedEvent = EventEnvelope[RecoveryRequestUpdatedPayload]
