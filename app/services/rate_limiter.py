import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.redis import get_redis_client
from app.core.security_ip import get_client_ip

logger = logging.getLogger(__name__)

LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local clear_before = now - (window * 1000)

-- 1. Remove expired timestamps
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. Count current entries in window
local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    -- Allowed: record request
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    local remaining = limit - (current_requests + 1)
    return {1, limit, remaining, window, 0}
else
    -- Denied: find earliest entry to calculate retry_after
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 1
    if #oldest >= 2 then
        local oldest_ts = tonumber(oldest[2])
        local reset_time = oldest_ts + (window * 1000)
        local diff_ms = reset_time - now
        if diff_ms > 0 then
            retry_after = math.ceil(diff_ms / 1000)
        end
    end
    return {0, limit, 0, window, retry_after}
end
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60,
    fail_closed: bool = True,
) -> RateLimitResult:
    """Executes atomic sliding-window rate limit check in Redis using Lua script."""
    if not settings.RATE_LIMIT_ENABLED:
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=limit,
            reset_seconds=window_seconds,
            retry_after=0,
        )

    try:
        client = get_redis_client()
        script = client.register_script(LUA_SLIDING_WINDOW)
        now_ms = int(time.time() * 1000)
        member = f"{now_ms}_{uuid.uuid4().hex[:8]}"

        raw_res: Any = await script(
            keys=[key],
            args=[now_ms, window_seconds, limit, member],
        )

        allowed_flag = int(raw_res[0]) == 1
        res_limit = int(raw_res[1])
        remaining = int(raw_res[2])
        reset_sec = int(raw_res[3])
        retry_after = int(raw_res[4])

        return RateLimitResult(
            allowed=allowed_flag,
            limit=res_limit,
            remaining=remaining,
            reset_seconds=reset_sec,
            retry_after=retry_after,
        )
    except Exception as exc:
        logger.warning("Redis rate limiter exception for key '%s': %s", key, exc)
        if fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service temporarily unavailable",
            ) from exc
        # Fail open for non-critical paths
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=1,
            reset_seconds=window_seconds,
            retry_after=0,
        )


def enforce_rate_limit(
    result: RateLimitResult, response: Response | None = None
) -> None:
    """Sets standard HTTP rate limit headers and raises 429 if limit is exceeded."""
    if response is not None:
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_seconds)

    if not result.allowed:
        headers = {
            "Retry-After": str(result.retry_after),
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(result.reset_seconds),
        }
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
            headers=headers,
        )


async def check_register_rate_limit(
    request: Request, response: Response | None = None
) -> None:
    """Enforces IP-based rate limiting on user registration."""
    client_ip = get_client_ip(request)
    key = f"rl:auth:register:ip:{client_ip}"
    result = await check_rate_limit(
        key=key,
        limit=settings.RATE_LIMIT_REGISTER_IP_LIMIT,
        window_seconds=60,
        fail_closed=True,
    )
    enforce_rate_limit(result, response=response)


async def check_login_rate_limits(
    request: Request, email: str, response: Response | None = None
) -> None:
    """Enforces IP and account-identifier rate limiting on user login."""
    client_ip = get_client_ip(request)

    # 1. IP-level rate limit
    ip_key = f"rl:auth:login:ip:{client_ip}"
    ip_res = await check_rate_limit(
        key=ip_key,
        limit=settings.RATE_LIMIT_LOGIN_IP_LIMIT,
        window_seconds=60,
        fail_closed=True,
    )
    enforce_rate_limit(ip_res, response=response)

    # 2. Account-identifier rate limit
    email_clean = email.strip().lower()
    email_hash = hashlib.sha256(email_clean.encode("utf-8")).hexdigest()[:16]
    acc_key = f"rl:auth:login:acc:{email_hash}"
    acc_res = await check_rate_limit(
        key=acc_key,
        limit=settings.RATE_LIMIT_LOGIN_ACCOUNT_LIMIT,
        window_seconds=60,
        fail_closed=True,
    )
    enforce_rate_limit(acc_res, response=response)


async def check_reports_discovery_rate_limits(
    request: Request,
    user_id: uuid.UUID | None = None,
    response: Response | None = None,
) -> None:
    """Enforces geographic discovery rate limits.

    - Anonymous: 10 requests / minute per IP (fail-open if Redis down)
    - Authenticated: 30 requests / minute per user ID (fail-open if Redis down)
    """
    client_ip = get_client_ip(request)

    if user_id is None:
        # Anonymous discovery
        key = f"rl:reports:anon:ip:{client_ip}"
        res = await check_rate_limit(
            key=key,
            limit=settings.RATE_LIMIT_REPORTS_ANONYMOUS_LIMIT,
            window_seconds=60,
            fail_closed=False,
        )
        enforce_rate_limit(res, response=response)
    else:
        # Authenticated discovery: rate limit primarily by user ID
        user_key = f"rl:reports:auth:usr:{user_id}"
        user_res = await check_rate_limit(
            key=user_key,
            limit=settings.RATE_LIMIT_REPORTS_AUTHENTICATED_LIMIT,
            window_seconds=60,
            fail_closed=False,
        )
        enforce_rate_limit(user_res, response=response)

        # Secondary IP ceiling to prevent single-IP botnets with multiple tokens
        ip_key = f"rl:reports:auth:ip:{client_ip}"
        ip_res = await check_rate_limit(
            key=ip_key,
            limit=settings.RATE_LIMIT_REPORTS_AUTHENTICATED_LIMIT * 2,
            window_seconds=60,
            fail_closed=False,
        )
        enforce_rate_limit(ip_res, response=None)
