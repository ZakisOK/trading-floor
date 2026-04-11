"""
COT Analyst Agent — CFTC Commitment of Traders signal generator.

Activates for commodity futures symbols:
  Gold (GC=F), Silver (SI=F), WTI Crude (CL=F),
  Natural Gas (NG=F), Corn (ZC=F), Wheat (ZW=F)

Signal source: CFTC disaggregated COT report (free, weekly, government data).
Claimed directional accuracy: 71-73% when commercial hedgers reach extremes.

Fallback: if ANTHROPIC_API_KEY is not set, uses rule-based signal directly
from COTFeed.get_cot_signal() without calling Claude.

The commercial hedger thesis:
  Producers and processors hedge their PHYSICAL inventory using futures.
  They buy futures to lock in input costs, sell futures to lock in sale prices.
  Because they know their own books, extreme positioning reveals market views
  they can't express any other way. They're "smart money" not by prediction
  but by INFORMATION — they know actual supply/demand in real time.
"""
from __future__ import annotations

import json
import logging

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings
from src.data.feeds.cot_feed import COTFeed, COT_CODES, COMMODITY_NAMES

logger = logging.getLogger(__name__)

# Symbols this agent handles
HANDLED_SYMBOLS = set(COT_CODES.keys())

# Map COT signal → agent direction
COT_TO_DIRECTION: dict[str, str] = {
    "STRONG_BULL": "LONG",
    "BULL":        "LONG",
    "NEUTRAL":     "NEUTRAL",
    "BEAR":        "SHORT",
    "STRONG_BEAR": "SHORT",
}

# Historical outcome context injected into the LLM prompt
SIGNAL_CONTEXT: dict[str, str] = {
    "STRONG_BULL": (
        "At this percentile historically, the commodity has rallied in the "
        "subsequent 4-8 weeks in approximately 70-75% of cases. This is the "
        "most reliable COT signal in the dataset."
    ),
    "BULL": (
        "Above-average commercial long positioning. Moderate bullish lean — "
        "not extreme enough to be the sole thesis, but supportive of longs."
    ),
    "NEUTRAL": (
        "Commercial positioning is within the middle of its historical range. "
        "COT provides no directional edge here — defer to technical/macro."
    ),
    "BEAR": (
        "Below-average commercial long positioning. Mild bearish lean. "
        "Monitor for further deterioration before acting."
    ),
    "STRONG_BEAR": (
        "Extremely heavy commercial short positioning. Historically precedes "
        "significant declines in ~65-70% of cases, especially when speculators "
        "are simultaneously very long (crowded trade setup)."
    ),
}


