"""Backfill historical OHLCV bars from Coinbase into TimescaleDB.

Run manually or via scheduler. Idempotent via ON CONFLICT DO NOTHING on the
(symbol, exchange, timeframe, ts) unique constraint.

    python scripts/ingest_ohlcv.py                # default: 90d hourly for the
                                                    standard symbol set
    python scripts/ingest_ohlcv.py --timeframe 1d --days 365
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy.dialects.postgresql import insert

from src.core.database import AsyncSessionLocal as async_session
from src.data.feeds.price_source import to_coinbase_symbol
from src.data.models.market import OHLCV

logger = structlog.get_logger()

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT",
    "DOT/USDT", "UNI/USDT",
    # MATIC delisted on Coinbase (Polygon rebrand to POL) \u2014 skip
]

# ccxt timeframe → seconds (Coinbase-supported only)
_TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400,
}


async def _fetch_bars(symbol: str, timeframe: str, since_ms: int, limit: int = 300) -> list[list[float]]:
    """Fetch one page of OHLCV from Coinbase via ccxt."""
    import ccxt.async_support as ccxt  # type: ignore[import]
    cb_symbol = to_coinbase_symbol(symbol)
    if cb_symbol is None:
        return []
    exchange = ccxt.coinbase({"enableRateLimit": True})
    try:
        return await exchange.fetch_ohlcv(cb_symbol, timeframe, since=since_ms, limit=limit)
    finally:
        await exchange.close()


async def ingest_one(symbol: str, timeframe: str, days: int) -> int:
    """Backfill `days` worth of `timeframe` bars for `symbol`. Returns rows inserted."""
    tf_seconds = _TF_SECONDS[timeframe]
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    since_ms = int(start.timestamp() * 1000)
    total_rows = 0

    while since_ms < int(now.timestamp() * 1000):
        try:
            bars = await _fetch_bars(symbol, timeframe, since_ms, limit=300)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ohlcv_fetch_failed", symbol=symbol, timeframe=timeframe,
                           since_ms=since_ms, error=str(exc))
            break
        if not bars:
            break

        values = []
        for ts_ms, o, h, l, c, v in bars:
            if ts_ms >= int(now.timestamp() * 1000):
                continue
            values.append({
                "symbol": symbol,
                "exchange": "coinbase",
                "timeframe": timeframe,
                "ts": datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                "open": Decimal(str(o)),
                "high": Decimal(str(h)),
                "low": Decimal(str(l)),
                "close": Decimal(str(c)),
                "volume": Decimal(str(v)),
            })

        if values:
            async with async_session() as session:
                stmt = insert(OHLCV).values(values).on_conflict_do_nothing(
                    index_elements=["symbol", "exchange", "timeframe", "ts"],
                )
                result = await session.execute(stmt)
                await session.commit()
                total_rows += result.rowcount or 0

        # Advance since by the span we just pulled (use last ts + one tf to avoid dup)
        last_ts_ms = bars[-1][0]
        new_since = last_ts_ms + tf_seconds * 1000
        if new_since <= since_ms:
            break
        since_ms = new_since
        await asyncio.sleep(0.3)  # gentle rate limit

    logger.info("ohlcv_backfill_complete", symbol=symbol, timeframe=timeframe,
                days=days, rows_inserted=total_rows)
    return total_rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", default="1h", choices=list(_TF_SECONDS.keys()))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()

    logger.info("ohlcv_backfill_start", timeframe=args.timeframe,
                days=args.days, symbols=args.symbols)

    results: dict[str, int] = {}
    for symbol in args.symbols:
        rows = await ingest_one(symbol, args.timeframe, args.days)
        results[symbol] = rows

    logger.info("ohlcv_backfill_done", summary=results)
    print("\nBackfill complete:")
    for sym, n in results.items():
        print(f"  {sym:<12} {n:>6} rows")


if __name__ == "__main__":
    asyncio.run(main())
