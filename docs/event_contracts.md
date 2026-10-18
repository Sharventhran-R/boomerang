# Boomerang Domain Event Contracts (Phase 7.1 Specification)

> **Status Notice**: Phase 7.1 defines versioned, validated event contracts and schema definitions in Python/Pydantic v2.
> Local Apache Kafka infrastructure and topic provisioning are established in Phase 7.2 (see [docs/kafka_setup.md](kafka_setup.md)).
> Transactional outbox persistence and live event publishing will be connected in subsequent phases.

---

## 1. What is a Domain Event in Boomerang?

In Boomerang, a **Domain Event** is an immutable record of a business fact that has already occurred within the system (e.g., a report was created, a recovery request was accepted, or a report was resolved).

Domain events are distinct from commands and database models:
- **Database Models** (`Report`, `RecoveryRequest`): Mutable representations of current system state stored in PostgreSQL.
- **Commands / API Requests** (`CreateReportRequest`): Intentions to alter system state, which can be rejected.
- **Domain Events** (`ReportCreatedEvent`): Historical facts that have already been validated, committed to PostgreSQL, and serialized for asynchronous downstream notification, matching, and analytics.

---

## 2. Common Event Envelope

Every Boomerang event is encapsulated in a generic, validated Pydantic v2 envelope (`EventEnvelope[PayloadT]`).

### Envelope Fields

| Field Name | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `event_id` | `uuid.UUID` | Yes (default UUIDv4) | Globally unique identifier for this specific event occurrence (idempotency key for consumers). |
| `event_type` | `EventType` | Yes | Namespaced identifier in dot-notation (e.g. `report.created`). |
| `event_version` | `int` | Yes (default `1`, `>= 1`) | Positive integer representing the schema contract version of the event. |
| `occurred_at` | `datetime` (UTC) | Yes | Timezone-aware UTC timestamp when the event occurred in the producer. |
| `producer` | `str` | Yes | Identifier of the producing subsystem (e.g. `boomerang.backend`, `boomerang.report_service`). |
| `aggregate_id` | `uuid.UUID` | Yes | Unique identifier of the aggregate root entity (report or recovery request). |
| `aggregate_type` | `AggregateType` | Yes | Domain aggregate type (`report` or `recovery_request`). |
| `correlation_id` | `uuid.UUID \| None` | No (default `None`) | Distributed tracing ID linking related operations across requests. |
| `payload` | `PayloadT` | Yes | Strongly-typed, validated payload specific to the `event_type`. |

### Envelope Invariants & Validation
- **Extra Fields Forbidden**: `model_config = ConfigDict(extra="forbid", frozen=True)` ensures unexpected or sensitive fields cannot be injected.
- **Namespace Consistency**: The envelope validates that `report.*` events have `aggregate_type == AggregateType.REPORT` and `recovery_request.*` events have `aggregate_type == AggregateType.RECOVERY_REQUEST`.
- **Entity Identity Synchronization**: The envelope validates that `aggregate_id` matches the entity ID specified within the payload (`payload.report_id` or `payload.recovery_request_id`).
- **UTC Timezone Enforcement**: All timestamps must be timezone-aware; naive datetimes are rejected with validation errors.

---

## 3. Initial Event Contracts (Version 1)

### 3.1. `report.created` (v1)

- **Purpose**: Emitted after a new Missing or Found report is committed to PostgreSQL.
- **Target Consumers**: Matching Engine (scans for potential cross-matches), Notification Dispatcher (notifies users within the area), Search Indexer.
- **Schema Payload**: `ReportCreatedPayload`

| Field | Type | Required | Justification |
| :--- | :--- | :--- | :--- |
| `report_id` | `uuid.UUID` | Yes | Entity identifier for the report. |
| `created_by_user_id` | `uuid.UUID` | Yes | Creator ID; required by Matching Engine to prevent self-matching and by Notification Service to attribute alerts. |
| `type` | `ReportType` | Yes | `MISSING` or `FOUND`; defines the matching direction. |
| `category` | `ReportCategory` | Yes | Item category (e.g. `ELECTRONICS`, `PET`); required for category-based match filtering. |
| `title` | `str` | Yes | Item headline summary; required for text matching and alert previews. |
| `description` | `str` | Yes | Detailed narrative; required for text matching. |
| `latitude` | `float` | Yes | Incident latitude coordinate; justified because the Matching Engine and nearby alert engines require spatial coordinates. |
| `longitude` | `float` | Yes | Incident longitude coordinate; justified for geospatial PostGIS matching. |
| `event_time` | `datetime` (UTC) | Yes | Incident timestamp; required for temporal match evaluation. |
| `reward_amount` | `Decimal \| None` | No | Optional monetary reward; strictly restricted to `MISSING` reports (`None` for `FOUND`). |
| `status` | `ReportStatus` | Yes | Initial status; must be `ACTIVE`. |
| `created_at` | `datetime` (UTC) | Yes | Record creation timestamp. |

