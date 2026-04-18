"""
Macro Analyst Agent — FRED-powered cross-asset macro signal generator.

Runs on a slow 30-minute cycle (macro doesn't change by the minute).
Outputs are cached in Redis so every graph cycle can read them without
re-hitting the FRED API.

Key insight: macro signals operate on a different timeframe than
technical signals. A VIX spike or yield curve inversion changes the
probability distribution for ALL assets over weeks, not hours.
This agent captures that slow-moving but high-conviction context.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any

from src.core.llm_costs import make_tracked_client

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings
from src.core.redis import get_redis
from src.data.feeds.fred_feed import FREDFeed

logger = logging.getLogger(__name__)

# Symbols this agent produces signals for
MACRO_SYMBOLS = ["XRP/USDT", "GC=F", "CL=F", "BTC/USDT"]

# Redis key for cached macro snapshot (read by all agents every cycle)
MACRO_CACHE_KEY = "macro:snapshot:latest"
MACRO_CACHE_TTL = 1800  # 30 minutes

# Per-symbol macro context — how each asset responds to macro regimes
SYMBOL_MACRO_CONTEXT: dict[str, str] = {
    "XRP/USDT": """
XRP macro sensitivity:
- HIGH risk-off sensitivity: XRP sells off hard when VIX spikes (retail-heavy asset).
- Rate sensitive: rising yields reduce appetite for speculative assets.
- Dollar strength bearish: XRP priced in USD, strong dollar = reduced foreign buying.
- Yield curve inversion: historically precedes 20-40% XRP drawdowns over 3-6 months.
- RISK_ON regime: XRP outperforms most crypto (high beta to crypto market).
- Key: XRP is NOT a store of value — it trades on risk appetite and liquidity.
""",
    "GC=F": """
Gold macro sensitivity:
- INVERSE to real yields (10Y TIPS): most important single driver.
- Inverse to USD: weaker dollar = gold up (gold is priced in USD).
- RISK_OFF safe haven: VIX spikes typically boost gold within 1-2 weeks.
- Oil-inflation cascade: rising inflation expectations support gold.
- Yield curve inversion: gold often rallies as recession fears mount.
- RISK_ON regime: gold may lag equities but stays supported.
""",
    "CL=F": """
WTI Crude Oil macro sensitivity:
- Dollar inverse: strong USD reduces global purchasing power for oil.
- Growth-sensitive: yield curve inversion = demand slowdown expectations = bearish.
- Oil IS the cascade trigger: oil up → inflation up → Fed hawkish → all assets affected.
- RISK_OFF: oil sells off on demand destruction fears (except geopolitical spikes).
- VIX spike: oil drops initially as recession fears dominate supply concerns.
""",
    "BTC/USDT": """
Bitcoin macro sensitivity:
- Behaves like high-beta tech in risk-off: drops more than equities initially.
- Rate sensitive: rising real yields reduce appetite for non-yielding assets.
- RISK_ON: BTC leads crypto recovery, typically 2-4 weeks after VIX peaks.
- Yield curve inversion: historically correlates with crypto bear markets.
- Long-term: Bitcoin is a bet against fiat/central bank credibility — inflation bullish long-term.
""",
}


class MacroAnalystAgent(BaseAgent):
    """
    FRED macro analyst — produces medium-term signals for XRP, gold, and crude.

    Cycle: runs every 30 minutes. Caches its snapshot in Redis so all other
    agents can read macro context without API calls.

    Confidence cap: 0.70 max (macro is noisy — high confidence requires
    multiple confirming signals, e.g. yield curve inversion + VIX > 30).
    """

    MAX_CONFIDENCE = 0.70

    def __init__(self) -> None:
        super().__init__("macro_analyst", "Macro Analyst", "Macro Economist")
        self._client = make_tracked_client(api_key=settings.anthropic_api_key)
        self._feed = FREDFeed()

    async def _cache_snapshot(self, snapshot: dict) -> None:
        """Write macro snapshot to Redis for consumption by other agents."""
        try:
            redis = get_redis()
            await redis.setex(
                MACRO_CACHE_KEY,
                MACRO_CACHE_TTL,
                json.dumps(snapshot, default=str),
            )
            logger.debug("macro_snapshot_cached ttl=%ds", MACRO_CACHE_TTL)
        except Exception as exc:
            logger.warning("macro_cache_write_error err=%s", exc)

    @staticmethod
    async def read_cached_snapshot() -> dict[str, Any] | None:
        """
        Read macro snapshot from Redis cache.
        Called by other agents that need macro context without running FRED queries.
        Returns None when cache is cold or Redis is unavailable.
        """
        try:
            redis = get_redis()
            raw = await redis.get(MACRO_CACHE_KEY)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("macro_cache_read_error err=%s", exc)
        return None

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        # Only activate for symbols with known macro sensitivity
        if symbol not in MACRO_SYMBOLS:
            return state

        # Fetch macro data — gracefully handles missing API key
        snapshot = await self._feed.get_macro_snapshot()
        cascade_signals = await self._feed.get_cascade_signals()

        # Cache for other agents to read
        await self._cache_snapshot(snapshot)

        summary = snapshot.get("_summary", {})
        regime = summary.get("regime", "UNKNOWN")
        vix = summary.get("vix")
        yield_curve = summary.get("yield_curve_spread")
        oil = summary.get("oil_price")
        rate_10y = summary.get("rate_10y")
        rate_2y = summary.get("rate_2y")

        symbol_context = SYMBOL_MACRO_CONTEXT.get(symbol, "")
        cascade_text = json.dumps(cascade_signals, indent=2) if cascade_signals else "None detected"

        prompt = f"""You are a macro economist at a global macro hedge fund.
