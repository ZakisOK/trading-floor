"""
Commodities Analyst Agent â€” multi-asset commodity specialist.

Activates for any Yahoo Finance futures symbol (GC=F, CL=F, NG=F, etc.).
Synthesizes COT positioning, seasonal bias, macro context, and sector
fundamentals into a single direction/confidence/thesis signal.

Key commodity frameworks:
  Gold:     Inverse USD + real yield sensitivity. Safe-haven demand in risk-off.
  Oil:      OPEC+ supply decisions, US inventory builds/draws, refinery runs.
  Nat Gas:  Highly seasonal. Storage levels vs 5-year average. Weather forecasts.
  Ag:       USDA WASDE reports, weather in key growing regions, export demand.
  Copper:   Leading global growth indicator. China PMI and property sector health.
  Silver:   Hybrid metal/precious. Industrial demand + gold ratio mean reversion.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from anthropic import AsyncAnthropic

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings
from src.data.feeds.commodities_feed import (
    CommoditiesFeed,
    SYMBOL_NAMES,
    COMMODITY_SYMBOLS,
)

logger = logging.getLogger(__name__)

# All commodity tickers we handle
ALL_COMMODITY_TICKERS = set(SYMBOL_NAMES.keys())

# Per-commodity context injected into the LLM prompt
COMMODITY_CONTEXT: dict[str, str] = {
    "GC=F": """
Gold-specific drivers:
- PRIMARY: 10-year TIPS real yield (inverse). When real yields fall, gold rallies.
- US Dollar (DXY): strong inverse correlation. Weaker USD = gold up.
- VIX > 25: risk-off buying, safe-haven demand spikes.
- Central bank buying (China, India, EM) is a structural bid.
- Resistance: $2,100 / $2,500. Support: $1,800 / $2,000 (round numbers matter).
- COT: commercials (bullion banks) rarely net long â€” when they are, it's a major signal.
""",
    "SI=F": """
Silver-specific drivers:
- Dual nature: part precious metal, part industrial metal (solar panels, EVs).
- Gold/Silver ratio: when >80, silver is historically undervalued vs gold.
- More volatile than gold â€” larger beta to moves in the gold complex.
- Industrial demand from green energy transition is structural tailwind.
- Thinner market means larger COT swings are more meaningful.
""",
    "CL=F": """
WTI Crude Oil-specific drivers:
- OPEC+ production decisions (meetings every 6 weeks) â€” single biggest variable.
- EIA weekly petroleum status report: crude inventories at Cushing, Oklahoma.
  Build > 2M bbl = bearish; Draw > 2M bbl = bullish.
- US shale production break-even ~$55-65/bbl â€” significant at these levels.
- Geopolitical risk premium: Middle East tensions, Russia/Ukraine.
- Contango/backwardation of futures curve reveals demand vs supply balance.
- Seasonal demand: summer driving season (May-Aug), winter heating (Nov-Feb).
""",
    "BZ=F": """
Brent Crude drivers (similar to WTI but global benchmark):
- More geopolitically sensitive than WTI.
- Brent/WTI spread signals US domestic supply vs global supply dynamics.
- Shipping route disruptions (Suez, Strait of Hormuz) impact Brent more.
""",
    "NG=F": """
Natural Gas-specific drivers (most seasonal of all commodities):
- EIA weekly storage report (Thursdays): compares to 5-year average.
  Storage deficit vs 5yr avg = bullish; surplus = bearish.
- Winter heating demand (Nov-Feb) and summer cooling demand (Jun-Aug).
- Henry Hub is US domestic price â€” heavily influenced by LNG export capacity.
- Weather forecasts (heating/cooling degree days) drive 1-2 week moves.
- Historical mean ~$3/MMBtu. Extremes (>$6 or <$2) revert sharply.
""",
    "HG=F": """
