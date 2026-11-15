# Boomerang Security Threat Model
**Phase 10.1 — Comprehensive Threat Modelling & Security Blueprint**

---

## 1. Executive Summary & Scope

Boomerang is a community-based physical asset reporting, discovery, matching, and recovery platform built on FastAPI, PostgreSQL with PostGIS, Apache Kafka (KRaft), MinIO/S3 object storage, and a cross-platform Flutter client (Android, iOS, Web).

### 1.1 In-Scope Product Capabilities
- Missing physical-item reports (`type=MISSING`)
- Found physical-item reports (`type=FOUND`)
- PostGIS-powered geographic and radius-based discovery
- Deterministic heuristic matching engine between Missing and Found items
- Two-party recovery requests and verification workflows
- Optional item owner rewards on Missing reports
- Transactional outbox pattern and Kafka asynchronous domain event bus
- Push (FCM / Web Push) and in-app notification infrastructure
- Flutter mobile and web client interfaces

### 1.2 Out-of-Scope Items (Strict Product Boundaries)
- **Missing-person and found-person functionality is NOT implemented and is strictly out of scope for Phase 10.** No person report types, workflows, or schemas are considered.
- Automated payment processing or escrow of rewards (rewards are purely informational and non-custodial).
- Mandatory identity verification / KYC systems.

---

## 2. System Assets & Data Classification

Assets within Boomerang are categorized under four sensitivity classifications:

| Asset Name | Sensitivity Level | Description | Impact of Compromise |
| :--- | :--- | :--- | :--- |
| **User Authentication Credentials** | `RESTRICTED` | Argon2id password hashes, refresh token SHA-256 hashes, JWT secret keys. | Account takeover, credential stuffing across accounts. |
| **User Contact Information** | `CONFIDENTIAL` | User real names, email addresses, notification preferences. | Phishing, identity correlation, privacy violations. |
| **Precise Incident Coordinates** | `CONFIDENTIAL` | High-precision GPS latitude/longitude where an item was lost or found. | Stalking, residential burglary targeting, route tracking. |
| **Recovery Verification Data** | `CONFIDENTIAL` | Challenge questions, private proof details, verification responses, recovery messages. | Fraudulent claim interception, item theft. |
| **Device Push Tokens** | `CONFIDENTIAL` | FCM registration tokens, Web Push endpoints, client device IDs. | Push notification spoofing, denial of service, push tracking. |
| **Uploaded Photographs & Assets** | `INTERNAL` | Images stored in MinIO/S3 buckets representing items. | Embedded EXIF GPS leakage, hosting of malicious/offensive content. |
| **Kafka Event Stream** | `INTERNAL` | Kafka topics carrying domain events, outbox table records. | Tampering with matching or notification pipelines, event interception. |
| **Public Item Metadata** | `PUBLIC` | Item title, category, generalized location, description, status, reward amount. | Search scraping, competitor indexing, spamming. |

---

## 3. Trust Boundaries & Data Flow Architecture

The Boomerang application operates across six explicit trust boundaries:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ TRUST BOUNDARY 1: Untrusted Internet (Public / Client Perimeter)            │
│  - Flutter Mobile (Android/iOS) & Flutter Web (Desktop Browser)             │
│  - External Crawlers, Scrapers, Malicious Clients                           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTPS / WSS / REST
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ TRUST BOUNDARY 2: Application Boundary (FastAPI Runtime & Dependencies)      │
│  - Routers: /auth, /reports, /matches, /recovery-requests, /notifications   │
│  - Auth Middleware & Dependency Inversion (get_current_user)                │
│  - Outbox Transactional Event Emitter                                       │
└──────────────┬───────────────────────┼──────────────────────────────┬───────┘
               │ SQLAlchemy Async      │ S3 Async API                 │ aiokafka
               ▼                       ▼                              ▼
