# Boomerang Security Architecture Blueprint
**Phase 10.1 — Technical Security Architecture & Control Specifications**

---

## 1. Security Architecture Overview

The Boomerang security architecture establishes defense-in-depth across the application's presentation, application, data, and asynchronous processing tiers. It is designed to maintain high availability and seamless community collaboration while rigorously defending against spam, location stalking, credential theft, recovery fraud, and resource exhaustion.

```text
                                 [CLIENTS]
                   Flutter Android / iOS / Desktop Web
                                     │
                             (TLS 1.3 / HTTPS)
                                     ▼
               ┌───────────────────────────────────────────┐
               │         API GATEWAY / INGRESS             │
               │  - Reverse Proxy (Nginx / Cloudflare)     │
               │  - IP Rate Limiting & TLS Termination     │
               │  - Security Headers (HSTS, CSP, XFO)      │
               └─────────────────────┬─────────────────────┘
                                     │
                                     ▼
               ┌───────────────────────────────────────────┐
               │          FASTAPI APPLICATION CORE         │
               │  ┌─────────────────────────────────────┐  │
               │  │ Rate Limiting & Quota Middleware    │  │
               │  └──────────────────┬──────────────────┘  │
               │                     ▼                     │
               │  ┌─────────────────────────────────────┐  │
               │  │ Authentication & Session (JWT)      │  │
               │  └──────────────────┬──────────────────┘  │
               │                     ▼                     │
               │  ┌─────────────────────────────────────┐  │
               │  │ Authorization & Ownership Guards    │  │
               │  └──────────────────┬──────────────────┘  │
               │                     ▼                     │
               │  ┌─────────────────────────────────────┐  │
               │  │ Location Privacy & Obfuscation      │  │
               │  └──────────────────┬──────────────────┘  │
               │                     ▼                     │
               │  ┌─────────────────────────────────────┐  │
               │  │ Image Sanitization Pipeline (EXIF)  │  │
               │  └──────────────────┬──────────────────┘  │
               │                     ▼                     │
               │  ┌─────────────────────────────────────┐  │
               │  │ Report Creation Quota Service       │  │
               │  └─────────────────────────────────────┘  │
               └─────────┬───────────────────────┬─────────┘
                         │                       │
           (PostgreSQL Wire / PostGIS)       (S3 API / TLS)
                         │                       │
                         ▼                       ▼
            ┌─────────────────────────┐ ┌─────────────────┐
            │ PostgreSQL 16 + PostGIS │ │ MinIO / AWS S3  │
            │ - Quota Reservations    │ │ - Sanitized     │
            │ - Atomic Outbox Events  │ │   Photos        │
            │ - Fuzzed vs Raw Geoms   │ └─────────────────┘
            │ - User Data & Auth      │
            └────────────┬────────────┘
                         │
                  (aiokafka / TLS)
                         │
                         ▼
            ┌─────────────────────────┐
            │ Apache Kafka KRaft 3.8  │
            │ - Sanitized Event Bus   │
            └────────────┬────────────┘
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
   ┌───────────────────┐   ┌───────────────────┐
   │ Matching Worker   │   │ Push Dispatcher   │
   │ (PostGIS Engine)  │   │ (FCM v1 / WebPush)│
   └───────────────────┘   └───────────────────┘
```

---

## 2. Authentication & Session Boundaries

### 2.1 Token Lifecycle & Cryptographic Specifications
1. **Access Tokens**:
   - Format: Stateless JSON Web Token (JWT), signed with `HS256` or `RS256` using `settings.SECRET_KEY`.
   - Expiration: Strict 15-minute window (`ACCESS_TOKEN_EXPIRE_MINUTES = 15`).
   - Standard Claims:
     - `sub`: User UUID string.
     - `type`: Fixed value `"access"`.
     - `iat`: Issued-at UTC timestamp.
     - `exp`: Expiration UTC timestamp.
     - `jti`: Unique token UUID (for emergency revocation tracking).
