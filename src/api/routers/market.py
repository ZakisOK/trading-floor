"""Market data REST endpoints."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.data.models.market import OHLCV
from src.data.schemas.market import OHLCVResponse, SymbolInfo
from src.data.feeds.polymarket_feed import PolymarketFeed

router = APIRouter(prefix="/api/market", tags=["market"])

_poly_feed = PolymarketFeed()

_VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"}


@router.get("/prices")
async def get_prices(symbols: str | None = None) -> dict:
    """Return latest prices for a comma-separated list of symbols. Handles crypto + futures."""
    import asyncio
    from src.data.feeds.price_source import fetch_price
    from src.data.feeds.commodity_source import fetch_quote as fetch_commodity_quote
    if not symbols:
        symbols_list = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT",
                        "GC=F", "CL=F", "SI=F", "NG=F"]
    else:
        symbols_list = [s.strip() for s in symbols.split(",") if s.strip()]

    async def one(sym: str) -> dict:
        if sym.endswith("=F") or sym.startswith(("GC", "CL", "SI", "HG", "NG", "ZW", "ZC", "ZS")):
            q = await fetch_commodity_quote(sym)
            if q:
                return {"symbol": sym, "price": q["last"], "change_pct": q["change_pct"]}
        p = await fetch_price(sym)
        return {"symbol": sym, "price": p, "change_pct": None}

    results = await asyncio.gather(*[one(s) for s in symbols_list], return_exceptions=True)
    return {"prices": [r for r in results if isinstance(r, dict)]}


@router.get("/ohlcv/{symbol:path}", response_model=list[OHLCVResponse])
async def get_ohlcv(
    symbol: str,
    exchange: Annotated[str, Query()] = "coinbase",
    timeframe: Annotated[str, Query()] = "1h",
    limit: Annotated[int, Query(ge=1, le=5000)] = 200,
    before: Annotated[datetime | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> list[OHLCVResponse]:
    """Fetch OHLCV candles for a symbol from TimescaleDB."""
    if timeframe not in _VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe. Valid options: {sorted(_VALID_TIMEFRAMES)}",
        )

    stmt = (
        select(OHLCV)
        .where(
            OHLCV.symbol == symbol.upper(),
            OHLCV.exchange == exchange.lower(),
            OHLCV.timeframe == timeframe,
        )
        .order_by(OHLCV.ts.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(OHLCV.ts < before)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        OHLCVResponse(
            symbol=row.symbol,
            exchange=row.exchange,
            timeframe=row.timeframe,
            ts=row.ts,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in reversed(rows)
    ]


@router.get("/symbols", response_model=list[SymbolInfo])
async def get_symbols(
    exchange: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> list[SymbolInfo]:
    """Return all symbols that have OHLCV data in the database."""
    stmt = select(OHLCV.symbol, OHLCV.exchange).distinct()
    if exchange:
        stmt = stmt.where(OHLCV.exchange == exchange.lower())
    result = await session.execute(stmt)
    rows = result.all()

    symbols: list[SymbolInfo] = []
    for row in rows:
        sym: str = row.symbol
        exch: str = row.exchange
        asset_class = "equity" if exch == "alpaca" else "crypto"
        parts = sym.split("/")
        base  = parts[0] if len(parts) > 1 else sym
        quote = parts[1] if len(parts) > 1 else ""
        symbols.append(SymbolInfo(symbol=sym, exchange=exch, asset_class=asset_class, base=base, quote=quote))
    return symbols


@router.get("/timeframes", response_model=list[str])
async def get_timeframes() -> list[str]:
    """Return all valid timeframe strings."""
    return sorted(_VALID_TIMEFRAMES)


@router.get("/polymarket/signals")
async def get_polymarket_signals(symbol: str = "XRP/USDT") -> list[dict]:
    """Get Polymarket prediction market signals relevant to a trading symbol."""
    signals = await _poly_feed.get_trading_signals()
    return [
        {
            "question": s.question,
            "yes_probability": s.yes_price,
            "no_probability": s.no_price,
            "volume_24h": s.volume_24h,
            "relevance": s.relevance,
            "implication": s.trading_implication,
            "end_date": s.end_date,
        }
        for s in signals
    ]


@router.get("/polymarket/xrp")
async def get_xrp_polymarket() -> list[dict]:
    """Get XRP-specific Polymarket markets."""
    markets = await _poly_feed.get_xrp_markets()
    return markets[:10]


# ---------------------------------------------------------------------------
# New Phase 2 endpoints: regime, sentiment, carry
# ---------------------------------------------------------------------------

@router.get("/regime")
async def get_market_regime(symbol: str = "XRP/USDT") -> dict:
    """
    Return current market regime for a symbol from Redis cache.

    Regime is written by RegimeDetector at the start of every graph cycle
    (TTL 10 min). Returns UNKNOWN when no cycle has run yet.

    Values: TRENDING | RANGING | VOLATILE | UNKNOWN
    """
    try:
        from src.core.redis import get_redis
        redis = get_redis()
        safe_sym = symbol.replace("/", "_")
        regime = await redis.get(f"market:regime:{safe_sym}")
        if not regime:
            # Fallback: check global key written by older graph versions
            regime = await redis.get("market:regime")
        return {
            "symbol": symbol,
            "regime": (regime or "UNKNOWN"),
            "source": "redis_cache",
        }
    except Exception as exc:
        return {"symbol": symbol, "regime": "UNKNOWN", "error": str(exc)}


@router.get("/sentiment/{symbol}")
async def get_sentiment(symbol: str) -> dict:
    """
    Return latest FinBERT/VADER sentiment score and recent headlines for a symbol.

    Data is written to Redis by SentimentAnalystAgent after each graph cycle.
    Key: sentiment:{symbol}  (TTL 3600s / 1 hour)

    Returns:
      score      float  [-1.0, +1.0]  (positive = bullish sentiment)
      label      str    BULLISH | BEARISH | NEUTRAL
      confidence float  [0.0, 1.0]
      headlines  list   up to 5 recent headlines used for scoring
      ts         str    ISO timestamp of last update
    """
    try:
        import json
        from src.core.redis import get_redis
        redis = get_redis()
        safe_sym = symbol.replace("/", "_").replace("=", "_")
        raw = await redis.get(f"sentiment:{safe_sym}")
        if raw:
            data = json.loads(raw)
            return {"symbol": symbol, **data}
        return {
            "symbol": symbol,
            "score": 0.0,
            "label": "NEUTRAL",
            "confidence": 0.0,
            "headlines": [],
            "ts": None,
            "note": "no_data_yet",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/carry/{symbol}")
async def get_carry(symbol: str) -> dict:
    """
    Return current carry signal for a symbol.

    CarryAgent writes to Redis after each cycle.
    Key: carry:{symbol}  (TTL 3600s)

    For commodity futures: roll yield (backwardation = positive carry).
    For crypto:            funding rate (inverted — high funding = SHORT signal).

    Returns:
      carry_yield  float   annualized carry yield (positive = favorable)
      direction    str     LONG | SHORT | NEUTRAL
      confidence   float   [0.0, 1.0]
      source       str     "roll_yield" | "funding_rate" | "none"
      ts           str     ISO timestamp of last update
    """
    try:
        import json
        from src.core.redis import get_redis
        redis = get_redis()
        safe_sym = symbol.replace("/", "_").replace("=", "_")
        raw = await redis.get(f"carry:{safe_sym}")
        if raw:
            data = json.loads(raw)
            return {"symbol": symbol, **data}
        return {
            "symbol": symbol,
            "carry_yield": 0.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "source": "none",
            "ts": None,
            "note": "no_data_yet",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
