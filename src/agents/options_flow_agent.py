"""
Options Flow Agent — pure-data institutional vs retail divergence signal.

No LLM calls. This agent is entirely rule-based: it reads options flow data
and emits signals when unusual (likely institutional) activity is detected.

Why no LLM here: the signal is already quantitative. Call/put ratio and
unusual score are crisp numbers. Adding an LLM would add latency and cost
without improving signal quality — the math speaks for itself.

Activated for: BTC/USDT, ETH/USDT, GC=F (gold), CL=F (crude oil).
Only emits signals when confidence > 0.60 (unusual flow threshold).
"""
from __future__ import annotations

import logging

from src.agents.base import BaseAgent, AgentState
from src.data.feeds.options_flow_feed import OptionsFlowFeed

logger = logging.getLogger(__name__)

# Symbols this agent covers
OPTIONS_FLOW_SYMBOLS = {"BTC/USDT", "ETH/USDT", "GC=F", "CL=F"}

# Minimum confidence to emit a signal (avoid noise)
MIN_CONFIDENCE = 0.60

# Confidence ceiling (options flow alone never gives 100% conviction)
MAX_CONFIDENCE = 0.85

class OptionsFlowAgent(BaseAgent):
    """
    Options flow analyst — detects institutional positioning divergence.

    Signal logic (pure data, no LLM):
      - call_put_ratio > 1.5 + unusual trades present → BULL signal
      - call_put_ratio < 0.6 + unusual trades present → BEAR signal
      - Confidence = unusual_score / 10, capped at 0.85
      - Flow type: INSTITUTIONAL trades get a confidence boost

    When "unusual" flow is detected (position size > 3 std above average),
    it suggests an informed institutional participant is taking a directional
    bet. This is not guaranteed (hedging exists) but is a statistically
    meaningful signal when combined with directional call/put skew.
    """

    def __init__(self) -> None:
        super().__init__("options_flow_agent", "Options Flow Agent", "Options Specialist")
        self._feed = OptionsFlowFeed()

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        if symbol not in OPTIONS_FLOW_SYMBOLS:
            return state

        # Fetch options signal — pure data, no LLM
        options_signal = await self._feed.get_options_signal(symbol)

        signal_dir = options_signal.get("signal", "NEUTRAL")
        confidence = float(options_signal.get("confidence", 0.0))
        flow_type = options_signal.get("flow_type", "MIXED")
        call_put_ratio = options_signal.get("call_put_ratio", 1.0)
        unusual_trades = options_signal.get("unusual_trades", [])
        total_call_prem = options_signal.get("total_call_premium", 0.0)
        total_put_prem = options_signal.get("total_put_premium", 0.0)
        data_source = options_signal.get("data_source", "unknown")

        # Only emit when confidence crosses the threshold
        # This avoids flooding the signal stream with noise on quiet days
        if confidence < MIN_CONFIDENCE or signal_dir == "NEUTRAL":
            logger.debug(
                "options_flow_skip symbol=%s confidence=%.2f signal=%s",
                symbol, confidence, signal_dir,
            )
            return state

        # Build a human-readable thesis from the raw data
        direction_word = "LONG" if signal_dir == "BULL" else "SHORT"
        flow_desc = f"{flow_type} flow"

        call_prem_m = total_call_prem / 1_000_000
        put_prem_m = total_put_prem / 1_000_000

        thesis_parts = [
            f"{flow_desc} detected on {symbol}: C/P ratio {call_put_ratio:.2f}",
            f"(calls ${call_prem_m:.1f}M vs puts ${put_prem_m:.1f}M).",
        ]

        if unusual_trades:
            top = unusual_trades[0]
            top_strike = top.get("strike", 0)
            top_expiry = top.get("expiry", "")
            top_cp = top.get("call_put", "")
            top_prem = top.get("premium", 0) / 1_000
            thesis_parts.append(
                f"Largest unusual: {top_cp} ${top_strike:.0f} exp {top_expiry} "
                f"${top_prem:.0f}K premium."
            )

        thesis_parts.append(f"Source: {data_source}.")
        thesis = " ".join(thesis_parts)

        await self.emit_signal(
            symbol=symbol,
            direction=direction_word,
            confidence=min(MAX_CONFIDENCE, confidence),
            thesis=thesis,
            strategy="options_flow_institutional",
        )

        # Append to state signals
        updated = dict(state)
        updated["signals"] = state.get("signals", []) + [{
            "agent": self.name,
            "direction": direction_word,
            "confidence": round(min(MAX_CONFIDENCE, confidence), 3),
            "thesis": thesis,
            "strategy": "options_flow_institutional",
            "symbol": symbol,
            "flow_type": flow_type,
            "call_put_ratio": call_put_ratio,
            "unusual_trade_count": len(unusual_trades),
            "data_source": data_source,
        }]
        return AgentState(**updated)

    async def close(self) -> None:
        await self._feed.close()
