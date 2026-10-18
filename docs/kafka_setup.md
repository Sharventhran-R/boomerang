# Boomerang — Local Kafka Infrastructure Guide (Phase 7.2)

This document provides complete instructions for running, inspecting, testing, and troubleshooting the local Apache Kafka deployment for Boomerang.

---

## 1. Architecture & Overview

Boomerang uses Apache Kafka for asynchronous domain event streaming (e.g., report publication, status updates, matching, and notification triggers).

For local development:
- **Engine**: Apache Kafka 3.8.0.
- **Mode**: Single-node **KRaft** (Kafka Raft metadata mode). ZooKeeper is **not** used or required.
- **Roles**: Combined `broker,controller` node (`KAFKA_NODE_ID: 1`).
- **Cluster ID**: Deterministic local development cluster UUID (`4L622nShTUiAnsYh0-AZSQ`).
- **Storage**: Docker named volume `kafka_data` mounted at `/var/lib/kafka/data` for persistent broker state.
- **Topic Creation**: Automated via `kafka-init` service that provisions `boomerang.domain.events` with 3 partitions and replication factor 1 upon broker health readiness.

---

## 2. Network & Listener Topology

Kafka requires dual listeners to allow seamless connectivity from both inside the Docker network and from local development tools running on the host machine:

| Listener Name | Internal / External | Bind Address | Advertised Address | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `PLAINTEXT` | Internal Docker Network | `0.0.0.0:29092` | `kafka:29092` | Inter-container communication (e.g. `kafka-init`, future containerized backend). |
| `PLAINTEXT_HOST` | External Host | `0.0.0.0:9092` | `localhost:9092` | Host applications (FastAPI backend running locally, pytest, CLI scripts). |
| `CONTROLLER` | Internal Controller | `0.0.0.0:9093` | N/A | KRaft metadata quorum communication. |

---

## 3. Configuration & Environment Variables

Kafka settings are managed via environment variables defined in `.env` (derived from `.env.example`) and validated in `app/core/config.py`:

```dotenv
# Kafka Local Development Configuration
KAFKA_BOOTSTRAP_SERVERS="localhost:9092"
KAFKA_DOMAIN_EVENTS_TOPIC="boomerang.domain.events"
KAFKA_PORT=9092
```

In `app/core/config.py`:
- `KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"`
- `KAFKA_DOMAIN_EVENTS_TOPIC: str = "boomerang.domain.events"`

> [!NOTE]
> If running the backend inside a Docker container attached to the Docker Compose network, set `KAFKA_BOOTSTRAP_SERVERS=kafka:29092`. When running on the host machine via `.venv`, keep `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`.

---

## 4. Operational Runbook

### 4.1 Starting Kafka

Start the database, MinIO, Kafka, and the topic initialization service:

```powershell
# Start all infrastructure services in the background
docker compose up -d

# Or start Kafka and its initializer specifically
docker compose up -d kafka kafka-init
```

The `kafka` container will start, initialize KRaft metadata, and become healthy once the broker API responds. The `kafka-init` service will wait for `kafka` to be healthy, ensure `boomerang.domain.events` exists with 3 partitions, and cleanly exit with code 0.

### 4.2 Checking Health and Container Status

Verify that the containers are healthy:

```powershell
docker compose ps
```

Expected status:
- `tracker_kafka`: `Up (healthy)`
- `tracker_kafka_init`: `Exited (0)`

Verify the broker API directly from inside the container:

```powershell
docker exec tracker_kafka /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092
```

### 4.3 Inspecting Topics and Partitions

List all topics:

```powershell
docker exec tracker_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

Describe `boomerang.domain.events`:

```powershell
docker exec tracker_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic boomerang.domain.events
```

Expected output:
```text
Topic: boomerang.domain.events	TopicId: ...	PartitionCount: 3	ReplicationFactor: 1	Configs: ...
	Topic: boomerang.domain.events	Partition: 0	Leader: 1	Replicas: 1	Isr: 1
	Topic: boomerang.domain.events	Partition: 1	Leader: 1	Replicas: 1	Isr: 1
	Topic: boomerang.domain.events	Partition: 2	Leader: 1	Replicas: 1	Isr: 1
