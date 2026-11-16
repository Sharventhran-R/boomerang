# Boomerang — Phase 10.2: API Security & Authentication Hardening

## 1. Executive Summary

Phase 10.2 audited, verified, and hardened API authentication, token lifecycles, and resource-level authorization across the Boomerang FastAPI backend. Building upon Phase 10.1's threat model and location privacy boundaries, Phase 10.2 establishes strict defense-in-depth against broken authentication, horizontal privilege escalation (BOLA/IDOR), token reuse/hijacking, and credential enumeration.

All improvements were achieved **without database migrations** or breaking schema changes, maintaining full backward compatibility with the existing PostgreSQL/PostGIS models, Kafka event streams, and Flutter client applications.

---

## 2. API Authorization & Access Control Inventory

Every endpoint in the Boomerang API was audited and cataloged with its enforced authorization policy:

| Method | Endpoint | Authorization Policy | Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Public (Unauthenticated) | Argon2id hashing, unique email check, password bounds [8, 128], non-blank name validation. |
| `POST` | `/api/v1/auth/login` | Public (Unauthenticated) | Argon2id verification, password bounds $\le 128$, generic error detail `"Incorrect email or password"`. |
| `POST` | `/api/v1/auth/refresh` | Public with Refresh Token | Validates SHA-256 hash in `user_sessions`, checks expiration, enforces RFC 6819 compromise detection on revoked tokens, verifies active user existence. |
| `POST` | `/api/v1/auth/logout` | Authenticated or Token Holder | Revokes `user_sessions` refresh token, registers access token in revocation store (`SEC-AUTH-003`). |
| `GET` | `/api/v1/users/me` | Authenticated User | Requires valid unrevoked access token; returns caller's own profile without `password_hash`. |
| `POST` | `/api/v1/reports` | Authenticated User | Server binds `created_by_user_id = current_user.id`; rejects rewards on `FOUND` reports. |
| `GET` | `/api/v1/reports/me` | Authenticated User | Scoped strictly to `user_id = current_user.id`; returns exact coordinates and distances. |
| `GET` | `/api/v1/reports` | Public / Optional Auth | Public coordinates coarsened (~1.1 km); search origin grid-snapped; distance bucketed (500m); non-owners receive 0.5 km quantized distance; owners receive exact metrics for own items. |
| `GET` | `/api/v1/reports/{id}` | Public / Optional Auth | Non-owners receive coarsened coordinates; 404 if not found. |
| `PATCH` | `/api/v1/reports/{id}` | Report Creator Only | 404 if report missing; 403 Forbidden if `created_by_user_id != current_user.id`; validates status state transitions; terminal states are immutable. |
| `POST` | `/api/v1/reports/{id}/images` | Report Creator Only | 404 if report missing; 403 Forbidden if `created_by_user_id != current_user.id`. |
| `DELETE` | `/api/v1/reports/{id}/images/{img_id}` | Report Creator Only | 404 if report/image missing; 403 Forbidden if `created_by_user_id != current_user.id`. |
| `POST` | `/api/v1/recovery-requests` | Authenticated Non-Owner | Rejects requests on user's own reports (400); rejects non-ACTIVE reports (400); prevents duplicate pending/accepted requests (409). |
| `GET` | `/api/v1/recovery-requests` | Request Participants Only | Scoped strictly to `user_id in (requester_id, recipient_id)`. Zero third-party data leakage. |
| `GET` | `/api/v1/recovery-requests/{id}` | Request Participants Only | 404 if missing; 403 Forbidden if `current_user.id not in (requester_id, recipient_id)`. |
| `PATCH` | `/api/v1/recovery-requests/{id}` | Request Participants Only | 404 if missing; 403 Forbidden if caller not participant; role-scoped status transitions (`PENDING` -> `ACCEPTED`/`REJECTED` by recipient; `CANCELLED` by requester); terminal states immutable. |
| `GET` | `/api/v1/reports/{id}/matches` | Report Creator Only | 404 if report missing; 403 Forbidden if `created_by_user_id != current_user.id`; opposite report coordinates coarsened and distance quantized. |
| `GET` | `/api/v1/matches/{id}` | Match Participants Only | 404 if match missing; 403 Forbidden if caller owns neither `report_missing` nor `report_found`; opposite report coordinates coarsened and distance quantized. |
| `GET` | `/api/v1/notifications` | Target User Only | Scoped strictly to `user_id = current_user.id`; sensitive tokens and coordinates purged. |
| `GET` | `/api/v1/notifications/unread-count` | Target User Only | Scoped strictly to `user_id = current_user.id`. |
| `PATCH` | `/api/v1/notifications/read-all` | Target User Only | Updates strictly `user_id = current_user.id`. |
| `POST` | `/api/v1/notifications/mark-all-read` | Target User Only | Alias for `read-all`. |
| `PATCH` | `/api/v1/notifications/{id}/read` | Target User Only | Scoped to `user_id = current_user.id AND id = notif_id`; returns 404 if not found (zero IDOR enumeration). |
| `GET` | `/api/v1/notifications/preferences` | Target User Only | Scoped strictly to `user_id = current_user.id`. |
| `PATCH` | `/api/v1/notifications/preferences` | Target User Only | Updates strictly `user_id = current_user.id`. |
| `POST` | `/api/v1/devices/register` | Authenticated User | Binds device to `current_user.id`; deactivates stale active tokens on other accounts; raw token never returned. |
| `DELETE` | `/api/v1/devices/{device_id}` | Device Owner Only | Scoped to `user_id = current_user.id AND device_id = device_id`; returns 404 if not found (zero IDOR enumeration). |
| `GET` | `/health` | Public (Unauthenticated) | Reports operational database connectivity. |

