from typing import Any

import redis.asyncio as aioredis

from src.core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def produce(stream: str, fields: dict[str, Any], maxlen: int = 10_000) -> str:
    """Append a message to a Redis Stream. Returns the message ID."""
    client = get_redis()
    msg_id: str = await client.xadd(stream, fields, maxlen=maxlen, approximate=True)
    return msg_id


async def ensure_consumer_group(stream: str, group: str) -> None:
    """Create a consumer group if it does not already exist."""
    client = get_redis()
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