┌──────────────────────────┐ ┌────────────────────┐ ┌─────────────────────────┐
│ TRUST BOUNDARY 3:        │ │ TRUST BOUNDARY 4:  │ │ TRUST BOUNDARY 5:       │
│ Authoritative Relational │ │ Object Storage     │ │ Event Streaming         │
│ Database (PostgreSQL 16  │ │ (MinIO / AWS S3)   │ │ (Apache Kafka 3.8 KRaft)│
│ + PostGIS 3.4)           │ │ - S3 Bucket:       │ │ - Topic:                │
│ - users, user_sessions   │ │   boomerang-photos │ │   boomerang.domain.     │
│ - reports, report_images │ │ - Stored Keys:     │ │   events                │
│ - matches, recovery_reqs │ │   reports/{id}/    │ │ - Outbox Dispatcher     │
│ - notifications, devices │ │   {uuid}.ext       │ │ - Matching Worker       │
│ - outbox_events          │ └────────────────────┘ │ - Notification Consumer │
│ - consumer_events        │                        └────────────┬────────────┘
└──────────────────────────┘                                     │
                                                                 │ Push Dispatcher
                                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ TRUST BOUNDARY 6: External Third-Party Cloud Services                       │
│  - Google Firebase Cloud Messaging (FCM v1 HTTP API)                        │
│  - APNs (Apple Push Notification service via FCM)                           │
│  - Web Push Service Workers                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Threat Actors & Attacker Profiles

1. **Anonymous Remote Scraper**: Exploits public endpoints (`GET /api/v1/reports`) to harvest catalog data, item locations, and photographs for competing services or criminal targeting.
2. **Credential Stuffer / Brute-Forcer**: Uses automated dictionary attacks against `/api/v1/auth/login` to hijack existing accounts.
3. **Malicious Authenticated User (Spammer/Sybil)**: Creates dozens of sockpuppet accounts to flood the system with fake reports, manipulate the matching worker, or bypass daily quotas.
4. **Opportunistic Item Fraudster (Extortionist)**: Targets reports with high cash rewards, files fraudulent recovery claims, guesses verification details, and demands ransom.
5. **Location Stalker**: Exploits high-precision PostGIS coordinates and iterative radius queries to pinpoint exact user residences or workplaces based on where items are lost or found.
6. **Malicious Content Uploader**: Exploits permissive file-upload endpoints to upload malware, scripts, or images with embedded location EXIF data.
7. **Privileged Insider / Compromised Database Operator**: Attempts to access or tamper with user sessions, verification responses, or audit logs directly.

---

## 5. Attack Surfaces

| Attack Surface | Entry Points | Primary Risks |
| :--- | :--- | :--- |
| **Authentication & Session** | `/api/v1/auth/register`<br>`/api/v1/auth/login`<br>`/api/v1/auth/refresh`<br>`/api/v1/auth/logout` | Credential stuffing, account takeover, refresh token hijacking, lack of access token revocation. |
| **Report Lifecycle & Quotas** | `POST /api/v1/reports`<br>`PATCH /api/v1/reports/{id}`<br>`GET /api/v1/reports/me` | Quota exhaustion, report flooding, unauthorized state transitions, reward tampering. |
| **Geospatial Discovery & PostGIS** | `GET /api/v1/reports`<br>`GeoSearchParams` (`latitude`, `longitude`, `radius_km`) | Precise coordinate exposure, spatial triangulation, geographic scraping, PostGIS denial of service. |
| **Matching Engine** | `GET /api/v1/reports/{id}/matches`<br>`GET /api/v1/matches/{id}` | BOLA/IDOR access, extraction of opposite report private coordinates, explainability data leakage. |
| **Recovery Claims** | `POST /api/v1/recovery-requests`<br>`PATCH /api/v1/recovery-requests/{id}` | Fraudulent recovery claims, verification answer guessing, unilateral completion hijacking. |
| **Media & File Storage** | `POST /api/v1/reports/{id}/images`<br>`DELETE /api/v1/reports/{id}/images/{id}` | MIME-type spoofing, unvalidated extensions, EXIF GPS coordinate leakage, storage exhaustion. |
| **Device & Notification Management** | `POST /api/v1/devices/register`<br>`DELETE /api/v1/devices/{device_id}`<br>`GET /api/v1/notifications` | Device registration flooding, token hijacking, push notification surveillance on shared devices. |
| **Kafka & Event Consumers** | Outbox table, Kafka topic `boomerang.domain.events`, Consumer workers | Plaintext broker communication, poison pill payloads, duplicate side effects, log credential leakage. |

---

## 6. Comprehensive STRIDE Threat Register

### 6.1 Spoofing (S)