---

## 3. Vulnerability Findings & Mitigations

### 3.1 Refresh Token Reuse Compromise Detection (RFC 6819 § 5.2.2.3)
- **Vulnerability**: Previously, when an adversary or client re-submitted an already-revoked refresh token, the endpoint returned `401 Unauthorized` without invalidating the active session. If an attacker had intercepted a token prior to rotation, the compromised session family remained active.
- **Remediation**: Implemented RFC 6819 compromise detection in [app/api/auth.py](file:///d:/PROJECTS/GetMe/app/api/auth.py#L131-L150). When a revoked refresh token is presented, all active sessions for that `user_id` are immediately revoked in PostgreSQL (`UserSession.revoked_at = now()`), and all access tokens for that user are revoked in the in-memory revocation store, neutralizing unauthorized persistence.

### 3.2 Account Existence Enforcement on Refresh
- **Vulnerability**: `POST /api/v1/auth/refresh` verified the `UserSession` table but did not query the `User` table to confirm that the underlying user account was still present and active.
- **Remediation**: Added explicit account verification in [app/api/auth.py](file:///d:/PROJECTS/GetMe/app/api/auth.py#L158-L167):
  ```python
  user = await db.get(User, session.user_id)
  if user is None:
      session.revoked_at = datetime.now(UTC)
      await db.commit()
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="User account not found or disabled",
          headers={"WWW-Authenticate": "Bearer"},
      )
  ```

### 3.3 Session-Bound Access Token Revocation (`SEC-AUTH-003`)
- **Vulnerability**: JWT access tokens are stateless by default and were previously valid until expiration (30 minutes) even after calling `POST /api/v1/auth/logout` or detecting refresh-token replay. Furthermore, in-memory revocation stores were wiped on restart and isolated per Uvicorn worker.
- **Remediation & Architecture**:
  - **Durable PostgreSQL Session Revocation**: Access tokens are bound via the RFC 8693 `sid` (Session ID) claim to existing `UserSession.id` UUID primary keys in PostgreSQL. When `logout` is invoked or compromise detection triggers, `UserSession.revoked_at = now()` is committed to PostgreSQL. `get_current_user` performs an indexed join on `UserSession` and verifies `session.revoked_at is None` and `session.expires_at >= now()`, guaranteeing revocation persists across process restarts, separate workers, and distributed replicas.
  - **Local In-Memory Optimization**: Bounded cache `_revoked_token_expirations` (max 10,000 entries) with `prune_expired_revocations()` provides fast-path local rejection without unbounded memory growth.
  - **Legacy & Unbound Token Rejection (Phase 10.2.2)**: `get_current_user` strictly rejects any access token missing `sid`, containing malformed `sid`, referencing non-existent sessions, or referencing sessions belonging to another user (HTTP 401 Unauthorized). Optional authentication endpoints degrade gracefully to the public view without 500 errors.
  - **Database Session Cleanup Maintenance & Scheduling Status**: Implemented `cleanup_expired_sessions(db, retention_days=30)` in `app/api/auth.py` to delete expired sessions older than 30 days while preserving active and recently revoked sessions for RFC 6819 replay detection. **Scheduling Status:** Cleanup is currently an explicit maintenance function and is **not** automated by a background cron/scheduler in this phase.

### 3.4 Password Length Bounding & DoS Mitigation (`SEC-AUTH-004`)
- **Vulnerability**: Argon2id password hashing is intentionally CPU- and memory-intensive. The absence of an upper length limit on passwords allowed attackers to submit multi-megabyte payloads, causing CPU exhaustion and event loop starvation.
- **Remediation**: In [app/schemas/auth.py](file:///d:/PROJECTS/GetMe/app/schemas/auth.py#L17-L29), enforced `max_length=128` on `UserCreate.password` and `UserLogin.password`. Also enforced non-whitespace validation on `name` and length limits on `refresh_token` (`max_length=512`).

### 3.5 Information Disclosure Hardening in Global Exception Handler
- **Vulnerability**: `app/main.py` returned `{"detail": str(exc)}` on unhandled 500 exceptions, risking leakage of SQL queries, table names, and internal paths to callers.
- **Remediation**: Updated global exception handler in [app/main.py](file:///d:/PROJECTS/GetMe/app/main.py#L84-L92) to return generic `{"detail": "Internal server error"}` while logging full diagnostic traces to server logs.

---

## 4. Verification & Quality Gates

The implementation was validated through the dedicated security test suite `tests/test_api_security_hardening.py` (33 automated tests across Phase 10.2, 10.2.1, and 10.2.2) and comprehensive backend regression suites:

```text
- tests/test_api_security_hardening.py: 33 passed (100%)
- Full backend regression suite: 73 passed in 127s (100%)
  (test_api_security_hardening.py, test_auth.py, test_reports.py, test_recovery.py,
   test_geo_privacy_hardening.py, test_geo_inference_containment.py)
```

### Static Analysis
- **Ruff Linter**: `ruff check .` $\rightarrow$ Clean (0 errors).
- **Ruff Formatter**: `ruff format --check .` $\rightarrow$ Clean (107 files formatted).
- **Strict Mypy**: `mypy .` $\rightarrow$ Clean (0 issues in 93 source files).
- **Alembic Schema Check**: `alembic check` $\rightarrow$ Clean (0 unmanaged schema drift).
- **Flutter Analysis**: `flutter analyze` $\rightarrow$ Clean (0 issues in 2.2s).
- **Flutter Unit & Widget Tests**: 35 passed.

---

## 5. Remaining Risks & Phase Dependencies

1. **Redis Rate Limiting & Quotas (Phase 10.3)**:
   - High-speed credential stuffing on `/auth/login` and mass registration attacks on `/auth/register` require Redis token-bucket IP/account rate limits (`SEC-AUTH-001`, `SEC-AUTH-002`).
2. **File Upload Security (Phase 10.4)**:
   - File magic-byte validation, EXIF coordinate stripping, and dimension bounds will be implemented in Phase 10.4 (`SEC-UPLOAD-001`, `SEC-UPLOAD-002`).
3. **Recovery Mutual Handshake (Phase 10.5)**:
   - Two-party verification PIN handshake before transition from `ACCEPTED` to `COMPLETED` is scheduled for Phase 10.5 (`SEC-RECOVERY-001`).
4. **Administrative Governance & RBAC (Phase 10.7)**:
   - Currently, zero administrative endpoints exist. Formal RBAC (`require_role("MODERATOR")`) will accompany moderation APIs in Phase 10.7 (`SEC-ADMIN-001`).

