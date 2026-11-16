# Boomerang Testable Security Requirements Specification
**Phase 10.1 — Canonical Security Requirements & Automated Verification Criteria**

---

## 1. Authentication & Session Security (SEC-AUTH)

### [SEC-AUTH-001] Credential Stuffing & Login Brute-Force Rate Limiting
- **Description**: The system must throttle failed authentication attempts to `/api/v1/auth/login`.
- **Behavioral Specification**:
  - Maximum 5 attempts per email address within a rolling 60-second window.
  - Maximum 10 requests per client IP address within a rolling 60-second window.
  - Subsequent requests exceeding this threshold must return HTTP `429 Too Many Requests` with a `Retry-After` header indicating remaining wait time in seconds.
  - Fail-closed policy: Returns HTTP 503 if rate limiting storage (Redis) is unreachable.
- **Threat Addressed**: `THR-AUTH-001`
- **Verification Method**: Submit 6 sequential invalid password attempts for a test account. Assert the first 5 return 401 Unauthorized, and the 6th returns 429 Too Many Requests with valid `Retry-After`.

### [SEC-AUTH-002] Sybil Mass-Registration Rate Limiting
- **Description**: The system must throttle account registration at `/api/v1/auth/register`.
- **Behavioral Specification**:
  - Maximum 5 registrations per IP address per rolling 60-second window.
  - Trusted proxy traversal validates peer connection against `settings.TRUSTED_PROXIES`.
  - Fail-closed policy: Returns HTTP 503 if rate limiting storage (Redis) is unreachable.
- **Threat Addressed**: `THR-AUTH-002`
- **Verification Method**: Submit 6 sequential registration requests from the same IP. Assert the 6th request returns 429 Too Many Requests with valid `Retry-After`.