#### [THR-AUTH-001] Credential Stuffing & Password Brute-Forcing
- **Affected Component**: `app/api/auth.py` (`POST /api/v1/auth/login`)
- **STRIDE Category**: Spoofing
- **Attacker Profile**: Remote unauthenticated attacker using automated botnets.
- **Attack Scenario**: Attacker executes high-speed password spraying or dictionary attacks against user email addresses.
- **Preconditions**: Attacker knows or guesses victim email addresses.
- **Potential Impact**: Complete account takeover, access to private reports, recovery messages, and user notifications.
- **Existing Controls**: Modern Argon2id hashing (`ph = PasswordHasher()`).
- **Control Gaps**: No rate limiting (neither IP-based nor email-based), no progressive delays, no CAPTCHA, no account lockout after repeated failures.
- **Recommended Mitigation**: Implement sliding-window IP and account rate limiting (5 attempts per 15 minutes), account lockout/cooling-off period, and security audit event logging.
- **Severity**: HIGH | **Likelihood**: HIGH | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.2 / 10.3
- **Verification Method**: Automated burst test verifying 429 Too Many Requests response after threshold violations.

#### [THR-AUTH-002] Sybil Account Mass Registration
- **Affected Component**: `app/api/auth.py` (`POST /api/v1/auth/register`)
- **STRIDE Category**: Spoofing
- **Attacker Profile**: Automated script / spam operator.
- **Attack Scenario**: Attacker creates thousands of throwaway accounts to bypass per-user daily report quotas and distribute spam.
- **Preconditions**: Internet access to the registration endpoint.
- **Potential Impact**: Database bloat, spam reports overwhelming matching algorithms, bypass of user-level rate limits.
- **Existing Controls**: Email lowercase normalization, unique database constraint on `users.email`.
- **Control Gaps**: No registration rate limiting, no email verification, no proof-of-work or CAPTCHA challenge.
- **Recommended Mitigation**: Implement IP-based registration throttling (max 3 accounts/hour per IP), email domain validation, and disposable email blocklists.
- **Severity**: MEDIUM | **Likelihood**: HIGH | **Risk Priority**: **MEDIUM**
- **Proposed Phase**: Phase 10.2 / 10.3
- **Verification Method**: Script attempting 10 sequential registrations from a single IP asserting rate limiting on the 4th attempt.

#### [THR-AUTH-003] Stale Access Token Reuse Post-Logout
- **Affected Component**: `app/api/auth.py` (`POST /api/v1/auth/logout`), `app/api/deps.py` (`get_current_user`)
- **STRIDE Category**: Spoofing / Elevation of Privilege
- **Attacker Profile**: Network eavesdropper or user of shared/borrowed device.
- **Attack Scenario**: User logs out on a shared computer. The application revokes the refresh token in `user_sessions`, but the JWT access token remains valid in browser storage/cache until expiration (up to 15 minutes).
- **Preconditions**: Attacker gains access to client session storage or intercepted access token prior to natural expiration.
- **Potential Impact**: Unauthorized actions performed as victim for remaining token lifetime.
- **Existing Controls**: Refresh token is marked revoked (`session.revoked_at = datetime.now(UTC)`). Access token lifespan is bounded (15 minutes).
- **Control Gaps**: Access tokens are completely stateless; `get_current_user` does not check any token denylist or user session invalidation timestamp.
- **Recommended Mitigation**: Maintain a Redis-backed or in-memory access token denylist (or track `users.token_invalid_before` timestamp) checked during `get_current_user`.
- **Severity**: MEDIUM | **Likelihood**: MEDIUM | **Risk Priority**: **MEDIUM**
- **Proposed Phase**: Phase 10.2
- **Verification Method**: Attempt authenticated API request using access token immediately after calling `/logout`, asserting 401 Unauthorized.

---

### 6.2 Tampering (T)

