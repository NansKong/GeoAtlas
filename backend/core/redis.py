import redis.asyncio as aioredis
from core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def redis_set(key: str, value: str, ttl_seconds: int = 60) -> None:
    r = get_redis()
    await r.setex(key, ttl_seconds, value)


async def redis_get(key: str) -> str | None:
    r = get_redis()
    return await r.get(key)


async def redis_delete(key: str) -> None:
    r = get_redis()
    await r.delete(key)
