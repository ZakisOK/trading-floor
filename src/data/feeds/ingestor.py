"""Market data ingestor — reads stream:market_data, upserts to TimescaleDB.

Public helpers:
    publish_ohlcv(ohlcv) — publish a parsed OHLCVSchema to stream:market_data
    publish_bar(ohlcv)   — alias of publish_ohlcv, clearer name for schedulers
    persist_ohlcv(ohlcv) — optional direct upsert into the Timescale hypertable
                           (use when you want to skip the stream round-trip)
"""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.data.models.market import OHLCV
from src.data.schemas.market import OHLCVSchema
from src.streams.consumer import BaseConsumer
from src.streams.producer import produce
from src.streams.topology import MARKET_DATA

logger = structlog.get_logger()


async def publish_ohlcv(ohlcv: OHLCVSchema) -> None:
    """Publish an OHLCV bar to stream:market_data."""
    await produce(
        MARKET_DATA,
        {
            "symbol": ohlcv.symbol,
            "exchange": ohlcv.exchange,
            "timeframe": ohlcv.timeframe,
            "ts": ohlcv.ts.isoformat(),
            "open": str(ohlcv.open),
            "high": str(ohlcv.high),
            "low": str(ohlcv.low),
            "close": str(ohlcv.close),
            "volume": str(ohlcv.volume),
        },
    )


# Public alias used by src.schedulers.cycle_runner so scheduler code reads cleanly.
publish_bar = publish_ohlcv


async def persist_ohlcv(
    ohlcv: OHLCVSchema,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Upsert a single OHLCV bar into TimescaleDB.

    Mirrors MarketDataIngestor.handle() but callable from any code path that
    already has an OHLCVSchema in hand (for example the Alpaca feed callback
    in the scheduler). Uses ON CONFLICT DO NOTHING against uq_ohlcv_bar to
    remain idempotent for replays.
    """
    async with session_factory() as session:
        stmt = (
            insert(OHLCV)
            .values(
                symbol=ohlcv.symbol,
                exchange=ohlcv.exchange,
                timeframe=ohlcv.timeframe,
                ts=ohlcv.ts,
                open=ohlcv.open,
                high=ohlcv.high,
                low=ohlcv.low,
                close=ohlcv.close,
                volume=ohlcv.volume,
            )
            .on_conflict_do_nothing(constraint="uq_ohlcv_bar")
        )
        await session.execute(stmt)
        await session.commit()


class MarketDataIngestor(BaseConsumer):
    """Consumes stream:market_data and upserts OHLCV rows into TimescaleDB.

    Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING with the unique constraint
    uq_ohlcv_bar (symbol, exchange, timeframe, ts) to deduplicate incoming bars.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        consumer_name: str = "ingestor-0",
    ) -> None:
        from src.core.redis import get_redis

        super().__init__(
            stream=MARKET_DATA,
            group="cg:market_analysts",
            consumer_name=consumer_name,
            redis=get_redis(),
        )
        self._session_factory = session_factory

    async def handle(self, msg_id: str, fields: dict[str, Any]) -> None:
        try:
            ohlcv = _parse_ohlcv(fields)
        except (KeyError, ValueError) as e:
            logger.warning("ingestor_parse_error", msg_id=msg_id, error=str(e))
            return

        async with self._session_factory() as session:
            stmt = (
                insert(OHLCV)
                .values(
                    symbol=ohlcv.symbol,
                    exchange=ohlcv.exchange,
                    timeframe=ohlcv.timeframe,
                    ts=ohlcv.ts,
                    open=ohlcv.open,
                    high=ohlcv.high,
                    low=ohlcv.low,
                    close=ohlcv.close,
                    volume=ohlcv.volume,
                )
                .on_conflict_do_nothing(constraint="uq_ohlcv_bar")
            )
            await session.execute(stmt)
            await session.commit()

        logger.debug(
            "ohlcv_ingested",
            symbol=ohlcv.symbol,
            exchange=ohlcv.exchange,
            timeframe=ohlcv.timeframe,
            ts=ohlcv.ts.isoformat(),
        )


def _parse_ohlcv(fields: dict[str, Any]) -> OHLCVSchema:
    """Parse Redis Stream fields into an OHLCVSchema."""
    ts_raw = fields["ts"]
    ts = datetime.fromisoformat(ts_raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    return OHLCVSchema(
        symbol=fields["symbol"],
        exchange=fields["exchange"],
        timeframe=fields["timeframe"],
        ts=ts,
        open=Decimal(fields["open"]),
        high=Decimal(fields["high"]),
        low=Decimal(fields["low"]),
        close=Decimal(fields["close"]),
        volume=Decimal(fields["volume"]),
    )


def ohlcv_to_ws_message(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Convert stream fields to a WebSocket-ready dict. Returns None on parse error."""
    try:
        ohlcv = _parse_ohlcv(fields)
        return {
            "type": "ohlcv",
            "symbol": ohlcv.symbol,
            "exchange": ohlcv.exchange,
            "timeframe": ohlcv.timeframe,
            "ts": ohlcv.ts.isoformat(),
            "open": float(ohlcv.open),
            "high": float(ohlcv.high),
            "low": float(ohlcv.low),
            "close": float(ohlcv.close),
            "volume": float(ohlcv.volume),
        }
    except (KeyError, ValueError):
        return None