Copper-specific drivers (Dr. Copper â€” leading economic indicator):
- China accounts for ~55% of global copper demand. Watch China PMI, property sector.
- Chile/Peru supply disruptions (mining strikes, weather).
- LME warehouse inventory levels.
- Green energy transition is structural demand driver (EVs, wind, solar).
- Tracks global growth expectations more than any other commodity.
""",
    "ZC=F": """
Corn-specific drivers:
- USDA WASDE report (monthly): the most important ag report â€” watch planted acres,
  yield estimates, ending stocks.
- US crop conditions (weekly): % rated Good/Excellent during growing season.
- Ethanol demand (~40% of US corn) and export demand (China is key buyer).
- Key weather: Iowa/Illinois during June-July pollination is critical.
- Seasonal: often rallies Mar-May on planting uncertainty, sells off post-harvest.
""",
    "ZW=F": """
Wheat-specific drivers:
- Multiple origins matter: US (CBOT), Russia/Ukraine (biggest global exporters),
  Australia, EU (Euronext).
- Russia export quotas and geopolitical disruption = major supply shock risk.
- USDA export sales (weekly) â€” large Chinese purchases = bullish.
- Winter wheat dormancy (Oct-Feb), spring weather re-emergence.
""",
    "ZS=F": """
Soybeans-specific drivers:
- Brazil/Argentina weather during Dec-Feb (Southern Hemisphere summer) is critical.
  Drought in Brazil = major supply shock.
- China import demand â€” biggest single buyer of US soybeans.
- USDA crush data: crush margins track biodiesel demand.
- Soybean/corn ratio: when beans are expensive vs corn, farmers shift acreage.
""",
    "KC=F": """
Coffee-specific drivers:
- Brazil (largest producer): frost risk in July-August, drought in flowering period (Oct-Nov).
- Colombia (arabica quality): La Nina/El Nina weather patterns.
- ICE warehouse certified stocks.
- Currency: Brazilian Real weakening = Brazilian farmers sell more USD-denominated coffee
  (bearish for price). BRL strengthening = they hold back (bullish).
""",
    "PL=F": """
Platinum-specific drivers:
- Primary uses: autocatalysts (diesel engines), hydrogen fuel cells.
- South Africa produces ~75% of world supply â€” labor strikes are key risk.
- Platinum discount to gold is historically unusual â€” structural opportunity.
- Hydrogen economy growth is a multi-year demand tailwind.
""",
    "HO=F": """
Heating Oil-specific drivers:
- Distillate demand: heavy trucks, jet fuel, space heating.
- East Coast US heating demand in winter (major market).
- Crack spread (HO premium to crude) indicates refinery profitability.
- EIA distillate stocks are the key weekly data point.
""",
}

# Default context for symbols without specific entry
_DEFAULT_CONTEXT = """
This commodity futures contract follows standard supply/demand dynamics.
Monitor COT positioning for smart money signals, apply seasonal bias,
and factor in macro USD and risk sentiment context.
"""


class CommoditiesAnalystAgent(BaseAgent):
    """
    Commodity-specialist research agent.

    Activates for any Yahoo Finance futures ticker (ends with =F or is in
    ALL_COMMODITY_TICKERS). Skips gracefully for crypto and equities.
    """

    def __init__(self) -> None:
        super().__init__("commodities_analyst", "Commodities Analyst", "Commodity Specialist")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._feed = CommoditiesFeed()

    def _is_commodity(self, symbol: str) -> bool:
        return symbol in ALL_COMMODITY_TICKERS or symbol.endswith("=F")

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        if not self._is_commodity(symbol):
            return state  # Not a commodity â€” pass through

        current_month = date.today().month

        # Fetch data concurrently
        import asyncio

        async def _seasonal() -> dict:
            return self._feed.get_seasonal_bias(symbol, current_month)

        price_data, cot_data, seasonal, macro = await asyncio.gather(
            self._feed.get_price(symbol),
            self._feed.get_cot_data(symbol),
            _seasonal(),
            self._feed.get_macro_context(),
            return_exceptions=True,
        )

        # Defensive: replace exceptions with empty dicts
        if isinstance(price_data, Exception):
            price_data = {}
        if isinstance(cot_data, Exception):
            cot_data = {}
        if isinstance(seasonal, Exception):
            seasonal = {}
        if isinstance(macro, Exception):
            macro = {}

        commodity_name = SYMBOL_NAMES.get(symbol, symbol)
        specific_context = COMMODITY_CONTEXT.get(symbol, _DEFAULT_CONTEXT)

        # Determine asset class for the prompt
        asset_class = "commodity"
        for cls, tickers in COMMODITY_SYMBOLS.items():
            if symbol in tickers:
                asset_class = cls
                break

        # Fetch EIA report for energy commodities
        eia_data: dict = {}
        if asset_class == "energy":
            try:
                eia_data = await self._feed.get_eia_report()
            except Exception:
                eia_data = {}

        prompt = f"""You are a commodities specialist analyst at a multi-asset trading firm.
