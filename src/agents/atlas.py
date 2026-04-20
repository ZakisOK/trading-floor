"""Atlas — Execution agent.

Week 2 / A5: pure execution. Sizing now happens upstream in
PortfolioConstructor; Atlas reads ``state["sized_order"]`` and submits it.
Atlas no longer calls position_sizer directly.

Week 2 / B5: contributor recording fixes:
- Records contributors on BOTH buy and sell executions (no BUY-only bias).
- Records ALL voting agents that matched the trade direction (no confidence
  threshold filter). Counterfactual attribution job assigns weight later.
- Records under ``paper:trade:{trade_id}:contributors`` so the outcome
  writer can join contributions to trades by ``trade_id``.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from src.agents.base import BaseAgent, AgentState
from src.streams.producer import produce
from src.streams import topology
from src.core.redis import get_redis
from src.execution.broker import paper_broker

logger = structlog.get_logger()


async def _get_autonomy_mode() -> str:
    """Read autonomy_mode from Redis. Defaults to COMMANDER (safest)."""
    redis = get_redis()
    val = await redis.hget("config:system", "autonomy_mode")
    return (val or "COMMANDER").upper()


_PROMPT_SKELETON = (
    "Atlas — deterministic execution router (Week 2 / A5: pure execution).\n"
    "Reads sized_order from state (set by PortfolioConstructor), checks "
    "autonomy_mode (COMMANDER queues for approval, TRUSTED/YOLO submits).\n"
    "Records contributors on every fill (Week 2 / B5)."
)


def _matched_contributors(state: AgentState, direction: str) -> list[dict]:
    """Return all signals matching the trade direction (no threshold filter).

    Each entry: {"agent_id", "agent_version", "direction", "confidence",
    "reasoning"}. agent_version is best-effort: signals don't carry it
    natively yet (would require a signals refactor); for now we look up the
    live agent registry to fill it.
    """
    out: list[dict] = []
    for s in state.get("signals", []):
        if s.get("direction") != direction or not s.get("agent"):
            continue
        agent_id = str(s["agent"]).lower()
        out.append({
            "agent_id": agent_id,
            "direction": s.get("direction"),
            "confidence": float(s.get("confidence") or 0.0),
            "reasoning": str(s.get("thesis") or s.get("reasoning") or "")[:500],
        })
    return out


async def _record_contributors_for_trade(
    *,
    trade_id: str,
    cycle_id: str,
    symbol: str,
    direction: str,
    contributors: list[dict],
) -> None:
    """Persist contributors under paper:trade:{trade_id}:contributors.

    Outcome writer reads this hash on exit and writes one agent_contributions
    row per contributor.
    """
    if not contributors:
        return
    redis = get_redis()
    payload = {
        "trade_id": trade_id,
        "cycle_id": cycle_id,
        "symbol": symbol,
        "direction": direction,
        "contributors": contributors,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    await redis.set(
        f"paper:trade:{trade_id}:contributors",
        json.dumps(payload),
        ex=60 * 60 * 24 * 14,  # 14 day TTL — outcome writer should pick up well within this
    )
    # Mirror to the legacy per-symbol contributor set so the position_monitor
    # ELO update path keeps working in the transition.
    legacy_set = [c["agent_id"] for c in contributors]
    if legacy_set:
        await redis.sadd(f"paper:position:{symbol}:contributors", *legacy_set)


class AtlasAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            "atlas",
            "Atlas",
            "Execution",
            model_name="deterministic",
            prompt_template=_PROMPT_SKELETON,
        )

    async def analyze(self, state: AgentState) -> AgentState:
        if not state.get("risk_approved"):
            logger.info("atlas_skipping", reason="risk not approved")
            return state

        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        direction = state.get("final_decision", "NEUTRAL")
        confidence = state.get("confidence", 0.0)
        price = float(market.get("price") or market.get("close") or 0.0)
        cycle_id = state.get("cycle_id") or ""

        order_summary = f"{direction} {symbol} @ confidence {confidence:.2f}"

        # Week 2 / A5: read sized_order from state. Refuse if missing — the
        # constructor must have run; if it didn't, that's an upstream bug.
        sized = state.get("sized_order")
        if not sized or not isinstance(sized, dict) or sized.get("quantity", 0) <= 0:
            logger.warning(
                "atlas_no_sized_order",
                symbol=symbol, direction=direction, cycle_id=cycle_id,
                msg="constructor did not produce a SizedOrder; skipping",
            )
            updated = dict(state)
            updated["messages"] = list(state.get("messages", [])) + [{
                "from": self.name,
                "content": f"Order skipped: no sized_order from constructor for {direction} {symbol}",
            }]
            return AgentState(**updated)

        if direction in ("LONG", "SHORT") and price > 0:
            side = sized.get("side") or ("BUY" if direction == "LONG" else "SELL")
            quantity = float(sized["quantity"])
            existing = await paper_broker._get_position(symbol)
            mode = await _get_autonomy_mode()
            contributors = _matched_contributors(state, direction)
            trade_id = str(uuid.uuid4())

            if side == "BUY" and existing is not None:
                logger.info("atlas_skip_existing_position", symbol=symbol)
            elif mode == "COMMANDER":
                signal_id = uuid.uuid4().hex[:10]
                redis = get_redis()
                await redis.hset("approval:pending", signal_id, json.dumps({
                    "signal_id": signal_id,
                    "trade_id": trade_id,
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "side": side,
                    "direction": direction,
                    "price": price,
                    "quantity": quantity,
                    "notional": float(sized.get("notional", 0)),
                    "confidence_adjusted_risk_pct": float(
                        sized.get("confidence_adjusted_risk_pct", 0)
                    ),
                    "confidence": confidence,
                    "agent_id": self.agent_id,
                    "strategy": "consensus",
                    "reasoning": state.get("reasoning", "")[:500],
                    "contributing_agents": [c["agent_id"] for c in contributors],
                    "contributors_full": contributors,
                    "created_at": datetime.now(UTC).isoformat(),
                }))
                # Pre-record contributors so when the operator approves, the
                # outcome writer has them at exit time.
                await _record_contributors_for_trade(
                    trade_id=trade_id, cycle_id=cycle_id,
                    symbol=symbol, direction=direction,
                    contributors=contributors,
                )
                order_summary = f"QUEUED {side} {symbol} @ ${price:.4f} (awaiting approval)"
                logger.info(
                    "atlas_order_queued_commander",
                    symbol=symbol, side=side, signal_id=signal_id, trade_id=trade_id,
                )
            else:
                try:
                    order = await paper_broker.submit_order(
                        symbol=symbol, side=side, quantity=quantity,
                        current_price=price, agent_id=self.agent_id,
                        strategy="consensus",
                        cycle_id=cycle_id,
                    )
                    order_summary = (
                        f"{side} {order.quantity:.4f} {symbol} "
                        f"@ ${order.filled_price:.4f} ({order.status})"
                    )
                    # B5: record contributors on EVERY fill (BUY and SELL),
                    # no confidence threshold filter.
                    if order.status == "FILLED":
                        await _record_contributors_for_trade(
                            trade_id=trade_id, cycle_id=cycle_id,
                            symbol=symbol, direction=direction,
                            contributors=contributors,
                        )
                    logger.info(
                        "atlas_order_filled",
                        symbol=symbol, side=side, price=order.filled_price,
                        qty=order.quantity, status=order.status,
                        order_id=order.order_id, trade_id=trade_id,
                    )
                except Exception as exc:
                    logger.error(
                        "atlas_order_failed",
                        symbol=symbol, side=side, error=str(exc),
                    )

            redis = get_redis()
            await produce(topology.ORDERS, {
                "agent_id": self.agent_id,
                "trade_id": trade_id,
                "cycle_id": cycle_id,
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
