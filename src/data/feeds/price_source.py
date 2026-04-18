"""Single source of truth for live-price fetches — Coinbase via ccxt.

Handles symbol translation: BTC/USDT → BTC/USD. Callers pass our internal
USDT-denominated symbol; this module maps to Coinbase's USD pair before calling
the exchange. Commodity futures and equity tickers are rejected (they have
different data paths).
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


def to_coinbase_symbol(symbol: str) -> str | None:
    """Translate internal symbol to a Coinbase ccxt symbol. Returns None if unsupported."""
    if not symbol or "/" not in symbol:
        return None
    base, quote = symbol.split("/", 1)
    if "=" in base or "=" in quote:
        return None  # commodity futures like GC=F
    if quote.upper() in ("USDT", "USDC", "USD"):
        return f"{base.upper()}/USD"
    return None


async def fetch_price(symbol: str) -> float | None:
    """Return the latest trade price for symbol from Coinbase, or None on error."""
    cb_symbol = to_coinbase_symbol(symbol)
    if cb_symbol is None:
        return None
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.coinbase({"enableRateLimit": True})
        try:
            ticker = await exchange.fetch_ticker(cb_symbol)
        finally:
            await exchange.close()
        price = ticker.get("last") or (
            (ticker.get("bid", 0) + ticker.get("ask", 0)) / 2
        )
        return float(price) if price else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "coinbase_price_fetch_failed",
            symbol=symbol, coinbase_symbol=cb_symbol, error=str(exc),
        )
        return None
