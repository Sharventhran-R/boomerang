from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user
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
    access_token = create_access_token(user.id)
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
        )

    if session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked",
        )

    if session.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
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

    # Generate new access token
    access_token = create_access_token(session.user_id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(req: RefreshTokenRequest, db: AsyncSession = Depends(get_db)) -> None:
    """
    Logout by revoking the refresh session.
    """
    hashed_rt = hash_token(req.refresh_token)

    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hashed_rt)
    )
    session = result.scalar_one_or_none()

    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()


@users_router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)) -> Any:
    """
    Get current user profile.
    """
    return current_user
