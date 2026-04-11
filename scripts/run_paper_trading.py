"""Paper trading scheduler — XRP runs every 2 minutes, other symbols every 5 minutes."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, UTC
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger()

# XRP gets a dedicated faster cycle — it's the primary asset
XRP_SYMBOLS = ["XRP/USDT"]
OTHER_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# Keep SYMBOLS for backwards-compatibility references
SYMBOLS = XRP_SYMBOLS + OTHER_SYMBOLS

XRP_CYCLE_INTERVAL = 120    # 2 minutes — XRP moves fast
OTHER_CYCLE_INTERVAL = 300  # 5 minutes

_shutdown = False


def _handle_signal(signum, frame):  # type: ignore[type-arg]
    global _shutdown
    logger.info("shutdown_requested", signal=signum)
    _shutdown = True


async def _get_market_price(symbol: str) -> float:
    """Try to get a live price; fall back to a placeholder."""
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.binance()
        ticker = await exchange.fetch_ticker(symbol)
        await exchange.close()
        return float(ticker["last"])
    except Exception:
        # Fallback prices for when exchange is unreachable
        defaults = {
            "XRP/USDT": 0.60,
            "BTC/USDT": 65000.0,
            "ETH/USDT": 3200.0,
            "SOL/USDT": 145.0,
        }
        return defaults.get(symbol, 100.0)


async def run_cycle(symbol: str) -> None:
    from src.agents.graph import run_trading_cycle
    price = await _get_market_price(symbol)
    market_data = {"close": price, "volume": 1000.0}
    result = await run_trading_cycle(symbol, market_data)
    logger.info(
        "cycle_complete",
        symbol=symbol,
        price=price,
        signals=len(result.get("signals", [])),
        approved=result.get("risk_approved"),
        decision=result.get("final_decision"),
    )


async def xrp_loop() -> None:
    """Dedicated XRP trading loop — runs every 2 minutes."""
    logger.info("xrp_loop_started", symbols=XRP_SYMBOLS, interval_s=XRP_CYCLE_INTERVAL)
    while not _shutdown:
        try:
            from src.core.security import is_kill_switch_active
            if await is_kill_switch_active():
                logger.warning("kill_switch_active_skipping_xrp_cycle")
                await asyncio.sleep(30)
                continue
        except Exception as e:
            logger.error("kill_switch_check_failed", error=str(e))

        tasks = [run_cycle(sym) for sym in XRP_SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, res in zip(XRP_SYMBOLS, results):
            if isinstance(res, Exception):
                logger.error("xrp_cycle_error", symbol=sym, error=str(res))

        await asyncio.sleep(XRP_CYCLE_INTERVAL)


async def other_loop() -> None:
    """Standard loop for non-XRP symbols — runs every 5 minutes."""
    logger.info("other_loop_started", symbols=OTHER_SYMBOLS, interval_s=OTHER_CYCLE_INTERVAL)
    while not _shutdown:
        try:
            from src.core.security import is_kill_switch_active
            if await is_kill_switch_active():
                logger.warning("kill_switch_active_skipping_cycle")
                await asyncio.sleep(60)
                continue
        except Exception as e:
            logger.error("kill_switch_check_failed", error=str(e))

        tasks = [run_cycle(sym) for sym in OTHER_SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, res in zip(OTHER_SYMBOLS, results):
            if isinstance(res, Exception):
                logger.error("cycle_error", symbol=sym, error=str(res))

        await asyncio.sleep(OTHER_CYCLE_INTERVAL)


async def main() -> None:
    import signal as _signal
    _signal.signal(_signal.SIGINT, _handle_signal)
    _signal.signal(_signal.SIGTERM, _handle_signal)

    logger.info(
        "paper_trading_started",
        xrp_symbols=XRP_SYMBOLS,
        xrp_interval_s=XRP_CYCLE_INTERVAL,
        other_symbols=OTHER_SYMBOLS,
        other_interval_s=OTHER_CYCLE_INTERVAL,
    )

    # Run both loops concurrently — XRP at 2m cadence, others at 5m
    await asyncio.gather(xrp_loop(), other_loop())

    logger.info("paper_trading_stopped")


if __name__ == "__main__":
    asyncio.run(main())
