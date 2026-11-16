import asyncio
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from starlette.requests import Request

from app.core.security_ip import get_client_ip
from app.services.rate_limiter import (
    RateLimitResult,
    check_rate_limit,
    enforce_rate_limit,
)


@pytest.mark.asyncio
async def test_sliding_window_basic_allow_and_limit() -> None:
    """1-3. Verifies sliding window Lua script enforces limit and retry-after."""
    key = f"test:rl:{uuid.uuid4()}"
    limit = 3
    window = 10

    # 1st request
    res1 = await check_rate_limit(key, limit=limit, window_seconds=window)
    assert res1.allowed is True
    assert res1.limit == limit
    assert res1.remaining == 2
    assert res1.retry_after == 0

    # 2nd request
    res2 = await check_rate_limit(key, limit=limit, window_seconds=window)
    assert res2.allowed is True
    assert res2.remaining == 1

    # 3rd request (at limit)
    res3 = await check_rate_limit(key, limit=limit, window_seconds=window)
    assert res3.allowed is True
    assert res3.remaining == 0

    # 4th request (exceeds limit)
    res4 = await check_rate_limit(key, limit=limit, window_seconds=window)
    assert res4.allowed is False
    assert res4.remaining == 0
    assert res4.retry_after > 0


@pytest.mark.asyncio
async def test_sliding_window_concurrency_atomicity() -> None:
    """4. Verifies 20 concurrent requests with limit 10: exactly 10 pass, 10 fail."""
    key = f"test:rl:concurrent:{uuid.uuid4()}"
    limit = 10
    window = 15

    results = await asyncio.gather(
        *(check_rate_limit(key, limit=limit, window_seconds=window) for _ in range(20))
    )

    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]
    assert len(allowed) == 10
    assert len(denied) == 10
    for r in denied:
        assert r.retry_after > 0


@pytest.mark.asyncio
async def test_enforce_rate_limit_headers() -> None:
    """5. Verifies HTTP 429 exception contains standard rate-limiting headers."""
    denied_result = RateLimitResult(
        allowed=False,
        limit=5,
        remaining=0,
        reset_seconds=60,
        retry_after=42,
    )

    with pytest.raises(Exception) as exc_info:
        enforce_rate_limit(denied_result)

    exc = exc_info.value
    assert getattr(exc, "status_code", None) == 429
    headers = getattr(exc, "headers", {})
    assert headers["Retry-After"] == "42"
    assert headers["X-RateLimit-Limit"] == "5"
    assert headers["X-RateLimit-Remaining"] == "0"
    assert headers["X-RateLimit-Reset"] == "60"


@pytest.mark.asyncio
async def test_fail_closed_on_redis_error_for_critical_paths() -> None:
    """6. Verifies fail_closed=True raises HTTP 503 when Redis is unavailable."""
    with patch(
        "app.services.rate_limiter.get_redis_client",
        side_effect=ConnectionError("Redis connection refused"),
    ):
        with pytest.raises(Exception) as exc_info:
            await check_rate_limit(
                "test:key", limit=5, window_seconds=60, fail_closed=True
            )
        exc = exc_info.value
        assert getattr(exc, "status_code", None) == 503
        detail_msg = str(getattr(exc, "detail", ""))
        assert "Rate limiting service temporarily unavailable" in detail_msg


@pytest.mark.asyncio
async def test_fail_open_on_redis_error_for_discovery() -> None:
    """7. Verifies fail_closed=False allows requests to proceed if Redis fails."""
    with patch(
        "app.services.rate_limiter.get_redis_client",
        side_effect=ConnectionError("Redis connection refused"),
    ):
        res = await check_rate_limit(
            "test:key", limit=10, window_seconds=60, fail_closed=False
        )
        assert res.allowed is True