---

### 3.2. `report.updated` (v1)

- **Purpose**: Emitted when mutable attributes of an active report are modified.
- **Target Consumers**: Matching Engine (re-evaluates or updates candidate matches), Search Indexer.
- **Schema Payload**: `ReportUpdatedPayload`

| Field | Type | Required | Justification |
| :--- | :--- | :--- | :--- |
| `report_id` | `uuid.UUID` | Yes | Entity identifier of the updated report. |
| `updated_fields` | `list[str]` | Yes | Explicit list of attribute names modified in this transaction (e.g. `["title", "description"]`). |
| `title` | `str \| None` | No | Updated title if changed. |
| `description` | `str \| None` | No | Updated description if changed. |
| `category` | `ReportCategory \| None` | No | Updated category if changed. |
| `latitude` | `float \| None` | No | Updated latitude coordinate if changed. |
| `longitude` | `float \| None` | No | Updated longitude coordinate if changed. |
| `event_time` | `datetime \| None` | No | Updated incident timestamp if changed. |
| `reward_amount` | `Decimal \| None` | No | Updated reward amount if changed. |
| `status` | `ReportStatus \| None` | No | Updated status if changed. |
| `updated_at` | `datetime` (UTC) | Yes | Timestamp when the update transaction occurred. |

*Rule*: `latitude` and `longitude` must be updated together as a coordinate pair.

---

### 3.3. `report.resolved` (v1)

- **Purpose**: Emitted when a report's lifecycle status transitions to `RESOLVED`.
- **Target Consumers**: Matching Engine (deactivates candidate matches), Search Indexer (delists report), Analytics.
- **Schema Payload**: `ReportResolvedPayload`

| Field | Type | Required | Justification |
| :--- | :--- | :--- | :--- |
| `report_id` | `uuid.UUID` | Yes | Entity identifier of the resolved report. |
| `status` | `ReportStatus` | Yes | Must be `RESOLVED`. |
| `resolved_at` | `datetime` (UTC) | Yes | Timezone-aware resolution timestamp. |
| `resolution_reason` | `str \| None` | No | Contextual reason (e.g. `'recovery_completed'`, `'manual_resolution'`). |
| `associated_recovery_request_id` | `uuid.UUID \| None` | No | ID of completed recovery request if resolved via recovery workflow; `None` if resolved independently. |

*Domain Meaning & Privacy Decision*:
- In Boomerang, a report may be resolved either through an in-app recovery request completion OR by the user resolving it independently. A `report.resolved` event does **not** assume recovery completion unless `associated_recovery_request_id` is present.
- **Geographic coordinates and location data are explicitly omitted** because downstream de-indexing and analytics consumers only require aggregate identity and resolution metadata.

---

### 3.4. `recovery_request.created` (v1)

- **Purpose**: Emitted when an operator initiates a recovery/contact request on an active report.
- **Target Consumers**: Notification Dispatcher (alerts the report creator/recipient of incoming request), Audit Logger.
- **Schema Payload**: `RecoveryRequestCreatedPayload`

| Field | Type | Required | Justification |
| :--- | :--- | :--- | :--- |
| `recovery_request_id` | `uuid.UUID` | Yes | Entity identifier of the request. |
| `report_id` | `uuid.UUID` | Yes | Associated report identifier. |
| `requester_id` | `uuid.UUID` | Yes | User ID of the operator initiating recovery. |
| `recipient_id` | `uuid.UUID` | Yes | User ID of the report creator receiving the request. |
| `status` | `RecoveryRequestStatus` | Yes | Initial status; must be `PENDING`. |
| `message` | `str \| None` | No | Optional introductory note from the requester. |
| `created_at` | `datetime` (UTC) | Yes | Timezone-aware creation timestamp. |

*Privacy Decisions*:
- Does **not** include user email, passwords, session tokens, or personal identifiers.
- Does **not** include verification proof or answers.

---

### 3.5. `recovery_request.updated` (v1)

- **Purpose**: Emitted when a recovery request transitions lifecycle state (`ACCEPTED`, `REJECTED`, `CANCELLED`, `COMPLETED`).
- **Target Consumers**: Notification Dispatcher (alerts parties of decision), Report Service (triggers report resolution upon `COMPLETED`), Audit Logger.
- **Schema Payload**: `RecoveryRequestUpdatedPayload`

