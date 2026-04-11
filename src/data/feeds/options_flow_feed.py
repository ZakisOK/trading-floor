"""
Options flow — retail vs institutional divergence signal.
Unusual Whales provides unusual options activity data.
Free tier available via their public RSS feed and limited API.

Why options flow matters:
- Large institutional options buyers often know something before the public
- "Unusual" = position size much larger than normal for that ticker/strike/expiry
- Divergence between retail (small options) and institutional (large options) = signal

For crypto: CBOE/CME BTC and ETH options data is public.
For commodities: CBOT options flow via CME public data.

Data sources (in priority order):
  1. Unusual Whales API — free tier with RSS feed (no key needed for RSS)
  2. CME Group public options data — BTC, ETH, gold, crude (free, no key)
  3. Synthetic fallback using open interest proxy from yfinance
"""
from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# CME public options data endpoints (no auth required)
CME_OPTIONS_URLS: dict[str, str] = {
    "BTC/USDT": "https://www.cmegroup.com/CmeWS/mvc/Quotes/Option/10116/G/0/ALL",
    "ETH/USDT": "https://www.cmegroup.com/CmeWS/mvc/Quotes/Option/10310/G/0/ALL",
    "GC=F":     "https://www.cmegroup.com/CmeWS/mvc/Quotes/Option/444/G/0/ALL",
    "CL=F":     "https://www.cmegroup.com/CmeWS/mvc/Quotes/Option/425/G/0/ALL",
}

# Unusual Whales free RSS feed
UW_RSS_URL = "https://unusualwhales.com/rss"

# Signal thresholds
BULL_RATIO_THRESHOLD = 1.5   # call/put ratio > 1.5 → institutional bullish flow
BEAR_RATIO_THRESHOLD = 0.6   # call/put ratio < 0.6 → institutional bearish flow
UNUSUAL_STD_MULTIPLIER = 3.0  # position size > 3 std above avg = "unusual"

