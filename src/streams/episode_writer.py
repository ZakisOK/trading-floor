"""EpisodeWriter — Redis Streams → Postgres agent_episodes consumer (Week 1 / B4).

Drains ``stream:episodes`` (consumer group ``cg:episode_writer``) into the
``agent_episodes`` Timescale hypertable. Idempotent on ``episode_id`` so a
re-delivered message is a no-op.

Failure modes:
- Postgres unavailable → message is NOT acked, BaseConsumer logs the error
  and retries on the next sweep. Redis stream buffers up to EPISODES_MAXLEN.
- Malformed payload → log + ack so the bad message doesn't poison the group.
  Bad rows surface in the runbook's ``stream:episodes`` lag dashboard.
- Duplicate episode_id → ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.streams.consumer import BaseConsumer
from src.streams.topology import EPISODES

logger = structlog.get_logger()


_INSERT_SQL = text(
    """
    INSERT INTO agent_episodes (
        episode_id, ts, cycle_id, cycle_started_at, subsystem, symbol,
        agent_id, agent_version, market_snapshot, input_state,
        prompt, raw_response, parsed_signal, reasoning,
        latency_ms, cost_usd, error,
        regime_fingerprint, regime_tags
    ) VALUES (
        :episode_id, :ts, :cycle_id, :cycle_started_at, :subsystem, :symbol,
        :agent_id, :agent_version, CAST(:market_snapshot AS JSONB), CAST(:input_state AS JSONB),
        :prompt, :raw_response, CAST(:parsed_signal AS JSONB), :reasoning,
        :latency_ms, :cost_usd, :error,
        :regime_fingerprint, :regime_tags
    )
    ON CONFLICT (episode_id, ts) DO NOTHING
    """
)


def _coerce_ts(value: str | None) -> datetime:
    """Parse an ISO8601 string back to datetime. Empty/missing → now-UTC."""
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.utcnow()


def _row_from_message(fields: dict[str, Any]) -> dict[str, Any]:
    """Translate a Redis Stream entry into INSERT bind params.

    Bytes vs str: redis-py with decode_responses=True returns str. Defensive
    decoding here in case decode_responses is False in some deployment.
    """
    decoded: dict[str, Any] = {}
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        decoded[key] = val

    return {
        "episode_id": decoded["episode_id"],
        "ts": _coerce_ts(decoded.get("ts")),
        "cycle_id": decoded["cycle_id"],
        "cycle_started_at": _coerce_ts(decoded.get("cycle_started_at")),
        "subsystem": decoded.get("subsystem") or "legacy",
        "symbol": decoded.get("symbol") or "UNKNOWN",
        "agent_id": decoded["agent_id"],
        "agent_version": decoded["agent_version"],
        "market_snapshot": decoded.get("market_snapshot") or "{}",
        "input_state": decoded.get("input_state") or "{}",
        "prompt": decoded.get("prompt") or None,
        "raw_response": decoded.get("raw_response") or None,
        "parsed_signal": decoded.get("parsed_signal") or "[]",
        "reasoning": decoded.get("reasoning") or None,
        "latency_ms": int(decoded.get("latency_ms") or 0),
        "cost_usd": float(decoded.get("cost_usd") or 0.0),
        "error": decoded.get("error") or None,
        "regime_fingerprint": decoded.get("regime_fingerprint") or "stub-v1:UNKNOWN",
        "regime_tags": _parse_tags(decoded.get("regime_tags")),
    }


def _parse_tags(raw: Any) -> list[str]:
    """regime_tags is a Postgres TEXT[]. asyncpg accepts a Python list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return [str(x) for x in loaded]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [str(raw)]


class EpisodeWriter(BaseConsumer):
    """Consumes EPISODES stream into Postgres agent_episodes."""

    def __init__(
        self,
        redis: Redis,
        session_factory,
        consumer_name: str = "episode_writer-1",
    ) -> None:
        super().__init__(
            stream=EPISODES,
            group="cg:episode_writer",
            consumer_name=consumer_name,
            redis=redis,
        )
        self._session_factory = session_factory

    async def handle(self, msg_id: str, fields: dict[str, Any]) -> None:
        try:
            row = _row_from_message(fields)
        except KeyError as exc:
            logger.error(
                "episode_payload_missing_field",
                msg_id=msg_id,
                missing=str(exc),
                hint="malformed episode message; will be acked to drain",
            )
            return  # Returning lets BaseConsumer ack and move on.

        session: AsyncSession
        async with self._session_factory() as session:
            await session.execute(_INSERT_SQL, row)
            await session.commit()

        logger.debug(
            "episode_written",
            msg_id=msg_id,
            episode_id=row["episode_id"],
            cycle_id=row["cycle_id"],
            agent_id=row["agent_id"],
        )
