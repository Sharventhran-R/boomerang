# PROJECT: Community Missing Item & Asset Tracker

## 1. Product Objective
Build a community-based platform for reporting, discovering, matching, and recovering missing people, pets, items, and other assets based on geographic location.
The platform should allow people in a community to publish missing or found reports and allow other users in the same or nearby geographic area to discover those reports.

The system should support:
- Missing item reports
- Found item reports
- Missing pet reports
- Found pet reports
- Missing-person reports where appropriate and legally permitted
- General missing/found asset reports
- Geographic/radius-based discovery
- Interactive maps
- Images/photos
- Descriptions
- Categories
- Date/time information
- Rewards offered by report creators
- Potential match detection
- Recovery requests
- Recovery verification
- Notifications
- Report resolution
- User accounts
- Abuse/spam prevention

The primary differentiating capability is location-aware community discovery.
A user should be able to say: "I lost my wallet near this location."
The system should allow other users within a configurable geographic radius to discover that report.
Likewise, someone who finds an item can publish a found report, and the system can identify nearby potential matches.

## 2. Core Product Workflow
The primary workflow is:

### Scenario A — Person loses something
1. A user creates a `MISSING` report.
2. The report contains: title, description, category, approximate/current relevant location, time of loss, optional images, optional reward.
3. Other users in the relevant geographic area can discover the report.
4. If someone finds the missing item, they can:
   - contact the person who created the missing report, or
   - create a `FOUND` report if they cannot identify the matching missing report.

### Scenario B — Person finds something
1. A user finds an item.
2. They search nearby `MISSING` reports.
3. If they find a likely match, they can initiate a recovery/contact request with the missing-report creator.
4. If they cannot find a matching missing report, they create a `FOUND` report.
5. The `FOUND` report becomes discoverable to users in the relevant geographic area.
6. The original owner can discover the found report and initiate a recovery/contact request with the finder.

### Scenario C — Recovery
Recovery/contact can be initiated by either side (e.g., Finder → missing-report creator, or Missing-item owner → found-report creator).
The system should support a controlled `recovery request` workflow rather than treating this as a generic "claim" system.
The recovery process should eventually support:
- contact/request message
- request status
- acceptance/rejection
- verification
- recovery completion
- auditability

Do NOT implement the detailed recovery workflow yet. This will be designed in a later phase.

## 3. Important Domain Terminology
Use these concepts consistently:

### User
A registered platform user.

### Report
A user-created record describing something missing or found.
A report has a type: `MISSING` or `FOUND`.
Do not create separate `missing_reports` and `found_reports` tables unless there is a strong architectural reason. Prefer a unified `reports` table with a `type` field.

### Report Creator
Use the concept of `created_by_user_id` rather than assuming that every report creator is always the legal/actual owner of an item.
For a `MISSING` report, the creator will normally be the person who lost the item.
For a `FOUND` report, the creator will normally be the person who found the item.
Avoid ambiguous terminology such as simply calling `reports.user_id` the "owner".

### Recovery Request
A recovery request represents an attempt by one user to contact another user regarding a specific report and recover the missing/found item.
A recovery request must support the fact that either party may initiate the interaction.
The exact schema will be designed during Phase 2.

### Match
A future matching concept may connect: `MISSING report <----> FOUND report`
Matching can eventually consider geographic proximity, category, title, description, time, images/other signals, and potentially ML/AI-based similarity.
The matching system belongs to a later phase and should NOT be implemented during this specification update.

## 4. Report Lifecycle
Document the initial report lifecycle separately from recovery state.
Suggested initial report statuses:
- `ACTIVE`
- `RESOLVED`
- `EXPIRED`
- `CANCELLED`

Do not mix recovery-request state into the report status. (e.g., Report can be `ACTIVE` while Recovery Request is `PENDING`). The exact recovery-request statuses will be finalized during Phase 2.

## 5. Platform Architecture
The application must support BOTH:
- **Mobile**: Use Flutter for Android and iOS. Mobile capabilities should include: GPS/location access, Interactive map, Nearby reports, Radius selection, Report creation, Report images, Report details, Recovery requests, Notifications, User account, My reports.
- **Web / PC**: The same Flutter codebase should also support Flutter Web. Users should be able to access the application through desktop browsers. The web application should provide: Responsive desktop interface, Interactive map, Nearby reports, Report creation, Report management, Authentication, Recovery requests, User dashboard, Search/filtering.