#### [THR-REPORT-001] Quota Bypass & Database Flooding via Report Creation
- **Affected Component**: `app/api/reports.py` (`POST /api/v1/reports`), `app/services/report.py`
- **STRIDE Category**: Tampering / Denial of Service
- **Attacker Profile**: Malicious user, rogue script, automated scraper.
- **Attack Scenario**: Attacker loops `POST /api/v1/reports`, submitting thousands of synthetic missing and found item reports.
- **Preconditions**: Valid authenticated user account.
- **Potential Impact**: Flooding of PostgreSQL storage, CPU saturation of the PostGIS matching engine, overwhelming genuine users with bogus match alerts.
- **Existing Controls**: Title length checks (3–100 chars), valid enum checks.
- **Control Gaps**: **Zero daily creation limits or active report caps are enforced.** Users can create unlimited reports. Deletion/recreation is unmetered.
- **Recommended Mitigation**: Implement the Centralized Report Creation Quota Service:
  - Missing: Max 5 per user per calendar day (midnight Asia/Kolkata reset), max 10 simultaneously active.
  - Found: Tiered limits (5 New / 15 Established / 30 Trusted per day).
  - Atomic reservation in PostgreSQL transaction; no refund on cancellation/deletion.
- **Severity**: CRITICAL | **Likelihood**: HIGH | **Risk Priority**: **CRITICAL**
- **Proposed Phase**: Phase 10.3
- **Verification Method**: Concurrently submit 6 Missing reports for one user; assert the 6th returns 429 Quota Exceeded and does not write to the database.

#### [THR-UPLOAD-001] File Upload Type Spoofing & Malicious Payload Delivery
- **Affected Component**: `app/services/storage.py` (`upload_image_to_s3`), `app/api/reports.py`
- **STRIDE Category**: Tampering / Elevation of Privilege
- **Attacker Profile**: Malicious authenticated user.
- **Attack Scenario**: Attacker crafts an executable script (`.php`, `.html`, `.svg`, `.exe`) or polyglot file, names it `exploit.jpg`, and sets the client header `Content-Type: image/jpeg`.
- **Preconditions**: Authenticated user owning an active report.
- **Potential Impact**: Remote Code Execution (if served from an executable context), Stored Cross-Site Scripting (XSS via SVG), or malware distribution via platform CDN.
- **Existing Controls**: Header check: `file.content_type in ["image/jpeg", "image/png", "image/webp"]`; file size checked $\le 5\text{ MB}$.
- **Control Gaps**: Content-Type header is completely client-controlled. **Zero magic-byte / file-signature verification is performed.** Filename extension is unsanitized (`file.filename.split(".")[-1]`).
- **Recommended Mitigation**: Inspect file magic bytes (`python-magic` or direct header byte inspection: JPEG `FF D8 FF`, PNG `89 50 4E 47`, WebP `RIFF...WEBP`). Re-encode images using Pillow to strip malicious embedded payloads. Force extension based strictly on verified MIME type, not client filename.
- **Severity**: HIGH | **Likelihood**: HIGH | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.4
- **Verification Method**: Upload a text file with `Content-Type: image/jpeg`; assert rejection with 422 Unprocessable Content.

#### [THR-RECOVERY-001] Unilateral Recovery Completion & Report Premature Resolution
- **Affected Component**: `app/services/recovery.py` (`update_recovery_request_status`)
- **STRIDE Category**: Tampering
- **Attacker Profile**: Dishonest requester or dishonest report creator.
- **Attack Scenario**: Once a recovery request is in `ACCEPTED` state, either party (`current_user.id in (requester_id, recipient_id)`) can unilaterally send `PATCH /api/v1/recovery-requests/{id}` with `status=COMPLETED`. This automatically transitions the underlying report to `RESOLVED`.
- **Preconditions**: Recovery request is in `ACCEPTED` status.
- **Potential Impact**: A dishonest finder can mark an item as recovered without actually handing it over, depriving the owner of community search visibility; or an owner can mark it resolved to evade verification.
- **Existing Controls**: Terminal state validation prevents reopening after completion.
- **Control Gaps**: No mutual two-party handshake or confirmation code required before transitioning to `COMPLETED`.
- **Recommended Mitigation**: Require a two-party confirmation handshake: recipient marks "Item Handed Over", requester inputs a 6-digit one-time handover token or confirms receipt before status transitions to `COMPLETED`.
- **Severity**: MEDIUM | **Likelihood**: MEDIUM | **Risk Priority**: **MEDIUM**
- **Proposed Phase**: Phase 10.5
- **Verification Method**: Attempt to mark recovery request COMPLETED from only one side without counterparty confirmation; assert status remains in handover state.

---

### 6.3 Repudiation (R)

