# Boomerang — Transactional Outbox & Reliable Event Publishing (Phase 7.3)

This document specifies the architecture, guarantees, operational workflows, and failure recovery procedures for Boomerang's Transactional Outbox pattern implemented in Phase 7.3.

---

## 1. Architectural Overview & Rationale

In distributed systems, publishing domain events directly to a message broker (such as Apache Kafka) within an HTTP API request handler introduces the **dual-write problem**:
- If the database commit succeeds but the Kafka publish fails (network timeout, broker restart), downstream consumers miss critical business events.
- If Kafka publishing succeeds but the database transaction rolls back (constraint violation, conflict), consumers act on phantom data that never existed.

Boomerang eliminates this failure mode by implementing the **Transactional Outbox Pattern**:
1. When a report or recovery request is created, updated, or resolved, the domain state change and its corresponding `EventEnvelope` are saved into the `outbox_events` table **in the same atomic PostgreSQL transaction**.
2. If the domain transaction succeeds, the event is guaranteed to be durably persisted. If the domain transaction fails, the outbox record rolls back with it.
3. A separate, asynchronous **Outbox Dispatcher** worker reads committed outbox rows and reliably publishes them to the Apache Kafka topic `boomerang.domain.events`.

```
[ Client Request ]
       │
       ▼
┌───────────────────────────────────────────────────────────┐
│ FastAPI Service Layer (Atomic PostgreSQL Transaction)    │
│                                                           │
│  1. INSERT / UPDATE reports / recovery_requests           │
│  2. INSERT outbox_events (Status: PENDING)                │
│  3. COMMIT TRANSACTION                                    │
└───────────────────────────────────────────────────────────┘
       │
       ▼ (Durably Stored in PostgreSQL)
┌───────────────────────────────────────────────────────────┐
│ Outbox Dispatcher Worker (Separately Runnable)            │
│                                                           │
│  1. Claim rows: SELECT ... FOR UPDATE SKIP LOCKED         │
│  2. Set Status: PROCESSING & COMMIT lock release          │
│  3. Await Kafka publish: producer.send_and_wait(...)     │
│  4. On ACK: Set Status: PUBLISHED                         │
│  5. On Error: Increment retry_count, Backoff with Jitter  │
└───────────────────────────────────────────────────────────┘
       │
       ▼
[ Apache Kafka: boomerang.domain.events ]
```

---

## 2. Outbox Schema & Status Transitions

### 2.1 Table: `outbox_events`

The `outbox_events` table records all pending, processing, published, and failed domain events:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `UUID (PK)` | Internal primary key for the outbox row. |
| `event_id` | `UUID (Unique)` | Business idempotency key from `EventEnvelope` (used by consumers to deduplicate). |
| `event_type` | `VARCHAR(100)` | Namespaced event type (e.g. `report.created`, `report.resolved`). |
| `event_version` | `INTEGER` | Schema contract version (default: 1). |
| `aggregate_type`| `VARCHAR(50)` | Aggregate entity classification (`report` or `recovery_request`). |
| `aggregate_id` | `UUID` | ID of the aggregate root (used as Kafka partition message key). |
| `topic` | `VARCHAR(255)` | Target Kafka topic (`boomerang.domain.events`). |
| `payload` | `JSONB` | Complete serialized `EventEnvelope` JSON adhering to Phase 7.1 contracts. |
| `status` | `outbox_status_enum`| `PENDING`, `PROCESSING`, `PUBLISHED`, `FAILED`, `DEAD_LETTER`. |
| `retry_count` | `INTEGER` | Number of failed delivery attempts (default: 0). |
| `max_retries` | `INTEGER` | Maximum delivery attempts before moving to `DEAD_LETTER` (default: 5). |
| `occurred_at` | `TIMESTAMPTZ` | Timestamp when the domain event occurred. |
| `created_at` | `TIMESTAMPTZ` | Timestamp when outbox row was inserted in PostgreSQL. |
| `updated_at` | `TIMESTAMPTZ` | Timestamp of last status change or attempt. |
| `next_retry_at` | `TIMESTAMPTZ` | Earliest time this row is eligible for processing/retry. |
| `published_at` | `TIMESTAMPTZ` | Timestamp when Kafka acknowledged receipt (nullable). |
| `last_error` | `TEXT` | Bounded error message from the most recent failed attempt (nullable). |

### 2.2 Database Indexes

- `ix_outbox_events_status_next_retry` on `(status, next_retry_at, created_at)`: Optimizes polling for eligible rows.
- `ix_outbox_events_aggregate` on `(aggregate_type, aggregate_id)`: Enables operational inspection of entity event history.
- `ix_outbox_events_event_id` on `event_id` (Unique): Guarantees global event uniqueness.

### 2.3 Status State Machine

