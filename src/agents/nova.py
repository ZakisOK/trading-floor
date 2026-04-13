"""
Nova — Synthesizer / Jury Foreperson (Desk 1 final node).

Nova doesn't generate signals. She reads all signals from Marcus, Vera, Rex,
XRP Analyst, Polymarket Scout, and CarryAgent, then applies confidence-weighted
Bayesian aggregation to produce a final conviction packet for Desk 2.

Phase 2 upgrade — Regime-weighted Bayesian aggregation:
  agent_weight = accuracy IN THE CURRENT REGIME (last 30 signals)
  Falls back to overall accuracy when <5 regime-specific trades exist.

Gap 2 (Griffin recommendation): Transaction cost filter.
  Before forwarding any signal, Nova estimates the round-trip transaction cost.
  Signals where cost_adjusted_ev <= 0 are discarded — they destroy alpha.
  This prevents Nova from forwarding signals that look good on paper but
  lose money after spread, fees, and market impact.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog

from src.agents.base import AgentState, BaseAgent
from src.learning.agent_memory import agent_memory
from src.streams.producer import produce, produce_audit
from src.streams import topology
from src.core.redis import get_redis
from src.execution import cost_model

logger = structlog.get_logger()

RESEARCH_AGENTS = ["marcus", "vera", "rex", "xrp_analyst", "polymarket_scout", "carry_agent"]

STRONG_THRESHOLD = 0.70
MODERATE_THRESHOLD = 0.50

DEFAULT_POSITION_SIZE_PCT = 0.02
DEFAULT_STOP_LOSS_PCT = 0.04
DEFAULT_TAKE_PROFIT_PCT = 0.12

CONVICTION_EXPIRY_MINUTES = 30
REGIME_ACCURACY_WINDOW = 30

# Typical account * position size to estimate notional for cost model
DEFAULT_NOTIONAL_USD = 10_000.0


def _consensus_strength(confidence: float) -> str:
    if confidence >= STRONG_THRESHOLD:
        return "strong"
    if confidence >= MODERATE_THRESHOLD:
        return "moderate"
    return "weak"


def _name_to_id(agent_name: str) -> str:
    mapping = {
        "marcus": "marcus", "vera": "vera", "rex": "rex",
        "xrp analyst": "xrp_analyst", "xrp_analyst": "xrp_analyst",
        "polymarket scout": "polymarket_scout", "polymarket_scout": "polymarket_scout",
        "carry": "carry_agent", "carry_agent": "carry_agent",
        "nova": "nova", "diana": "diana",
    }
    return mapping.get(agent_name, agent_name)


class NovaAgent(BaseAgent):
    """Synthesizer — regime-weighted Bayesian aggregation with cost filter."""

    def __init__(self) -> None:
        super().__init__("nova", "Nova", "Synthesizer")

    async def analyze(self, state: AgentState) -> AgentState:
        signals: list[dict] = state.get("signals", [])
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        regime: str = market.get("regime", "UNKNOWN")
        price: float = float(market.get("close", market.get("price", 0)) or 0)

        if regime == "UNKNOWN":
            redis = get_redis()
            try:
                cached = await redis.get(f"market:regime:{symbol}")
                if cached:
                    regime = cached
                else:
                    cached_global = await redis.get("market:regime")
                    if cached_global:
                        regime = cached_global
            except Exception:
                pass

        if not signals:
            logger.warning("nova_no_signals", symbol=symbol)
            updated = dict(state)
            updated["final_decision"] = None
            updated["risk_approved"] = False
            return AgentState(**updated)

        # Step 1: Regime-specific Bayesian weights
        agent_weights: dict[str, float] = {}
        for agent_id in RESEARCH_AGENTS:
            agent_weights[agent_id] = await agent_memory.get_agent_accuracy(
                agent_id, regime=regime, last_n=REGIME_ACCURACY_WINDOW
            )

        # Step 2: Weighted confidence aggregation
        weighted_confidence_sum = 0.0
        weight_sum = 0.0
        direction_votes: dict[str, float] = {}
        dissenting_agents: list[str] = []
        thesis_parts: list[str] = []

        for sig in signals:
            agent_name = sig.get("agent", "").lower()
            agent_id   = _name_to_id(agent_name)
            weight     = agent_weights.get(agent_id, 0.5)
            conf       = float(sig.get("confidence", 0.5))
            direction  = sig.get("direction", "NEUTRAL")
            thesis     = sig.get("thesis", "")

            weighted_confidence_sum += conf * weight
            weight_sum += weight
            direction_votes[direction] = direction_votes.get(direction, 0.0) + weight
            if thesis:
                thesis_parts.append(f"[{agent_name.title()}] {thesis}")

        final_confidence = (
            weighted_confidence_sum / weight_sum if weight_sum > 0 else 0.5
        )
        final_confidence = round(min(max(final_confidence, 0.0), 1.0), 4)
        consensus_direction = max(direction_votes, key=direction_votes.get) if direction_votes else "NEUTRAL"

        for sig in signals:
            if sig.get("direction") != consensus_direction:
                dissenting_agents.append(_name_to_id(sig.get("agent", "").lower()))

        strength = _consensus_strength(final_confidence)

        polymarket_boost = 0.0
        for sig in signals:
            if "polymarket" in sig.get("agent", "").lower():
                if sig.get("direction") == consensus_direction:
                    polymarket_boost = round(float(sig.get("confidence", 0)) * 0.1, 3)

        # Step 3: Transaction cost filter (Gap 2 — Griffin recommendation)
        # Estimate notional size and check if signal clears its own costs.
        if consensus_direction != "NEUTRAL" and strength != "weak":
            expected_edge_bps = cost_model.confidence_to_edge_bps(final_confidence)
            cost_estimate = cost_model.estimate(
                symbol=symbol,
                size_usd=DEFAULT_NOTIONAL_USD * DEFAULT_POSITION_SIZE_PCT,
                price=price if price > 0 else 1.0,
                expected_edge_bps=expected_edge_bps,
            )
            if cost_estimate["cost_adjusted_ev"] <= 0:
                logger.info(
                    "nova_signal_killed_by_cost",
                    symbol=symbol,
                    direction=consensus_direction,
                    confidence=final_confidence,
                    total_cost_bps=cost_estimate["total_cost_bps"],
                    expected_edge_bps=expected_edge_bps,
                    cost_adjusted_ev=cost_estimate["cost_adjusted_ev"],
                )
                redis = get_redis()
                await produce_audit("nova_cost_killed", "nova", {
                    "symbol": symbol,
                    "direction": consensus_direction,
                    "confidence": final_confidence,
                    "reason": "cost_negative",
                    "total_cost_bps": cost_estimate["total_cost_bps"],
                    "expected_edge_bps": expected_edge_bps,
                }, redis=redis)
                updated = dict(state)
                updated["final_decision"] = None
                updated["risk_approved"] = False
                updated["confidence"] = final_confidence
                updated["reasoning"] = (
                    f"Nova: cost-negative signal killed "
                    f"(edge={expected_edge_bps:.1f}bps < cost={cost_estimate['total_cost_bps']:.1f}bps)"
                )
                return AgentState(**updated)

        # Step 4: Build conviction packet
        packet_id  = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(minutes=CONVICTION_EXPIRY_MINUTES)).isoformat()

        conviction_packet = {
            "packet_id": packet_id, "symbol": symbol,
            "direction": consensus_direction, "final_confidence": final_confidence,
            "consensus_strength": strength, "dissenting_agents": dissenting_agents,
            "thesis_summary": " | ".join(thesis_parts)[:500],
            "polymarket_boost": polymarket_boost,
            "recommended_position_size_pct": DEFAULT_POSITION_SIZE_PCT,
            "stop_loss_pct": DEFAULT_STOP_LOSS_PCT,
            "take_profit_pct": DEFAULT_TAKE_PROFIT_PCT,
            "expires_at": expires_at, "regime": regime, "agent_weights": agent_weights,
        }

        logger.info(
            "nova_conviction_packet", symbol=symbol, direction=consensus_direction,
            confidence=final_confidence, strength=strength, regime=regime,
        )

        # Step 5: Gate — only forward strong/moderate conviction
        if strength == "weak":
            logger.info("nova_weak_consensus_no_trade", symbol=symbol, confidence=final_confidence)
            updated = dict(state)
            updated["final_decision"] = None
            updated["risk_approved"] = False
            updated["confidence"] = final_confidence
            updated["reasoning"] = f"Nova: weak consensus ({final_confidence:.2f}) — no trade"
            return AgentState(**updated)

        # Step 6: Publish to Desk 2
        redis = get_redis()
        await produce(
            topology.TRADE_DESK_INBOX,
            {
                "packet_id": packet_id, "symbol": symbol,
                "direction": consensus_direction,
                "final_confidence": str(final_confidence),
                "consensus_strength": strength,
                "dissenting_agents": json.dumps(dissenting_agents),
                "thesis_summary": conviction_packet["thesis_summary"],
                "polymarket_boost": str(polymarket_boost),
                "recommended_position_size_pct": str(DEFAULT_POSITION_SIZE_PCT),
                "stop_loss_pct": str(DEFAULT_STOP_LOSS_PCT),
                "take_profit_pct": str(DEFAULT_TAKE_PROFIT_PCT),
                "expires_at": expires_at, "regime": regime,
                "regime_weights": json.dumps({k: round(v, 3) for k, v in agent_weights.items()}),
            },
            redis=redis,
        )
        await produce_audit("nova_conviction_forwarded", "nova", {
            "packet_id": packet_id, "symbol": symbol,
            "direction": consensus_direction, "confidence": final_confidence,
            "strength": strength, "regime": regime,
        }, redis=redis)

        updated = dict(state)
        updated["final_decision"] = consensus_direction
        updated["risk_approved"] = True
        updated["confidence"] = final_confidence
        updated["reasoning"] = (
            f"Nova ({strength} consensus, conf={final_confidence:.2f}, "
            f"regime={regime}): {consensus_direction}"
        )
        return AgentState(**updated)