The backend must be client-independent. Both clients must use the same backend APIs and business logic.
Architecture:
```text
Flutter Mobile ───────┐
                      │
Flutter Web ──────────┼──→ FastAPI REST API
                      │         ▼
                      │    PostgreSQL + PostGIS
                      │         ▼
                      │    Kafka
```

## 6. High-Level Architecture
```text
┌───────────────────┐     │     Flutter Mobile    │     │     Android / iOS     │
└─────────┬─────────┘     │
┌─────────▼─────────┐     │
Flutter Web         │     │
Desktop Browser     │
└─────────┬─────────┘     │
REST / JSON               │
▼
┌───────────────────┐     │
FastAPI             │     │
│                   │     │
Authentication      │     │
Reports             │     │
Recovery Requests   │     │
Search              │     │
Business Logic      │
└───────┬─────┬─────┘     │
│             │
┌───────┘             └───────────┐
▼                           ▼
┌───────────────┐     ┌──────────────┐
│ PostgreSQL    │     │ Kafka        │
│ + PostGIS     │     │              │
│               │     │ Events       │
│ Users         │     │ Topics       │
│ Reports       │     └──────┬───────┘
│ Recovery Req. │            │
│ Locations     │            │
┌────────┼─────────┐     └───────────────┘
▼        ▼         ▼
Matching Notification Analytics
Consumer Consumer Consumer
```

## 7. Geographic Model
The system is fundamentally location-aware.
Reports should contain geographic information directly rather than introducing a separate generic `locations` table unless required later.
The planned database technology is PostgreSQL and PostGIS.
The intended spatial representation is approximately: `GEOGRAPHY(POINT, 4326)`
The system should eventually support: nearby reports, radius-based search, distance calculation, geographic filtering, map visualization, spatial indexing using GiST, and area-based discovery.
The exact database implementation belongs to Phase 2/Phase 5.

## 8. Kafka's Role
Kafka is part of the architecture, but it must not replace normal database operations.
Synchronous request:
```text
Flutter
   ↓
FastAPI
   ↓
PostgreSQL/PostGIS
```
Asynchronous events can later flow through Kafka:
```text
Report Created
      ↓
    Kafka
      ↓
 ┌────┼───────────────┐
 ↓    ↓               ↓
Match Notification  Analytics
```
Potential future events include: `report.created`, `report.updated`, `potential_match.detected`, `recovery.requested`, `recovery.accepted`, `recovery.completed`, `notification.created`.
Kafka implementation belongs to Phase 7. Do not implement Kafka during Phase 2.

## 9. Future Matching Architecture
Intended future architecture:
```text
MISSING REPORT
      │
      │
      ▼
Matching Engine
      ▲
      │
FOUND REPORT
```
Potential matching stages:
1. geographic filtering using PostGIS
2. category filtering
3. temporal filtering
4. textual similarity
5. optional image similarity
6. scoring/ranking
7. potential-match event
8. notification
The matching specification, eligibility criteria, provisional ranking formula ($S = 0.30I + 0.30C + 0.25D + 0.15T$), alert policies, and lifecycle transitions are formalized in Phase 8.1 (`docs/matching_specification.md`). Do not add ML/embeddings/vector databases in Phase 8.

## 10. Images
Reports may optionally contain multiple images.
The initial architecture should allow:
```text
reports
   │
   └── report_images
```
Actual image storage strategy can be decided later. Do not implement cloud object storage or image-processing infrastructure yet.

## 11. Rewards
A `MISSING` report may optionally include a reward.
Rewards should be represented as data associated with the report.
Important:
- reward is optional
- reward must not be treated as payment processing
- payment processing is not part of the current roadmap
- the system should not imply that the platform guarantees or processes the reward
The exact field/type/constraints will be finalized during Phase 2.

## 12. Authentication & Security
Eventual application must use JWT authentication. Security requirements: Registration, Login, Password hashing (Argon2id), Protected endpoints, Authorization, User ownership checks, Rate limiting, Spam/duplicate prevention, Secure environment variables. No secrets in Git.
*Deferred features (to be implemented in future phases): Email Verification, Multi-Factor Authentication (MFA), password reset workflows.*

## 13. Python Development Environment
The backend must use a project-local Python virtual environment: `.venv/`
Requirements: Python 3.12+, Never install project dependencies globally, Use `.venv` for development (must be ignored by Git), Use `python -m pip`, `python -m pytest`, `python -m ruff`, `python -m mypy`. Project should contain `requirements.txt` and `pyproject.toml` (with Ruff, mypy, pytest configs).
Strict typing with zero tolerance for unnecessary `Any`, untyped functions, `# type: ignore`, dead code, or unused imports.

