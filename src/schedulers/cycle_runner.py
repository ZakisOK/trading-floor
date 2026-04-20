"""Phase 1 cycle scheduler.

Runs two long-lived async tasks:

    1. run_alpaca_feed_loop  — consumes Alpaca WebSocket bars for the equities
       universe, persists each bar to TimescaleDB, publishes it on
       stream:market_data, and caches the latest bar per symbol.
    2. run_cycle_loop        — every 60 seconds, walks the equities + crypto
       universes and invokes sage.run_trading_cycle(symbol, market_data) using
       the last known bar.

This module is the Docker entrypoint for the ``scheduler`` service. Keep it
thin; business logic belongs in agents / execution modules.
"""
from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.agents.sage import run_trading_cycle
from src.core.config import settings
from src.data.feeds.alpaca_feed import AlpacaFeed
from src.data.feeds.feed_manager import DEFAULT_CRYPTO_SYMBOLS
from src.data.feeds.ingestor import persist_ohlcv, publish_bar
from src.data.schemas.market import OHLCVSchema

logger = structlog.get_logger()

EQUITIES_UNIVERSE: list[str] = ["SPY", "QQQ", "NVDA", "TSLA", "AMD", "META"]
CRYPTO_UNIVERSE: list[str] = list(DEFAULT_CRYPTO_SYMBOLS)

CYCLE_INTERVAL_SECONDS: int = 60


def _alpaca_paper_flag() -> bool:
    """Read the paper-trading flag. Stream A will add alpaca_paper_trade to Settings."""
    value = getattr(settings, "alpaca_paper_trade", None)
    if value is None:
        value = os.getenv("ALPACA_PAPER_TRADE", "true")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no")


def _alpaca_key() -> str:
    return getattr(settings, "alpaca_api_key", "") or os.getenv("ALPACA_API_KEY", "")


def _alpaca_secret() -> str:
    return getattr(settings, "alpaca_secret_key", "") or os.getenv("ALPACA_SECRET_KEY", "")