#### [THR-AUDIT-001] Missing Administrative & Security Audit Trail
- **Affected Component**: Entire backend (`app/api/`)
- **STRIDE Category**: Repudiation
- **Attacker Profile**: Malicious user, abusive reporter, or rogue administrative operator.
- **Attack Scenario**: Attacker performs abusive actions (fraudulent recovery claims, rapid report deletion, status tampering), then deletes their account or denies having performed the action.
- **Preconditions**: Valid authenticated account.
- **Potential Impact**: Incapability to conduct forensic analysis, dispute resolution, or prove fraud in law-enforcement requests.
- **Existing Controls**: Transactional outbox emits domain events for report and recovery lifecycle changes.
- **Control Gaps**: Outbox is primarily an integration event bus, not an immutable tamper-evident security audit log. Failed login attempts, permission rejections (403), location search queries, and administrative actions are not logged to a durable audit table.
- **Recommended Mitigation**: Implement a dedicated `security_audit_logs` table recording timestamp, user_id, IP address, user_agent, action, resource_id, outcome, and metadata.
- **Severity**: MEDIUM | **Likelihood**: HIGH | **Risk Priority**: **MEDIUM**
- **Proposed Phase**: Phase 10.8
- **Verification Method**: Perform security-relevant actions (failed login, permission denial) and query audit log table to verify immutable log generation.

---

### 6.4 Information Disclosure (I)