2. **Refresh Tokens**:
   - Generation: Cryptographically secure 256-bit entropy via `secrets.token_urlsafe(32)`.
   - Storage: Raw refresh tokens are **never stored** in the database. The database records `UserSession.refresh_token_hash = sha256(token)`.
   - Expiration: 30 days (`REFRESH_TOKEN_EXPIRE_DAYS = 30`).
   - Rotation: Single-use rotation on every `/api/v1/auth/refresh`. Calling refresh atomically revokes the existing session (`revoked_at = now()`) and issues a fresh refresh token and access token in the same transaction.
3. **Session Invalidation & Logout**:
   - Immediate refresh token revocation: `/api/v1/auth/logout` sets `revoked_at = now()` on the target session.
   - User-level token revocation timestamp: Introduce `User.tokens_invalid_before` timestamp. When a user changes password, logs out of all devices, or is suspended, `tokens_invalid_before` is updated to `now()`. Any access token issued prior to this timestamp is rejected immediately in `get_current_user`.

### 2.2 Password Policy & Hashing
- Algorithm: Argon2id via `argon2-cffi` (`ph = PasswordHasher()`).
- Complexity Requirements:
  - Minimum length: 10 characters.
  - Maximum length: 128 characters (prevents CPU denial of service during hashing).
  - Entropy check: Minimum Shannon entropy or rejection of top 10,000 common passwords.
  - No character class restrictions that encourage weak predictable substitutions (e.g. `P@ssword1!`).

---

## 3. Authorization Enforcement & BOLA/IDOR Defense

### 3.1 Declarative Authorization Pattern
FastAPI dependencies must explicitly enforce authorization boundaries rather than relying on ad-hoc controller code. Every route accessing a sensitive resource must pass through an authorization dependency:

```python
# Conceptual Dependency Pattern for Phase 10.2
async def require_report_owner(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Report:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this report"
        )
    return report
```

### 3.2 Subsystem Authorization Matrices

#### Reports Subsystem
- **Create**: Any authenticated user within quota limits.
- **Read (Single/List)**: Public (with location obfuscation applied).
- **Update (Title/Description/Category/Location)**: Creator only, report must be `ACTIVE`.
- **Status Change**:
  - `ACTIVE` $\rightarrow$ `CANCELLED`: Creator only.
  - `ACTIVE` $\rightarrow$ `RESOLVED`: Creator only (or automatically via completed recovery request).
  - `RESOLVED` / `CANCELLED` / `EXPIRED`: Immutable terminal states.
- **Upload Image**: Creator only, report must be `ACTIVE`, max 5 images.
- **Delete Image**: Creator only.

#### Matches Subsystem
- **List Matches for Report**: Creator of the report only (`report.created_by_user_id == current_user.id`).
- **Get Match Detail**: Creator of `report_missing` OR creator of `report_found` only. All other users receive 403 Forbidden.

#### Recovery Requests Subsystem
- **Create**: Authenticated user, `report.status == ACTIVE`, requester $\neq$ report creator, no existing pending/accepted request.
- **View**: Requester OR Recipient (report creator) only.
- **State Transitions**:
  - `PENDING` $\rightarrow$ `ACCEPTED`: Recipient only.
  - `PENDING` $\rightarrow$ `REJECTED`: Recipient only.
  - `PENDING` $\rightarrow$ `CANCELLED`: Requester only.
  - `ACCEPTED` $\rightarrow$ `CANCELLED`: Requester or Recipient.
  - `ACCEPTED` $\rightarrow$ `COMPLETED`: Requires **mutual verification handshake** (see Section 7).

#### Notifications & Devices Subsystem
- **List/Read Notifications**: Target user only (`notification.user_id == current_user.id`).
- **Register Device**: Authenticated user; deactivates identical token on any other account. Max 10 active devices per user.
- **Deactivate Device**: Device owner only (`device.user_id == current_user.id`).

---

## 4. Report Creation Limits & Quota Architecture

### 4.1 Authoritative Business Policy
1. **Missing Reports**:
   - **Daily Limit**: Maximum 5 Missing reports per user per calendar day.
   - **Active Cap**: Maximum 10 simultaneously active Missing reports per user.
   - **Reset Timezone**: Midnight Asia/Kolkata (`UTC+05:30`).
   - **Non-Refundable**: Cancelling, deleting, expiring, or resolving a report consumes its slot permanently for that calendar day.
   - **Active Cap Accounting**: Only reports with `status == ACTIVE` count toward the 10 active cap.
