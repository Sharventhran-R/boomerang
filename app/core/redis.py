import asyncio
import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def init_redis_pool() -> aioredis.Redis:
    """Initializes the global Redis connection pool and client singleton."""
    global _redis_pool, _redis_client, _redis_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if (
        _redis_client is None
        or _redis_loop is None
        or (current_loop is not None and _redis_loop is not current_loop)
        or _redis_loop.is_closed()
    ):
        logger.info(
            "Initializing Redis connection pool: host=%s port=%s db=%s",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
            settings.REDIS_DB,
        )
        _redis_loop = current_loop
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            max_connections=50,
        )
        _redis_client = aioredis.Redis(connection_pool=_redis_pool)
    return _redis_client


def get_redis_client() -> aioredis.Redis:
    """Returns the global Redis client singleton, initializing it if necessary."""
    return init_redis_pool()


async def close_redis_pool() -> None:
    """Closes the Redis client and connection pool cleanly on shutdown."""
    global _redis_pool, _redis_client, _redis_loop
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as exc:
            logger.warning("Error closing Redis client: %s", exc)
        finally:
            _redis_client = None

    if _redis_pool is not None:
        try:
            await _redis_pool.disconnect()
        except Exception as exc:
            logger.warning("Error disconnecting Redis pool: %s", exc)
        finally:
            _redis_pool = None
            _redis_loop = None


async def check_redis_health() -> bool:
    """Pings Redis to verify connectivity and responsiveness."""
    try:
        client = get_redis_client()
        pong = await client.ping()
        return bool(pong)
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return False
