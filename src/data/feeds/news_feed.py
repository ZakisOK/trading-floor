"""
Financial news feed using NewsAPI (free tier: 100 req/day).
Falls back to RSS feeds (Yahoo Finance, Reuters) if no API key set.
Fetches headlines relevant to each trading symbol.
"""
from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import httpx

from src.core.config import settings
from src.core.redis import get_redis

logger = logging.getLogger(__name__)

# NewsAPI base URL
NEWSAPI_URL = "https://newsapi.org/v2/everything"

# Symbol → search query list mapping
SYMBOL_QUERIES: dict[str, list[str]] = {
    # Crypto
    "BTC": ["Bitcoin", "BTC"],
    "BTC-USD": ["Bitcoin", "BTC"],
    "BTC/USD": ["Bitcoin", "BTC"],
    "ETH": ["Ethereum", "ETH"],
    "ETH-USD": ["Ethereum", "ETH"],
    "XRP": ["XRP", "Ripple", "XRPL"],
    "XRP-USD": ["XRP", "Ripple", "XRPL"],
    "SOL": ["Solana", "SOL"],
    "SOL-USD": ["Solana", "SOL"],
    # Commodities
    "GC=F": ["gold", "gold futures", "XAUUSD"],
    "SI=F": ["silver", "silver futures"],
    "CL=F": ["crude oil", "WTI", "oil futures"],
    "NG=F": ["natural gas", "natgas"],
    "HG=F": ["copper", "copper futures"],
    # Equity indices
    "SPY": ["S&P 500", "SPY", "equity market"],
    "QQQ": ["Nasdaq", "QQQ", "tech stocks"],
    "DIA": ["Dow Jones", "DJIA"],
    # FX
    "EURUSD=X": ["EUR/USD", "euro dollar"],
    "GBPUSD=X": ["GBP/USD", "pound dollar"],
    "DX-Y.NYB": ["US dollar index", "DXY"],
}

# RSS feeds per symbol (Yahoo Finance ticker → RSS URL)
YAHOO_RSS_TEMPLATE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={ticker}&region=US&lang=en-US"
)

SYMBOL_TICKERS: dict[str, str] = {
    "BTC": "BTC-USD",
    "BTC-USD": "BTC-USD",
    "ETH": "ETH-USD",
    "ETH-USD": "ETH-USD",
    "XRP": "XRP-USD",
    "XRP-USD": "XRP-USD",
    "SOL": "SOL-USD",
    "GC=F": "GC=F",
    "CL=F": "CL=F",
    "SI=F": "SI=F",
    "NG=F": "NG=F",
    "SPY": "SPY",
    "QQQ": "QQQ",
}

CACHE_TTL_SECONDS = 30 * 60  # 30-minute TTL


class NewsFeed:
    """Fetches financial news headlines for trading symbols.

    Priority:
      1. NewsAPI (if NEWS_API_KEY set) — structured, filterable by date
      2. Yahoo Finance RSS fallback — free, no key required
    Results are cached in Redis for 30 minutes to conserve API quota.
    """

    def __init__(self) -> None:
        self._api_key: str = settings.news_api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_headlines(
        self, symbol: str, hours_back: int = 24
    ) -> list[dict]:
        """Return recent headlines for *symbol*.

        Each item: {title, description, published_at, source, symbol}
        Returns [] if no news found or fetch fails.
        """
        cache_key = f"news:{symbol}:{hours_back}h"
        redis = get_redis()

        # Check Redis cache first
        cached = await redis.get(cache_key)
        if cached:
            try:
                result: list[dict] = json.loads(cached)
                logger.debug("news_cache_hit", extra={"symbol": symbol, "count": len(result)})
                return result
            except json.JSONDecodeError:
                pass

        headlines: list[dict] = []

        if self._api_key:
            headlines = await self._fetch_newsapi(symbol, hours_back)
        else:
            headlines = await self._fetch_rss(symbol, hours_back)

        # Cache even empty results to avoid hammering APIs
        await redis.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(headlines))
        logger.info(
            "news_fetched",
            extra={"symbol": symbol, "count": len(headlines),
                   "backend": "newsapi" if self._api_key else "rss"},
        )
        return headlines

    # ------------------------------------------------------------------
    # NewsAPI backend
    # ------------------------------------------------------------------

    async def _fetch_newsapi(self, symbol: str, hours_back: int) -> list[dict]:
        queries = SYMBOL_QUERIES.get(symbol.upper(), [symbol])
        query_str = " OR ".join(f'"{q}"' for q in queries)
        from_dt = (datetime.now(UTC) - timedelta(hours=hours_back)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        params = {
            "q": query_str,
            "from": from_dt,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 50,
            "apiKey": self._api_key,
        }
        try:
            client = await self._get_client()
            resp = await client.get(NEWSAPI_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "published_at": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "symbol": symbol,
                }
                for a in articles
                if a.get("title") and "[Removed]" not in a.get("title", "")
            ]
        except Exception as exc:
            logger.warning("newsapi_fetch_failed", extra={"symbol": symbol, "error": str(exc)})
            # Fall back to RSS on NewsAPI error
            return await self._fetch_rss(symbol, hours_back)

    # ------------------------------------------------------------------
    # RSS fallback backend
    # ------------------------------------------------------------------

    async def _fetch_rss(self, symbol: str, hours_back: int) -> list[dict]:
        ticker = SYMBOL_TICKERS.get(symbol.upper(), symbol)
        url = YAHOO_RSS_TEMPLATE.format(ticker=ticker)
        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
        headlines: list[dict] = []

        try:
            client = await self._get_client()
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                return []
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                description = (item.findtext("description") or "").strip()
                pub_date_str = (item.findtext("pubDate") or "").strip()
                source = (item.findtext("source") or "Yahoo Finance").strip()

                pub_dt = _parse_rfc2822(pub_date_str)
                if pub_dt and pub_dt < cutoff:
                    continue  # Too old

                headlines.append(
                    {
                        "title": title,
                        "description": description,
                        "published_at": pub_dt.isoformat() if pub_dt else pub_date_str,
                        "source": source,
                        "symbol": symbol,
                    }
                )
        except Exception as exc:
            logger.warning("rss_fetch_failed", extra={"symbol": symbol, "error": str(exc)})

        return headlines


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_rfc2822(date_str: str) -> datetime | None:
    """Parse RFC 2822 date strings like 'Thu, 10 Apr 2025 12:00:00 +0000'."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y %H:%M:%S %z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


# Module-level singleton
_feed_instance: NewsFeed | None = None


def get_news_feed() -> NewsFeed:
    global _feed_instance
    if _feed_instance is None:
        _feed_instance = NewsFeed()
    return _feed_instance