class COTAnalystAgent(BaseAgent):
    """
    COT commercial signal agent.
    Runs in parallel with Marcus and momentum agents as a signal generator.
    Emits signals only for commodity symbols — passes through unchanged for others.
    """

    def __init__(self) -> None:
        super().__init__("cot_analyst", "COT Analyst", "Commodity Positioning Specialist")
        self._feed = COTFeed()
        self._use_llm = bool(settings.anthropic_api_key)

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        if symbol not in HANDLED_SYMBOLS:
            return state  # Not a COT-tracked commodity — pass through unchanged

        cot = await self._feed.get_cot_signal(symbol)

        if not cot.get("available"):
            logger.warning("cot_analyst_no_data symbol=%s reason=%s",
                           symbol, cot.get("reason"))
            return state

        signal_label = cot.get("signal", "NEUTRAL")
        direction = COT_TO_DIRECTION.get(signal_label, "NEUTRAL")
        confidence = float(cot.get("confidence", 0.5))
        commodity_name = COMMODITY_NAMES.get(symbol, symbol)

        if self._use_llm:
            direction, confidence, thesis = await self._llm_analysis(
                symbol, commodity_name, cot
            )
        else:
            thesis = self._rule_based_thesis(symbol, commodity_name, cot)

        await self.emit_signal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            strategy="cot_commercial_positioning",
            entry=market.get("close") or market.get("latest_close"),
        )

        updated = dict(state)
        updated["signals"] = list(state.get("signals", [])) + [{
            "agent": self.name,
            "direction": direction,
            "confidence": confidence,
            "thesis": thesis,
            "strategy": "cot_commercial_positioning",
            "symbol": symbol,
            "cot_signal": signal_label,
            "cot_percentile_52w": cot.get("percentile_52w"),
            "commercial_net": cot.get("commercial_net"),
            "commercial_pct_oi": cot.get("commercial_pct_oi"),
            "report_date": cot.get("report_date"),
        }]
        return AgentState(**updated)

    # ------------------------------------------------------------------
    # LLM path: Claude Haiku synthesises COT context into a narrative
    # ------------------------------------------------------------------

    async def _llm_analysis(
        self,
        symbol: str,
        commodity_name: str,
        cot: dict,
    ) -> tuple[str, float, str]:
        """Call Claude Haiku with COT context. Returns (direction, confidence, thesis)."""
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)

            signal_label = cot.get("signal", "NEUTRAL")
            percentile = cot.get("percentile_52w", 50)
            comm_net = cot.get("commercial_net", 0)
            comm_pct = cot.get("commercial_pct_oi", 0.0)
            noncomm_net = cot.get("noncommercial_net", 0)
            oi = cot.get("open_interest", 0)
            history_weeks = cot.get("history_weeks", 0)
            historical_context = SIGNAL_CONTEXT.get(signal_label, "")

            prompt = f"""You are a COT (Commitment of Traders) specialist at a commodity trading firm.
Analyze the following positioning data for {commodity_name} ({symbol}).

COMMERCIAL HEDGERS (the "smart money" — producers, merchants, processors):
  Net position: {comm_net:+,} contracts ({comm_pct:+.1f}% of open interest)
  52-week percentile: {percentile:.0f}th (0 = most short historically, 100 = most long)
  COT signal: {signal_label}
  Open interest: {oi:,} total contracts
  History: {history_weeks} weeks of data

NON-COMMERCIAL SPECULATORS (managed money, hedge funds):
  Net position: {noncomm_net:+,} contracts

HISTORICAL OUTCOME CONTEXT:
{historical_context}

CFTC REASONING: {cot.get("reasoning", "")}

Based ONLY on the COT positioning signal, provide your analysis:
- direction: LONG / SHORT / NEUTRAL
- confidence: 0.0-1.0 (COT alone rarely exceeds 0.80 — be conservative)
- thesis: 2 sentences max, focus on what the commercial positioning implies

Respond ONLY in valid JSON:
{{"direction": "LONG", "confidence": 0.72, "thesis": "..."}}"""

            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}
            direction = data.get("direction", "NEUTRAL")
            confidence = float(data.get("confidence", 0.5))
            thesis = data.get("thesis", self._rule_based_thesis(symbol, commodity_name, cot))
            return direction, confidence, thesis
        except Exception as exc:
            logger.warning("cot_analyst_llm_error symbol=%s err=%s", symbol, exc)
            # Fall back to rule-based
            return (
                COT_TO_DIRECTION.get(cot.get("signal", "NEUTRAL"), "NEUTRAL"),
                float(cot.get("confidence", 0.5)),
                self._rule_based_thesis(symbol, commodity_name, cot),
            )

    # ------------------------------------------------------------------
    # Rule-based path: no LLM required
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_based_thesis(symbol: str, commodity_name: str, cot: dict) -> str:
        signal = cot.get("signal", "NEUTRAL")
        percentile = cot.get("percentile_52w", 50)
        comm_net = cot.get("commercial_net", 0)
        comm_pct = cot.get("commercial_pct_oi", 0.0)
        direction_word = "long" if comm_net >= 0 else "short"
        return (
            f"Commercial hedgers are net {direction_word} {abs(comm_net):,} contracts "
            f"({comm_pct:+.1f}% OI) — {percentile:.0f}th percentile over 52 weeks. "
            f"COT signal: {signal}. {SIGNAL_CONTEXT.get(signal, '')}"
        )

    async def close(self) -> None:
        await self._feed.close()
