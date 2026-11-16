import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

ph = PasswordHasher()

# Bounded in-memory revocation tracking for fast-path validation (Phase 10.2 / 10.2.1).
# Backed durably by PostgreSQL UserSession (sid claim in JWT).
MAX_REVOKED_STORE_SIZE = 10_000
_revoked_token_expirations: dict[str, float] = {}
_user_tokens_revoked_after: dict[uuid.UUID, datetime] = {}


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, password)
    except VerifyMismatchError:
        return False


def prune_expired_revocations(now_ts: float | None = None) -> int:
    """Prune expired tokens and outdated user revocation timestamps to bound memory."""
    if now_ts is None:
        now_ts = datetime.now(UTC).timestamp()

    pruned = 0
    expired_keys = [k for k, exp in _revoked_token_expirations.items() if exp <= now_ts]
    for k in expired_keys:
        del _revoked_token_expirations[k]
        pruned += 1

    # Prune user revocation timestamps older than max access token lifespan + buffer
    user_cutoff = now_ts - ((settings.ACCESS_TOKEN_EXPIRE_MINUTES + 5) * 60)
    expired_users = [
        uid
        for uid, rev_dt in _user_tokens_revoked_after.items()
        if rev_dt.timestamp() <= user_cutoff
    ]
    for uid in expired_users:
        del _user_tokens_revoked_after[uid]
        pruned += 1

    return pruned


def create_access_token(
    subject: str | Any, session_id: uuid.UUID | str | None = None
) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode: dict[str, Any] = {
        "exp": expire,
        "sub": str(subject),
        "type": "access",
        "iat": now,
        "jti": uuid.uuid4().hex,
    }
    if session_id is not None:
        to_encode["sid"] = str(session_id)
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def revoke_token(token: str, exp: float | None = None) -> None:
    """Revoke a specific access token by signature/hash and JTI with TTL tracking."""
    now_ts = datetime.now(UTC).timestamp()
    prune_expired_revocations(now_ts)

    if len(_revoked_token_expirations) >= MAX_REVOKED_STORE_SIZE:
        oldest_key = next(iter(_revoked_token_expirations))
        del _revoked_token_expirations[oldest_key]

    default_exp = now_ts + (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    tok_exp = exp if exp is not None else default_exp

    token_hash = hash_token(token)
    _revoked_token_expirations[token_hash] = tok_exp

    try:
        # Attempt unverified decode to extract jti and exp for targeted tracking
        unverified = jwt.decode(token, options={"verify_signature": False})
        jti = unverified.get("jti")
        if jti and isinstance(jti, str):
            jwt_exp = unverified.get("exp")
            resolved_exp = float(jwt_exp) if jwt_exp is not None else tok_exp
            _revoked_token_expirations[jti] = resolved_exp
    except Exception:
        pass


def revoke_user_tokens(user_id: uuid.UUID) -> None:
    """Invalidate all access tokens issued for a user up to the current timestamp."""
    now = datetime.now(UTC)
    prune_expired_revocations(now.timestamp())
    _user_tokens_revoked_after[user_id] = now


def clear_revocation_store() -> None:
    """Clear in-memory revocation store (used in test isolation)."""
    _revoked_token_expirations.clear()
    _user_tokens_revoked_after.clear()


def is_token_revoked(
    decoded_token: dict[str, Any], raw_token: str | None = None
) -> bool:
    """Check whether a token or its user's sessions have been explicitly revoked."""
    now_ts = datetime.now(UTC).timestamp()

    if raw_token:
        tok_hash = hash_token(raw_token)
        if tok_hash in _revoked_token_expirations:
            if _revoked_token_expirations[tok_hash] > now_ts:
                return True
            else:
                del _revoked_token_expirations[tok_hash]

    jti = decoded_token.get("jti")
    if jti and isinstance(jti, str) and jti in _revoked_token_expirations:
        if _revoked_token_expirations[jti] > now_ts:
            return True
        else:
            del _revoked_token_expirations[jti]

    sub = decoded_token.get("sub")
    if sub:
        try:
            user_uuid = uuid.UUID(str(sub))
            revoked_after = _user_tokens_revoked_after.get(user_uuid)
            if revoked_after is not None:
                iat = decoded_token.get("iat")
                if iat is not None:
                    # PyJWT serializes iat to unix timestamp integer
                    iat_ts = (
                        iat.timestamp() if isinstance(iat, datetime) else float(iat)
                    )
                    if iat_ts <= revoked_after.timestamp():
                        return True
        except ValueError:
            return True

    return False


def verify_access_token(token: str) -> dict[str, Any] | None:
    try:
        decoded_token = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        if decoded_token.get("type") != "access":
            return None
        if is_token_revoked(decoded_token, raw_token=token):
            return None
        return decoded_token
    except jwt.PyJWTError:
        return None


def generate_refresh_token() -> str:
    # Generate a cryptographically secure random url-safe string
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Use SHA-256 to hash the refresh token before storing it
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