## 14. Maps
Interactive map supporting: User location, Missing/Found markers, Potential-match indicators, Report details, Search radius, Map movement.
Mobile uses GPS, Web uses browser geolocation (handle lack of permissions gracefully).

## 15. Planned Technology Stack
- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL, PostGIS, JWT authentication, pytest, Ruff, mypy
- **Messaging / Event Processing**: Apache Kafka, aiokafka.
- **Frontend**: Flutter, Dart (Flutter Web, Android, iOS) communicating via REST APIs.
- **Infrastructure**: Docker, Docker Compose

## 16. Development Roadmap
- **Phase 0  — Agentic Workspace**
- **Phase 1  — Backend Infrastructure**
- **Phase 2  — Database Domain Model**
- **Phase 3  — Authentication & Authorization**
- **Phase 4  — Missing/Found Reports**
- **Phase 5  — PostGIS Geospatial Search**
- **Phase 6  — Flutter Mobile + Web**
- **Phase 7  — Kafka Event Architecture**
- **Phase 8  — Matching Engine**
- **Phase 9  — Notifications**
- **Phase 10 — Security & Abuse Prevention**
- **Phase 11 — Testing & Observability**
- **Phase 12 — Production Hardening**

Phase 2 should establish the database foundation for: users, reports, report images, recovery requests. Potential future entities such as matches, notifications, analytics events, etc. should remain future-phase concepts unless they are strictly required for the initial schema.

## 17. Current State
- Phase 0 complete (Agentic Workspace)
- Phase 1 complete (Backend Infrastructure)
- Phase 2 complete (Database Domain Model)
- Phase 3 complete (Authentication & Authorization)
- Phase 4 complete (Missing/Found Reports + S3 Object Storage)
- Phase 5 complete (PostGIS Geospatial Search & Distance Sorting)
- Phase 6 complete (Flutter Mobile + Web Foundation & Stitch UI)
- Phase 7 complete (Kafka Event Architecture, Outbox, Consumer Foundation & Reliability Hardening)
- Phase 8.1 complete (Preflight Audit & Missing/Found Matching Specification in `docs/matching_specification.md`)
- Phase 8.2 complete (Candidate Retrieval Service in `app/services/matching/`)
- Infrastructure operational: PostgreSQL 16 + PostGIS 3.4, Apache Kafka 3.8, MinIO object storage
- Backend test suite reported clean (140 passed)
- Quality gates reported clean: Ruff linter & format, strict mypy, Alembic schema check, Flutter analyze
- Outstanding Production-Readiness Item: Live Kafka consumer-group rebalance integration test pending prior to deploying multi-consumer replicas (see `.agents/AGENT_MEMORY.md`)

## 18. Phase Control Rules
> The agent must work one phase at a time. The agent must not begin a later phase until the current phase has been explicitly completed and approved.

Only the currently authorized phase may be implemented. The agent MUST NOT autonomously jump ahead. If a later-phase dependency appears necessary, stop, explain, and ask for authorization.

## 19. Engineering Principles
Prioritize: Correctness, Maintainability, Strong typing, Testability, Separation of concerns, Minimal dependencies, Small diffs, Good error handling.
Avoid: Premature optimization, unnecessary abstraction, microservices, ML, payment processing, untyped code.

## 20. Agentic Development Workflow
PLAN -> IMPLEMENT -> TEST -> VERIFY -> REVIEW DIFF -> UPDATE .agents/AGENT_MEMORY.md -> COMMIT -> NEXT AUTHORIZED TASK
Every milestone must have explicit acceptance criteria. Must run relevant tests before completing tasks.

## 21. Current Workspace Files
```text
project/
├── .venv/
├── .agents/
│   ├── AGENTS.md
│   ├── AGENT_MEMORY.md
│   └── PROJECT_SPEC.md
├── app/
├── tests/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 22. Separation of Responsibilities
- **.agents/AGENTS.md**: HOW the agent works (rules, commands, guardrails). References AGENT_MEMORY.md using `@[Project Memory](.agents/AGENT_MEMORY.md)`.
- **.agents/PROJECT_SPEC.md**: WHAT the project is (objectives, roadmap, architecture).
- **.agents/AGENT_MEMORY.md**: WHAT HAS ALREADY HAPPENED (current state, log, architecture decisions).
