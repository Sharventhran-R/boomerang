import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient, db: AsyncSession) -> None:
    import uuid

    test_email = f"test_{uuid.uuid4()}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Test User", "email": test_email, "password": "password123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test User"
    assert data["email"] == test_email
    assert "id" in data

    # Register duplicate
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Duplicate", "email": test_email, "password": "password123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient, db: AsyncSession) -> None:
    import uuid

    test_email = f"login_{uuid.uuid4()}@example.com"
    # Register
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Login User", "email": test_email, "password": "password123"},
    )

    # Login
    response = await client.post(
        "/api/v1/auth/login", json={"email": test_email, "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_get_users_me(client: AsyncClient, db: AsyncSession) -> None:
    import uuid

    test_email = f"me_{uuid.uuid4()}@example.com"
    # Register & Login
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Me User", "email": test_email, "password": "password123"},
    )
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": test_email, "password": "password123"}
    )
    access_token = login_response.json()["access_token"]

    # Get Me
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_email


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, db: AsyncSession) -> None:
    import uuid

    test_email = f"refresh_{uuid.uuid4()}@example.com"
    # Register & Login
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Refresh User", "email": test_email, "password": "password123"},
    )
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": test_email, "password": "password123"}
    )
    refresh_token = login_response.json()["refresh_token"]

    # Refresh
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, db: AsyncSession) -> None:
    import uuid

    test_email = f"logout_{uuid.uuid4()}@example.com"
    # Register & Login
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Logout User", "email": test_email, "password": "password123"},
    )
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": test_email, "password": "password123"}
    )
    refresh_token = login_response.json()["refresh_token"]

    # Logout
    logout_response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout_response.status_code == 204

    # Try to refresh with revoked token
    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 401
