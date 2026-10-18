# Boomerang — Reliable Event Consumer Foundation (Phase 7.4)

This document specifies the architecture, guarantees, operational workflows, and failure recovery procedures for Boomerang's Event Consumer Foundation implemented in Phase 7.4.

---

## 1. Architectural Overview & Responsibilities

In Boomerang's event-driven architecture, domain state changes (e.g., reports created/updated/resolved, recovery requests initiated/accepted/completed) are committed to PostgreSQL, published to Apache Kafka via the Transactional Outbox (Phase 7.3), and streamed to asynchronous consumers on `boomerang.domain.events`.

Phase 7.4 establishes a **reusable, resilient consumer pipeline** designed to support upcoming downstream subsystems:
- **Phase 8 (Matching Engine)**: Consumes `report.created` and `report.updated` to evaluate geospatial cross-matches against opposing reports.
- **Phase 9 (Notification Service)**: Consumes `report.created` (nearby incident alerts) and `recovery_request.*` events (handover contact updates).

```
                      [ Apache Kafka: boomerang.domain.events ]
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ EventConsumer Pipeline (Per-Partition Sequential Processing)                │
│                                                                             │
│  1. Receive Record: topic, partition, offset, key, value                    │
│  2. Parse & Validate Envelope: Pydantic v2 schema + version check           │
│     ├─ Malformed / Unsupported Version ──► QUARANTINE & Commit Offset       │
│     └─ Valid Envelope ──────────────────────────────────────────────┐       │
│                                                                     ▼       │
│  3. Idempotency Check (SELECT status FROM consumer_events)                  │
│     ├─ Already COMPLETED ────────────────► SKIP Handler & Commit Offset     │
│     └─ Not Completed ───────────────────────────────────────────────┐       │
│                                                                     ▼       │
│  4. Atomic DB Transaction (session.begin()):                                │
│     ├─ Invoke Typed Handlers: handler.handle(event, session)                │
│     ├─ Insert Idempotency Record: status = COMPLETED                        │
│     └─ COMMIT DATABASE TRANSACTION (atomic state + idempotency)             │
│                                                                     │       │
│  5. On DB Commit: Commit Kafka Offset (offset + 1)                          │
│                                                                     │       │
│  6. On Transient Handler Error: Bounded Exponential Backoff + Jitter Retry   │
│     └─ Retries Exhausted ───────────────► QUARANTINE & Commit Offset        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Event Lifecycle & Status State Machine

Every event processed by a named consumer instance transitions through the `consumer_events` table:

| Status | Meaning |
| :--- | :--- |
| `PROCESSING` | Transient state while worker is actively running handlers. |
| `COMPLETED` | Handlers and idempotency record committed durably to PostgreSQL; Kafka offset acknowledged. |
| `FAILED` | Intermediate failure state during active retry attempts. |
| `QUARANTINED` | Permanent poison message, schema version mismatch, or retry exhaustion. Offset acknowledged to unblock partition. Preserved for operator diagnosis and replay. |

```
              ┌────────────────────┐
              │   Kafka Message    │
              └─────────┬──────────┘
                        │
                        ▼
            [ Envelope Validation ]
           /                        \
    (Invalid / Bad Version)      (Valid Envelope)
         /                            \
        ▼                              ▼
 ┌─────────────┐             [ Idempotency Check ]
 │ QUARANTINED │            /                     \
 └─────────────┘     (Already Done)          (Not Done)
       ▲                   /                      \
       │         ┌───────────────────┐    ┌────────────────────┐
       │         │ DUPLICATE_SKIPPED │    │  Execute Handlers  │
       │         │ (Commit Offset)   │    │  (DB Transaction)  │
       │         └───────────────────┘    └─────────┬──────────┘
       │                                            │
 (Max Retries)                              (Commit Succeeded)
       │                                            │
       │                                            ▼
 ┌─────────────┐                          ┌────────────────────┐
 │ Retry Loop  │ ◄─── (Transient Error)   │     COMPLETED      │
 └─────────────┘                          │  (Commit Offset)   │
                                          └────────────────────┘
