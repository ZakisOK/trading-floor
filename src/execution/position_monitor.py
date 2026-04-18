"""
Real-time position monitor — runs every 5 seconds.
Independently checks all open positions against live prices.
Does NOT wait for the agent cycle. Fires exits immediately.

This is what separates a real trading firm from a scheduled job.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, UTC

import structlog

from src.execution.broker import paper_broker
from src.core.security import is_kill_switch_active
from src.core.redis import get_redis
from src.streams.producer import produce, produce_audit
from src.streams import topology

logger = structlog.get_logger()

MONITOR_INTERVAL = 5          # seconds between each sweep
TRAILING_STOP_THRESHOLD = 0.05  # 5% profit triggers trail to breakeven
DEFAULT_STOP_PCT = 0.03       # 3% default stop if position has none
DEFAULT_TARGET_PCT = 0.06     # 6% default target if position has none


async def _fetch_live_price(symbol: str) -> float | None:
    """Fetch live mid price via CCXT REST (binance ticker)."""
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = await exchange.fetch_ticker(symbol)
        await exchange.close()
        # Prefer last traded price; fall back to mid of bid/ask
        price = ticker.get("last") or (
            (ticker.get("bid", 0) + ticker.get("ask", 0)) / 2
        )
        return float(price) if price else None
    except Exception as e:
        logger.error("price_fetch_failed", symbol=symbol, error=str(e))
        return None


async def _check_position(pos: dict, current_price: float) -> str | None:
    """
    Evaluate stop/target/trailing for a position.
    Returns 'stop', 'target', or None.
    Side-effect: updates trailing_stop in-place when threshold is crossed.
    """
    symbol = pos["symbol"]
    avg_price = pos["avg_price"]
    stop_loss = pos.get("stop_loss") or avg_price * (1 - DEFAULT_STOP_PCT)
    take_profit = pos.get("take_profit") or avg_price * (1 + DEFAULT_TARGET_PCT)
    trailing_stop: float | None = pos.get("trailing_stop")

    pnl_pct = (current_price - avg_price) / avg_price

    # Trailing stop: position up >= 5% → trail stop to breakeven (avg_price)
    if pnl_pct >= TRAILING_STOP_THRESHOLD:
        new_trail = avg_price  # lock in breakeven
        if trailing_stop is None or new_trail > trailing_stop:
            await paper_broker.update_position_field(symbol, "trailing_stop", new_trail)
            trailing_stop = new_trail
            logger.info(
                "trailing_stop_activated",
                symbol=symbol,
                trailing_stop=round(new_trail, 6),
                pnl_pct=f"{pnl_pct:.1%}",
            )
    # Effective stop is the tighter of static stop and trailing stop
    effective_stop = max(stop_loss, trailing_stop) if trailing_stop else stop_loss

    if current_price <= effective_stop:
        return "stop"
    if current_price >= take_profit:
        return "target"
    return None


async def _exit_position(pos: dict, current_price: float, reason: str) -> None:
    """Execute a market SELL to close the position, then emit audit + PnL."""
    symbol = pos["symbol"]
    quantity = pos["quantity"]
    avg_price = pos["avg_price"]
    redis = get_redis()

    logger.warning(
        "position_exit_triggered",
        symbol=symbol, reason=reason,
        current_price=round(current_price, 6),
        avg_price=round(avg_price, 6),
        pnl_pct=f"{(current_price - avg_price) / avg_price:.2%}",
    )

    order = await paper_broker.submit_order(
        symbol=symbol, side="SELL", quantity=quantity,
        current_price=current_price,
        agent_id="position_monitor",
        strategy=f"auto_exit:{reason}",
    )

    pnl = (current_price - avg_price) * quantity

    await produce(topology.PNL, {
        "symbol": symbol, "reason": reason,
        "entry_price": str(avg_price), "exit_price": str(current_price),
        "quantity": str(quantity), "pnl": str(round(pnl, 6)),
        "order_id": order.order_id,
    }, redis=redis)

    await produce_audit("position_exit", "position_monitor", {
        "symbol": symbol, "reason": reason,
        "pnl": round(pnl, 6), "order_id": order.order_id,
    }, redis=redis)


async def _process_position(pos: dict) -> None:
    """Fetch live price, log the check, and fire exit if a level is hit."""
    symbol = pos["symbol"]
    redis = get_redis()

    price = await _fetch_live_price(symbol)
    if price is None:
        return

    # Audit every check so the Redis stream has a full trail
    await produce(topology.AUDIT, {
        "event": "position_monitor_check",
        "symbol": symbol,
        "current_price": str(round(price, 6)),
        "avg_price": str(round(pos["avg_price"], 6)),
        "stop_loss": str(pos.get("stop_loss") or ""),
        "take_profit": str(pos.get("take_profit") or ""),
        "trailing_stop": str(pos.get("trailing_stop") or ""),
    }, redis=redis)

    action = await _check_position(pos, price)
    if action in ("stop", "target"):
        await _exit_position(pos, price, action)


async def _flatten_all_for_kill_switch() -> None:
    """Close every open position immediately — kill switch is active."""
    positions = await paper_broker.get_positions()
    if not positions:
        return
    logger.critical("kill_switch_flattening_all", count=len(positions))
    tasks = []
    for pos in positions:
        price = await _fetch_live_price(pos["symbol"])
        if price:
            tasks.append(_exit_position(pos, price, "kill_switch"))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def run() -> None:
    """
    Main monitor loop.
    Runs every 5 seconds. Checks kill switch first, then sweeps all open positions
    concurrently via asyncio.gather — one price fetch + check per position.
    """
    logger.info(
        "position_monitor_started",
        interval_s=MONITOR_INTERVAL,
        trailing_stop_threshold=f"{TRAILING_STOP_THRESHOLD:.0%}",
        default_stop_pct=f"{DEFAULT_STOP_PCT:.0%}",
        default_target_pct=f"{DEFAULT_TARGET_PCT:.0%}",
    )
    while True:
        try:
            if await is_kill_switch_active():
                await _flatten_all_for_kill_switch()
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            positions = await paper_broker.get_positions()
            if positions:
                await asyncio.gather(
                    *[_process_position(pos) for pos in positions],
                    return_exceptions=True,
                )
            logger.debug("position_monitor_sweep", open_positions=len(positions))

        except Exception as e:
            logger.error("position_monitor_unhandled_error", error=str(e))

        await asyncio.sleep(MONITOR_INTERVAL)