def test_trusted_proxy_logic_and_spoofing_defense() -> None:
    """8-10. Verifies untrusted direct peer cannot spoof X-Forwarded-For."""

    def build_request(client_host: str, xff: str | None = None) -> Request:
        headers: list[tuple[bytes, bytes]] = []
        if xff:
            headers.append((b"x-forwarded-for", xff.encode("utf-8")))
        scope = {
            "type": "http",
            "client": (client_host, 12345),
            "headers": headers,
        }
        return Request(scope)

    trusted_list = ["127.0.0.1", "::1", "10.0.0.0/24"]

    # 1. Untrusted peer connection with forged XFF
    req_untrusted = build_request(client_host="203.0.113.195", xff="1.1.1.1, 8.8.8.8")
    assert get_client_ip(req_untrusted, trusted_list=trusted_list) == "203.0.113.195"

    # 2. Trusted proxy peer connection with XFF
    req_trusted = build_request(client_host="127.0.0.1", xff="198.51.100.44")
    assert get_client_ip(req_trusted, trusted_list=trusted_list) == "198.51.100.44"

    # 3. Multi-proxy chain: client -> proxy1 (trusted) -> proxy2 (trusted)
    req_chain = build_request(
        client_host="127.0.0.1",
        xff="198.51.100.77, 10.0.0.5, 127.0.0.1",
    )
    assert get_client_ip(req_chain, trusted_list=trusted_list) == "198.51.100.77"

    # 4. Malformed XFF falls back safely to peer host
    req_malformed = build_request(
        client_host="127.0.0.1", xff="<script>alert(1)</script>"
    )
    assert get_client_ip(req_malformed, trusted_list=trusted_list) == "127.0.0.1"


@pytest.mark.asyncio
async def test_register_rate_limit_endpoint(client: AsyncClient) -> None:
    """11. Verifies /api/v1/auth/register enforces IP limit (5 per minute)."""
    # 5 registrations from same IP should succeed
    for i in range(5):
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "name": f"User {i}",
                "email": f"reg_limit_{i}_{uuid.uuid4()}@example.com",
                "password": "Password123!",
            },
        )
        assert res.status_code == 201, res.text
        assert "X-RateLimit-Limit" in res.headers

    # 6th registration from same IP must be rejected with 429
    res_rejected = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "User Exceeded",
            "email": f"reg_limit_exceeded_{uuid.uuid4()}@example.com",
            "password": "Password123!",
        },
    )
    assert res_rejected.status_code == 429
    assert res_rejected.headers.get("Retry-After") is not None
    assert "Rate limit exceeded" in res_rejected.json()["detail"]


@pytest.mark.asyncio
async def test_login_account_identifier_throttling(client: AsyncClient) -> None:
    """12. Verifies account-based throttling limits failed attempts per email to 5."""
    target_email = f"target_{uuid.uuid4()}@example.com"

    # Register target account
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Target User",
            "email": target_email,
            "password": "CorrectPassword123!",
        },
        headers={"X-Forwarded-For": "10.10.10.1"},
    )

    # 5 failed login attempts for this target account from different IPs
    for i in range(5):
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email, "password": "WrongPassword!"},
            headers={"X-Forwarded-For": f"192.168.1.{i + 1}"},
        )
        # Should return 401 generic error (not revealing account existence)
        assert res.status_code == 401
        assert res.json()["detail"] == "Incorrect email or password"

    # 6th attempt for the SAME email must be throttled with HTTP 429
    res_throttled = await client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": "WrongPassword!"},
        headers={"X-Forwarded-For": "192.168.1.99"},
    )
    assert res_throttled.status_code == 429
    assert res_throttled.headers.get("Retry-After") is not None


@pytest.mark.asyncio
async def test_reports_discovery_rate_limiting(client: AsyncClient) -> None:
    """13. Verifies GET /api/v1/reports enforces discovery rate limits with headers."""
    # Anonymous discovery: 10 allowed, 11th gets 429
    ip = "172.16.0.42"
    for i in range(10):
        res = await client.get("/api/v1/reports", headers={"X-Forwarded-For": ip})
        assert res.status_code == 200, res.text
        assert res.headers["X-RateLimit-Limit"] == "10"

    res_rejected = await client.get("/api/v1/reports", headers={"X-Forwarded-For": ip})
    assert res_rejected.status_code == 429
    assert res_rejected.headers.get("Retry-After") is not None