You specialize in {asset_class} markets with deep knowledge of physical supply/demand.

=== COMMODITY: {commodity_name} ({symbol}) ===

{specific_context}

=== CURRENT DATA ===
Price data: {json.dumps(price_data, default=str)}
COT (Commitment of Traders): {json.dumps(cot_data, default=str)}
Seasonal bias (month {current_month}): {json.dumps(seasonal, default=str)}
Macro context (USD, real yields, VIX): {json.dumps(macro, default=str)}
{f'EIA petroleum report: {json.dumps(eia_data, default=str)}' if eia_data else ''}

=== ANALYSIS FRAMEWORK ===
1. COT positioning: Are commercials (smart money) signaling? Is speculator positioning extreme?
2. Seasonal tendency: Does the calendar support the trade?
3. Macro tailwinds/headwinds: USD direction, real yields, risk sentiment
4. Sector fundamentals: Supply/demand balance, key scheduled reports
5. Technical context: Price relative to key levels from price data

Produce your commodity analysis:
- direction: LONG / SHORT / NEUTRAL
- confidence: 0.0-1.0 (be conservative â€” commodity markets are volatile)
- thesis: 2-3 sentences focusing on the most important signal
- primary_driver: the single factor driving your view (cot/seasonal/macro/fundamental/technical)
- key_risk: the main thing that invalidates your thesis
- timeframe: short (days) / medium (weeks) / long (months)

Respond ONLY in valid JSON:
{{"direction": "LONG", "confidence": 0.72, "thesis": "...", "primary_driver": "cot", "key_risk": "...", "timeframe": "medium"}}"""

        try:
            resp = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}

            direction = data.get("direction", "NEUTRAL")
            confidence = float(data.get("confidence", 0.5))
            thesis = data.get("thesis", "")
            primary_driver = data.get("primary_driver", "technical")
            key_risk = data.get("key_risk", "")
            timeframe = data.get("timeframe", "medium")

            # Build a rich thesis with context
            full_thesis = thesis
            if cot_data.get("cot_available"):
                full_thesis += f" [COT: {cot_data.get('signal')} â€” commercials {cot_data.get('commercial_net_pct', 0):+.1f}% OI]"
            if seasonal.get("available"):
                full_thesis += f" [Seasonal: {seasonal.get('bias')} {seasonal.get('seasonal_return_pct', 0):+.1f}% avg]"

            await self.emit_signal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                thesis=full_thesis,
                strategy=f"commodities_{primary_driver}",
                entry=price_data.get("latest_close"),
            )

            updated = dict(state)
            updated["signals"] = state.get("signals", []) + [{
                "agent": self.name,
                "direction": direction,
                "confidence": confidence,
                "thesis": full_thesis,
                "primary_driver": primary_driver,
                "key_risk": key_risk,
                "timeframe": timeframe,
                "symbol": symbol,
                "asset_class": asset_class,
                "cot_signal": cot_data.get("signal", "N/A"),
                "seasonal_bias": seasonal.get("bias", "N/A"),
            }]
            return AgentState(**updated)

        except Exception as exc:
            logger.error("commodities_analyst_error symbol=%s err=%s", symbol, exc)
            return state
