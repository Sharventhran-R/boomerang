import json
import uuid
from datetime import UTC, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models import (
    RecoveryRequestStatus,
    ReportCategory,
    ReportStatus,
    ReportType,
)
from app.schemas.events import (
    AggregateType,
    EventParseError,
    EventType,
    RecoveryRequestCreatedEvent,
    RecoveryRequestCreatedPayload,
    RecoveryRequestUpdatedEvent,
    RecoveryRequestUpdatedPayload,
    ReportCreatedEvent,
    ReportCreatedPayload,
    ReportResolvedEvent,
    ReportResolvedPayload,
    ReportUpdatedEvent,
    ReportUpdatedPayload,
    UnsupportedEventTypeError,
    UnsupportedEventVersionError,
    parse_event,
)


class TestEventEnvelopeValidation:
    """Tests for EventEnvelope structure, invariants, and validation rules."""

    def test_valid_envelope_construction(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportCreatedPayload(
            report_id=report_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.MISSING,
            category=ReportCategory.ELECTRONICS,
            title="Lost iPhone 15",
            description="Lost near central station",
            latitude=50.4501,
            longitude=30.5234,
            event_time=now,
            reward_amount=Decimal("50.00"),
            status=ReportStatus.ACTIVE,
            created_at=now,
        )

        event = ReportCreatedEvent(
            event_type=EventType.REPORT_CREATED,
            event_version=1,
            occurred_at=now,
            producer="boomerang.report_service",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            correlation_id=uuid.uuid4(),
            payload=payload,
        )

        assert event.event_type == EventType.REPORT_CREATED
        assert event.event_version == 1
        assert event.aggregate_id == report_id
        assert event.aggregate_type == AggregateType.REPORT
        assert event.correlation_id is not None
        assert event.payload.title == "Lost iPhone 15"

    def test_optional_correlation_id_defaults_to_none(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportCreatedPayload(
            report_id=report_id,
            created_by_user_id=uuid.uuid4(),
            type=ReportType.FOUND,
            category=ReportCategory.KEYS,
            title="Keys found",
            description="Found set of brass keys",
            latitude=13.0827,
            longitude=80.2707,
            event_time=now,
            status=ReportStatus.ACTIVE,
            created_at=now,
        )

        event = ReportCreatedEvent(
            event_type=EventType.REPORT_CREATED,
            occurred_at=now,
            producer="boomerang.report_service",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=payload,
        )

        assert event.correlation_id is None
        assert isinstance(event.event_id, uuid.UUID)

    def test_rejection_of_malformed_uuids(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_id="not-a-valid-uuid",  # type: ignore[arg-type]
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                payload=payload,
            )
        assert "event_id" in str(exc.value)

    def test_rejection_of_malformed_correlation_id(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                correlation_id="invalid-uuid",  # type: ignore[arg-type]
                payload=payload,
            )
        assert "correlation_id" in str(exc.value)

    def test_rejection_of_invalid_version(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                event_version=0,  # Invalid: must be >= 1
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                payload=payload,
            )
        assert "event_version" in str(exc.value)

    def test_rejection_of_empty_or_whitespace_producer(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="   ",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                payload=payload,
            )
        assert "producer" in str(exc.value)

    def test_rejection_of_naive_timestamp(self) -> None:
        report_id = uuid.uuid4()
        naive_time = datetime(2026, 10, 18, 12, 0, 0)  # No tzinfo
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=datetime.now(UTC),
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=naive_time,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                payload=payload,
            )
        assert "timezone-aware" in str(exc.value)

    def test_mismatched_aggregate_type_and_event_type_rejected(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.RECOVERY_REQUEST,  # Wrong aggregate type
                payload=payload,
            )
        assert "requires aggregate_type 'report'" in str(exc.value)

    def test_mismatched_aggregate_id_and_payload_entity_id_rejected(self) -> None:
        report_id = uuid.uuid4()
        different_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=different_id,  # Mismatch with payload.report_id
                aggregate_type=AggregateType.REPORT,
                payload=payload,
            )
        assert "does not match payload entity ID" in str(exc.value)

    def test_immutability_of_frozen_envelope(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        event = ReportResolvedEvent(
            event_type=EventType.REPORT_RESOLVED,
            occurred_at=now,
            producer="boomerang.test",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=payload,
        )
        with pytest.raises(ValidationError):
            event.producer = "modified.producer"


class TestReportEventPayloads:
    """Tests for report event contracts: created, updated, resolved."""

    def test_report_created_found_rejects_reward(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                type=ReportType.FOUND,
                category=ReportCategory.WALLET,
                title="Found black wallet",
                description="Found in park",
                latitude=50.45,
                longitude=30.52,
                event_time=now,
                reward_amount=Decimal("20.00"),  # Invalid for FOUND
                status=ReportStatus.ACTIVE,
                created_at=now,
            )
        assert "FOUND reports cannot specify a reward_amount" in str(exc.value)

    def test_report_created_status_must_be_active(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                type=ReportType.MISSING,
                category=ReportCategory.BAG,
                title="Lost backpack",
                description="Lost on train",
                latitude=50.45,
                longitude=30.52,
                event_time=now,
                status=ReportStatus.RESOLVED,  # Invalid: must be ACTIVE
                created_at=now,
            )
        assert "Initial status for report.created must be ACTIVE" in str(exc.value)

    def test_report_created_rejects_out_of_bounds_coordinates(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                type=ReportType.MISSING,
                category=ReportCategory.OTHER,
                title="Lost item",
                description="Lost somewhere",
                latitude=95.0,  # Invalid: > 90
                longitude=30.52,
                event_time=now,
                created_at=now,
            )
        assert "latitude" in str(exc.value)

    def test_report_updated_valid(self) -> None:
        now = datetime.now(UTC)
        report_id = uuid.uuid4()
        payload = ReportUpdatedPayload(
            report_id=report_id,
            updated_fields=["title", "reward_amount"],
            title="Updated Title",
            reward_amount=Decimal("100.00"),
            updated_at=now,
        )
        assert payload.title == "Updated Title"
        assert payload.reward_amount == Decimal("100.00")
        assert payload.category is None

    def test_report_updated_rejects_unrecognized_field_name(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportUpdatedPayload(
                report_id=uuid.uuid4(),
                updated_fields=["unknown_column"],  # Invalid
                updated_at=now,
            )
        assert "Invalid updated field: 'unknown_column'" in str(exc.value)

    def test_report_updated_enforces_coordinate_pair(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportUpdatedPayload(
                report_id=uuid.uuid4(),
                updated_fields=["latitude"],  # Latitude without longitude
                latitude=50.45,
                updated_at=now,
            )
        assert "latitude and longitude must be updated together" in str(exc.value)

    def test_report_resolved_valid_with_recovery_link(self) -> None:
        report_id = uuid.uuid4()
        recovery_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
            resolution_reason="recovery_completed",
            associated_recovery_request_id=recovery_id,
        )
        assert payload.status == ReportStatus.RESOLVED
        assert payload.associated_recovery_request_id == recovery_id

    def test_report_resolved_must_have_resolved_status(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportResolvedPayload(
                report_id=uuid.uuid4(),
                status=ReportStatus.ACTIVE,  # Invalid for report.resolved
                resolved_at=now,
            )
        assert "status for report.resolved must be RESOLVED" in str(exc.value)


class TestRecoveryRequestEventPayloads:
    """Tests for recovery request event contracts: created and updated."""

    def test_recovery_request_created_valid(self) -> None:
        req_id = uuid.uuid4()
        report_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        recipient_id = uuid.uuid4()
        now = datetime.now(UTC)

        payload = RecoveryRequestCreatedPayload(
            recovery_request_id=req_id,
            report_id=report_id,
            requester_id=requester_id,
            recipient_id=recipient_id,
            status=RecoveryRequestStatus.PENDING,
            message="I believe this is my item",
            created_at=now,
        )
        assert payload.status == RecoveryRequestStatus.PENDING
        assert payload.message == "I believe this is my item"

    def test_recovery_request_created_rejects_identical_users(self) -> None:
        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestCreatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=user_id,
                recipient_id=user_id,  # Same user
                status=RecoveryRequestStatus.PENDING,
                created_at=now,
            )
        assert "requester_id and recipient_id cannot be identical" in str(exc.value)

    def test_recovery_request_created_status_must_be_pending(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestCreatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                status=RecoveryRequestStatus.ACCEPTED,  # Invalid initial status
                created_at=now,
            )
        assert "Initial status for recovery_request.created must be PENDING" in str(
            exc.value
        )

    def test_recovery_request_updated_valid_transition(self) -> None:
        now = datetime.now(UTC)
        payload = RecoveryRequestUpdatedPayload(
            recovery_request_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
            requester_id=uuid.uuid4(),
            recipient_id=uuid.uuid4(),
            previous_status=RecoveryRequestStatus.PENDING,
            new_status=RecoveryRequestStatus.ACCEPTED,
            updated_at=now,
        )
        assert payload.previous_status == RecoveryRequestStatus.PENDING
        assert payload.new_status == RecoveryRequestStatus.ACCEPTED

    def test_recovery_request_updated_rejects_same_status(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestUpdatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                previous_status=RecoveryRequestStatus.ACCEPTED,
                new_status=RecoveryRequestStatus.ACCEPTED,
                updated_at=now,
            )
        assert "previous_status and new_status cannot both be 'ACCEPTED'" in str(
            exc.value
        )

    def test_recovery_request_updated_rejects_transition_from_terminal(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestUpdatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                previous_status=RecoveryRequestStatus.COMPLETED,
                new_status=RecoveryRequestStatus.ACCEPTED,
                updated_at=now,
            )
        assert "Cannot transition from terminal recovery status 'COMPLETED'" in str(
            exc.value
        )

    def test_recovery_request_updated_rejects_invalid_intermediate_transition(
        self,
    ) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestUpdatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                previous_status=RecoveryRequestStatus.PENDING,
                # Cannot jump from PENDING to COMPLETED
                new_status=RecoveryRequestStatus.COMPLETED,
                updated_at=now,
            )
        assert "Invalid transition from PENDING to 'COMPLETED'" in str(exc.value)


class TestSensitiveFieldsProtection:
    """Tests ensuring private and sensitive information cannot enter event contracts."""

    def test_report_payload_rejects_sensitive_extra_fields(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                type=ReportType.MISSING,
                category=ReportCategory.DOCUMENT,
                title="Lost Passport",
                description="Lost in cafe",
                latitude=50.45,
                longitude=30.52,
                event_time=now,
                created_at=now,
                password_hash="secret_hash",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc.value)

    def test_recovery_payload_rejects_verification_response_extra_field(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestCreatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                status=RecoveryRequestStatus.PENDING,
                created_at=now,
                verification_response="secret answer 123",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc.value)

    def test_recovery_updated_payload_rejects_verification_response(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            RecoveryRequestUpdatedPayload(
                recovery_request_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                previous_status=RecoveryRequestStatus.PENDING,
                new_status=RecoveryRequestStatus.ACCEPTED,
                updated_at=now,
                verification_response="secret verification",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc.value)

    def test_envelope_rejects_extra_fields(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=now,
        )
        with pytest.raises(ValidationError) as exc:
            ReportResolvedEvent(
                event_type=EventType.REPORT_RESOLVED,
                occurred_at=now,
                producer="boomerang.test",
                aggregate_id=report_id,
                aggregate_type=AggregateType.REPORT,
                payload=payload,
                jwt_token="sensitive.bearer.token",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc.value)


class TestSerializationAndDeserialization:
    """Tests for serialization, JSON deserialization, and event parsing."""

    def test_serialize_and_parse_report_created_event(self) -> None:
        report_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(UTC)

        event = ReportCreatedEvent(
            event_type=EventType.REPORT_CREATED,
            event_version=1,
            occurred_at=now,
            producer="boomerang.report_service",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=ReportCreatedPayload(
                report_id=report_id,
                created_by_user_id=user_id,
                type=ReportType.MISSING,
                category=ReportCategory.PET,
                title="Lost Golden Retriever",
                description="Wearing red collar near park",
                latitude=50.4501,
                longitude=30.5234,
                event_time=now,
                reward_amount=Decimal("150.00"),
                status=ReportStatus.ACTIVE,
                created_at=now,
            ),
        )

        serialized = event.model_dump_json()
        assert isinstance(serialized, str)

        parsed = parse_event(serialized)
        assert isinstance(parsed.payload, ReportCreatedPayload)
        assert parsed.event_type == EventType.REPORT_CREATED
        assert parsed.event_version == 1
        assert parsed.aggregate_id == report_id
        assert parsed.payload.title == "Lost Golden Retriever"
        assert parsed.payload.reward_amount == Decimal("150.00")
        assert parsed.payload.category == ReportCategory.PET

    def test_serialize_and_parse_recovery_request_updated_event(self) -> None:
        req_id = uuid.uuid4()
        report_id = uuid.uuid4()
        now = datetime.now(UTC)

        event = RecoveryRequestUpdatedEvent(
            event_type=EventType.RECOVERY_REQUEST_UPDATED,
            occurred_at=now,
            producer="boomerang.recovery_service",
            aggregate_id=req_id,
            aggregate_type=AggregateType.RECOVERY_REQUEST,
            payload=RecoveryRequestUpdatedPayload(
                recovery_request_id=req_id,
                report_id=report_id,
                requester_id=uuid.uuid4(),
                recipient_id=uuid.uuid4(),
                previous_status=RecoveryRequestStatus.ACCEPTED,
                new_status=RecoveryRequestStatus.COMPLETED,
                updated_at=now,
            ),
        )

        raw_dict = event.model_dump(mode="json")
        parsed = parse_event(raw_dict)

        assert isinstance(parsed.payload, RecoveryRequestUpdatedPayload)
        assert parsed.event_type == EventType.RECOVERY_REQUEST_UPDATED
        assert parsed.aggregate_id == req_id
        assert parsed.payload.previous_status == RecoveryRequestStatus.ACCEPTED
        assert parsed.payload.new_status == RecoveryRequestStatus.COMPLETED

    def test_parse_event_unsupported_version(self) -> None:
        data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "report.created",
            "event_version": 2,  # Unsupported version
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "boomerang.test",
            "aggregate_id": str(uuid.uuid4()),
            "aggregate_type": "report",
            "payload": {},
        }
        with pytest.raises(UnsupportedEventVersionError) as exc:
            parse_event(data)
        assert "Unsupported event version: 2" in str(exc.value)

    def test_parse_event_unsupported_type(self) -> None:
        data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "unknown.future.event",
            "event_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "boomerang.test",
            "aggregate_id": str(uuid.uuid4()),
            "aggregate_type": "report",
            "payload": {},
        }
        with pytest.raises(UnsupportedEventTypeError) as exc:
            parse_event(data)
        assert "Unsupported event type: 'unknown.future.event'" in str(exc.value)

    def test_parse_event_malformed_json(self) -> None:
        with pytest.raises(EventParseError) as exc:
            parse_event("{malformed json")
        assert "Malformed JSON" in str(exc.value)

    def test_parse_event_invalid_root_type(self) -> None:
        with pytest.raises(EventParseError) as exc:
            parse_event(json.dumps(["not", "an", "object"]))
        assert "Root JSON value must be an object" in str(exc.value)

    def test_serialize_and_parse_report_updated_event(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        event = ReportUpdatedEvent(
            event_type=EventType.REPORT_UPDATED,
            occurred_at=now,
            producer="boomerang.report_service",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=ReportUpdatedPayload(
                report_id=report_id,
                updated_fields=["title", "latitude", "longitude"],
                title="Found Keys Near Main Gate",
                latitude=50.4501,
                longitude=30.5234,
                updated_at=now,
            ),
        )
        serialized = event.model_dump_json()
        parsed = parse_event(serialized)
        assert isinstance(parsed.payload, ReportUpdatedPayload)
        assert parsed.event_type == EventType.REPORT_UPDATED
        assert parsed.payload.title == "Found Keys Near Main Gate"
        assert parsed.payload.latitude == 50.4501
        assert parsed.payload.longitude == 30.5234

    def test_serialize_and_parse_report_resolved_event(self) -> None:
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        event = ReportResolvedEvent(
            event_type=EventType.REPORT_RESOLVED,
            occurred_at=now,
            producer="boomerang.report_service",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=ReportResolvedPayload(
                report_id=report_id,
                status=ReportStatus.RESOLVED,
                resolved_at=now,
                resolution_reason="Item recovered by owner",
            ),
        )
        parsed = parse_event(event.model_dump_json())
        assert isinstance(parsed.payload, ReportResolvedPayload)
        assert parsed.event_type == EventType.REPORT_RESOLVED
        assert parsed.payload.status == ReportStatus.RESOLVED
        assert parsed.payload.resolution_reason == "Item recovered by owner"

    def test_serialize_and_parse_recovery_request_created_event(self) -> None:
        req_id = uuid.uuid4()
        report_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        recipient_id = uuid.uuid4()
        now = datetime.now(UTC)

        event = RecoveryRequestCreatedEvent(
            event_type=EventType.RECOVERY_REQUEST_CREATED,
            occurred_at=now,
            producer="boomerang.recovery_service",
            aggregate_id=req_id,
            aggregate_type=AggregateType.RECOVERY_REQUEST,
            payload=RecoveryRequestCreatedPayload(
                recovery_request_id=req_id,
                report_id=report_id,
                requester_id=requester_id,
                recipient_id=recipient_id,
                status=RecoveryRequestStatus.PENDING,
                message="Hello, I have your item",
                created_at=now,
            ),
        )
        parsed = parse_event(event.model_dump_json())
        assert isinstance(parsed.payload, RecoveryRequestCreatedPayload)
        assert parsed.event_type == EventType.RECOVERY_REQUEST_CREATED
        assert parsed.payload.message == "Hello, I have your item"
        assert parsed.payload.status == RecoveryRequestStatus.PENDING

    def test_timezone_conversion_to_utc_for_aware_non_utc(self) -> None:
        # Non-UTC timezone offset (+05:30)
        from datetime import timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        ist_time = datetime(2026, 10, 18, 17, 30, 0, tzinfo=ist)

        report_id = uuid.uuid4()
        payload = ReportResolvedPayload(
            report_id=report_id,
            status=ReportStatus.RESOLVED,
            resolved_at=ist_time,
        )
        event = ReportResolvedEvent(
            event_type=EventType.REPORT_RESOLVED,
            occurred_at=ist_time,
            producer="boomerang.test",
            aggregate_id=report_id,
            aggregate_type=AggregateType.REPORT,
            payload=payload,
        )

        # Should be converted to UTC: 17:30 +05:30 -> 12:00 UTC
        assert event.occurred_at.tzinfo == UTC
        assert event.occurred_at.hour == 12
        assert event.occurred_at.minute == 0
        assert event.payload.resolved_at.tzinfo == UTC
        assert event.payload.resolved_at.hour == 12

    def test_rejection_of_empty_or_whitespace_title(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                created_by_user_id=uuid.uuid4(),
                type=ReportType.MISSING,
                category=ReportCategory.BAG,
                title="    ",  # Only whitespace
                description="Lost somewhere",
                latitude=50.45,
                longitude=30.52,
                event_time=now,
                created_at=now,
            )
        assert "title must not be empty or whitespace only" in str(exc.value)

    def test_rejection_of_negative_reward_in_updated_payload(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError) as exc:
            ReportUpdatedPayload(
                report_id=uuid.uuid4(),
                updated_fields=["reward_amount"],
                reward_amount=Decimal("-10.00"),  # Negative reward
                updated_at=now,
            )
        assert "reward_amount" in str(exc.value)

    def test_rejection_of_missing_required_payload_fields(self) -> None:
        with pytest.raises(ValidationError) as exc:
            ReportCreatedPayload(
                report_id=uuid.uuid4(),
                # missing created_by_user_id, type, category, etc.
            )  # type: ignore[call-arg]
        assert "created_by_user_id" in str(exc.value)
        assert "title" in str(exc.value)