class CycleRunner:
    """Owns the Alpaca feed task, the trading-cycle task, and the shared
    last-bar cache. Call start() to launch; call stop() to shut down cleanly."""

    def __init__(
        self,
        equities: list[str] | None = None,
        crypto: list[str] | None = None,
        cycle_interval: int = CYCLE_INTERVAL_SECONDS,
    ) -> None:
        self.equities: list[str] = list(equities or EQUITIES_UNIVERSE)
        self.crypto: list[str] = list(crypto or CRYPTO_UNIVERSE)
        self.cycle_interval: int = cycle_interval

        self._last_bar: dict[str, dict[str, Any]] = {}
        self._feed: AlpacaFeed | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event: asyncio.Event = asyncio.Event()

        self._session_factory = None  # lazy — avoid import side effects at module load
        self.api_key = _alpaca_key()
        self.api_secret = _alpaca_secret()
        self.paper = _alpaca_paper_flag()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        logger.info(
            "cycle_runner_starting",
            equities=self.equities,
            crypto=self.crypto,
            paper=self.paper,
            interval_s=self.cycle_interval,
        )
        self._tasks = [
            asyncio.create_task(self._run_alpaca_feed_loop(), name="alpaca_feed_loop"),
            asyncio.create_task(self._run_cycle_loop(), name="cycle_loop"),
        ]
        await self._stop_event.wait()

    async def stop(self) -> None:
        if self._stop_event.is_set():
            return
        logger.info("cycle_runner_stopping")
        self._stop_event.set()

        if self._feed is not None:
            with suppress(Exception):
                await self._feed.disconnect()

        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
        logger.info("cycle_runner_stopped")

    # ------------------------------------------------------------------
    # Alpaca feed loop
    # ------------------------------------------------------------------
    async def _run_alpaca_feed_loop(self) -> None:
        if not self.api_key or not self.api_secret:
            logger.warning(
                "alpaca_feed_disabled_missing_credentials",
                msg="Set alpaca_api_key / alpaca_secret_key to enable the equities feed.",
            )
            return

        self._feed = AlpacaFeed(
            api_key=self.api_key,
            api_secret=self.api_secret,
            symbols=self.equities,
            paper=self.paper,
        )
        try:
            await self._feed.connect()
            logger.info("alpaca_feed_streaming", symbols=self.equities)
            await self._feed.stream(self._on_bar)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("alpaca_feed_loop_error", error=str(exc))

    async def _on_bar(self, ohlcv: OHLCVSchema) -> None:
        """Persist, publish, and cache each incoming Alpaca bar."""
        # Cache — cycle loop reads from this in-memory dict.
        self._last_bar[ohlcv.symbol] = _ohlcv_to_cache_entry(ohlcv)

        # Persist to Timescale (best-effort; don't crash the feed on DB issues).
        session_factory = self._get_session_factory()
        if session_factory is not None:
            try:
                await persist_ohlcv(ohlcv, session_factory)
            except Exception as exc:  # noqa: BLE001
                logger.warning("persist_ohlcv_failed", symbol=ohlcv.symbol, error=str(exc))

        # Publish on stream:market_data (authoritative hand-off to ingestor group).
        try:
            await publish_bar(ohlcv)
        except Exception as exc:  # noqa: BLE001
            logger.warning("publish_bar_failed", symbol=ohlcv.symbol, error=str(exc))

    # ------------------------------------------------------------------
    # Trading cycle loop
    # ------------------------------------------------------------------
    async def _run_cycle_loop(self) -> None:
        """Every cycle_interval seconds, run a trading cycle per symbol."""
        # Small warmup so feeds have a chance to populate the cache.
        await asyncio.sleep(min(5, self.cycle_interval))

        while not self._stop_event.is_set():
            started = datetime.now(UTC)
            for symbol in self.equities + self.crypto:
                if self._stop_event.is_set():
                    break
                await self._run_one_cycle(symbol)

            elapsed = (datetime.now(UTC) - started).total_seconds()
            sleep_for = max(0.0, self.cycle_interval - elapsed)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)

    async def _run_one_cycle(self, symbol: str) -> None:
        market_data = dict(self._last_bar.get(symbol) or {"symbol": symbol})
        # If the WebSocket cache has no bar for this symbol (market closed,
        # crypto not on the equities feed, cold start), fall back to a REST
        # fetch so agents have SOMETHING to analyze. Without a price, Claude
        # correctly returns NEUTRAL 0.0 on every cycle and the pipeline never
        # produces a signal.
        if not market_data.get("close") and not market_data.get("price"):
            try:
                from src.data.feeds.price_source import fetch_price

                price = await fetch_price(symbol)
                if price:
                    market_data["price"] = float(price)
                    market_data["close"] = float(price)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cycle_price_fetch_failed", symbol=symbol, error=str(exc)
                )

        try:
            result = await run_trading_cycle(symbol, market_data)
            logger.info(
                "cycle_ran",
                symbol=symbol,
                approved=result.get("risk_approved"),
                confidence=result.get("confidence"),
                signals=len(result.get("signals", [])),
                price=market_data.get("close"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("cycle_error", symbol=symbol, error=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_session_factory(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory
        try:
            from src.core.database import AsyncSessionLocal

            self._session_factory = AsyncSessionLocal
        except Exception as exc:  # noqa: BLE001
            logger.warning("session_factory_unavailable", error=str(exc))
            self._session_factory = None
        return self._session_factory


def _ohlcv_to_cache_entry(ohlcv: OHLCVSchema) -> dict[str, Any]:
    """Flatten OHLCVSchema to JSON-friendly dict (Decimals stringified)."""
    return {
        "symbol": ohlcv.symbol,
        "exchange": ohlcv.exchange,
        "timeframe": ohlcv.timeframe,
        "ts": ohlcv.ts.isoformat(),
        "open": str(ohlcv.open),
        "high": str(ohlcv.high),
        "low": str(ohlcv.low),
        "close": str(ohlcv.close),
        "volume": str(ohlcv.volume),
        "price": float(ohlcv.close) if isinstance(ohlcv.close, Decimal) else ohlcv.close,
    }


async def main() -> None:
    """Container entrypoint. Installs signal handlers and blocks until stopped."""
    runner = CycleRunner()
    loop = asyncio.get_running_loop()

    def _trigger_shutdown(sig_name: str) -> None:
        logger.info("signal_received", signal=sig_name)
        asyncio.create_task(runner.stop())

    # Windows event loops don't support add_signal_handler on ProactorEventLoop.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger_shutdown, sig.name)
        except (NotImplementedError, RuntimeError):
            # Fallback: rely on KeyboardInterrupt / process termination.
            pass

    try:
        await runner.start()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.stop()


if __name__ == "__main__":
    asyncio.run(main())
