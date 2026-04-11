"""
CarryAgent — pure-calculation carry factor agent. No LLM calls.

Emits LONG when carry is positive/bullish, SHORT when negative/bearish.
Confidence = |carry_yield| normalized to [0, 1] (capped at 10% annualized = 1.0).

Runs for all symbols:
  - Commodity futures (=F tickers): roll yield from front vs second month
  - Crypto (BTC/USDT, XRP/USDT, etc.): contrarian funding rate signal
  - Other symbols: emits nothing (no carry model)
"""
from __future__ import annotations

import structlog

from src.agents.base import AgentState, BaseAgent
from src.signals.carry import CarrySignal

logger = structlog.get_logger()


class CarryAgent(BaseAgent):
    """
    Carry factor agent — determines whether the cost/benefit of holding
    a position (independent of price appreciation) is favorable.

    Signal logic:
      Commodity backwardation → positive carry → LONG
      Commodity contango       → negative carry → SHORT
      Crypto high funding      → crowded long → SHORT (contrarian)
      Crypto negative funding  → crowded short → LONG (contrarian)
    """

    def __init__(self) -> None:
        super().__init__("carry_agent", "Carry", "Carry Factor")
        self._carry = CarrySignal()

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        try:
            carry_data = await self._carry.get_carry_signal(symbol)
        except Exception as exc:
            logger.error("carry_agent_error", symbol=symbol, error=str(exc))
            return state

        signal = carry_data.get("signal", "NEUTRAL")
        confidence = float(carry_data.get("confidence", 0.0))
        carry_type = carry_data.get("carry_type", "unknown")
        error = carry_data.get("error")

        # Skip if unsupported or no meaningful signal
        if error or signal == "NEUTRAL" or confidence < 0.05:
            logger.debug(
                "carry_agent_no_signal",
                symbol=symbol,
                signal=signal,
                carry_type=carry_type,
            )
            return state

        # Map BULL/BEAR → LONG/SHORT
        direction = "LONG" if signal == "BULL" else "SHORT"

        # Build thesis based on carry type
        if carry_type == "commodity_roll_yield":
            structure = carry_data.get("structure", "unknown")
            yield_pct = carry_data.get("carry_yield_annualized", 0) * 100
            thesis = (
                f"Commodity carry: {structure} ({yield_pct:+.2f}% annualized roll yield). "
                f"Front={carry_data.get('front_price')} vs "
                f"2nd-month={carry_data.get('second_price')}."
            )
        else:
            funding = carry_data.get("funding_rate_8h", 0)
            crowding = carry_data.get("crowding", "unknown")
            thesis = (
                f"Crypto funding carry: {crowding} ({funding:+.4%}/8h). "
                f"Contrarian signal: {direction}."
            )

        await self.emit_signal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            strategy=f"carry_{carry_type}",
        )

        updated = dict(state)
        updated["signals"] = list(state.get("signals", [])) + [{
            "agent": self.name,
            "direction": direction,
            "confidence": confidence,
            "thesis": thesis,
            "carry_type": carry_type,
            "carry_data": carry_data,
        }]
        logger.info(
            "carry_agent_signal",
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            carry_type=carry_type,
        )
        return AgentState(**updated)