Your job: translate FRED macro data into directional signals for specific assets.
You have a 2-4 week forward-looking timeframe (medium-term, not intraday).

=== CURRENT MACRO REGIME: {regime} ===

Key readings:
- VIX (fear gauge): {vix}
- 10Y-2Y yield spread (yield curve): {yield_curve}%
- 10Y Treasury yield: {rate_10y}%
- 2Y Treasury yield: {rate_2y}%
- WTI crude oil: ${oil}

Active cascade signals:
{cascade_text}

=== TARGET ASSET: {symbol} ===
{symbol_context}

Produce a directional macro signal for {symbol} over the next 2-4 weeks.
Be conservative — macro signals are noisy. Max confidence 0.70.
Only go above 0.60 when 2+ signals align (e.g. yield curve inverted AND VIX elevated).

Respond ONLY in valid JSON:
{{"direction": "LONG|SHORT|NEUTRAL", "confidence": 0.0-0.70, "thesis": "2-3 sentences", "primary_macro_driver": "vix|yield_curve|oil_cascade|rates|regime", "timeframe": "macro_medium_term", "key_risk": "what invalidates this"}}"""

        try:
            resp = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}

            direction = data.get("direction", "NEUTRAL")
            confidence = min(
                self.MAX_CONFIDENCE,
                float(data.get("confidence", 0.40)),
            )
            thesis = data.get("thesis", "")
            driver = data.get("primary_macro_driver", "regime")
            timeframe = data.get("timeframe", "macro_medium_term")
            key_risk = data.get("key_risk", "")

            # Boost confidence slightly when cascade signals align with LLM direction
            for cs in cascade_signals:
                cs_dir = cs.get("direction", "")
                if direction == "SHORT" and "BEARISH" in cs_dir:
                    confidence = min(self.MAX_CONFIDENCE, confidence + 0.05)
                elif direction == "LONG" and "BULLISH" in cs_dir:
                    confidence = min(self.MAX_CONFIDENCE, confidence + 0.05)

            full_thesis = (
                f"[MACRO {regime}] {thesis} "
                f"[VIX:{vix} YC:{yield_curve}% 10Y:{rate_10y}%]"
            )
            if cascade_signals:
                first_cascade = cascade_signals[0]["cascade"].replace("_", " ").upper()
                full_thesis += f" [Cascade: {first_cascade}]"

            await self.emit_signal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                thesis=full_thesis,
                strategy=f"macro_{driver}",
            )

            updated = dict(state)
            updated["signals"] = state.get("signals", []) + [{
                "agent": self.name,
                "direction": direction,
                "confidence": confidence,
                "thesis": full_thesis,
                "timeframe": timeframe,
                "key_risk": key_risk,
                "regime": regime,
                "cascade_signals": [c["cascade"] for c in cascade_signals],
                "symbol": symbol,
            }]
            return AgentState(**updated)

        except Exception as exc:
            logger.error("macro_analyst_error symbol=%s err=%s", symbol, exc)
            return state

    async def close(self) -> None:
        await self._feed.close()
