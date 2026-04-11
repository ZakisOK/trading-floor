"""
TradeDeskAgent — Desk 2: Trade Execution.

Listens to `stream:trade_desk:inbox` for conviction packets from Nova (Desk 1).
For each packet:
  1. Validates the packet hasn't expired
  2. Calls Diana for final position sizing
  3. Calls Atlas for execution
  4. Registers the trade with the Position Monitor
  5. When the trade closes, writes outcome to `stream:trade_outcomes`
     so the Learning Layer (AgentMemory) can update agent weights.

This is the bridge between Alpha Research and the live book.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import structlog

from src.agents.diana import DianaAgent
from src.agents.atlas import AtlasAgent
from src.agents.base import AgentState
from src.core.redis import get_redis
from src.core.security import is_kill_switch_active
from src.learning.agent_memory import agent_memory
from src.streams.producer import produce, produce_audit
from src.streams import topology

logger = structlog.get_logger()

CONSUMER_GROUP = "cg:trade_desk"
CONSUMER_NAME = "trade_desk_main"

# Poll interval when stream is empty
POLL_INTERVAL_SECONDS = 2

# Read at most this many packets per loop iteration
BATCH_SIZE = 5


class TradeDeskAgent:
    """
    Desk 2 — receives conviction packets from Nova and drives execution.

    Wires together: Diana (risk sizing) → Atlas (execution) → AgentMemory (outcome logging).
    """

    def __init__(self) -> None:
        self.diana = DianaAgent()
        self.atlas = AtlasAgent()
        self._open_trades: dict[str, dict] = {}  # packet_id → trade record

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Listen to the trade desk inbox stream and process conviction packets."""
        redis = get_redis()

        # Ensure the consumer group exists
        try:
            await redis.xgroup_create(
                topology.TRADE_DESK_INBOX, CONSUMER_GROUP, id="0", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        logger.info("trade_desk_started", stream=topology.TRADE_DESK_INBOX)

        while True:
            try:
                if await is_kill_switch_active():
                    logger.warning("trade_desk_kill_switch_active")
                    await asyncio.sleep(10)
                    continue

                messages = await redis.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {topology.TRADE_DESK_INBOX: ">"},
                    count=BATCH_SIZE,
                    block=POLL_INTERVAL_SECONDS * 1000,  # ms
                )

                if not messages:
                    continue

                for _stream, entries in messages:
                    for msg_id, fields in entries:
                        try:
                            await self._process_conviction_packet(fields)
                            # Acknowledge the message
                            await redis.xack(topology.TRADE_DESK_INBOX, CONSUMER_GROUP, msg_id)
                        except Exception as e:
                            logger.error(
                                "trade_desk_packet_error",
                                msg_id=msg_id,
                                error=str(e),
                            )

            except asyncio.CancelledError:
                logger.info("trade_desk_shutdown")
                break
            except Exception as e:
                logger.error("trade_desk_loop_error", error=str(e))
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # -------------------------------------------------------------------------
    # Packet processing
    # -------------------------------------------------------------------------

    async def _process_conviction_packet(self, fields: dict) -> None:
        """
        Process a single conviction packet from Nova.
        Pipeline: validate → Diana sizing → Atlas execute → register.
        """
        packet_id = fields.get("packet_id", str(uuid.uuid4()))
        symbol = fields.get("symbol", "UNKNOWN")
        direction = fields.get("direction", "NEUTRAL")
        confidence = float(fields.get("final_confidence", 0))
        expires_at_str = fields.get("expires_at", "")
        regime = fields.get("regime", "UNKNOWN")

        logger.info(
            "trade_desk_packet_received",
            packet_id=packet_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
        )

        # 1. Expiry check
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if datetime.now(UTC) > expires_at:
                    logger.warning("trade_desk_packet_expired", packet_id=packet_id, symbol=symbol)
                    await produce_audit("packet_expired", "trade_desk", {"packet_id": packet_id})
                    return
            except ValueError:
                pass

        # 2. Reconstruct an AgentState from the packet so Diana and Atlas can work on it
        state: AgentState = AgentState(
            agent_id="trade_desk",
            agent_name="Trade Desk",
            messages=[],
            market_data={
                "symbol": symbol,
                "regime": regime,
                "close": 0,  # Atlas will fetch live price
            },
            signals=[{
                "agent": "Nova",
                "direction": direction,
                "confidence": confidence,
                "thesis": fields.get("thesis_summary", ""),
            }],
            risk_approved=False,
            final_decision=direction,
            confidence=confidence,
            reasoning=f"Nova conviction packet {packet_id}",
        )

        # 3. Diana: final position sizing and risk check
        state = await self.diana.analyze(state)
        if not state.get("risk_approved"):
            logger.warning(
                "trade_desk_diana_rejected",
                packet_id=packet_id,
                symbol=symbol,
                reason=state.get("reasoning"),
            )
            await produce(topology.PORTFOLIO_EVENTS, {
                "event": "diana_rejected",
                "packet_id": packet_id,
                "symbol": symbol,
                "reason": state.get("reasoning", ""),
            })
            return

        # 4. Atlas: execution
        state = await self.atlas.analyze(state)

        # 5. Register the open trade so we can match it to an outcome later
        trade_record = {
            "packet_id": packet_id,
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "entry_time": datetime.now(UTC).isoformat(),
            "regime": regime,
            "stop_loss_pct": float(fields.get("stop_loss_pct", 0.04)),
            "take_profit_pct": float(fields.get("take_profit_pct", 0.12)),
            "state": "OPEN",
        }
        self._open_trades[packet_id] = trade_record

        redis = get_redis()
        await redis.hset(f"trade:open:{packet_id}", mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in trade_record.items()
        })
        await redis.expire(f"trade:open:{packet_id}", 60 * 60 * 24 * 7)  # 7-day TTL

        await produce_audit("trade_desk_opened", "trade_desk", {
            "packet_id": packet_id,
            "symbol": symbol,
            "direction": direction,
        })

        logger.info(
            "trade_desk_trade_opened",
            packet_id=packet_id,
            symbol=symbol,
            direction=direction,
        )

    # -------------------------------------------------------------------------
    # Outcome recording (called by position monitor when a trade closes)
    # -------------------------------------------------------------------------

    async def record_trade_outcome(
        self,
        packet_id: str,
        outcome: str,  # "WIN" | "LOSS" | "NEUTRAL"
        pnl_pct: float,
        hold_time_minutes: int,
    ) -> None:
        """
        Called when the Position Monitor closes a trade (stop/target hit).
        Writes to stream:trade_outcomes and updates AgentMemory.
        """
        redis = get_redis()
        trade = self._open_trades.pop(packet_id, None)

        if trade is None:
            # Try to recover from Redis
            raw = await redis.hgetall(f"trade:open:{packet_id}")
            if raw:
                trade = raw
            else:
                logger.warning("trade_desk_outcome_unknown_packet", packet_id=packet_id)
                return

        symbol = trade.get("symbol", "UNKNOWN")
        confidence = float(trade.get("confidence", 0))
        regime = trade.get("regime", "UNKNOWN")

        # Write to trade outcomes stream so Learning Layer can consume it
        await produce(topology.TRADE_OUTCOMES, {
            "packet_id": packet_id,
            "symbol": symbol,
            "outcome": outcome,
            "pnl_pct": str(pnl_pct),
            "hold_time_minutes": str(hold_time_minutes),
            "confidence_at_entry": str(confidence),
            "regime": regime,
            "originating_agent_id": "nova",  # Nova synthesized all agents
            "closed_at": datetime.now(UTC).isoformat(),
        })

        # Update AgentMemory for each research agent that contributed to this trade
        # We record the outcome against Nova's signal (which aggregated all agents)
        await agent_memory.record_outcome(
            signal_id=packet_id,
            outcome=outcome,  # type: ignore[arg-type]
            pnl_pct=pnl_pct,
            hold_time_minutes=hold_time_minutes,
        )

        # Clean up the open trade record
        await redis.delete(f"trade:open:{packet_id}")

        await produce_audit("trade_desk_closed", "trade_desk", {
            "packet_id": packet_id,
            "symbol": symbol,
            "outcome": outcome,
            "pnl_pct": pnl_pct,
        })

        logger.info(
            "trade_desk_trade_closed",
            packet_id=packet_id,
            symbol=symbol,
            outcome=outcome,
            pnl_pct=f"{pnl_pct:.2%}",
        )


# Module-level singleton
trade_desk = TradeDeskAgent()