```

### 4.4 Viewing Broker Logs

Stream logs from the Kafka broker:

```powershell
docker compose logs -f kafka
```

### 4.5 Stopping Kafka

Stop the Kafka broker while retaining volume data:

```powershell
# Stop Kafka service only
docker compose stop kafka

# Stop all compose services
docker compose stop
```

### 4.6 Resetting Persistent State (Clean Slate)

If you need to wipe all Kafka topics, offsets, and broker logs:

```powershell
# Stop and remove containers and volumes
docker compose down -v

# Re-create and start fresh
docker compose up -d
```

---

## 5. Development Smoke Testing

Boomerang includes a development-only smoke test that verifies end-to-end publish and consume roundtrip on `boomerang.domain.events` using synthetic probe payloads. It does **not** publish real report events.

### 5.1 CLI Smoke Test Script

Run the standalone CLI smoke test:

```powershell
.venv\Scripts\python.exe scripts/kafka_smoke_test.py
```

Optional CLI parameters:
```powershell
.venv\Scripts\python.exe scripts/kafka_smoke_test.py --bootstrap-servers localhost:9092 --topic boomerang.domain.events --timeout 15.0
```

Sample output:
```text
============================================================
Boomerang Kafka Smoke Test (Phase 7.2)
============================================================
Bootstrap Servers : localhost:9092
Topic             : boomerang.domain.events
Consumer Group    : smoke-test-8b9297ad
Probe ID          : c1afd84c-299b-41b6-8401-4af82907a689
------------------------------------------------------------
[1/4] Starting Kafka consumer...
[2/4] Starting Kafka producer...
[3/4] Publishing synthetic probe message to 'boomerang.domain.events'...
      Published -> Partition: 1, Offset: 1
[4/4] Awaiting consumption of probe 'c1afd84c-299b-41b6-8401-4af82907a689' (timeout: 15.0s)...
------------------------------------------------------------
[PASS] Smoke Test PASSED!
  Received Partition : 1
  Received Offset    : 1
  Roundtrip Latency  : 2.0 ms
============================================================
Stopping producer and consumer...
```

### 5.2 Automated Pytest Integration

The test suite includes `tests/test_kafka_smoke.py`, which automatically tests broker connectivity, routing, and consumption when Kafka is running:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_kafka_smoke.py -v
```

If Kafka is not running, the test automatically skips with an informative message (`Kafka broker not reachable at localhost:9092`) rather than failing offline test runs.

---

## 6. Troubleshooting Guide

### 6.1 `KafkaConnectionError` / Connection Refused on `localhost:9092`
- **Symptom**: `aiokafka.errors.KafkaConnectionError: Unable to connect to localhost:9092`
- **Causes**:
  1. Docker container is not running. Check `docker compose ps`.
  2. Port 9092 is occupied by another process on your host. Check `netstat -ano | findstr 9092`.
  3. Kafka is still initializing. Check `docker compose logs kafka` to verify that `KafkaServer id=1 ... started` has appeared.

### 6.2 Listener Mismatch (`Advertised Listeners`)
- **Symptom**: Client connects to `localhost:9092`, but times out attempting to produce or fetch metadata.
- **Cause**: Client received incorrect advertised listener.
- **Solution**: Ensure `KAFKA_ADVERTISED_LISTENERS: 'PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092'`. Connect via `localhost:9092` when on the host, and `kafka:29092` when inside Docker.

### 6.3 `GroupCoordinatorNotAvailableError` on Initial Startup
- **Symptom**: `Group Coordinator Request failed: [Error 15] GroupCoordinatorNotAvailableError`
- **Cause**: When a consumer group connects for the very first time on a single-node cluster, Kafka dynamically creates the internal `__consumer_offsets` topic.
- **Solution**: `docker-compose.yml` sets `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` and `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0`. The client retries automatically and establishes coordination within a few milliseconds.

### 6.4 Missing Topic `boomerang.domain.events`
- **Symptom**: `UnknownTopicOrPartitionError: boomerang.domain.events`
- **Solution**: Re-run the topic initializer:
  ```powershell
  docker compose up kafka-init
  ```
  Or manually create the topic:
  ```powershell
  docker exec tracker_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic boomerang.domain.events --partitions 3 --replication-factor 1
  ```
