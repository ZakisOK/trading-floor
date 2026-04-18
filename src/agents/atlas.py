"""Atlas — Execution agent."""
from __future__ import annotations

import structlog
from src.agents.base import BaseAgent, AgentState
from src.streams.producer import produce
from src.streams import topology
from src.core.redis import get_redis
from src.execution.broker import paper_broker

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
        price = float(market.get("price") or market.get("close") or 0.0)

        order_summary = f"{direction} {symbol} @ confidence {confidence:.2f}"

        if direction in ("LONG", "SHORT") and price > 0:
            side = "BUY" if direction == "LONG" else "SELL"
            existing = await paper_broker._get_position(symbol)
            if side == "BUY" and existing is not None:
                logger.info("atlas_skip_existing_position", symbol=symbol)
            else:
                try:
                    order = await paper_broker.submit_order(
                        symbol=symbol, side=side, quantity=0.0,
                        current_price=price, agent_id=self.agent_id,
                        strategy="consensus",
                    )
                    order_summary = (
                        f"{side} {order.quantity:.4f} {symbol} "
                        f"@ ${order.filled_price:.4f} ({order.status})"
                    )
                    logger.info(
                        "atlas_order_filled", symbol=symbol, side=side,
                        price=order.filled_price, qty=order.quantity,
                        status=order.status, order_id=order.order_id,
                    )
                except Exception as exc:
                    logger.error(
                        "atlas_order_failed", symbol=symbol,
                        side=side, error=str(exc),
                    )

            redis = get_redis()
            await produce(topology.ORDERS, {
                "agent_id": self.agent_id,
                "symbol": symbol,
                "direction": direction,
                "confidence": str(confidence),
                "reasoning": state.get("reasoning", ""),
                "mode": "paper",
            }, redis=redis)
        elif direction in ("LONG", "SHORT"):
            logger.warning(
                "atlas_skip_no_price", symbol=symbol, direction=direction,
            )

        updated = dict(state)
        updated["messages"] = list(state.get("messages", [])) + [{
            "from": self.name,
            "content": f"Order: {order_summary}",
        }]
        return AgentState(**updated)
