import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.database import get_db
from app.db.models import User, UserSession
from app.services.auth import verify_access_token

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(reusable_oauth2)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_access_token(token)
    if not token_data:
        raise credentials_exception

    user_id = token_data.get("sub")
    if not user_id:
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise credentials_exception

    # Session-bound token validation (Phase 10.2.2 / SEC-AUTH-003):
    # Production access tokens must be bound to a valid, active UserSession.
    # Reject missing, malformed, or unknown sid claims.
    sid_str = token_data.get("sid")
    if not sid_str:
        raise credentials_exception

    try:
        session_uuid = uuid.UUID(sid_str)
    except ValueError:
        raise credentials_exception

    result = await db.execute(
        select(User, UserSession)
        .join(UserSession, UserSession.user_id == User.id)
        .where(User.id == user_uuid, UserSession.id == session_uuid)
    )
    row = result.first()
    if not row:
        raise credentials_exception
    auth_user, session = row
    if session.revoked_at is not None:
        raise credentials_exception
    now = datetime.now(UTC)
    session_exp = (
        session.expires_at.replace(tzinfo=UTC)
        if session.expires_at.tzinfo is None
        else session.expires_at
    )
    if session_exp < now:
        raise credentials_exception
    return auth_user


reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)


async def get_optional_current_user(
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(reusable_oauth2_optional),
) -> User | None:
    if not token:
        return None
    token_data = verify_access_token(token)
    if not token_data:
        return None
    user_id = token_data.get("sub")
    if not user_id:
        return None
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None

    sid_str = token_data.get("sid")
    if not sid_str:
        return None

    try:
        session_uuid = uuid.UUID(sid_str)
    except ValueError:
        return None

    result = await db.execute(
        select(User, UserSession)
        .join(UserSession, UserSession.user_id == User.id)
        .where(User.id == user_uuid, UserSession.id == session_uuid)
    )
    row = result.first()
    if not row:
        return None
    user, session = row
    if session.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    session_exp = (
        session.expires_at.replace(tzinfo=UTC)
        if session.expires_at.tzinfo is None
        else session.expires_at
    )
    if session_exp < now:
        return None
    return user
