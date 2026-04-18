"""Commodity futures price source via yfinance.

Coinbase doesn't list futures and Alpaca's futures coverage is limited to a
handful of contracts. yfinance pulls from Yahoo Finance which has full
coverage of COMEX/NYMEX/CBOT/ICE tickers (GC=F, CL=F, SI=F, etc.). Free,
no API key.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

logger = structlog.get_logger()

COMMODITY_SYMBOLS = [
    "GC=F", "SI=F", "HG=F",
    "CL=F", "NG=F",
    "ZW=F", "ZC=F", "ZS=F",
]

_TF_INTERVAL = {"1d": "1d", "1h": "60m", "5m": "5m", "15m": "15m", "1m": "1m"}
_TF_PERIOD = {"1d": "3mo", "1h": "1mo", "5m": "5d", "15m": "5d", "1m": "1d"}


def _sync_fetch_quote(symbol: str) -> dict[str, Any] | None:
    """Synchronous yfinance call — wrap in run_in_executor to call from async."""
    try:
        import yfinance as yf  # type: ignore[import]
        t = yf.Ticker(symbol)
        info = t.fast_info
        last = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        if last is None:
            return None
        prev = getattr(info, "previous_close", None) or last
        change = float(last) - float(prev)
        change_pct = (change / float(prev)) if prev else 0.0
        return {
            "symbol": symbol,
            "last": float(last),
            "previous_close": float(prev),
            "change": round(change, 6),
            "change_pct": round(change_pct, 6),
            "currency": getattr(info, "currency", "USD") or "USD",
            "ts": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance_quote_failed", symbol=symbol, error=str(exc))
        return None


async def fetch_quote(symbol: str) -> dict[str, Any] | None:
    return await asyncio.get_event_loop().run_in_executor(None, _sync_fetch_quote, symbol)


async def fetch_all_quotes(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    symbols = symbols or COMMODITY_SYMBOLS
    results = await asyncio.gather(
        *[fetch_quote(s) for s in symbols], return_exceptions=True,
    )
    return [r for r in results if isinstance(r, dict)]


def _sync_fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> list[dict[str, Any]]:
    try:
        import yfinance as yf  # type: ignore[import]
        interval = _TF_INTERVAL.get(timeframe, "1d")
        period = _TF_PERIOD.get(timeframe, "3mo")
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        rows: list[dict[str, Any]] = []
        for ts, row in hist.tail(limit).iterrows():
            rows.append({
                "symbol": symbol,
                "exchange": "yfinance",
                "timeframe": timeframe,
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance_ohlcv_failed", symbol=symbol, error=str(exc))
        return []


async def fetch_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 100) -> list[dict[str, Any]]:
    return await asyncio.get_event_loop().run_in_executor(
        None, _sync_fetch_ohlcv, symbol, timeframe, limit,
    )
