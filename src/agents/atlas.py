"""Atlas — Execution agent."""
from __future__ import annotations

import structlog
from src.agents.base import BaseAgent, AgentState
from src.streams.producer import produce
from src.streams import topology
from src.core.redis import get_redis

logger = structlog.get_logger()


class AtlasAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("atlas", "Atlas", "Execution")

    async def analyze(self, state: AgentState) -> AgentState:
        if not state.get("risk_approved"):
            logger.info("atlas_skipping", reason="risk not approved")
            return state

        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        direction = state.get("final_decision", "NEUTRAL")
        confidence = state.get("confidence", 0.0)

        if direction in ("LONG", "SHORT"):
            redis = get_redis()
            await produce(topology.ORDERS, {
                "agent_id": self.agent_id,
                "symbol": symbol,
                "direction": direction,
                "confidence": str(confidence),
                "reasoning": state.get("reasoning", ""),
                "mode": "paper",
            }, redis=redis)
            logger.info("atlas_order_emitted", symbol=symbol, direction=direction,
                        confidence=confidence)

        updated = dict(state)
        updated["messages"] = list(state.get("messages", [])) + [{
            "from": self.name,
            "content": f"Order submitted: {direction} {symbol} @ confidence {confidence:.2f}",
        }]
        return AgentState(**updated)
