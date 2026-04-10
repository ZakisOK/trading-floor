"""Create all Redis Streams and consumer groups on startup.

Run once before starting the application, or on every deploy (idempotent).
"""
import asyncio

import structlog

from src.core.redis import ensure_consumer_group, get_redis
from src.streams.topology import CONSUMER_GROUPS

logger = structlog.get_logger()

# Map each consumer group to the streams it should consume from
GROUP_STREAM_MAP: dict[str, list[str]] = {
    "cg:market_analysts": ["stream:market_data", "stream:agent:tasks"],
    "cg:risk_managers": ["stream:signals:raw"],
    "cg:executors": ["stream:signals:validated"],
    "cg:portfolio": ["stream:signals:validated", "stream:trades", "stream:agent:results"],
    "cg:ws_broadcast": [
        "stream:market_data",
        "stream:orders",
        "stream:pnl",
        "stream:alerts",
        "stream:agent:results",
    ],
    "cg:audit_writer": ["stream:trades", "stream:pnl", "stream:audit"],
}


async def bootstrap() -> None:
    """Create all consumer groups. Idempotent — safe to run on every deploy."""
    r = get_redis()
    for group_key, group_name in CONSUMER_GROUPS.items():
        streams = GROUP_STREAM_MAP.get(group_name, [])
        for stream in streams:
            await ensure_consumer_group(stream, group_name)
            logger.info("bootstrap_consumer_group", group=group_name, stream=stream)
    await r.aclose()
    logger.info("bootstrap_complete", groups=len(CONSUMER_GROUPS))


if __name__ == "__main__":
    asyncio.run(bootstrap())
