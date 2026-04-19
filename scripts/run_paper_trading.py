"""Paper trading scheduler — XRP every 2 min, other symbols every 5 min.

New in v2:
  - macro_refresh_loop() runs every 30 minutes to keep FRED macro cache warm.
    All graph cycles read macro signals from Redis (zero per-cycle API cost).
  - Three concurrent loops run via asyncio.gather:
      xrp_loop()           — 2-minute cadence for XRP/USDT
      other_loop()         — 5-minute cadence for BTC, ETH, SOL
      macro_refresh_loop() — 30-minute FRED cache refresh (background)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger()

XRP_SYMBOLS          = ["XRP/USDT"]
CRYPTO_TIER1         = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
CRYPTO_TIER2         = ["ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT", "DOT/USDT", "UNI/USDT"]
COMMODITY_SYMBOLS    = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
SYMBOLS              = XRP_SYMBOLS + CRYPTO_TIER1 + CRYPTO_TIER2 + COMMODITY_SYMBOLS

XRP_CYCLE_INTERVAL   = 120    # 2 minutes  — XRP moves fast
OTHER_CYCLE_INTERVAL = 300    # 5 minutes
TIER2_CYCLE_INTERVAL = 600    # 10 minutes — lower-priority alts
COMMODITY_CYCLE_INTERVAL = 900  # 15 minutes — futures move slow
MACRO_REFRESH_INTERVAL = 1800  # 30 minutes — FRED data is slow-moving

_shutdown = False


def _handle_signal(signum, frame):  # type: ignore[type-arg]
    global _shutdown
    logger.info("shutdown_requested", signal=signum)
    _shutdown = True


async def _get_market_price(symbol: str) -> float:
    """Try to get a live price from Coinbase; fall back to a placeholder."""
    try:
        from src.data.feeds.price_source import fetch_price
        price = await fetch_price(symbol)
        if price:
            return price
    except Exception:
        pass
    defaults = {
        "XRP/USDT": 0.60,
        "BTC/USDT": 65000.0,
        "ETH/USDT": 3200.0,
        "SOL/USDT": 145.0,
    }
    return defaults.get(symbol, 100.0)


async def run_cycle(symbol: str) -> None:
    from datetime import UTC, datetime
    from src.agents.sage import run_trading_cycle
    from src.core.redis import get_redis
    from src.streams.producer import produce
    from src.streams import topology

    redis = get_redis()
    started_at = datetime.now(UTC)
    await redis.set(f"schedule:started:{symbol}", started_at.isoformat())

    price = await _get_market_price(symbol)
    market_data = {"close": price, "volume": 1000.0}
    result = await run_trading_cycle(symbol, market_data)

    finished_at = datetime.now(UTC)
    duration_s = (finished_at - started_at).total_seconds()

    # Track for schedule endpoint + recent completions list
    await redis.set(f"schedule:last_run:{symbol}", finished_at.isoformat())
    summary = {
        "symbol": symbol,
        "finished_at": finished_at.isoformat(),
        "duration_s": round(duration_s, 2),
        "decision": result.get("final_decision") or "NEUTRAL",
        "signals": len(result.get("signals", []) or []),
        "approved": bool(result.get("risk_approved")),
    }
    # Keep last 30 completions
    await redis.lpush("schedule:completions", json.dumps(summary))
    await redis.ltrim("schedule:completions", 0, 29)
    await produce(topology.AUDIT, {"event": "cycle_complete", **{k: str(v) for k, v in summary.items()}}, redis=redis)

    logger.info(
        "cycle_complete",
        symbol=symbol, price=price, duration_s=duration_s,
        regime=result.get("market_regime"),
        signals=summary["signals"],
        effective_signals=result.get("effective_signal_count"),
        approved=summary["approved"],
        decision=summary["decision"],
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


async def _kill_active() -> bool:
    try:
        from src.core.security import is_kill_switch_active
        return await is_kill_switch_active()
    except Exception as e:
        logger.error("kill_switch_check_failed", error=str(e))
        return False


async def _symbol_loop(name: str, symbols: list[str], interval_s: int) -> None:
    """Generic loop: iterate symbols, run_cycle each, sleep, repeat."""
    logger.info(f"{name}_loop_started", symbols=symbols, interval_s=interval_s)
    while not _shutdown:
        if await _kill_active():
            logger.warning(f"{name}_loop_kill_switch_active")
            await asyncio.sleep(60)
            continue
        tasks = [run_cycle(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, res in zip(symbols, results):
            if isinstance(res, Exception):
                logger.error(f"{name}_cycle_error", symbol=sym, error=str(res))
        await asyncio.sleep(interval_s)


async def other_loop() -> None:
    """Tier-1 crypto (BTC, ETH, SOL) every 5 min."""
    await _symbol_loop("crypto_tier1", CRYPTO_TIER1, OTHER_CYCLE_INTERVAL)


async def tier2_loop() -> None:
    """Tier-2 alts every 10 min."""
    await _symbol_loop("crypto_tier2", CRYPTO_TIER2, TIER2_CYCLE_INTERVAL)


async def commodity_loop() -> None:
    """Commodity futures every 15 min."""
    await _symbol_loop("commodities", COMMODITY_SYMBOLS, COMMODITY_CYCLE_INTERVAL)


async def macro_refresh_loop() -> None:
    """
    Background macro cache refresh — runs every 30 minutes.

    MacroAnalystAgent.refresh_cache() fetches FRED indicators
    (VIX, yield curve, DXY, credit spreads) and writes a snapshot
    to Redis key macro:snapshot:latest (TTL 1800s).

    All graph cycles read this cache — they never hit FRED directly.
    This means macro context costs zero per-cycle latency.
    """
    from src.agents.macro_analyst import MacroAnalystAgent
    _macro = MacroAnalystAgent()
    logger.info("macro_refresh_loop_started", interval_s=MACRO_REFRESH_INTERVAL)

    if not hasattr(_macro, "refresh_cache"):
        logger.warning("macro_refresh_skipped", reason="MacroAnalystAgent.refresh_cache() not implemented")
        return

    while not _shutdown:
        try:
            await _macro.refresh_cache()
            logger.info("macro_cache_refreshed")
        except Exception as e:
            logger.error("macro_refresh_failed", error=str(e))

        await asyncio.sleep(MACRO_REFRESH_INTERVAL)


async def main() -> None:
    import signal as _signal
    _signal.signal(_signal.SIGINT,  _handle_signal)
    _signal.signal(_signal.SIGTERM, _handle_signal)

    logger.info(
        "paper_trading_started",
        xrp_symbols=XRP_SYMBOLS,
        xrp_interval_s=XRP_CYCLE_INTERVAL,
        tier1_symbols=CRYPTO_TIER1,
        tier2_symbols=CRYPTO_TIER2,
        commodity_symbols=COMMODITY_SYMBOLS,
        macro_refresh_interval_s=MACRO_REFRESH_INTERVAL,
    )

    # Concurrent loops spanning the full firm coverage
    await asyncio.gather(
        xrp_loop(),
        other_loop(),
        tier2_loop(),
        commodity_loop(),
        macro_refresh_loop(),
    )

    logger.info("paper_trading_stopped")


if __name__ == "__main__":
    asyncio.run(main())
