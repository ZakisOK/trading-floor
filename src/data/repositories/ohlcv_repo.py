"""OHLCV repository — async queries against TimescaleDB."""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.market import OHLCV, OHLCVBar


class OHLCVRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_bars(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int = 10_000,
    ) -> list[OHLCVBar]:
        stmt = (
            select(OHLCV)
            .where(
                OHLCV.symbol == symbol,
                OHLCV.exchange == exchange,
                OHLCV.timeframe == timeframe,
                OHLCV.ts >= start,
                OHLCV.ts <= end,
            )
            .order_by(OHLCV.ts.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [OHLCVBar.from_orm(r) for r in rows]

    async def latest_bar(
        self, symbol: str, exchange: str, timeframe: str
    ) -> OHLCVBar | None:
        stmt = (
            select(OHLCV)
            .where(
                OHLCV.symbol == symbol,
                OHLCV.exchange == exchange,
                OHLCV.timeframe == timeframe,
            )
            .order_by(OHLCV.ts.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return OHLCVBar.from_orm(row) if row else None