```

### 2.1 Inbound Message Classification & Action Policy

Every Kafka record is classified into one of five explicit categories with deterministic database and offset outcomes:

| Category | Definition / Example | Processing Action | Database State | Offset Committed? |
| :--- | :--- | :--- | :--- | :--- |
| **1. Malformed JSON** | Byte payload fails UTF-8 or JSON decoding. | Quarantined immediately. | `status = QUARANTINED`, `error_category = PARSE_ERROR`. Raw payload omitted. | **Yes** (`offset + 1`) to prevent partition stall. |
| **2. Unsupported Version** | `event_version != 1` (e.g. future v2 or unknown version). | Quarantined immediately without handler dispatch. | `status = QUARANTINED`, `error_category = UNSUPPORTED_VERSION`. Envelope preserved. | **Yes** (`offset + 1`) to unblock subsequent messages. |
| **3. Unknown Event Type** | `event_type` is not recognized by system contracts (e.g. `billing.charged`). | Quarantined for operator inspection; never silently dropped. | `status = QUARANTINED`, `error_category = UNSUPPORTED_TYPE`. Valid payload preserved. | **Yes** (`offset + 1`) to preserve partition progress. |
| **4. Known Event, No Handler** | Valid type (e.g. `report.created`), but this consumer has not registered a handler. | Acknowledged without running business logic. | `status = COMPLETED`, `retry_count = 0` (so future redeliveries fast-skip). | **Yes** (`offset + 1`). |
| **5. Duplicate Delivery** | Event with same `(consumer_name, event_id)` already `COMPLETED`. | Fast-path idempotency skip; handler is not invoked. | Retains existing `COMPLETED` record. | **Yes** (`offset + 1`). |

---

## 3. Delivery Guarantees & Durable Idempotency

### 3.1 Delivery Guarantee: At-Least-Once
- Transport between Kafka and the consumer is **at-least-once**.
- In the event of a worker crash, network interruption, or rebalance before the Kafka offset commit, Kafka will redeliver the message upon restart.
- **Do not assume exactly-once delivery across transport.** The consumer achieves **effectively-once** execution through database-backed idempotency.

### 3.2 Database Idempotency Barrier
The table `consumer_events` enforces a PostgreSQL unique constraint:
```sql
CONSTRAINT uq_consumer_events_consumer_event UNIQUE (consumer_name, event_id)
```
- Each named consumer (e.g. `matching_engine`, `notification_service`) tracks its own independent processing record.
- If an event has already reached `status = COMPLETED` for that consumer, subsequent deliveries skip handler invocation entirely and immediately advance the Kafka offset.
- **Concurrent Safety:** If two consumer instances receive duplicate messages concurrently, PostgreSQL's unique constraint causes the lagging transaction to raise an `IntegrityError` and roll back completely, ensuring the handler's business logic is never applied twice.

### 3.3 Atomic State Mutations
Handler business mutations and the `ConsumerEvent` idempotency record share the active `session: AsyncSession` transaction:
1. `async with session.begin():` starts a PostgreSQL transaction.
2. The handler executes mutations (e.g. writing match candidates or updating entity states).
3. The consumer inserts `ConsumerEvent(status=COMPLETED)`.
4. PostgreSQL commits both atomically. If an exception occurs, all database changes roll back together.
5. Only after the database commit succeeds does the consumer advance and commit the Kafka offset.

### 3.4 External Side Effects
If a future handler executes non-database external side effects (e.g. external SMS or push notification HTTP gateways), database transactions cannot guarantee external atomicity. External side effects must implement their own idempotency keys or rely on a transactional outbox.

---

## 4. Kafka Offset and Acknowledgement Semantics

### 4.1 Manual Offset Commits (`enable_auto_commit=False`)
Automatic commits are strictly disabled. The consumer manages commits explicitly using `consumer.commit({TopicPartition: OffsetAndMetadata(safe_offset + 1, "")})`.

### 4.2 Contiguous Monotonic Offset Tracking (`PartitionOffsetTracker`)
To guarantee that a partition's committed offset **never advances beyond an earlier message whose outcome is not yet durable**, the consumer incorporates a dedicated per-partition offset tracker:
- When a message is fetched, its offset is registered as `in_flight` for its `TopicPartition`.
- When processing completes (whether `COMPLETED` or `QUARANTINED`), the offset is marked `durable`.
- An offset $S$ is safe to commit if and only if **no earlier offset $Y \le S$ is currently in-flight on that partition**:
  $$\forall Y \in \text{in\_flight}(tp): Y > S$$
- If a later message completes before an earlier message in the same partition, the later offset commit is deferred until the earlier message reaches a durable outcome.

### 4.3 Partition Isolation
Offset tracking is strictly keyed by `TopicPartition(topic, partition)`. Processing progress on partition 0 never triggers or blocks offset commits on partition 1.

### 4.4 Crash & Rebalance Safety
If a consumer worker crashes or rebalances mid-batch:
- In-flight messages that did not commit to PostgreSQL have not advanced their Kafka offset.
- Upon restart, Kafka redelivers starting at the lowest uncommitted offset.
- Messages that committed to the database before the crash are recognized by the idempotency barrier, skipped safely, and acknowledged.

## 5. Retry, Quarantine, and Replay Runbook

### 5.1 Retry Policy
Transient handler failures are retried with exponential backoff and randomized full jitter:
$$\text{Delay} = \text{random.uniform}(0.5 \times \text{raw}, \text{raw}) \quad \text{where} \quad \text{raw} = \min(\text{max\_delay}, \text{initial\_delay} \times \text{multiplier}^{\text{attempt}-1})$$

Configurable in `app/core/config.py`:
- `CONSUMER_MAX_RETRIES`: `3`
- `CONSUMER_INITIAL_RETRY_DELAY_SECONDS`: `0.5`
- `CONSUMER_MAX_RETRY_DELAY_SECONDS`: `30.0`
- `CONSUMER_BACKOFF_MULTIPLIER`: `2.0`

### 5.2 Quarantine Inspection
To inspect quarantined events in PostgreSQL:
```sql
SELECT id, consumer_name, event_id, event_type, error_category, last_error, topic, partition, offset, created_at
FROM consumer_events
WHERE status = 'QUARANTINED';
```

### 5.3 CLI Operational Commands

The runner script `scripts/run_event_consumer.py` provides operational control:

```powershell
# 1. Check consumer backlog and quarantine counts
.venv\Scripts\python.exe scripts/run_event_consumer.py --consumer-name matching_engine --status

