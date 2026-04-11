"""
Polymarket prediction market feed.
Uses public Polymarket API — no auth required for reading market data.
Polymarket runs on Polygon blockchain, markets resolve to YES (1.0) or NO (0.0).

Why this matters for trading:
- Markets like "Will BTC hit $100k by Dec 2025?" give probability-weighted price targets
- "Will Fed cut rates in March?" predicts macro environment
- "Will XRP win SEC case?" directly impacts XRP price
- High-confidence prediction markets can shift agent conviction scores
"""
import httpx
import structlog
from datetime import datetime, UTC
from dataclasses import dataclass

logger = structlog.get_logger()

POLYMARKET_API = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"


@dataclass
class PolymarketSignal:
    question: str
    category: str
    yes_price: float      # 0.0-1.0 = probability of YES
    no_price: float
    volume_24h: float
    end_date: str
    relevance: str        # "XRP", "BTC", "MACRO", "CRYPTO"
    trading_implication: str  # How this affects our trades


class PolymarketFeed:
    def __init__(self):
        self._cache: list[PolymarketSignal] = []
        self._last_fetch: datetime | None = None

    async def get_crypto_markets(self, limit: int = 50) -> list[dict]:
        """Fetch active crypto-related prediction markets."""
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(
                    f"{POLYMARKET_API}/markets",
                    params={
                        "active": True,
                        "closed": False,
                        "tag_slug": "crypto",
                        "limit": limit,
                        "_order": "volume24hr",
                        "_sort": "desc",
                    }
                )
                return resp.json() if resp.status_code == 200 else []
            except Exception as e:
                logger.error("polymarket_fetch_error", error=str(e))
                return []

    async def get_xrp_markets(self) -> list[dict]:
        """Fetch all XRP/Ripple-related prediction markets."""
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(
                    f"{POLYMARKET_API}/markets",
                    params={
                        "active": True,
                        "closed": False,
                        "search": "XRP",
                        "limit": 20,
                    }
                )
                markets = resp.json() if resp.status_code == 200 else []
                # Also search for Ripple
                resp2 = await client.get(
                    f"{POLYMARKET_API}/markets",
                    params={"active": True, "closed": False, "search": "Ripple", "limit": 10}
                )
                markets += resp2.json() if resp2.status_code == 200 else []
                return markets
            except Exception as e:
                logger.error("polymarket_xrp_error", error=str(e))
                return []

    async def get_macro_markets(self) -> list[dict]:
        """Fetch macro markets relevant to crypto (Fed rates, inflation, etc.)."""
        async with httpx.AsyncClient(timeout=15) as client:
            searches = ["Federal Reserve", "interest rate", "inflation", "recession"]
            markets = []
            for search in searches:
                try:
                    resp = await client.get(
                        f"{POLYMARKET_API}/markets",
                        params={"active": True, "closed": False, "search": search, "limit": 5}
                    )
                    markets += resp.json() if resp.status_code == 200 else []
                except Exception:
                    pass
            return markets

    def extract_signal(self, market: dict) -> "PolymarketSignal | None":
        """Convert a Polymarket market to a trading signal."""
        try:
            question = market.get("question", "")
            yes_price = float(market.get("outcomePrices", ["0.5"])[0])
            volume = float(market.get("volume", 0))

            # Classify relevance
            q_lower = question.lower()
            if "xrp" in q_lower or "ripple" in q_lower:
                relevance = "XRP"
                implication = f"XRP-specific: market gives {yes_price:.0%} probability"
            elif "bitcoin" in q_lower or "btc" in q_lower:
                relevance = "BTC"
                implication = f"BTC signal affects XRP correlation: {yes_price:.0%}"
            elif "fed" in q_lower or "rate" in q_lower or "inflation" in q_lower:
                relevance = "MACRO"
                implication = f"Macro signal: {yes_price:.0%} — affects risk appetite"
            elif "crypto" in q_lower or "ethereum" in q_lower or "eth" in q_lower:
                relevance = "CRYPTO"
                implication = f"Broad crypto signal: {yes_price:.0%}"
            else:
                return None

            return PolymarketSignal(
                question=question,
                category=market.get("category", ""),
                yes_price=yes_price,
                no_price=1.0 - yes_price,
                volume_24h=volume,
                end_date=market.get("endDate", ""),
                relevance=relevance,
                trading_implication=implication,
            )
        except Exception:
            return None

    async def get_trading_signals(self) -> list[PolymarketSignal]:
        """
        Aggregate all relevant Polymarket signals for trading decisions.
        Sorted by volume (higher volume = more reliable probability).
        """
        all_markets = []
        all_markets += await self.get_xrp_markets()
        all_markets += await self.get_macro_markets()
        all_markets += await self.get_crypto_markets(limit=20)

        signals = []
        seen: set[str] = set()
        for market in all_markets:
            mid = market.get("id", "")
            if mid in seen:
                continue
            seen.add(mid)
            sig = self.extract_signal(market)
            if sig and sig.volume_24h > 1000:  # Only liquid markets
                signals.append(sig)

        signals.sort(key=lambda s: s.volume_24h, reverse=True)
        return signals[:15]  # Top 15 most relevant
