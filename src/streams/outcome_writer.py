"""OutcomeWriter — stream:trade_outcomes → trade_outcomes + agent_contributions.

Week 2 / B2. Drains structured exit events emitted by position_monitor
(and, post-Week-2, by the manual exit endpoint) into Postgres. For each
trade it also writes one ``agent_contributions`` row per recorded
contributor (loaded from ``paper:trade:{trade_id}:contributors``).

Idempotent: ``trade_outcomes.trade_id`` is the PK with ON CONFLICT DO
NOTHING. The contributions UNIQUE (trade_id, agent_id, agent_version)
gives the same property at attribution time.

counterfactual_hit + attributed_pnl_usd start NULL. The nightly
counterfactual job populates them.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.streams.consumer import BaseConsumer
from src.streams.topology import TRADE_OUTCOMES

logger = structlog.get_logger()


_INSERT_OUTCOME = text(
    """
    INSERT INTO trade_outcomes (
        trade_id, cycle_id, symbol, venue,
        entry_ts, exit_ts,
        direction, entry_price, exit_price, quantity,
        pnl_usd, pnl_pct, costs_usd,
        exit_reason, regime_at_entry, regime_at_exit,
        backfilled
    ) VALUES (
        :trade_id, :cycle_id, :symbol, :venue,
        :entry_ts, :exit_ts,
        :direction, :entry_price, :exit_price, :quantity,
        :pnl_usd, :pnl_pct, :costs_usd,
        :exit_reason, :regime_at_entry, :regime_at_exit,
        :backfilled
    )
    ON CONFLICT (trade_id) DO NOTHING
    """
)


_INSERT_CONTRIBUTION = text(
    """
    INSERT INTO agent_contributions (
        trade_id, cycle_id, agent_id, agent_version,
        signal_direction, signal_confidence, reasoning,
        matched_trade_direction
    ) VALUES (
        :trade_id, :cycle_id, :agent_id, :agent_version,
        :signal_direction, :signal_confidence, :reasoning,
        :matched_trade_direction
    )
    ON CONFLICT (trade_id, agent_id, agent_version) DO NOTHING
    """
)


_LOOKUP_AGENT_VERSION = text(
    """
    SELECT agent_version
    FROM agent_episodes
    WHERE cycle_id = :cycle_id AND agent_id = :agent_id
    ORDER BY ts DESC
    LIMIT 1
    """
)


def _coerce_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC)


def _parse_event(fields: dict[str, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        decoded[key] = val

    return {
        "trade_id": decoded["trade_id"],
        "cycle_id": decoded.get("cycle_id") or "",
        "symbol": decoded["symbol"],
        "venue": decoded.get("venue") or "sim",
        "entry_ts": _coerce_ts(decoded.get("entry_ts")),
        "exit_ts": _coerce_ts(decoded.get("exit_ts")),
        "direction": (decoded.get("direction") or "LONG").upper(),
        "entry_price": float(decoded["entry_price"]),
        "exit_price": float(decoded["exit_price"]),
        "quantity": float(decoded["quantity"]),
        "pnl_usd": float(decoded.get("pnl_usd") or 0.0),
        "pnl_pct": float(decoded.get("pnl_pct") or 0.0),
        "costs_usd": float(decoded.get("costs_usd") or 0.0),
        "exit_reason": decoded.get("exit_reason") or "manual",
        "regime_at_entry": decoded.get("regime_at_entry") or "stub-v1:UNKNOWN",
        "regime_at_exit": decoded.get("regime_at_exit") or "stub-v1:UNKNOWN",
        "backfilled": str(decoded.get("backfilled") or "false").lower() in ("true", "1", "yes"),
    }


async def _load_contributors(redis: Redis, trade_id: str) -> dict[str, Any]:
    raw = await redis.get(f"paper:trade:{trade_id}:contributors")
    if not raw:
        return {}
    try:
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


class OutcomeWriter(BaseConsumer):
    """Consumes TRADE_OUTCOMES stream into Postgres."""

    def __init__(
        self,
        redis: Redis,
        session_factory,
        consumer_name: str = "outcome_writer-1",
    ) -> None:
        super().__init__(
            stream=TRADE_OUTCOMES,
            group="cg:outcome_writer",
            consumer_name=consumer_name,
            redis=redis,
        )
        self._session_factory = session_factory

    async def handle(self, msg_id: str, fields: dict[str, Any]) -> None:
        try:
            event = _parse_event(fields)
        except KeyError as exc:
            logger.error(
                "outcome_payload_missing_field",
                msg_id=msg_id, missing=str(exc),
            )
            return

        # The pnl_pct CHECK constraint on trade_outcomes is BETWEEN -1 AND 10.
        # Clip silly outliers (e.g. price feed glitch produces -150% pnl).
        if event["pnl_pct"] < -1:
            event["pnl_pct"] = -1.0
        elif event["pnl_pct"] > 10:
            event["pnl_pct"] = 10.0

        contributors_payload = await _load_contributors(self.redis, event["trade_id"])
        contributors: list[dict[str, Any]] = contributors_payload.get("contributors") or []

        async with self._session_factory() as session:
            await session.execute(_INSERT_OUTCOME, event)

            for c in contributors:
                agent_id = str(c.get("agent_id") or "").lower()
                if not agent_id:
                    continue
                agent_version = await self._lookup_agent_version(
                    session, event["cycle_id"], agent_id
                )
                if not agent_version:
                    # Without a version we'd violate the FK chain we'll add
                    # in Week 4; skip and log rather than write a bad row.
                    logger.warning(
                        "contribution_missing_agent_version",
                        trade_id=event["trade_id"], agent_id=agent_id,
                    )
                    continue
                signal_direction = str(c.get("direction") or "NEUTRAL").upper()
                matched = signal_direction == event["direction"]
                await session.execute(_INSERT_CONTRIBUTION, {
                    "trade_id": event["trade_id"],
                    "cycle_id": event["cycle_id"],
                    "agent_id": agent_id,
                    "agent_version": agent_version,
                    "signal_direction": signal_direction,
                    "signal_confidence": max(0.0, min(1.0, float(c.get("confidence") or 0.0))),
                    "reasoning": str(c.get("reasoning") or "")[:1000] or None,
                    "matched_trade_direction": matched,
                })
            await session.commit()

        logger.info(
            "outcome_written",
            trade_id=event["trade_id"], symbol=event["symbol"],
            exit_reason=event["exit_reason"], pnl_usd=event["pnl_usd"],
            contributors=len(contributors),
        )

    async def _lookup_agent_version(
        self, session: AsyncSession, cycle_id: str, agent_id: str
    ) -> str | None:
        if not cycle_id:
            return None
        res = await session.execute(
            _LOOKUP_AGENT_VERSION,
            {"cycle_id": cycle_id, "agent_id": agent_id},
        )
        row = res.first()
        return row[0] if row else None