| Field | Type | Required | Justification |
| :--- | :--- | :--- | :--- |
| `recovery_request_id` | `uuid.UUID` | Yes | Entity identifier. |
| `report_id` | `uuid.UUID` | Yes | Target report identifier. |
| `requester_id` | `uuid.UUID` | Yes | Requester user ID. |
| `recipient_id` | `uuid.UUID` | Yes | Recipient user ID. |
| `previous_status` | `RecoveryRequestStatus` | Yes | State prior to transition. |
| `new_status` | `RecoveryRequestStatus` | Yes | State after transition. |
| `updated_at` | `datetime` (UTC) | Yes | Transition timestamp. |

*Privacy Decisions*:
- **`verification_response` is strictly excluded**: In Boomerang, verification responses contain private claimant proof, serial numbers, or answers to identification questions. Exposing this on an event bus would leak private verification data. Downstream notification consumers only need the status transition (`ACCEPTED`, `REJECTED`, `COMPLETED`), not the secret proof text.

---

## 4. Versioning and Compatibility Rules

### 4.1. Version Representation
Event versions are represented by a positive integer in the envelope (`event_version: int = 1`).
Major revisions increment this version (`1` -> `2`).

### 4.2. Backward-Compatible Changes
A change is backward-compatible if existing consumers continue to process the event without modification.
- **Allowed in Current Version (v1)**:
  - Adding a new **optional field** (`field_name: str | None = None`) with a default value of `None`.
  - Adding a new, distinct `event_type` (e.g. `report.expired`).
- **Strict Requirement**: Existing required fields cannot be removed, renamed, or have their types narrowed within version 1.

### 4.3. Breaking Changes Requiring a New Event Version
A breaking change requires bumping `event_version` to `2` (e.g. `event_version: 2`) and defining a versioned payload class (e.g. `ReportCreatedPayloadV2`):
- Removing an existing field.
- Renaming an existing field.
- Changing a field's data type (e.g., `float` to `int`, or scalar to object).
- Making a previously optional field required.
- Modifying enum value semantics or removing an enum option.
- Restructuring coordinates from flat floats (`latitude`, `longitude`) to GeoJSON.

### 4.4. Production Immutability (Why Events Must Never Be Silently Altered)
In distributed event-driven systems, events are written to durable commit logs (Kafka topics) and consumed asynchronously by decoupled services.
- **Silent changes cause deserialization failures**: If an existing contract is modified without a version bump, downstream consumers reading older events or newer events will crash with schema validation errors.
- **Replayability**: Stored events may be replayed years later for audits, disaster recovery, or analytics recalculations. Historical events must remain decodable by their original schema version.

### 4.5. Consumer Strategy for Unsupported Versions or Types
Downstream consumers using `parse_event` must handle unsupported events defensively:
1. **Unsupported Version (`UnsupportedEventVersionError`)**: The consumer logs a warning with event metadata and routes the message to a Dead Letter Queue (DLQ) for operator inspection, without crashing the consumer worker loop.
2. **Unsupported Event Type (`UnsupportedEventTypeError`)**: If an event type is unrecognized (e.g., produced by a newer service), the consumer logs a debug entry and safely acknowledges/skips the event if it does not subscribe to that topic partition.

---

## 5. Privacy & Sensitive-Data Rules

1. **Zero Credential Exposure**: Passwords, password hashes, refresh token hashes, and JWT signatures must NEVER enter any event envelope or payload.
2. **Exclusion of Recovery Verification Details**: `verification_response` text and claim evidence must never be included in events.
3. **Location Privacy**: Incident coordinates (`latitude`, `longitude`) are included ONLY when strictly justified by the event's consumers (e.g. `report.created` and `report.updated` for PostGIS radius matching). Events that do not require spatial calculations (e.g. `report.resolved`, `recovery_request.*`) omit location data.
4. **Strict Schema Constraints**: All schemas specify `extra="forbid"`, which causes Pydantic to immediately reject any payload containing unmodeled fields. This prevents sensitive database columns from accidentally leaking into events during object mapping.

---

## 6. Roadmap: How Later Phases Will Use These Contracts

- **Phase 7.2 (Transactional Outbox)**: Will implement an `outbox_events` table in PostgreSQL. When reports or recovery requests are saved in database transactions, an event envelope JSON is written to `outbox_events` in the same atomic commit.
- **Phase 7.3 (Kafka Integration)**: A background relay process will poll `outbox_events`, deserialize using `parse_event`, and publish to partitioned Kafka topics (`reports.events`, `recovery.events`).
- **Phase 8 (Matching Engine)**: Will subscribe to `report.created` and `report.updated` events from Kafka to trigger geospatial matching against opposing reports.
- **Phase 9 (Notifications)**: Will subscribe to `report.created` (nearby alerts) and `recovery_request.*` events to deliver push and email notifications.