# 2. Run bounded processing pass (e.g. cron or batch verification)
.venv\Scripts\python.exe scripts/run_event_consumer.py --consumer-name matching_engine --once --max-messages 50

# 3. Replay a specific quarantined event after fixing an upstream bug
.venv\Scripts\python.exe scripts/run_event_consumer.py --consumer-name matching_engine --replay <EVENT_UUID>

# 4. Replay all quarantined events for this consumer
.venv\Scripts\python.exe scripts/run_event_consumer.py --consumer-name matching_engine --replay-quarantined

# 5. Run continuous daemon worker
.venv\Scripts\python.exe scripts/run_event_consumer.py --consumer-name matching_engine
```

Replay is an **explicit operator action**: it re-parses the preserved event payload, re-runs the registered handlers in an atomic database transaction, and transitions the status to `COMPLETED`.

---

## 6. Privacy & Sensitive-Data Safeguards

1. Diagnostic error messages (`last_error`) are bounded to 1,000 characters and scrubbed of credential keywords (`password`, `secret`, `token`, `key`).
2. Payload retention in `consumer_events.payload` stores the validated event envelope, which inherits Phase 7.1's strict privacy rules (`extra="forbid"`, exclusion of `verification_response`, exclusion of passwords and tokens).
3. Raw database connection strings or secrets are never logged.

---

## 7. Verification & Testing

Run the consumer test suite:
```powershell
.venv\Scripts\python.exe -m pytest tests/test_event_consumer.py -v
```
Run the full backend test suite:
```powershell
.venv\Scripts\python.exe -m pytest -q
```
