"""
Polymarket Scout — monitors prediction markets and adjusts agent confidence.
High-probability Polymarket events directly affect trading conviction.

Examples:
- "Will XRP reach $3 by end of 2025?" at 65% YES → boosts long XRP confidence
- "Will Fed cut rates in Q1?" at 80% YES → bullish macro, boost all crypto
- "Will Ripple settle with SEC?" at 90% YES → strong XRP long signal
"""
from src.agents.base import BaseAgent, AgentState
from src.data.feeds.polymarket_feed import PolymarketFeed, PolymarketSignal
from src.core.config import settings
from src.core.llm_costs import make_tracked_client
import structlog

logger = structlog.get_logger()


_PROMPT_SKELETON = (
    "Polymarket scout — deterministic conviction adjuster. "
    "Filters relevant Polymarket signals, applies bounded conviction boost "
    "(±20%) to existing signals based on YES probability and relevance. "
    "Output: signals[].confidence adjusted in place, polymarket_context."
)


class PolymarketScoutAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            "polymarket_scout",
            "Polymarket Scout",
            "Prediction Market Analyst",
            model_name="deterministic",
            prompt_template=_PROMPT_SKELETON,
        )
        self._client = make_tracked_client(api_key=settings.anthropic_api_key)
        self._feed = PolymarketFeed()

    async def get_market_conviction(self, symbol: str) -> dict:
        """
        Get Polymarket-derived conviction score for a symbol.
        Returns: {"conviction_boost": float, "signals": list, "summary": str}
        """
        signals = await self._feed.get_trading_signals()
        symbol_base = symbol.split("/")[0]  # XRP from XRP/USDT

        # Filter relevant signals
        relevant = [s for s in signals if s.relevance in (symbol_base, "MACRO", "CRYPTO")]

        if not relevant:
            return {"conviction_boost": 0.0, "signals": [], "summary": "No relevant Polymarket data"}

        # Calculate conviction boost based on signal alignment
        xrp_signals = [s for s in relevant if s.relevance == "XRP"]
        macro_signals = [s for s in relevant if s.relevance == "MACRO"]

        conviction_boost = 0.0
        for sig in xrp_signals[:3]:
            # XRP-specific markets have the most impact
            if sig.yes_price > 0.7:  # High probability YES
                conviction_boost += 0.05 * (sig.yes_price - 0.5) * 2
            elif sig.yes_price < 0.3:  # High probability NO
                conviction_boost -= 0.05 * (0.5 - sig.yes_price) * 2

        for sig in macro_signals[:3]:
            # Macro signals have smaller impact
            if sig.yes_price > 0.7:
                conviction_boost += 0.02

        conviction_boost = max(-0.2, min(0.2, conviction_boost))  # Cap at ±20%

        summary_parts = [f"{s.question[:60]}... → {s.yes_price:.0%} YES" for s in relevant[:5]]

        return {
            "conviction_boost": conviction_boost,
            "signals": [{"q": s.question, "prob": s.yes_price, "vol": s.volume_24h} for s in relevant[:5]],
            "summary": " | ".join(summary_parts),
        }

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data", {})
        symbol = market.get("symbol", "XRP/USDT")

        conviction = await self.get_market_conviction(symbol)
        boost = conviction.get("conviction_boost", 0.0)

        # Adjust existing signal confidences
        updated_signals = []
        for sig in state.get("signals", []):
            adjusted = dict(sig)
            adjusted["confidence"] = min(0.95, sig["confidence"] + boost)
            adjusted["polymarket_boost"] = boost
            updated_signals.append(adjusted)

        updated = dict(state)
        updated["signals"] = updated_signals
        updated["polymarket_context"] = conviction

        logger.info("polymarket_conviction_applied",
                    symbol=symbol,
                    boost=boost,
                    summary=conviction.get("summary", ""))

        return AgentState(**updated)
