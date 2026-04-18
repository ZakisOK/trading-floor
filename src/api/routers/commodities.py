"""Commodity futures quotes + OHLCV via yfinance."""
from __future__ import annotations

from fastapi import APIRouter, Query

from src.data.feeds.commodity_source import (
    COMMODITY_SYMBOLS, fetch_all_quotes, fetch_ohlcv, fetch_quote,
)

router = APIRouter(prefix="/api/commodities", tags=["commodities"])


@router.get("/quotes")
async def get_quotes(symbol: str | None = Query(default=None)) -> dict:
    """Return latest quotes for all tracked commodity futures."""
    if symbol:
        q = await fetch_quote(symbol)
        return {"quote": q, "source": "yfinance"}
    quotes = await fetch_all_quotes()
    return {"quotes": quotes, "source": "yfinance", "symbols": COMMODITY_SYMBOLS}


@router.get("/ohlcv/{symbol:path}")
async def get_ohlcv(
    symbol: str,
    timeframe: str = Query(default="1d"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Historical OHLCV bars for a commodity future."""
    bars = await fetch_ohlcv(symbol, timeframe, limit)
    return {"symbol": symbol, "timeframe": timeframe, "source": "yfinance", "bars": bars}
