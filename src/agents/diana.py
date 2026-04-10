"""Diana — Risk Manager agent."""
from __future__ import annotations

import structlog
from src.agents.base import BaseAgent, AgentState
from src.core.config import settings

logger = structlog.get_logger()

CONFIDENCE_THRESHOLD = 0.5


class DianaAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("diana", "Diana", "Risk Manager")

    async def analyze(self, state: AgentState) -> AgentState:
        signals = state.get("signals", [])
        if not signals:
            updated = dict(state)
            updated["risk_approved"] = False
            updated["reasoning"] = "No signals to evaluate"
            return AgentState(**updated)

        # Average confidence across all analyst signals
        avg_confidence = sum(s.get("confidence", 0) for s in signals) / len(signals)

        # Count directional consensus
        longs = sum(1 for s in signals if s.get("direction") == "LONG")
        shorts = sum(1 for s in signals if s.get("direction") == "SHORT")
        total = len(signals)
        consensus_pct = max(longs, shorts) / total if total > 0 else 0

        approved = avg_confidence >= CONFIDENCE_THRESHOLD and consensus_pct >= 0.5
        direction = "LONG" if longs > shorts else "SHORT" if shorts > longs else "NEUTRAL"
        reason = (
            f"avg_confidence={avg_confidence:.2f}, consensus={consensus_pct:.0%}, "
            f"direction={direction}"
        )

        updated = dict(state)
        updated["risk_approved"] = approved
        updated["confidence"] = avg_confidence
        updated["final_decision"] = direction if approved else None
        updated["reasoning"] = reason
        logger.info("diana_risk_check", approved=approved, reason=reason)
        return AgentState(**updated)