2. **Found Reports (Progressive Trust Tiers)**:
   - **New Account Tier**: Maximum 5 Found reports per calendar day.
   - **Established Account Tier**: Maximum 15 Found reports per calendar day.
   - **Trusted Account Tier**: Maximum 30 Found reports per calendar day.
   - **No Unlimited Tier**: All tiers are strictly bounded.
   - **Single Item Invariant**: Each distinct physical item found must be reported individually. No multi-item batch reports.

### 4.2 Account Trust Progression Model
Progression between Found-report tiers is automatic, deterministic, and resistant to Sybil manipulation:

```text
               ┌───────────────────────┐
               │      NEW ACCOUNT      │ (Limit: 5 Found / day)
               └───────────┬───────────┘
                           │
                           │ Requirements:
                           │  - Account age >= 7 days
                           │  - Email verified (when available)
                           │  - >= 2 legitimate completed recoveries OR
                           │    >= 3 reports with non-spam status for 7+ days
                           │  - Zero moderation flags
                           ▼
               ┌───────────────────────┐
               │  ESTABLISHED ACCOUNT  │ (Limit: 15 Found / day)
               └───────────┬───────────┘
                           │
                           │ Requirements:
                           │  - Account age >= 30 days
                           │  - >= 5 successfully completed recoveries
                           │  - Profile completeness score 100%
                           │  - Positive community confirmation ratio >= 90%
                           │  - Zero active moderation strikes
                           ▼
               ┌───────────────────────┐
               │    TRUSTED ACCOUNT    │ (Limit: 30 Found / day)
               └───────────────────────┘
```

#### Anti-Gaming Principles
- Account age alone **never** elevates tier.
- Flooding the system with reports **never** increases trust (in fact, rapid creation triggers moderation review).
- Active abuse reports, rapid report-and-delete cycles, or rejected recovery claims immediately freeze or downgrade the user's tier.

### 4.3 Centralized Report Creation Quota Service Architecture

To prevent concurrency races (e.g. submitting 10 simultaneous requests to bypass the 5-report limit), quota enforcement must be transactional and centralized in PostgreSQL:

```text
POST /api/v1/reports
         │
         ▼
[Begin PostgreSQL Transaction]
         │
         ▼
[Lock User Quota Row / Advisory Lock: user_id]
         │
         ├─► Calculate user's current day in Asia/Kolkata (UTC+05:30)
         ├─► Query: Count active Missing reports (if type == MISSING)
         │   └─► If active >= 10: ROLLBACK & Return 422 ("Active report cap reached")
         │
         ├─► Query: Daily reports created today in Asia/Kolkata
         │   └─► If Missing created today >= 5: ROLLBACK & Return 429 ("Daily Missing quota reached")
         │   └─► If Found created today >= TierLimit: ROLLBACK & Return 429 ("Daily Found quota reached")
         │
         ▼
[Insert Report Record + Insert Outbox Event]
         │
         ▼
[Increment / Record Daily Consumption in Quota Table]
         │
         ▼
[Commit PostgreSQL Transaction]
```

#### Atomic Guarantees
- **Atomic Reservation**: The quota check, report insert, and quota recording execute in a single atomic database transaction.
- **Rollback Safety**: If report validation fails, image upload fails, or database constraint fails, the entire transaction rolls back; no quota slot is consumed.
- **Client Transparency**: The API response headers and a dedicated `/api/v1/reports/quota` endpoint provide the Flutter client with:
  - `missing_daily_remaining`: Integer (0–5).
  - `missing_active_remaining`: Integer (0–10).
  - `found_daily_remaining`: Integer (0–30).
  - `quota_resets_at`: ISO 8601 UTC timestamp of the next midnight in Asia/Kolkata.

---

## 5. Rate Limiting Architecture & Abuse Prevention (Phase 10.3)

Request frequency rate limits protect system resources and operate independently of business report quotas:

