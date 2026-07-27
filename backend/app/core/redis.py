"""Redis client lifecycle plus the two things we use it for on Day 1:
a token denylist and a fixed-window rate limiter.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_pool: ConnectionPool | None = None
_client: Redis | None = None

DENYLIST_PREFIX = "auth:denylist:"
RATE_LIMIT_PREFIX = "ratelimit:"


async def init_redis() -> Redis:
    global _pool, _client
    if _client is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URI,
            decode_responses=True,
            max_connections=50,
            health_check_interval=30,
        )
        _client = Redis(connection_pool=_pool)
        await _client.ping()
        logger.info("redis_connected", host=settings.REDIS_HOST, db=settings.REDIS_DB)
    return _client


async def close_redis() -> None:
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
    logger.info("redis_disconnected")


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis is not initialised. Did the lifespan hook run?")
    return _client


# --- Token denylist ----------------------------------------------------------


async def deny_token(jti: str, ttl_seconds: int) -> None:
    """Revoke an access token until it would have expired anyway."""
    if ttl_seconds <= 0:
        return
    await get_redis().setex(f"{DENYLIST_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_denied(jti: str) -> bool:
    return bool(await get_redis().exists(f"{DENYLIST_PREFIX}{jti}"))


# --- Rate limiting -----------------------------------------------------------


async def check_rate_limit(
    identifier: str, *, limit: int, window_seconds: int
) -> tuple[bool, int, int]:
    """Fixed-window counter.

    Returns `(allowed, remaining, retry_after_seconds)`. Increment and expiry are
    pipelined so two concurrent requests cannot both create a key without a TTL.
    """
    key = f"{RATE_LIMIT_PREFIX}{identifier}"
    async with get_redis().pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = await pipe.execute()

    if ttl is None or ttl < 0:
        await get_redis().expire(key, window_seconds)
        ttl = window_seconds

    if count > limit:
        return False, 0, int(ttl)
    return True, max(limit - int(count), 0), int(ttl)


async def redis_healthcheck() -> dict[str, Any]:
    try:
        await get_redis().ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
