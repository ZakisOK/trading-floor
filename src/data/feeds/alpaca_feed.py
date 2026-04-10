"""Alpaca market data feed — equity bars via WebSocket + REST."""
import asyncio
import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.data.feeds.base import BaseFeed, OnBarCallback
from src.data.schemas.market import OHLCVSchema

logger = structlog.get_logger()

_ALPACA_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "1h": "1Hour",
    "4h": "4Hour",
    "1D": "1Day",
}


class AlpacaFeed(BaseFeed):
    """Streams equity bars from Alpaca Markets via WebSocket.

    Uses alpaca-py's StockDataStream for real-time bars and
    StockHistoricalDataClient for historical REST backfill.

    Example usage:
        feed = AlpacaFeed(api_key, api_secret, ["SPY", "QQQ"])
        await feed.connect()
        await feed.stream(on_bar)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbols: list[str],
        timeframes: list[str] | None = None,
        paper: bool = True,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols
        self.timeframes = timeframes or ["1m"]
        self.paper = paper
        self._stream: Any = None
        self._historical_client: Any = None
        self._on_bar: OnBarCallback | None = None
        self._running = False

    async def connect(self) -> None:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.live import StockDataStream

            self._stream = StockDataStream(self.api_key, self.api_secret)
            self._historical_client = StockHistoricalDataClient(self.api_key, self.api_secret)
        except ImportError:
            logger.warning("alpaca_not_installed", msg="alpaca-py not installed, feed disabled")
            return

        self._running = True
        logger.info("alpaca_feed_connected", symbols=self.symbols)

    async def disconnect(self) -> None:
        self._running = False
        if self._stream is not None:
            with contextlib.suppress(Exception):
                await self._stream.stop_ws()
        logger.info("alpaca_feed_disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        for sym in symbols:
            if sym not in self.symbols:
                self.symbols.append(sym)

    async def stream(self, on_bar: OnBarCallback) -> None:
        """Subscribe to bar updates via Alpaca WebSocket."""
        if self._stream is None:
            logger.warning("alpaca_stream_not_initialized")
            return

        self._on_bar = on_bar

        async def handle_bar(bar: Any) -> None:
            ohlcv = OHLCVSchema(
                symbol=bar.symbol,
                exchange="alpaca",
                timeframe="1m",
                ts=bar.timestamp.replace(tzinfo=UTC) if bar.timestamp.tzinfo is None
                else bar.timestamp.astimezone(UTC),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=Decimal(str(bar.volume)),
            )
            await on_bar(ohlcv)

        self._stream.subscribe_bars(handle_bar, *self.symbols)
        with contextlib.suppress(asyncio.CancelledError):
            await self._stream.run()

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[OHLCVSchema]:
        """Fetch historical bars via Alpaca REST API."""
        if self._historical_client is None:
            return []

        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            alpaca_tf_str = _ALPACA_TIMEFRAME_MAP.get(timeframe, "1Min")
            tf_attr = alpaca_tf_str.replace("Min", "Minute").replace("Hour", "Hour")
            alpaca_tf = getattr(TimeFrame, tf_attr, TimeFrame.Minute)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=alpaca_tf,
                start=start,
                end=end,
                limit=limit,
            )
            bars = self._historical_client.get_stock_bars(request)
            result: list[OHLCVSchema] = []
            for bar in bars[symbol]:
                raw_ts = bar.timestamp
                ts = raw_ts.replace(tzinfo=UTC) if raw_ts.tzinfo is None else raw_ts.astimezone(UTC)
                result.append(
                    OHLCVSchema(
                        symbol=symbol,
                        exchange="alpaca",
                        timeframe=timeframe,
                        ts=ts,
                        open=Decimal(str(bar.open)),
                        high=Decimal(str(bar.high)),
                        low=Decimal(str(bar.low)),
                        close=Decimal(str(bar.close)),
                        volume=Decimal(str(bar.volume)),
                    )
                )
            return result
        except Exception as e:
            logger.error("alpaca_fetch_error", symbol=symbol, error=str(e))
            return []