| Tier | Endpoints | Keying Strategy | Limit | Window | Failure Policy | Action on Exceed |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Auth Register** | `POST /api/v1/auth/register` | Client IP (`get_client_ip`) | 5 requests | 1 minute | Fail-Closed (503) | 429 Too Many Requests, `Retry-After` |
| **Auth Login IP** | `POST /api/v1/auth/login` | Client IP (`get_client_ip`) | 10 requests | 1 minute | Fail-Closed (503) | 429 Too Many Requests, `Retry-After` |
| **Auth Login Account** | `POST /api/v1/auth/login` | SHA-256(email) hash | 5 attempts | 1 minute | Fail-Closed (503) | 429 Too Many Requests, `Retry-After` |
| **Discovery (Anon)** | `GET /api/v1/reports` | Client IP (`get_client_ip`) | 10 requests | 1 minute | Fail-Open (degraded) | 429 Too Many Requests, `Retry-After` |
| **Discovery (Auth)** | `GET /api/v1/reports` | User ID + Secondary IP | 30 requests | 1 minute | Fail-Open (degraded) | 429 Too Many Requests, `Retry-After` |

### 5.1 Multi-Layer Rate Limiting Implementation
- **Perimeter Layer (Nginx / Cloudflare)**: Coarse IP rate limiting (protects against raw layer-7 DDoS).
- **Application Layer (Redis Sliding Window)**: Distributed sliding-window log via atomic Redis Lua script (`ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`, `EXPIRE`).
  - RFC 6585 headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`.
- **Client IP & Trusted Proxy Boundary (`app/core/security_ip.py`)**:
  - Direct connection host (`request.client.host`) is strictly authoritative for untrusted peers. If the direct peer is not in `TRUSTED_PROXIES`, any incoming `X-Forwarded-For` header is completely ignored to prevent spoofing.
  - Forwarded headers (`X-Forwarded-For`) are parsed via right-to-left traversal exclusively when received from configured trusted reverse proxies (`settings.TRUSTED_PROXIES`), stepping backward past trusted intermediate proxy hops to find the true client IP.
  - **Production Deployment Configuration Requirement**:
    - In containerized or reverse-proxy deployments (such as behind AWS ALB, Cloudflare, or Nginx Ingress), production operators **must explicitly configure** `TRUSTED_PROXY_IPS` (or environment variable `TRUSTED_PROXIES`) with the exact IP addresses or CIDR blocks of the trusted ingress proxies.
    - Default configuration is deliberately restrictive: `["127.0.0.1", "::1"]` (local loopback only).
    - **Security Rule**: Dangerously broad ranges such as `0.0.0.0/0` or `::/0` must NEVER be configured in `TRUSTED_PROXIES`. Trusting arbitrary networks allows attackers to spoof `X-Forwarded-For` and bypass IP-based rate limits.

### 5.2 Authoritative PostgreSQL Report Quotas & User Trust Tiers
Business report quotas are authoritative and enforced directly in PostgreSQL transactions with row locking (`SELECT ... FOR UPDATE`):
- **Missing Reports**:
  - Daily limit: Maximum 5 reports created per day.
  - Active cap: Maximum 10 simultaneously active (`ReportStatus.ACTIVE`) missing reports.
- **Found Reports (Tiered by `UserTrustTier`)**:
  - `NEW`: 5 found reports per day.
  - `ESTABLISHED`: 15 found reports per day.
  - `TRUSTED`: 30 found reports per day.
- **Quota Reset Boundary**: Authoritative midnight reset in Indian Standard Time (`Asia/Kolkata`, UTC+05:30).
- **Non-Refundable Durability**: Stored in `user_daily_quotas` table; resolving, cancelling, or deleting a report does not restore consumed daily creation quota.
- **Quota Status Endpoint**: `GET /api/v1/reports/quota-status` exposes real-time remaining quotas and `resets_at` timestamp.

---

## 6. Location Privacy & Spatial Security

### 6.1 Dual-Coordinate Model: Raw Incident vs Public Obfuscated
To resolve the critical vulnerability identified in `THR-LOCATION-001`, Boomerang must implement a strict separation between authoritative incident coordinates and public discovery coordinates:

```text
DATABASE MODEL (reports table):
┌────────────────────────────────────────────────────────────────────────┐
│ - location: GEOGRAPHY(POINT, 4326)         <- Precise incident point   │
│ - location_fuzzed: GEOGRAPHY(POINT, 4326)  <- Coarsened public centroid│
│ - location_accuracy: FLOAT                 <- Uncertainty radius (m)   │
└────────────────────────────────────────────────────────────────────────┘

