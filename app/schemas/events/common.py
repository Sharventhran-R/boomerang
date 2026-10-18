from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


class EventError(Exception):
    """Base exception for event processing and schema validation errors."""


class UnsupportedEventTypeError(EventError):
    """Raised when an event type is unrecognized or unsupported."""


class UnsupportedEventVersionError(EventError):
    """Raised when an event schema version is unrecognized or unsupported."""


class EventParseError(EventError):
    """Raised when event raw data cannot be parsed into a valid event structure."""


def ensure_utc_datetime(v: datetime) -> datetime:
    """Enforces that a datetime is timezone-aware and normalizes it to UTC.

    Rejects naive datetimes to avoid timezone ambiguity across distributed systems.
    """
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("Timestamp must be timezone-aware (e.g. UTC)")
    return v.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc_datetime)]