class OptionsFlowFeed:
    """
    Options flow data feed — detects unusual institutional vs retail positioning.

    All methods degrade gracefully. When no external data is available,
    returns NEUTRAL signal with zero confidence rather than raising.
    """

    def __init__(self) -> None:
        self._uw_key = os.getenv("UNUSUAL_WHALES_API_KEY", "")
        self._http = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "TradingFloor/1.0 (research; contact@tradingfloor.io)"},
        )

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    async def get_unusual_options(self, symbol: str) -> list[dict]:
        """
        Fetch unusual options activity for a symbol.

        Priority:
          1. Unusual Whales API (if key is set)
          2. Unusual Whales RSS feed (free, no key)
          3. CME public options chain (for BTC, ETH, gold, crude)
          4. yfinance options chain as last resort

        Each returned entry contains:
          strike, expiry, call_put, size, premium, implied_vol, unusual_score
        """
        flows: list[dict] = []

        # Try UW API first if key is set
        if self._uw_key:
            flows = await self._fetch_uw_api(symbol)
            if flows:
                return flows

        # Try UW RSS (free, symbol-filtered)
        flows = await self._fetch_uw_rss(symbol)
        if flows:
            return flows

        # CME public data for supported symbols
        if symbol in CME_OPTIONS_URLS:
            flows = await self._fetch_cme_options(symbol)
            if flows:
                return flows

        # yfinance fallback
        return await self._fetch_yfinance_options(symbol)

    async def get_options_signal(self, symbol: str) -> dict[str, Any]:
        """
        Compute a directional signal from options flow.

        Returns:
          {
            "symbol": str,
            "signal": "BULL" | "BEAR" | "NEUTRAL",
            "confidence": float,          # 0.0 – 0.85
            "flow_type": "INSTITUTIONAL" | "RETAIL" | "MIXED",
            "call_put_ratio": float,
            "unusual_trades": list[dict], # trades > 3 std above average size
            "total_call_premium": float,  # USD
            "total_put_premium": float,   # USD
            "data_source": str,
          }
        """
        flows = await self.get_unusual_options(symbol)

        if not flows:
            return {
                "symbol": symbol,
                "signal": "NEUTRAL",
                "confidence": 0.0,
                "flow_type": "MIXED",
                "call_put_ratio": 1.0,
                "unusual_trades": [],
                "total_call_premium": 0.0,
                "total_put_premium": 0.0,
                "data_source": "none",
            }

        calls = [f for f in flows if f.get("call_put", "").upper() == "CALL"]
        puts = [f for f in flows if f.get("call_put", "").upper() == "PUT"]

        total_call_premium = sum(f.get("premium", 0.0) for f in calls)
        total_put_premium = sum(f.get("premium", 0.0) for f in puts)

        # Call/put ratio by premium (dollar-weighted, not count-weighted)
        # Premium weighting captures large institutional trades more accurately
        if total_put_premium > 0:
            call_put_ratio = round(total_call_premium / total_put_premium, 3)
        else:
            call_put_ratio = 9.99 if total_call_premium > 0 else 1.0

        # Detect "unusual" trades — position size > 3 std above avg
        all_sizes = [f.get("size", 0) for f in flows if f.get("size")]
        unusual_trades: list[dict] = []
        if len(all_sizes) >= 4:
            avg_size = statistics.mean(all_sizes)
            try:
                std_size = statistics.stdev(all_sizes)
            except statistics.StatisticsError:
                std_size = 0.0
            threshold = avg_size + UNUSUAL_STD_MULTIPLIER * std_size
            unusual_trades = [
                f for f in flows if f.get("size", 0) >= threshold
            ]

        # Classify flow type by average trade size
        avg_premium = (
            statistics.mean([f.get("premium", 0) for f in flows]) if flows else 0
        )
        if avg_premium > 500_000:
            flow_type = "INSTITUTIONAL"
        elif avg_premium > 50_000:
            flow_type = "MIXED"
        else:
            flow_type = "RETAIL"

        # Directional signal
        if call_put_ratio >= BULL_RATIO_THRESHOLD:
            signal = "BULL"
            base_conf = min(0.75, 0.45 + (call_put_ratio - BULL_RATIO_THRESHOLD) * 0.15)
        elif call_put_ratio <= BEAR_RATIO_THRESHOLD:
            signal = "BEAR"
            base_conf = min(0.75, 0.45 + (BEAR_RATIO_THRESHOLD - call_put_ratio) * 0.20)
        else:
            signal = "NEUTRAL"
            base_conf = 0.0

        # Boost confidence for unusual (likely institutional) trades
        if unusual_trades:
            unusual_boost = min(0.10, len(unusual_trades) * 0.03)
            base_conf = min(0.85, base_conf + unusual_boost)

        # Institutional flow gets higher confidence (they have better info)
        if flow_type == "INSTITUTIONAL" and signal != "NEUTRAL":
            base_conf = min(0.85, base_conf + 0.05)

        data_source = flows[0].get("source", "unknown") if flows else "none"

        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": round(base_conf, 3),
            "flow_type": flow_type,
            "call_put_ratio": call_put_ratio,
            "unusual_trades": unusual_trades[:5],  # top 5 for display
            "total_call_premium": round(total_call_premium, 0),
            "total_put_premium": round(total_put_premium, 0),
            "data_source": data_source,
        }

    # ------------------------------------------------------------------
    # Data source implementations
    # ------------------------------------------------------------------

    async def _fetch_uw_api(self, symbol: str) -> list[dict]:
        """Fetch from Unusual Whales paid API (requires UNUSUAL_WHALES_API_KEY)."""
        try:
            # Map trading symbols to UW ticker format
            uw_ticker = symbol.replace("/USDT", "").replace("=F", "")
            resp = await self._http.get(
                f"https://phx.unusualwhales.com/api/option-trades/{uw_ticker}",
                headers={"Authorization": f"Bearer {self._uw_key}"},
                params={"limit": 50, "date": datetime.now().strftime("%Y-%m-%d")},
            )
            resp.raise_for_status()
            raw = resp.json().get("data", [])
            return [self._normalize_uw_trade(t) for t in raw]
        except Exception as exc:
            logger.debug("uw_api_error symbol=%s err=%s", symbol, exc)
            return []

    async def _fetch_uw_rss(self, symbol: str) -> list[dict]:
        """
        Parse Unusual Whales free RSS feed.
        Filters for mentions of the symbol in trade descriptions.
        Less structured than the API but free and no key required.
        """
        try:
            resp = await self._http.get(UW_RSS_URL, timeout=10.0)
            resp.raise_for_status()

            # Simple RSS text parse — avoid xml dependency
            content = resp.text
            items = content.split("<item>")[1:]  # Skip header

            # Map symbol to search terms in RSS descriptions
            search_terms = self._get_rss_search_terms(symbol)
            flows: list[dict] = []

            for item in items[:100]:  # Check first 100 items
                title = self._extract_xml_tag(item, "title")
                desc = self._extract_xml_tag(item, "description")
                pub_date = self._extract_xml_tag(item, "pubDate")
                combined = f"{title} {desc}".upper()

                if not any(t in combined for t in search_terms):
                    continue

                flow = self._parse_rss_flow(title, desc, pub_date, symbol)
                if flow:
                    flows.append(flow)

            return flows
        except Exception as exc:
            logger.debug("uw_rss_error symbol=%s err=%s", symbol, exc)
            return []

    async def _fetch_cme_options(self, symbol: str) -> list[dict]:
        """
        Fetch CME Group public options chain data.
        Free — no authentication required.
        Available for BTC, ETH (CME futures options), gold, crude oil.
        """
        url = CME_OPTIONS_URLS.get(symbol)
        if not url:
            return []
        try:
            resp = await self._http.get(url, timeout=12.0)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("optionContractQuotes", []) or data.get("quotes", [])
            flows: list[dict] = []
            for row in rows[:100]:
                calls = row.get("calls", [])
                puts = row.get("puts", [])
                strike = row.get("strikePrice") or row.get("strike", 0)
                expiry = row.get("expiration") or row.get("expirationDate", "")
                for c in calls[:3]:
                    vol = c.get("volume", 0) or 0
                    if vol > 0:
                        flows.append(self._build_flow_entry(
                            strike, expiry, "CALL", vol,
                            c.get("lastPrice", 0), c.get("impliedVolatility", 0),
                            "cme_public",
                        ))
                for p in puts[:3]:
                    vol = p.get("volume", 0) or 0
                    if vol > 0:
                        flows.append(self._build_flow_entry(
                            strike, expiry, "PUT", vol,
                            p.get("lastPrice", 0), p.get("impliedVolatility", 0),
                            "cme_public",
                        ))
            return flows
        except Exception as exc:
            logger.debug("cme_options_error symbol=%s err=%s", symbol, exc)
            return []

    async def _fetch_yfinance_options(self, symbol: str) -> list[dict]:
        """
        yfinance options chain as last-resort fallback.
        Works for equities and ETFs (SPY, QQQ) — NOT for crypto.
        For crypto/commodities, returns empty list.
        """
        yf_symbol = symbol.replace("/USDT", "-USD").replace("=F", "=F")
        if "USDT" in symbol:
            return []  # yfinance doesn't have crypto options

        try:
            import asyncio
            import yfinance as yf

            loop = asyncio.get_event_loop()
            ticker = yf.Ticker(yf_symbol)

            # Get nearest expiry
            exps = await loop.run_in_executor(None, lambda: ticker.options)
            if not exps:
                return []

            chain = await loop.run_in_executor(
                None, lambda: ticker.option_chain(exps[0])
            )
            flows: list[dict] = []
            for _, row in chain.calls.head(20).iterrows():
                if row.get("volume", 0) > 0:
                    flows.append(self._build_flow_entry(
                        row.get("strike", 0), exps[0], "CALL",
                        int(row.get("volume", 0)),
                        float(row.get("lastPrice", 0)),
                        float(row.get("impliedVolatility", 0)),
                        "yfinance",
                    ))
            for _, row in chain.puts.head(20).iterrows():
                if row.get("volume", 0) > 0:
                    flows.append(self._build_flow_entry(
                        row.get("strike", 0), exps[0], "PUT",
                        int(row.get("volume", 0)),
                        float(row.get("lastPrice", 0)),
                        float(row.get("impliedVolatility", 0)),
                        "yfinance",
                    ))
            return flows
        except Exception as exc:
            logger.debug("yfinance_options_error symbol=%s err=%s", symbol, exc)
            return []

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _build_flow_entry(
        strike: float,
        expiry: str,
        call_put: str,
        size: int,
        last_price: float,
        implied_vol: float,
        source: str,
    ) -> dict:
        """Build a normalized options flow dict."""
        premium = float(size) * float(last_price) * 100  # standard 100-multiplier
        # Unusual score: placeholder based on size (real score requires historical avg)
        unusual_score = min(10.0, size / 100.0)
        return {
            "strike": float(strike),
            "expiry": str(expiry),
            "call_put": call_put,
            "size": int(size),
            "last_price": float(last_price),
            "premium": round(premium, 0),
            "implied_vol": round(float(implied_vol), 4),
            "unusual_score": round(unusual_score, 2),
            "source": source,
        }

    @staticmethod
    def _normalize_uw_trade(trade: dict) -> dict:
        """Normalize an Unusual Whales API trade dict to our schema."""
        size = int(trade.get("volume", 0) or trade.get("size", 0) or 0)
        price = float(trade.get("price", 0) or 0)
        premium = float(trade.get("premium", 0) or size * price * 100)
        return {
            "strike": float(trade.get("strike_price", 0) or trade.get("strike", 0)),
            "expiry": str(trade.get("expiry", trade.get("expiration_date", ""))),
            "call_put": str(trade.get("put_call", trade.get("call_put", ""))).upper(),
            "size": size,
            "last_price": price,
            "premium": round(premium, 0),
            "implied_vol": round(float(trade.get("implied_volatility", 0) or 0), 4),
            "unusual_score": round(float(trade.get("unusual_score", 0) or 0), 2),
            "source": "unusual_whales_api",
        }

    @staticmethod
    def _get_rss_search_terms(symbol: str) -> list[str]:
        """Map trading symbols to RSS text search terms."""
        mapping = {
            "BTC/USDT": ["BTC", "BITCOIN", "MSTR", "IBIT", "GBTC"],
            "ETH/USDT": ["ETH", "ETHEREUM", "ETHA"],
            "GC=F":     ["GOLD", "GLD", "IAU", "GC"],
            "CL=F":     ["CRUDE", "OIL", "USO", "XLE", "CL"],
        }
        return mapping.get(symbol, [symbol.replace("/USDT", "").replace("=F", "")])

    @staticmethod
    def _extract_xml_tag(text: str, tag: str) -> str:
        """Extract content of an XML tag from a string (no xml lib needed)."""
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        end = text.find(end_tag)
        if start >= 0 and end > start:
            return text[start + len(start_tag):end].strip()
        return ""

    def _parse_rss_flow(
        self,
        title: str,
        description: str,
        pub_date: str,
        symbol: str,
    ) -> dict | None:
        """
        Parse an RSS item into an options flow dict.
        RSS items are narrative (e.g. '500 BTC Jan2025 $50K CALL sweep for $2.1M').
        We extract what we can; missing fields default to 0.
        """
        combined = f"{title} {description}".upper()
        call_put = "CALL" if "CALL" in combined else ("PUT" if "PUT" in combined)

        # Very rough premium parse: look for dollar amounts like $1.2M or $500K
        premium = 0.0
        import re
        m = re.search(r"\$(\d+(?:\.\d+)?)(M|K)?", combined)
        if m:
            val = float(m.group(1))
            suffix = m.group(2)
            premium = val * 1_000_000 if suffix == "M" else val * 1_000 if suffix == "K" else val

        if not call_put or premium == 0:
            return None

        return {
            "strike": 0.0,
            "expiry": pub_date,
            "call_put": call_put,
            "size": 0,
            "last_price": 0.0,
            "premium": premium,
            "implied_vol": 0.0,
            "unusual_score": min(10.0, premium / 100_000),
            "source": "unusual_whales_rss",
        }

    async def close(self) -> None:
        await self._http.aclose()