API VISIBILITY RULES:
┌───────────────────────────┬────────────────────────────────────────────┐
│ Context                   │ Coordinates Returned in API Response       │
├───────────────────────────┼────────────────────────────────────────────┤
│ Public Discovery (GET /)  │ location_fuzzed ONLY (Coarsened to ~1 km) │
│ Report Details (Public)   │ location_fuzzed ONLY                       │
│ Report Creator (Own /me)  │ location (Exact raw GPS coordinates)       │
│ Accepted Recovery Counter │ location (Disclosed upon mutual consent)   │
│ Match List & Detail       │ location_fuzzed (for opposite party)       │
│ Notifications & FCM       │ ZERO raw coordinates in payload            │
└───────────────────────────┴────────────────────────────────────────────┘
```

### 6.2 Spatial Anti-Triangulation & Radius Restrictions
1. **Discrete Radius Quantization**:
   - `GeoSearchParams.radius_km` must reject arbitrary floating-point values (e.g. `1.23456 km`).
   - Permitted values: Strict whitelist `[1.0, 2.0, 5.0, 10.0, 25.0, 50.0]` km.
2. **PostGIS Query Hardening**:
   - Internal candidate indexing uses `ST_DWithin` on the GiST-indexed `location`.
   - The returned distance `distance_km` is rounded to the nearest $0.5\text{ km}$ for public callers, preventing distance-based intersection attacks.
3. **Map Anchor Disassociation**:
   - The Flutter client map center (search anchor) is never stored or associated with the user's account profile.

---

## 7. Recovery Verification & Handshake Security

### 7.1 Two-Party Mutual Handshake Protocol
To eliminate unilateral takeover of recovery requests (`THR-RECOVERY-001`), the transition from `ACCEPTED` to `COMPLETED` requires a mutual cryptographic or code-based verification handshake:

```text
  MISSING ITEM OWNER (Alice)                  FOUND ITEM FINDER (Bob)
             │                                           │
             │─── 1. Recovery Request (PENDING) ────────►│
             │                                           │
             │◄── 2. Accept Request (ACCEPTED) ──────────│
             │                                           │
[System generates a 6-digit handover PIN]               │
[Handover PIN displayed to Alice only: e.g. "849201"]    │
             │                                           │
             │--- 3. In-Person Handover Occurs ----------│
             │    Alice provides PIN "849201" to Bob     │
             │                                           │
             │                                 4. Bob submits PIN
             │                                    PATCH /recovery-requests/{id}
             │                                    { action: "complete", pin: "849201" }
             │                                           │
             │◄── 5. Request Status: COMPLETED ──────────┤
             │       Report Status: RESOLVED             │
```

### 7.2 Verification Guessing & Brute-Force Throttling
- When a report owner configures verification questions (e.g. "Describe unique sticker on back"), the counterparty is limited to **maximum 3 verification attempts**.
- After 3 failed attempts, the recovery request is automatically transitioned to `REJECTED`, and the requester is placed in a 24-hour cooldown for that specific report.

---

## 8. File Upload & Storage Security Pipeline

### 8.1 Triple-Gate Image Sanitization Pipeline

```text
Incoming UploadFile
       │
       ▼
[Gate 1: Header & Size Gate]
 ├─ Size <= 5 MB
 └─ Declared Content-Type in ["image/jpeg", "image/png", "image/webp"]
       │
       ▼
[Gate 2: Magic-Byte Signature Inspection]
 ├─ Read first 32 bytes
 ├─ Match against exact magic signatures:
 │   - JPEG: FF D8 FF
 │   - PNG:  89 50 4E 47 0D 0A 1A 0A
 │   - WebP: 52 49 46 46 (RIFF) + 57 45 42 50 (WEBP)
 └─ Reject any mismatch with 422 Unprocessable Content
       │
       ▼
