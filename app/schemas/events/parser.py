import json
from typing import Any

from app.schemas.events.common import (
    EventParseError,
    UnsupportedEventTypeError,
    UnsupportedEventVersionError,
)
from app.schemas.events.envelope import EventType
from app.schemas.events.recovery import (
    RecoveryRequestCreatedEvent,
    RecoveryRequestUpdatedEvent,
)
from app.schemas.events.report import (
    ReportCreatedEvent,
    ReportResolvedEvent,
    ReportUpdatedEvent,
)

type BoomerangEvent = (
    ReportCreatedEvent
    | ReportUpdatedEvent
    | ReportResolvedEvent
    | RecoveryRequestCreatedEvent
    | RecoveryRequestUpdatedEvent
)


def parse_event(raw: str | bytes | dict[str, Any]) -> BoomerangEvent:
    """Parses and strictly validates raw incoming data into a typed domain event.

    Args:
        raw: Serialized JSON string, bytes, or parsed dictionary.

    Returns:
        Concrete validated instance of BoomerangEvent matching event_type.

    Raises:
        EventParseError: If input is not a valid JSON string, bytes, or dict.
        UnsupportedEventVersionError: If event_version is not supported (v1 only).
        UnsupportedEventTypeError: If event_type is unknown or missing.
        pydantic.ValidationError: If payload or envelope violates constraints.
    """
    if isinstance(raw, (str, bytes)):
        try:
            data: Any = json.loads(raw)
        except Exception as exc:
            raise EventParseError(f"Malformed JSON payload: {exc}") from exc
    elif isinstance(raw, dict):
        data = raw
    else:
        raise EventParseError(
            f"Expected str, bytes, or dict, but received {type(raw).__name__}"
        )

    if not isinstance(data, dict):
        raise EventParseError(
            f"Root JSON value must be an object, got {type(data).__name__}"
        )

    version = data.get("event_version")
    if version != 1:
        raise UnsupportedEventVersionError(
            f"Unsupported event version: {version}. Currently supported versions: [1]."
        )

    event_type_raw = data.get("event_type")
    if not event_type_raw or not isinstance(event_type_raw, str):
        raise UnsupportedEventTypeError(
            f"Missing or invalid 'event_type': {event_type_raw}"
        )

    try:
        event_type = EventType(event_type_raw)
    except ValueError:
        raise UnsupportedEventTypeError(
            f"Unsupported event type: '{event_type_raw}'. Supported types: "
            f"{[e.value for e in EventType]}"
        )

    match event_type:
        case EventType.REPORT_CREATED:
            return ReportCreatedEvent.model_validate(data)
        case EventType.REPORT_UPDATED:
            return ReportUpdatedEvent.model_validate(data)
        case EventType.REPORT_RESOLVED:
            return ReportResolvedEvent.model_validate(data)
        case EventType.RECOVERY_REQUEST_CREATED:
            return RecoveryRequestCreatedEvent.model_validate(data)
        case EventType.RECOVERY_REQUEST_UPDATED:
            return RecoveryRequestUpdatedEvent.model_validate(data)
