"""
MomentumAgent — cross-sectional price momentum signal generator.

Pure math, no LLM.  Computes momentum score from recent price returns
using a short (5-bar) vs medium (20-bar) lookback — a practical proxy for
the classic Jegadeesh & Titman 12-1 momentum in intraday/short cycles.

Signal logic:
  momentum_score > +0.02  →  LONG   (recent bars outpacing medium lookback)
  momentum_score < -0.02  →  SHORT  (recent bars lagging medium lookback)
  |momentum_score| ≤ 0.02 →  NEUTRAL (no edge — agent stays silent)

Confidence = min(|momentum_score| / 0.10, 0.85)
  — capped at 85%: momentum alone never delivers full conviction.

Regime gate:
  Skips signal emission in VOLATILE regime.
  Momentum strategies fail (crash/gap risk) during volatility spikes.
"""
from __future__ import annotations

import structlog

from src.agents.base import AgentState, BaseAgent

logger = structlog.get_logger()

LONG_THRESHOLD  = 0.02   # 2% return advantage  → emit LONG
SHORT_THRESHOLD = -0.02  # -2% return advantage → emit SHORT
MAX_CONFIDENCE  = 0.85   # cap — momentum alone isn't full conviction
CONF_NORMALIZER = 0.10   # 10% spread → max confidence


class MomentumAgent(BaseAgent):
    """
    Cross-sectional momentum agent — pure arithmetic on price history.

    Regime-aware: skips signal emission in VOLATILE regime because
    momentum crashes are historically the worst drawdowns for the factor.
    """

    def __init__(self) -> None:
        super().__init__("momentum", "Momentum Agent", "Signal Generator")

    async def analyze(self, state: AgentState) -> AgentState:  # noqa: PLR0911
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")
        regime = state.get("market_regime", "RANGING")

        # Skip in crash/volatile regime — momentum factor crashes here
        if regime == "VOLATILE":
            logger.debug("momentum_skipped_volatile_regime", symbol=symbol)
            return state

        # Extract price history; fall back to single close price
        prices: list[float] = market.get("prices", [])
        if not prices:
            close = market.get("close")
            if close is None:
                return state
            prices = [float(close)]

        if len(prices) < 2:
            return state

        prices_f = [float(p) for p in prices]

        # 5-bar vs 20-bar momentum (short vs medium lookback)
        recent = prices_f[-5:]
        medium = prices_f[-20:] if len(prices_f) >= 20 else prices_f

        recent_ret = (recent[-1] - recent[0]) / (recent[0] or 1.0)
        medium_ret = (medium[-1] - medium[0]) / (medium[0] or 1.0)
        momentum_score = recent_ret - medium_ret

        if abs(momentum_score) < LONG_THRESHOLD:
            return state  # No edge — stay silent

        direction = "LONG" if momentum_score > 0 else "SHORT"
        confidence = min(abs(momentum_score) / CONF_NORMALIZER, MAX_CONFIDENCE)

        signal = {
            "agent": "momentum",
            "direction": direction,
            "confidence": round(confidence, 3),
            "thesis": (
                f"Momentum {direction}: recent {recent_ret:.2%} vs "
                f"medium {medium_ret:.2%}. Score={momentum_score:.4f}"
            ),
            "symbol": symbol,
            "signal_type": "momentum",
        }

        logger.info(
            "momentum_signal",
            symbol=symbol,
            direction=direction,
            score=round(momentum_score, 4),
            confidence=round(confidence, 3),
        )
        return AgentState(**{**dict(state), "signals": list(state.get("signals", [])) + [signal]})
