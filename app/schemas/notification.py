"""Pydantic schemas for Boomerang Notification REST APIs (Phase 9.5).

Exposes models for:
- In-app notification listing, counting, and reading.
- FCM device token registration and deactivation.
- User notification preferences.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import DevicePlatform, NotificationPriority, NotificationType

# Keys that must never be leaked through notification data
SENSITIVE_DATA_KEYS: frozenset[str] = frozenset(
    {
        "fcm_token",
        "token",
        "latitude",
        "longitude",
        "coordinates",
        "verification_secret",
        "secret",
        "password",
        "pin",
    }
)


class NotificationResponse(BaseModel):
    """Public representation of an in-app notification."""

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    data: dict[str, Any]
    priority: NotificationPriority
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("data", mode="after")
    @classmethod
    def sanitize_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Strip internal secrets or sensitive coordinates defensively."""
        if not isinstance(v, dict):
            return {}
        return {k: val for k, val in v.items() if k.lower() not in SENSITIVE_DATA_KEYS}


class NotificationListResponse(BaseModel):
    """Paginated list of user notifications."""

    items: list[NotificationResponse]
    unread_count: int
    page: int
    page_size: int
    total: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


class UnreadCountResponse(BaseModel):
    """Badge count response for unread notifications."""

    unread_count: int


class BulkActionResponse(BaseModel):
    """Response for bulk notification operations."""

    count: int = Field(..., description="Number of notifications affected")


# Aliases for specification compatibility
BulkReadResponse = BulkActionResponse


class DeviceRegisterRequest(BaseModel):
    """Request payload for FCM device token registration."""

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique client device identifier",
    )
    fcm_token: str = Field(
        ...,
        min_length=10,
        description="FCM registration token",
    )
    platform: DevicePlatform
    device_model: str | None = Field(default=None, max_length=100)
    app_version: str | None = Field(default=None, max_length=20)


# Alias for specification compatibility
RegisterDeviceRequest = DeviceRegisterRequest


class DeviceResponse(BaseModel):
    """Public device representation. Never exposes raw FCM tokens."""

    id: uuid.UUID
    device_id: str
    platform: DevicePlatform
    device_model: str | None = None
    app_version: str | None = None
    is_active: bool
    last_active_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceResponse(BaseModel):
    """User notification settings response."""

    push_enabled: bool
    in_app_enabled: bool
    match_alerts_enabled: bool
    match_min_score: float
    match_high_priority_only: bool
    recovery_updates_enabled: bool
    report_status_enabled: bool
    quiet_hours_enabled: bool
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceUpdateRequest(BaseModel):
    """Request payload for updating notification preferences."""

    push_enabled: bool | None = None
    in_app_enabled: bool | None = None
    match_alerts_enabled: bool | None = None
    match_min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Minimum match composite score threshold (0.0 - 100.0)",
    )
    match_high_priority_only: bool | None = None
    recovery_updates_enabled: bool | None = None
    report_status_enabled: bool | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


# Alias for specification compatibility
UpdateNotificationPreferenceRequest = NotificationPreferenceUpdateRequest
