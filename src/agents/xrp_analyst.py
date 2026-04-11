"""
XRP Analyst — combines XRPL on-chain data, technical analysis,
and macro signals (Fed policy, Ripple legal status) for XRP-specific thesis generation.
"""
from src.agents.base import BaseAgent, AgentState
from src.data.feeds.xrpl_feed import XRPLFeed
from src.core.config import settings
from anthropic import AsyncAnthropic
import structlog

logger = structlog.get_logger()

XRP_CONTEXT = """
Key XRP fundamentals to consider:
- Ripple ODL (On-Demand Liquidity): high corridor volume = bullish
- Monthly Ripple escrow releases (~1B XRP): oversupply risk
- XRPL DEX activity: growing ecosystem = bullish
- Regulatory clarity: SEC case resolution is a major catalyst
- XRP is used for cross-border payments — adoption metrics matter more than speculation
- Key resistance/support levels historically: $0.50, $1.00, $3.40 (ATH area)
- Correlation with BTC but also independent moves on Ripple news
"""


class XRPAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__("xrp_analyst", "XRP Analyst", "XRP Specialist")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._xrpl_feed = XRPLFeed()

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data", {})
        symbol = market.get("symbol", "XRP/USDT")
        if "XRP" not in symbol:
            return state  # Only analyze XRP

        # Fetch XRPL on-chain data
        network_stats = await self._xrpl_feed.get_network_stats()
        xrp_metrics = await self._xrpl_feed.get_xrp_metrics()
        odl_signals = await self._xrpl_feed.get_odl_signals()

        prompt = f"""You are an XRP specialist analyst at a trading firm.
{XRP_CONTEXT}

Current price data: {market}
XRPL network stats: {network_stats}
XRP on-chain metrics: {xrp_metrics}
ODL corridor activity: {odl_signals}

Provide a comprehensive XRP analysis:
1. Direction (LONG/SHORT/NEUTRAL)
2. Confidence (0.0-1.0)
3. Thesis focusing on: ODL adoption, escrow impact, technical level, macro catalyst
4. Key risk (regulatory, escrow release, BTC correlation)
5. Time horizon (short/medium/long term)

Respond in JSON: {{"direction": "LONG", "confidence": 0.78, "thesis": "...", "risk": "...", "timeframe": "medium"}}"""

        try:
            resp = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            import json
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}

            direction = data.get("direction", "NEUTRAL")
            confidence = float(data.get("confidence", 0.5))
            thesis = data.get("thesis", "")

            await self.emit_signal(symbol, direction, confidence, thesis, "xrp_specialist",
                                   entry=float(market.get("close", 0)) or None)

            updated = dict(state)
            updated["signals"] = state.get("signals", []) + [{
                "agent": self.name, "direction": direction,
                "confidence": confidence, "thesis": thesis,
                "timeframe": data.get("timeframe", "short"),
            }]
            return AgentState(**updated)
        except Exception as e:
            logger.error("xrp_analyst_error", error=str(e))
            return state
