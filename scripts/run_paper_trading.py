"""Paper trading scheduler — runs multi-agent cycles every 5 minutes."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, UTC
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger()

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
CYCLE_INTERVAL = 300  # 5 minutes
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
        defaults = {"BTC/USDT": 65000.0, "ETH/USDT": 3200.0, "SOL/USDT": 145.0}
        return defaults.get(symbol, 100.0)


async def run_cycle(symbol: str) -> None:
    from src.agents.sage import run_trading_cycle
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


async def main() -> None:
    import signal as _signal
    _signal.signal(_signal.SIGINT, _handle_signal)
    _signal.signal(_signal.SIGTERM, _handle_signal)

    logger.info("paper_trading_started", symbols=SYMBOLS, interval_s=CYCLE_INTERVAL)

    cycle_count = 0
    while not _shutdown:
        cycle_count += 1
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        logger.info("starting_cycle", n=cycle_count, ts=ts)

        try:
            from src.core.security import is_kill_switch_active
            if await is_kill_switch_active():
                logger.warning("kill_switch_active_skipping_cycle")
                await asyncio.sleep(60)
                continue
        except Exception as e:
            logger.error("kill_switch_check_failed", error=str(e))

        tasks = [run_cycle(sym) for sym in SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, res in zip(SYMBOLS, results):
            if isinstance(res, Exception):
                logger.error("cycle_error", symbol=sym, error=str(res))

        logger.info("cycle_batch_complete", n=cycle_count, next_in_s=CYCLE_INTERVAL)
        await asyncio.sleep(CYCLE_INTERVAL)

    logger.info("paper_trading_stopped", cycles_run=cycle_count)


if __name__ == "__main__":
    asyncio.run(main())
