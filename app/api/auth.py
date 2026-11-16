import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user, reusable_oauth2_optional
from app.core.config import settings
from app.db.database import get_db
from app.db.models import User, UserSession
from app.schemas.auth import (
    RefreshTokenRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.auth import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    revoke_token,
    revoke_user_tokens,
    verify_access_token,
    verify_password,
)

auth_router = APIRouter()
users_router = APIRouter()


@auth_router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Register a new user.
    """
    email = user_in.email.lower()

    # Check duplicate
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists.",
        )

    user = User(
        name=user_in.name,
        email=email,
        password_hash=hash_password(user_in.password),
    )
    db.add(user)

    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists.",
        )

    return user


@auth_router.post("/login", response_model=Token)
async def login(user_in: UserLogin, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Login and return access and refresh tokens.
    """
    email = user_in.email.lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_in.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate tokens
    refresh_token = generate_refresh_token()
    hashed_rt = hash_token(refresh_token)

    # Create session
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hashed_rt,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Generate session-bound access token (Phase 10.2.1 / SEC-AUTH-003)
    access_token = create_access_token(user.id, session_id=session.id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@auth_router.post("/refresh", response_model=Token)
async def refresh_token_endpoint(
    req: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Refresh access token using a refresh token.
    Rotates the refresh token.
    """
    hashed_rt = hash_token(req.refresh_token)

    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hashed_rt)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if session.revoked_at is not None:
        # Compromise detection (RFC 6819 § 5.2.2.3):
        # A revoked refresh token was re-presented.
        # Invalidate all active sessions for this user.
        await db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == session.user_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        revoke_user_tokens(session.user_id)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked. All active sessions invalidated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if session.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify the user account still exists and is valid
    user = await db.get(User, session.user_id)
    if user is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Rotate refresh token
    new_refresh_token = generate_refresh_token()
    new_hashed_rt = hash_token(new_refresh_token)

    # Revoke old session
    session.revoked_at = datetime.now(UTC)

    # Create new session
    new_expires_at = datetime.now(UTC) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    new_session = UserSession(
        user_id=session.user_id,
        refresh_token_hash=new_hashed_rt,
        expires_at=new_expires_at,
    )

    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    # Generate new access token bound to rotated session
    access_token = create_access_token(session.user_id, session_id=new_session.id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    raw_token: str | None = Depends(reusable_oauth2_optional),
) -> None:
    """Logout by revoking refresh session and invalidating current access tokens."""
    hashed_rt = hash_token(req.refresh_token)

    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hashed_rt)
    )
    session = result.scalar_one_or_none()

    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        revoke_user_tokens(session.user_id)

    if raw_token:
        # Also revoke access token session in PostgreSQL if sid is present
        token_data = verify_access_token(raw_token)
        if token_data:
            sid_str = token_data.get("sid")
            if sid_str:
                try:
                    sid_uuid = uuid.UUID(sid_str)
                    tok_session = await db.get(UserSession, sid_uuid)
                    if tok_session and tok_session.revoked_at is None:
                        tok_session.revoked_at = datetime.now(UTC)
                except ValueError:
                    pass
        revoke_token(raw_token)

    await db.commit()


async def cleanup_expired_sessions(db: AsyncSession, retention_days: int = 30) -> int:
    """Delete user sessions expired longer than retention_days (Phase 10.2.1)."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await db.execute(
        delete(UserSession).where(UserSession.expires_at < cutoff)
    )
    await db.commit()
    return int(cast(CursorResult[Any], result).rowcount)


@users_router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)) -> Any:
    """
    Get current user profile.
    """
    return current_user
