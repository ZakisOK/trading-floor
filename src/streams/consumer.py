"""Redis Streams consumer base class stub."""
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as aioredis

from src.core.redis import get_redis, ensure_consumer_group


class BaseConsumer(ABC):
    """Base class for all Redis Streams consumers."""

    stream: str
    group: str
    consumer_name: str

    def __init__(self, consumer_name: str) -> None:
        self.consumer_name = consumer_name

    async def start(self) -> None:
        await ensure_consumer_group(self.stream, self.group)
        await self._consume_loop()

    async def _consume_loop(self) -> None:
        client = get_redis()
        while True:
            results: list[Any] = await client.xreadgroup(
                groupname=self.group,
                consumername=self.consumer_name,
                streams={self.stream: ">"},
                count=10,
                block=1000,
            )
            for _stream, messages in results:
                for msg_id, fields in messages:
                    await self.handle(msg_id, fields)
                    await client.xack(self.stream, self.group, msg_id)

    @abstractmethod
    async def handle(self, msg_id: str, fields: dict[str, Any]) -> None: ...