[Gate 3: Safe Parsing & Decompression with Pillow]
 ├─ Inspect header dimensions: width <= 4096, height <= 4096, total_pixels <= 25,000,000
 ├─ Decompress image buffer in isolated memory
 ├─ Strip ALL EXIF, GPS, camera serial, and author metadata
 ├─ Re-encode image into clean, standardized WebP or JPEG buffer
 └─ Enforce extension matching verified image format (.webp / .jpg)
       │
       ▼
[Persist to MinIO/S3 Storage]
 Key: reports/{report_id}/{uuid.uuid4()}.webp
 Content-Type: image/webp
 ACL: Private
```

---

## 9. Suspicious Activity & Moderation Architecture

### 9.1 Multi-Tier Severity Classification Policy
Boomerang adheres strictly to the rule: **Flag suspicious activity for human review rather than automatically blocking legitimate users.**

```text
┌─────────────────┬──────────────────────────────────────────┬─────────────────────────────┐
│ Severity Level  │ Trigger Conditions                       │ Enforcement Action          │
├─────────────────┼──────────────────────────────────────────┼─────────────────────────────┤
│ **LOW**         │ - Rapid search radius adjustments        │ - Log security audit event  │
│ (Monitor)       │ - User updates title/desc 3+ times in 1h │ - No user impact            │
├─────────────────┼──────────────────────────────────────────┼─────────────────────────────┤
│ **MEDIUM**      │ - 3+ failed recovery verification tries │ - Create `moderation_flag`  │
│ (Flag Review)   │ - Report created and cancelled < 5 min   │ - Notify moderation queue   │
│                 │ - High text similarity across categories │ - Normal user access kept   │
├─────────────────┼──────────────────────────────────────────┼─────────────────────────────┤
│ **HIGH**        │ - Submitting 5 recovery claims across    │ - Rate-limit recovery claims│
│ (Restrict Feat) │   different reports within 15 minutes    │ - Delay push notifications  │
│                 │ - 3+ reports flagged for spam by users   │ - Flag for human moderator  │
├─────────────────┼──────────────────────────────────────────┼─────────────────────────────┤
│ **CRITICAL**    │ - Exploit payload detected in image/text │ - Immediately freeze        │
│ (Escalate)      │ - Excessive Sybil registrations from IP  │   creation privileges       │
│                 │ - Credential stuffing pattern detected   │ - Escalate to Superadmin    │
└─────────────────┴──────────────────────────────────────────┴─────────────────────────────┘
```

### 9.2 Human-in-the-Loop Moderation Rules
- **No Automatic Permanent Bans**: Heuristic algorithms never permanently delete or ban accounts autonomously.
- **Automated Restrictions Are Bounded**: Automated restrictions are temporary (e.g. 1-hour or 24-hour claim pause) pending moderator determination.
- **Transparent Appeals**: Any restricted user receives a clear in-app status notice and can submit an appeal through the Flutter client.

---

## 10. Administrative Security & Governance

### 10.1 Role-Based Access Control (RBAC) Specification
Administrative access is governed by three distinct roles:

```text
[SUPERADMIN]
     │
     ├─ System Configuration & Key Rotation
     ├─ Manage Staff / Moderator Accounts
     └─ Permanent Account Purge / GDPR Data Purge
     │
     ▼
[MODERATOR]
     │
     ├─ Review Flagged Reports & Moderation Queue
     ├─ Review Recovery Fraud Disputes
     └─ Issue Temporary Feature Restrictions
     │
     ▼
[REGULAR USER]
     └─ Standard In-Scope Operations (Missing/Found Reports, Recovery, Matches)
```

### 10.2 Administrative Audit Logging
Every administrative or moderation action must generate an append-only record in `security_audit_logs`:
- `id`: UUID.
- `operator_id`: UUID of the administrator.
- `target_user_id`: UUID of the affected user.
- `action`: e.g. `REPORT_REMOVED`, `FLAG_DISMISSED`, `TIER_DOWNGRADED`.
- `reason`: Mandatory text justification.
- `timestamp`: UTC datetime.
- `ip_address`: Operator IP address.

