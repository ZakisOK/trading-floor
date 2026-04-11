"""
Nova — Synthesizer / Jury Foreperson (Desk 1 final node).

Nova doesn't generate signals. She reads all signals from Marcus, Vera, Rex,
XRP Analyst, and Polymarket Scout, then applies confidence-weighted Bayesian
aggregation to produce a final conviction packet for Desk 2.

Bayesian aggregation:
  final_confidence = Σ(agent_confidence_i × agent_weight_i) / Σ(agent_weight_i)
  agent_weight_i   = rolling accuracy over last 50 trades (from AgentMemory)
                     defaults to 0.5 (equal weight) when history is insufficient

Nova only passes to Desk 2 if consensus_strength is "strong" (≥0.7)
or "moderate" (0.5–0.7). Weak consensus (<0.5) → no trade.
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

logger = structlog.get_logger()

# Agents whose signals Nova aggregates (must match agent_id in BaseAgent subclasses)
RESEARCH_AGENTS = ["marcus", "vera", "rex", "xrp_analyst", "polymarket_scout"]

# Conviction thresholds
STRONG_THRESHOLD = 0.70
MODERATE_THRESHOLD = 0.50

# Default position sizing parameters (Desk 2 / Diana can override)
DEFAULT_POSITION_SIZE_PCT = 0.02   # 2% of portfolio
DEFAULT_STOP_LOSS_PCT = 0.04       # 4%
DEFAULT_TAKE_PROFIT_PCT = 0.12     # 12%

# Conviction packet expires after this many minutes if Desk 2 doesn't act
CONVICTION_EXPIRY_MINUTES = 30


def _consensus_strength(confidence: float) -> str:
    if confidence >= STRONG_THRESHOLD:
        return "strong"
    if confidence >= MODERATE_THRESHOLD:
        return "moderate"
    return "weak"


class NovaAgent(BaseAgent):
    """
    Synthesizer — reads the accumulated signals state from Desk 1 agents
    and applies Bayesian aggregation to produce a conviction packet.
    Replaces Diana as the final node in the research pipeline.
    """

    def __init__(self) -> None:
        super().__init__("nova", "Nova", "Synthesizer")

    async def analyze(self, state: AgentState) -> AgentState:
        signals: list[dict] = state.get("signals", [])
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        regime: str = market.get("regime", "UNKNOWN")

        # If no signals came in from the research pipeline, pass through unchanged
        if not signals:
            logger.warning("nova_no_signals", symbol=symbol)
            updated = dict(state)
            updated["final_decision"] = None
            updated["risk_approved"] = False
            return AgentState(**updated)

        # -----------------------------------------------------------------
        # Step 1: Fetch per-agent Bayesian weights from AgentMemory
        # -----------------------------------------------------------------
        agent_weights: dict[str, float] = {}
        for agent_id in RESEARCH_AGENTS:
            agent_weights[agent_id] = await agent_memory.get_effective_weight(agent_id)

        # -----------------------------------------------------------------
        # Step 2: Weighted confidence aggregation
        # -----------------------------------------------------------------
        weighted_confidence_sum = 0.0
        weight_sum = 0.0
        direction_votes: dict[str, float] = {}  # direction → weighted votes
        dissenting_agents: list[str] = []
        thesis_parts: list[str] = []

        for sig in signals:
            agent_name = sig.get("agent", "").lower()
            # Map agent_name → agent_id (agents store name not id in signals)
            agent_id = _name_to_id(agent_name)
            weight = agent_weights.get(agent_id, 0.5)

            conf = float(sig.get("confidence", 0.5))
            direction = sig.get("direction", "NEUTRAL")
            thesis = sig.get("thesis", "")

            weighted_confidence_sum += conf * weight
            weight_sum += weight

            direction_votes[direction] = direction_votes.get(direction, 0.0) + weight

            if thesis:
                thesis_parts.append(f"[{agent_name.title()}] {thesis}")

        final_confidence = (
            weighted_confidence_sum / weight_sum if weight_sum > 0 else 0.5
        )
        final_confidence = round(min(max(final_confidence, 0.0), 1.0), 4)

        # Determine consensus direction by highest weighted vote
        consensus_direction = max(direction_votes, key=direction_votes.get) if direction_votes else "NEUTRAL"

        # Identify dissenting agents (those who voted differently than consensus)
        for sig in signals:
            if sig.get("direction") != consensus_direction:
                dissenting_agents.append(_name_to_id(sig.get("agent", "").lower()))

        strength = _consensus_strength(final_confidence)

        # Polymarket boost: check if polymarket_scout voted with consensus at high confidence
        polymarket_boost = 0.0
        for sig in signals:
            if "polymarket" in sig.get("agent", "").lower():
                if sig.get("direction") == consensus_direction:
                    polymarket_boost = round(float(sig.get("confidence", 0)) * 0.1, 3)

        # -----------------------------------------------------------------
        # Step 3: Build conviction packet
        # -----------------------------------------------------------------
        packet_id = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(minutes=CONVICTION_EXPIRY_MINUTES)).isoformat()

        conviction_packet = {
            "packet_id": packet_id,
            "symbol": symbol,
            "direction": consensus_direction,
            "final_confidence": final_confidence,
            "consensus_strength": strength,
            "dissenting_agents": dissenting_agents,
            "thesis_summary": " | ".join(thesis_parts)[:500],
            "polymarket_boost": polymarket_boost,
            "recommended_position_size_pct": DEFAULT_POSITION_SIZE_PCT,
            "stop_loss_pct": DEFAULT_STOP_LOSS_PCT,
            "take_profit_pct": DEFAULT_TAKE_PROFIT_PCT,
            "expires_at": expires_at,
            "regime": regime,
            "agent_weights": agent_weights,
        }

        logger.info(
            "nova_conviction_packet",
            symbol=symbol,
            direction=consensus_direction,
            confidence=final_confidence,
            strength=strength,
            dissenters=dissenting_agents,
        )

        # -----------------------------------------------------------------
        # Step 4: Gate — only forward strong/moderate conviction
        # -----------------------------------------------------------------
        if strength == "weak":
            logger.info("nova_weak_consensus_no_trade", symbol=symbol, confidence=final_confidence)
            updated = dict(state)
            updated["final_decision"] = None
            updated["risk_approved"] = False
            updated["confidence"] = final_confidence
            updated["reasoning"] = f"Nova: weak consensus ({final_confidence:.2f}) — no trade"
            return AgentState(**updated)

        # -----------------------------------------------------------------
        # Step 5: Publish conviction packet to Desk 2 inbox stream
        # -----------------------------------------------------------------
        redis = get_redis()
        await produce(
            topology.TRADE_DESK_INBOX,
            {
                "packet_id": packet_id,
                "symbol": symbol,
                "direction": consensus_direction,
                "final_confidence": str(final_confidence),
                "consensus_strength": strength,
                "dissenting_agents": json.dumps(dissenting_agents),
                "thesis_summary": conviction_packet["thesis_summary"],
                "polymarket_boost": str(polymarket_boost),
                "recommended_position_size_pct": str(DEFAULT_POSITION_SIZE_PCT),
                "stop_loss_pct": str(DEFAULT_STOP_LOSS_PCT),
                "take_profit_pct": str(DEFAULT_TAKE_PROFIT_PCT),
                "expires_at": expires_at,
                "regime": regime,
            },
            redis=redis,
        )

        await produce_audit("nova_conviction_forwarded", "nova", {
            "packet_id": packet_id,
            "symbol": symbol,
            "direction": consensus_direction,
            "confidence": final_confidence,
            "strength": strength,
        }, redis=redis)

        # Update AgentState so callers can see Nova's decision
        updated = dict(state)
        updated["final_decision"] = consensus_direction
        updated["risk_approved"] = True
        updated["confidence"] = final_confidence
        updated["reasoning"] = (
            f"Nova ({strength} consensus, conf={final_confidence:.2f}): {consensus_direction}"
        )
        return AgentState(**updated)


def _name_to_id(agent_name: str) -> str:
    """Map display name → agent_id used in AgentMemory."""
    mapping = {
        "marcus": "marcus",
        "vera": "vera",
        "rex": "rex",
        "xrp analyst": "xrp_analyst",
        "xrp_analyst": "xrp_analyst",
        "polymarket scout": "polymarket_scout",
        "polymarket_scout": "polymarket_scout",
        "nova": "nova",
        "diana": "diana",
    }
    return mapping.get(agent_name, agent_name)