```
              ┌─────────────┐
              │   PENDING   │ ◄────────────────────────┐
              └──────┬──────┘                          │
                     │ (Claimed by Worker)             │
                     ▼                                 │
              ┌─────────────┐                          │
              │ PROCESSING  │                          │
              └──────┬──────┘                          │
         ┌───────────┴───────────┐                     │
 (Kafka ACK) │                   │ (Kafka Error)       │
             ▼                   ▼                     │
      ┌─────────────┐     ┌─────────────┐              │
      │  PUBLISHED  │     │   FAILED    │              │
      └─────────────┘     └──────┬──────┘              │
                                 │                     │
                    (retry_count │                     │ (Manual Replay)
                   >= max_retries│                     │
                                 ▼                     │
                          ┌─────────────┐              │
                          │ DEAD_LETTER │ ─────────────┘
                          └─────────────┘
```

---

## 3. Delivery Guarantees & Semantics

### 3.1 At-Least-Once Delivery
The transactional outbox guarantees **at-least-once delivery**:
- Every committed domain change produces an outbox event that will be delivered to Kafka.
- In rare failure scenarios (e.g., Kafka acknowledges message delivery, but the worker process dies or loses network connectivity before committing `status = PUBLISHED`), the worker upon restart will re-send the message.
- **Do not assume exactly-once delivery.** Downstream consumers **must** implement deduplication using `event_id`.

### 3.2 Short Database Transactions & Non-Blocking I/O
Database transactions are kept short and never held open during Kafka network I/O:
1. **Transaction 1 (Claiming)**: Claims eligible rows with `SELECT ... FOR UPDATE SKIP LOCKED`, sets `status = PROCESSING`, and commits immediately to release table/row locks.
2. **External I/O (Kafka)**: Awaits `producer.send_and_wait(...)` outside of any database transaction.
3. **Transaction 2 (Resolution)**: Updates status to `PUBLISHED` or `FAILED` in a short dedicated commit.

### 3.3 Partition Ordering
Kafka message keys are set to `str(event.aggregate_id).encode("utf-8")`. All events belonging to the same Report or RecoveryRequest are deterministically routed to the same Kafka partition, preserving chronological ordering for downstream consumers.

### 3.4 Bounded Exponential Backoff with Jitter
Failed delivery attempts are retried with exponential backoff and randomized full jitter to prevent thundering-herd effects on broker recovery:
$$\text{Delay} = \text{random.uniform}(0.5 \times \text{raw}, \text{raw}) \quad \text{where} \quad \text{raw} = \min(\text{max\_delay}, \text{initial\_delay} \times \text{multiplier}^{\text{attempt}-1})$$

Configurable parameters in `app/core/config.py`:
- `OUTBOX_INITIAL_RETRY_DELAY_SECONDS`: `1.0`
- `OUTBOX_MAX_RETRY_DELAY_SECONDS`: `60.0`
- `OUTBOX_BACKOFF_MULTIPLIER`: `2.0`
- `OUTBOX_MAX_RETRIES`: `5`
- `OUTBOX_STALE_PROCESSING_SECONDS`: `300.0` (reclaims rows stuck in `PROCESSING` if a worker crashes mid-batch)

---

## 4. Operational Runbook

### 4.1 Running the Outbox Dispatcher

The dispatcher is runnable standalone as a long-running daemon worker:

```powershell
# Continuous background polling loop
.venv\Scripts\python.exe scripts/run_outbox_dispatcher.py

# Optional parameters:
.venv\Scripts\python.exe scripts/run_outbox_dispatcher.py --poll-interval 1.0 --batch-size 50
```

### 4.2 Inspecting Outbox Backlog Status

To check the distribution of events in the outbox table:

```powershell
.venv\Scripts\python.exe scripts/run_outbox_dispatcher.py --status
```

Sample output:
```text
==================================================
Boomerang Outbox Backlog Status
==================================================
  PENDING        : 0
  PROCESSING     : 0
  PUBLISHED      : 42
  FAILED         : 0
  DEAD_LETTER    : 0
==================================================
```

### 4.3 Running a Single Batch (Cron / CLI Mode)

To process available pending events in a single batch and exit immediately:

```powershell
.venv\Scripts\python.exe scripts/run_outbox_dispatcher.py --once
```

### 4.4 Recovering and Replaying Dead-Letter Events

When an event exceeds `OUTBOX_MAX_RETRIES` (e.g. poison message or persistent broker misconfiguration), it transitions to `DEAD_LETTER` status and is preserved in the database for inspection.

To inspect dead-letter events:
```sql
SELECT id, event_id, event_type, retry_count, last_error, created_at 
FROM outbox_events 
WHERE status = 'DEAD_LETTER';
```

After fixing the underlying issue (e.g. Kafka ACLs, schema migration), re-enqueue all dead-letter events:
```powershell
.venv\Scripts\python.exe scripts/run_outbox_dispatcher.py --replay-dead-letters
```

This resets their status to `PENDING`, sets `retry_count = 0`, and clears `last_error`, while preserving the original `event_id` to maintain consumer deduplication guarantees.

---

## 5. Verification & Testing

Run all unit, integration, and real Kafka outbox tests:

```powershell
# Run the complete outbox test suite
.venv\Scripts\python.exe -m pytest tests/test_outbox.py -v

# Run full backend test suite
.venv\Scripts\python.exe -m pytest -q
```
