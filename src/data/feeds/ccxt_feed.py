"""CCXT Pro market data feed — WebSocket OHLCV streaming with REST fallback."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import ccxt.pro as ccxtpro
import structlog

from src.data.feeds.base import BaseFeed, OnBarCallback
from src.data.schemas.market import OHLCVSchema

logger = structlog.get_logger()


class CCXTFeed(BaseFeed):
    """Streams OHLCV candles from a CCXT Pro exchange via WebSocket.

    Example usage:
        feed = CCXTFeed("binance", ["BTC/USDT", "ETH/USDT"], ["1m", "1h"])
        await feed.connect()
        await feed.stream(on_bar)  # blocks until disconnect()
    """

    def __init__(
        self,
        exchange_id: str,
        symbols: list[str],
        timeframes: list[str],
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self.exchange_id = exchange_id
        self.symbols = symbols
        self.timeframes = timeframes
        self._exchange: Any = None
        self._running = False
        self._api_key = api_key
        self._api_secret = api_secret

    async def connect(self) -> None:
        exchange_class = getattr(ccxtpro, self.exchange_id)
        self._exchange = exchange_class(
            {
                "apiKey": self._api_key or None,
                "secret": self._api_secret or None,
                "enableRateLimit": True,
            }
        )
        self._running = True
        logger.info("ccxt_feed_connected", exchange=self.exchange_id)

    async def disconnect(self) -> None:
        self._running = False
        if self._exchange is not None:
            await self._exchange.close()
        logger.info("ccxt_feed_disconnected", exchange=self.exchange_id)

    async def subscribe(self, symbols: list[str]) -> None:
        for sym in symbols:
            if sym not in self.symbols:
                self.symbols.append(sym)

    async def stream(self, on_bar: OnBarCallback) -> None:
        """Start streaming OHLCV for all symbol/timeframe pairs concurrently."""
        tasks = [
            asyncio.create_task(self._watch_ohlcv(symbol, tf, on_bar))
            for symbol in self.symbols
            for tf in self.timeframes
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()

    async def _watch_ohlcv(self, symbol: str, timeframe: str, on_bar: OnBarCallback) -> None:
        while self._running:
            try:
                candles: list[list[Any]] = await self._exchange.watch_ohlcv(
                    symbol, timeframe
                )
                for candle in candles:
                    ts_ms, o, h, lo, c, v = candle
                    ohlcv = OHLCVSchema(
                        symbol=symbol,
                        exchange=self.exchange_id,
                        timeframe=timeframe,
                        ts=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                        open=Decimal(str(o)),
                        high=Decimal(str(h)),
                        low=Decimal(str(lo)),
                        close=Decimal(str(c)),
                        volume=Decimal(str(v)),
                    )
                    await on_bar(ohlcv)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "ccxt_watch_error",
                    symbol=symbol,
                    timeframe=timeframe,
                    error=str(e),
                )
                await asyncio.sleep(5)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[OHLCVSchema]:
        """Fetch historical OHLCV via REST. Used for initial backfill."""
        if self._exchange is None:
            await self.connect()

        since_ms = int(since.timestamp() * 1000) if since else None
        candles: list[list[Any]] = await self._exchange.fetch_ohlcv(
            symbol, timeframe, since=since_ms, limit=limit
        )
        return [
            OHLCVSchema(
                symbol=symbol,
                exchange=self.exchange_id,
                timeframe=timeframe,
                ts=datetime.fromtimestamp(c[0] / 1000, tz=UTC),
                open=Decimal(str(c[1])),
                high=Decimal(str(c[2])),
                low=Decimal(str(c[3])),
                close=Decimal(str(c[4])),
                volume=Decimal(str(c[5])),
            )
            for c in candles
        ]
