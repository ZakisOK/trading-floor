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

router = APIRouter(prefix="/market", tags=["market"])

_poly_feed = PolymarketFeed()

_VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"}


@router.get("/ohlcv/{symbol}", response_model=list[OHLCVResponse])
async def get_ohlcv(
    symbol: str,
    exchange: Annotated[str, Query()] = "binance",
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
        for row in reversed(rows)  # Return chronological order
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
        base = parts[0] if len(parts) > 1 else sym
        quote = parts[1] if len(parts) > 1 else ""
        symbols.append(
            SymbolInfo(
                symbol=sym,
                exchange=exch,
                asset_class=asset_class,
                base=base,
                quote=quote,
            )
        )
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
