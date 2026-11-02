"""Match domain event schemas for Boomerang Matching & Notification Engine (Phase 9.3).

Defines the event payload and envelope for 'match.alert_ready', emitted when a
persisted match record satisfies alert-eligibility rules.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ScoreClassification
from app.schemas.events.envelope import EventEnvelope


class MatchAlertReadyPayload(BaseModel):
    """Payload for 'match.alert_ready' domain event (v1).

    Emitted when a persisted, active candidate match satisfies alert eligibility
    conditions (composite score >= 75.0, alert_eligible == True).

    Privacy decision: Geographic coordinates are excluded to avoid third-party
    location leakage; distance is expressed strictly as relative distance_meters.
    """

    match_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the persisted match record.",
    )
    report_missing_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the Missing report in the match pair.",
    )
    report_found_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the Found report in the match pair.",
    )
    missing_owner_id: uuid.UUID = Field(
        ...,
        description="User identifier of the author who created the Missing report.",
    )
    found_owner_id: uuid.UUID = Field(
        ...,
        description="User identifier of the author who created the Found report.",
    )
    source_report_id: uuid.UUID = Field(
        ...,
        description="Identifier of the report triggering this matching evaluation.",
    )
    source_owner_id: uuid.UUID = Field(
        ...,
        description="User identifier of the author triggering the matching evaluation.",
    )
    composite_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Authoritative composite match score (0-100).",
    )
    classification: ScoreClassification = Field(
        ...,
        description="Score band classification (HIGH_PRIORITY, POSSIBLE_MATCH, etc.).",
    )
    alert_eligible: bool = Field(
        ...,
        description="Whether this match satisfies all alert eligibility criteria.",
    )
    is_update: bool = Field(
        default=False,
        description=(
            "Whether this event represents an update to a previously scored match."
        ),
    )
    previous_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Previous composite score before rescoring (if is_update is True).",
    )
    score_delta: float | None = Field(
        default=None,
        description="Change in composite score (new_score - previous_score) if update.",
    )
    evidence_summary: str | None = Field(
        default=None,
        max_length=500,
        description="Textual evidence summary explaining why the reports matched.",
    )
    distance_meters: float | None = Field(
        default=None,
        ge=0.0,
        description="Relative distance between report locations in meters.",
    )
    matched_category: str | None = Field(
        default=None,
        description="Item category shared between the two matched reports.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @model_validator(mode="after")
    def validate_match_alert_rules(self) -> MatchAlertReadyPayload:
        if self.report_missing_id == self.report_found_id:
            raise ValueError(
                "report_missing_id and report_found_id cannot be identical"
            )
        if self.source_report_id not in (self.report_missing_id, self.report_found_id):
            raise ValueError(
                "source_report_id must match either report_missing_id or "
                "report_found_id"
            )
        if self.source_owner_id not in (self.missing_owner_id, self.found_owner_id):
            raise ValueError(
                "source_owner_id must match either missing_owner_id or found_owner_id"
            )
        if not self.alert_eligible:
            raise ValueError("match.alert_ready event requires alert_eligible=True")
        if self.is_update and self.previous_score is None:
            raise ValueError("is_update=True requires previous_score to be specified")
        return self


MatchAlertReadyEvent = EventEnvelope[MatchAlertReadyPayload]
