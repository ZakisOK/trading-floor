"""Redis Streams producer helpers."""
import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from src.core.redis import get_redis
from src.streams.topology import AUDIT


async def produce(
    stream: str,
    data: dict[str, Any],
    redis: Redis | None = None,
) -> str:
    """Produce a message to a Redis Stream. Returns the message ID."""
    r: Redis = redis or get_redis()
    payload: dict[str, str] = {
        k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in data.items()
    }
    payload["_ts"] = datetime.now(UTC).isoformat()
    # redis-py StreamCommands expects Mapping[field, value]; str satisfies the value type
    msg_id: str = await r.xadd(stream, payload, maxlen=100_000, approximate=True)  # type: ignore[arg-type]
    return msg_id


async def produce_audit(
    event_type: str,
    agent_id: str,
    payload: dict[str, Any],
    redis: Redis | None = None,
    cycle_id: str | None = None,
) -> str:
    """Produce an immutable audit event.

    ``cycle_id`` is nullable: most cycle-driven audits (signal_emitted, trade
    executed, kill switch flatten) carry one; non-cycle audits (background
    health checks, monitor heartbeats) leave it empty.
    """
    return await produce(
        AUDIT,
        {
            "event_type": event_type,
            "agent_id": agent_id,
            "payload": payload,
            "cycle_id": cycle_id or "",
        },
        redis,
    )