#### [THR-LOCATION-001] Public Harvesting of Precise Incident GPS Coordinates
- **Affected Component**: `app/services/report.py` (`list_reports`, `get_report_by_id`), `app/api/reports.py`
- **STRIDE Category**: Information Disclosure
- **Attacker Profile**: Stalker, thief, automated harvester.
- **Attack Scenario**: Attacker calls `GET /api/v1/reports` or `GET /api/v1/reports/{id}` and directly reads exact 7-decimal-place GPS coordinates (`latitude`, `longitude`) returned in the JSON payload.
- **Preconditions**: None (public unauthenticated endpoint).
- **Potential Impact**: Pinpoints exact location where an expensive physical item was lost (e.g. victim's driveway, residential porch, office cubicle), enabling burglary or real-world harassment.
- **Existing Controls**: None. Exact database coordinates are cast to float and serialized directly.
- **Control Gaps**: **Exact coordinates are exposed to unauthenticated public callers.** There is no coordinate coarsening, grid discretization, or fuzzing.
- **Recommended Mitigation**:
  - Enforce the Location Privacy Policy: public discovery endpoints must return *coarsened / approximate* coordinates (e.g. truncated to ~500m–1km grid or jittered by a deterministic radial offset).
  - Exact coordinates must only be accessible to the report creator, or shared with an accepted recovery claimant upon explicit authorization.
- **Severity**: CRITICAL | **Likelihood**: HIGH | **Risk Priority**: **CRITICAL**
- **Proposed Phase**: Phase 10.6
- **Verification Method**: Call `GET /api/v1/reports` without auth; assert returned coordinates are rounded/fuzzed to configured privacy precision ($\sim 0.01^\circ$).

#### [THR-LOCATION-002] Coordinate Triangulation via Differential Radius Queries
- **Affected Component**: `app/api/reports.py` (`GET /api/v1/reports?latitude=...&longitude=...&radius_km=...`)
- **STRIDE Category**: Information Disclosure
- **Attacker Profile**: Technical attacker scripting automated queries.
- **Attack Scenario**: Attacker executes automated binary searches using microscopic increments of `latitude`, `longitude`, and `radius_km` with `ST_DWithin`. By observing when a report appears and disappears from query results, the attacker mathematically calculates the exact incident point down to the meter.
- **Preconditions**: Public access to radius search API.
- **Potential Impact**: Bypasses location coarsening and reveals exact home/work locations.
- **Existing Controls**: None.
- **Control Gaps**: `radius_km` accepts arbitrary floating-point values without minimum snapping or pagination/rate throttling.
- **Recommended Mitigation**: Enforce discrete radius quantization (e.g., allowed radii restricted to `[1, 2, 5, 10, 25]` km), rate limit spatial queries per IP/user, and base distance calculations on fuzzed anchor coordinates.
- **Severity**: HIGH | **Likelihood**: MEDIUM | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.6
- **Verification Method**: Execute 50 sequential radius probes within 10 seconds; assert rate limiting and discrete radius enforcement.

#### [THR-UPLOAD-002] EXIF GPS Coordinate Leakage in Uploaded Photos
- **Affected Component**: `app/services/storage.py` (`upload_image_to_s3`)
- **STRIDE Category**: Information Disclosure
- **Attacker Profile**: Anyone viewing public report photographs.
- **Attack Scenario**: User takes a photo of their lost item at their private home using an iPhone or Android phone. The photo's EXIF metadata contains exact GPS coordinates. The user uploads it to Boomerang, and the backend stores the raw bytes in S3. A thief downloads the photo and extracts the EXIF tag `GPSLatitude`/`GPSLongitude`.
- **Preconditions**: User uploads a smartphone photo with location services enabled.
- **Potential Impact**: Complete exposure of user's residence, routine, or private address.
- **Existing Controls**: None. Files are uploaded directly to S3 as raw byte streams.
- **Control Gaps**: No EXIF stripping or image normalization pipeline.
- **Recommended Mitigation**: Process all uploaded images through an image sanitization pipeline (Pillow) to strip all EXIF, GPS, and device metadata before persisting to S3.
- **Severity**: HIGH | **Likelihood**: HIGH | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.4
- **Verification Method**: Upload a JPEG containing EXIF GPS tags; download from S3 and assert EXIF tags are completely absent.

---

### 6.5 Denial of Service (D)

#### [THR-DOS-001] Device Registration Flooding & Push Fan-Out Amplification
- **Affected Component**: `app/api/devices.py` (`POST /api/v1/devices/register`), `app/services/push_dispatcher.py`
- **STRIDE Category**: Denial of Service
- **Attacker Profile**: Authenticated malicious user.
- **Attack Scenario**: Attacker scripts calls to `/api/v1/devices/register`, generating 50,000 unique `device_id` strings under a single user account. When any event triggers a notification for this user, `create_delivery_tasks` creates 50,000 delivery task records in `notification_deliveries`, clogging the push dispatcher queue and exhausting worker capacity.
- **Preconditions**: Valid authenticated account.
- **Potential Impact**: Starvation of the push dispatcher, delayed notification delivery for all platform users, database connection pool exhaustion.
- **Existing Controls**: Stale tokens on other accounts are deactivated.
- **Control Gaps**: No limit on the maximum number of active devices per user account.
- **Recommended Mitigation**: Enforce an active device limit of max 10 active devices per user. When an 11th device registers, automatically deactivate the least-recently active device.
- **Severity**: HIGH | **Likelihood**: MEDIUM | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.3
- **Verification Method**: Register 12 distinct devices for one user; assert exactly 10 are active and the oldest 2 are marked inactive.

#### [THR-DOS-002] Decompression Bomb / Image Dimension Denial of Service
- **Affected Component**: `app/services/storage.py`
- **STRIDE Category**: Denial of Service
- **Attacker Profile**: Malicious user.
- **Attack Scenario**: Attacker submits a specially crafted "pixel bomb" image file (e.g., compressed to 500 KB, but unpacking to $50,000 \times 50,000$ uncompressed pixels in RAM).
- **Preconditions**: Authenticated user uploading an image.
- **Potential Impact**: Memory exhaustion (OOM kill) of FastAPI or worker containers when processing or rendering image thumbnails.
- **Existing Controls**: File size is limited to 5 MB.
- **Control Gaps**: No check on uncompressed pixel dimensions.
- **Recommended Mitigation**: Enforce strict dimension bounds on image inspection (e.g., max $4096 \times 4096$ pixels, max 25 megapixels) using safe header parsing before loading entire buffers into memory.
- **Severity**: MEDIUM | **Likelihood**: LOW | **Risk Priority**: **MEDIUM**
- **Proposed Phase**: Phase 10.4
- **Verification Method**: Upload a compressed pixel bomb file; assert rejection before full buffer decompression.

---

### 6.6 Elevation of Privilege (E)

#### [THR-ADMIN-001] Complete Absence of Role-Based Access Control (RBAC)
- **Affected Component**: Entire backend (`app/db/models.py`, `app/api/deps.py`)
- **STRIDE Category**: Elevation of Privilege
- **Attacker Profile**: Insider, support technician, or attacker seeking unauthorized platform control.
- **Attack Scenario**: If administrative features (e.g. content moderation, account banning, dispute resolution) are implemented ad-hoc without formal RBAC, regular users or compromised API keys can call moderation endpoints.
- **Preconditions**: Lack of formal administrative architecture.
- **Potential Impact**: Arbitrary report deletion, unauthorized access to private recovery messages, malicious account suspension.
- **Existing Controls**: Currently, zero administrative endpoints or roles exist in code.
- **Control Gaps**: There is no `Role` enum, no `is_admin`/`is_moderator` column, and no `require_admin` dependency.
- **Recommended Mitigation**: Define a formal RBAC model (User, Moderator, Superadmin) with least-privilege scoping, explicit role checks (`require_role("MODERATOR")`), and dedicated administrative audit logging before implementing any moderation APIs.
- **Severity**: HIGH | **Likelihood**: LOW | **Risk Priority**: **HIGH**
- **Proposed Phase**: Phase 10.7
- **Verification Method**: Test admin endpoints with regular user credentials; assert immediate 403 Forbidden rejection.

---

## 7. Risk Priority Assessment & Matrix

| Risk Level | Definition | Threats |
| :--- | :--- | :--- |
| **CRITICAL** | High likelihood & severe impact. Threatens user physical safety, privacy, or core platform integrity. | **THR-REPORT-001** (Quota bypass & mass report creation)<br>**THR-LOCATION-001** (Public exposure of exact GPS incident coordinates) |
| **HIGH** | High likelihood with significant operational/security impact, or high impact with moderate likelihood. | **THR-AUTH-001** (Credential stuffing / no login throttling)<br>**THR-UPLOAD-001** (MIME spoofing & executable upload)<br>**THR-UPLOAD-002** (EXIF GPS leakage in photos)<br>**THR-LOCATION-002** (Iterative radius triangulation)<br>**THR-DOS-001** (Device flooding & push queue exhaustion)<br>**THR-ADMIN-001** (Unstructured admin permissions) |
| **MEDIUM** | Moderate likelihood or impact. Abuse or data leakage restricted in scope. | **THR-AUTH-002** (Sybil account registration)<br>**THR-AUTH-003** (Stale access token reuse)<br>**THR-RECOVERY-001** (Unilateral recovery completion)<br>**THR-AUDIT-001** (Missing security audit logging)<br>**THR-DOS-002** (Image decompression bomb) |
| **LOW** | Minor or cosmetic impact. | Public metadata scraping, lock-screen notification preview truncation. |

---

## 8. Summary of Existing Controls vs Control Gaps

| Subsystem | Existing Verified Controls | Identified Control Gaps |
| :--- | :--- | :--- |
| **Authentication** | Argon2id hashing, dual-token architecture, refresh token SHA-256 storage, refresh rotation, session revocation on logout. | No login/register rate limits, access token cannot be revoked before expiry, no password complexity requirements. |
| **Reports** | Report owner authorization checks on edit/delete, status transition state machine enforcement, max 5 images/report. | **Zero daily creation quota or active report cap enforced**, no spam/duplicate detection. |
| **Location & PostGIS** | GiST spatial indexing, ST_DWithin distance queries. | **Precise raw GPS coordinates returned publicly**, radius parameter unbounded, no spatial fuzzing. |
| **Media / Storage** | Client Content-Type whitelist, 5 MB file size limit, UUID object key generation. | **No magic byte verification**, raw EXIF metadata retained in S3 photos, unsanitized client file extension. |
| **Recovery Requests** | BOLA/IDOR authorization checks, duplicate pending claim rejection, status transition enforcement. | Unilateral completion allowed by either party, verification challenge brute-forcing unthrottled. |
| **Matching Engine** | Strict report ownership required to view matches, explainability score transparency. | Exact opposite report coordinates exposed in match detail view. |
| **Push Notifications** | Device token isolation across accounts, FCM payloads audited for 0 coordinate/token leaks, 1500ms debouncing. | No device count cap per user account (allows fan-out DoS). |
| **Administration** | No admin code exists (attack surface currently zero). | No RBAC model or moderation framework designed. |
| **Privacy / Retention** | Notification preferences allow disabling push channels. | No account deletion endpoint, no GDPR cascade purge mechanism. |

