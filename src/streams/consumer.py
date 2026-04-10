"""Redis Streams base consumer with auto-ack and error handling."""
import asyncio
import contextlib
from abc import ABC, abstractmethod
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


class BaseConsumer(ABC):
    """Base class for all Redis Streams consumers.

    Subclasses implement `handle(msg_id, fields)` to process each message.
    Consumer groups are created automatically if they do not exist.
    Messages are acknowledged after successful handle() calls.
    """

    def __init__(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        redis: Redis,
    ) -> None:
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name
        self.redis = redis
        self._running = False

    async def start(self) -> None:
        """Start the consumer loop. Blocks until stop() is called."""
        self._running = True
        with contextlib.suppress(Exception):
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)

        while self._running:
            try:
                messages: list[Any] = await self.redis.xreadgroup(
                    self.group,
                    self.consumer_name,
                    {self.stream: ">"},
                    count=10,
                    block=1000,
                )
                for _stream_name, msgs in messages or []:
                    for msg_id, fields in msgs:
                        try:
                            await self.handle(msg_id, fields)
                            await self.redis.xack(self.stream, self.group, msg_id)
                        except Exception as e:
                            logger.error(
                                "consumer_handle_error",
                                stream=self.stream,
                                msg_id=msg_id,
                                error=str(e),
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("consumer_loop_error", stream=self.stream, error=str(e))
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False

    @abstractmethod
    async def handle(self, msg_id: str, fields: dict[str, Any]) -> None:
        """Process a single message. Raise to prevent acknowledgement."""
        ...