### [SEC-RATE-001] Distributed Sliding-Window Discovery Rate Limiting
- **Description**: The system must prevent automated geographic triangulation and API scraping via distributed Redis sliding windows.
- **Behavioral Specification**:
  - Anonymous callers to `GET /api/v1/reports`: Maximum 10 requests per minute per IP.
  - Authenticated callers to `GET /api/v1/reports`: Maximum 30 requests per minute per user ID (with secondary IP ceiling).
  - RFC 6585 compliance: Response headers include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`.
  - Fail-open policy: If Redis is unavailable, requests are allowed (degraded) with a warning log, while PostGIS spatial coarsening remains strictly active.
- **Threat Addressed**: `THR-LOCATION-001`, `THR-RESOURCE-001`
- **Verification Method**: Run 11 anonymous requests against `/api/v1/reports`; assert the 11th returns 429.

### [SEC-PROXY-001] Trusted Reverse Proxy & Forwarded Header Verification
- **Description**: The system must prevent IP-spoofing attacks that attempt to bypass IP-based rate limiting or fraud controls.
- **Behavioral Specification**:
  - Direct connection peer IP (`request.client.host`) is strictly authoritative if peer is not in `settings.TRUSTED_PROXIES`. Incoming `X-Forwarded-For` headers from untrusted peers are ignored.
  - When peer is a trusted proxy, `X-Forwarded-For` is parsed via right-to-left traversal, selecting the rightmost untrusted IP address.
  - Production deployments behind reverse proxies (Nginx, ALB, Cloudflare) must explicitly configure trusted proxy IP/CIDR ranges.
  - Wildcard ranges (`0.0.0.0/0`, `::/0`) are forbidden.
  - Default configuration is strictly restricted to loopback (`["127.0.0.1", "::1"]`).
- **Threat Addressed**: `THR-AUTH-002`, `THR-RESOURCE-001`
- **Verification Method**: Send direct request with spoofed `X-Forwarded-For: 1.1.1.1` from untrusted IP; assert rate-limiting key is bound to peer IP, not spoofed header.

### [SEC-QUOTA-001] Authoritative PostgreSQL Report Quotas & Active Caps
- **Description**: Authoritative business quotas must prevent spam item generation and resource exhaustion.
- **Behavioral Specification**:
  - Missing reports: Maximum 5 reports created per day; maximum 10 simultaneously active reports.
  - Found reports: Tiered daily limit based on `UserTrustTier` (`NEW`: 5, `ESTABLISHED`: 15, `TRUSTED`: 30).
  - Daily reset: Midnight Indian Standard Time (`Asia/Kolkata`, UTC+05:30).
  - Atomicity & Durability: Checked and incremented with row locking (`SELECT ... FOR UPDATE`) in `user_daily_quotas`.
  - Non-refundable: Deleting or resolving reports does not restore daily consumed quota.
  - Status endpoint: `GET /api/v1/reports/quota-status` returns remaining allowances.
- **Threat Addressed**: `THR-SPAM-001`, `THR-RESOURCE-002`
- **Verification Method**: Create 6 missing reports in a day; assert 6th returns 429. Seed 10 active missing reports; assert next creation returns 429.

### [SEC-AUTH-003] Immediate Access Token Invalidation on Logout & Credential Change
- **Description**: The system must revoke access tokens upon user logout, password change, or account suspension.
- **Behavioral Specification**:
  - Updating `User.tokens_invalid_before` must reject any access token with `iat <= tokens_invalid_before` with HTTP `401 Unauthorized`.
  - Calling `POST /api/v1/auth/logout` revokes the refresh session and invalidates current access tokens.
- **Threat Addressed**: `THR-AUTH-003`
- **Verification Method**: Obtain access token, call `/logout`, then immediately call `/api/v1/users/me` with the previous access token; assert HTTP 401 Unauthorized.

### [SEC-AUTH-004] Password Complexity & Length Bounding
- **Description**: User passwords must meet minimum entropy criteria and enforce upper length limits.
- **Behavioral Specification**:
  - Minimum length: 10 characters.
  - Maximum length: 128 characters.
  - Reject common passwords from a top-10,000 dictionary.
- **Threat Addressed**: `THR-AUTH-001`
- **Verification Method**: Submit registration with 9-character password (assert 422), "password1234" (assert 422), and 129-character password (assert 422).

---

## 2. API Authorization & IDOR/BOLA Protection (SEC-API)

### [SEC-API-001] Strict Object Ownership Verification on Report Modifications
- **Description**: Only the original creator of a report may edit its contents, upload images, delete images, or transition its status.
- **Behavioral Specification**:
  - Any request to `PATCH /api/v1/reports/{id}`, `POST /api/v1/reports/{id}/images`, or `DELETE /api/v1/reports/{id}/images/{img_id}` where `report.created_by_user_id != current_user.id` must be rejected with HTTP `403 Forbidden`.
  - Non-existent reports must return HTTP `404 Not Found` without disclosing existence.
- **Threat Addressed**: `THR-API-001`
- **Verification Method**: Authenticate as User B and attempt to PATCH a report created by User A. Assert HTTP 403 Forbidden.

### [SEC-API-002] Immutable Terminal State Transitions
- **Description**: Reports in terminal states cannot be transitioned back to active.
- **Behavioral Specification**:
  - A report with `status in {RESOLVED, CANCELLED, EXPIRED}` cannot be updated to `ACTIVE` or any other status. Attempted transitions must return HTTP `422 Unprocessable Content`.
- **Threat Addressed**: `THR-API-001`
- **Verification Method**: Create report, transition to `RESOLVED`, attempt to transition back to `ACTIVE`; assert HTTP 422.

---

## 3. Report Creation Quotas & Abuse Prevention (SEC-QUOTA)

### [SEC-QUOTA-001] Daily Missing Report Creation Quota
- **Description**: A user is limited to creating at most 5 Missing reports per calendar day.
- **Behavioral Specification**:
  - Quota tracks calendar days in the `Asia/Kolkata` timezone (`UTC+05:30`), resetting at 00:00:00 Asia/Kolkata.
  - The 6th creation attempt within the same calendar day must be rejected with HTTP `429 Too Many Requests` with a detail message indicating daily quota exceeded.
  - Editing, resolving, cancelling, or deleting reports does **not** refund the consumed daily creation slot.
- **Threat Addressed**: `THR-REPORT-001`
- **Verification Method**: In a test session, create 5 Missing reports successfully. Attempt to create a 6th Missing report; assert HTTP 429 Too Many Requests. Cancel 1 report and attempt creation again; assert still rejected with 429.

### [SEC-QUOTA-002] Active Missing Report Cap
- **Description**: A user cannot maintain more than 10 simultaneously active Missing reports.
- **Behavioral Specification**:
  - Before inserting an active Missing report, the backend counts existing reports where `created_by_user_id == current_user.id` and `type == MISSING` and `status == ACTIVE`.
  - If count $\ge 10$, the request must be rejected with HTTP `422 Unprocessable Content`.
- **Threat Addressed**: `THR-REPORT-001`
- **Verification Method**: Seed 10 active Missing reports for a user across previous days. Attempt to create an 11th; assert HTTP 422 Unprocessable Content. Transition 1 to RESOLVED, then create; assert success.

### [SEC-QUOTA-003] Found Report Progressive Daily Tiers
- **Description**: Found reports are subject to progressive daily limits based on account trust tier.
- **Behavioral Specification**:
  - New Account: Max 5 Found reports / day.
  - Established Account: Max 15 Found reports / day.
  - Trusted Account: Max 30 Found reports / day.
  - Quotas reset at midnight Asia/Kolkata.
  - Each distinct physical item found must be reported individually (no batching).
- **Threat Addressed**: `THR-REPORT-001`
- **Verification Method**: Create 6 Found reports on a New Account; assert the 6th returns HTTP 429 Too Many Requests.

### [SEC-QUOTA-004] Transactional Quota Consistency & Concurrency Protection
- **Description**: Quota reservation and report creation must commit atomically without race condition bypass.
- **Behavioral Specification**:
  - Quota checks and consumption must occur within the same PostgreSQL transaction as the report insertion (`SELECT ... FOR UPDATE` or advisory lock on `user_id`).
  - If the report transaction rolls back, no quota slot is consumed.
- **Threat Addressed**: `THR-REPORT-001`
- **Verification Method**: Fire 10 concurrent report creation requests simultaneously using `asyncio.gather` on an account with 2 remaining quota slots. Assert exactly 2 succeed and 8 fail with 429.

---

## 4. Location Privacy & Spatial Security (SEC-LOCATION)

### [SEC-LOCATION-001] Public Coordinate Obfuscation
- **Description**: Public report discovery endpoints must never return high-precision raw GPS incident coordinates.
- **Behavioral Specification**:
  - `GET /api/v1/reports` and public `GET /api/v1/reports/{id}` must return coarsened coordinates (`location_fuzzed`) rounded to a ~1 km grid or jittered by a deterministic radial offset.
  - Raw 7-decimal-place incident coordinates must only be serialized for the authentic report creator in `/me` routes or authorized counterparty in accepted recovery workflows.
- **Threat Addressed**: `THR-LOCATION-001`
- **Verification Method**: Call `GET /api/v1/reports` as an unauthenticated or third-party user; assert returned latitude/longitude differ from exact database incident coordinates by between 500m and 1200m.

### [SEC-LOCATION-002] Spatial Anti-Triangulation & Radius Quantization
- **Description**: Spatial search parameters must prevent coordinate triangulation via microscopic differential radius probes.
- **Behavioral Specification**:
  - `radius_km` parameter must reject non-whitelisted values. Allowed values: `[1.0, 2.0, 5.0, 10.0, 25.0, 50.0]`.
  - Maximum search radius is capped at 50.0 km.
  - Distance values (`distance_km`) in public search responses must be rounded to the nearest 0.5 km.
- **Threat Addressed**: `THR-LOCATION-002`
- **Verification Method**: Call `GET /api/v1/reports?latitude=37.77&longitude=-122.41&radius_km=1.2345`; assert HTTP 422 Unprocessable Content.

---

## 5. Recovery Requests & Handshake Security (SEC-RECOVERY)

### [SEC-RECOVERY-001] Mutual Handshake for Recovery Completion
- **Description**: Recovery requests cannot be unilaterally completed by one party.
- **Behavioral Specification**:
  - When a recovery request is in `ACCEPTED` status, transition to `COMPLETED` requires a 6-digit confirmation PIN generated by the system and visible only to the item owner.
  - Submitting `PATCH /api/v1/recovery-requests/{id}` with `action=complete` requires providing the matching handover PIN.
- **Threat Addressed**: `THR-RECOVERY-001`
- **Verification Method**: Finder attempts to mark recovery request COMPLETED without providing owner's PIN; assert HTTP 422 Unprocessable Content.

### [SEC-RECOVERY-002] Recovery Verification Guessing Rate Limit
- **Description**: Answering recovery verification questions is bounded against brute-force guessing.
- **Behavioral Specification**:
  - Maximum 3 incorrect verification attempts allowed per recovery request.
  - On the 4th failure, the recovery request is automatically transitioned to `REJECTED`, and the requester is placed in a 24-hour cooldown for that report.
- **Threat Addressed**: `THR-RECOVERY-002`
- **Verification Method**: Submit 4 sequential incorrect verification responses; assert request transitions to REJECTED and subsequent attempts return HTTP 422.

---

## 6. File Upload & Storage Security (SEC-UPLOAD)

### [SEC-UPLOAD-001] File Magic-Byte Signature Verification
- **Description**: Uploaded files must match magic byte signatures, regardless of client `Content-Type` header.
- **Behavioral Specification**:
  - Read first 32 bytes of uploaded file. Validate:
    - JPEG: `FF D8 FF`
    - PNG: `89 50 4E 47 0D 0A 1A 0A`
    - WebP: `52 49 46 46` ... `57 45 42 50`
  - Any mismatch must return HTTP `422 Unprocessable Content`.
- **Threat Addressed**: `THR-UPLOAD-001`
- **Verification Method**: Create a text file containing `<?php echo 'exploit'; ?>`, name it `photo.jpg` with `Content-Type: image/jpeg`. Upload to `POST /reports/{id}/images`; assert HTTP 422.

### [SEC-UPLOAD-002] EXIF Metadata & GPS Coordinate Stripping
- **Description**: Uploaded images must be stripped of all EXIF, GPS, device, and private metadata before storage.
- **Behavioral Specification**:
  - Image bytes must be decoded and re-encoded via an image sanitization pipeline.
  - S3 stored files must have zero EXIF or GPS tags.
- **Threat Addressed**: `THR-UPLOAD-002`
- **Verification Method**: Upload a JPEG containing GPS tags (`GPSLatitude`, `GPSLongitude`). Download the stored object from MinIO/S3 and inspect with `exifread`/Pillow; assert zero GPS tags exist.

### [SEC-UPLOAD-003] Image Dimension Bounding
- **Description**: Image dimensions must be bounded to prevent decompression bombs.
- **Behavioral Specification**:
  - Maximum image width: 4096 pixels.
  - Maximum image height: 4096 pixels.
  - Maximum total pixels: 25,000,000 pixels.
- **Threat Addressed**: `THR-DOS-002`
- **Verification Method**: Upload an image with dimensions $5000 \times 5000$; assert HTTP 422 Unprocessable Content.

---

## 7. Device & Push Notification Security (SEC-NOTIFICATION)

### [SEC-NOTIFICATION-001] Active Device Cap per User
- **Description**: Limit the maximum number of active devices per user account to prevent push fanout denial of service.
- **Behavioral Specification**:
  - Maximum 10 simultaneously active user devices per account.
  - Registering an 11th device automatically marks the least-recently active device `is_active = False`.
- **Threat Addressed**: `THR-DOS-001`
- **Verification Method**: Register 12 distinct devices sequentially on a user account; query database and assert exactly 10 have `is_active == True`.

### [SEC-NOTIFICATION-002] Payload Privacy Invariant
- **Description**: Notification payloads must never contain sensitive identifiers or exact coordinates.
- **Behavioral Specification**:
  - FCM data payloads and in-app notification data must exclude: passwords, credential hashes, raw tokens (`fcm_token`, `verification_token`), and raw GPS coordinates (`latitude`, `longitude`, `lat`, `lon`).
- **Threat Addressed**: `THR-NOTIF-002`
- **Verification Method**: Trigger notifications across all 9 notification types; assert payload validation scanner finds zero forbidden keys.

---

## 8. Asynchronous Processing & Kafka Security (SEC-KAFKA)

### [SEC-KAFKA-001] Asynchronous Offset-Commit Boundary Invariant
- **Description**: Handler database mutations and Kafka offset commits must follow strict idempotent boundaries.
- **Behavioral Specification**:
  - DB mutations and idempotency records (`ConsumerEvent`) must commit in the same transaction.
  - A failure to commit Kafka offset after successful DB commit must never re-execute handler side effects during retry.
- **Threat Addressed**: `THR-KAFKA-002`
- **Verification Method**: Simulate offset commit failure; retry consumer record and assert duplicate is safely skipped.

---

## 9. Administrative Governance & Moderation (SEC-ADMIN)

### [SEC-ADMIN-001] Role-Based Access Control on Administrative Operations
- **Description**: Administrative endpoints must require explicit elevated role assignment.
- **Behavioral Specification**:
  - Endpoints under `/api/v1/admin/*` must verify `current_user.role in {MODERATOR, SUPERADMIN}`.
  - Regular user accounts must receive HTTP `403 Forbidden`.
- **Threat Addressed**: `THR-ADMIN-001`
- **Verification Method**: Call an administrative route with a standard user token; assert HTTP 403 Forbidden.

### [SEC-ADMIN-002] Immutable Security Audit Logging
- **Description**: All administrative actions, role assignments, and security-relevant events must generate immutable audit records.
- **Behavioral Specification**:
  - Records in `security_audit_logs` cannot be updated or deleted through application APIs.
- **Threat Addressed**: `THR-AUDIT-001`
- **Verification Method**: Perform a moderation action; assert an audit log row is created with matching operator ID, timestamp, and action description.

---

## 10. Privacy & Data Lifecycle (SEC-PRIVACY)

### [SEC-PRIVACY-001] Transactional User Account Deletion & Anonymization
- **Description**: Support secure account deletion complying with right-to-be-forgotten privacy standards.
- **Behavioral Specification**:
  - Anonymize user personal data (email, name, password hash).
  - Deactivate all user devices and revoke all user sessions.
  - Safely handle cascade deletion across reports, S3 photos, recovery requests, and notifications without leaving orphan assets.
- **Threat Addressed**: `THR-PRIVACY-001`
- **Verification Method**: Create user with reports, images, and devices. Execute account deletion; assert user profile is scrubbed and S3 images are removed.

